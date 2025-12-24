#!/usr/bin/env python3
"""
Benchmark: Serialization overhead.

Measures msgpack serialization/deserialization time for various payload sizes.
This is a component of the total RPC overhead.
"""

import statistics
import time
from dataclasses import dataclass

import msgpack


@dataclass
class BenchmarkResult:
    name: str
    iterations: int
    total_time_ms: float
    mean_time_us: float
    std_dev_us: float
    min_time_us: float
    max_time_us: float
    ops_per_sec: float

    def __str__(self) -> str:
        return (
            f"{self.name}:\n"
            f"  iterations: {self.iterations:,}\n"
            f"  mean: {self.mean_time_us:.2f} us\n"
            f"  std:  {self.std_dev_us:.2f} us\n"
            f"  min:  {self.min_time_us:.2f} us\n"
            f"  max:  {self.max_time_us:.2f} us\n"
            f"  ops/sec: {self.ops_per_sec:,.0f}"
        )


def benchmark(name: str, func, iterations: int = 10000) -> BenchmarkResult:
    """Run a benchmark and collect statistics."""
    times = []

    # Warmup
    for _ in range(min(100, iterations // 10)):
        func()

    # Actual benchmark
    for _ in range(iterations):
        start = time.perf_counter()
        func()
        end = time.perf_counter()
        times.append((end - start) * 1_000_000)  # Convert to microseconds

    return BenchmarkResult(
        name=name,
        iterations=iterations,
        total_time_ms=sum(times) / 1000,
        mean_time_us=statistics.mean(times),
        std_dev_us=statistics.stdev(times) if len(times) > 1 else 0,
        min_time_us=min(times),
        max_time_us=max(times),
        ops_per_sec=1_000_000 / statistics.mean(times),
    )


def create_rpc_request(args: tuple, kwargs: dict) -> dict:
    """Create a typical RPC request structure."""
    return {
        "request_id": "bench-12345678",
        "function_ref": "mymodule.submodule:my_function",
        "args": args,
        "kwargs": kwargs,
        "timeout_ms": 1000,
    }


def run_serialization_benchmarks():
    """Run serialization benchmarks with various payload sizes."""
    print("=" * 60)
    print("SERIALIZATION BENCHMARKS")
    print("=" * 60)

    # Small payload (typical simple function call)
    small_request = create_rpc_request(
        args=(42, "hello", True),
        kwargs={"option": "value"},
    )
    small_packed = msgpack.packb(small_request, use_bin_type=True)
    print(f"\nSmall payload: {len(small_packed)} bytes")

    result = benchmark(
        "small_serialize",
        lambda: msgpack.packb(small_request, use_bin_type=True),
    )
    print(result)

    result = benchmark(
        "small_deserialize",
        lambda: msgpack.unpackb(small_packed, raw=False),
    )
    print(result)

    # Medium payload (list of dicts)
    medium_data = [{"id": i, "name": f"item_{i}", "value": i * 1.5} for i in range(100)]
    medium_request = create_rpc_request(args=(medium_data,), kwargs={})
    medium_packed = msgpack.packb(medium_request, use_bin_type=True)
    print(f"\nMedium payload: {len(medium_packed)} bytes")

    result = benchmark(
        "medium_serialize",
        lambda: msgpack.packb(medium_request, use_bin_type=True),
    )
    print(result)

    result = benchmark(
        "medium_deserialize",
        lambda: msgpack.unpackb(medium_packed, raw=False),
    )
    print(result)

    # Large payload (binary data)
    large_binary = b"x" * 100_000  # 100KB
    large_request = create_rpc_request(args=(large_binary,), kwargs={})
    large_packed = msgpack.packb(large_request, use_bin_type=True)
    print(f"\nLarge payload: {len(large_packed)} bytes")

    result = benchmark(
        "large_serialize",
        lambda: msgpack.packb(large_request, use_bin_type=True),
        iterations=1000,
    )
    print(result)

    result = benchmark(
        "large_deserialize",
        lambda: msgpack.unpackb(large_packed, raw=False),
        iterations=1000,
    )
    print(result)

    # Round-trip (serialize + deserialize)
    print(f"\nRound-trip benchmarks:")

    result = benchmark(
        "small_roundtrip",
        lambda: msgpack.unpackb(
            msgpack.packb(small_request, use_bin_type=True), raw=False
        ),
    )
    print(result)

    result = benchmark(
        "medium_roundtrip",
        lambda: msgpack.unpackb(
            msgpack.packb(medium_request, use_bin_type=True), raw=False
        ),
    )
    print(result)


if __name__ == "__main__":
    run_serialization_benchmarks()
