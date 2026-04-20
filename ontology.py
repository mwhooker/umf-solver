from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from utils import die, norm_key, normalize


@dataclass
class IngredientConcept:
    name: str


@dataclass
class Material:
    name: str


@dataclass
class StudioMaterial:
    name: str
    material: str
    notes: str = ""


@dataclass
class SourceRecipeLine:
    original_name: str
    amount: float
    role: str
    provider: str
    order: int


@dataclass
class SourceRecipe:
    name: Optional[str]
    provider: str
    source: str
    lines: List[SourceRecipeLine]

    def save(self, path: Path) -> None:
        data = {
            "name": self.name,
            "provider": self.provider,
            "source": self.source,
            "lines": [asdict(line) for line in self.lines],
        }
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def load(path: Path) -> "SourceRecipe":
        data = json.loads(path.read_text(encoding="utf-8"))
        return SourceRecipe(
            name=data.get("name"),
            provider=data["provider"],
            source=data["source"],
            lines=[SourceRecipeLine(**line) for line in data.get("lines", [])],
        )


@dataclass
class StudioRecipeLine:
    name: str
    material: str
    amount: float
    role: str
    derivation_reason: str


@dataclass
class StudioRecipe:
    name: Optional[str]
    source: str
    provider: str
    lines: List[StudioRecipeLine]


@dataclass
class MaterialMapping:
    source_term: str
    material: str


@dataclass
class ReformulationPlan:
    fixed_base_materials: Dict[str, float]
    reformulated_base_materials: Dict[str, float]
    addition_materials: Dict[str, float]


@dataclass
class DirectSubstitutionRule:
    from_material: str
    to_material: str


@dataclass
class OntologyCatalog:
    concepts: Dict[str, IngredientConcept]
    provider_synonyms: Dict[str, Dict[str, str]]
    material_concepts: Dict[str, str]
    material_synonyms: Dict[str, str]
    direct_substitution_rules: List[DirectSubstitutionRule] = field(default_factory=list)

    @staticmethod
    def load(path: Path) -> "OntologyCatalog":
        data = json.loads(path.read_text(encoding="utf-8"))
        concepts = {
            entry["name"]: IngredientConcept(name=entry["name"])
            for entry in data.get("concepts", [])
        }
        provider_synonyms = {
            provider: {norm_key(key): value for key, value in mapping.items()}
            for provider, mapping in data.get("provider_synonyms", {}).items()
        }
        material_concepts = {
            normalize(material): concept
            for material, concept in data.get("material_concepts", {}).items()
        }
        material_synonyms = {
            norm_key(term): normalize(material)
            for term, material in data.get("material_synonyms", {}).items()
        }
        rules = [
            DirectSubstitutionRule(
                from_material=normalize(rule["from_material"]),
                to_material=normalize(rule["to_material"]),
            )
            for rule in data.get("direct_substitution_rules", [])
        ]
        return OntologyCatalog(
            concepts=concepts,
            provider_synonyms=provider_synonyms,
            material_concepts=material_concepts,
            material_synonyms=material_synonyms,
            direct_substitution_rules=rules,
        )

    def concept_for_term(self, provider: str, term: str) -> Optional[str]:
        key = norm_key(term)
        if key in self.provider_synonyms.get(provider, {}):
            return self.provider_synonyms[provider][key]
        if key in self.provider_synonyms.get("generic", {}):
            return self.provider_synonyms["generic"][key]
        return None

    def concept_for_material(self, material: str) -> Optional[str]:
        return self.material_concepts.get(normalize(material))

    def material_for_term(self, term: str) -> Optional[str]:
        return self.material_synonyms.get(norm_key(term))

    def materials_for_concept(self, concept: str) -> List[str]:
        return sorted(material for material, member in self.material_concepts.items() if member == concept)

    def direct_substitutes_for(self, material: str) -> List[str]:
        material = normalize(material)
        return [rule.to_material for rule in self.direct_substitution_rules if rule.from_material == material]
