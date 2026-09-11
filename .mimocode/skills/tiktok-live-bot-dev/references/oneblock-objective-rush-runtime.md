# OneBlock Objective Rush — Runtime & Verification Pattern

Use this for phase-aware, event-driven objectives backed by a Forge helper and a Flask/Python runtime.

## V1 scope

Reliable objective types:

- `collect_item`: inventory gain after baseline, preserving peak progress if materials are later spent.
- `craft_item`: authoritative crafted-output counter delta; inventory movement must not count.
- `kill_mob`: player-attributed kill counter delta.
- `use_item`: completed item-use/consumption counter delta.
- `mine_oneblock`: authoritative OneBlock counter delta.
- `reach_next_phase`: phase ID change after baseline.

Exclude until explicitly requested: objective timers, survive-for-time, place/build verification, and no-damage challenges.

## Phase-aware selection

Random selection happens only after filtering:

1. Read current phase and helper capabilities.
2. Exclude objectives whose tracker is unsupported.
3. Exclude collect/craft/kill/use objectives unavailable in the current phase.
4. Apply Win-based difficulty.
5. Exclude the recent-objective window.
6. Prevent more than two consecutive objectives of one type.
7. Randomly choose from the remaining valid pool.

Use the installed OneBlock mod's actual phase JSON tables as the source of truth. Do not infer availability from generic Minecraft knowledge.

For a 10-Win run, reserve Win 10 for a Finale: when score is `9/10`, select only from the Finale pool.

## Forge helper counter contract

Expose two endpoints:

- `/objective/capabilities`
- `/objective/snapshot`

Snapshot includes player UUID/name/alive/dimension, inventory totals, monotonic server-session counters for crafted outputs, player kills, completed item uses, and OneBlock counter/phase state.

The Python engine captures a baseline when an objective starts and calculates deltas. Existing cumulative counts are safe: baseline 5 husk kills, current 6 means objective progress 1.

## Mandatory live verification order

After building and deploying the helper JAR, restart the Minecraft instance and test one tracker at a time:

1. Query ping, capabilities, and initial snapshot.
2. Craft a known quantity (for example four sticks); verify exact crafted delta.
3. Consume one item completely; verify `used +1`.
4. Record an existing mob-kill baseline, kill exactly one more personally, verify `kills +1`.
5. Mine the OneBlock once; verify counter, phase progress, blocks-left, and current-block changes.

Do not build runtime assumptions around Forge event semantics until these live probes pass.

## Pure Python engine invariants

- Default score: `0/10 Wins`, `0/3 Strikes`.
- No objective timer in V1.
- Completion is idempotent and awards one Win exactly once.
- Three Strikes remove one Win (floor zero) and reset Strikes.
- Free reroll does not add a Strike.
- Won runs reject further progress.
- Preserve peak collect progress when items are spent.
- Persist run ID, active objective instance, baseline, progress, score, recent IDs/types, and terminal status.
- Save state atomically through temp-file + `os.replace`.

## Minecraft-only headless runtime

Objective Rush gameplay should not require opening the desktop dashboard or connecting TikTok. Provide an explicit process mode that imports only the minimal Flask/Objectives stack:

```text
TikTokMCIntegrator.exe --objective-rush
```

Dispatch this mode at the earliest executable entry boundary, before importing the dashboard, native shell/tray, TikTok bot, Spotify, or TTS modules. The minimal runtime should bind locally, expose `/health` plus the same Objective Rush Blueprint/state engine, start its poller once, and preserve the normal executable path unchanged.

Package a one-click launcher beside the Minecraft server that:

1. Probes `/health` first and exits successfully if either the full app or headless runtime already owns the API.
2. Verifies the release executable exists.
3. Starts the EXE minimized with `--objective-rush`.
4. Waits for a positive health response with a finite deadline.

Verification must prove more than port availability: assert the health payload identifies Objective Rush mode, inspect the process command line, run a real `/rush start` through Minecraft, confirm authoritative API/sidebar state, then abort the synthetic run so persistent state is left clean. Do not silently auto-launch this process from a destructive Minecraft command until orphan-process and shutdown ownership are explicitly designed.

## Idempotent penalty API for cross-system catastrophes

When a Minecraft catastrophe needs exactly one Objective Rush penalty, add an API-level idempotency contract instead of relying on the caller not to retry:

- Accept a caller-generated operation ID with `fail`.
- Persist operation ID → resulting transition/score atomically with state.
- Return the original result for duplicate IDs without adding another Strike.
- Include post-transition Wins, Strikes, status, and active objective in the response.
- Test normal Strike, third-Strike rollover, duplicate submission, restart persistence, and timeout/retry behavior.

A local UUID that the Flask API never records provides no deduplication. Until this contract exists, the Forge caller must not retry ambiguous mutating requests automatically.

## Operator score controls and stream extension

Keep score edits authoritative in the Python service; Minecraft is only an operator-permission bridge.

Recommended contract:

- `/rush wins set|add|remove <amount>`
- `/rush goal set|add|remove <amount>`
- A dedicated POST admin endpoint accepting explicit `{field, operation, amount}`.
- Persist the complete run state atomically immediately after mutation.
- Preserve the current objective instance, baseline, and progress during ordinary active-run edits.
- Wins floor at zero and cannot exceed the current goal.
- Goal is positive and bounded, and cannot be reduced below current Wins.
- Reject score edits when no run is active, except extending a terminal `won` run.

The stream-extension edge case is mandatory:

```text
10/10, status=won
/rush goal add 10
→ 10/20, status=active
→ capture a fresh helper snapshot
→ select and announce a new eligible objective
```

Test active mutations, invalid bounds, atomic restoration, objective-instance preservation, and post-victory resumption. In live production verification, mutate and then reverse the mutation so the real run ends with its original score and objective progress.

### Command bridge details

- Register score mutation branches below `/rush` with permission level 2 even if ordinary lifecycle actions remain player-accessible.
- Pass a `CommandSourceStack`, not only a `ServerPlayer`, so console/RCON can run and verify admin mutations.
- Perform HTTP off-thread, then marshal chat/success/failure output back through `server.execute(...)`.
- Do not replay the active-objective announcement/title after ordinary score edits; the sidebar poll will project the saved score. Announce/select a new objective only when extending a terminal won run.
- An asynchronous RCON dispatch may return an empty command response before the HTTP callback finishes. Verify by polling authoritative API state and persisted state, not by treating the immediate RCON string as success/failure.
- A live smoke sequence should test and reverse both dimensions, e.g. `goal add N → goal remove N` and `wins add N → wins remove N`, while asserting the objective instance ID, baseline, progress, Strikes, and status remain unchanged.

## Flask integration pattern

Keep Objective Rush isolated from the generic add-on loader:

- Dedicated helper client.
- Dedicated service owning an `RLock`, engine, state store, helper status, and idempotent daemon poller.
- Dedicated Blueprint mounted under `/api/addons/oneblock/objective-rush`.
- Endpoints: `state`, `start`, `fail`, `reroll`, `surrender`, `abort`.
- Helper disconnect must not destroy or fail an active run; report disconnected state and resume evaluation after recovery.
- Return `409` for invalid lifecycle transitions and `503` when an action requires an unavailable helper.
- Put runtime state under `data/` and ignore the specific generated file in Git.

## Test gates

Before UI/overlay work:

- Unit-test every tracker delta and exact-once completion.
- Test phase/capability filtering, anti-repeat rules, Strike penalty, free reroll, Finale, terminal state, and atomic restoration.
- Simulate complete 10-Win runs across every real OneBlock phase, not only one representative phase.
- Register the Blueprint in the actual Flask app and smoke-test start/state/abort against the live helper.
- Abort and remove any smoke-test state so no fake run remains active.

## Deployment boundary

Source/API changes do not affect the running packaged app until rebuilt/deployed and restarted. Forge JAR changes require a full Minecraft instance restart; changing worlds is insufficient.
