from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class NetworkPolicy(Enum):
    NONE = "none"
    HTTPS_ONLY = "https-only"
    ALL = "all"


class FileSystemAccess(Enum):
    NONE = "none"
    READ = "r"
    WRITE = "w"
    READ_WRITE = "rw"


@dataclass(frozen=True)
class FSMount:
    path: str
    access: FileSystemAccess

    @classmethod
    def parse(cls, spec: str) -> FSMount:
        if spec == "none":
            return cls(path="", access=FileSystemAccess.NONE)

        if ":" not in spec:
            raise ValueError(f"Invalid fs spec: {spec}. Expected format: 'r:/path' or 'rw:/path'")

        access_str, path = spec.split(":", 1)
        access_map = {
            "r": FileSystemAccess.READ,
            "w": FileSystemAccess.WRITE,
            "rw": FileSystemAccess.READ_WRITE,
        }
        if access_str not in access_map:
            raise ValueError(f"Invalid access mode: {access_str}. Expected: r, w, or rw")

        return cls(path=path, access=access_map[access_str])

    def __str__(self) -> str:
        if self.access == FileSystemAccess.NONE:
            return "none"
        access_str = {
            FileSystemAccess.READ: "r",
            FileSystemAccess.WRITE: "w",
            FileSystemAccess.READ_WRITE: "rw",
        }[self.access]
        return f"{access_str}:{self.path}"


@dataclass(frozen=True)
class CapabilityProfile:
    fs_mounts: tuple[FSMount, ...] = field(default_factory=tuple)
    net: NetworkPolicy = NetworkPolicy.NONE
    cpu_ms: int = 1000
    mem_mb: int = 128
    dependencies: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.cpu_ms <= 0:
            raise ValueError("cpu_ms must be positive")
        if self.mem_mb <= 0:
            raise ValueError("mem_mb must be positive")

    @classmethod
    def from_kwargs(
        cls,
        fs: str | list[str] | None = None,
        net: str | None = None,
        cpu_ms: int = 1000,
        mem_mb: int = 128,
        dependencies: list[str] | None = None,
    ) -> CapabilityProfile:
        fs_mounts: list[FSMount] = []
        if fs is not None:
            if isinstance(fs, str):
                fs_mounts = [FSMount.parse(fs)]
            else:
                fs_mounts = [FSMount.parse(f) for f in fs]

        net_policy = NetworkPolicy.NONE
        if net is not None:
            net_policy = NetworkPolicy(net)

        deps: tuple[str, ...] = ()
        if dependencies is not None:
            # Sort for canonical representation
            deps = tuple(sorted(dependencies))

        return cls(
            fs_mounts=tuple(sorted(fs_mounts, key=str)),
            net=net_policy,
            cpu_ms=cpu_ms,
            mem_mb=mem_mb,
            dependencies=deps,
        )

    def canonical_repr(self) -> str:
        parts = [
            f"cpu_ms={self.cpu_ms}",
            f"deps={','.join(self.dependencies) or 'none'}",
            f"fs={','.join(str(m) for m in self.fs_mounts) or 'none'}",
            f"mem_mb={self.mem_mb}",
            f"net={self.net.value}",
        ]
        return ";".join(parts)


@dataclass
class RPCRequest:
    request_id: str
    function_ref: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    timeout_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "function_ref": self.function_ref,
            "args": self.args,
            "kwargs": self.kwargs,
            "timeout_ms": self.timeout_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RPCRequest:
        return cls(
            request_id=data["request_id"],
            function_ref=data["function_ref"],
            args=tuple(data["args"]),
            kwargs=data["kwargs"],
            timeout_ms=data["timeout_ms"],
        )


@dataclass
class RPCResponse:
    request_id: str
    success: bool
    result: Any = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "success": self.success,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RPCResponse:
        return cls(
            request_id=data["request_id"],
            success=data["success"],
            result=data.get("result"),
            error=data.get("error"),
        )


@dataclass
class VMConfig:
    vcpu_count: int = 1
    mem_size_mb: int = 128
    kernel_path: str = ""
    rootfs_path: str = ""
    vsock_cid: int = 3
    vsock_port: int = 5000
    boot_args: str = "console=ttyS0 reboot=k panic=1 pci=off"

    def with_profile(self, profile: CapabilityProfile) -> VMConfig:
        return VMConfig(
            vcpu_count=self.vcpu_count,
            mem_size_mb=profile.mem_mb,
            kernel_path=self.kernel_path,
            rootfs_path=self.rootfs_path,
            vsock_cid=self.vsock_cid,
            vsock_port=self.vsock_port,
            boot_args=self.boot_args,
        )

