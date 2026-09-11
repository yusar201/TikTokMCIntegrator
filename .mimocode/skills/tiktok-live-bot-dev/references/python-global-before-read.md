# Python `global` Must Be Before Variable Read

## The Rule

In Python, if a function contains `global <name>`, that variable name CANNOT be read anywhere in the function BEFORE the `global` declaration. Python's parser sees the `global` statement and treats ALL references to that name as global — but the compiler requires the declaration to appear before any read access.

## The Crash

```python
# BROKEN — SyntaxError at import time
def _spotify_get(endpoint, params=None):
    if _rate_limited():             # reads _rate_limit_until (global)
        remaining = int(_rate_limit_until - time.time())  # reads again
        return {"error": f"..."}
    ...
    if resp.status_code == 429:
        global _rate_limit_until     # SYNTAX ERROR — declared AFTER read
        _rate_limit_until = time.time() + seconds
```

Python sees the `global _rate_limit_until` on line ~346, backtracks, and realizes line ~327 already tried to read `_rate_limit_until` as a local variable (since at that point Python didn't know it was global). The compiler throws `SyntaxError` at module load time.

**Impact in PyInstaller builds:** The entire `spotify_handler.py` module is un-importable. PyInstaller silently skips it during `Analysis` (no import errors during build — it just excludes the module). At runtime, `import spotify_handler` raises `ModuleNotFoundError: No module named 'spotify_handler'`. The app crashes before the Flask server starts.

## The Fix

```python
# CORRECT — global declaration at top of function
def _spotify_get(endpoint, params=None):
    global _rate_limit_until  # MUST come before any read of _rate_limit_until

    if _rate_limited():       # now fine — global already declared
        remaining = int(_rate_limit_until - time.time())
        ...
```

## Detection

This never shows as a lint error in most tools. The file compiles fine with `python3 -c "import spotify_handler"` (the error triggers only when Python actually loads the module, which `py_compile` doesn't do). Detection method:

```bash
# Verify the module is actually importable (not just syntactically valid)
python3 -c "import spotify_handler; print('OK')"
```

If you see `SyntaxError: name '_rate_limit_until' is used prior to global declaration` in the traceback, a `global` statement was placed after a read.

## Applies To

- Any module-level global that is (a) read by helper functions and (b) written by the same function after a conditional check. Common pattern with rate-limit cooldowns, cache timestamps, and toggle flags.
