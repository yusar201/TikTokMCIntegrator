# Minecraft official-texture icon extraction (for overlay icons)

Goal: use REAL Minecraft textures (not emoji, not CDN) as overlay icons — e.g. mob heads for
`kill_mob` objectives in Survival Rush — embedded as base64 so OBS/stream needs no network.

Verified 2026-08-10 while producing 38 mob-head icons for the Survival Rush objective overlay.
Extended same session to cover all 159 item/block targets (collect_item, craft_item, mine_block,
place_block, smelt_item, fish_item, trade_item, use_item).

## 1. Get the client jar (no game install needed)

Mojang serves it; nothing to install:

```bash
cd /tmp
# version manifest -> pick the version -> its metadata url
curl -s https://launchermeta.mojang.com/mc/game/version_manifest.json -o vm.json
python3 -c "import json;d=json.load(open('vm.json'));print([v['url'] for v in d['versions'] if v['id']=='1.20.1'][0])"
# that url -> version json -> downloads.client.url, then download the jar
curl -s <version-json-url> -o v.json
python3 -c "import json;print(json.load(open('v.json'))['downloads']['client']['url'])"
curl -s -o mc1201.jar "<client.jar url>"   # ~23 MB
```

**Textures ARE inside client.jar** at `assets/minecraft/textures/...` (block/, item/,
entity/<mob>/<mob>.png, entity/enderdragon/dragon.png, etc.).

## 2. Enumerate/extract with Python zipfile — NOT `unzip -l`

`unzip -l mc1201.jar | grep textures` returned 0 mid-download (file incomplete). Python
`zipfile` is reliable:

```python
import zipfile
z = zipfile.ZipFile('/tmp/mc1201.jar')
heads = [n for n in z.namelist() if ('head' in n or 'skull' in n) and n.endswith('.png')]
with z.open('assets/minecraft/textures/entity/creeper.png') as f:
    open('/tmp/creeper.png','wb').write(f.read())
```

Note: since ~1.19.3 some item/block textures moved to a separate asset bundle, but **entity
skins stayed in client.jar** — mob heads are safe to pull from the jar.

## 3. Crop the face from the entity skin

Entity skins are flat UV atlases (most mobs 64×32; warden/dragon are 128×/256×). The face is a
specific UV island, NOT always the humanoid layout.

- **Humanoid mobs** (zombie, skeleton, creeper, piglin, villager-types like evoker/vindicator/
  pillager/witch, iron_golem, enderman): front face is the standard **8×8 at (8,8)-(16,16)**.
- **Non-humanoid mobs** (spider, guardian, ghast, slime, ravager, rabbit, chicken, etc.) need
  per-mob boxes — see the verified table below.
- **Ender Dragon:** no flat `dragon_head` item icon in the jar (it's a 3D model). Use the face
  region on `entity/enderdragon/dragon.png` (dark head + glowing purple eyes read fine).

Resize crops with `Image.NEAREST` (pixelated), square-pad if width≠height so all icons match.

## 4. CRITICAL — vision cannot reliably read coordinates off a zoomed grid

Do NOT ask vision to "give the source box from this gridded zoom." It hallucinates coordinates.
The workflow that actually worked:

1. **Dense zoomed grid** (12×, red grid + yellow coord labels every 2–4px) is fine for *you* to
   eyeball a rough region, but don't trust vision's numeric answer.
2. **Candidate-variant approach:** crop N candidate boxes (e.g. the suspected region ± a few
   offsets, plus standard UV positions), paste them side-by-side on a dark background, and label
   each with its box coords as yellow text. Ask vision to pick "which labeled box shows the
   face." It picks by label far more reliably than it measures.
3. **Contact-sheet QA:** after cropping all mobs, build a labeled grid sheet (6 per row, light
   gray bg so dark mobs like spider/dragon stay visible), have vision list BAD ones, re-crop only
   those, re-verify. Expect 2–4 QA rounds. Dark-themed mobs (dragon, warden) look dark but are
   correct — judge by shape/glow, not brightness.

## 5. Embed as base64, keyed by entity id

```python
b64 = base64.b64encode(open(png,'rb').read()).decode()
# JS: var MOB_HEADS = {'minecraft:creeper':'data:image/png;base64,...', 'dragon_slayer':'...'};
```

38 icons ≈ 29 KB of base64 total — fine to inline in the overlay HTML. In `iconFor()`, for
`kill_mob` return an `<img src="data:...">` keyed by `definition.target.entity`, falling back to
the tracker emoji. Add `.icon img{width:100%;height:100%;image-rendering:pixelated}`. Keep the
contract constraints (no RAF, no infinite animation, ≤420px, `esc()`).

## Verified face-crop boxes (source px, left,top,right,bottom)

| Mob | Box | Mob | Box |
|---|---|---|---|
| humanoid (zombie/skeleton/creeper/piglin/evoker/vindicator/pillager/witch/iron_golem/enderman) | (8,8,16,16) | guardian / elder_guardian | (16,16,40,40) |
| spider / cave_spider | per-mob eye cluster | phantom | per-mob |
| slime | (26,0,42,16) | ravager | (16,16,36,36) |
| silverfish | (0,0,16,16) | rabbit | (32,6,38,12) |
| warden | (16,0,32,16) | endermite | (2,2,6,5) |
| blaze | (8,8,16,16) | ender dragon | (128,32,160,64) on dragon.png |

(Any mob not listed: use the candidate-variant method in §4 to find it.)

## 6. Item/block icons (non-mob trackers) — much easier than mob heads

Item and block textures are mostly flat 16×16 PNGs already shaped like icons — no face-cropping
needed. Search order per target name `minecraft:<name>`:

```python
def find_texture(name):
    item = f'assets/minecraft/textures/item/{name}.png'
    if item in entries: return item                       # flat item icon
    for cand in (f'assets/minecraft/textures/block/{name}_side.png',
                 f'assets/minecraft/textures/block/{name}.png'):
        if cand in entries: return cand                   # block face
    return None
```

This resolves ~98% of targets directly (156/159 in Survival Rush). The rest need overrides:

| Target | Problem | Fix |
|---|---|---|
| `chest`, `ender_chest` | no flat item texture; entity-model UV | **composite** front: lid `(14,14,28,19)` + base `(14,33,28,43)` + latch `(1,1,3,5)` pasted onto 14×15 canvas from `entity/chest/normal.png` / `ender.png` |
| `shield` | entity texture, not item | crop `(0,0,22,22)` from `entity/shield_base_nopattern.png` |
| `compass` | animated frames only | `item/compass_16.png` |
| `crossbow` | states only | `item/crossbow_standby.png` |
| `crafting_table` | `_side` exists but `_front` is the recognizable face | `block/crafting_table_front.png` |
| `magma_block` | `magma_block.png` doesn't exist | `block/magma.png` |
| `respawn_anchor` | states only | `block/respawn_anchor_side0.png` |

**Blank-icon QA:** some items are legitimately thin/transparent (arrow, stick, torch, chain,
ghast_tear, wheat_seeds — opaque px < 15% of 256). These are CORRECT, not broken. Don't
"fix" them.

**Integration in `iconFor()`:** resolve `target.item || target.block || target.entity`, look up
`ITEM_ICONS` (non-mob) / `MOB_HEADS` (kill_mob), render `<img src="data:...">`, fall back to
tracker emoji when no texture. 159 item icons ≈ 60 KB base64; total overlay ~97 KB — fine inline.

**TEST PITFALL:** Survival Rush contract test `test_no_oneblock_references` does naive
`"anchor" not in src` — `minecraft:respawn_anchor` (legit craft target) trips it. Exempt the
token (`src.replace("respawn_anchor","")`) before asserting; keep the OneBlock guard intact.
