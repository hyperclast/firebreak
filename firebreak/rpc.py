from __future__ import annotations

import asyncio
import socket
import struct
from typing import Any

import msgpack

from .exceptions import SerializationError
from .types import RPCRequest, RPCResponse

HEADER_SIZE = 4
VSOCK_PORT = 5000


def serialize(data: Any) -> bytes:
    try:
        return msgpack.packb(data, use_bin_type=True)
    except Exception as e:
        raise SerializationError(f"Failed to serialize: {e}") from e


def deserialize(data: bytes) -> Any:
    try:
        return msgpack.unpackb(data, raw=False)
    except Exception as e:
        raise SerializationError(f"Failed to deserialize: {e}") from e


def pack_message(data: bytes) -> bytes:
    length = len(data)
    header = struct.pack(">I", length)
    return header + data


def unpack_header(header: bytes) -> int:
    return struct.unpack(">I", header)[0]


class VsockConnection:
    def __init__(self, sock: socket.socket):
        self._sock = sock
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    @classmethod
    async def connect(cls, cid: int, port: int) -> VsockConnection:
        sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
        sock.setblocking(False)

        loop = asyncio.get_event_loop()
        await loop.sock_connect(sock, (cid, port))

        return cls(sock)

    @classmethod
    def from_socket(cls, sock: socket.socket) -> VsockConnection:
        return cls(sock)

    async def send(self, data: bytes) -> None:
        message = pack_message(data)
        loop = asyncio.get_event_loop()
        await loop.sock_sendall(self._sock, message)

    async def recv(self) -> bytes:
        loop = asyncio.get_event_loop()

        header = b""
        while len(header) < HEADER_SIZE:
            chunk = await loop.sock_recv(self._sock, HEADER_SIZE - len(header))
            if not chunk:
                raise ConnectionError("Connection closed while reading header")
            header += chunk

        length = unpack_header(header)

        data = b""
        while len(data) < length:
            chunk = await loop.sock_recv(self._sock, min(65536, length - len(data)))
            if not chunk:
                raise ConnectionError("Connection closed while reading data")
            data += chunk

        return data

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass


class SyncVsockConnection:
    def __init__(self, sock: socket.socket):
        self._sock = sock

    @classmethod
    def accept(cls, listener: socket.socket) -> tuple[SyncVsockConnection, tuple[int, int]]:
        conn, addr = listener.accept()
        return cls(conn), addr

    @classmethod
    def create_listener(cls, port: int) -> socket.socket:
        sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((socket.VMADDR_CID_ANY, port))
        sock.listen(16)
        return sock

    def send(self, data: bytes) -> None:
        message = pack_message(data)
        self._sock.sendall(message)

    def recv(self) -> bytes:
        header = b""
        while len(header) < HEADER_SIZE:
            chunk = self._sock.recv(HEADER_SIZE - len(header))
            if not chunk:
                raise ConnectionError("Connection closed while reading header")
            header += chunk

        length = unpack_header(header)

        data = b""
        while len(data) < length:
            chunk = self._sock.recv(min(65536, length - len(data)))
            if not chunk:
                raise ConnectionError("Connection closed while reading data")
            data += chunk

        return data

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass


class RPCClient:
    def __init__(self, cid: int, port: int = VSOCK_PORT):
        self.cid = cid
        self.port = port
        self._conn: VsockConnection | None = None

    async def connect(self) -> None:
        self._conn = await VsockConnection.connect(self.cid, self.port)

    async def call(self, request: RPCRequest) -> RPCResponse:
        if self._conn is None:
            await self.connect()

        assert self._conn is not None

        data = serialize(request.to_dict())
        await self._conn.send(data)

        response_data = await self._conn.recv()
        response_dict = deserialize(response_data)
        return RPCResponse.from_dict(response_dict)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


class RPCServer:
    def __init__(self, port: int = VSOCK_PORT):
        self.port = port
        self._listener: socket.socket | None = None

    def start(self) -> None:
        self._listener = SyncVsockConnection.create_listener(self.port)

    def accept(self) -> SyncVsockConnection:
        if self._listener is None:
            raise RuntimeError("Server not started")
        conn, _ = SyncVsockConnection.accept(self._listener)
        return conn

    def stop(self) -> None:
        if self._listener:
            self._listener.close()
            self._listener = None

