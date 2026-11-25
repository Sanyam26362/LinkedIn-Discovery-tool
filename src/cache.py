import hashlib
import json
import time
from pathlib import Path
from typing import Any
from src.config import CACHE_DIR, CACHE_TTL_SECS, ENABLE_CACHE


def build_cache_key(payload: Any) -> str:
    """Create a deterministic SHA-256 hex key from JSON-serializable input."""
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def get_cached_json(
    namespace: str,
    key: str,
    ttl_secs: int | None = None,
) -> Any | None:
    """Load a cached JSON entry if caching is enabled and not expired."""
    if not ENABLE_CACHE:
        return None
    effective_ttl = CACHE_TTL_SECS if ttl_secs is None else ttl_secs
    if effective_ttl == 0:
        return None

    path = CACHE_DIR / namespace / f"{key}.json"
    if not path.exists():
        return None

    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        ts = float(envelope.get("cached_at", 0.0))
        if effective_ttl > 0 and (time.time() - ts) > effective_ttl:
            return None
        return envelope.get("data")
    except Exception:
        return None


def set_cached_json(namespace: str, key: str, data: Any) -> None:
    """Persist a JSON-serializable payload into the local TTL cache."""
    if not ENABLE_CACHE:
        return
    ns_dir = CACHE_DIR / namespace
    ns_dir.mkdir(parents=True, exist_ok=True)
    path: Path = ns_dir / f"{key}.json"
    envelope = {"cached_at": time.time(), "data": data}
    try:
        path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    except Exception:
        # Cache writes must never break the main pipeline.
        return
