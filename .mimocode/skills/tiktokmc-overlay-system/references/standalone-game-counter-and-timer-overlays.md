# Standalone game counter and timer overlays

Use this reference for compact, single-purpose Minecraft overlays exposed from an add-on tab.

## Typography: prove the real Minecraft font rendered

Declaring `font-family: Minecraftia, monospace` is not sufficient. A preview captured before a remote webfont finishes loading can silently show the monospace fallback and be mistaken for the final design.

Production pattern:

1. Package the chosen Minecraft-style webfont inside the add-on, e.g. `static/fonts/minecraft.woff2`.
2. Serve it through `/addon-assets/<addon_id>/fonts/minecraft.woff2`.
3. Use `font-display:block` and apply the font explicitly to every visible text element, especially large numbers.
4. Start rendering/polling only after `document.fonts.ready` resolves.
5. Render a mock screenshot and inspect the actual glyphs before calling the design finished.

Do not use Monocraft as a substitute for an in-game Minecraft UI font; Khito already rejected Monocraft as a general UI typeface.

## Death counter contract

- Use the app-authoritative active-run `run_deaths`, never Minecraft lifetime `player.deaths`.
- Keep the number large and horizontally centered; the whole overlay should be centered, not left- or right-anchored.
- Hide it outside active/paused run states.
- Prefer a compact Minecraft-style panel with a transparent page background.

## Frozen Hands layout: Mining Fatigue parity

When Khito says to match the Mining-game fatigue timer, the canonical reference is:

`C:\Users\yusar\Documents\Code\Live\McPY\overlay\timerdiamond.html`

Match its composition, not merely its colors:

- Body anchored to the right edge: `justify-content:flex-end; align-items:center`.
- One compact horizontal pill, flat on the right edge and rounded on the left.
- Icon box on the left, timer text on the right.
- Active state slides in from the right; zero/inactive slides out and becomes hidden.
- Preserve an explicit `<img>` icon slot even when the final icon has not arrived. Use a clearly temporary fallback only for development previews; replace it when Khito supplies the asset.
- Timer format is `M:SS`, with tabular numerals and the self-hosted Minecraft font.
- Keep polling non-overlapping and event-idle; no permanent RAF or decorative infinite loops.

## Preview and handoff rule

Do not say the visual design is finished merely because HTML/CSS exists and route/tests pass. Produce a rendered preview using live-shaped mock payloads after fonts are ready. If a required visual asset is pending, implement the slot and behavior, but wait for that asset before sending the final preview or describing the design as final.
