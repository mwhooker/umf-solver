from typing import Dict, List, Optional, Set, Tuple

try:
    from ortools.linear_solver import pywraplp
except Exception:
    pywraplp = None

from constants import INTERNAL_SLACK_WEIGHTS
from db import OxideDB
from state import AliasState, InventoryState
from utils import die


def split_recipe_fixed_variable(
    db: OxideDB,
    alias: AliasState,
    base_user: Dict[str, float],
    colorant_user: Dict[str, float],
) -> Tuple[Dict[str, float], Dict[str, float], float, float]:
    """
    Returns (fixed_db, variable_db, fixed_total_parts, variable_total_parts)

    fixed_db:    DB-name -> parts (materials listed as colorants in recipe)
    variable_db: DB-name -> parts (base materials in recipe)
    """
    fixed_db: Dict[str, float] = {}
    variable_db: Dict[str, float] = {}

    for u, p in colorant_user.items():
        r = alias.resolve(u, db)
        if r is None:
            die(f"Recipe material not found: '{u}' (add alias or use exact DB name)")
        fixed_db[r] = fixed_db.get(r, 0.0) + p

    for u, p in base_user.items():
        r = alias.resolve(u, db)
        if r is None:
            die(f"Recipe material not found: '{u}' (add alias or use exact DB name)")
        variable_db[r] = variable_db.get(r, 0.0) + p

    fixed_total = sum(fixed_db.values())
    var_total = sum(variable_db.values())
    return fixed_db, variable_db, fixed_total, var_total


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
) -> Dict[str, float]:
    """
    Default behavior is lexicographic:
      (1) minimize UMF mismatch (weighted slack)
      (2) minimize # of new materials
      (3) minimize recipe deviation (L1 vs baseline)
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
    variable_mass_target = sum(variable_db.values())

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
        die("Inventory base is empty. Add materials via: inventory add 'Name'")

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

    allowed_db = {m for m in allowed_db if m not in banned_db and m not in fixed_db}
    if not allowed_db:
        die("After banning fixed colorants and unavailable materials, no allowed base materials remain in inventory.")

    mats = sorted(allowed_db)

    solver = pywraplp.Solver.CreateSolver("CBC")
    if solver is None:
        die("Failed to create CBC solver (ortools install issue).")

    # Decision vars
    x = {m: solver.NumVar(0.0, solver.infinity(), f"x[{m}]") for m in mats}
    y = {m: solver.IntVar(0, 1, f"y[{m}]") for m in mats}

    # Ingredient cap and on/off coupling
    M = variable_mass_target
    for m in mats:
        solver.Add(x[m] <= M * y[m])
    solver.Add(sum(y[m] for m in mats) <= int(max_materials))

    # Keep the original base recipe total unchanged; colorants are additions on top.
    if variable_mass_target <= 0.0:
        die("Recipe has no base-material mass left to substitute.")
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
    for m in mats:
        obj.SetCoefficient(dplus[m], 1.0)
        obj.SetCoefficient(dminus[m], 1.0)
    obj.SetMinimization()

    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        die("Solver error in stage-3 (min deviation).")

    sol_var = {m: x[m].solution_value() for m in mats if x[m].solution_value() > 1e-6}
    sol_full = dict(fixed_db)
    for k, v in sol_var.items():
        sol_full[k] = sol_full.get(k, 0.0) + v
    return sol_full
