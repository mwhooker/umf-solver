#!/usr/bin/env python3
"""
umf.py — Inventory-managed UMF + substitution solver (MILP w/ slack) for ceramic glazes.

Defaults (relative to this script):
  - DB:          ./data.csv
  - State dir:   ./.umf_state/
  - Aliases:     ./.umf_state/aliases.json
  - Inventory:   ./.umf_state/inventory.json

Recipe CSV format:
material,parts
Custer,77
Flint,0.1
Whiting,6.2
EPK,4.3
Gerstley Borate,12.4

Dependencies:
  - pandas
  - ortools (CBC MILP): pip install ortools
No yaml/pyyaml required.

New in this version:
  - substitute: --show-umf prints TARGET / BASELINE / SOLUTION UMF
  - substitute: --show-groups prints Seger group sums (RO, R2O, R2O3, RO2) and ratios
  - umf:        --show-groups prints the same for the single recipe
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Set, Tuple

from constants import DEFAULT_TARGETS, FLUXES_DEFAULT
from db import OxideDB
from recipe import read_recipe_csv
from reporting import print_umf_block
from solver import solve_substitution_milp, split_recipe_fixed_variable
from state import AliasState, InventoryState
from utils import die, normalize, norm_key, parse_list, resolve_oxide_list


# ----------------------------
# Paths & defaults
# ----------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = SCRIPT_DIR / "data.csv"
DEFAULT_STATE_DIR = SCRIPT_DIR / ".umf_state"
DEFAULT_ALIASES_PATH = DEFAULT_STATE_DIR / "aliases.json"
DEFAULT_INVENTORY_PATH = DEFAULT_STATE_DIR / "inventory.json"


# ----------------------------
# Commands
# ----------------------------

def cmd_db_check(args):
    db = OxideDB.load(args.db)
    print(f"DB: {args.db}")
    print(f"  materials: {len(db.all_materials())}")
    print(f"  oxides:    {len(db.oxides)}")
    print("  MW sanity:")
    for ox in ["SiO2", "Al2O3", "Na2O", "K2O", "CaO", "B2O3"]:
        if ox in db.mw:
            print(f"    {ox}: {db.mw[ox]}")
    return 0


def cmd_alias_set(args):
    db = OxideDB.load(args.db)
    alias = AliasState.load(args.aliases)

    user_name = normalize(args.user_name)
    db_name = normalize(args.db_name)

    # Validate db_name exists (try fallback normalization)
    if not db.has_material(db_name):
        nk = norm_key(db_name)
        found = None
        for m in db.all_materials():
            if norm_key(m) == nk:
                found = m
                break
        if found is None:
            die(f"DB material not found: '{db_name}'")
        db_name = found

    alias.aliases[user_name] = db_name
    alias.save(args.aliases)
    print(f"Alias set: '{user_name}' -> '{db_name}'")
    print(f"Saved: {args.aliases}")
    return 0


def cmd_alias_list(args):
    alias = AliasState.load(args.aliases)
    if not alias.aliases:
        print("(no aliases)")
        return 0
    for k in sorted(alias.aliases.keys()):
        print(f"{k} -> {alias.aliases[k]}")
    return 0


def cmd_inventory_add(args):
    db = OxideDB.load(args.db)
    alias = AliasState.load(args.aliases)
    inv = InventoryState.load(args.inventory)

    name = normalize(args.material)
    resolved = alias.resolve(name, db)

    if resolved is None and not args.allow_unresolved:
        die(f"Material '{name}' doesn't resolve to DB. Add an alias first or use --allow-unresolved.")

    inv.base.add(name)
    kind = "base"

    inv.save(args.inventory)
    print(f"Added ({kind}): {name}")
    print(f"Saved: {args.inventory}")
    return 0


def cmd_inventory_remove(args):
    inv = InventoryState.load(args.inventory)
    name = normalize(args.material)
    existed = False
    if name in inv.base:
        inv.base.remove(name)
        existed = True
    if not existed:
        print(f"(not in inventory) {name}")
        return 0
    inv.save(args.inventory)
    print(f"Removed: {name}")
    return 0


def cmd_inventory_list(args):
    inv = InventoryState.load(args.inventory)
    print("Base:")
    for m in sorted(inv.base):
        print(f"  - {m}")
    return 0


def cmd_inventory_report(args):
    db = OxideDB.load(args.db)
    alias = AliasState.load(args.aliases)
    inv = InventoryState.load(args.inventory)

    def report(title: str, items: Set[str]):
        ok, bad = [], []
        for u in sorted(items):
            r = alias.resolve(u, db)
            if r is None:
                bad.append(u)
            else:
                ok.append((u, r))
        print(title)
        for u, r in ok:
            print(f"  OK: '{u}' -> '{r}'")
        for u in bad:
            print(f"  MISSING: '{u}' (add alias)")
        print("")

    report("Base materials:", inv.base)
    return 0


def cmd_umf(args):
    db = OxideDB.load(args.db)
    alias = AliasState.load(args.aliases)

    base_user, colorant_user = read_recipe_csv(args.recipe)
    recipe_user = dict(base_user)
    for k, v in colorant_user.items():
        recipe_user[k] = recipe_user.get(k, 0.0) + v

    # Resolve recipe to DB names
    recipe_db: Dict[str, float] = {}
    for u, p in recipe_user.items():
        r = alias.resolve(u, db)
        if r is None:
            die(f"Recipe material not found: '{u}' (add alias or use exact DB name)")
        recipe_db[r] = recipe_db.get(r, 0.0) + p

    print("Resolved recipe (DB names):")
    for m in sorted(recipe_db.keys()):
        print(f"  {m}: {recipe_db[m]:.6g}")

    flux_raw = parse_list(args.fluxes) if args.fluxes else FLUXES_DEFAULT
    fluxes = resolve_oxide_list(flux_raw, db, allow_r2o=False)

    print_umf_block(db, recipe_db, fluxes, "UMF", show_groups=args.show_groups)
    return 0


def cmd_substitute(args):
    db = OxideDB.load(args.db)
    alias = AliasState.load(args.aliases)
    inv = InventoryState.load(args.inventory)

    base_user, colorant_user = read_recipe_csv(args.recipe)

    ban = parse_list(args.ban) if args.ban else []
    baseline_swap = None
    if args.baseline_swap:
        if "=" not in args.baseline_swap:
            die("--baseline-swap must look like 'A=B'")
        left, right = args.baseline_swap.split("=", 1)
        baseline_swap = (normalize(left), normalize(right))

    target_raw = parse_list(args.targets) if args.targets else DEFAULT_TARGETS
    targets = resolve_oxide_list(target_raw, db, allow_r2o=True)

    flux_raw = parse_list(args.fluxes) if args.fluxes else FLUXES_DEFAULT
    fluxes = resolve_oxide_list(flux_raw, db, allow_r2o=False)

    want_umf = bool(args.show_umf or args.show_groups)

    fixed_db, variable_db, _fixed_total, _var_total = split_recipe_fixed_variable(
        db=db,
        alias=alias,
        base_user=base_user,
        colorant_user=colorant_user,
    )

    # Full recipe for TARGET UMF (fixed + variable)
    recipe_db_full = dict(fixed_db)
    for k, v in variable_db.items():
        recipe_db_full[k] = recipe_db_full.get(k, 0.0) + v

    if want_umf:
        print_umf_block(db, recipe_db_full, fluxes, "TARGET UMF (original recipe)", show_groups=args.show_groups)

        # Baseline is variable-only with swap applied, then combined with fixed colorants
        baseline_var = dict(variable_db)
        if baseline_swap is not None:
            left_user, right_user = baseline_swap
            left_db = alias.resolve(left_user, db) or left_user
            right_db = alias.resolve(right_user, db) or right_user
            moved = baseline_var.get(left_db, 0.0)
            baseline_var[left_db] = 0.0
            baseline_var[right_db] = baseline_var.get(right_db, 0.0) + moved

        baseline_full = dict(fixed_db)
        for k, v in baseline_var.items():
            baseline_full[k] = baseline_full.get(k, 0.0) + v

        print_umf_block(db, baseline_full, fluxes, "BASELINE UMF (after swap)", show_groups=args.show_groups)

    sol = solve_substitution_milp(
        db=db,
        alias=alias,
        inv=inv,
        fixed_db=fixed_db,
        variable_db=variable_db,
        ban_user_names=ban,
        baseline_swap=baseline_swap,
        max_materials=int(args.max_materials),
        targets=targets,
        fluxes=fluxes,
    )

    print("\nSubstitution result (DB names):")
    total = sum(sol.values())
    for m in sorted(sol.keys()):
        print(f"  {m}: {sol[m]:.4f}")
    print(f"  TOTAL: {total:.4f}")

    if want_umf:
        print_umf_block(db, sol, fluxes, "SOLUTION UMF (optimized)", show_groups=args.show_groups)

    return 0


# ----------------------------
# CLI
# ----------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="umf.py", add_help=True)

    p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                   help=f"Path to DB CSV (default: {DEFAULT_DB_PATH})")
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR,
                   help=f"State directory (default: {DEFAULT_STATE_DIR})")
    p.add_argument("--aliases", type=Path, default=None,
                   help="Aliases JSON path (default: <state-dir>/aliases.json)")
    p.add_argument("--inventory", type=Path, default=None,
                   help="Inventory JSON path (default: <state-dir>/inventory.json)")

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("db-check", help="Load DB and print basic info.")
    sp.set_defaults(func=cmd_db_check)

    # alias
    sp = sub.add_parser("alias", help="Manage aliases.")
    sub2 = sp.add_subparsers(dest="alias_cmd", required=True)

    sp2 = sub2.add_parser("set", help="Set an alias: user_name -> db_name")
    sp2.add_argument("user_name")
    sp2.add_argument("db_name")
    sp2.set_defaults(func=cmd_alias_set)

    sp2 = sub2.add_parser("list", help="List aliases")
    sp2.set_defaults(func=cmd_alias_list)

    # inventory
    sp = sub.add_parser("inventory", help="Manage persistent inventory.")
    sub2 = sp.add_subparsers(dest="inv_cmd", required=True)

    sp2 = sub2.add_parser("add", help="Add a material to inventory base.")
    sp2.add_argument("material")
    sp2.add_argument("--allow-unresolved", action="store_true", help="Allow adding even if no DB/alias match yet.")
    sp2.set_defaults(func=cmd_inventory_add)

    sp2 = sub2.add_parser("remove", help="Remove a material from inventory.")
    sp2.add_argument("material")
    sp2.set_defaults(func=cmd_inventory_remove)

    sp2 = sub2.add_parser("list", help="List inventory.")
    sp2.set_defaults(func=cmd_inventory_list)

    sp2 = sub2.add_parser("report", help="Report resolution vs DB.")
    sp2.set_defaults(func=cmd_inventory_report)

    # umf
    sp = sub.add_parser("umf", help="Compute UMF for a recipe CSV.")
    sp.add_argument("--recipe", type=Path, required=True)
    sp.add_argument("--fluxes", default=",".join(FLUXES_DEFAULT), help="Comma list of flux oxides")
    sp.add_argument("--show-groups", action="store_true",
                    help="Print Seger group sums (RO, R2O, R2O3, RO2) and ratios")
    sp.set_defaults(func=cmd_umf)

    # substitute
    sp = sub.add_parser("substitute", help="Solve substitution MILP using inventory base materials.")
    sp.add_argument("--recipe", type=Path, required=True)
    sp.add_argument("--ban", default="", help="Comma list of unavailable materials (user or DB names)")
    sp.add_argument("--baseline-swap", default="", help="Baseline swap like 'Custer=Mahavir Feldspar'")
    sp.add_argument("--max-materials", default="6", help="Max number of materials in output recipe")
    sp.add_argument("--targets", default=",".join(DEFAULT_TARGETS), help="UMF targets to match with slack")
    sp.add_argument("--fluxes", default=",".join(FLUXES_DEFAULT), help="Comma list of flux oxides")
    sp.add_argument("--show-umf", action="store_true",
                    help="Print target, baseline, and solution UMF blocks")
    sp.add_argument("--show-groups", action="store_true",
                    help="Also print Seger group sums (RO, R2O, R2O3, RO2) and ratios within UMF blocks")
    sp.set_defaults(func=cmd_substitute)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Fill default state paths from state-dir if not explicitly provided
    state_dir: Path = args.state_dir
    aliases_path: Path = args.aliases or (state_dir / "aliases.json")
    inventory_path: Path = args.inventory or (state_dir / "inventory.json")

    # Attach resolved paths to args for downstream commands
    args.db = args.db
    args.aliases = aliases_path
    args.inventory = inventory_path

    # Ensure state dir exists (lazy-create files on save)
    state_dir.mkdir(parents=True, exist_ok=True)

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
