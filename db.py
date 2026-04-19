from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from utils import die


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
