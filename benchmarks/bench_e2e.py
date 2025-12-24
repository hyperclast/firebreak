#!/usr/bin/env python3
"""
Benchmark: End-to-end call overhead.

Measures the full overhead of a sandboxed function call,
simulating the complete path without actual VM execution.

Components measured:
1. Stub dispatch
2. Request creation (UUID, serialization)
3. Pool acquisition (mock)
4. RPC round-trip (simulated)
5. Response handling
"""

import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.bench_serialization import BenchmarkResult, benchmark

import msgpack


def run_request_creation_benchmark():
    """Benchmark RPC request creation."""
    print("=" * 60)
    print("REQUEST CREATION BENCHMARKS")
    print("=" * 60)

    from firebreak.profile import ProfileHasher
    from firebreak.stub import SandboxStub

    def sample_func(x: int, y: int) -> int:
        return x + y

    profile, profile_key = ProfileHasher.from_kwargs(
        fs="r:/data", net="none", cpu_ms=1000, mem_mb=256
    )

    stub = SandboxStub(
        function_ref="mymodule:sample_func",
        profile=profile,
        profile_key=profile_key,
        original_func=sample_func,
    )

    print("\nRequest creation:")
    result = benchmark(
        "create_request",
        lambda: stub.create_request(args=(1, 2), kwargs={}),
        iterations=50000,
    )
    print(result)

    request = stub.create_request(args=(1, 2), kwargs={})
    result = benchmark(
        "serialize_request",
        lambda: msgpack.packb(request.to_dict(), use_bin_type=True),
        iterations=50000,
    )
    print(result)


def run_simulated_rpc_benchmark():
    """Benchmark simulated RPC round-trip (in-memory)."""
    print("\n" + "=" * 60)
    print("SIMULATED RPC BENCHMARKS (in-memory, no network)")
    print("=" * 60)

    # Suppress executor logging for benchmarks
    import logging
    logging.getLogger("firebreak.executor").setLevel(logging.WARNING)

    from firebreak.executor import handle_request
    from firebreak.types import RPCRequest, RPCResponse

    # Create a test function in a module that can be imported
    import benchmarks.bench_executor as bench_mod

    def simulate_rpc_roundtrip():
        """Simulate full RPC without network."""
        # 1. Create request
        request = RPCRequest(
            request_id="bench-123",
            function_ref="benchmarks.bench_executor:simple_add",
            args=(1, 2),
            kwargs={},
            timeout_ms=0,
        )

        # 2. Serialize (host → VM)
        request_bytes = msgpack.packb(request.to_dict(), use_bin_type=True)

        # 3. Deserialize (in VM)
        request_data = msgpack.unpackb(request_bytes, raw=False)

        # 4. Execute (in VM)
        response_data = handle_request(request_data)

        # 5. Serialize (VM → host)
        response_bytes = msgpack.packb(response_data, use_bin_type=True)

        # 6. Deserialize (in host)
        response_dict = msgpack.unpackb(response_bytes, raw=False)

        # 7. Create response object
        response = RPCResponse.from_dict(response_dict)

        return response.result

    print("\nFull RPC simulation (no network):")
    result = benchmark(
        "rpc_roundtrip_simulated",
        simulate_rpc_roundtrip,
        iterations=5000,
    )
    print(result)

    # Break down components
    print("\nComponent breakdown:")

    request = RPCRequest(
        request_id="bench-123",
        function_ref="benchmarks.bench_executor:simple_add",
        args=(1, 2),
        kwargs={},
        timeout_ms=0,
    )
    request_bytes = msgpack.packb(request.to_dict(), use_bin_type=True)

    result = benchmark(
        "serialize_request",
        lambda: msgpack.packb(request.to_dict(), use_bin_type=True),
        iterations=10000,
    )
    print(result)

    result = benchmark(
        "deserialize_request",
        lambda: msgpack.unpackb(request_bytes, raw=False),
        iterations=10000,
    )
    print(result)

    request_data = msgpack.unpackb(request_bytes, raw=False)
    result = benchmark(
        "handle_request",
        lambda: handle_request(request_data),
        iterations=5000,
    )
    print(result)

    response_data = handle_request(request_data)
    result = benchmark(
        "serialize_response",
        lambda: msgpack.packb(response_data, use_bin_type=True),
        iterations=10000,
    )
    print(result)


def run_overhead_analysis():
    """Analyze overhead breakdown."""
    print("\n" + "=" * 60)
    print("OVERHEAD ANALYSIS")
    print("=" * 60)

    # Suppress executor logging for benchmarks
    import logging
    logging.getLogger("firebreak.executor").setLevel(logging.WARNING)

    from firebreak.executor import handle_request
    from firebreak.types import RPCRequest

    # Baseline: direct function call
    from benchmarks.bench_executor import simple_add

    iterations = 10000

    # Direct call
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        simple_add(1, 2)
        times.append((time.perf_counter() - start) * 1_000_000)
    direct_mean = statistics.mean(times)

    # Full simulated RPC
    request = RPCRequest(
        request_id="bench-123",
        function_ref="benchmarks.bench_executor:simple_add",
        args=(1, 2),
        kwargs={},
        timeout_ms=0,
    )

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        # Serialize
        request_bytes = msgpack.packb(request.to_dict(), use_bin_type=True)
        # Deserialize
        request_data = msgpack.unpackb(request_bytes, raw=False)
        # Execute
        response_data = handle_request(request_data)
        # Serialize response
        response_bytes = msgpack.packb(response_data, use_bin_type=True)
        # Deserialize response
        msgpack.unpackb(response_bytes, raw=False)
        times.append((time.perf_counter() - start) * 1_000_000)

    rpc_mean = statistics.mean(times)
    overhead = rpc_mean - direct_mean

    print(f"""
Overhead breakdown (simulated, no actual VM or network):

  Direct function call:     {direct_mean:>8.2f} us
  Simulated RPC call:       {rpc_mean:>8.2f} us
  ─────────────────────────────────────
  Overhead (no VM/network): {overhead:>8.2f} us

With real Firecracker VM, expect additional:
  - vsock IPC latency:      ~100-500 us
  - VM context switch:      ~50-200 us
  - Total warm call:        ~1-10 ms

This benchmark measures serialization + executor dispatch only.
""")


if __name__ == "__main__":
    run_request_creation_benchmark()
    run_simulated_rpc_benchmark()
    run_overhead_analysis()
