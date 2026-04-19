import json
import tempfile
import unittest
from pathlib import Path

from constants import DEFAULT_TARGETS, FLUXES_DEFAULT
from db import OxideDB
from importer import import_recipe
from ontology import OntologyCatalog, SourceRecipe, SourceRecipeLine
from solver import solve_base_reformulation
from state import MaterialMappings, StudioInventory
from umf import resolve_source_recipe_to_studio


ROOT = Path(__file__).resolve().parents[1]


class RealWorldExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = OxideDB.load(ROOT / "data.csv")
        cls.catalog = OntologyCatalog.load(ROOT / "ontology_catalog.json")

    def test_hamada_rust_umf_reference_still_matches_db(self) -> None:
        recipe = {
            "Custer": 77,
            "Flint": 0.1,
            "Whiting": 6.2,
            "EPK": 4.3,
            "Gerstley Borate": 12.4,
            "Iron Oxide, Red": 7.5,
        }
        moles = self.db.oxide_moles_from_recipe(recipe)
        umf, flux_moles = self.db.umf_from_moles(moles, FLUXES_DEFAULT)

        self.assertAlmostEqual(flux_moles, 0.267982, places=5)
        self.assertAlmostEqual(umf["SiO2"], 3.4845, places=3)
        self.assertAlmostEqual(umf["Al2O3"], 0.5465, places=3)

    def test_direct_substitution_uses_explicit_rule_only(self) -> None:
        source_recipe = SourceRecipe(
            name="Custer Swap",
            provider="generic",
            source="test",
            lines=[
                SourceRecipeLine("Custer", 100.0, "base", "generic", 0),
                SourceRecipeLine("Red Iron Oxide", 5.0, "addition", "generic", 1),
            ],
        )
        inventory = StudioInventory()
        inventory.add("Mahavir Feldspar", "Mahavir")
        inventory.add("RIO", "Iron Oxide, Red")

        studio_recipe = resolve_source_recipe_to_studio(
            db=self.db,
            catalog=self.catalog,
            inventory=inventory,
            mappings=MaterialMappings(),
            recipe=source_recipe,
            max_materials=6,
        )

        base_lines = [line for line in studio_recipe.lines if line.role == "base"]
        addition_lines = [line for line in studio_recipe.lines if line.role == "addition"]
        self.assertEqual(len(base_lines), 1)
        self.assertEqual(base_lines[0].material, "Mahavir")
        self.assertEqual(base_lines[0].derivation_reason, "direct_substitution:Custer")
        self.assertEqual(len(addition_lines), 1)
        self.assertEqual(addition_lines[0].name, "RIO")

    def test_same_concept_materials_do_not_auto_substitute_without_rule(self) -> None:
        source_recipe = SourceRecipe(
            name="Mahavir Source",
            provider="generic",
            source="test",
            lines=[SourceRecipeLine("Mahavir", 100.0, "base", "generic", 0)],
        )
        inventory = StudioInventory()
        inventory.add("Custer Bag", "Custer")

        studio_recipe = resolve_source_recipe_to_studio(
            db=self.db,
            catalog=self.catalog,
            inventory=inventory,
            mappings=MaterialMappings(),
            recipe=source_recipe,
            max_materials=6,
        )

        self.assertEqual(studio_recipe.lines[0].material, "Custer")
        self.assertEqual(studio_recipe.lines[0].derivation_reason, "umf_reformulation")

    def test_recipe_resolve_requires_confirmation_for_generic_concept(self) -> None:
        source_recipe = SourceRecipe(
            name="Generic Feldspar",
            provider="glazy",
            source="test",
            lines=[SourceRecipeLine("Potash Feldspar", 100.0, "base", "glazy", 0)],
        )
        inventory = StudioInventory()
        inventory.add("Mahavir Feldspar", "Mahavir")

        with self.assertRaises(SystemExit):
            resolve_source_recipe_to_studio(
                db=self.db,
                catalog=self.catalog,
                inventory=inventory,
                mappings=MaterialMappings(),
                recipe=source_recipe,
                max_materials=6,
            )

    def test_recipe_resolve_base_reformulation_preserves_additions(self) -> None:
        source_recipe = SourceRecipe(
            name="Neph Reformulation",
            provider="generic",
            source="test",
            lines=[
                SourceRecipeLine("Neph Sy", 35.0, "base", "generic", 0),
                SourceRecipeLine("Flint", 30.0, "base", "generic", 1),
                SourceRecipeLine("EPK", 20.0, "base", "generic", 2),
                SourceRecipeLine("Whiting", 15.0, "base", "generic", 3),
                SourceRecipeLine("Iron Oxide, Red", 5.0, "addition", "generic", 4),
            ],
        )
        inventory = StudioInventory()
        inventory.add("Mahavir Feldspar", "Mahavir")
        inventory.add("Minspar Soda Spar", "Minspar")
        inventory.add("Silica 325M", "Flint")
        inventory.add("EPK Kaolin", "EPK")
        inventory.add("Whiting 325M", "Whiting")
        inventory.add("RIO", "Iron Oxide, Red")

        studio_recipe = resolve_source_recipe_to_studio(
            db=self.db,
            catalog=self.catalog,
            inventory=inventory,
            mappings=MaterialMappings(),
            recipe=source_recipe,
            max_materials=6,
        )

        addition_lines = [line for line in studio_recipe.lines if line.role == "addition"]
        base_lines = [line for line in studio_recipe.lines if line.role == "base"]
        self.assertEqual(len(addition_lines), 1)
        self.assertEqual(addition_lines[0].name, "RIO")
        self.assertEqual(addition_lines[0].amount, 5.0)
        self.assertTrue(all(line.material != "Iron Oxide, Red" for line in base_lines))
        self.assertTrue(any(line.derivation_reason == "umf_reformulation" for line in base_lines))

    def test_solver_preserves_base_mass(self) -> None:
        solved = solve_base_reformulation(
            db=self.db,
            target_base_materials={"Neph Sy": 35.0, "Flint": 30.0, "EPK": 20.0, "Whiting": 15.0},
            fixed_base_materials={"Flint": 30.0, "EPK": 20.0, "Whiting": 15.0},
            available_materials=["Mahavir", "Minspar", "Flint", "EPK", "Whiting"],
            max_materials=5,
            targets=DEFAULT_TARGETS,
            fluxes=FLUXES_DEFAULT,
        )
        self.assertAlmostEqual(sum(solved.values()), 100.0, places=6)
        self.assertNotIn("Neph Sy", solved)

    def test_redart_fixture_cannot_resolve_until_missing_canonical_materials_exist(self) -> None:
        recipe = SourceRecipe.load(ROOT / "recipes" / "redart_test.source.json")
        inventory = StudioInventory()
        inventory.add("Soda Ash", "Soda Ash")
        inventory.add("Neph Sy", "Neph Sy")
        inventory.add("EPK", "EPK")

        with self.assertRaises(SystemExit):
            resolve_source_recipe_to_studio(
                db=self.db,
                catalog=self.catalog,
                inventory=inventory,
                mappings=MaterialMappings(),
                recipe=recipe,
                max_materials=6,
            )
