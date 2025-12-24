from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar, overload

from .manager import get_default_manager
from .profile import ProfileHasher
from .stub import SandboxStub

F = TypeVar("F", bound=Callable[..., Any])


def _get_function_ref(func: Callable[..., Any]) -> str:
    module = getattr(func, "__module__", "__main__")
    qualname = getattr(func, "__qualname__", func.__name__)
    return f"{module}:{qualname}"


@overload
def firebreak(
    func: F,
) -> SandboxStub: ...


@overload
def firebreak(
    *,
    fs: str | list[str] | None = None,
    net: str | None = None,
    cpu_ms: int = 1000,
    mem_mb: int = 128,
    dependencies: list[str] | None = None,
) -> Callable[[F], SandboxStub]: ...


def firebreak(
    func: F | None = None,
    *,
    fs: str | list[str] | None = None,
    net: str | None = None,
    cpu_ms: int = 1000,
    mem_mb: int = 128,
    dependencies: list[str] | None = None,
) -> SandboxStub | Callable[[F], SandboxStub]:
    def decorator(fn: F) -> SandboxStub:
        profile, profile_key = ProfileHasher.from_kwargs(
            fs=fs,
            net=net,
            cpu_ms=cpu_ms,
            mem_mb=mem_mb,
            dependencies=dependencies,
        )

        function_ref = _get_function_ref(fn)

        stub = SandboxStub(
            function_ref=function_ref,
            profile=profile,
            profile_key=profile_key,
            original_func=fn,
        )

        manager = get_default_manager()
        manager.register_stub(stub)

        return stub

    if func is not None:
        return decorator(func)

    return decorator


def sandbox(
    fs: str | list[str] | None = None,
    net: str | None = None,
    cpu_ms: int = 1000,
    mem_mb: int = 128,
    dependencies: list[str] | None = None,
) -> Callable[[F], SandboxStub]:
    return firebreak(fs=fs, net=net, cpu_ms=cpu_ms, mem_mb=mem_mb, dependencies=dependencies)

