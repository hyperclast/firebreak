# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Firebreak is a Python library that provides function-level sandboxing via warm Firecracker microVMs. The `@firebreak` decorator replaces decorated functions with RPC stubs that dispatch calls to isolated microVMs, providing real OS/VM-level isolation rather than in-process sandboxing.

## Development Commands

```bash
# Install dependencies (uses uv)
uv sync

# Install with dev dependencies
uv sync --extra dev

# Run type checking
mypy firebreak

# Run linting
ruff check firebreak

# Run tests
pytest

# Run a single test
pytest tests/test_file.py::test_name -v

# Run example
python examples/basic_usage.py
```

## Architecture

### Call Flow

1. `@firebreak` decorator (decorator.py) → creates `SandboxStub` at import time
2. Function call → `SandboxStub.__call__` → `SandboxManager.execute`
3. `SandboxManager` → `PoolManager.get_pool` → `VMWorkerPool` (keyed by capability profile hash)
4. `VMWorkerPool.execute` → acquires VM → `RPCClient.call` over vsock
5. Inside VM: `executor.py` receives request, imports function, executes, returns result
6. Response flows back through RPC → stub deserializes and returns/raises

### Key Components

- **decorator.py**: `@firebreak` decorator that creates `SandboxStub` from capability parameters
- **stub.py**: `SandboxStub` - callable proxy that forwards invocations to the manager
- **manager.py**: `SandboxManager` - orchestrates execution, manages pool lifecycle
- **pool.py**: `VMWorkerPool` - maintains warm VM instances per capability profile; `PoolManager` - routes to correct pool
- **runner.py**: `FirecrackerRunner` (abstract), `LocalFirecrackerRunner`, `MockFirecrackerRunner` - VM lifecycle management
- **executor.py**: Runs inside the microVM, listens on vsock, executes functions
- **rpc.py**: `RPCClient`/`VsockConnection` - msgpack-serialized RPC over vsock
- **types.py**: `CapabilityProfile`, `FSMount`, `NetworkPolicy`, `RPCRequest`/`RPCResponse`, `VMConfig`
- **profile.py**: `ProfileHasher` - canonicalizes and hashes capability profiles for pool keying
- **exceptions.py**: `SandboxError` hierarchy with remote traceback preservation

### Capability Profiles

Each unique combination of permissions creates a separate VM pool:
- `fs`: filesystem access (`"r:/path"`, `"rw:/path"`, `"none"`)
- `net`: network policy (`"none"`, `"https-only"`, `"all"`)
- `cpu_ms`: execution timeout
- `mem_mb`: memory limit
- `dependencies`: list of pip packages to pre-install in VMs

Profiles are canonicalized and SHA256-hashed to create pool keys.

### Dependency Management

Third-party packages can be specified per-function:

```python
@firebreak(
    net="https-only",
    cpu_ms=5000,
    dependencies=["requests", "pandas>=2.0"],
)
def fetch_data(url: str) -> dict:
    import requests
    import pandas as pd
    ...
```

**Provisioning flow:**
1. When pool starts, if profile has dependencies:
   - Boot a base VM
   - Send install command to executor (`uv pip install` or `pip install`)
   - Take Firecracker snapshot
2. All warm VMs restore from this snapshot (deps pre-installed)
3. Function calls use already-warm VMs with no install overhead

Different dependency sets create separate pools with their own snapshots.

### VM Lifecycle

- VMs are pre-booted and kept warm in pools (configurable min/max size)
- VMs are recycled after N calls or when tainted (timeout/crash)
- Maintenance loop removes idle VMs beyond min pool size
- Snapshot/restore for fast scale-up is designed but not yet implemented

## Design Constraints

Decorated functions must be:
- Top-level importable (not closures)
- Have stable `module:qualname`
- Not rely on ambient host globals
- Use serializable arguments/returns (JSON-compatible types, bytes)
