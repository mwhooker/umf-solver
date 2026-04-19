import unittest
from pathlib import Path

from db import OxideDB
from ingredient_api import IngredientResolver
from state import AliasState, InventoryState


ROOT = Path(__file__).resolve().parents[1]


class IngredientResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db = OxideDB.load(ROOT / "data.csv")

    def test_digitalfire_specific_name_maps_to_local_db_name(self) -> None:
        resolver = IngredientResolver(self.db, AliasState({}))

        match = resolver.resolve("Ferro Frit 3134", provider="digitalfire")

        self.assertEqual(match.status, "resolved")
        self.assertEqual(match.resolved_name, "3134 (Frit)")
        self.assertEqual(match.source, "digitalfire")

    def test_generic_name_uses_inventory_to_break_tie(self) -> None:
        resolver = IngredientResolver(
            self.db,
            AliasState({"Mahavir Feldspar": "Mahavir"}),
            InventoryState(base={"Mahavir Feldspar"}),
        )

        match = resolver.resolve("Potash Feldspar", provider="glazy")

        self.assertEqual(match.status, "resolved")
        self.assertEqual(match.resolved_name, "Mahavir")

    def test_generic_name_without_inventory_returns_ambiguous_candidates(self) -> None:
        resolver = IngredientResolver(self.db, AliasState({}))

        match = resolver.resolve("Potash Feldspar", provider="glazy")

        self.assertEqual(match.status, "ambiguous")
        self.assertIn("Custer", match.candidates)
        self.assertIn("Mahavir", match.candidates)

    def test_existing_alias_beats_provider_synonym(self) -> None:
        resolver = IngredientResolver(
            self.db,
            AliasState({"Silica": "Flint"}),
            InventoryState(base={"Silica 325M"}),
        )

        match = resolver.resolve("Silica", provider="glazy")

        self.assertEqual(match.status, "resolved")
        self.assertEqual(match.resolved_name, "Flint")
        self.assertEqual(match.source, "db-or-alias")


if __name__ == "__main__":
    unittest.main()
