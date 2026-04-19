from typing import Dict, List

from db import OxideDB


# Classic Seger groupings (you can tweak as desired)
SEGER_RO = ["MgO", "CaO", "SrO", "BaO", "ZnO"]       # RO fluxes (divalents)
SEGER_R2O = ["Li2O", "Na2O", "K2O"]                  # R2O fluxes (monovalents)
SEGER_R2O3 = ["Al2O3", "B2O3", "Fe2O3"]              # intermediates/viscosity group (B2O3 is special-case but often here)
SEGER_RO2 = ["SiO2", "TiO2"]                         # glass formers


def seger_group_sums(umf: Dict[str, float]) -> Dict[str, float]:
    ro = sum(umf.get(o, 0.0) for o in SEGER_RO)
    r2o = sum(umf.get(o, 0.0) for o in SEGER_R2O)
    r2o3 = sum(umf.get(o, 0.0) for o in SEGER_R2O3)
    ro2 = sum(umf.get(o, 0.0) for o in SEGER_RO2)
    return {"RO": ro, "R2O": r2o, "R2O3": r2o3, "RO2": ro2}


def print_umf_block(db: OxideDB, recipe_db: Dict[str, float], fluxes: List[str], label: str, show_groups: bool) -> Dict[str, float]:
    moles = db.oxide_moles_from_recipe(recipe_db)
    umf, F = db.umf_from_moles(moles, fluxes)

    print(f"\n{label}")
    print(f"  Flux moles: {F:.6f}")
    for ox in ["Na2O", "K2O", "CaO", "MgO", "B2O3", "Al2O3", "SiO2", "Fe2O3", "TiO2"]:
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
