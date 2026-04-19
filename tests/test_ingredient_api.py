import unittest
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from contextlib import redirect_stdout

from db import OxideDB
from ingredient_api import IngredientResolver
from state import AliasState, InventoryState
from umf import cmd_ingredient_resolve


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

    def test_cli_resolve_prints_ambiguous_candidates(self) -> None:
        with tempfile_alias_inventory(self.db) as (aliases_path, inventory_path):
            args = SimpleNamespace(
                db=ROOT / "data.csv",
                aliases=aliases_path,
                inventory=inventory_path,
                provider="glazy",
                ingredients=["Potash Feldspar"],
            )
            out = StringIO()
            with redirect_stdout(out):
                cmd_ingredient_resolve(args)

        text = out.getvalue()
        self.assertIn("status: ambiguous", text)
        self.assertIn("candidates: Custer, Mahavir", text)

    def test_cli_resolve_uses_inventory_context(self) -> None:
        with tempfile_alias_inventory(
            self.db,
            aliases={"Mahavir Feldspar": "Mahavir"},
            inventory=["Mahavir Feldspar"],
        ) as (aliases_path, inventory_path):
            args = SimpleNamespace(
                db=ROOT / "data.csv",
                aliases=aliases_path,
                inventory=inventory_path,
                provider="glazy",
                ingredients=["Potash Feldspar"],
            )
            out = StringIO()
            with redirect_stdout(out):
                cmd_ingredient_resolve(args)

        text = out.getvalue()
        self.assertIn("status: resolved", text)
        self.assertIn("resolved: Mahavir", text)


class tempfile_alias_inventory:
    def __init__(self, db, aliases=None, inventory=None):
        self.aliases = aliases or {}
        self.inventory = inventory or []

    def __enter__(self):
        import json
        import tempfile

        self.tmpdir = tempfile.TemporaryDirectory()
        aliases_path = Path(self.tmpdir.name) / "aliases.json"
        inventory_path = Path(self.tmpdir.name) / "inventory.json"
        aliases_path.write_text(json.dumps({"aliases": self.aliases}), encoding="utf-8")
        inventory_path.write_text(json.dumps({"base": self.inventory}), encoding="utf-8")
        return aliases_path, inventory_path

    def __exit__(self, exc_type, exc, tb):
        self.tmpdir.cleanup()
        return False


if __name__ == "__main__":
    unittest.main()
