import csv
from pathlib import Path
from typing import Dict, List, Tuple

from utils import die, normalize


def _parse_recipe_lines(lines: List[str]) -> Dict[str, float]:
    recipe: Dict[str, float] = {}
    r = csv.DictReader(lines)
    if not r.fieldnames or "material" not in r.fieldnames or "parts" not in r.fieldnames:
        die("Recipe CSV must have headers: material,parts")
    for row in r:
        if row is None:
            continue
        m_raw = row.get("material")
        p_raw = row.get("parts")
        if m_raw is None or p_raw is None:
            continue
        m = normalize(m_raw)
        if not m:
            continue
        p = float(p_raw)
        recipe[m] = recipe.get(m, 0.0) + p
    return recipe


def read_recipe_csv(path: Path) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    Reads a recipe CSV and returns (base_parts, colorant_parts).
    Convention: any rows after a blank line are treated as colorants.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines:
        die("Recipe CSV is empty.")
    header = lines[0]
    base_lines = [header]
    color_lines = [header]
    in_color = False
    for line in lines[1:]:
        if line.strip() == "":
            in_color = True
            continue
        if in_color:
            color_lines.append(line)
        else:
            base_lines.append(line)
    base_recipe = _parse_recipe_lines(base_lines)
    color_recipe = _parse_recipe_lines(color_lines) if len(color_lines) > 1 else {}
    return base_recipe, color_recipe
