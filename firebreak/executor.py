#!/usr/bin/env python3
from __future__ import annotations

import importlib
import logging
import signal
import sys
import traceback
from collections.abc import Callable
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="[executor] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

try:
    import msgpack
except ImportError:
    logger.error("msgpack not available, falling back to json")
    import json as msgpack  # type: ignore

VSOCK_PORT = 5000


def serialize(data: Any) -> bytes:
    if hasattr(msgpack, "packb"):
        return msgpack.packb(data, use_bin_type=True)
    return msgpack.dumps(data).encode()  # type: ignore


def deserialize(data: bytes) -> Any:
    if hasattr(msgpack, "unpackb"):
        return msgpack.unpackb(data, raw=False)
    return msgpack.loads(data.decode())  # type: ignore


def import_function(function_ref: str) -> Callable[..., Any]:
    if ":" not in function_ref:
        raise ValueError(f"Invalid function reference: {function_ref}")

    module_path, func_name = function_ref.rsplit(":", 1)

    module = importlib.import_module(module_path)

    parts = func_name.split(".")
    obj: Any = module
    for part in parts:
        obj = getattr(obj, part)

    if not callable(obj):
        raise TypeError(f"{function_ref} is not callable")

    return obj


def execute_function(
    function_ref: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    timeout_ms: int,
) -> dict[str, Any]:
    try:
        func = import_function(function_ref)

        def timeout_handler(signum: int, frame: Any) -> None:
            raise TimeoutError(f"Function execution exceeded {timeout_ms}ms")

        if timeout_ms > 0:
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.setitimer(signal.ITIMER_REAL, timeout_ms / 1000.0)

        try:
            result = func(*args, **kwargs)
            return {
                "success": True,
                "result": result,
                "error": None,
            }
        finally:
            if timeout_ms > 0:
                signal.setitimer(signal.ITIMER_REAL, 0)

    except Exception as e:
        return {
            "success": False,
            "result": None,
            "error": {
                "type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc(),
            },
        }


def install_dependencies(dependencies: list[str]) -> dict[str, Any]:
    """
    Install dependencies using uv (preferred) or pip (fallback).

    Security: subprocess.run with list args prevents shell injection.
    Dependencies come from decorator definitions (developer code, not user input).
    """
    import subprocess

    if not dependencies:
        return {"success": True, "result": "No dependencies to install"}

    # Validate dependency strings - basic sanity check
    for dep in dependencies:
        if not dep or not isinstance(dep, str):
            return {
                "success": False,
                "result": None,
                "error": {
                    "type": "ValidationError",
                    "message": f"Invalid dependency specification: {dep!r}",
                    "traceback": "",
                },
            }

    try:
        # Try uv first (faster, more reliable)
        # --system: allow system Python (no venv required in microVM)
        # --no-progress: cleaner logs, avoid terminal detection issues
        try:
            cmd = ["uv", "pip", "install", "--system", "--no-progress"] + list(dependencies)
            logger.info(f"Installing dependencies with uv: {dependencies}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout for large packages
            )
        except FileNotFoundError:
            # uv not available, fall back to pip
            # --disable-pip-version-check: skip update nag
            # --no-input: never prompt (would hang in VM)
            cmd = [
                "pip", "install",
                "--disable-pip-version-check",
                "--no-input",
            ] + list(dependencies)
            logger.info(f"Installing dependencies with pip (uv unavailable): {dependencies}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )

        if result.returncode != 0:
            error_output = result.stderr or result.stdout
            logger.error(f"Installation failed: {error_output}")
            return {
                "success": False,
                "result": None,
                "error": {
                    "type": "InstallError",
                    "message": f"Failed to install dependencies: {error_output[:500]}",
                    "traceback": error_output,
                },
            }

        logger.info(f"Dependencies installed successfully: {dependencies}")
        return {"success": True, "result": f"Installed: {dependencies}"}

    except subprocess.TimeoutExpired:
        logger.error("Dependency installation timed out after 300s")
        return {
            "success": False,
            "result": None,
            "error": {
                "type": "TimeoutError",
                "message": "Dependency installation timed out after 300 seconds",
                "traceback": "",
            },
        }
    except Exception as e:
        logger.exception("Unexpected error during dependency installation")
        return {
            "success": False,
            "result": None,
            "error": {
                "type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc(),
            },
        }


def handle_request(request_data: dict[str, Any]) -> dict[str, Any]:
    request_id = request_data.get("request_id", "unknown")

    # Handle special commands
    command = request_data.get("command")
    if command == "install":
        dependencies = request_data.get("dependencies", [])
        logger.info(f"Received install command for: {dependencies}")
        result = install_dependencies(dependencies)
        result["request_id"] = request_id
        return result

    # Normal function execution
    function_ref = request_data.get("function_ref", "")
    args = tuple(request_data.get("args", []))
    kwargs = request_data.get("kwargs", {})
    timeout_ms = request_data.get("timeout_ms", 0)

    logger.info(f"Executing {function_ref} (request_id={request_id})")

    result = execute_function(function_ref, args, kwargs, timeout_ms)
    result["request_id"] = request_id

    return result


class ExecutorServer:
    def __init__(self, port: int = VSOCK_PORT):
        self.port = port
        self._running = False

    def start(self) -> None:
        import socket

        try:
            listener = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
        except (AttributeError, OSError):
            logger.warning("vsock not available, falling back to TCP for testing")
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", self.port))
            listener.listen(16)
            logger.info(f"Executor listening on TCP 127.0.0.1:{self.port}")
            self._running = True
            self._serve_tcp(listener)
            return

        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((socket.VMADDR_CID_ANY, self.port))
        listener.listen(16)

        logger.info(f"Executor listening on vsock port {self.port}")
        self._running = True

        while self._running:
            try:
                conn, addr = listener.accept()
                logger.info(f"Connection from {addr}")
                self._handle_connection(conn)
            except Exception as e:
                logger.error(f"Error accepting connection: {e}")

    def _serve_tcp(self, listener: Any) -> None:
        while self._running:
            try:
                conn, addr = listener.accept()
                logger.info(f"TCP connection from {addr}")
                self._handle_connection(conn)
            except Exception as e:
                logger.error(f"Error accepting TCP connection: {e}")

    def _handle_connection(self, conn: Any) -> None:
        import struct

        try:
            while True:
                header = self._recv_exact(conn, 4)
                if not header:
                    break

                length = struct.unpack(">I", header)[0]
                data = self._recv_exact(conn, length)
                if not data:
                    break

                request = deserialize(data)
                response = handle_request(request)

                response_data = serialize(response)
                response_header = struct.pack(">I", len(response_data))
                conn.sendall(response_header + response_data)

        except Exception as e:
            logger.error(f"Connection error: {e}")
        finally:
            conn.close()

    def _recv_exact(self, conn: Any, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = conn.recv(n - len(data))
            if not chunk:
                return b""
            data += chunk
        return data

    def stop(self) -> None:
        self._running = False


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Firebreak executor daemon")
    parser.add_argument("--port", type=int, default=VSOCK_PORT, help="Port to listen on")
    args = parser.parse_args()

    server = ExecutorServer(port=args.port)

    def signal_handler(signum: int, frame: Any) -> None:
        logger.info("Received shutdown signal")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("Starting executor daemon")
    server.start()


if __name__ == "__main__":
    main()

