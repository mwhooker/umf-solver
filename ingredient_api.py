from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from db import OxideDB
from state import AliasState, InventoryState
from utils import norm_key, normalize


PROVIDER_SYNONYMS: Dict[str, Dict[str, List[str]]] = {
    "generic": {
        "silica": ["Flint"],
        "flint": ["Flint"],
        "kaolin": ["EPK"],
        "red iron oxide": ["Iron Oxide, Red"],
        "rio": ["Iron Oxide, Red"],
        "ferro frit 3134": ["3134 (Frit)"],
        "ferro frit 3124": ["3124 (Frit)"],
        "potash feldspar": ["Custer", "Mahavir"],
        "soda feldspar": ["Minspar"],
        "nepheline syenite": ["Neph Sy"],
    },
    "digitalfire": {
        "epk": ["EPK"],
        "custer feldspar": ["Custer"],
        "ferro frit 3134": ["3134 (Frit)"],
        "ferro frit 3124": ["3124 (Frit)"],
        "silica": ["Flint"],
        "kaolin": ["EPK"],
        "potash feldspar": ["Custer", "Mahavir"],
        "soda feldspar": ["Minspar"],
        "red iron oxide": ["Iron Oxide, Red"],
    },
    "glazy": {
        "silica": ["Flint"],
        "kaolin": ["EPK"],
        "potash feldspar": ["Custer", "Mahavir"],
        "soda feldspar": ["Minspar"],
        "red iron oxide": ["Iron Oxide, Red"],
    },
}


@dataclass
class IngredientMatch:
    query: str
    resolved_name: Optional[str]
    status: str
    source: str
    candidates: List[str] = field(default_factory=list)


class IngredientResolver:
    def __init__(self, db: OxideDB, alias: AliasState, inventory: Optional[InventoryState] = None):
        self.db = db
        self.alias = alias
        self.inventory = inventory

    def _inventory_db_names(self) -> Set[str]:
        if self.inventory is None:
            return set()

        out: Set[str] = set()
        for name in self.inventory.base:
            resolved = self.alias.resolve(name, self.db)
            if resolved is not None:
                out.add(resolved)
        return out

    def _rank_candidates(self, candidates: List[str]) -> List[str]:
        deduped: List[str] = []
        seen = set()
        for candidate in candidates:
            if candidate in seen or not self.db.has_material(candidate):
                continue
            seen.add(candidate)
            deduped.append(candidate)

        inventory_db = self._inventory_db_names()
        if not inventory_db:
            return deduped

        in_inventory = [candidate for candidate in deduped if candidate in inventory_db]
        not_in_inventory = [candidate for candidate in deduped if candidate not in inventory_db]
        return in_inventory + not_in_inventory

    def _inventory_unique_candidate(self, candidates: List[str]) -> Optional[str]:
        inventory_db = self._inventory_db_names()
        if not inventory_db:
            return None

        in_inventory = [candidate for candidate in candidates if candidate in inventory_db]
        if len(in_inventory) == 1:
            return in_inventory[0]
        return None

    def resolve(self, name: str, provider: str = "generic") -> IngredientMatch:
        query = normalize(name)
        if not query:
            return IngredientMatch(query=name, resolved_name=None, status="unresolved", source="empty")

        direct = self.alias.resolve(query, self.db)
        if direct is not None:
            return IngredientMatch(query=query, resolved_name=direct, status="resolved", source="db-or-alias")

        key = norm_key(query)
        provider_map = PROVIDER_SYNONYMS.get(provider, {})
        generic_map = PROVIDER_SYNONYMS["generic"]

        if key in provider_map:
            candidates = self._rank_candidates(provider_map[key])
            inventory_choice = self._inventory_unique_candidate(candidates)
            if inventory_choice is not None:
                return IngredientMatch(
                    query=query,
                    resolved_name=inventory_choice,
                    status="resolved",
                    source=f"{provider}-inventory",
                )
            if len(candidates) == 1:
                return IngredientMatch(query=query, resolved_name=candidates[0], status="resolved", source=provider)
            if len(candidates) > 1:
                return IngredientMatch(
                    query=query,
                    resolved_name=candidates[0] if len(candidates) == 1 else None,
                    status="ambiguous",
                    source=provider,
                    candidates=candidates,
                )

        if key in generic_map:
            candidates = self._rank_candidates(generic_map[key])
            inventory_choice = self._inventory_unique_candidate(candidates)
            if inventory_choice is not None:
                return IngredientMatch(
                    query=query,
                    resolved_name=inventory_choice,
                    status="resolved",
                    source="generic-inventory",
                )
            if len(candidates) == 1:
                return IngredientMatch(query=query, resolved_name=candidates[0], status="resolved", source="generic")
            if len(candidates) > 1:
                return IngredientMatch(
                    query=query,
                    resolved_name=None,
                    status="ambiguous",
                    source="generic",
                    candidates=candidates,
                )

        return IngredientMatch(query=query, resolved_name=None, status="unresolved", source="none")
