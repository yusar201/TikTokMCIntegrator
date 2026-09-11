# JS Silent ReferenceError: esc() vs escHtml()

## Symptom

A dashboard section (e.g., Song Test Search) shows **nothing at all** after an action — no results, no error text, not even a "Searching..." or "Search failed" message. The UI is just blank. No console errors are visible to the user (browser source in OBS, or user doesn't have DevTools open).

## Root Cause

A helper function is defined with one name but called with another:

```javascript
// Defined as:
function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// But called as:
container.innerHTML = `<span>${esc(msg)}</span>`;  // esc() is undefined → ReferenceError
```

In async handlers, the flow is:
1. `try` block calls `esc()` → `ReferenceError` thrown
2. `catch(e)` block catches it, tries to set error HTML — also calls `esc()` → second `ReferenceError`
3. Both `innerHTML` assignments fail before rendering anything
4. The unhandled promise rejection is silent in the UI

## Diagnosis

1. Check if the function exists: `grep "function esc\|const esc\|let esc\|var esc" static/script.js`
2. Check what name is actually called: `grep "esc(" static/script.js`
3. If the names don't match, you found it

## Fix

Add an alias right after the function definition:

```javascript
function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Alias for callers that use 'esc'
const esc = escHtml;
```

This preserves existing `escHtml()` callers and fixes all `esc()` callers.

## Hit In

- TikTokMCIntegrator Song Test Search (2026-05-21): `esc()` called 8 times in the song section but function was `escHtml()`. All search results, error messages, queue rendering silently failed.
