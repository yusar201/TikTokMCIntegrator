# Gift Catalog Completeness — Union Architecture (verified 2026-09-02)

## The bug this replaced

`minecraft_main.py`'s connect handler **overwrote** `release/data/available_gifts.json` on every bot connect with only the room's gift panel. TikTok's `/gift/list/` self-reports `is_full_gift_data: False` — on Khito's room it holds ~700 gifts out of ~2,800 known. Any gift learned earlier (custom creator gifts, event exclusives, region-locked gifts) lost its name/icon/price on the next connect. Symptom: Super GG (12988) and KhitoFam (938882) had no icon in the catalog despite being sent hundreds of times.

## Rule: the catalog is a union cache, never a replacement

Every write goes through `gift_catalog.merge_into_catalog(path, entries, source=...)`:

- **Per-field trust for price/name:** `event` (live GiftEvent) > `panel` > `region` > `euler`/history (`_SOURCE_RANK = {euler:0, region:1, panel:2, event:3}`). A higher-trust source upgrades; a lower-trust source only fills blanks.
- **Icons never downgrade:** an empty icon from a new source never erases an existing one.
- **`source` is recorded per entry** so debugging knows where each gift's metadata came from.
- **Entries without an `id` are rejected** by `normalize_entry`.

## The four sources

| Source | Module / call | Verified yield (2026-09-02) |
|---|---|---|
| Room panel on connect | `minecraft_main.py` connect handler → merge | 701–703 gifts; authoritative price for current-panel gifts |
| 20 regional panels | `gift_catalog_sync.sync_regions` → `GET /webcast/gifts?region=XX` | 1,767 unique; recovered Game Controller (6581/7569, 100 coins, US panel, absent from ID) |
| Euler full catalog | `gift_catalog_sync.sync_euler_catalog` → `GET /webcast/gifts/catalog` | 2,783 rows / 28 pages; recovered retired gifts (Spirit of 45, Live Up, Fighting, Spark ring) |
| Local history | `gift_catalog_backfill.backfill_all(gift_log.json, points.db)` | +6 new / 2 updated; price = **GCD of observed ledger totals** per gift_id (exact once any 1× send exists) |

Result: **701 → 2,789 gifts, zero pre-existing gifts lost** (set-diff vs backup). All 76 gifts ever received are present with a price; 66/76 with an icon.

## Live-event self-learning

Every completed `GiftEvent` teaches the catalog its own gift **before any icon lookup** (`source="event"`; no network call). This is the only path for gifts that exist in no catalog anywhere (Super GG, KhitoFam). Placement: after the latency-critical dispatch, before `append_gift_log` — never add awaits or network I/O on this path.

## Dashboard surface

- `POST /api/gifts/refresh` — blocking union rebuild (panel + regions + full catalog + history); wired to the **Sync Gift Catalog** button in the Gifts panel (`#btn-refresh-gift-catalog`, handler `refreshGiftCatalog()`, cache-bust `script.js?v=42`).
- `GET /api/gifts/available` — serves the union cache. `?scope=panel` filters to `in_panel` only; `?scope=room` filters to `in_panel OR seen`; unrecognized/absent scope = full catalog, so overlays and icon/name lookups are unchanged.
- Auto-sync on connect runs via `asyncio.to_thread` so it never delays gift dispatch.

## Room-scope visibility — the picker's data model (2026-09-02)

Every catalog entry carries two booleans, defaulted by `normalize_entry` and merged by `_better` (flags only ever turn ON during a merge — never cleared):

- `in_panel` — TikTok can deliver this gift to the room *right now*. Defaults true for `source="panel"` and `source="event"` (a GiftEvent shipped the gift struct into this room, which is proof of deliverability). Re-evaluated on every connect by `gift_catalog.mark_panel_gifts(path, panel_ids)`: stamps the fresh panel's ids and **clears** the flag everywhere else — gifts rotate out of panels. `seen` is untouched by this.
- `seen` — ever received as a real GiftEvent. Defaults true only for `source="event"`. **The history backfill does NOT set it** (it merges with `source="euler"`), so a pre-flag catalog must be stamped explicitly (recipe below).

### The Add/Edit Gift picker UX (Khito's actual complaint)

The picker must answer “which exact gift ID can be sent to this room now?”, not merely “which known gifts share this name.” Duplicate-name families can contain many region-specific IDs with identical names, prices, and icons. Therefore:

- Default to strict `?scope=panel` (`in_panel` only). Do not include merely `seen` gifts and do not silently fall back when a search has zero matches.
- Offer the full union only through an explicit **All known gifts** selector, with a visible warning that those IDs may be regional or unavailable.
- Show icon and exact gift ID beside the name; name and coin price are not unique identifiers.
- Fetch panel + full scope together when useful, but keep caches separate: full-catalog icon/name preload populates `cachedAllGifts`, never the current-panel `cachedAvailableGifts`. Otherwise an early-return cache path can bypass the panel fetch and leak every regional duplicate into the modal.
- Verify with a real duplicate family end to end: compare the released `?scope=panel` response with the rendered modal, then switch explicitly to all-known and confirm the larger set appears. A source-level API test alone does not catch frontend cache poisoning.

### Migration recipe for a pre-flag catalog

1. Re-run each entry through `normalize_entry` with its own `source` — flags default correctly for panel/event entries, not for euler/region.
2. Stamp `seen` (+`in_panel`, receiving a gift is proof it is deliverable here) from `SELECT DISTINCT gift_id FROM gift_ledger WHERE kind='gift' AND gift_id != ''`.
3. Also stamp from distinct `gift_log.json` gift_ids (catches icon-bearing log entries the ledger misses).
4. Verify: room-scope count sane (~700+76, not 2,789); `76/76` ever-received gifts visible in room scope; spot-check Super GG 12988 / KhitoFam 938882.

### Scope tests

`tests/test_gift_catalog_scope.py` covers flag defaults, merge behavior, and room filtering. `tests/test_gift_catalog_routes.py` must distinguish `panel`, `room`, and full responses. `tests/test_gift_picker_frontend.py` must lock strict panel-first wiring, explicit full-catalog switching, no silent fallback, and the rule that icon preload cannot seed the panel cache. Also exercise the released modal with a duplicate-name family; require one panel match and multiple matches only after choosing all-known.

## Hard-won gotchas

- **Persisted icon shape is a flat URL string; TikTok's payload `ImageModel` is a dict** (`{url_list: [...]}`). `_first_url` must accept both. Bug caught by contract test: a dict-only normalizer would have wiped all 701 existing icons on the first merge.
- **Euler API rejects plain `urllib` with Cloudflare 403 `error code: 1010`.** Use `httpx` with a browser User-Agent + `x-api-key` header (imported lazily inside `gift_catalog_sync`).
- **`pageSize` above 100 is silently clamped** by the catalog endpoint (2,783 rows arrive as 28 pages × 100).
- **Euler's own image host returns 403 `Origin not allowed`** on server-side fetches — Euler rows carry a correct name/price but no usable icon. Store an empty icon, never a broken URL (the UI hides empty icons). CDN-hash reconstruction from `imageUri` failed: 96 host/folder/suffix URL shapes tried, all 404. Only Krupuk resolved.
- **Retired gifts are iconless forever unless cached:** ~10 of the 76 received gifts have no image anywhere; 6 of those do have cached MP4 animations (gift asset downloader manifest), which is why the Top Gift overlay animated them despite the missing icon.
- **The Exclusive page (`page_type 15`) returns 0 gifts without authentication** — consistent with the room panel being region/room-scoped, not account-scoped.
- **PyInstaller:** add `gift_catalog*` + `httpx` to `hiddenimports` in `TikTokMCIntegrator.spec`.
- **Verifying frozen-exe bundling — parse `build/TikTokMCIntegrator/PYZ-00.toc`, never check for loose folders.** PyInstaller compiles pure-Python modules into the PYZ archive; `ls release/_internal/httpx` returning nothing proves nothing (that wrong check nearly concluded httpx was missing on 2026-09-02). Working check:

  ```bash
  C:\Python313\python.exe -c "import ast; data=ast.literal_eval(open(r'build/TikTokMCIntegrator/PYZ-00.toc',encoding='utf-8',errors='replace').read()); inner=data[1] if isinstance(data[0],str) else data; names=[e[0] for e in inner]; print({w: any(n==w or n.startswith(w+'.') for n in names) for w in ('gift_catalog','httpx','points_store')})"
  ```

  (The TOC is a 2-tuple `(pyz_path, entries)`; a failed unwrap yields an implausibly small module count like 2 — treat that as a signal the parse is wrong, not that modules are missing.)

## Verification recipes

- **Tests:** `tests/test_gift_catalog{,_sync,_routes,_backfill,_frontend,_scope}.py` + `tests/test_gift_picker_frontend.py` — 92 tests. Key contracts: merge preserves pre-existing gifts (nothing lost), `pageSize ≤ 100`, icon string-or-dict, sync button wiring + cache bust, scope flags never cleared by a merge, picker room-scope-first wiring.
- **Real-data dry run (before touching `release/data/`):** copy `available_gifts.json` to a temp dir, run the three syncs against the copy, then diff ID sets vs the original — require `pre-existing gifts lost: NONE`.
- **In-place populate (exe not running, relaunch approval unavailable):** backup to a timestamped `.bak`, run the sync modules from source against the real paths (same functions the exe uses), verify counts + set-diff. Took ~32s total.
- **Coverage check:** `SELECT DISTINCT gift_id FROM gift_ledger WHERE kind='gift'` vs catalog — report in-catalog / priced / iconed counts.
