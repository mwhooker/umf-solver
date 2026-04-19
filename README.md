# umf-solver

This repo now uses `uv` for dependency and environment management.

## Quick start

```bash
uv sync
uv run umf db-check
uv run umf umf --recipe recipes/hamada_rust.csv
```

You can also run the module directly:

```bash
uv run python umf.py substitute --recipe recipes/hamada_rust.csv --show-umf
```

## Importing Recipes

You can import a Digitalfire recipe URL or a local text/export file:

```bash
uv run umf import-recipe https://digitalfire.com/recipe/g1214m --save-recipe recipes/g1214m.csv
uv run umf import-recipe /path/to/glazy-export.txt --save-recipe recipes/imported.csv
```

To pull imported ingredient names into your inventory as-is:

```bash
uv run umf import-recipe /path/to/recipe.txt --add-to-inventory
```

To persist unambiguous imported ingredient mappings into your aliases:

```bash
uv run umf import-recipe https://digitalfire.com/recipe/g1214m --write-aliases
```

Note: direct `glazy.org` recipe URLs are JavaScript-driven, so import those by saving/exporting the recipe text locally first.

Imported ingredients are resolved through a small ingredient API layer that combines:

- exact DB names
- your saved aliases
- provider-specific synonyms (e.g. Digitalfire/Glazy naming)
- inventory-aware disambiguation for generic names like `Potash Feldspar`

## Dependencies

The current runtime dependencies are:

- `pandas`
- `ortools`

The old `venv/` can be removed once you're happy with the `uv` workflow.
