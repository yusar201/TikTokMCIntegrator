# TikTokLive 7.0.0a1 → 7.0.0b2 Upgrade Audit (2026-07-24)

## Production decision

Upgrade and pin the Python pair exactly:

```text
TikTokLive==7.0.0b2
TikTokLiveProto==0.2.2
```

Do not adopt the parallel npm/TypeScript, full-types, C#, Java/Kotlin, or Maven releases: TikTokMCIntegrator has no runtime component using them. Euler dashboard/Discord/OAuth/leaderboard/proxy-mesh/RabbitMQ changes likewise require no project change because the bot does not consume those products. Revisit Sign API headers or non-English Gift Gallery changes only if project code begins consuming those exact surfaces.

## Compatibility evidence

- `TikTokLiveClient.__init__`: unchanged.
- `TikTokLiveClient.run`: unchanged, including `fetch_gift_info` and `fetch_live_check`.
- Existing project event imports and custom SuperFan events: compatible.
- `WebDefaults.tiktok_sign_url` upstream default changed from `tiktok.eulerstream.com` to `api.eulerstream.com`; the project override controls the effective endpoint.
- Cookie handling now scopes cookies to `.tiktok.com`; no project adaptation required.
- Existing-event schema additions are additive:
  - `GiftEvent`: `secondary_effect_info`, `gift_variant_id`, `shiny_card_unlock_token`, `gift_effect`
  - `LinkMicBattleEvent`: `cross_room_layout`, `tracking_extra`, `match_theme_display_resource`
  - `LinkEvent`, `SubPinEventEvent`: `public_area_msg_common`
  - `LinkLayerEvent`: `link_envelope_content`
  - `GuideEvent`: `frequency_rule`

## Upstream badge bug remains

`ExtendedUser._get_all_badge_info` in b2 still reads v2 names:

```text
self.badges          → actual v3 field: badge_list
badge.badge_scene    → actual v3 field: scene_type
log_extra            → actual v3 field: privilege_log_extra
```

Keep TikTokMCIntegrator’s `minecraft_main.py` compatibility patch. Verify the monkey patch in the Windows Python environment used for PyInstaller, not only in a bare venv.

## New event: battle item cards / power-ups

`LinkMicBattleItemCardEvent` is exported and mapped from `WebcastLinkMicBattleItemCard`. Useful scalar fields:

```text
battle_id
msg_type
award_reason
```

`msg_type` discriminates card obtain, critical strike, smoke, award notice, extra time, special effect, potion, wave, Top 2/3, vault glove, and related notices. The event also contains corresponding nested card objects.

Project integration:

- Registry key: `LinkMicBattleItemCardEvent`
- Dashboard name: `Battle Power-Up`
- Category: `battle`
- Generic dynamic-action variables: `battle_id`, `msg_type`, `award_reason`
- No hard-coded handler is needed until a power-up requires bespoke state or behavior.

Constructed-event probe expectation:

```python
LinkMicBattleItemCardEvent(
    battle_id=42,
    msg_type=BattleCardMsgType.USE_SMOKE_CARD,
    award_reason=7,
)
# build_context →
{"battle_id": "42", "msg_type": "USE_SMOKE_CARD", "award_reason": "7"}
```

## Dependency and install discipline

Pin TikTokLive and TikTokLiveProto as a matched pair. Do not add direct pins for transitive packages such as `websockets` or `protobuf` merely because their resolved versions changed; TikTokLive’s metadata should constrain them unless a concrete bug proves otherwise.

Validate the complete project requirements in a new venv with `pip install -r requirements.txt` and `pip check`. This audit exposed an unrelated stale `mcrcon==0.3.3` pin that modern PyPI could not resolve; production already used compatible `mcrcon==0.7.0`, so the project pin was corrected. General lesson: a client upgrade is not installable until the whole requirements file resolves cleanly.

## License classification

The exact 7.0.0b2 wheel ships AGPL-3.0 with additional permissions. Section 18 explicitly permits downstream TikTok LIVE overlays, games, stream bots, and other automated tools without forcing downstream AGPL adoption. Section 19 excludes specified commercial closed-source/hosted SaaS, WebSocket relay, scraping API, and managed-hosting uses. TikTokMCIntegrator’s local stream-bot use fits the explicit bot exception; reassess before turning it into a hosted third-party service.

Always inspect the license included in the exact package version rather than relying on old metadata or memory.

## Verification recipe

1. Diff installed production version against candidate wheel: signatures, event exports/mappings, custom events, signer defaults, schema fields, and monkey-patched methods.
2. Write a failing release-contract test for exact pins and registry exposure.
3. Update `requirements.txt` and `event_registry.py`.
4. Run a constructed-event `build_context` probe.
5. Fresh-venv install and `pip check`.
6. Run complete repository test suites.
7. Run Windows build-Python compile/import/event/badge-patch checks.
8. Ensure the app is closed, then `./deploy.sh --full`.
9. Verify release/dist EXE hash or size+fresh mtime, root layout, `_internal`, frontend synchronization, and no nested release directory.
10. Launch the frozen EXE only for smoke testing; verify `/health` and `/api/event-registry` show `Battle Power-Up`, then stop the temporary process unless asked to leave it running.

PyInstaller may strip `.dist-info` metadata, so missing metadata directories are not proof a package was omitted. The executable/API smoke test is the authoritative packaging check.