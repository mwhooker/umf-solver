# umf-solver

`umf-solver` imports glaze recipes from outside sources, preserves them as source recipes, and turns them into studio recipes using your local inventory plus UMF-driven reformulation when needed.

The project uses `uv` for environment management.

## Quick start

```bash
uv sync
uv run umf db-check
```

## Core model

- `SourceRecipe` is the first-class imported object.
- `StudioRecipe` is derived at run time from the source recipe.
- Generic concepts like `Potash Feldspar` stay distinct from canonical materials like `Custer` or `Mahavir`.
- Studio inventory entries like `Silica 325M` and `Silica 200M` stay distinct even if they map to the same canonical material.
- Additions/colorants are preserved separately from the 100-part base recipe.

## Studio inventory

Studio inventory entries map your local labels to canonical materials from `data.csv`.

```bash
uv run umf inventory add "Silica 325M" --material Flint
uv run umf inventory add "Mahavir Feldspar" --material Mahavir
uv run umf inventory inspect
```

## Confirmed mappings

Generic imported terms do not silently collapse to a specific material. If you want a source term to resolve to one material in your studio, confirm it explicitly:

```bash
uv run umf mapping set "Potash Feldspar" Mahavir
uv run umf mapping list
```

## Ingredient resolution

Inspect how imported terms resolve against concepts, canonical materials, studio inventory, and confirmed mappings:

```bash
uv run umf ingredient resolve --provider glazy "Potash Feldspar" "Silica" "Red Iron Oxide"
```

## Importing recipes

You can import:

- a Digitalfire recipe URL
- a local text or export file

```bash
uv run umf import-recipe https://digitalfire.com/recipe/g1214m
uv run umf import-recipe /path/to/glazy-export.txt --save-recipe recipes/g1214m.source.json
```

`import-recipe` preserves:

- original ingredient names
- line order
- base vs addition roles
- provider/source metadata

It prints a separate resolution analysis, but it does not mutate inventory or mappings.

Note: direct `glazy.org` recipe pages are JavaScript-driven, so the supported Glazy path is still importing saved/exported recipe text.

## Rendering and solving recipes

Recipe commands accept:

- source recipe JSON saved by `import-recipe`
- plain-text recipe files like `recipes/md-shino.txt`
- legacy recipe CSV files using `material,parts`

`render` shows a 1:1 studio recipe using exact matches, material synonyms, confirmed mappings, and explicit direct substitutions:

```bash
uv run umf recipe render recipes/md-shino.txt
uv run umf recipe render recipes/md-shino.txt --batch 1000 --batch-unit g
```

`solve` uses your studio inventory as the allowed base materials and UMF-rebalances the whole base recipe:

```bash
uv run umf recipe solve recipes/md-shino.txt
uv run umf recipe solve recipes/md-shino.txt --batch 100 --batch-unit oz
```

Important behavior:

- additions are preserved on top and are not routinely substituted
- `render` is strict 1:1 substitution
- `solve` rebalances the full base recipe instead of only swapping one line
- generic concepts like `Potash Feldspar` still require explicit confirmation before resolution

## Tests

Run the test suite with:

```bash
UV_CACHE_DIR=.uv-cache uv run --no-sync python -m unittest discover -s tests -v
```
