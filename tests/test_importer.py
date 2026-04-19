import tempfile
import unittest
from pathlib import Path

from importer import import_recipe
from ontology import SourceRecipe


DIGITALFIRE_FIXTURE = """<!doctype html>
<html>
<body>
<h1>G1214M - 20x5 Cone 6 Base Glossy Glaze</h1>
<div>
<?xml version="1.0"?>
<recipes version="1.0" encoding="UTF-8">
<recipe name="20x5 Cone 6 Base Glossy Glaze" id="37">
<recipelines>
<recipeline material="Wollastonite" amount="20.000"/>
<recipeline material="Ferro Frit 3134" amount="20.000"/>
<recipeline material="Custer Feldspar" amount="20.000"/>
<recipeline material="EPK" amount="20.000"/>
<recipeline material="Silica" amount="20.000"/>
</recipelines>
</recipe>
</recipes>
</div>
</body>
</html>
"""


GLAZY_TEXT_FIXTURE = """Leach 4321 Celadon

40 Potash Feldspar
30 Silica
20 Whiting
10 Kaolin

Added
1 Red Iron Oxide
"""


class ImporterTests(unittest.TestCase):
    def test_import_digitalfire_preserves_source_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "digitalfire.html"
            path.write_text(DIGITALFIRE_FIXTURE, encoding="utf-8")
            recipe = import_recipe(str(path))

        self.assertEqual(recipe.name, "20x5 Cone 6 Base Glossy Glaze")
        self.assertEqual(recipe.provider, "digitalfire")
        self.assertEqual([line.original_name for line in recipe.lines], [
            "Wollastonite",
            "Ferro Frit 3134",
            "Custer Feldspar",
            "EPK",
            "Silica",
        ])
        self.assertTrue(all(line.role == "base" for line in recipe.lines))

    def test_import_glazy_text_preserves_base_and_addition_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "glazy.txt"
            path.write_text(GLAZY_TEXT_FIXTURE, encoding="utf-8")
            recipe = import_recipe(str(path))

        self.assertEqual(recipe.name, "Leach 4321 Celadon")
        self.assertEqual(recipe.provider, "glazy")
        self.assertEqual([line.role for line in recipe.lines], ["base", "base", "base", "base", "addition"])
        self.assertEqual(recipe.lines[-1].original_name, "Red Iron Oxide")
        self.assertEqual(recipe.lines[-1].amount, 1.0)

    def test_source_recipe_round_trips_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "glazy.txt"
            save_path = Path(tmpdir) / "recipe.json"
            path.write_text(GLAZY_TEXT_FIXTURE, encoding="utf-8")
            recipe = import_recipe(str(path))
            recipe.save(save_path)
            loaded = SourceRecipe.load(save_path)

        self.assertEqual(loaded.name, recipe.name)
        self.assertEqual(loaded.provider, recipe.provider)
        self.assertEqual([(line.original_name, line.role) for line in loaded.lines],
                         [(line.original_name, line.role) for line in recipe.lines])
