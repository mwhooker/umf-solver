import json
import re
import sys
from pathlib import Path
from typing import Dict, List


def die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def normalize(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s


def norm_key(s: str) -> str:
    """Aggressive normalization for matching keys."""
    s = s.strip().lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default_obj) -> dict:
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return default_obj


def save_json(path: Path, obj: dict) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=False)


def parse_kv(s: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not s:
        return out
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            die(f"Bad key=value list: {s}")
        k, v = part.split("=", 1)
        out[normalize(k)] = float(v.strip())
    return out


def parse_list(s: str) -> List[str]:
    return [normalize(x) for x in s.split(",") if x.strip()]


def resolve_oxide_list(items: List[str], db, allow_r2o: bool) -> List[str]:
    """Resolve oxide names case-insensitively against DB oxides (and optional R2O)."""
    by_lower = {ox.lower(): ox for ox in db.oxides}
    if allow_r2o:
        by_lower["r2o"] = "R2O"
    resolved: List[str] = []
    unknown: List[str] = []
    for raw in items:
        key = raw.strip().lower()
        if not key:
            continue
        ox = by_lower.get(key)
        if ox is None:
            unknown.append(raw)
        else:
            resolved.append(ox)
    if unknown:
        valid = sorted(set(by_lower.values()))
        die("Unknown oxide(s): " + ", ".join(unknown) + "\nValid: " + ", ".join(valid))
    return resolved
