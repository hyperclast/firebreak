from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .exceptions import SandboxError, deserialize_exception
from .types import CapabilityProfile, RPCRequest, RPCResponse

if TYPE_CHECKING:
    from .manager import SandboxManager


class SandboxStub:
    def __init__(
        self,
        function_ref: str,
        profile: CapabilityProfile,
        profile_key: str,
        manager: SandboxManager | None = None,
        original_func: Callable[..., Any] | None = None,
    ):
        self.function_ref = function_ref
        self.profile = profile
        self.profile_key = profile_key
        self._manager = manager
        self._original_func = original_func

        if original_func:
            self.__name__ = original_func.__name__
            self.__doc__ = original_func.__doc__
            self.__module__ = original_func.__module__
            self.__qualname__ = original_func.__qualname__
            self.__annotations__ = original_func.__annotations__

    def bind_manager(self, manager: SandboxManager) -> None:
        self._manager = manager

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._manager is None:
            from .manager import get_default_manager

            self._manager = get_default_manager()

        return self._manager.execute(self, args, kwargs)

    async def __call_async__(self, *args: Any, **kwargs: Any) -> Any:
        if self._manager is None:
            from .manager import get_default_manager

            self._manager = get_default_manager()

        return await self._manager.execute_async(self, args, kwargs)

    def create_request(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> RPCRequest:
        return RPCRequest(
            request_id=str(uuid.uuid4()),
            function_ref=self.function_ref,
            args=args,
            kwargs=kwargs,
            timeout_ms=self.profile.cpu_ms,
        )

    def handle_response(self, response: RPCResponse) -> Any:
        if response.success:
            return response.result
        else:
            if response.error:
                raise deserialize_exception(response.error)
            raise SandboxError("Unknown", "Unknown error occurred in sandbox")

    def __repr__(self) -> str:
        return f"<SandboxStub {self.function_ref} profile={self.profile_key}>"

