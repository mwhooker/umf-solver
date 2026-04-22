import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from constants import DEFAULT_TARGETS, FLUXES_DEFAULT
from db import OxideDB
from importer import import_recipe
from ontology import OntologyCatalog, SourceRecipe, SourceRecipeLine, StudioRecipe, StudioRecipeLine
from solver import solve_base_reformulation
from state import MaterialMappings, StudioInventory
from umf import (
    parse_batch_quantity,
    print_studio_recipe,
    print_text_table,
    recipe_materials,
    render_source_recipe_to_studio,
    scale_recipe_lines,
    solve_source_recipe_to_studio,
    source_recipe_materials,
)


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

    def test_solver_first_resolution_rebalances_when_only_substitute_is_stocked(self) -> None:
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

        studio_recipe = solve_source_recipe_to_studio(
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
        self.assertEqual(base_lines[0].derivation_reason, "umf_reformulation")
        self.assertAlmostEqual(base_lines[0].amount, 100.0, places=6)
        self.assertEqual(len(addition_lines), 1)
        self.assertEqual(addition_lines[0].name, "RIO")

    def test_kona_f4_rebalances_to_minspar_when_only_substitute_is_stocked(self) -> None:
        source_recipe = SourceRecipe(
            name="Kona F4 Swap",
            provider="generic",
            source="test",
            lines=[SourceRecipeLine("Kona F-4 Feldspar", 100.0, "base", "generic", 0)],
        )
        inventory = StudioInventory()
        inventory.add("Minspar Soda Spar", "Minspar")

        studio_recipe = render_source_recipe_to_studio(
            db=self.db,
            catalog=self.catalog,
            inventory=inventory,
            mappings=MaterialMappings(),
            recipe=source_recipe,
        )

        self.assertEqual(len(studio_recipe.lines), 1)
        self.assertEqual(studio_recipe.lines[0].material, "Minspar")
        self.assertEqual(studio_recipe.lines[0].derivation_reason, "direct_substitution:Kona F-4 Feldspar")
        self.assertAlmostEqual(studio_recipe.lines[0].amount, 100.0, places=6)

    def test_kona_f4_solve_rebalances_to_minspar_when_only_substitute_is_stocked(self) -> None:
        source_recipe = SourceRecipe(
            name="Kona F4 Swap",
            provider="generic",
            source="test",
            lines=[SourceRecipeLine("Kona F-4 Feldspar", 100.0, "base", "generic", 0)],
        )
        inventory = StudioInventory()
        inventory.add("Minspar Soda Spar", "Minspar")

        studio_recipe = solve_source_recipe_to_studio(
            db=self.db,
            catalog=self.catalog,
            inventory=inventory,
            mappings=MaterialMappings(),
            recipe=source_recipe,
            max_materials=6,
        )

        self.assertEqual(len(studio_recipe.lines), 1)
        self.assertEqual(studio_recipe.lines[0].material, "Minspar")
        self.assertEqual(studio_recipe.lines[0].derivation_reason, "umf_reformulation")
        self.assertAlmostEqual(studio_recipe.lines[0].amount, 100.0, places=6)

    def test_same_concept_materials_do_not_auto_substitute_without_rule(self) -> None:
        source_recipe = SourceRecipe(
            name="Mahavir Source",
            provider="generic",
            source="test",
            lines=[SourceRecipeLine("Mahavir", 100.0, "base", "generic", 0)],
        )
        inventory = StudioInventory()
        inventory.add("Custer Bag", "Custer")

        studio_recipe = solve_source_recipe_to_studio(
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
            solve_source_recipe_to_studio(
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

        studio_recipe = solve_source_recipe_to_studio(
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

    def test_solve_rebalances_full_base_not_just_substituted_line(self) -> None:
        source_recipe = SourceRecipe(
            name="MD Shino style",
            provider="generic",
            source="test",
            lines=[
                SourceRecipeLine("Soda Ash", 17.27, "base", "generic", 0),
                SourceRecipeLine("Kona F-4 Feldspar", 9.82, "base", "generic", 1),
                SourceRecipeLine("Nepheline Syenite", 40.91, "base", "generic", 2),
                SourceRecipeLine("Edgar Plastic Kaolin", 18.18, "base", "generic", 3),
                SourceRecipeLine("OM4", 13.82, "base", "generic", 4),
                SourceRecipeLine("Red Art", 6.0, "addition", "generic", 5),
            ],
        )
        inventory = StudioInventory()
        inventory.add("Soda Ash", "Soda Ash")
        inventory.add("Minspar", "Minspar")
        inventory.add("Nepheline Syenite", "Neph Sy")
        inventory.add("EPK", "EPK")
        inventory.add("OM4", "OM4")
        inventory.add("Red Art", "Red Art")

        studio_recipe = solve_source_recipe_to_studio(
            db=self.db,
            catalog=self.catalog,
            inventory=inventory,
            mappings=MaterialMappings(),
            recipe=source_recipe,
            max_materials=6,
        )

        base_amounts = {line.material: line.amount for line in studio_recipe.lines if line.role == "base"}
        self.assertNotAlmostEqual(base_amounts["Soda Ash"], 17.27, places=2)
        self.assertNotAlmostEqual(base_amounts["Minspar"], 9.82, places=2)
        self.assertAlmostEqual(sum(base_amounts.values()), 100.0, places=6)

    def test_render_can_force_material_substitution(self) -> None:
        source_recipe = SourceRecipe(
            name="Forced kaolin",
            provider="generic",
            source="test",
            lines=[SourceRecipeLine("Edgar Plastic Kaolin", 18.18, "base", "generic", 0)],
        )
        inventory = StudioInventory()
        inventory.add("EPK", "EPK")
        inventory.add("Ione", "Ione Kaolin")

        studio_recipe = render_source_recipe_to_studio(
            db=self.db,
            catalog=self.catalog,
            inventory=inventory,
            mappings=MaterialMappings(),
            recipe=source_recipe,
            substitutions={"EPK": "Ione Kaolin"},
        )

        self.assertEqual(len(studio_recipe.lines), 1)
        self.assertEqual(studio_recipe.lines[0].material, "Ione Kaolin")
        self.assertEqual(studio_recipe.lines[0].derivation_reason, "forced_substitution:EPK")

    def test_scale_recipe_lines_uses_total_recipe_weight(self) -> None:
        inventory = StudioInventory()
        inventory.add("Soda Ash", "Soda Ash")
        inventory.add("Red Art", "Red Art")
        studio_recipe = render_source_recipe_to_studio(
            db=self.db,
            catalog=self.catalog,
            inventory=inventory,
            mappings=MaterialMappings(),
            recipe=SourceRecipe(
                name="Scale test",
                provider="generic",
                source="test",
                lines=[
                    SourceRecipeLine("Soda Ash", 100.0, "base", "generic", 0),
                    SourceRecipeLine("Red Art", 6.0, "addition", "generic", 1),
                ],
            ),
        )

        scaled = scale_recipe_lines(studio_recipe, 1060.0)
        amounts = {line.material: amount for line, amount in scaled}
        self.assertAlmostEqual(amounts["Soda Ash"], 1000.0, places=6)
        self.assertAlmostEqual(amounts["Red Art"], 60.0, places=6)

    def test_parse_batch_quantity_accepts_compact_and_spaced_units(self) -> None:
        self.assertEqual(parse_batch_quantity("100oz"), (100.0, "oz"))
        self.assertEqual(parse_batch_quantity("100 oz"), (100.0, "oz"))
        self.assertEqual(parse_batch_quantity("1.5kg"), (1.5, "kg"))

    def test_print_studio_recipe_rounds_line_amounts_to_two_decimals(self) -> None:
        studio_recipe = StudioRecipe(
            name="Round test",
            provider="generic",
            source="test",
            lines=[
                StudioRecipeLine("Soda Ash", {"Soda Ash": 1.0}, 16.2925, "base", "exact_studio_material"),
                StudioRecipeLine("Red Art", {"Red Art": 1.0}, 5.66038, "addition", "material_synonym"),
            ],
        )

        out = StringIO()
        with redirect_stdout(out):
            print_studio_recipe(studio_recipe, "Rendered studio recipe from", batch_amount=None, batch_unit=None)

        text = out.getvalue()
        self.assertIn("Soda Ash: 16.29 parts", text)
        self.assertIn("Red Art: 5.66 parts", text)

    def test_print_text_table_uses_fixed_width_columns(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            print_text_table(
                ["oxide", "moles", "umf"],
                [
                    ["Na2O", "0.240085", "0.868170"],
                    ["K2O", "0.028259", "0.102186"],
                ],
            )

        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], "oxide   moles     umf")
        self.assertEqual(lines[1], "Na2O    0.240085  0.868170")
        self.assertEqual(lines[2], "K2O     0.028259  0.102186")

    def test_render_converts_dry_requirement_to_solution_stock_amount(self) -> None:
        source_recipe = SourceRecipe(
            name="Soda ash solution",
            provider="generic",
            source="test",
            lines=[SourceRecipeLine("Soda Ash", 18.0, "base", "generic", 0)],
        )
        inventory = StudioInventory()
        inventory.add("Soda Ash Solution 18%", contributions={"Soda Ash": 0.18})

        studio_recipe = render_source_recipe_to_studio(
            db=self.db,
            catalog=self.catalog,
            inventory=inventory,
            mappings=MaterialMappings(),
            recipe=source_recipe,
        )

        self.assertEqual(len(studio_recipe.lines), 1)
        self.assertEqual(studio_recipe.lines[0].name, "Soda Ash Solution 18%")
        self.assertAlmostEqual(studio_recipe.lines[0].amount, 100.0, places=6)
        self.assertAlmostEqual(recipe_materials(studio_recipe)["Soda Ash"], 18.0, places=6)

    def test_solve_can_batch_with_single_material_solution_stock(self) -> None:
        source_recipe = SourceRecipe(
            name="Soda ash solution solve",
            provider="generic",
            source="test",
            lines=[SourceRecipeLine("Soda Ash", 18.0, "base", "generic", 0)],
        )
        inventory = StudioInventory()
        inventory.add("Soda Ash Solution 18%", contributions={"Soda Ash": 0.18})

        studio_recipe = solve_source_recipe_to_studio(
            db=self.db,
            catalog=self.catalog,
            inventory=inventory,
            mappings=MaterialMappings(),
            recipe=source_recipe,
            max_materials=2,
        )

        self.assertEqual(len(studio_recipe.lines), 1)
        self.assertEqual(studio_recipe.lines[0].name, "Soda Ash Solution 18%")
        self.assertAlmostEqual(studio_recipe.lines[0].amount, 100.0, places=6)
        self.assertAlmostEqual(recipe_materials(studio_recipe)["Soda Ash"], 18.0, places=6)

    def test_solve_can_force_material_substitution(self) -> None:
        source_recipe = SourceRecipe(
            name="Forced kaolin",
            provider="generic",
            source="test",
            lines=[
                SourceRecipeLine("Soda Ash", 17.27, "base", "generic", 0),
                SourceRecipeLine("Kona F-4 Feldspar", 9.82, "base", "generic", 1),
                SourceRecipeLine("Nepheline Syenite", 40.91, "base", "generic", 2),
                SourceRecipeLine("Edgar Plastic Kaolin", 18.18, "base", "generic", 3),
                SourceRecipeLine("OM4", 13.82, "base", "generic", 4),
            ],
        )
        inventory = StudioInventory()
        inventory.add("Soda Ash", "Soda Ash")
        inventory.add("Minspar", "Minspar")
        inventory.add("Nepheline Syenite", "Neph Sy")
        inventory.add("EPK", "EPK")
        inventory.add("Ione", "Ione Kaolin")
        inventory.add("OM4", "OM4")

        studio_recipe = solve_source_recipe_to_studio(
            db=self.db,
            catalog=self.catalog,
            inventory=inventory,
            mappings=MaterialMappings(),
            recipe=source_recipe,
            max_materials=6,
            substitutions={"EPK": "Ione Kaolin"},
        )

        base_amounts = {line.material: line.amount for line in studio_recipe.lines if line.role == "base"}
        self.assertIn("Ione Kaolin", base_amounts)
        self.assertNotIn("EPK", base_amounts)

    def test_source_recipe_materials_can_compute_imported_recipe_umf_inputs(self) -> None:
        recipe = SourceRecipe.load(ROOT / "recipes" / "md-shino.json")
        materials, unresolved = source_recipe_materials(
            db=self.db,
            catalog=self.catalog,
            mappings=MaterialMappings.load(ROOT / ".umf_state" / "material_mappings.json"),
            recipe=recipe,
        )

        self.assertEqual(unresolved, [])
        self.assertAlmostEqual(materials["Soda Ash"], 17.27, places=6)
        self.assertAlmostEqual(materials["Kona F-4 Feldspar"], 9.82, places=6)
        self.assertAlmostEqual(materials["Neph Sy"], 40.91, places=6)
        self.assertAlmostEqual(materials["EPK"], 18.18, places=6)
        self.assertAlmostEqual(materials["OM4"], 13.82, places=6)
        self.assertAlmostEqual(materials["Red Art"], 6.0, places=6)

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
        inventory.add("Kona F-4 Bag", "Kona F-4 Feldspar")
        inventory.add("Neph Sy", "Neph Sy")
        inventory.add("EPK", "EPK")

        with self.assertRaises(SystemExit):
            render_source_recipe_to_studio(
                db=self.db,
                catalog=self.catalog,
                inventory=inventory,
                mappings=MaterialMappings(),
                recipe=recipe,
            )

    def test_redart_fixture_solve_cannot_resolve_until_missing_canonical_materials_exist(self) -> None:
        recipe = SourceRecipe.load(ROOT / "recipes" / "redart_test.source.json")
        inventory = StudioInventory()
        inventory.add("Soda Ash", "Soda Ash")
        inventory.add("Kona F-4 Bag", "Kona F-4 Feldspar")
        inventory.add("Neph Sy", "Neph Sy")
        inventory.add("EPK", "EPK")

        with self.assertRaises(SystemExit):
            solve_source_recipe_to_studio(
                db=self.db,
                catalog=self.catalog,
                inventory=inventory,
                mappings=MaterialMappings(),
                recipe=recipe,
                max_materials=6,
            )
