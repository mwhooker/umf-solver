import math
import unittest
from pathlib import Path

from constants import DEFAULT_TARGETS, FLUXES_DEFAULT
from db import OxideDB
from recipe import read_recipe_csv
from solver import solve_substitution_milp, split_recipe_fixed_variable
from state import AliasState, InventoryState


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data.csv"
HAMADA_RUST_PATH = ROOT / "recipes" / "hamada_rust.csv"


def resolve_recipe_db_names(
    db: OxideDB,
    alias: AliasState,
    recipe_user: dict[str, float],
) -> dict[str, float]:
    recipe_db: dict[str, float] = {}
    for user_name, parts in recipe_user.items():
        resolved = alias.resolve(user_name, db)
        if resolved is None:
            raise AssertionError(f"Could not resolve recipe material {user_name!r}")
        recipe_db[resolved] = recipe_db.get(resolved, 0.0) + parts
    return recipe_db


class RealWorldExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = OxideDB.load(DB_PATH)

    def test_hamada_rust_umf_matches_reference_values(self) -> None:
        # Source fixture: local Hamada Rust recipe plus the repo's DB chemistry.
        alias = AliasState({"RIO": "Iron Oxide, Red"})
        base_user, colorant_user = read_recipe_csv(HAMADA_RUST_PATH)
        recipe_user = dict(base_user)
        for name, parts in colorant_user.items():
            recipe_user[name] = recipe_user.get(name, 0.0) + parts

        recipe_db = resolve_recipe_db_names(self.db, alias, recipe_user)
        moles = self.db.oxide_moles_from_recipe(recipe_db)
        umf, flux_moles = self.db.umf_from_moles(moles, FLUXES_DEFAULT)

        self.assertAlmostEqual(flux_moles, 0.267982, places=5)
        self.assertAlmostEqual(umf["Na2O"], 0.2409, places=3)
        self.assertAlmostEqual(umf["K2O"], 0.3078, places=3)
        self.assertAlmostEqual(umf["CaO"], 0.4067, places=3)
        self.assertAlmostEqual(umf["Al2O3"], 0.5465, places=3)
        self.assertAlmostEqual(umf["SiO2"], 3.4845, places=3)
        self.assertAlmostEqual(umf["Fe2O3"], 0.1699, places=3)

    def test_colorants_do_not_shrink_base_batch_during_substitution(self) -> None:
        # Source fixture rationale:
        # - Local Hamada Rust recipe with RIO after a blank line (colorant addition).
        # - Mirrors common studio practice and the Glazy/Digitalfire distinction
        #   between a 100-part base glaze and added colorants.
        alias = AliasState({})
        inventory = InventoryState(
            base={
                "Mahavir",
                "Flint",
                "EPK",
                "Whiting",
                "Gerstley Borate",
                "3124 (Frit)",
                "Soda Ash",
            }
        )

        base_user, colorant_user = read_recipe_csv(HAMADA_RUST_PATH)
        fixed_db, variable_db, fixed_total, variable_total = split_recipe_fixed_variable(
            db=self.db,
            alias=AliasState({"RIO": "Iron Oxide, Red"}),
            base_user=base_user,
            colorant_user=colorant_user,
        )
        solution = solve_substitution_milp(
            db=self.db,
            alias=alias,
            inv=inventory,
            fixed_db=fixed_db,
            variable_db=variable_db,
            ban_user_names=[],
            baseline_swap=None,
            max_materials=6,
            targets=DEFAULT_TARGETS,
            fluxes=FLUXES_DEFAULT,
        )

        self.assertAlmostEqual(fixed_total, 7.5, places=6)
        self.assertAlmostEqual(variable_total, 100.0, places=6)
        self.assertAlmostEqual(solution["Iron Oxide, Red"], 7.5, places=6)
        self.assertAlmostEqual(sum(solution.values()), 107.5, places=6)
        self.assertAlmostEqual(
            sum(parts for material, parts in solution.items() if material != "Iron Oxide, Red"),
            100.0,
            places=6,
        )

    def test_alias_resolution_is_case_insensitive_for_stored_aliases(self) -> None:
        alias = AliasState({"Mahavir Feldspar": "Mahavir"})

        self.assertEqual(alias.resolve("Mahavir Feldspar", self.db), "Mahavir")
        self.assertEqual(alias.resolve("mahavir feldspar", self.db), "Mahavir")
        self.assertEqual(alias.resolve("MAHAVIR FELDSPAR", self.db), "Mahavir")

    def test_wollastonite_can_be_recreated_from_whiting_and_flint(self) -> None:
        # Source fixture: Glazy's whiting <-> wollastonite substitution example.
        woll_recipe = {"Wollastonite": 10.0}
        woll_moles = self.db.oxide_moles_from_recipe(woll_recipe)

        ca_from_woll = woll_moles["CaO"]
        si_from_woll = woll_moles["SiO2"]
        ca_per_gram_whiting = self.db.coeffs_moles_per_gram("Whiting")["CaO"]
        si_per_gram_flint = self.db.coeffs_moles_per_gram("Flint")["SiO2"]

        replacement_recipe = {
            "Whiting": ca_from_woll / ca_per_gram_whiting,
            "Flint": si_from_woll / si_per_gram_flint,
        }
        replacement_moles = self.db.oxide_moles_from_recipe(replacement_recipe)

        self.assertAlmostEqual(replacement_moles["CaO"], woll_moles["CaO"], delta=2e-5)
        self.assertAlmostEqual(replacement_moles["SiO2"], woll_moles["SiO2"], delta=2e-5)

    def test_3134_is_not_a_one_to_one_gerstley_borate_substitute(self) -> None:
        # Source fixture: Digitalfire's "Ferro Frit 3134 is NOT A SUBSTITUTE
        # for Gerstley Borate" shows 118 g frit 3134 to match the B2O3 from 100 g GB.
        gb_moles = self.db.oxide_moles_from_recipe({"Gerstley Borate": 100.0})
        frit_moles = self.db.oxide_moles_from_recipe({"3134 (Frit)": 118.0})

        self.assertAlmostEqual(frit_moles["B2O3"], gb_moles["B2O3"], delta=0.05)
        self.assertGreater(frit_moles["Na2O"], gb_moles["Na2O"] * 2.0)
        self.assertGreater(frit_moles["SiO2"], gb_moles["SiO2"] * 2.0)
        self.assertGreater(gb_moles["MgO"], 0.0)
        self.assertTrue(math.isclose(frit_moles.get("MgO", 0.0), 0.0, abs_tol=1e-12))

    def test_nepheline_syenite_substitution_preserves_flux_chemistry(self) -> None:
        # Source fixture rationale:
        # - Digitalfire's nepheline syenite replacement example.
        # - Archived Glazy rule-of-thumb: nepheline can be approximated by potash
        #   feldspar + soda feldspar, then the rest of the recipe rebalanced.
        variable_db = {
            "Neph Sy": 35.0,
            "Flint": 30.0,
            "EPK": 20.0,
            "Whiting": 15.0,
        }
        inventory = InventoryState(base={"Mahavir", "Minspar", "Flint", "EPK", "Whiting"})
        solution = solve_substitution_milp(
            db=self.db,
            alias=AliasState({}),
            inv=inventory,
            fixed_db={},
            variable_db=variable_db,
            ban_user_names=["Neph Sy"],
            baseline_swap=None,
            max_materials=5,
            targets=DEFAULT_TARGETS,
            fluxes=FLUXES_DEFAULT,
        )

        self.assertNotIn("Neph Sy", solution)
        self.assertAlmostEqual(sum(solution.values()), sum(variable_db.values()), places=6)

        original_umf, _ = self.db.umf_from_moles(
            self.db.oxide_moles_from_recipe(variable_db),
            FLUXES_DEFAULT,
        )
        solved_umf, _ = self.db.umf_from_moles(
            self.db.oxide_moles_from_recipe(solution),
            FLUXES_DEFAULT,
        )

        self.assertAlmostEqual(solved_umf["SiO2"], original_umf["SiO2"], delta=0.08)
        self.assertAlmostEqual(solved_umf["Al2O3"], original_umf["Al2O3"], delta=0.05)
        original_r2o = original_umf.get("Na2O", 0.0) + original_umf.get("K2O", 0.0)
        solved_r2o = solved_umf.get("Na2O", 0.0) + solved_umf.get("K2O", 0.0)
        self.assertAlmostEqual(solved_r2o, original_r2o, delta=0.05)


if __name__ == "__main__":
    unittest.main()
