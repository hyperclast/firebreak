#!/usr/bin/env python3
"""
Benchmark: Profile hashing and stub creation.

Measures the overhead of creating capability profiles and hashing them.
This happens at import time for each decorated function.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.bench_serialization import benchmark


def run_profile_benchmarks():
    """Benchmark profile creation and hashing."""
    print("=" * 60)
    print("PROFILE BENCHMARKS")
    print("=" * 60)

    from firebreak.profile import ProfileHasher
    from firebreak.types import CapabilityProfile

    # Simple profile (no fs, no net)
    print("\nSimple profile (defaults):")
    result = benchmark(
        "create_simple_profile",
        lambda: CapabilityProfile.from_kwargs(),
        iterations=50000,
    )
    print(result)

    simple_profile = CapabilityProfile.from_kwargs()
    result = benchmark(
        "hash_simple_profile",
        lambda: ProfileHasher.hash(simple_profile),
        iterations=50000,
    )
    print(result)

    result = benchmark(
        "create_and_hash_simple",
        lambda: ProfileHasher.from_kwargs(),
        iterations=50000,
    )
    print(result)

    # Complex profile (fs mounts, net, deps)
    print("\nComplex profile (fs + net + deps):")
    result = benchmark(
        "create_complex_profile",
        lambda: CapabilityProfile.from_kwargs(
            fs=["r:/data", "rw:/tmp"],
            net="https-only",
            cpu_ms=5000,
            mem_mb=512,
            dependencies=["pandas", "numpy", "requests"],
        ),
        iterations=50000,
    )
    print(result)

    complex_profile = CapabilityProfile.from_kwargs(
        fs=["r:/data", "rw:/tmp"],
        net="https-only",
        cpu_ms=5000,
        mem_mb=512,
        dependencies=["pandas", "numpy", "requests"],
    )
    result = benchmark(
        "hash_complex_profile",
        lambda: ProfileHasher.hash(complex_profile),
        iterations=50000,
    )
    print(result)

    result = benchmark(
        "create_and_hash_complex",
        lambda: ProfileHasher.from_kwargs(
            fs=["r:/data", "rw:/tmp"],
            net="https-only",
            cpu_ms=5000,
            mem_mb=512,
            dependencies=["pandas", "numpy", "requests"],
        ),
        iterations=50000,
    )
    print(result)

    # Canonical repr
    print("\nCanonical representation:")
    result = benchmark(
        "canonical_repr_simple",
        lambda: simple_profile.canonical_repr(),
        iterations=100000,
    )
    print(result)

    result = benchmark(
        "canonical_repr_complex",
        lambda: complex_profile.canonical_repr(),
        iterations=100000,
    )
    print(result)


def run_stub_creation_benchmark():
    """Benchmark stub creation (what happens at import time)."""
    print("\n" + "=" * 60)
    print("STUB CREATION BENCHMARKS (import-time overhead)")
    print("=" * 60)

    from firebreak.profile import ProfileHasher
    from firebreak.stub import SandboxStub

    def sample_function(x: int) -> int:
        return x * 2

    print("\nStub creation (simulating @firebreak decorator):")

    def create_stub():
        profile, profile_key = ProfileHasher.from_kwargs(
            fs="r:/data",
            net="none",
            cpu_ms=1000,
            mem_mb=256,
        )
        return SandboxStub(
            function_ref="mymodule:sample_function",
            profile=profile,
            profile_key=profile_key,
            original_func=sample_function,
        )

    result = benchmark("create_stub", create_stub, iterations=10000)
    print(result)


if __name__ == "__main__":
    run_profile_benchmarks()
    run_stub_creation_benchmark()
