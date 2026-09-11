# WebView2 dashboard downloads

## Symptom

A dashboard download works in a normal browser but the same button does nothing inside the
pywebview desktop shell. The representative flow fetches a remote image, renders it to canvas,
creates a PNG blob, assigns it to an `<a download>` element, and calls `link.click()`.

## Root cause

pywebview's `ALLOW_DOWNLOADS` setting defaults to `False`. WebView2 therefore suppresses the
blob-backed anchor download at the shell layer. Because the frontend code can finish normally,
there may be no exception, alert, or console error.

## Correct fix

Enable downloads after importing pywebview and before creating the window:

```python
import webview
webview.settings['ALLOW_DOWNLOADS'] = True
window = webview.create_window(...)
```

Do not first replace a working browser download pipeline with a custom JS-to-Python save bridge.
The browser-versus-desktop asymmetry is evidence to inspect embedded-browser policy first.

## Regression coverage

Use a focused source assertion when the native renderer cannot be exercised headlessly:

```python
source = MAIN.read_text(encoding='utf-8')
enable = "webview.settings['ALLOW_DOWNLOADS'] = True"
assert enable in source
assert source.index(enable) < source.index('webview.create_window(')
```

Also retain a frontend assertion for the intended export contract (`canvas.toBlob`, a `.png`
filename assigned to `link.download`, and `link.click()`). Run Python compilation and the focused
frontend/shell tests before the full PyInstaller build.

## Deployment verification

A Python launcher change requires a full build. Follow `tiktokmc-build-deploy`: ensure the EXE is
not running, use `./deploy.sh --full`, verify the root release EXE and `_internal/`, confirm there
is no nested release directory, and compare build/release timestamps. The final native save-dialog
interaction should be checked after restarting the desktop app.
