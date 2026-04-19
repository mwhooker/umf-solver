# umf-solver

`umf-solver` imports glaze recipes from outside sources, preserves them as source recipes, and resolves them into studio recipes using your local inventory plus UMF-driven reformulation when needed.

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

Generic imported terms do not silently collapse to a specific material. If you want a provider-specific source term to resolve to one material in your studio, confirm it explicitly:

```bash
uv run umf mapping set --provider glazy "Potash Feldspar" Mahavir
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

## Resolving a source recipe into a studio recipe

Resolve a saved source recipe into a studio recipe using exact matches, confirmed mappings, explicit direct substitution rules, and UMF-driven reformulation for unresolved base materials.

```bash
uv run umf recipe resolve recipes/g1214m.source.json
```

Important behavior:

- additions are preserved on top and are not routinely substituted
- generic concepts like `Potash Feldspar` require explicit confirmation before resolution
- same-concept materials do not auto-substitute without an explicit rule

## Tests

Run the test suite with:

```bash
UV_CACHE_DIR=.uv-cache uv run --no-sync python -m unittest discover -s tests -v
```
