from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .types import CapabilityProfile, FSMount, FileSystemAccess, NetworkPolicy, VMConfig

logger = logging.getLogger(__name__)


@dataclass
class FirecrackerConfig:
    firecracker_bin: str = "firecracker"
    jailer_bin: str = "jailer"
    kernel_path: str = ""
    rootfs_path: str = ""
    use_jailer: bool = False
    chroot_base: str = "/srv/firecracker"
    snapshot_dir: str = ""


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


class LocalFirecrackerRunner(FirecrackerRunner):
    def __init__(self, fc_config: FirecrackerConfig):
        self.fc_config = fc_config
        self._vm_processes: dict[str, VMProcess] = {}

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


class MockFirecrackerRunner(FirecrackerRunner):
    def __init__(self) -> None:
        self._vms: dict[str, VMProcess] = {}
        self._mock_server_tasks: dict[str, asyncio.Task[None]] = {}

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

