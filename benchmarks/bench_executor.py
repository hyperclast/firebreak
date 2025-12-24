#!/usr/bin/env python3
"""
Benchmark: Executor overhead.

Measures the overhead of function dispatch in the executor,
excluding actual function execution time.
"""

import statistics
import sys
import time
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.bench_serialization import BenchmarkResult, benchmark


def noop():
    """No-op function for measuring dispatch overhead."""
    pass


def simple_add(a: int, b: int) -> int:
    """Simple function for basic dispatch."""
    return a + b


def process_list(items: list) -> list:
    """Process a list (light computation)."""
    return [x * 2 for x in items]


def run_executor_benchmarks():
    """Benchmark executor function dispatch."""
    print("=" * 60)
    print("EXECUTOR BENCHMARKS")
    print("=" * 60)

    # Suppress executor logging for benchmarks
    import logging
    logging.getLogger("firebreak.executor").setLevel(logging.WARNING)

    from firebreak.executor import execute_function, import_function

    # Benchmark: import_function lookup
    print("\nFunction import/lookup:")

    # First call (cold)
    start = time.perf_counter()
    func = import_function("benchmarks.bench_executor:simple_add")
    cold_import_us = (time.perf_counter() - start) * 1_000_000
    print(f"  cold import: {cold_import_us:.2f} us")

    # Subsequent calls (module cached)
    result = benchmark(
        "warm_import",
        lambda: import_function("benchmarks.bench_executor:simple_add"),
        iterations=10000,
    )
    print(result)

    # Benchmark: execute_function overhead
    print("\nFunction execution (includes import + call):")

    # No-op function to measure pure overhead
    result = benchmark(
        "execute_noop",
        lambda: execute_function(
            "benchmarks.bench_executor:noop",
            args=(),
            kwargs={},
            timeout_ms=0,  # No timeout for benchmarking
        ),
        iterations=5000,
    )
    print(result)

    # Simple add
    result = benchmark(
        "execute_simple_add",
        lambda: execute_function(
            "benchmarks.bench_executor:simple_add",
            args=(1, 2),
            kwargs={},
            timeout_ms=0,
        ),
        iterations=5000,
    )
    print(result)

    # With timeout enabled (adds signal setup overhead)
    result = benchmark(
        "execute_with_timeout",
        lambda: execute_function(
            "benchmarks.bench_executor:simple_add",
            args=(1, 2),
            kwargs={},
            timeout_ms=1000,
        ),
        iterations=5000,
    )
    print(result)

    # List processing
    test_list = list(range(100))
    result = benchmark(
        "execute_process_list",
        lambda: execute_function(
            "benchmarks.bench_executor:process_list",
            args=(test_list,),
            kwargs={},
            timeout_ms=0,
        ),
        iterations=5000,
    )
    print(result)


def run_direct_comparison():
    """Compare direct call vs execute_function overhead."""
    print("\n" + "=" * 60)
    print("DIRECT CALL vs EXECUTE_FUNCTION OVERHEAD")
    print("=" * 60)

    from firebreak.executor import execute_function

    iterations = 10000
    test_list = list(range(100))

    # Direct call
    times_direct = []
    for _ in range(iterations):
        start = time.perf_counter()
        process_list(test_list)
        times_direct.append((time.perf_counter() - start) * 1_000_000)

    # Via execute_function
    times_executor = []
    for _ in range(iterations):
        start = time.perf_counter()
        execute_function(
            "benchmarks.bench_executor:process_list",
            args=(test_list,),
            kwargs={},
            timeout_ms=0,
        )
        times_executor.append((time.perf_counter() - start) * 1_000_000)

    direct_mean = statistics.mean(times_direct)
    executor_mean = statistics.mean(times_executor)
    overhead = executor_mean - direct_mean

    print(f"\nDirect call:      {direct_mean:.2f} us")
    print(f"Via executor:     {executor_mean:.2f} us")
    print(f"Executor overhead: {overhead:.2f} us ({overhead/direct_mean*100:.1f}%)")


if __name__ == "__main__":
    run_executor_benchmarks()
    run_direct_comparison()
