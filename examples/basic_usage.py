#!/usr/bin/env python3
"""
Basic usage example for firebreak.

Note: This example requires Firecracker to be installed and configured.
For testing without VMs, use MockFirecrackerRunner.
"""

from firebreak import (
    SandboxManager,
    firebreak,
    set_default_manager,
    MockFirecrackerRunner,
    VMConfig,
    PoolConfig,
)


@firebreak(
    fs="r:/data",
    net="none",
    cpu_ms=200,
    mem_mb=256,
)
def parse_claims(blob: bytes) -> dict:
    """Parse claims from a blob - runs in isolated microVM."""
    import json
    return json.loads(blob)


@firebreak(
    fs="none",
    net="none",
    cpu_ms=1000,
    mem_mb=128,
)
def compute_hash(data: str) -> str:
    """Compute SHA256 hash - runs in isolated microVM."""
    import hashlib
    return hashlib.sha256(data.encode()).hexdigest()


@firebreak
def simple_add(a: int, b: int) -> int:
    """Simple addition with default isolation settings."""
    return a + b


def main():
    manager = SandboxManager(
        runner=MockFirecrackerRunner(),
        vm_config=VMConfig(),
        pool_config=PoolConfig(min_size=1, max_size=5),
        use_mock=True,
    )
    set_default_manager(manager)

    print("Firebreak Example")
    print("=" * 40)

    print(f"\nparse_claims stub: {parse_claims}")
    print(f"  Profile key: {parse_claims.profile_key}")
    print(f"  Function ref: {parse_claims.function_ref}")

    print(f"\ncompute_hash stub: {compute_hash}")
    print(f"  Profile key: {compute_hash.profile_key}")

    print(f"\nsimple_add stub: {simple_add}")
    print(f"  Profile key: {simple_add.profile_key}")


if __name__ == "__main__":
    main()

