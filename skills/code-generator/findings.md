# Findings

- The existing example contains only one or two modules per layer, so the rendered diagram cannot communicate typical layer contents.
- `Service -> Os` is architecturally valid only as the concrete `OSIF -> OS/RTOS` dependency. A layer-border arrow is visually ambiguous.
- The requested default topology remains: App -> Native/Device Service -> HAL; HAL -> MCAL for on-chip devices; HAL -> CDD -> MCAL for off-chip devices; MCAL and OS/RTOS are peers on hardware.
- Cross-cutting concerns should remain vertical: Types, Bus, and Cfg.
- The first rich render exposed connector overlap: the Native path must route outside the Service module grid, while OSIF keeps its own farther-right OS path.
- The accepted SVG needs to be referenced by the main SKILL.md as an authoritative fallback baseline; otherwise future runs may treat it as a decorative example.
- A SAD/default mismatch must be a blocking user decision, not an automatic precedence rule in either direction.
- `layered-architecture-styled.png` duplicated the default PNG byte-for-byte, while its same-named SVG was stale; the styled pair had no references and was removed.
