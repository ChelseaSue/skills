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
