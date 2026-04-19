#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Tuple

from constants import DEFAULT_TARGETS, FLUXES_DEFAULT
from db import OxideDB
from ingredient_api import IngredientResolver, ResolutionResult
from importer import import_recipe
from ontology import OntologyCatalog, SourceRecipe, StudioRecipe, StudioRecipeLine
from solver import solve_base_reformulation
from state import MaterialMappings, StudioInventory
from utils import die, normalize


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = SCRIPT_DIR / "data.csv"
DEFAULT_STATE_DIR = SCRIPT_DIR / ".umf_state"
DEFAULT_STUDIO_INVENTORY_PATH = DEFAULT_STATE_DIR / "studio_inventory.json"
DEFAULT_MAPPINGS_PATH = DEFAULT_STATE_DIR / "material_mappings.json"
DEFAULT_CATALOG_PATH = SCRIPT_DIR / "ontology_catalog.json"


def load_context(args) -> Tuple[OxideDB, OntologyCatalog, StudioInventory, MaterialMappings]:
    db = OxideDB.load(args.db)
    catalog = OntologyCatalog.load(args.catalog)
    inventory = StudioInventory.load(args.studio_inventory)
    mappings = MaterialMappings.load(args.material_mappings)
    return db, catalog, inventory, mappings


def choose_unique_studio_material(inventory: StudioInventory, material: str):
    matches = inventory.find_by_material(material)
    if len(matches) == 1:
        return matches[0]
    return None


def describe_resolution(match: ResolutionResult) -> str:
    parts = [f"status={match.status}"]
    if match.matched_concept:
        parts.append(f"concept={match.matched_concept}")
    if match.matched_material:
        parts.append(f"material={match.matched_material}")
    if match.matched_studio_material:
        parts.append(f"studio={match.matched_studio_material}")
    if match.candidate_materials:
        parts.append("candidates=" + ", ".join(match.candidate_materials))
    parts.append(f"reason={match.reason}")
    return "; ".join(parts)


def cmd_db_check(args):
    db = OxideDB.load(args.db)
    print(f"DB: {args.db}")
    print(f"  materials: {len(db.all_materials())}")
    print(f"  oxides:    {len(db.oxides)}")
    return 0


def cmd_inventory_add(args):
    db, _catalog, inventory, _mappings = load_context(args)
    material = normalize(args.material)
    if not db.has_material(material):
        die(f"Canonical material not found in DB: {material}")
    inventory.add(args.studio_name, material, notes=args.notes or "")
    inventory.save(args.studio_inventory)
    print(f"Added studio material: {args.studio_name} -> {material}")
    print(f"Saved: {args.studio_inventory}")
    return 0


def cmd_inventory_remove(args):
    _db, _catalog, inventory, _mappings = load_context(args)
    if not inventory.remove(args.studio_name):
        print(f"(not in studio inventory) {args.studio_name}")
        return 0
    inventory.save(args.studio_inventory)
    print(f"Removed studio material: {args.studio_name}")
    return 0


def cmd_inventory_list(args):
    _db, _catalog, inventory, _mappings = load_context(args)
    for item in sorted(inventory.items, key=lambda item: item.name.lower()):
        print(item.name)
    return 0


def cmd_inventory_inspect(args):
    _db, _catalog, inventory, _mappings = load_context(args)
    for item in sorted(inventory.items, key=lambda item: item.name.lower()):
        print(item.name)
        print(f"  material: {item.material}")
        if item.notes:
            print(f"  notes: {item.notes}")
    return 0


def cmd_mapping_set(args):
    db, _catalog, _inventory, mappings = load_context(args)
    material = normalize(args.material)
    if not db.has_material(material):
        die(f"Canonical material not found in DB: {material}")
    mappings.set(args.provider, args.source_term, material)
    mappings.save(args.material_mappings)
    print(f"Mapping set: ({args.provider}) {args.source_term} -> {material}")
    print(f"Saved: {args.material_mappings}")
    return 0


def cmd_mapping_list(args):
    _db, _catalog, _inventory, mappings = load_context(args)
    for item in sorted(mappings.items, key=lambda item: (item.provider, item.source_term.lower())):
        print(f"{item.provider}: {item.source_term} -> {item.material}")
    return 0


def cmd_mapping_remove(args):
    _db, _catalog, _inventory, mappings = load_context(args)
    if not mappings.remove(args.provider, args.source_term):
        print(f"(not mapped) ({args.provider}) {args.source_term}")
        return 0
    mappings.save(args.material_mappings)
    print(f"Removed mapping: ({args.provider}) {args.source_term}")
    return 0


def cmd_ingredient_resolve(args):
    db, catalog, inventory, mappings = load_context(args)
    resolver = IngredientResolver(db=db, catalog=catalog, inventory=inventory, mappings=mappings)
    for raw_name in args.ingredients:
        match = resolver.resolve(raw_name, provider=args.provider)
        print(f"{match.query}:")
        print(f"  status: {match.status}")
        if match.matched_concept:
            print(f"  concept: {match.matched_concept}")
        if match.matched_material:
            print(f"  material: {match.matched_material}")
        if match.matched_studio_material:
            print(f"  studio material: {match.matched_studio_material}")
        if match.candidate_materials:
            print(f"  candidates: {', '.join(match.candidate_materials)}")
        print(f"  reason: {match.reason}")
    return 0


def print_source_recipe(recipe: SourceRecipe) -> None:
    print(f"Imported recipe from: {recipe.source}")
    if recipe.name:
        print(f"Name: {recipe.name}")
    print(f"Provider: {recipe.provider}")
    print("\nSource recipe lines:")
    for line in recipe.lines:
        print(f"  [{line.role}] {line.original_name}: {line.amount:.6g}")


def cmd_import_recipe(args):
    db, catalog, inventory, mappings = load_context(args)
    resolver = IngredientResolver(db=db, catalog=catalog, inventory=inventory, mappings=mappings)
    recipe = import_recipe(args.source)
    print_source_recipe(recipe)
    print("\nResolution analysis:")
    for line in recipe.lines:
        match = resolver.resolve(line.original_name, provider=recipe.provider)
        print(f"  [{line.role}] {line.original_name}: {line.amount:.6g}")
        print(f"    {describe_resolution(match)}")
    if args.save_recipe is not None:
        recipe.save(args.save_recipe)
        print(f"\nSaved source recipe: {args.save_recipe}")
    return 0


def render_source_recipe_to_studio(
    db: OxideDB,
    catalog: OntologyCatalog,
    inventory: StudioInventory,
    mappings: MaterialMappings,
    recipe: SourceRecipe,
) -> StudioRecipe:
    resolver = IngredientResolver(db=db, catalog=catalog, inventory=inventory, mappings=mappings)

    rendered_lines: List[StudioRecipeLine] = []
    unresolved: List[str] = []

    for line in recipe.lines:
        match = resolver.resolve(line.original_name, provider=recipe.provider)

        if line.role == "addition":
            if match.status == "exact_studio_material":
                rendered_lines.append(
                    StudioRecipeLine(
                        name=match.matched_studio_material or line.original_name,
                        material=match.matched_material or "",
                        amount=line.amount,
                        role="addition",
                        derivation_reason=match.status,
                    )
                )
                continue
            if match.status in {"exact_material", "material_synonym", "mapped_material", "concept_material"} and match.matched_material is not None:
                studio_item = choose_unique_studio_material(inventory, match.matched_material)
                if studio_item is None:
                    unresolved.append(
                        f"addition '{line.original_name}' resolves to {match.matched_material} but has no unique studio material"
                    )
                    continue
                rendered_lines.append(
                    StudioRecipeLine(
                        name=studio_item.name,
                        material=studio_item.material,
                        amount=line.amount,
                        role="addition",
                        derivation_reason=match.status,
                    )
                )
                continue
            unresolved.append(f"addition '{line.original_name}' is not directly resolvable: {match.status}")
            continue

        if match.status == "exact_studio_material":
            rendered_lines.append(
                StudioRecipeLine(
                    name=match.matched_studio_material or line.original_name,
                    material=match.matched_material or "",
                    amount=line.amount,
                    role="base",
                    derivation_reason=match.status,
                )
            )
            continue

        if match.status in {"exact_material", "material_synonym", "mapped_material", "concept_material"} and match.matched_material is not None:
            material = match.matched_material
            studio_item = choose_unique_studio_material(inventory, material)
            if studio_item is not None:
                rendered_lines.append(
                    StudioRecipeLine(
                        name=studio_item.name,
                        material=material,
                        amount=line.amount,
                        role="base",
                        derivation_reason=match.status,
                    )
                )
                continue

            for substitute_material in catalog.direct_substitutes_for(material):
                studio_substitute = choose_unique_studio_material(inventory, substitute_material)
                if studio_substitute is not None:
                    rendered_lines.append(
                        StudioRecipeLine(
                            name=studio_substitute.name,
                            material=substitute_material,
                            amount=line.amount,
                            role="base",
                            derivation_reason=f"direct_substitution:{material}",
                        )
                    )
                    break
            else:
                unresolved.append(
                    f"base '{line.original_name}' resolves to {material} but has no direct studio material or substitution"
                )
            continue

        unresolved.append(f"base '{line.original_name}' requires confirmation before resolution: {match.status}")

    if unresolved:
        die("Cannot resolve source recipe:\n  - " + "\n  - ".join(unresolved))

    return StudioRecipe(
        name=recipe.name,
        source=recipe.source,
        provider=recipe.provider,
        lines=rendered_lines,
    )


def solve_source_recipe_to_studio(
    db: OxideDB,
    catalog: OntologyCatalog,
    inventory: StudioInventory,
    mappings: MaterialMappings,
    recipe: SourceRecipe,
    max_materials: int,
) -> StudioRecipe:
    resolver = IngredientResolver(db=db, catalog=catalog, inventory=inventory, mappings=mappings)

    target_base_materials: Dict[str, float] = {}
    fixed_base_materials: Dict[str, float] = {}
    fixed_base_reasons: Dict[str, str] = {}
    addition_lines: List[StudioRecipeLine] = []
    unresolved: List[str] = []

    for line in recipe.lines:
        match = resolver.resolve(line.original_name, provider=recipe.provider)

        if line.role == "addition":
            if match.status == "exact_studio_material":
                addition_lines.append(
                    StudioRecipeLine(
                        name=match.matched_studio_material or line.original_name,
                        material=match.matched_material or "",
                        amount=line.amount,
                        role="addition",
                        derivation_reason=match.status,
                    )
                )
                continue
            if match.status in {"exact_material", "material_synonym", "mapped_material", "concept_material"} and match.matched_material is not None:
                studio_item = choose_unique_studio_material(inventory, match.matched_material)
                if studio_item is None:
                    unresolved.append(
                        f"addition '{line.original_name}' resolves to {match.matched_material} but has no unique studio material"
                    )
                    continue
                addition_lines.append(
                    StudioRecipeLine(
                        name=studio_item.name,
                        material=studio_item.material,
                        amount=line.amount,
                        role="addition",
                        derivation_reason=match.status,
                    )
                )
                continue
            unresolved.append(f"addition '{line.original_name}' is not directly resolvable: {match.status}")
            continue

        if match.status == "exact_studio_material":
            material = match.matched_material or ""
            target_base_materials[material] = target_base_materials.get(material, 0.0) + line.amount
            fixed_base_materials[material] = fixed_base_materials.get(material, 0.0) + line.amount
            fixed_base_reasons[material] = match.status
            continue

        if match.status in {"exact_material", "material_synonym", "mapped_material", "concept_material"} and match.matched_material is not None:
            material = match.matched_material
            target_base_materials[material] = target_base_materials.get(material, 0.0) + line.amount
            studio_item = choose_unique_studio_material(inventory, material)
            if studio_item is not None:
                fixed_base_materials[material] = fixed_base_materials.get(material, 0.0) + line.amount
                fixed_base_reasons[material] = match.status
            continue

        unresolved.append(f"base '{line.original_name}' requires confirmation before resolution: {match.status}")

    if unresolved:
        die("Cannot resolve source recipe:\n  - " + "\n  - ".join(unresolved))

    addition_materials = {line.material for line in addition_lines}
    available_materials = sorted(
        {
            item.material
            for item in inventory.items
            if item.material not in addition_materials or item.material in fixed_base_materials
        }
    )

    solved_base = solve_base_reformulation(
        db=db,
        target_base_materials=target_base_materials,
        fixed_base_materials=fixed_base_materials,
        available_materials=available_materials,
        max_materials=max_materials,
        targets=DEFAULT_TARGETS,
        fluxes=FLUXES_DEFAULT,
    )

    base_lines: List[StudioRecipeLine] = []
    for material, amount in sorted(solved_base.items()):
        studio_item = choose_unique_studio_material(inventory, material)
        if studio_item is None:
            die(f"Resolved material {material} does not have a unique studio material entry.")
        base_lines.append(
            StudioRecipeLine(
                name=studio_item.name,
                material=material,
                amount=amount,
                role="base",
                derivation_reason=fixed_base_reasons.get(material, "umf_reformulation"),
            )
        )

    return StudioRecipe(
        name=recipe.name,
        source=recipe.source,
        provider=recipe.provider,
        lines=base_lines + addition_lines,
    )


def print_studio_recipe(studio_recipe: StudioRecipe, heading: str) -> None:
    print(f"{heading}: {studio_recipe.source}")
    if studio_recipe.name:
        print(f"Name: {studio_recipe.name}")
    print("\nStudio recipe:")
    for line in studio_recipe.lines:
        print(f"  [{line.role}] {line.name}: {line.amount:.6g} ({line.material}; {line.derivation_reason})")


def cmd_recipe_render(args):
    db, catalog, inventory, mappings = load_context(args)
    recipe = SourceRecipe.load(args.source_recipe)
    studio_recipe = render_source_recipe_to_studio(
        db=db,
        catalog=catalog,
        inventory=inventory,
        mappings=mappings,
        recipe=recipe,
    )
    print_studio_recipe(studio_recipe, "Rendered studio recipe from")
    return 0


def cmd_recipe_solve(args):
    db, catalog, inventory, mappings = load_context(args)
    recipe = SourceRecipe.load(args.source_recipe)
    studio_recipe = solve_source_recipe_to_studio(
        db=db,
        catalog=catalog,
        inventory=inventory,
        mappings=mappings,
        recipe=recipe,
        max_materials=args.max_materials,
    )
    print_studio_recipe(studio_recipe, "Solved studio recipe from")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="umf", add_help=True)
    p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    p.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    p.add_argument("--studio-inventory", type=Path, default=None)
    p.add_argument("--material-mappings", type=Path, default=None)

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("db-check")
    sp.set_defaults(func=cmd_db_check)

    sp = sub.add_parser("inventory", help="Manage studio inventory.")
    sub2 = sp.add_subparsers(dest="inventory_cmd", required=True)
    sp2 = sub2.add_parser("add")
    sp2.add_argument("studio_name")
    sp2.add_argument("--material", required=True)
    sp2.add_argument("--notes", default="")
    sp2.set_defaults(func=cmd_inventory_add)
    sp2 = sub2.add_parser("remove")
    sp2.add_argument("studio_name")
    sp2.set_defaults(func=cmd_inventory_remove)
    sp2 = sub2.add_parser("list")
    sp2.set_defaults(func=cmd_inventory_list)
    sp2 = sub2.add_parser("inspect")
    sp2.set_defaults(func=cmd_inventory_inspect)

    sp = sub.add_parser("mapping", help="Manage confirmed source-term material mappings.")
    sub2 = sp.add_subparsers(dest="mapping_cmd", required=True)
    sp2 = sub2.add_parser("set")
    sp2.add_argument("--provider", choices=["generic", "digitalfire", "glazy"], required=True)
    sp2.add_argument("source_term")
    sp2.add_argument("material")
    sp2.set_defaults(func=cmd_mapping_set)
    sp2 = sub2.add_parser("list")
    sp2.set_defaults(func=cmd_mapping_list)
    sp2 = sub2.add_parser("remove")
    sp2.add_argument("--provider", choices=["generic", "digitalfire", "glazy"], required=True)
    sp2.add_argument("source_term")
    sp2.set_defaults(func=cmd_mapping_remove)

    sp = sub.add_parser("ingredient", help="Ingredient lookup and resolution helpers.")
    sub2 = sp.add_subparsers(dest="ingredient_cmd", required=True)
    sp2 = sub2.add_parser("resolve")
    sp2.add_argument("ingredients", nargs="+")
    sp2.add_argument("--provider", choices=["generic", "digitalfire", "glazy"], default="generic")
    sp2.set_defaults(func=cmd_ingredient_resolve)

    sp = sub.add_parser("import-recipe", help="Import a source recipe from a URL or file.")
    sp.add_argument("source")
    sp.add_argument("--save-recipe", type=Path, default=None)
    sp.set_defaults(func=cmd_import_recipe)

    sp = sub.add_parser("recipe", help="Source/studio recipe operations.")
    sub2 = sp.add_subparsers(dest="recipe_cmd", required=True)
    sp2 = sub2.add_parser("render")
    sp2.add_argument("source_recipe", type=Path)
    sp2.set_defaults(func=cmd_recipe_render)
    sp2 = sub2.add_parser("solve")
    sp2.add_argument("source_recipe", type=Path)
    sp2.add_argument("--max-materials", type=int, default=6)
    sp2.set_defaults(func=cmd_recipe_solve)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    state_dir: Path = args.state_dir
    args.studio_inventory = args.studio_inventory or (state_dir / "studio_inventory.json")
    args.material_mappings = args.material_mappings or (state_dir / "material_mappings.json")
    state_dir.mkdir(parents=True, exist_ok=True)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
