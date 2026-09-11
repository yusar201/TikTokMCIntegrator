# PyInstaller Windowed Mode — Debug Logging Pattern

## Problem

When a PyInstaller-frozen app uses `console=False` (windowed/no-console mode), all `print()` output goes to `/dev/null`. If background threads catch exceptions and only `print()` them, the failures are 100% invisible:

```python
def _play_tts():
    try:
        edge_tts.Communicate(...).save(out_file)
    except Exception as e:
        print(f"[TTS] Error: {e}")  # GOES NOWHERE — console=False
```

The dashboard shows "success" (HTTP 200), but no audio plays. The error is swallowed — no traceback, no file, no way to diagnose.

## Pattern: File-Based Error Logging

Replace bare `print()` exception handlers in background threads with file-based logging:

```python
def _play_tts():
    log_file = os.path.join(BASE_DIR, "tts_debug.log")
    try:
        import edge_tts, traceback

        tts_dir = os.path.join(BASE_DIR, "tts")
        os.makedirs(tts_dir, exist_ok=True)
        out_file = os.path.join(tts_dir, f"tts_{int(time.time())}.mp3")

        rate = speed.replace("%", "") if "%" in speed else "+0"
        ptch = pitch

        async def _gen():
            communicate = edge_tts.Communicate(
                text, voice, rate=rate, pitch=ptch
            )
            await communicate.save(out_file)

        asyncio.run(_gen())

        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

        sound = pygame.mixer.Sound(out_file)
        sound.play()
        msg = f"[TTS] {nick}: \"{text[:80]}\" ({len(text)} chars) | voice={voice}"
        print(msg)
        with open(log_file, "a") as f:
            f.write(msg + "\n")
    except Exception as e:
        err = f"[TTS ERROR] {e}\n{traceback.format_exc()}"
        print(err)
        with open(log_file, "a") as f:
            f.write(err + "\n")
```

## Key Points

- Log to `BASE_DIR` (same directory as config.yml) — always writable in frozen apps
- Include `traceback.format_exc()` — full stack trace beats a one-line error
- Append mode (`"a"`) — preserves history across crashes
- Still call `print()` — useful when running from terminal during development

## Diagnosis Workflow

1. Add file-based logging to the suspicious thread/function
2. Rebuild + redeploy
3. Reproduce the issue
4. Read the log file: `cat release/TikTokMCIntegrator/tts_debug.log`
5. Fix the root cause, remove or reduce logging

## Common Root Causes Found This Way

- Missing scoped imports (`NameError: name 'time' is not defined`)
- edge_tts dependency not bundled (aiohttp, certifi missing in PyInstaller build)
- asyncio event loop error in background thread
- Network timeout fetching TTS audio from Microsoft
- pygame mixer init failure (no audio device)
