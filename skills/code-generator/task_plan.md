# Task Plan

## Goal
Require an explicit user decision whenever the SAD architecture differs from the skill's accepted default baseline.

## Phases
- [x] Inspect the current model, renderer, and layering rules.
- [x] Expand default layer/module configuration.
- [x] Update renderer for responsibility panels, module-specific edges, and richer cross-cutting content.
- [x] Render and visually inspect SVG/PNG.
- [x] Run configuration/layering checks and summarize the architecture decision.
- [x] Codify the accepted SVG topology in the main skill workflow.
- [x] Add conformance checks for the default baseline and verify references.
- [x] Add a blocking architecture-conflict decision gate.
- [x] Add decision-record and conformance requirements.

## Decisions
- Preserve MCAL and OS/RTOS as peer layers with no mutual dependency.
- Preserve `HAL -> MCAL` and `HAL -> CDD -> MCAL`.
- Render `Native/Device Service -> HAL` and `OSIF -> OS/RTOS` as separate module-level paths.

## Errors Encountered
| Error | Attempt | Resolution |
|---|---|---|
| `rg` pattern backticks were interpreted by the shell | 1 | Re-run with a single-quoted pattern |
