from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils import die, normalize


USER_AGENT = "umf-solver/0.1 (+https://github.com/mwhooker/umf-solver)"


@dataclass
class ImportedRecipe:
    name: Optional[str]
    base: Dict[str, float]
    additions: Dict[str, float]
    source: str


def _looks_like_url(source: str) -> bool:
    parsed = urllib.parse.urlparse(source)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _download_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except urllib.error.URLError as exc:
        die(f"Failed to fetch {url}: {exc}")
    raise AssertionError("unreachable")


def _read_source_text(source: str) -> Tuple[str, str]:
    if _looks_like_url(source):
        return _download_text(source), source

    path = Path(source)
    if not path.exists():
        die(f"Import source not found: {source}")
    return path.read_text(encoding="utf-8"), str(path)


def _parse_digitalfire_xml(text: str) -> Optional[ImportedRecipe]:
    if "<recipeline " not in text:
        return None

    recipe_match = re.search(r'<recipe name="([^"]+)"', text)
    lines = re.findall(r'<recipeline material="([^"]+)" amount="([^"]+)"\s*/>', text)
    if not lines:
        return None

    base: Dict[str, float] = {}
    for material, amount in lines:
        base[normalize(unescape(material))] = float(amount)
    return ImportedRecipe(
        name=unescape(recipe_match.group(1)) if recipe_match else None,
        base=base,
        additions={},
        source="digitalfire-xml",
    )


def _strip_tags(text: str) -> str:
    text = re.sub(r"<script\b.*?</script>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "\n", text)
    return unescape(text)


def _parse_name(text: str) -> Optional[str]:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^[+-]?\d+(?:\.\d+)?\s*(?:%|g|grams?)?\s+\S", line, flags=re.IGNORECASE):
            continue
        if line.startswith("# "):
            return normalize(line[2:])
        if " - " in line and line[:1].isalnum():
            return normalize(line)
        if line.lower() not in {"added", "additions", "ingredient", "ingredients", "material amount"}:
            return normalize(line)
    return None


def _parse_recipe_lines(text: str) -> Tuple[Dict[str, float], Dict[str, float]]:
    base: Dict[str, float] = {}
    additions: Dict[str, float] = {}
    target = base

    for raw_line in text.splitlines():
        line = normalize(raw_line)
        if not line:
            continue

        lower = line.lower()
        if lower in {"material amount", "ingredient amount", "ingredients", "ingredient"}:
            continue
        if lower in {"added", "additions", "additional ingredients"}:
            target = additions
            continue
        if lower.startswith("total"):
            continue

        amount_match = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*(?:%|g|grams?)?\s+(.+)$", line, flags=re.IGNORECASE)
        if amount_match is None:
            amount_match = re.match(
                r"^(.+?)\s+([+-]?\d+(?:\.\d+)?)\s*(?:%|g|grams?)?$",
                line,
                flags=re.IGNORECASE,
            )
        if amount_match is None:
            continue

        if amount_match.re.pattern.startswith("^([+-]?"):
            amount = float(amount_match.group(1))
            material = normalize(amount_match.group(2))
        else:
            material = normalize(amount_match.group(1))
            amount = float(amount_match.group(2))

        if material.lower() in {"amount", "percent"}:
            continue
        if amount <= 0:
            continue
        target[material] = target.get(material, 0.0) + amount

    return base, additions


def import_recipe(source: str) -> ImportedRecipe:
    text, label = _read_source_text(source)

    digitalfire = _parse_digitalfire_xml(text)
    if digitalfire is not None:
        digitalfire.source = label
        return digitalfire

    if "doesn't work properly without JavaScript enabled" in text and "glazy" in label.lower():
        die(
            "Direct Glazy recipe URLs are JavaScript-driven. Export the recipe from Glazy "
            "or save/copy the ingredient text to a local file and import that file instead."
        )

    plain_text = _strip_tags(text) if "<" in text and ">" in text else text
    base, additions = _parse_recipe_lines(plain_text)
    if not base and not additions:
        die(f"Could not find recipe ingredients in {source}")

    return ImportedRecipe(
        name=_parse_name(plain_text),
        base=base,
        additions=additions,
        source=label,
    )


def write_recipe_csv(path: Path, recipe: ImportedRecipe) -> None:
    lines: List[str] = ["material,parts"]
    for material, parts in recipe.base.items():
        lines.append(f"{material},{parts:g}")
    if recipe.additions:
        lines.append("")
        for material, parts in recipe.additions.items():
            lines.append(f"{material},{parts:g}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
