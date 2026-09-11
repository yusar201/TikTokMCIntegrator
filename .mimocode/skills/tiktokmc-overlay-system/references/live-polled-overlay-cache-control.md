# Live-Polled Overlay State and Browser Cache Control

Use this when a dashboard edit persists correctly but an OBS Browser Source or WebView2 preview keeps showing an older label, goal, counter, or other JSON-backed value.

## Diagnose the boundary before fixing

Trace the exact pipeline:

1. Dashboard form value.
2. POST response body.
3. Runtime JSON state file.
4. GET `/api/stats/<overlay>` response body and headers.
5. Overlay polling request.
6. Rendered DOM text/property.

If the POST response and production JSON file already contain the new value, saving is not the bug. If a fresh Flask test-client GET also returns it, isolate the browser request/render layer instead of rewriting persistence.

Do not assume an iframe reload fixes this. Reloading the same URL can reuse the same cached GET response.

## Durable two-layer no-cache pattern

For mutable state polled at a stable URL, protect both HTTP and browser layers.

### Flask response

```python
response = jsonify(read_live_state())
response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
response.headers["Pragma"] = "no-cache"
response.headers["Expires"] = "0"
return response
```

### Overlay polling

```javascript
const requestUrl = url + (url.includes('?') ? '&' : '?') + '_=' + Date.now();
const response = await fetch(requestUrl, { cache: 'no-store' });
```

Use this narrowly for genuinely live mutable endpoints. Do not disable caching globally for static assets or every overlay endpoint without evidence.

## Regression test

The strongest Flask test covers the whole save-to-read contract:

1. Redirect both the POST route and stats reader to one temporary state file.
2. POST a new label/value through the real dashboard endpoint.
3. Assert the POST response contains the new value.
4. GET the stats endpoint and assert the new value is returned.
5. Assert exact no-cache headers.
6. Render the overlay template and assert its polling code adds a timestamp, uses `cache: 'no-store'`, and writes the returned field into the target DOM element.

This distinguishes persistence bugs from stale browser responses and prevents either side of the fix from being removed later.

## Production verification

After canonical deployment:

1. Verify the production runtime state file was preserved.
2. Start the released EXE only for a bounded smoke test.
3. Confirm `/health` is HTTP 200.
4. Fetch `/api/stats/<overlay>` from the released app and inspect both JSON and cache headers.
5. Open the real overlay URL in a browser.
6. Read the rendered DOM value and visually confirm the expected text.
7. Stop the smoke-test EXE if the user did not ask to leave it running.

For TikTokMCIntegrator's Coin Goal Jar, the durable source of truth is `data/coin_goal.json`; label, sublabel, goal, and current should update on the existing polling interval without an OBS refresh after the fixed release has been loaded once.
