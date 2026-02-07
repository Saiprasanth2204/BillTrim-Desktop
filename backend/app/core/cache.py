"""In-memory cache for desktop (no Redis). Same interface as cloud cache."""
import json
import time
from typing import Any, Optional, Dict, Tuple

CACHE_PREFIX_REPORTS = "report"
CACHE_TTL_SHORT = 120
CACHE_TTL_MEDIUM = 3600
CACHE_TTL_LONG = 86400

_memory: Dict[str, Tuple[float, str]] = {}  # key -> (expires_at, json_value)


def cache_get(key: str) -> Optional[Any]:
    now = time.time()
    if key not in _memory:
        return None
    expires_at, raw = _memory[key]
    if now > expires_at:
        del _memory[key]
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def cache_set(key: str, value: Any, ttl_seconds: int = CACHE_TTL_MEDIUM) -> bool:
    try:
        _memory[key] = (time.time() + ttl_seconds, json.dumps(value, default=str))
        return True
    except Exception:
        return False


def cache_delete(key: str) -> bool:
    _memory.pop(key, None)
    return True


def cache_delete_pattern(prefix: str) -> bool:
    to_del = [k for k in _memory if k.startswith(prefix)]
    for k in to_del:
        del _memory[k]
    return True


def report_cache_key(
    report_type: str,
    company_id: Optional[int],
    branch_id: Optional[int],
    start: str,
    end: str,
) -> str:
    cid = company_id if company_id is not None else "all"
    bid = branch_id if branch_id is not None else "all"
    return f"{CACHE_PREFIX_REPORTS}:{report_type}:{cid}:{bid}:{start}:{end}"
