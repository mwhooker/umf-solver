from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Set

from db import OxideDB
from utils import load_json, normalize, norm_key, save_json


@dataclass
class AliasState:
    aliases: Dict[str, str] = field(default_factory=dict)  # user_name -> db_name

    @staticmethod
    def load(path: Path) -> "AliasState":
        data = load_json(path, default_obj={})
        raw = data.get("aliases", {}) if isinstance(data, dict) else {}
        out: Dict[str, str] = {}
        for k, v in raw.items():
            out[normalize(k)] = normalize(v)
        return AliasState(out)

    def save(self, path: Path) -> None:
        save_json(path, {"aliases": self.aliases})

    def resolve(self, user_name: str, db: OxideDB) -> Optional[str]:
        """Resolve user_name to a DB material name."""
        u = normalize(user_name)
        if db.has_material(u):
            return u
        nk = norm_key(u)
        for alias_name, db_name in self.aliases.items():
            if norm_key(alias_name) == nk and db.has_material(db_name):
                return db_name
        for m in db.all_materials():
            if norm_key(m) == nk:
                return m
        return None


@dataclass
class InventoryState:
    base: Set[str] = field(default_factory=set)  # user-facing names

    @staticmethod
    def load(path: Path) -> "InventoryState":
        data = load_json(path, default_obj={})
        base = set(normalize(x) for x in (data.get("base", []) if isinstance(data, dict) else []))
        return InventoryState(base=base)

    def save(self, path: Path) -> None:
        save_json(path, {"base": sorted(self.base)})
