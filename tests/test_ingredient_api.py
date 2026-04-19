import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from db import OxideDB
from ingredient_api import IngredientResolver
from ontology import OntologyCatalog, SourceRecipe
from state import MaterialMappings, StudioInventory
from umf import cmd_ingredient_resolve, cmd_inventory_inspect, cmd_mapping_set


ROOT = Path(__file__).resolve().parents[1]


class IngredientResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = OxideDB.load(ROOT / "data.csv")
        cls.catalog = OntologyCatalog.load(ROOT / "ontology_catalog.json")

    def test_exact_studio_material_labels_stay_distinct(self) -> None:
        inventory = StudioInventory()
        inventory.add("Silica 200M", "Flint")
        inventory.add("Silica 325M", "Flint")
        resolver = IngredientResolver(self.db, self.catalog, inventory, MaterialMappings())

        match_200 = resolver.resolve("Silica 200M", provider="generic")
        match_325 = resolver.resolve("Silica 325M", provider="generic")

        self.assertEqual(match_200.status, "exact_studio_material")
        self.assertEqual(match_200.matched_studio_material, "Silica 200M")
        self.assertEqual(match_325.status, "exact_studio_material")
        self.assertEqual(match_325.matched_studio_material, "Silica 325M")

    def test_generic_concept_stays_ambiguous_without_mapping(self) -> None:
        resolver = IngredientResolver(self.db, self.catalog, StudioInventory(), MaterialMappings())

        match = resolver.resolve("Potash Feldspar", provider="glazy")

        self.assertEqual(match.status, "ambiguous_concept")
        self.assertEqual(match.matched_concept, "Potash Feldspar")
        self.assertIn("Custer", match.candidate_materials)
        self.assertIn("Mahavir", match.candidate_materials)

    def test_mapping_set_makes_resolution_deterministic(self) -> None:
        mappings = MaterialMappings()
        mappings.set("glazy", "Potash Feldspar", "Mahavir")
        resolver = IngredientResolver(self.db, self.catalog, StudioInventory(), mappings)

        match = resolver.resolve("Potash Feldspar", provider="glazy")

        self.assertEqual(match.status, "mapped_material")
        self.assertEqual(match.matched_material, "Mahavir")

    def test_material_synonym_resolves_to_canonical_material(self) -> None:
        resolver = IngredientResolver(self.db, self.catalog, StudioInventory(), MaterialMappings())

        match = resolver.resolve("Edgar Plastic Kaolin", provider="generic")
        typo_match = resolver.resolve("Esgar Plastic Kaolin", provider="generic")

        self.assertEqual(match.status, "material_synonym")
        self.assertEqual(match.matched_material, "EPK")
        self.assertEqual(typo_match.status, "material_synonym")
        self.assertEqual(typo_match.matched_material, "EPK")

    def test_inventory_inspect_shows_studio_material_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inventory_path = Path(tmpdir) / "studio_inventory.json"
            mappings_path = Path(tmpdir) / "material_mappings.json"
            inventory = StudioInventory()
            inventory.add("Silica 325M", "Flint", notes="fine mesh")
            inventory.save(inventory_path)
            mappings_path.write_text(json.dumps({"items": []}), encoding="utf-8")

            args = SimpleNamespace(
                db=ROOT / "data.csv",
                catalog=ROOT / "ontology_catalog.json",
                studio_inventory=inventory_path,
                material_mappings=mappings_path,
            )
            out = StringIO()
            with redirect_stdout(out):
                cmd_inventory_inspect(args)

        text = out.getvalue()
        self.assertIn("Silica 325M", text)
        self.assertIn("material: Flint", text)
        self.assertIn("notes: fine mesh", text)

    def test_cli_mapping_set_persists_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inventory_path = Path(tmpdir) / "studio_inventory.json"
            mappings_path = Path(tmpdir) / "material_mappings.json"
            inventory_path.write_text(json.dumps({"items": []}), encoding="utf-8")
            mappings_path.write_text(json.dumps({"items": []}), encoding="utf-8")
            args = SimpleNamespace(
                db=ROOT / "data.csv",
                catalog=ROOT / "ontology_catalog.json",
                studio_inventory=inventory_path,
                material_mappings=mappings_path,
                provider="glazy",
                source_term="Potash Feldspar",
                material="Mahavir",
            )
            cmd_mapping_set(args)
            resolver = IngredientResolver(
                self.db,
                self.catalog,
                StudioInventory.load(inventory_path),
                MaterialMappings.load(mappings_path),
            )

        match = resolver.resolve("Potash Feldspar", provider="glazy")
        self.assertEqual(match.status, "mapped_material")
        self.assertEqual(match.matched_material, "Mahavir")

    def test_cli_resolve_reports_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inventory_path = Path(tmpdir) / "studio_inventory.json"
            mappings_path = Path(tmpdir) / "material_mappings.json"
            inventory_path.write_text(json.dumps({"items": []}), encoding="utf-8")
            mappings_path.write_text(json.dumps({"items": []}), encoding="utf-8")
            args = SimpleNamespace(
                db=ROOT / "data.csv",
                catalog=ROOT / "ontology_catalog.json",
                studio_inventory=inventory_path,
                material_mappings=mappings_path,
                provider="glazy",
                ingredients=["Potash Feldspar"],
            )
            out = StringIO()
            with redirect_stdout(out):
                cmd_ingredient_resolve(args)

        text = out.getvalue()
        self.assertIn("status: ambiguous_concept", text)
        self.assertIn("concept: Potash Feldspar", text)

    def test_redart_recipe_surfaces_real_world_ontology_gaps_without_guessing(self) -> None:
        recipe = SourceRecipe.load(ROOT / "recipes" / "redart_test.source.json")
        resolver = IngredientResolver(self.db, self.catalog, StudioInventory(), MaterialMappings())

        statuses = {
            line.original_name: resolver.resolve(line.original_name, provider=recipe.provider).status
            for line in recipe.lines
        }

        self.assertEqual(statuses["Soda Ash"], "exact_material")
        self.assertEqual(statuses["Nepheline Syenite"], "concept_material")
        self.assertEqual(statuses["Edgar Plastic Kaolin"], "material_synonym")
        self.assertEqual(statuses["Kona F-4 Feldspar"], "unresolved")
        self.assertEqual(statuses["Kentucky Ball Clay (OM 4)"], "unresolved")
        self.assertEqual(statuses["Cedar Heights Redart"], "unresolved")
