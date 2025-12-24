from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .exceptions import VMPoolExhaustedError, VMStartupError
from .rpc import RPCClient
from .types import CapabilityProfile, RPCRequest, RPCResponse, VMConfig

if TYPE_CHECKING:
    from .runner import FirecrackerRunner, SnapshotInfo

logger = logging.getLogger(__name__)


@dataclass
class VMInstance:
    vm_id: str
    cid: int
    port: int
    profile_key: str
    process: Any = None
    client: RPCClient | None = None
    call_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    tainted: bool = False

    def mark_used(self) -> None:
        self.call_count += 1
        self.last_used = time.time()


@dataclass
class PoolConfig:
    min_size: int = 1
    max_size: int = 10
    max_calls_per_vm: int = 100
    idle_timeout_sec: float = 300.0
    startup_timeout_sec: float = 30.0
    acquire_timeout_sec: float = 10.0


class VMWorkerPool:
    def __init__(
        self,
        profile: CapabilityProfile,
        profile_key: str,
        runner: FirecrackerRunner,
        vm_config: VMConfig,
        pool_config: PoolConfig | None = None,
    ):
        self.profile = profile
        self.profile_key = profile_key
        self._runner = runner
        self._vm_config = vm_config.with_profile(profile)
        self._pool_config = pool_config or PoolConfig()

        self._available: asyncio.Queue[VMInstance] = asyncio.Queue()
        self._in_use: dict[str, VMInstance] = {}
        self._all_vms: dict[str, VMInstance] = {}
        self._lock = asyncio.Lock()
        self._cid_counter = 100
        self._shutdown = False
        self._maintenance_task: asyncio.Task[None] | None = None
        self._snapshot: SnapshotInfo | None = None

    @property
    def total_count(self) -> int:
        return len(self._all_vms)

    @property
    def available_count(self) -> int:
        return self._available.qsize()

    @property
    def in_use_count(self) -> int:
        return len(self._in_use)

    async def start(self) -> None:
        logger.info(f"Starting VM pool for profile {self.profile_key}")

        # Provision snapshot if profile has dependencies
        if self.profile.dependencies:
            logger.info(f"Provisioning snapshot for dependencies: {self.profile.dependencies}")
            self._snapshot = await self._runner.provision_snapshot(
                profile=self.profile,
                profile_key=self.profile_key,
                config=self._vm_config,
            )
            if self._snapshot:
                logger.info(f"Snapshot ready: {self._snapshot.snapshot_path}")

        for _ in range(self._pool_config.min_size):
            try:
                vm = await self._create_vm()
                await self._available.put(vm)
            except Exception as e:
                logger.error(f"Failed to create initial VM: {e}")

        self._maintenance_task = asyncio.create_task(self._maintenance_loop())

    async def stop(self) -> None:
        logger.info(f"Stopping VM pool for profile {self.profile_key}")
        self._shutdown = True

        if self._maintenance_task:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass

        while not self._available.empty():
            try:
                vm = self._available.get_nowait()
                await self._destroy_vm(vm)
            except asyncio.QueueEmpty:
                break

        for vm in list(self._in_use.values()):
            await self._destroy_vm(vm)

    async def _create_vm(self) -> VMInstance:
        async with self._lock:
            self._cid_counter += 1
            cid = self._cid_counter

        vm_id = f"{self.profile_key}-{cid}"
        logger.debug(f"Creating VM {vm_id}")

        try:
            # Use snapshot restore if available (dependencies pre-installed)
            if self._snapshot:
                logger.debug(f"Restoring VM {vm_id} from snapshot")
                process = await self._runner.restore_snapshot(
                    vm_id=vm_id,
                    snapshot_path=self._snapshot.snapshot_path,
                    cid=cid,
                )
            else:
                process = await self._runner.start_vm(
                    vm_id=vm_id,
                    config=self._vm_config,
                    cid=cid,
                    profile=self.profile,
                )

            vm = VMInstance(
                vm_id=vm_id,
                cid=cid,
                port=self._vm_config.vsock_port,
                profile_key=self.profile_key,
                process=process,
            )

            await self._wait_for_vm_ready(vm)

            async with self._lock:
                self._all_vms[vm_id] = vm

            logger.info(f"VM {vm_id} created and ready")
            return vm

        except Exception as e:
            logger.error(f"Failed to create VM {vm_id}: {e}")
            raise VMStartupError(f"Failed to create VM: {e}") from e

    async def _wait_for_vm_ready(self, vm: VMInstance) -> None:
        deadline = time.time() + self._pool_config.startup_timeout_sec
        last_error: Exception | None = None

        while time.time() < deadline:
            try:
                client = RPCClient(vm.cid, vm.port)
                await asyncio.wait_for(
                    client.connect(),
                    timeout=2.0,
                )
                vm.client = client
                return
            except Exception as e:
                last_error = e
                await asyncio.sleep(0.5)

        raise VMStartupError(f"VM {vm.vm_id} did not become ready: {last_error}")

    async def _destroy_vm(self, vm: VMInstance) -> None:
        logger.debug(f"Destroying VM {vm.vm_id}")

        if vm.client:
            vm.client.close()

        if vm.process:
            await self._runner.stop_vm(vm.vm_id, vm.process)

        async with self._lock:
            self._all_vms.pop(vm.vm_id, None)
            self._in_use.pop(vm.vm_id, None)

    async def _should_recycle(self, vm: VMInstance) -> bool:
        if vm.tainted:
            return True
        if vm.call_count >= self._pool_config.max_calls_per_vm:
            return True
        return False

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[VMInstance]:
        vm = await self._acquire_vm()
        try:
            yield vm
        finally:
            await self._release_vm(vm)

    async def _acquire_vm(self) -> VMInstance:
        try:
            vm = await asyncio.wait_for(
                self._available.get(),
                timeout=self._pool_config.acquire_timeout_sec,
            )
        except asyncio.TimeoutError:
            if self.total_count < self._pool_config.max_size:
                vm = await self._create_vm()
            else:
                raise VMPoolExhaustedError(self.profile_key)

        async with self._lock:
            self._in_use[vm.vm_id] = vm

        return vm

    async def _release_vm(self, vm: VMInstance) -> None:
        async with self._lock:
            self._in_use.pop(vm.vm_id, None)

        vm.mark_used()

        if await self._should_recycle(vm):
            logger.debug(f"Recycling VM {vm.vm_id}")
            await self._destroy_vm(vm)
            if self.total_count < self._pool_config.min_size:
                try:
                    new_vm = await self._create_vm()
                    await self._available.put(new_vm)
                except Exception as e:
                    logger.error(f"Failed to replace recycled VM: {e}")
        else:
            await self._available.put(vm)

    async def execute(self, request: RPCRequest) -> RPCResponse:
        async with self.acquire() as vm:
            if vm.client is None:
                vm.client = RPCClient(vm.cid, vm.port)
                await vm.client.connect()

            try:
                response = await asyncio.wait_for(
                    vm.client.call(request),
                    timeout=request.timeout_ms / 1000.0 + 5.0,
                )
                return response
            except asyncio.TimeoutError:
                vm.tainted = True
                raise
            except Exception:
                vm.tainted = True
                raise

    async def _maintenance_loop(self) -> None:
        while not self._shutdown:
            try:
                await asyncio.sleep(60)

                now = time.time()
                vms_to_check: list[VMInstance] = []

                while not self._available.empty():
                    try:
                        vm = self._available.get_nowait()
                        vms_to_check.append(vm)
                    except asyncio.QueueEmpty:
                        break

                for vm in vms_to_check:
                    if (
                        now - vm.last_used > self._pool_config.idle_timeout_sec
                        and self.total_count > self._pool_config.min_size
                    ):
                        logger.debug(f"Removing idle VM {vm.vm_id}")
                        await self._destroy_vm(vm)
                    else:
                        await self._available.put(vm)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Maintenance loop error: {e}")


class PoolManager:
    def __init__(self, runner: FirecrackerRunner, vm_config: VMConfig):
        self._runner = runner
        self._vm_config = vm_config
        self._pools: dict[str, VMWorkerPool] = {}
        self._lock = asyncio.Lock()

    async def get_pool(
        self,
        profile: CapabilityProfile,
        profile_key: str,
        pool_config: PoolConfig | None = None,
    ) -> VMWorkerPool:
        async with self._lock:
            if profile_key not in self._pools:
                pool = VMWorkerPool(
                    profile=profile,
                    profile_key=profile_key,
                    runner=self._runner,
                    vm_config=self._vm_config,
                    pool_config=pool_config,
                )
                await pool.start()
                self._pools[profile_key] = pool

            return self._pools[profile_key]

    async def shutdown(self) -> None:
        async with self._lock:
            for pool in self._pools.values():
                await pool.stop()
            self._pools.clear()

