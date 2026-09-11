# edge-tts Integration Pitfalls

**Lesson learned:** 2026-05-29 — TTS voice effects feature development.

## Critical: DO NOT Use SSML Wrapping

edge-tts does NOT support SSML input the way Azure TTS does. When you wrap text in `<speak><prosody>...</prosody></speak>` tags, edge-tts reads them as **literal text** — the TTS voice will read the HTML/XML code aloud.

```python
# WRONG — TTS reads "<speak version..." as literal text
ssml = f'<speak><prosody volume="soft" rate="-15%">{text}</prosody></speak>'
communicate = edge_tts.Communicate(ssml, voice)  # ❌ Reads XML tags

# CORRECT — use native rate/pitch parameters
communicate = edge_tts.Communicate(text, voice, rate="-15%", pitch="-10Hz")  # ✓
```

## Critical: Pitch Format MUST Be Hz

edge-tts expects pitch in Hz format, NOT percentage:

```python
# WRONG — causes silent failure, no audio plays
pitch = "-10%"  # ❌

# CORRECT
pitch = "-10Hz"  # ✓
pitch = "+5Hz"   # ✓
pitch = "+0Hz"   # ✓ (neutral)
```

Rate IS percentage: `"-15%"`, `"+10%"`, `"+0%"`

## Effect Parameter Reference

| Effect | Rate | Pitch | pygame_volume |
|--------|------|-------|---------------|
| whisper | -15% | -10Hz | 0.6 |
| yell | +10% | +5Hz | 1.0 |
| normal | +0% | +0Hz | 1.0 |

## ffmpeg Post-Processing

For enhanced audio effects (beyond rate/pitch changes):

```python
# Whisper — soft, muffled
"volume=0.4,highpass=f=300,lowpass=f=3500,aresample=44100"

# Yell — loud, compressed
"volume=2.5,acompressor=threshold=0.02:ratio=6:attack=5:release=50"
```

**Pitfall:** `limiter=limit=0.9` filter NOT supported in all ffmpeg versions. Use `acompressor` without limiter.

## Fallback Chain

1. **edge-tts rate/pitch** — always works, zero dependency
2. **pygame volume** — always works, basic loudness control
3. **ffmpeg post-processing** — optional, requires ffmpeg on target machine

If ffmpeg not available, effects still work via #1 + #2 (just less dramatic).

## Integration Pattern

```python
# In _tts_speak_impl():
effect = data.get("effect", "normal")
cfg = get_effect_config(effect)

# Generate with effect params
communicate = edge_tts.Communicate(
    text, voice,
    rate=cfg["ssml_rate"],
    pitch=cfg["ssml_pitch"]
)

# Post-process with ffmpeg if available
if effect != "normal":
    processed = apply_audio_effects(out_file, effect)
else:
    processed = out_file

# Play with volume
sound = pygame.mixer.Sound(processed)
sound.set_volume(cfg["pygame_volume"])
```
