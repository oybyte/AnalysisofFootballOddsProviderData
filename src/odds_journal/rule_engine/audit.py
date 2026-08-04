from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_sha256(value: Any) -> str:
    """Hash JSON-compatible data with a stable representation."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
