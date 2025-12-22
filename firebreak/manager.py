from __future__ import annotations

import asyncio
import logging
from typing import Any

from .exceptions import SandboxTimeoutError
from .pool import PoolConfig, PoolManager
from .runner import FirecrackerConfig, FirecrackerRunner, LocalFirecrackerRunner, MockFirecrackerRunner
from .stub import SandboxStub
from .types import CapabilityProfile, VMConfig

logger = logging.getLogger(__name__)

_default_manager: SandboxManager | None = None


def get_default_manager() -> SandboxManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = SandboxManager()
    return _default_manager


def set_default_manager(manager: SandboxManager) -> None:
    global _default_manager
    _default_manager = manager


class SandboxManager:
    def __init__(
        self,
        runner: FirecrackerRunner | None = None,
        vm_config: VMConfig | None = None,
        pool_config: PoolConfig | None = None,
        use_mock: bool = False,
    ):
        if runner is None:
            if use_mock:
                runner = MockFirecrackerRunner()
            else:
                runner = LocalFirecrackerRunner(FirecrackerConfig())

        self._runner = runner
        self._vm_config = vm_config or VMConfig()
        self._default_pool_config = pool_config or PoolConfig()
        self._pool_manager = PoolManager(runner, self._vm_config)
        self._stubs: dict[str, SandboxStub] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        logger.info("Starting SandboxManager")
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        logger.info("Stopping SandboxManager")
        await self._pool_manager.shutdown()
        self._started = False

    def register_stub(self, stub: SandboxStub) -> None:
        self._stubs[stub.function_ref] = stub
        stub.bind_manager(self)

    def execute(
        self,
        stub: SandboxStub,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        try:
            loop = asyncio.get_running_loop()
            future = asyncio.ensure_future(self.execute_async(stub, args, kwargs))
            return loop.run_until_complete(future)
        except RuntimeError:
            return asyncio.run(self.execute_async(stub, args, kwargs))

    async def execute_async(
        self,
        stub: SandboxStub,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        if not self._started:
            await self.start()

        pool = await self._pool_manager.get_pool(
            profile=stub.profile,
            profile_key=stub.profile_key,
            pool_config=self._default_pool_config,
        )

        request = stub.create_request(args, kwargs)

        try:
            response = await pool.execute(request)
            return stub.handle_response(response)
        except asyncio.TimeoutError:
            raise SandboxTimeoutError(
                f"Function {stub.function_ref} timed out after {stub.profile.cpu_ms}ms"
            )

    def __enter__(self) -> SandboxManager:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        loop.run_until_complete(self.stop())

    async def __aenter__(self) -> SandboxManager:
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.stop()

