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

## Dependencies

The current runtime dependencies are:

- `pandas`
- `ortools`

The old `venv/` can be removed once you're happy with the `uv` workflow.
