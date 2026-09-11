# TTS one-time cold-start warmup

Session learning: first viewer-triggered TTS can be noticeably slower because the process pays the edge-tts import/network setup, TLS/session setup, and pygame mixer init on the first request. If Khito asks to reduce first-TTS latency, warm once at application startup — not on a recurring timer.

## Pattern

Add a process-local guard + background thread near the TTS loop/client code:

```python
_tts_warmup_started = False
_tts_warmup_lock = threading.Lock()

def start_tts_warmup_once():
    global _tts_warmup_started
    with _tts_warmup_lock:
        if _tts_warmup_started:
            return False
        _tts_warmup_started = True

    def _warm():
        # Load live TTS config. If disabled, log and return.
        # Generate a tiny throwaway phrase/file with edge_tts.Communicate(...).save(...).
        # Initialize pygame.mixer if needed.
        # Delete the warmup file.
        # Do NOT play audio, write TTS history, or touch cooldown state.
        pass

    threading.Thread(target=_warm, daemon=True).start()
    return True
```

Call it once from the main launcher startup after config/profile setup and before/alongside Flask startup. Also call it in the `app.py __main__` dev path if that path is still supported.

## Requirements

- **One-time only per process**: protected by a lock/flag.
- **No recurring warmup**: Khito explicitly does not want every-X-minutes warmups.
- **Silent**: do not play the generated file.
- **No side effects**: do not update `_tts_last_at`, `_tts_user_at`, or TTS history.
- **Live config aware**: use current voice/rate/pitch and skip if TTS is disabled.
- **Clean up**: remove the temp `tts_warmup.mp3` in `finally`.
- **Non-blocking**: start a daemon thread; startup must not wait for network TTS.

## Verification

Use a Flask/app import smoke test to assert the guard:

```python
import app as a
assert a.start_tts_warmup_once() is True
assert a.start_tts_warmup_once() is False
```

Then deploy normally and tell Khito to restart `release/TikTokMCIntegrator.exe`.
