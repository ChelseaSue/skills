# SWDD Generator - External Tool Setup Guide

## 1. PlantUML

PlantUML is used to render sequence diagrams (`.puml` -> `.png`).

**Dependencies:** Java 11+

**Installation:**
1. Install Java JDK/JRE 11 or later
2. Download PlantUML jar from https://plantuml.com/download (MIT version recommended)
3. Place the jar in a stable location (e.g., `D:/tools/plantuml/plantuml-mit-1.2025.8.jar`)
4. Set environment variable:
   ```
   PLANTUML_JAR=D:/tools/plantuml/plantuml-mit-1.2025.8.jar
   ```

**Verify:**
```bash
java -version
java -jar $PLANTUML_JAR -version
```

## 2. Graphviz

PlantUML internally uses Graphviz's `dot` engine for rendering non-sequence diagrams (component diagrams, class diagrams, etc.). Without Graphviz, PlantUML can only render sequence diagrams.

**Installation:**
- Windows: Download from https://graphviz.org/download/ and install to e.g. `D:/tools/Graphviz/`
- Linux: `sudo apt install graphviz`
- macOS: `brew install graphviz`

Ensure `dot` is in PATH. Optionally set:
```
GRAPHVIZ_DOT=D:/tools/Graphviz/bin/dot.exe
```

**Verify:**
```bash
dot -V
```

## 3. Mermaid CLI

Mermaid CLI renders Mermaid diagrams (`.mmd` -> `.png`): static diagrams and flowcharts.

**Dependencies:** Node.js 18+, Chrome/Chromium (for Puppeteer)

**Installation:**
```bash
# Global install (recommended)
npm install -g @mermaid-js/mermaid-cli

# Or use npx (downloads on first use)
npx @mermaid-js/mermaid-cli -V
```

Chrome/Chromium is auto-downloaded by Puppeteer. If needed, set:
```
PUPPETEER_EXECUTABLE_PATH=C:/path/to/chrome.exe
```

**Verify:**
```bash
npx @mermaid-js/mermaid-cli -V
```

## 4. Python

Python is used for DOCX generation and diagram extraction scripts.

**Dependencies:** Python 3.9+

**Installation:**
```bash
pip install -r ~/.claude/skills/swdd-generator/requirements.txt
```

This installs: `python-docx`, `Pillow`, `requests`

**Verify:**
```bash
python -c "import docx; import PIL; print('OK')"
```

## 5. Environment Variables Summary

| Variable | Purpose | Example |
|----------|---------|---------|
| `PLANTUML_JAR` | Path to PlantUML jar file | `D:/tools/plantuml/plantuml-mit-1.2025.8.jar` |
| `GRAPHVIZ_DOT` | Path to Graphviz dot executable (optional if in PATH) | `D:/tools/Graphviz/bin/dot.exe` |
| `PUPPETEER_EXECUTABLE_PATH` | Path to Chrome/Chromium (optional if auto-detected) | `C:/Program Files/Google/Chrome/Application/chrome.exe` |

## 6. cscope

`cscope` is used for accurate C source analysis — **function definition lookup, symbol references, caller/callee relationships**. The SKILL mandates cscope over `grep` because it understands C syntax, distinguishes definitions from calls, and has a pre-built index for whole-project queries in milliseconds.

### Installation (cross-platform)

#### Linux

```bash
# Debian / Ubuntu
sudo apt install cscope

# RHEL / CentOS / Fedora
sudo dnf install cscope        # or: sudo yum install cscope

# Arch
sudo pacman -S cscope
```

#### macOS

```bash
brew install cscope
```

#### Windows — option A: WSL (recommended)

Install Ubuntu in WSL and run `sudo apt install cscope`. Then run all SWDD generation commands from inside WSL so paths and tools stay consistent.

#### Windows — option B: MSYS2 / Git Bash

```bash
# In MSYS2 shell
pacman -S cscope
```
Git Bash alone does not ship cscope; install via MSYS2 or copy `cscope.exe` into a directory already in Git Bash's PATH.

#### Windows — option C: Chocolatey

```powershell
choco install cscope
```

#### Windows — option D: Prebuilt binary

Download a prebuilt `cscope.exe` from http://cscope.sourceforge.net/ (or a mirror such as https://code.google.com/archive/p/cscope-win32/ — unmaintained but functional for read-only queries). Place `cscope.exe` anywhere in PATH.

### Verify

```bash
cscope --version
# Expected output: cscope: version 15.9 (or similar)
```

### Build the database (must run once per project, and after any source change)

From the project root directory:

**Linux / macOS / Git Bash / WSL / MSYS2:**
```bash
# 1. List all C source files (adjust paths for your project layout)
find BBS_K311_APP/src BBS_K311_APP/MCAL -type f \( -name "*.c" -o -name "*.h" \) > cscope.files

# 2. Build the database
cscope -bqk
# Generates: cscope.out, cscope.in.out, cscope.po.out
```

**Windows PowerShell (when `find` is not available):**
```powershell
Get-ChildItem -Path BBS_K311_APP\src, BBS_K311_APP\MCAL -Recurse -Include *.c, *.h |
    ForEach-Object { $_.FullName } | Out-File -Encoding ASCII cscope.files
cscope -bqk
```

Flag meaning:
- `-b` build only, no interactive UI
- `-q` build fast inverted index (required for `-d` queries)
- `-k` kernel mode (do not auto-add `/usr/include`) — required for cross-compile embedded projects

Add `cscope.out`, `cscope.in.out`, `cscope.po.out`, `cscope.files` to `.gitignore`.

### Verify a query works

```bash
# Find the definition of 'main'
cscope -dL -1 main

# Find callers of a function
cscope -dL -3 ABBSM_vidMainFunction

# Find callees (functions called by this function)
cscope -dL -2 ABBSM_vidMainFunction

# Find all references to a symbol
cscope -dL -0 AINCU_u16PeriodTime
```

Output format (four space-separated columns):
```
<file_path> <containing_function> <line_number> <source_line>
```

### Cross-platform notes

- **Path separators**: cscope accepts both `/` and `\` on Windows. `cscope.files` generated by PowerShell uses `\`; generated by Git Bash uses `/`. Both are valid — pick one and stick with it per project.
- **Paths with spaces**: wrap each path in `cscope.files` with double quotes.
- **File encoding**: `cscope.files` must be ASCII or UTF-8 **without BOM**. PowerShell's default `Out-File` uses UTF-16 — use `-Encoding ASCII` explicitly as shown above.
- **Database freshness**: cscope does not auto-detect source changes. Rebuild with `cscope -bqk` whenever `.c` / `.h` files change, or scripts/CI can run it unconditionally before SWDD generation.
- **Native Windows vs WSL**: both work, but do not mix — a database built under WSL paths (`/mnt/c/...`) is not consumable by native Windows cscope. Pick one environment per project.

---

## Example Commands (BBS_K311 Project Reference)

```bash
# Current project environment
# Java:      java 11.0.23 LTS
# PlantUML:  D:/tools/plantuml/plantuml-mit-1.2025.8.jar
# Graphviz:  D:/tools/Graphviz/bin/dot.exe (v14.0.0)
# Node.js:   node + npx @mermaid-js/mermaid-cli
# Python:    3.13

# Extract and render all diagrams for a single module (mmd->png, puml->png)
python ~/.claude/skills/swdd-generator/scripts/extract_diagrams.py \
  --swdd-root ./swdd --module ABBSM

# Extract and render all modules
python ~/.claude/skills/swdd-generator/scripts/extract_diagrams.py \
  --swdd-root ./swdd

# Generate DOCX for a single module
python ~/.claude/skills/swdd-generator/scripts/md_to_docx.py \
  --swdd-root ./swdd ABBSM

# Generate DOCX for all modules
python ~/.claude/skills/swdd-generator/scripts/md_to_docx.py \
  --swdd-root ./swdd

# PlantUML standalone render
java -jar D:/tools/plantuml/plantuml-mit-1.2025.8.jar \
  -tpng swdd/ABBSM/img/ABBSM_Dynamic_Behavior.puml

# Mermaid standalone render
npx @mermaid-js/mermaid-cli \
  -i swdd/ABBSM/img/ABBSM_Static_Diagram.mmd \
  -o swdd/ABBSM/img/ABBSM_Static_Diagram.png
```
