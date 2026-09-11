# Self-hosted dashboard typography in WebView2

Use when replacing a decorative dashboard font with a readable game-themed font across a Flask/pywebview desktop app.

## Why self-host

A desktop app must not depend on Google Fonts being reachable. Bundle a legally redistributable font and its license under `static/fonts/`. For Minecraft-inspired typography, Monocraft is OFL-1.1 and has regular/bold variants; do not ship extracted Mojang font assets.

## Complete audit

Changing `body { font-family }` is insufficient. Search dashboard CSS and standalone templates for:

- `--font-heading`, `--font-body`, `--font-mono`, `--font-display`, and feature-specific tokens;
- hard-coded families and fallback clauses;
- `!important` families in optional skins/previews;
- native controls (`button`, `input`, `select`, `textarea`, `option`, `optgroup`);
- placeholders and pseudo-elements;
- setup/wizard pages with inline CSS;
- console/code/timestamp text when the user explicitly requests all text.

Font Awesome/icon-font families are intentional exceptions; never override them.

## Implementation

1. Add local regular and bold `@font-face` rules with `font-display: swap`.
2. Load the font stylesheet before the main stylesheet.
3. Point every dashboard typography token at the new family.
4. Explicitly apply it to native controls and placeholders so browser defaults cannot escape body inheritance.
5. Replace hard-coded families in special skins and fallback clauses.
6. Update standalone wizard/setup templates.
7. Remove obsolete remote font links and bump CSS cache versions.
8. Preserve the existing palette/layout unless a full redesign was requested; typography and color theme are separate concerns.

## Verification

- Source contract: obsolete family names are absent; font binaries and license exist.
- Validate binaries and compare hashes across source, `release/static/`, and `release/_internal/static/`.
- In a browser require `document.fonts.check('16px Monocraft') === true`.
- Inspect computed `fontFamily` on body, headings, controls, console/code, and special-skin text.
- Visually inspect both dashboard and wizard for clipping, overlap, ambiguous numbers, and small-text legibility.

Khito preference: TikTokMCIntegrator desktop text uses self-hosted Monocraft regular/bold everywhere, including console/mono and pixel-song skin text; Font Awesome icons remain unchanged.
