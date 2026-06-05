# ADR-0001: PoB Decoding Strategy

## Status

Accepted (2026-06-05)

## Context

We need to decode Path of Building (PoB) share codes into structured data for our PoE2 tool site. PoB share codes are base64+zlib encoded XML. The question is: how should we approach decoding and parsing?

## Decision

We decode in three stages:
1. **URL-safe base64 restore** (`-_` → `+/`, add padding)
2. **Zlib decompress** (try zlib wrapper first, raw deflate fallback)
3. **XML parse** (standard library `xml.etree.ElementTree` — no lxml dependency)

For parsing, we extract:
- Build metadata (class, ascendancy, level)
- Tree specs (nodes as comma-separated attribute, NOT child elements)
- Skill sets (gems grouped by slot)
- Items (raw text with rarity/name/base parsing)
- Player stats (pre-computed by PoB — we NEVER recalculate)

## Consequences

- **Positive**: Zero external dependencies for decoding. Standard library only.
- **Positive**: Handles both full and minimal PoB export formats gracefully.
- **Negative**: XML parsing is format-dependent — if PoB changes its XML schema, we need to update the parser.
- **Mitigation**: Version field (`targetVersion`) is captured so we can handle schema changes per version.
