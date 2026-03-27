#!/usr/bin/env python3
"""Extract Mermaid/PlantUML diagrams from SWDD markdown and render image assets.

Usage:
  python extract_diagrams.py --swdd-root ./swdd --module ABBSM
  python extract_diagrams.py --swdd-root ./swdd              # all modules
  python extract_diagrams.py --swdd-root ./swdd --extract-only  # no rendering
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path


def find_chrome() -> str | None:
    """Find Chrome/Chromium for Puppeteer (used by mermaid-cli)."""
    env = os.environ.get("PUPPETEER_EXECUTABLE_PATH")
    if env and Path(env).exists():
        return env
    candidates = [
        Path.home() / ".cache" / "puppeteer" / "chrome-headless-shell",
        Path.home() / ".cache" / "puppeteer",
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
        if candidate.is_dir():
            found = next((p for p in candidate.rglob("chrome-headless-shell") if p.is_file()), None)
            if found:
                return str(found)
    return None


def find_plantuml_cmd() -> list[str]:
    """Build the PlantUML command.

    Priority:
      1. PLANTUML_JAR env var -> java -jar $PLANTUML_JAR
      2. 'plantuml' on PATH
    """
    jar = os.environ.get("PLANTUML_JAR")
    if jar and Path(jar).exists():
        return ["java", "-jar", jar]
    # Check if plantuml command exists
    if shutil.which("plantuml"):
        return ["plantuml"]
    # Fallback: try java -jar with common locations
    return ["plantuml"]


def module_name_from_md(md_path: Path) -> str:
    """Extract module name from SWDD markdown filename.

    Works with any project prefix:
      BBS_K311_APP_ABBSM_Software_... -> ABBSM
      XXX_YYY_DMCU_Software_...       -> DMCU
    """
    name = md_path.stem
    # Remove _Software_Detailed_Design_Document_EN suffix
    name = re.sub(r"_Software_Detailed_Design_Document_EN$", "", name)
    # Take the last segment before _Software (which is the module name)
    # Module names are typically all-uppercase: ABBSM, DMCU, HADC, MC363X
    parts = name.split("_")
    # Walk backwards to find the module name (uppercase segment)
    for i in range(len(parts) - 1, -1, -1):
        if re.match(r'^[A-Z][A-Z0-9]+$', parts[i]):
            # Check if next part (if exists) is also uppercase - could be multi-part like MC363X
            return parts[i]
    # Fallback: use parent directory name
    return md_path.parent.name


def extract_blocks(md_path: Path) -> list[tuple[str, str, str]]:
    """Extract mermaid/plantuml code blocks from markdown.

    Returns list of (lang, diagram_name, code) tuples.
    """
    lines = md_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    blocks: list[tuple[str, str, str]] = []
    module = module_name_from_md(md_path)
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line not in {"```mermaid", "```plantuml"}:
            i += 1
            continue
        lang = "mermaid" if line == "```mermaid" else "plantuml"
        i += 1
        buf: list[str] = []
        while i < len(lines) and lines[i].strip() != "```":
            buf.append(lines[i])
            i += 1
        code = "\n".join(buf).rstrip() + "\n"
        diagram_name = None
        search_end = min(len(lines), i + 60)
        for j in range(i + 1, search_end):
            fig = re.search(r"\*\*Figure\s+[\d.-]+:\s*([A-Za-z_]\w*)\s+Flowchart\*\*", lines[j])
            if fig and lang == "mermaid":
                diagram_name = f"{fig.group(1)}_Flowchart"
                break
            if "Static Diagram" in lines[j] and lang == "mermaid":
                diagram_name = f"{module}_Static_Diagram"
                break
            if "Dynamic Behavior" in lines[j] and lang == "plantuml":
                diagram_name = f"{module}_Dynamic_Behavior"
                break
        if not diagram_name and lang == "mermaid":
            for j in range(max(0, i - 30), i):
                if "2.4.1" in lines[j]:
                    diagram_name = f"{module}_Static_Diagram"
                    break
        if not diagram_name and lang == "plantuml":
            diagram_name = f"{module}_Dynamic_Behavior"
        if diagram_name:
            blocks.append((lang, diagram_name, code))
        i += 1
    return blocks


def render_mermaid(mmd_file: Path, png_file: Path) -> None:
    """Render a Mermaid diagram to PNG using mermaid-cli."""
    env = os.environ.copy()
    chrome = find_chrome()
    if chrome:
        env["PUPPETEER_EXECUTABLE_PATH"] = chrome
    subprocess.run(
        ["npx", "-y", "@mermaid-js/mermaid-cli", "-i", str(mmd_file), "-o", str(png_file)],
        check=True,
        text=True,
        capture_output=True,
        timeout=180,
        env=env,
    )


def render_plantuml(puml_file: Path, png_file: Path) -> None:
    """Render a PlantUML diagram to PNG."""
    cmd = find_plantuml_cmd()
    subprocess.run(
        cmd + ["-tpng", str(puml_file)],
        check=True,
        text=True,
        capture_output=True,
        timeout=180,
    )
    generated = puml_file.with_suffix(".png")
    if not generated.exists():
        raise FileNotFoundError(f"PlantUML output missing: {generated}")
    if generated != png_file:
        generated.replace(png_file)


def process_md(md_path: Path, render: bool = True) -> list[Path]:
    """Process a single SWDD markdown file: extract diagrams and optionally render."""
    img_dir = md_path.parent / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    blocks = extract_blocks(md_path)
    expected_names = {diagram_name for _, diagram_name, _ in blocks}

    # Remove stale artifacts that no longer exist in the current markdown
    for existing in img_dir.iterdir():
        if existing.suffix not in {".mmd", ".puml", ".png"}:
            continue
        stem = existing.stem
        if stem not in expected_names:
            existing.unlink()

    for lang, diagram_name, code in blocks:
        ext = ".mmd" if lang == "mermaid" else ".puml"
        source_file = img_dir / f"{diagram_name}{ext}"
        png_file = img_dir / f"{diagram_name}.png"
        source_file.write_text(code, encoding="utf-8")
        if render:
            try:
                if lang == "mermaid":
                    render_mermaid(source_file, png_file)
                else:
                    render_plantuml(source_file, png_file)
            except Exception as exc:
                print(f"warning: failed to render {source_file.name}: {exc}", flush=True)
        generated.append(source_file)
        if png_file.exists():
            generated.append(png_file)
    return generated


def find_md_files(swdd_root: Path, modules: list[str] | None = None) -> list[Path]:
    """Find SWDD markdown files in the swdd directory.

    If modules is provided, only look in those subdirectories.
    Otherwise, scan all subdirectories.
    """
    files = []
    if modules:
        for module in modules:
            mod_dir = swdd_root / module
            if not mod_dir.is_dir():
                print(f"warning: module directory not found: {mod_dir}")
                continue
            # Find any *_Software_Detailed_Design_Document_EN.md
            md_list = list(mod_dir.glob("*_Software_Detailed_Design_Document_EN.md"))
            if not md_list:
                # Fallback: any .md file
                md_list = list(mod_dir.glob("*.md"))
            files.extend(md_list)
    else:
        files = sorted(swdd_root.glob("*/*_Software_Detailed_Design_Document_EN.md"))
    return files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract and render diagrams from SWDD markdown files."
    )
    parser.add_argument(
        "--swdd-root", type=Path, default=Path.cwd() / "swdd",
        help="Path to the swdd directory (default: ./swdd)"
    )
    parser.add_argument(
        "--module", action="append", dest="modules",
        help="Process specific module(s), repeatable (default: all)"
    )
    parser.add_argument(
        "--extract-only", action="store_true",
        help="Only extract .mmd/.puml source files, do not render PNG"
    )
    args = parser.parse_args()

    swdd_root = args.swdd_root.resolve()
    if not swdd_root.is_dir():
        print(f"SWDD directory not found: {swdd_root}")
        return

    md_files = find_md_files(swdd_root, args.modules)

    if not md_files:
        print("No SWDD markdown files found.")
        return

    for md_path in md_files:
        print(f"processing {md_path.relative_to(swdd_root.parent)}", flush=True)
        for output in process_md(md_path, render=not args.extract_only):
            print(f"  {output.relative_to(swdd_root.parent)}", flush=True)


if __name__ == "__main__":
    main()
