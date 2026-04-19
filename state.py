from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ontology import MaterialMapping, StudioMaterial
from utils import ensure_parent, norm_key, normalize


@dataclass
class StudioInventory:
    items: List[StudioMaterial] = field(default_factory=list)

    @staticmethod
    def load(path: Path) -> "StudioInventory":
        if not path.exists():
            return StudioInventory()
        data = json.loads(path.read_text(encoding="utf-8"))
        return StudioInventory(items=[StudioMaterial(**item) for item in data.get("items", [])])

    def save(self, path: Path) -> None:
        ensure_parent(path)
        data = {"items": [item.__dict__ for item in self.items]}
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def add(self, studio_name: str, material: str, notes: str = "") -> None:
        studio_name = normalize(studio_name)
        for item in self.items:
            if norm_key(item.name) == norm_key(studio_name):
                raise ValueError(f"Studio material already exists: {studio_name}")
        self.items.append(StudioMaterial(name=studio_name, material=normalize(material), notes=notes))

    def remove(self, studio_name: str) -> bool:
        target = norm_key(studio_name)
        before = len(self.items)
        self.items = [item for item in self.items if norm_key(item.name) != target]
        return len(self.items) != before

    def find_by_name(self, name: str) -> Optional[StudioMaterial]:
        target = norm_key(name)
        for item in self.items:
            if norm_key(item.name) == target:
                return item
        return None

    def find_by_material(self, material: str) -> List[StudioMaterial]:
        material = normalize(material)
        return [item for item in self.items if item.material == material]


@dataclass
class MaterialMappings:
    items: List[MaterialMapping] = field(default_factory=list)

    @staticmethod
    def load(path: Path) -> "MaterialMappings":
        if not path.exists():
            return MaterialMappings()
        data = json.loads(path.read_text(encoding="utf-8"))
        return MaterialMappings(items=[MaterialMapping(**item) for item in data.get("items", [])])

    def save(self, path: Path) -> None:
        ensure_parent(path)
        data = {"items": [item.__dict__ for item in self.items]}
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def get(self, provider: str, source_term: str) -> Optional[MaterialMapping]:
        provider = normalize(provider)
        target = norm_key(source_term)
        for item in self.items:
            if item.provider == provider and norm_key(item.source_term) == target:
                return item
        return None

    def set(self, provider: str, source_term: str, material: str) -> None:
        provider = normalize(provider)
        source_term = normalize(source_term)
        material = normalize(material)
        existing = self.get(provider, source_term)
        if existing is not None:
            existing.material = material
            return
        self.items.append(MaterialMapping(provider=provider, source_term=source_term, material=material))

    def remove(self, provider: str, source_term: str) -> bool:
        provider = normalize(provider)
        target = norm_key(source_term)
        before = len(self.items)
        self.items = [
            item for item in self.items
            if not (item.provider == provider and norm_key(item.source_term) == target)
        ]
        return len(self.items) != before
