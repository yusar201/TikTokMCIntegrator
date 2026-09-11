# TTS whitelist permission pitfall

Symptom: Dashboard TTS whitelist appears saved, but a whitelisted viewer still gets `Permission denied: no_permission` when testing live.

Root causes to check:
1. Bot payload to `/api/tts/speak` must include `user_info.unique_id`. If `_extract_user_info()` returns user_info without `unique_id`, the Flask permission check sees an empty UID and whitelist can never match.
2. Normalize both sides: saved whitelist entries and incoming `unique_id` should use `str(value).strip().lower().lstrip('@')`. The UI label/placeholder says `@username`, but TikTok `unique_id` usually arrives without `@`.
3. Save endpoint should normalize whitelist before writing `data/tts_config.json`, and frontend can strip `@` for immediate visual feedback.

Verification:
- `python -m py_compile app.py minecraft_main.py`
- `node --check static/script.js`
- Regression: whitelist `['@ViewerOne']` saves as `['viewerone']`; `_check_tts_permission(cfg, {'unique_id': 'viewerone'})` returns `(True, 'whitelisted')`.
- Full deploy is required after changing `app.py`/`minecraft_main.py`; remind Khito to restart the exe/server after deploy.