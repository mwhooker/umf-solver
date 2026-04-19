import tempfile
import unittest
from pathlib import Path

from importer import import_recipe, write_recipe_csv


ROOT = Path(__file__).resolve().parents[1]


DIGITALFIRE_FIXTURE = """<!doctype html>
<html>
<body>
<h1>G1214M - 20x5 Cone 6 Base Glossy Glaze</h1>
<p>Material Amount</p>
<p>Wollastonite 20.00</p>
<p>Ferro Frit 3134 20.00</p>
<p>Custer Feldspar 20.00</p>
<p>EPK 20.00</p>
<p>Silica 20.00</p>
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
    def test_imports_digitalfire_recipe_from_local_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "digitalfire.html"
            path.write_text(DIGITALFIRE_FIXTURE, encoding="utf-8")

            imported = import_recipe(str(path))

        self.assertEqual(imported.name, "20x5 Cone 6 Base Glossy Glaze")
        self.assertEqual(imported.provider, "digitalfire")
        self.assertEqual(imported.base["Wollastonite"], 20.0)
        self.assertEqual(imported.base["Ferro Frit 3134"], 20.0)
        self.assertEqual(imported.base["Custer Feldspar"], 20.0)
        self.assertFalse(imported.additions)

    def test_imports_glazy_style_text_with_additions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "glazy.txt"
            path.write_text(GLAZY_TEXT_FIXTURE, encoding="utf-8")

            imported = import_recipe(str(path))

        self.assertEqual(imported.name, "Leach 4321 Celadon")
        self.assertEqual(imported.provider, "glazy")
        self.assertEqual(imported.base["Potash Feldspar"], 40.0)
        self.assertEqual(imported.base["Silica"], 30.0)
        self.assertEqual(imported.additions["Red Iron Oxide"], 1.0)

    def test_writes_csv_with_blank_line_for_additions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "glazy.txt"
            csv_path = Path(tmpdir) / "recipe.csv"
            path.write_text(GLAZY_TEXT_FIXTURE, encoding="utf-8")

            imported = import_recipe(str(path))
            write_recipe_csv(csv_path, imported)

            saved = csv_path.read_text(encoding="utf-8")

        self.assertEqual(
            saved,
            "material,parts\n"
            "Potash Feldspar,40\n"
            "Silica,30\n"
            "Whiting,20\n"
            "Kaolin,10\n"
            "\n"
            "Red Iron Oxide,1\n",
        )


if __name__ == "__main__":
    unittest.main()
