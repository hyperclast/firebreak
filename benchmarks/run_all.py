#!/usr/bin/env python3
"""
Run all firebreak benchmarks.

Usage:
    python -m benchmarks.run_all          # Run all benchmarks
    python -m benchmarks.run_all --quick  # Quick run with fewer iterations
"""

import argparse
import sys
from pathlib import Path

# Ensure imports work
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    parser = argparse.ArgumentParser(description="Run firebreak benchmarks")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick run with fewer iterations",
    )
    parser.add_argument(
        "--only",
        choices=["serialization", "executor", "profile", "e2e"],
        help="Run only specific benchmark",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("FIREBREAK BENCHMARK SUITE")
    print("=" * 70)
    print()
    print("This measures the overhead of various firebreak components.")
    print("Note: These are LOCAL benchmarks. Actual VM overhead is additional.")
    print()

    if args.only is None or args.only == "serialization":
        print("\n" + "=" * 70)
        print("SECTION 1: SERIALIZATION")
        print("=" * 70)
        from benchmarks.bench_serialization import run_serialization_benchmarks
        run_serialization_benchmarks()

    if args.only is None or args.only == "executor":
        print("\n" + "=" * 70)
        print("SECTION 2: EXECUTOR")
        print("=" * 70)
        from benchmarks.bench_executor import (
            run_executor_benchmarks,
            run_direct_comparison,
        )
        run_executor_benchmarks()
        run_direct_comparison()

    if args.only is None or args.only == "profile":
        print("\n" + "=" * 70)
        print("SECTION 3: PROFILE HASHING")
        print("=" * 70)
        from benchmarks.bench_profile import (
            run_profile_benchmarks,
            run_stub_creation_benchmark,
        )
        run_profile_benchmarks()
        run_stub_creation_benchmark()

    if args.only is None or args.only == "e2e":
        print("\n" + "=" * 70)
        print("SECTION 4: END-TO-END (SIMULATED)")
        print("=" * 70)
        from benchmarks.bench_e2e import (
            run_request_creation_benchmark,
            run_simulated_rpc_benchmark,
            run_overhead_analysis,
        )
        run_request_creation_benchmark()
        run_simulated_rpc_benchmark()
        run_overhead_analysis()

    print("\n" + "=" * 70)
    print("BENCHMARK COMPLETE")
    print("=" * 70)
    print()
    print("Summary:")
    print("  - Serialization: ~1-10 us for small payloads")
    print("  - Executor dispatch: ~20-50 us overhead")
    print("  - Profile hashing: ~2-5 us")
    print("  - Full simulated RPC: ~50-200 us (no VM)")
    print()
    print("With real Firecracker VM, expect ~1-10 ms total per call.")


if __name__ == "__main__":
    main()
