# TTS Effects (Whisper/Yell) for edge-tts

## Summary

Added whisper/yell voice effects to the TTS system. Viewers type `. *whisper* hello` or `. [yell] come here` to trigger effects.

## Architecture

```
Viewer chat → minecraftDiamond.py (parse effect) → API (apply effect) → edge-tts (rate/pitch) → ffmpeg (audio filter) → pygame (play)
```

## Files Changed

- `tts_effects.py` — NEW module: effect parsing, config, ffmpeg post-processing
- `minecraftDiamond.py` — Parse effect tags from viewer messages
- `app.py` — Apply effects in TTS speak endpoint
- `constants.py` — Added `TTS_EFFECTS` tuple
- `templates/index.html` — Voice Effects section on TTS dashboard
- `static/script.js` — testTts() parses effects, history shows effect badges
- `TikTokMCIntegrator.spec` — Added `tts_effects` to hiddenimports

## Viewer Syntax

```
. *whisper* hello everyone    → whisper mode
. [yell] come here            → yell mode
. {scream} BOO                → yell mode
. *whisp* shorthand           → whisper mode
. [loud] volume               → yell mode
. hello                       → normal (no effect)
```

## Effect Configuration (tts_effects.py)

```python
EFFECTS = {
    "whisper": {
        "ssml_rate": "-15%",      # Slower speech
        "ssml_pitch": "-10Hz",    # Lower pitch (NOT %, must be Hz!)
        "ffmpeg_filter": "volume=0.4,highpass=f=300,lowpass=f=3500",
        "pygame_volume": 0.6,     # Quieter
    },
    "yell": {
        "ssml_rate": "+10%",      # Faster speech
        "ssml_pitch": "+5Hz",     # Higher pitch
        "ffmpeg_filter": "volume=2.5,acompressor=threshold=0.02:ratio=6",
        "pygame_volume": 1.0,     # Full volume
    },
}
```

## Critical Pitfalls

1. **edge-tts does NOT support SSML style tags** — `<mstts:express-as>` is Azure-only. Passing SSML causes edge-tts to READ THE TAGS LITERALLY (e.g., "prosody volume soft hello" instead of whispering).

2. **edge-tts pitch format is Hz, NOT %** — `"-10%"` causes silent failure (no audio, no error). Must be `"-10Hz"`.

3. **Use rate/pitch params directly** — Don't wrap text in SSML. Pass rate and pitch to `edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)`.

4. **ffmpeg post-processing is optional** — If ffmpeg not available, falls back to SSML-only mode (rate/pitch changes only). Effects still work, just less dramatic.

## Research: True Whisper/Yell TTS

For REALISTIC whisper/yell (not just volume/rate changes), need Azure Cognitive Services TTS:

| Engine | Whisper? | Yell? | Free Tier | Latency |
|--------|----------|-------|-----------|---------|
| edge-tts | ❌ Simulated | ❌ Simulated | Free | <1s |
| Azure TTS | ✅ Real | ✅ Real | 500K chars/mo | ~300ms |
| ElevenLabs | ✅ Real | ✅ Real | 10K chars/mo | ~1.5s |
| Bark (local) | ✅ Real | ✅ Real | Free (GPU) | 3-10s |

**Azure SSML for real whisper:**
```xml
<mstts:express-as style="whispering" styledegree="1.5">
    Keep your voice down!
</mstts:express-as>
```

**ElevenLabs tags (v3 model):**
```
[whispers] Don't make a sound.
[shouts] Watch out behind you!
```

## Dashboard UI

Added "Voice Effects" section to TTS dashboard showing:
- Whisper card: `. *whisper* hello` example
- Yell card: `. [yell] come here` example
- All valid tags listed at bottom
- Effect badges in TTS history (blue=whisper, red=yell)

## PyInstaller Build

See `references/pyinstaller-build.md` for full build/deploy process.

**Key**: New modules must be added to `hiddenimports` in `TikTokMCIntegrator.spec` or they won't be bundled.

## Skip Cooldown

5-second global cooldown on `!skip` prevents double-skips when multiple viewers type it simultaneously.

## Missing API Endpoints After Refactoring

Always verify ALL frontend API calls have matching backend routes after refactoring. Real example: `/api/bot/logs` was missing — console showed "Waiting for bot to start..." forever.
