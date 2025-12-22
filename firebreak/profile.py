from __future__ import annotations

import hashlib
from typing import Any

from .types import CapabilityProfile


class ProfileHasher:
    @staticmethod
    def hash(profile: CapabilityProfile) -> str:
        canonical = profile.canonical_repr()
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    @staticmethod
    def from_kwargs(**kwargs: Any) -> tuple[CapabilityProfile, str]:
        profile = CapabilityProfile.from_kwargs(**kwargs)
        profile_key = ProfileHasher.hash(profile)
        return profile, profile_key

