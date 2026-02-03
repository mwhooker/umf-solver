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
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set

import pandas as pd

try:
    from ortools.linear_solver import pywraplp
except Exception:
    pywraplp = None


# ----------------------------
# Paths & defaults
# ----------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = SCRIPT_DIR / "data.csv"
DEFAULT_STATE_DIR = SCRIPT_DIR / ".umf_state"
DEFAULT_ALIASES_PATH = DEFAULT_STATE_DIR / "aliases.json"
DEFAULT_INVENTORY_PATH = DEFAULT_STATE_DIR / "inventory.json"

# Flux set used for unity normalization (Seger fluxes)
FLUXES_DEFAULT = ["Li2O", "Na2O", "K2O", "MgO", "CaO", "SrO", "BaO", "ZnO"]

# Default target set for substitution (tune as you like)
DEFAULT_TARGETS = ["SiO2", "Al2O3", "B2O3", "CaO", "R2O"]  # R2O = Na2O + K2O

INTERNAL_SLACK_WEIGHTS = {"SiO2": 3.0, "Al2O3": 3.0, "B2O3": 2.0, "CaO": 2.0, "R2O": 2.0}


# Objective weights (tuneable)
DEFAULT_DEV_WEIGHT = 1000.0         # huge: stay close to baseline


# ----------------------------
# Utilities
# ----------------------------

def die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def normalize(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s

def norm_key(s: str) -> str:
    """Aggressive normalization for matching keys."""
    s = s.strip().lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def load_json(path: Path, default_obj) -> dict:
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return default_obj

def save_json(path: Path, obj: dict) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=False)

def parse_kv(s: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not s:
        return out
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            die(f"Bad key=value list: {s}")
        k, v = part.split("=", 1)
        out[normalize(k)] = float(v.strip())
    return out

def parse_list(s: str) -> List[str]:
    return [normalize(x) for x in s.split(",") if x.strip()]

def read_recipe_csv(path: Path) -> Dict[str, float]:
    recipe: Dict[str, float] = {}
    with path.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if not r.fieldnames or "material" not in r.fieldnames or "parts" not in r.fieldnames:
            die("Recipe CSV must have headers: material,parts")
        for row in r:
            m = normalize(row["material"])
            p = float(row["parts"])
            recipe[m] = recipe.get(m, 0.0) + p
    return recipe


# ----------------------------
# DB loading + chemistry
# ----------------------------

@dataclass
class OxideDB:
    mw: Dict[str, float]                 # oxide -> g/mol
    materials: pd.DataFrame              # index = material, oxide columns wt% per 100g
    oxides: List[str]                    # oxide names

    @staticmethod
    def load(db_path: Path) -> "OxideDB":
        if not db_path.exists():
            die(f"DB not found at {db_path}. Put data.csv next to this script or pass --db.")
        df = pd.read_csv(db_path).rename(columns={"Unnamed: 0": "Material"})
        if "Material" not in df.columns:
            die("DB CSV missing 'Unnamed: 0' column (expected Matrix-style format).")

        oxide_cols = [c for c in df.columns if c not in ["Material", "Total"]]
        mw_row = df.iloc[0]
        mw: Dict[str, float] = {}
        for ox in oxide_cols:
            v = mw_row.get(ox)
            if pd.isna(v):
                continue
            mw[ox] = float(v)

        materials = df.iloc[1:].set_index("Material")
        for ox in oxide_cols:
            if ox in materials.columns:
                materials[ox] = pd.to_numeric(materials[ox], errors="coerce")

        return OxideDB(mw=mw, materials=materials, oxides=list(mw.keys()))

    def has_material(self, name: str) -> bool:
        return name in self.materials.index

    def all_materials(self) -> List[str]:
        return self.materials.index.tolist()

    def coeffs_moles_per_gram(self, material: str) -> Dict[str, float]:
        """a[o] = moles oxide o per gram material"""
        row = self.materials.loc[material]
        a: Dict[str, float] = {}
        for ox, mwv in self.mw.items():
            pct = row.get(ox)
            if pct is None or pd.isna(pct):
                continue
            a[ox] = (float(pct) / 100.0) / mwv
        return a

    def oxide_moles_from_recipe(self, recipe_db_names: Dict[str, float]) -> Dict[str, float]:
        moles: Dict[str, float] = {ox: 0.0 for ox in self.oxides}
        for mat, grams in recipe_db_names.items():
            if grams == 0:
                continue
            a = self.coeffs_moles_per_gram(mat)
            for ox, k in a.items():
                moles[ox] += grams * k
        return {ox: v for ox, v in moles.items() if abs(v) > 1e-12}

    def umf_from_moles(self, moles: Dict[str, float], fluxes: List[str]) -> Tuple[Dict[str, float], float]:
        F = sum(moles.get(f, 0.0) for f in fluxes)
        if F <= 0:
            die("Flux sum is zero; cannot compute UMF (no flux oxides present).")
        return {ox: moles.get(ox, 0.0) / F for ox in moles.keys()}, F


# ----------------------------
# Alias + inventory state
# ----------------------------

@dataclass
class AliasState:
    aliases: Dict[str, str] = field(default_factory=dict)  # user_name -> db_name

    @staticmethod
    def load(path: Path) -> "AliasState":
        data = load_json(path, default_obj={})
        raw = data.get("aliases", {}) if isinstance(data, dict) else {}
        out: Dict[str, str] = {}
        for k, v in raw.items():
            out[normalize(k)] = normalize(v)
        return AliasState(out)

    def save(self, path: Path) -> None:
        save_json(path, {"aliases": self.aliases})

    def resolve(self, user_name: str, db: OxideDB) -> Optional[str]:
        """Resolve user_name to a DB material name."""
        u = normalize(user_name)
        if db.has_material(u):
            return u
        if u in self.aliases and db.has_material(self.aliases[u]):
            return self.aliases[u]
        nk = norm_key(u)
        for m in db.all_materials():
            if norm_key(m) == nk:
                return m
        return None


@dataclass
class InventoryState:
    base: Set[str] = field(default_factory=set)       # user-facing names
    additions: Set[str] = field(default_factory=set)  # user-facing names

    @staticmethod
    def load(path: Path) -> "InventoryState":
        data = load_json(path, default_obj={})
        base = set(normalize(x) for x in (data.get("base", []) if isinstance(data, dict) else []))
        additions = set(normalize(x) for x in (data.get("additions", []) if isinstance(data, dict) else []))
        return InventoryState(base=base, additions=additions)

    def save(self, path: Path) -> None:
        save_json(path, {"base": sorted(self.base), "additions": sorted(self.additions)})


# ----------------------------
# Seger groups + reporting
# ----------------------------

# Classic Seger groupings (you can tweak as desired)
SEGER_RO   = ["MgO", "CaO", "SrO", "BaO", "ZnO"]       # RO fluxes (divalents)
SEGER_R2O  = ["Li2O", "Na2O", "K2O"]                   # R2O fluxes (monovalents)
SEGER_R2O3 = ["Al2O3", "B2O3", "Fe2O3"]                # intermediates/viscosity group (B2O3 is special-case but often here)
SEGER_RO2  = ["SiO2", "TiO2"]                          # glass formers

def seger_group_sums(umf: Dict[str, float]) -> Dict[str, float]:
    ro = sum(umf.get(o, 0.0) for o in SEGER_RO)
    r2o = sum(umf.get(o, 0.0) for o in SEGER_R2O)
    r2o3 = sum(umf.get(o, 0.0) for o in SEGER_R2O3)
    ro2 = sum(umf.get(o, 0.0) for o in SEGER_RO2)
    return {"RO": ro, "R2O": r2o, "R2O3": r2o3, "RO2": ro2}

def print_umf_block(db, recipe_db: Dict[str, float], fluxes: List[str], label: str, show_groups: bool) -> Dict[str, float]:
    moles = db.oxide_moles_from_recipe(recipe_db)
    umf, F = db.umf_from_moles(moles, fluxes)

    print(f"\n{label}")
    print(f"  Flux moles: {F:.6f}")
    for ox in ["Na2O","K2O","CaO","MgO","B2O3","Al2O3","SiO2","Fe2O3","TiO2"]:
        if ox in umf and abs(umf[ox]) > 1e-8:
            print(f"  {ox:6s}: {umf[ox]:.4f}")

    if show_groups:
        g = seger_group_sums(umf)
        ro = g["RO"]
        r2o = g["R2O"]
        r2o3 = g["R2O3"]
        ro2 = g["RO2"]
        flux_total = ro + r2o  # should be ~1.0 by UMF normalization, aside from floating error

        def safe_div(a: float, b: float) -> float:
            return a / b if abs(b) > 1e-12 else float("nan")

        print("\n  Seger group sums (UMF):")
        print(f"    RO   : {ro:.4f}")
        print(f"    R2O  : {r2o:.4f}")
        print(f"    R2O3 : {r2o3:.4f}")
        print(f"    RO2  : {ro2:.4f}")
        print(f"    Flux (RO+R2O): {flux_total:.4f}")

        print("\n  Group ratios:")
        print(f"    RO/R2O       : {safe_div(ro, r2o):.4f}")
        print(f"    (RO+R2O)/R2O3 : {safe_div(flux_total, r2o3):.4f}")
        print(f"    RO2/R2O3      : {safe_div(ro2, r2o3):.4f}")
        print(f"    RO2/(RO+R2O)  : {safe_div(ro2, flux_total):.4f}")

    return umf


def split_recipe_fixed_variable(
    db: OxideDB,
    alias: AliasState,
    inv: InventoryState,
    recipe_user: Dict[str, float],
) -> Tuple[Dict[str, float], Dict[str, float], float, float]:
    """
    Returns (fixed_db, variable_db, fixed_total_parts, variable_total_parts)

    fixed_db:    DB-name -> parts (materials listed in inventory.additions)
    variable_db: DB-name -> parts (everything else)
    """
    additions_db: Set[str] = set()
    for u in inv.additions:
        r = alias.resolve(u, db)
        if r is None:
            # Allow unresolved additions in inventory, but if they appear in recipe, we'll error below.
            continue
        additions_db.add(r)

    fixed_db: Dict[str, float] = {}
    variable_db: Dict[str, float] = {}

    for u, p in recipe_user.items():
        r = alias.resolve(u, db)
        if r is None:
            die(f"Recipe material not found: '{u}' (add alias or use exact DB name)")
        if r in additions_db:
            fixed_db[r] = fixed_db.get(r, 0.0) + p
        else:
            variable_db[r] = variable_db.get(r, 0.0) + p

    fixed_total = sum(fixed_db.values())
    var_total = sum(variable_db.values())
    return fixed_db, variable_db, fixed_total, var_total


# ----------------------------
# MILP solver
# ----------------------------

def solve_substitution_milp(
    db: OxideDB,
    alias: AliasState,
    inv: InventoryState,
    fixed_db: Dict[str, float],
    variable_db: Dict[str, float],
    ban_user_names: List[str],
    baseline_swap: Optional[Tuple[str, str]],
    max_materials: int,
    targets: List[str],
    fluxes: List[str],
    dev_weight: float,
) -> Dict[str, float]:
    """
    Default behavior is lexicographic:
      (1) minimize UMF mismatch (weighted slack)
      (2) minimize # of new materials
      (3) minimize recipe deviation (L1 vs baseline)
    Flags dev_weight/new_mat_penalty/slack_weight are kept for compatibility but are not the primary mechanism.
    """
    if pywraplp is None:
        die("ortools is required. Install with: python3 -m pip install ortools")

    # Target UMF from original (full) recipe: fixed + variable
    recipe_full = dict(fixed_db)
    for k, v in variable_db.items():
        recipe_full[k] = recipe_full.get(k, 0.0) + v

    orig_moles = db.oxide_moles_from_recipe(recipe_full)
    orig_umf, _ = db.umf_from_moles(orig_moles, fluxes)

    # Fixed oxide moles and mass
    fixed_moles = db.oxide_moles_from_recipe(fixed_db)
    fixed_mass = sum(fixed_db.values())

    # Allowed materials = inventory base (resolved to DB names)
    allowed_db: Set[str] = set()
    unresolved: List[str] = []
    for u in sorted(inv.base):
        r = alias.resolve(u, db)
        if r is None:
            unresolved.append(u)
        else:
            allowed_db.add(r)
    if unresolved:
        die("Inventory base has unresolved materials (add aliases):\n  - " + "\n  - ".join(unresolved))
    if not allowed_db:
        die("Inventory base is empty. Add materials via: inventory add --base 'Name'")

    # Ban list resolved
    banned_db: Set[str] = set()
    for u in ban_user_names:
        r = alias.resolve(u, db)
        if r is None:
            if db.has_material(u):
                r = u
            else:
                die(f"Ban material not found: '{u}'")
        banned_db.add(r)

    allowed_db = {m for m in allowed_db if m not in banned_db}
    if not allowed_db:
        die("After banning, no allowed materials remain in inventory base.")

    mats = sorted(allowed_db)

    solver = pywraplp.Solver.CreateSolver("CBC")
    if solver is None:
        die("Failed to create CBC solver (ortools install issue).")

    # Decision vars
    x = {m: solver.NumVar(0.0, solver.infinity(), f"x[{m}]") for m in mats}
    y = {m: solver.IntVar(0, 1, f"y[{m}]") for m in mats}

    # Ingredient cap and on/off coupling
    M = 100.0
    for m in mats:
        solver.Add(x[m] <= M * y[m])
    solver.Add(sum(y[m] for m in mats) <= int(max_materials))

    # Total mass = 100 - fixed additions
    variable_mass_target = 100.0 - fixed_mass
    if variable_mass_target <= 0.0:
        die(f"Fixed additions sum to {fixed_mass:.6g}, leaving no mass for base materials.")
    solver.Add(sum(x[m] for m in mats) == variable_mass_target)

    # Baseline (variable-only, DB names), including baseline swap if provided
    baseline_db = dict(variable_db)
    if baseline_swap is not None:
        left_user, right_user = baseline_swap
        left = alias.resolve(left_user, db) or left_user
        right = alias.resolve(right_user, db) or right_user
        if not db.has_material(left):
            die(f"Baseline swap left not in DB: '{left_user}' -> '{left}'")
        if not db.has_material(right):
            die(f"Baseline swap right not in DB: '{right_user}' -> '{right}'")
        moved = baseline_db.get(left, 0.0)
        baseline_db[left] = 0.0
        baseline_db[right] = baseline_db.get(right, 0.0) + moved

    core_set = {m for m, v in baseline_db.items() if abs(v) > 1e-9}

    # Oxide mole expressions
    a = {m: db.coeffs_moles_per_gram(m) for m in mats}

    def n_ox(ox: str):
        return float(fixed_moles.get(ox, 0.0)) + sum(a[m].get(ox, 0.0) * x[m] for m in mats)

    # Flux sum for UMF normalization
    F = sum(n_ox(f) for f in fluxes)
    solver.Add(F >= 1e-9)

    # Slack vars for UMF targets
    splus, sminus = {}, {}
    for t in targets:
        splus[t] = solver.NumVar(0.0, solver.infinity(), f"splus[{t}]")
        sminus[t] = solver.NumVar(0.0, solver.infinity(), f"sminus[{t}]")

    # UMF constraints with slack:
    # n_target - target*F == s+ - s-
    for t in targets:
        if t == "R2O":
            t_val = float(orig_umf.get("Na2O", 0.0) + orig_umf.get("K2O", 0.0))
            solver.Add((n_ox("Na2O") + n_ox("K2O")) - t_val * F == splus[t] - sminus[t])
        else:
            t_val = float(orig_umf.get(t, 0.0))
            solver.Add(n_ox(t) - t_val * F == splus[t] - sminus[t])

    # Deviation from baseline (L1)
    dplus, dminus = {}, {}
    for m in mats:
        dplus[m] = solver.NumVar(0.0, solver.infinity(), f"dplus[{m}]")
        dminus[m] = solver.NumVar(0.0, solver.infinity(), f"dminus[{m}]")
        b = float(baseline_db.get(m, 0.0))
        solver.Add(x[m] - b == dplus[m] - dminus[m])

    # New material count (materials not in baseline core)
    new_mats = solver.NumVar(0.0, solver.infinity(), "new_mats")
    solver.Add(new_mats == sum(y[m] for m in mats if m not in core_set))

    # Weighted slack score S (primary objective)
    S = solver.NumVar(0.0, solver.infinity(), "S")
    solver.Add(
        S == sum(float(INTERNAL_SLACK_WEIGHTS.get(t, 1.0)) * (splus[t] + sminus[t]) for t in targets)
    )


    # --------------------------
    # Stage 1: minimize slack S
    # --------------------------
    obj = solver.Objective()
    obj.SetCoefficient(S, 1.0)
    obj.SetMinimization()
    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        die("MILP infeasible or solver error in stage-1 (slack minimization).")

    S_star = S.solution_value()

    # Constrain to (near) best slack
    # CBC is floating-point; keep a small tolerance to avoid numeric churn.
    tol = 1e-7
    solver.Add(S <= S_star + tol)

    # -------------------------------
    # Stage 2: minimize new materials
    # -------------------------------
    obj = solver.Objective()
    obj.SetCoefficient(new_mats, 1.0)
    obj.SetMinimization()
    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        die("Solver error in stage-2 (min new materials).")

    new_star = new_mats.solution_value()
    solver.Add(new_mats <= new_star + 1e-9)

    # ---------------------------------------
    # Stage 3: minimize deviation from baseline
    # ---------------------------------------
    obj = solver.Objective()
    # dev_weight retained (this is now the correct place to use it)
    for m in mats:
        obj.SetCoefficient(dplus[m], dev_weight)
        obj.SetCoefficient(dminus[m], dev_weight)
    obj.SetMinimization()

    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        die("Solver error in stage-3 (min deviation).")

    sol_var = {m: x[m].solution_value() for m in mats if x[m].solution_value() > 1e-6}
    sol_full = dict(fixed_db)
    for k, v in sol_var.items():
        sol_full[k] = sol_full.get(k, 0.0) + v
    return sol_full


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

    if args.base:
        inv.base.add(name)
        inv.additions.discard(name)
        kind = "base"
    else:
        inv.additions.add(name)
        inv.base.discard(name)
        kind = "addition"

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
    if name in inv.additions:
        inv.additions.remove(name)
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
    print("\nAdditions:")
    for m in sorted(inv.additions):
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
    report("Additions:", inv.additions)
    return 0

def cmd_umf(args):
    db = OxideDB.load(args.db)
    alias = AliasState.load(args.aliases)

    recipe_user = read_recipe_csv(args.recipe)

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

    fluxes = parse_list(args.fluxes) if args.fluxes else FLUXES_DEFAULT
    # This prints a compact UMF selection plus groups if requested
    print_umf_block(db, recipe_db, fluxes, "UMF", show_groups=args.show_groups)
    return 0

def cmd_substitute(args):
    db = OxideDB.load(args.db)
    alias = AliasState.load(args.aliases)
    inv = InventoryState.load(args.inventory)

    recipe_user = read_recipe_csv(args.recipe)

    ban = parse_list(args.ban) if args.ban else []
    baseline_swap = None
    if args.baseline_swap:
        if "=" not in args.baseline_swap:
            die("--baseline-swap must look like 'A=B'")
        left, right = args.baseline_swap.split("=", 1)
        baseline_swap = (normalize(left), normalize(right))

    targets = parse_list(args.targets) if args.targets else DEFAULT_TARGETS

    fluxes = parse_list(args.fluxes) if args.fluxes else FLUXES_DEFAULT
    want_umf = bool(args.show_umf or args.show_groups)

    fixed_db, variable_db, _fixed_total, _var_total = split_recipe_fixed_variable(
        db=db,
        alias=alias,
        inv=inv,
        recipe_user=recipe_user,
    )

    # Full recipe for TARGET UMF (fixed + variable)
    recipe_db_full = dict(fixed_db)
    for k, v in variable_db.items():
        recipe_db_full[k] = recipe_db_full.get(k, 0.0) + v

    if want_umf:
        print_umf_block(db, recipe_db_full, fluxes, "TARGET UMF (original recipe)", show_groups=args.show_groups)

        # Baseline is variable-only with swap applied, then combined with fixed additions
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
        dev_weight=float(args.dev_weight),
    )

    print("\nSubstitution result (DB names), sum=100:")
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

    sp2 = sub2.add_parser("add", help="Add a material to inventory.")
    sp2.add_argument("material")
    sp2.add_argument("--base", action="store_true", help="Mark as base material (solver may use).")
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
    sp.add_argument("--dev-weight", default=str(DEFAULT_DEV_WEIGHT), help="Weight on recipe variation (L1)")
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
