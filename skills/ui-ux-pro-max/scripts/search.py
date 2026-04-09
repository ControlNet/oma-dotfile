#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI/UX Pro Max Search - BM25 search engine for UI/UX style guides
Usage: python /absolute/path/to/search.py "<query>" [--domain <domain>] [--stack <stack>] [--max-results 3]
       python /absolute/path/to/search.py "<query>" --design-system [-p "Project Name"]
       python /absolute/path/to/search.py "<query>" --design-system --persist [-p "Project Name"] [--page "dashboard"] [--output-dir "<dir>"]

Domains: style, prompt, color, chart, landing, product, ux, typography, icons, react, web
Stacks: html-tailwind, react, nextjs, astro, vue, nuxtjs, nuxt-ui, svelte, swiftui, react-native, flutter, shadcn, jetpack-compose

Persistence (project-scoped Master + Overrides pattern):
  --persist    Save design system to <output-dir>/design-system/<project-slug>/MASTER.md
  --page       Also create a page-specific override file in <output-dir>/design-system/<project-slug>/pages/
"""

import argparse
import importlib.util
import sys
import io
from pathlib import Path
from types import ModuleType


def _load_local_module(module_name: str) -> ModuleType:
    """Load a sibling module by file path so the script works from any cwd."""
    module_path = Path(__file__).resolve().with_name(f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(
        f"ui_ux_pro_max_{module_name}", module_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module '{module_name}' from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_core_module = _load_local_module("core")
_design_system_module = _load_local_module("design_system")

CSV_CONFIG = _core_module.CSV_CONFIG
AVAILABLE_STACKS = _core_module.AVAILABLE_STACKS
MAX_RESULTS = _core_module.MAX_RESULTS
search = _core_module.search
search_stack = _core_module.search_stack
generate_design_system = _design_system_module.generate_design_system

# Force UTF-8 for stdout/stderr to handle emojis on Windows (cp1252 default)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


def format_output(result):
    """Format results for Claude consumption (token-optimized)"""
    if "error" in result:
        return f"Error: {result['error']}"

    output = []
    if result.get("stack"):
        output.append(f"## UI Pro Max Stack Guidelines")
        output.append(f"**Stack:** {result['stack']} | **Query:** {result['query']}")
    else:
        output.append(f"## UI Pro Max Search Results")
        output.append(f"**Domain:** {result['domain']} | **Query:** {result['query']}")
    output.append(
        f"**Source:** {result['file']} | **Found:** {result['count']} results\n"
    )

    for i, row in enumerate(result["results"], 1):
        output.append(f"### Result {i}")
        for key, value in row.items():
            value_str = str(value)
            if len(value_str) > 300:
                value_str = value_str[:300] + "..."
            output.append(f"- **{key}:** {value_str}")
        output.append("")

    return "\n".join(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UI Pro Max Search")
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "--domain", "-d", choices=list(CSV_CONFIG.keys()), help="Search domain"
    )
    parser.add_argument(
        "--stack",
        "-s",
        choices=AVAILABLE_STACKS,
        help="Stack-specific search (html-tailwind, react, nextjs)",
    )
    parser.add_argument(
        "--max-results",
        "-n",
        type=int,
        default=MAX_RESULTS,
        help="Max results (default: 3)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    # Design system generation
    parser.add_argument(
        "--design-system",
        "-ds",
        action="store_true",
        help="Generate complete design system recommendation",
    )
    parser.add_argument(
        "--project-name",
        "-p",
        type=str,
        default=None,
        help="Project name for design system output",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["ascii", "markdown"],
        default="ascii",
        help="Output format for design system",
    )
    # Persistence (Master + Overrides pattern)
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Save design system to <output-dir>/design-system/<project-slug>/MASTER.md",
    )
    parser.add_argument(
        "--page",
        type=str,
        default=None,
        help="Create page-specific override file in <output-dir>/design-system/<project-slug>/pages/",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Output directory for persisted files (default: current directory)",
    )

    args = parser.parse_args()

    # Design system takes priority
    if args.design_system:
        result = generate_design_system(
            args.query,
            args.project_name,
            args.format,
            persist=args.persist,
            page=args.page,
            output_dir=args.output_dir,
        )
        print(result)

        # Print persistence confirmation
        if args.persist:
            project_name = args.project_name or args.query.upper()
            project_slug = project_name.lower().replace(" ", "-")
            base_dir = (
                Path(args.output_dir).resolve() if args.output_dir else Path.cwd()
            )
            design_system_dir = base_dir / "design-system" / project_slug
            print("\n" + "=" * 60)
            print(f"✅ Design system persisted to {design_system_dir}/")
            print(f"   📄 {design_system_dir / 'MASTER.md'} (Global Source of Truth)")
            if args.page:
                page_filename = args.page.lower().replace(" ", "-")
                print(
                    f"   📄 {design_system_dir / 'pages' / f'{page_filename}.md'} (Page Overrides)"
                )
            print("")
            print(
                f"📖 Usage: When building a page, check {(design_system_dir / 'pages').as_posix()}/[page].md first."
            )
            print(
                f"   If it exists, its rules override {(design_system_dir / 'MASTER.md').as_posix()}. Otherwise, use {(design_system_dir / 'MASTER.md').as_posix()}."
            )
            print("=" * 60)
    # Stack search
    elif args.stack:
        result = search_stack(args.query, args.stack, args.max_results)
        if args.json:
            import json

            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(format_output(result))
    # Domain search
    else:
        result = search(args.query, args.domain, args.max_results)
        if args.json:
            import json

            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(format_output(result))
