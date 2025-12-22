from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RemoteTraceback:
    exception_type: str
    message: str
    traceback_str: str

    def __str__(self) -> str:
        return f"{self.exception_type}: {self.message}\n\nRemote traceback:\n{self.traceback_str}"


class SandboxError(Exception):
    def __init__(
        self,
        original_type: str,
        message: str,
        remote_traceback: str | None = None,
    ):
        self.original_type = original_type
        self.message = message
        self.remote_traceback = remote_traceback
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        msg = f"[{self.original_type}] {self.message}"
        if self.remote_traceback:
            msg += f"\n\nRemote traceback:\n{self.remote_traceback}"
        return msg


class SandboxTimeoutError(SandboxError):
    def __init__(self, message: str = "Sandbox execution timed out"):
        super().__init__("TimeoutError", message)


class SandboxCrashError(SandboxError):
    def __init__(self, message: str = "Sandbox VM crashed"):
        super().__init__("CrashError", message)


class VMPoolExhaustedError(Exception):
    def __init__(self, profile_key: str):
        self.profile_key = profile_key
        super().__init__(f"No available VMs in pool for profile: {profile_key}")


class VMStartupError(Exception):
    pass


class SerializationError(Exception):
    pass


class ProfileValidationError(Exception):
    pass


def serialize_exception(exc: BaseException) -> dict[str, Any]:
    import traceback

    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }


def deserialize_exception(data: dict[str, Any]) -> SandboxError:
    return SandboxError(
        original_type=data.get("type", "Unknown"),
        message=data.get("message", "Unknown error"),
        remote_traceback=data.get("traceback"),
    )

