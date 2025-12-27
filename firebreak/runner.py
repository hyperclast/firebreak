from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .types import CapabilityProfile, NetworkPolicy, VMConfig

logger = logging.getLogger(__name__)


@dataclass
class FirecrackerConfig:
    firecracker_bin: str = "firecracker"
    jailer_bin: str = "jailer"
    kernel_path: str = ""
    rootfs_path: str = ""
    use_jailer: bool = False
    chroot_base: str = "/srv/firecracker"
    snapshot_dir: str = "/tmp/firebreak-snapshots"


@dataclass
class SnapshotInfo:
    snapshot_path: str
    mem_path: str
    profile_key: str
    dependencies: tuple[str, ...]


@dataclass
class VMProcess:
    pid: int
    vm_id: str
    socket_path: str
    process: asyncio.subprocess.Process | None = None
    workdir: str = ""


class FirecrackerRunner(ABC):
    @abstractmethod
    async def start_vm(
        self,
        vm_id: str,
        config: VMConfig,
        cid: int,
        profile: CapabilityProfile,
    ) -> VMProcess:
        pass

    @abstractmethod
    async def stop_vm(self, vm_id: str, process: VMProcess) -> None:
        pass

    @abstractmethod
    async def create_snapshot(
        self,
        vm_id: str,
        process: VMProcess,
        snapshot_path: str,
    ) -> None:
        pass

    @abstractmethod
    async def restore_snapshot(
        self,
        vm_id: str,
        snapshot_path: str,
        cid: int,
    ) -> VMProcess:
        pass

    @abstractmethod
    async def provision_snapshot(
        self,
        profile: CapabilityProfile,
        profile_key: str,
        config: VMConfig,
    ) -> SnapshotInfo | None:
        """
        Provision a snapshot with dependencies installed.

        1. Boot a base VM
        2. Install dependencies using uv
        3. Take a snapshot
        4. Return snapshot info for pool to use

        Returns None if no dependencies need provisioning.
        """
        pass

    @abstractmethod
    def get_snapshot(self, profile_key: str) -> SnapshotInfo | None:
        """Get existing snapshot for a profile if it exists."""
        pass


class LocalFirecrackerRunner(FirecrackerRunner):
    def __init__(self, fc_config: FirecrackerConfig):
        self.fc_config = fc_config
        self._vm_processes: dict[str, VMProcess] = {}
        self._snapshots: dict[str, SnapshotInfo] = {}
        os.makedirs(fc_config.snapshot_dir, exist_ok=True)

    def _generate_fc_config(
        self,
        vm_id: str,
        config: VMConfig,
        cid: int,
        profile: CapabilityProfile,
        socket_path: str,
    ) -> dict[str, Any]:
        fc_config: dict[str, Any] = {
            "boot-source": {
                "kernel_image_path": config.kernel_path or self.fc_config.kernel_path,
                "boot_args": config.boot_args,
            },
            "drives": [
                {
                    "drive_id": "rootfs",
                    "path_on_host": config.rootfs_path or self.fc_config.rootfs_path,
                    "is_root_device": True,
                    "is_read_only": False,
                }
            ],
            "machine-config": {
                "vcpu_count": config.vcpu_count,
                "mem_size_mib": config.mem_size_mb,
            },
            "vsock": {
                "guest_cid": cid,
                "uds_path": f"{socket_path}.vsock",
            },
        }

        if profile.net == NetworkPolicy.NONE:
            pass
        else:
            fc_config["network-interfaces"] = [
                {
                    "iface_id": "eth0",
                    "guest_mac": self._generate_mac(cid),
                    "host_dev_name": f"tap-{vm_id[:8]}",
                }
            ]

        return fc_config

    def _generate_mac(self, cid: int) -> str:
        return f"02:FC:00:00:{(cid >> 8) & 0xFF:02x}:{cid & 0xFF:02x}"

    async def start_vm(
        self,
        vm_id: str,
        config: VMConfig,
        cid: int,
        profile: CapabilityProfile,
    ) -> VMProcess:
        workdir = tempfile.mkdtemp(prefix=f"firebreak-{vm_id}-")
        socket_path = os.path.join(workdir, "firecracker.sock")
        config_path = os.path.join(workdir, "config.json")

        fc_config = self._generate_fc_config(vm_id, config, cid, profile, socket_path)

        with open(config_path, "w") as f:
            json.dump(fc_config, f)

        cmd = [
            self.fc_config.firecracker_bin,
            "--api-sock",
            socket_path,
            "--config-file",
            config_path,
        ]

        logger.info(f"Starting VM {vm_id}: {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
        )

        vm_process = VMProcess(
            pid=process.pid or 0,
            vm_id=vm_id,
            socket_path=socket_path,
            process=process,
            workdir=workdir,
        )

        self._vm_processes[vm_id] = vm_process
        return vm_process

    async def stop_vm(self, vm_id: str, process: VMProcess) -> None:
        logger.info(f"Stopping VM {vm_id}")

        if process.process:
            try:
                process.process.terminate()
                await asyncio.wait_for(process.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                process.process.kill()
                await process.process.wait()
            except Exception as e:
                logger.warning(f"Error stopping VM {vm_id}: {e}")

        if process.workdir and os.path.exists(process.workdir):
            try:
                shutil.rmtree(process.workdir)
            except Exception as e:
                logger.warning(f"Error cleaning up workdir for {vm_id}: {e}")

        self._vm_processes.pop(vm_id, None)

    async def create_snapshot(
        self,
        vm_id: str,
        process: VMProcess,
        snapshot_path: str,
    ) -> None:
        logger.info(f"Creating snapshot for VM {vm_id} at {snapshot_path}")
        raise NotImplementedError("Snapshot creation not yet implemented")

    async def restore_snapshot(
        self,
        vm_id: str,
        snapshot_path: str,
        cid: int,
    ) -> VMProcess:
        logger.info(f"Restoring VM {vm_id} from snapshot {snapshot_path}")
        raise NotImplementedError("Snapshot restore not yet implemented")

    async def provision_snapshot(
        self,
        profile: CapabilityProfile,
        profile_key: str,
        config: VMConfig,
    ) -> SnapshotInfo | None:
        if not profile.dependencies:
            return None

        if profile_key in self._snapshots:
            logger.info(f"Using cached snapshot for profile {profile_key}")
            return self._snapshots[profile_key]

        logger.info(
            f"Provisioning snapshot for profile {profile_key} with deps: {profile.dependencies}"
        )

        snapshot_dir = os.path.join(self.fc_config.snapshot_dir, profile_key)
        os.makedirs(snapshot_dir, exist_ok=True)

        snapshot_path = os.path.join(snapshot_dir, "snapshot")
        mem_path = os.path.join(snapshot_dir, "mem")

        # Boot a provisioning VM
        provision_vm_id = f"provision-{profile_key[:8]}"
        cid = 99  # Use a dedicated CID for provisioning

        vm = await self.start_vm(provision_vm_id, config, cid, profile)

        try:
            # Wait for VM to be ready and install dependencies
            # The executor inside the VM handles the install command
            await self._install_dependencies(vm, profile.dependencies)

            # Create snapshot via Firecracker API
            await self._create_snapshot_via_api(vm, snapshot_path, mem_path)

            snapshot_info = SnapshotInfo(
                snapshot_path=snapshot_path,
                mem_path=mem_path,
                profile_key=profile_key,
                dependencies=profile.dependencies,
            )
            self._snapshots[profile_key] = snapshot_info

            logger.info(f"Snapshot created for profile {profile_key}")
            return snapshot_info

        finally:
            await self.stop_vm(provision_vm_id, vm)

    async def _install_dependencies(
        self,
        vm: VMProcess,
        dependencies: tuple[str, ...],
    ) -> None:
        """Send install command to executor in VM."""
        import socket
        import struct

        # Wait for executor to be ready
        await asyncio.sleep(2.0)

        # Connect to executor and send install command
        # The executor handles this as a special "install" request
        try:
            sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
            sock.setblocking(False)
            loop = asyncio.get_event_loop()
            await loop.sock_connect(sock, (99, 5000))

            install_request = {
                "request_id": "provision",
                "command": "install",
                "dependencies": list(dependencies),
            }

            import msgpack
            data = msgpack.packb(install_request, use_bin_type=True)
            header = struct.pack(">I", len(data))
            await loop.sock_sendall(sock, header + data)

            # Read response
            resp_header = b""
            while len(resp_header) < 4:
                chunk = await loop.sock_recv(sock, 4 - len(resp_header))
                resp_header += chunk

            length = struct.unpack(">I", resp_header)[0]
            resp_data = b""
            while len(resp_data) < length:
                chunk = await loop.sock_recv(sock, length - len(resp_data))
                resp_data += chunk

            response = msgpack.unpackb(resp_data, raw=False)
            if not response.get("success"):
                raise RuntimeError(f"Failed to install dependencies: {response.get('error')}")

            sock.close()
            logger.info(f"Dependencies installed: {dependencies}")

        except (AttributeError, OSError) as e:
            logger.warning(f"vsock not available for provisioning: {e}")
            raise

    async def _create_snapshot_via_api(
        self,
        vm: VMProcess,
        snapshot_path: str,
        mem_path: str,
    ) -> None:
        """Create snapshot via Firecracker API socket."""
        try:
            import aiohttp
            from aiohttp import UnixConnector
        except ImportError:
            raise ImportError(
                "aiohttp is required for Firecracker snapshot creation. "
                "Install it with: pip install firebreak[firecracker]"
            ) from None

        connector = UnixConnector(path=vm.socket_path)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Pause the VM first
            async with session.patch(
                "http://localhost/vm",
                json={"state": "Paused"},
            ) as resp:
                if resp.status != 204:
                    raise RuntimeError(f"Failed to pause VM: {await resp.text()}")

            # Create snapshot
            async with session.put(
                "http://localhost/snapshot/create",
                json={
                    "snapshot_type": "Full",
                    "snapshot_path": snapshot_path,
                    "mem_file_path": mem_path,
                },
            ) as resp:
                if resp.status != 204:
                    raise RuntimeError(f"Failed to create snapshot: {await resp.text()}")

    def get_snapshot(self, profile_key: str) -> SnapshotInfo | None:
        return self._snapshots.get(profile_key)


class MockFirecrackerRunner(FirecrackerRunner):
    def __init__(self) -> None:
        self._vms: dict[str, VMProcess] = {}
        self._mock_server_tasks: dict[str, asyncio.Task[None]] = {}
        self._snapshots: dict[str, SnapshotInfo] = {}

    async def start_vm(
        self,
        vm_id: str,
        config: VMConfig,
        cid: int,
        profile: CapabilityProfile,
    ) -> VMProcess:
        logger.info(f"[MOCK] Starting VM {vm_id} with cid={cid}")

        vm_process = VMProcess(
            pid=os.getpid(),
            vm_id=vm_id,
            socket_path=f"/tmp/mock-{vm_id}.sock",
        )
        self._vms[vm_id] = vm_process

        return vm_process

    async def stop_vm(self, vm_id: str, process: VMProcess) -> None:
        logger.info(f"[MOCK] Stopping VM {vm_id}")
        self._vms.pop(vm_id, None)

        if vm_id in self._mock_server_tasks:
            self._mock_server_tasks[vm_id].cancel()
            del self._mock_server_tasks[vm_id]

    async def create_snapshot(
        self,
        vm_id: str,
        process: VMProcess,
        snapshot_path: str,
    ) -> None:
        logger.info(f"[MOCK] Creating snapshot for {vm_id}")

    async def restore_snapshot(
        self,
        vm_id: str,
        snapshot_path: str,
        cid: int,
    ) -> VMProcess:
        logger.info(f"[MOCK] Restoring {vm_id} from snapshot")
        return VMProcess(
            pid=os.getpid(),
            vm_id=vm_id,
            socket_path=f"/tmp/mock-{vm_id}.sock",
        )

    async def provision_snapshot(
        self,
        profile: CapabilityProfile,
        profile_key: str,
        config: VMConfig,
    ) -> SnapshotInfo | None:
        if not profile.dependencies:
            return None

        if profile_key in self._snapshots:
            logger.info(f"[MOCK] Using cached snapshot for profile {profile_key}")
            return self._snapshots[profile_key]

        logger.info(f"[MOCK] Provisioning snapshot with deps: {profile.dependencies}")

        # Simulate provisioning delay
        await asyncio.sleep(0.1)

        snapshot_info = SnapshotInfo(
            snapshot_path=f"/tmp/mock-snapshot-{profile_key}",
            mem_path=f"/tmp/mock-mem-{profile_key}",
            profile_key=profile_key,
            dependencies=profile.dependencies,
        )
        self._snapshots[profile_key] = snapshot_info
        return snapshot_info

    def get_snapshot(self, profile_key: str) -> SnapshotInfo | None:
        return self._snapshots.get(profile_key)

