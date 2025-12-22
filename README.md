# Function-Level Sandboxing via Warm MicroVMs (Python)

> Goal: Allow Python functions annotated with `@permissions(...)` to execute inside **warm microVMs**, while all other functions run normally in the host process.

This is **real isolation**, enforced at the OS / VM boundary.
Decorators provide *developer ergonomics*, not security. MicroVMs provide security.

---

## TL;DR

- `@permissions(...)` **replaces the function with an RPC stub**
- Calls are dispatched to a **warm Firecracker microVM pool**
- Pools are keyed by **capability profiles**
- Only decorated functions are affected
- Other Python code runs unchanged in the host

---

## Non-Goals

- No in-process sandboxing
- No monkey-patching / restricted builtins
- No attempt to safely execute untrusted code inside CPython
- No support for closures or implicit ambient state

---

## Mental Model

```text
Host Python Process
│
├── normal_function()          → runs locally
├── other_normal_function()    → runs locally
└── sandboxed_function()       → RPC → microVM → result
```

Decorated functions become **remote procedure calls**.

---

## User-Facing API

```python
from sandbox import permissions

@permissions(
    fs="r:/data",
    net="none",
    cpu_ms=200,
    mem_mb=256,
)
def parse_claims(blob: bytes) -> dict:
    ...
```

Calling `parse_claims()`:
- does NOT execute locally
- dispatches to a sandboxed microVM
- returns the result (or raises a remote exception)

---

## Core Design

### 1. Decorator = Stub Replacement

At import time:

```python
parse_claims = SandboxStub(
    function_ref="mymodule:parse_claims",
    profile_key=hash_permissions(...),
)
```

The original function body is **never called in the host**.

---

### 2. Capability Profiles

A **profile** defines the sandbox environment:

Example profiles:
- `net=none, fs=none`
- `net=none, fs=ro:/data`
- `net=https-only, fs=ro:/models`

Profiles are:
- canonicalized
- hashed
- used as pool keys

Each unique profile → **its own microVM pool**

---

### 3. Warm MicroVM Pools

For each profile:
- N pre-booted Firecracker microVMs
- Python interpreter already running
- Executor daemon already listening

Dispatch is:
- acquire VM from pool
- send request over vsock
- await response
- return VM to pool (or recycle)

---

## MicroVM Responsibilities

Each microVM runs a small **executor daemon**:

```text
executor.py
├── listen on vsock
├── receive (func_id, args, kwargs)
├── import module + function
├── execute with timeout
├── serialize result / exception
└── send response
```

The microVM is **long-lived** but **logically tainted** after executing code.

Strategies:
- recycle VM after N calls
- or dedicate VMs to trusted code only
- or snapshot-restore for clean state

---

## Isolation Enforcement (Where Security Actually Lives)

### Enforced by VM boundary, NOT Python:

- **Filesystem**
  - Only bind-mounted paths exist
  - Read-only mounts enforced by host
- **Network**
  - No NIC attached (default)
  - Or restricted egress via host firewall / netns
- **CPU / Memory**
  - VM sizing + cgroups
- **Time**
  - Per-call timeout + host kill

Python inside the VM is **unrestricted**, and that’s fine.

---

## Serialization Contract

### Inputs / Outputs

Allowed by default:
- JSON-compatible types
- bytes
- lists / dicts / primitives

Optional (dangerous but useful):
- `cloudpickle` (host → VM only)
  - treat as **code injection**
  - never accept pickles from untrusted users

Large payloads:
- shared memory
- temp files
- mmap-backed blobs

---

## Function Constraints (Explicit Design Choice)

Decorated functions MUST:
- be top-level importable
- have stable `module:qualname`
- not rely on closures
- not rely on ambient host globals

This is a **feature**, not a limitation.

---

## Call Flow (End-to-End)

1. Host calls `parse_claims(x)`
2. Stub:
   - serializes `(func_id, args, kwargs)`
   - selects pool by `profile_key`
3. RPC over vsock
4. Executor:
   - imports function
   - executes
5. Result or exception returned
6. Stub:
   - deserializes
   - re-raises remote exception if needed

---

## Error Handling

Remote exceptions are:
- serialized with traceback
- re-raised as `SandboxError(original_type, message, remote_tb)`

Timeouts:
- soft timeout inside VM
- hard kill by host as backstop

Crashes:
- VM discarded
- new VM pulled from pool

---

## Performance Expectations (Reality-Based)

Approximate (very rough):
- Warm microVM call: ~1–10 ms overhead + execution
- Cold VM boot: too slow (avoid)
- Snapshot restore: much faster pool expansion

This is **not** for hot inner loops.
It *is* appropriate for:
- untrusted logic
- user-generated code
- plugin execution
- AI-generated code
- policy-sensitive operations

---

## Snapshot / Restore Strategy (Optional but Recommended)

1. Boot VM
2. Start Python
3. Import heavy dependencies
4. Start executor daemon
5. Take Firecracker snapshot + memory image
6. Restore clones on demand

This gives:
- fast scale-up
- consistent clean state

---

## Dev vs Prod

### Dev
- same code mounted read-only into VM
- relaxed recycling
- verbose logging

### Prod
- immutable VM image
- strict mount lists
- aggressive recycling
- resource quotas enforced

---

## Security Notes

- This isolates **the function**, not the entire program
- Bugs in Firecracker or the kernel are out-of-scope
- Pickle-based serialization is trusted-host-only
- Side channels (timing, resource usage) exist

This is **orders of magnitude stronger** than in-process sandboxes.

---

## Minimal Components (v1)

- `permissions` decorator
- `SandboxStub`
- `SandboxManager`
- `ProfileHasher`
- `VMWorkerPool`
- `executor.py`
- vsock RPC protocol
- Firecracker runner / snapshot tooling

---

## Why This Exists

Python assumes **ambient authority**.
Modern systems increasingly run:
- user-generated code
- AI-generated code
- plugin ecosystems

This design accepts Python’s limitations and **moves the trust boundary to the VM**, where it belongs.

---
## Performance Characteristics & Overhead

This system deliberately trades **raw call speed** for **strong isolation**.  
The goal is *safety and correctness*, not replacing in-process function calls.

Below are realistic expectations based on current Firecracker-class microVMs and vsock IPC.

### Baseline Comparison (Order of Magnitude)

| Execution Model                  | Typical Overhead (excluding function work) |
|----------------------------------|---------------------------------------------|
| In-process Python function call  | ~0.1–1 µs                                   |
| Thread / coroutine dispatch      | ~1–5 µs                                     |
| Subprocess (cold)                | 50–200 ms                                   |
| **Warm microVM (this system)**   | **~1–10 ms**                                |
| Cold microVM boot                | 100–500+ ms (not used on hot path)          |

> The warm microVM path is **~10³–10⁴× slower than a local function call**, and that is intentional.

### What Contributes to the Overhead

A sandboxed call includes:

1. Argument serialization
2. Host → VM IPC (vsock)
3. Deserialization inside VM
4. Python function execution
5. Result serialization
6. VM → host IPC
7. Deserialization + exception re-mapping

Even with everything warm, this is **not free**.

### Expected Latency Breakdown (Warm VM)

Very rough but realistic ballpark per call:

- Serialization + IPC: ~0.5–3 ms
- Python dispatch + import lookup: ~0.5–2 ms
- Return path (serialization + IPC): ~0.5–3 ms

**Total typical overhead:**  
➡ **~1–10 ms**, depending on payload size and system load.

### Throughput Expectations

This model is **not suitable** for:
- tight inner loops
- per-element numeric processing
- hot paths called thousands of times per second

It *is* suitable for:
- policy-sensitive operations
- user-generated or AI-generated code
- plugin execution
- document / data processing
- security-critical transformations

A good rule of thumb:

> If the function’s *own work* takes **<1 ms**, sandboxing will dominate.  
> If it takes **10–100+ ms**, the overhead is usually acceptable.

### Scaling Characteristics

- **Horizontal scaling** is straightforward: add more microVMs per profile.
- Each profile has its own pool; no cross-contamination.
- Snapshot/restore dramatically reduces scale-up latency.
- Pools can be sized conservatively and grown on demand.

This favors **many moderately expensive calls**, not millions of tiny ones.

### Why This Is Still the Right Trade-off

Python provides **no safe in-process isolation**.

Any system that:
- runs untrusted code
- runs user-generated code
- runs AI-generated code
- enforces real permissions (fs/net/cpu)

must pay an isolation cost somewhere.

This design pays that cost:
- **explicitly**
- **predictably**
- **at a real security boundary**

### Design Philosophy

> This is not a faster function call.  
> It is a safer execution boundary.

If you need speed, use normal Python.  
If you need isolation, **this is about as cheap as real isolation gets today**.

---

## Open Questions (Intentionally Deferred)

- Cross-function calls back to host
- Stateful sandboxes
- Deterministic replay
- Distributed VM pools
- WASM alternative backend

These are v2+ problems.

---

## Summary

- Decorators are UX
- MicroVMs are enforcement
- Processes/VMs are the only real sandbox
- Warm pools make it practical
- Explicit boundaries make it sane

This is the correct abstraction boundary.
