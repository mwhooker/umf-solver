from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
import csv
from html import unescape
from pathlib import Path
from typing import List, Optional, Tuple

from ontology import SourceRecipe, SourceRecipeLine
from utils import die, normalize


USER_AGENT = "umf-solver/0.1 (+https://github.com/mwhooker/umf-solver)"


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


def _provider_for_source(label: str) -> str:
    lowered = label.lower()
    if "digitalfire" in lowered:
        return "digitalfire"
    if "glazy" in lowered:
        return "glazy"
    return "generic"


def _parse_legacy_recipe_csv(text: str, source: str) -> Optional[SourceRecipe]:
    lines = text.splitlines()
    if not lines:
        return None

    reader = csv.DictReader(lines)
    if not reader.fieldnames:
        return None
    fieldnames = {normalize(name).lower() for name in reader.fieldnames if name is not None}
    if "material" not in fieldnames or "parts" not in fieldnames:
        return None

    header = lines[0]
    base_lines = [header]
    addition_lines = [header]
    in_additions = False
    for line in lines[1:]:
        if not line.strip():
            in_additions = True
            continue
        if in_additions:
            addition_lines.append(line)
        else:
            base_lines.append(line)

    source_lines: List[SourceRecipeLine] = []
    for role, role_lines in (("base", base_lines), ("addition", addition_lines)):
        role_reader = csv.DictReader(role_lines)
        for row in role_reader:
            if row is None:
                continue
            material = normalize(row.get("material"))
            parts = normalize(row.get("parts"))
            if not material or not parts:
                continue
            if material.lower() == "material" or parts.lower() == "parts":
                continue
            source_lines.append(
                SourceRecipeLine(
                    original_name=material,
                    amount=float(parts),
                    role=role,
                    provider="generic",
                    order=len(source_lines),
                )
            )

    if not source_lines:
        return None

    return SourceRecipe(
        name=Path(source).stem,
        provider="generic",
        source=source,
        lines=source_lines,
    )


def _parse_name(text: str) -> Optional[str]:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^[+-]?\d+(?:\.\d+)?\s*(?:%|g|grams?)?\s+\S", line, flags=re.IGNORECASE):
            continue
        if re.match(r"^.+?\s+[+-]?\d+(?:\.\d+)?\s*(?:%|g|grams?)?$", line, flags=re.IGNORECASE):
            continue
        if line.startswith("# "):
            return normalize(line[2:])
        if " - " in line and line[:1].isalnum():
            return normalize(line)
        if line.lower() not in {"added", "additions", "ingredient", "ingredients", "material amount"}:
            return normalize(line)
    return None


def _strip_tags(text: str) -> str:
    text = re.sub(r"<script\b.*?</script>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "\n", text)
    return unescape(text)


def _parse_digitalfire_xml(text: str, source: str) -> Optional[SourceRecipe]:
    if "<recipeline " not in text:
        return None

    recipe_match = re.search(r'<recipe name="([^"]+)"', text)
    lines = re.findall(r'<recipeline material="([^"]+)" amount="([^"]+)"\s*/>', text)
    if not lines:
        return None

    source_lines = [
        SourceRecipeLine(
            original_name=normalize(unescape(material)),
            amount=float(amount),
            role="base",
            provider="digitalfire",
            order=index,
        )
        for index, (material, amount) in enumerate(lines)
    ]
    return SourceRecipe(
        name=unescape(recipe_match.group(1)) if recipe_match else None,
        provider="digitalfire",
        source=source,
        lines=source_lines,
    )


def _parse_plain_text_lines(text: str, provider: str) -> List[SourceRecipeLine]:
    lines: List[SourceRecipeLine] = []
    role = "base"

    for raw_line in text.splitlines():
        line = normalize(raw_line)
        if not line:
            continue
        lower = line.lower()
        if lower in {"material amount", "ingredient amount", "ingredients", "ingredient"}:
            continue
        if lower in {"added", "additions", "additional ingredients"}:
            role = "addition"
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

        if material.lower() in {"amount", "percent"} or amount <= 0:
            continue

        lines.append(
            SourceRecipeLine(
                original_name=material,
                amount=amount,
                role=role,
                provider=provider,
                order=len(lines),
            )
        )

    return lines


def import_recipe(source: str) -> SourceRecipe:
    text, label = _read_source_text(source)

    digitalfire = _parse_digitalfire_xml(text, label)
    if digitalfire is not None:
        return digitalfire

    legacy_csv = _parse_legacy_recipe_csv(text, label)
    if legacy_csv is not None:
        return legacy_csv

    if "doesn't work properly without JavaScript enabled" in text and "glazy" in label.lower():
        die(
            "Direct Glazy recipe URLs are JavaScript-driven. Export the recipe from Glazy "
            "or save/copy the ingredient text to a local file and import that file instead."
        )

    provider = _provider_for_source(label)
    plain_text = _strip_tags(text) if "<" in text and ">" in text else text
    lines = _parse_plain_text_lines(plain_text, provider)
    if not lines:
        die(f"Could not find recipe ingredients in {source}")

    return SourceRecipe(
        name=_parse_name(plain_text) or Path(label).stem,
        provider=provider,
        source=label,
        lines=lines,
    )
