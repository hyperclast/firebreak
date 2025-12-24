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


# Example with third-party dependencies
# The dependencies are installed in the microVM via uv when the pool is created.
# VMs are then snapshotted, so all warm VMs have deps pre-installed.
@firebreak(
    net="https-only",
    cpu_ms=5000,
    mem_mb=512,
    dependencies=["requests", "beautifulsoup4"],
)
def fetch_and_parse(url: str) -> list[str]:
    """Fetch URL and extract all links - runs in isolated microVM with deps."""
    import requests
    from bs4 import BeautifulSoup

    response = requests.get(url, timeout=10)
    soup = BeautifulSoup(response.text, "html.parser")
    return [a.get("href") for a in soup.find_all("a", href=True)]


@firebreak(
    fs="r:/data",
    net="none",
    cpu_ms=10000,
    mem_mb=1024,
    dependencies=["pandas", "numpy"],
)
def process_csv(csv_bytes: bytes) -> dict:
    """Process CSV data with pandas - runs in isolated microVM."""
    import io
    import pandas as pd

    df = pd.read_csv(io.BytesIO(csv_bytes))
    return {
        "rows": len(df),
        "columns": list(df.columns),
        "summary": df.describe().to_dict(),
    }


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

    print("\n--- Functions without dependencies ---")
    print(f"\nparse_claims stub: {parse_claims}")
    print(f"  Profile key: {parse_claims.profile_key}")
    print(f"  Function ref: {parse_claims.function_ref}")

    print(f"\ncompute_hash stub: {compute_hash}")
    print(f"  Profile key: {compute_hash.profile_key}")

    print(f"\nsimple_add stub: {simple_add}")
    print(f"  Profile key: {simple_add.profile_key}")

    print("\n--- Functions with dependencies ---")
    print(f"\nfetch_and_parse stub: {fetch_and_parse}")
    print(f"  Profile key: {fetch_and_parse.profile_key}")
    print(f"  Dependencies: {fetch_and_parse.profile.dependencies}")

    print(f"\nprocess_csv stub: {process_csv}")
    print(f"  Profile key: {process_csv.profile_key}")
    print(f"  Dependencies: {process_csv.profile.dependencies}")

    print("\n" + "=" * 40)
    print("Note: Different dependency sets create separate VM pools.")
    print("Each pool provisions a snapshot with deps pre-installed via uv.")


if __name__ == "__main__":
    main()

