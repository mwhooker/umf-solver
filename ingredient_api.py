from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from db import OxideDB
from ontology import OntologyCatalog, StudioMaterial
from state import MaterialMappings, StudioInventory
from utils import norm_key, normalize


@dataclass
class ResolutionResult:
    query: str
    provider: str
    matched_concept: Optional[str]
    matched_material: Optional[str]
    matched_studio_material: Optional[str]
    status: str
    candidate_materials: List[str] = field(default_factory=list)
    reason: str = ""


class IngredientResolver:
    def __init__(
        self,
        db: OxideDB,
        catalog: OntologyCatalog,
        inventory: StudioInventory,
        mappings: MaterialMappings,
    ):
        self.db = db
        self.catalog = catalog
        self.inventory = inventory
        self.mappings = mappings

    def _find_exact_material(self, query: str) -> Optional[str]:
        if self.db.has_material(query):
            return query
        query_key = norm_key(query)
        for material in self.db.all_materials():
            if norm_key(material) == query_key:
                return material
        return None

    def resolve(self, name: str, provider: str = "generic") -> ResolutionResult:
        query = normalize(name)
        if not query:
            return ResolutionResult(
                query=name,
                provider=provider,
                matched_concept=None,
                matched_material=None,
                matched_studio_material=None,
                status="unresolved",
                reason="empty query",
            )

        studio_item = self.inventory.find_by_name(query)
        if studio_item is not None:
            return ResolutionResult(
                query=query,
                provider=provider,
                matched_concept=self.catalog.concept_for_material(studio_item.material),
                matched_material=studio_item.material,
                matched_studio_material=studio_item.name,
                status="exact_studio_material",
                reason="matched studio inventory label",
            )

        material = self._find_exact_material(query)
        if material is not None:
            return ResolutionResult(
                query=query,
                provider=provider,
                matched_concept=self.catalog.concept_for_material(material),
                matched_material=material,
                matched_studio_material=None,
                status="exact_material",
                reason="matched canonical material name",
            )

        mapping = self.mappings.get(provider, query)
        if mapping is not None:
            return ResolutionResult(
                query=query,
                provider=provider,
                matched_concept=self.catalog.concept_for_material(mapping.material),
                matched_material=mapping.material,
                matched_studio_material=None,
                status="mapped_material",
                reason="matched explicit studio-confirmed mapping",
            )

        concept = self.catalog.concept_for_term(provider, query)
        if concept is not None:
            candidate_materials = self.catalog.materials_for_concept(concept)
            if len(candidate_materials) == 1:
                material = candidate_materials[0]
                return ResolutionResult(
                    query=query,
                    provider=provider,
                    matched_concept=concept,
                    matched_material=material,
                    matched_studio_material=None,
                    status="concept_material",
                    candidate_materials=candidate_materials,
                    reason="matched ingredient concept with a single canonical material",
                )
            return ResolutionResult(
                query=query,
                provider=provider,
                matched_concept=concept,
                matched_material=None,
                matched_studio_material=None,
                status="ambiguous_concept",
                candidate_materials=candidate_materials,
                reason="matched generic ingredient concept",
            )

        return ResolutionResult(
            query=query,
            provider=provider,
            matched_concept=None,
            matched_material=None,
            matched_studio_material=None,
            status="unresolved",
            reason="no matching studio material, material, mapping, or concept",
        )
