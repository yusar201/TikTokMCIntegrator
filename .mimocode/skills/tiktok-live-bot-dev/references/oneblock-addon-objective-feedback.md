# OneBlock Add-on and Objective Feedback Patterns

## Add-on discovery boundary

Treat a directory as an add-on only when it contains `addon.yml` or `addon.json`. Filter at directory discovery before validating IDs or constructing error cards. This prevents `__pycache__`, tooling, docs, and runtime artifacts from appearing as disabled add-ons.

## Action presets must reflect current gameplay

When a feature replaces old commands, update the add-on's `actions.yml` rather than leaving legacy presets visible. For Objective Rush, expose the current lifecycle commands (`/rush start`, `status`, `fail`, `reroll`, `surrender`, `abort`) and remove obsolete `/obprogress` presets unless explicitly retained as optional effects.

Verify presets through the real add-on loader, not YAML parsing alone, then verify the packaged copy after PyInstaller deployment.

## Matching overlay families

When asked to make one overlay resemble another, inspect and reuse the source overlay's design tokens and behavior:

- font family and weights;
- frame/border/inset-shadow recipe;
- background gradient and accent colors;
- dimensions and corner placement;
- show/hide behavior;
- entrance and update animations;
- progress-bar easing.

Keep inactive overlays transparent/hidden. Animate objective-instance changes separately from initial appearance.

## Event-specific Minecraft feedback

Do not emit only a generic “new objective” notification. Send an event `kind` through the Python service → helper HTTP bridge → server thread, and map it to chat color, title, particles, and sound:

- `objective`: enchant particles + XP pickup;
- `completed`: happy particles + level-up;
- `failed`: angry particles + negative villager sound;
- `rerolled`: portal particles + teleport sound;
- `victory`: firework/totem particles + challenge-complete sound;
- `surrendered` / `aborted`: smoke + deactivation sound.

Completion must be announced before the next objective announcement. Final completion emits victory instead of another objective. Execute all Minecraft player/world effects on `server.execute(...)`.

## Verification and deployment

1. Run focused Python Objective Rush and add-on-loader tests.
2. Compile the Forge helper with the working project toolchain.
3. Copy the rebuilt JAR to both the add-on package and active Minecraft instance.
4. Compare checksums across all JAR copies.
5. Build/deploy the PyInstaller release while preserving runtime config.
6. Read back packaged `actions.yml` and overlay files.
7. Remind the user to restart Minecraft after a JAR change and restart the desktop app after an EXE/add-on bundle change.
