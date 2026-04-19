from __future__ import annotations

from typing import Dict, List, Sequence, Set

try:
    from ortools.linear_solver import pywraplp
except Exception:
    pywraplp = None

from constants import INTERNAL_SLACK_WEIGHTS
from db import OxideDB
from utils import die


def solve_base_reformulation(
    db: OxideDB,
    target_base_materials: Dict[str, float],
    fixed_base_materials: Dict[str, float],
    available_materials: Sequence[str],
    max_materials: int,
    targets: List[str],
    fluxes: List[str],
) -> Dict[str, float]:
    if pywraplp is None:
        die("ortools is required. Install with: python3 -m pip install ortools")

    if not target_base_materials:
        return dict(fixed_base_materials)

    recipe_full = dict(target_base_materials)
    orig_moles = db.oxide_moles_from_recipe(recipe_full)
    orig_umf, _ = db.umf_from_moles(orig_moles, fluxes)

    fixed_moles = db.oxide_moles_from_recipe(fixed_base_materials)
    variable_mass_target = sum(target_base_materials.values()) - sum(fixed_base_materials.values())
    if variable_mass_target < -1e-9:
        die("Fixed base materials exceed target base recipe mass.")
    if variable_mass_target <= 1e-9:
        return dict(fixed_base_materials)

    allowed_db: Set[str] = {material for material in available_materials if db.has_material(material)}
    allowed_db = {material for material in allowed_db if material not in fixed_base_materials}
    if not allowed_db:
        die("No available studio materials remain for reformulation.")

    mats = sorted(allowed_db)

    solver = pywraplp.Solver.CreateSolver("CBC")
    if solver is None:
        die("Failed to create CBC solver (ortools install issue).")

    x = {m: solver.NumVar(0.0, solver.infinity(), f"x[{m}]") for m in mats}
    y = {m: solver.IntVar(0, 1, f"y[{m}]") for m in mats}

    for m in mats:
        solver.Add(x[m] <= variable_mass_target * y[m])
    solver.Add(sum(y[m] for m in mats) <= int(max_materials))
    solver.Add(sum(x[m] for m in mats) == variable_mass_target)

    baseline_db = {m: target_base_materials.get(m, 0.0) for m in mats}
    core_set = {m for m, v in baseline_db.items() if abs(v) > 1e-9}

    coeffs = {m: db.coeffs_moles_per_gram(m) for m in mats}

    def n_ox(oxide: str):
        return float(fixed_moles.get(oxide, 0.0)) + sum(coeffs[m].get(oxide, 0.0) * x[m] for m in mats)

    F = sum(n_ox(flux) for flux in fluxes)
    solver.Add(F >= 1e-9)

    splus, sminus = {}, {}
    for target in targets:
        splus[target] = solver.NumVar(0.0, solver.infinity(), f"splus[{target}]")
        sminus[target] = solver.NumVar(0.0, solver.infinity(), f"sminus[{target}]")
        if target == "R2O":
            target_value = float(orig_umf.get("Na2O", 0.0) + orig_umf.get("K2O", 0.0))
            solver.Add((n_ox("Na2O") + n_ox("K2O")) - target_value * F == splus[target] - sminus[target])
        else:
            target_value = float(orig_umf.get(target, 0.0))
            solver.Add(n_ox(target) - target_value * F == splus[target] - sminus[target])

    dplus, dminus = {}, {}
    for m in mats:
        dplus[m] = solver.NumVar(0.0, solver.infinity(), f"dplus[{m}]")
        dminus[m] = solver.NumVar(0.0, solver.infinity(), f"dminus[{m}]")
        baseline = float(baseline_db.get(m, 0.0))
        solver.Add(x[m] - baseline == dplus[m] - dminus[m])

    new_mats = solver.NumVar(0.0, solver.infinity(), "new_mats")
    solver.Add(new_mats == sum(y[m] for m in mats if m not in core_set))

    S = solver.NumVar(0.0, solver.infinity(), "S")
    solver.Add(
        S == sum(float(INTERNAL_SLACK_WEIGHTS.get(target, 1.0)) * (splus[target] + sminus[target]) for target in targets)
    )

    obj = solver.Objective()
    obj.SetCoefficient(S, 1.0)
    obj.SetMinimization()
    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        die("MILP infeasible or solver error in stage-1 (slack minimization).")

    S_star = S.solution_value()
    solver.Add(S <= S_star + 1e-7)

    obj = solver.Objective()
    obj.SetCoefficient(new_mats, 1.0)
    obj.SetMinimization()
    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        die("Solver error in stage-2 (min new materials).")

    new_star = new_mats.solution_value()
    solver.Add(new_mats <= new_star + 1e-9)

    obj = solver.Objective()
    for m in mats:
        obj.SetCoefficient(dplus[m], 1.0)
        obj.SetCoefficient(dminus[m], 1.0)
    obj.SetMinimization()
    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        die("Solver error in stage-3 (min deviation).")

    solved = dict(fixed_base_materials)
    for material in mats:
        value = x[material].solution_value()
        if value > 1e-6:
            solved[material] = solved.get(material, 0.0) + value
    return solved
