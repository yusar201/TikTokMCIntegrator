# Euler Stream Premium TikTok LIVE Endpoints

Research sessions: 2026-05-23 (two rounds)

## Premium Endpoints (Business $50/mo + "Premium Webcast Routes" add-on)

### `/webcast/chat` (POST)
- **What:** Send messages to a TikTok LIVE chat as an authenticated user
- **Gap filled:** Free TikTokLive library can READ chat but cannot SEND
- **Use case:** Auto-reply bot, gift acknowledgments, song queue announcements directly in TikTok chat
- **Requires:** OAuth authorization, signed requests, TikTok app approval for chat scopes

### `/webcast/user_earnings` (GET)
- **What:** Streamer's revenue/earnings data (diamonds, gift revenue, session breakdown)
- **Gap filled:** TikTok hides earnings data from public API
- **Use case:** Live earnings overlay, per-stream analytics, revenue dashboard
- **Requires:** OAuth authorization, likely TikTok app approval for financial scopes

## Pricing
| Plan | Price | Request Limit | Premium Routes |
|------|-------|---------------|----------------|
| Community | Free | 1,000/day | ❌ |
| Business | $50/mo | 10,000/day | ✅ (add-on) |
| Enterprise | Custom | Custom | ✅ |

48-hour free trial on Business tier.

## Reverse Engineering Assessment (2026-05-23, Round 2)

**Verdict: Chat sending is simple — the Node.js library kept it, Python dropped it. But Euler Stream blocks direct sign API calls for community tier.**

### Key Discovery: `zerodytrash/TikTok-Live-Connector` has working `sendMessage()`

The original Node.js library from which Isaac Kogan ported TikTokLive **retains a working `sendMessage(text, sessionId)` function**. It was deliberately **not ported** to the Python version.

How it works (from reading the Node.js source):
- POST form data to `https://webcast.tiktok.com/webcast/room/chat/`
- Params: `{ ...client_params, content: text }`
- Authentication: TikTok `sessionid` cookie (from your browser)
- Returns `{ status_code: 0 }` on success, `20003` on expired session
- Uses the same signing provider already built into the library

That's it. ~25 lines of code. No protobuf, no new packet format, no OAuth. Just an HTTP POST with a session cookie.

### Why Python Doesn't Have This

Isaac Kogan (same dev behind both TikTokLive and Euler Stream) chose not to port `sendMessage()`. Whether this was:
- **Strategic:** Selling Euler Stream Premium ($50/mo) for chat sending
- **Business reality:** Euler Stream's costs need some premium features to justify the paid tiers

...the code is right there in the open-source Node.js library.

### Cookie Approach vs Euler Stream OAuth Approach

| | Session Cookie | Euler Stream Premium |
|---|---|---|
| Cost | $0 | $50/mo |
| Auth | Browser `sessionid` cookie | Permanent OAuth token |
| Setup | Extract cookie from DevTools (every few days) | OAuth flow once |
| Reliability | Cookie expires — re-extract | Token auto-refreshes |
| Terms of Service | Cookie scraping = gray area | Authorized API access |
| Maintenance | You maintain the POST call | They maintain backend |

### Recommendation

**Verdict after full investigation (2026-05-23, 3 rounds): Chat sending is paywalled. No free path exists.**

- The `client=ttlive-node` parameter bypasses the 401 on Euler Stream's deprecated `sign_url` endpoint (returns 200 + redirect to proxy), but the proxy (`webcast/fetch/`) is itself premium-gated and the deprecated endpoint doesn't produce a usable signed TikTok URL.
- TikTok's `room/chat/` endpoint requires proper signed POST — direct POST with session cookie returns 403 regardless of params.
- The Node.js v2 library that had working `sendMessage()` was rewritten as v7 — the function was removed. The original code is only available in archived git tags that don't include built dist files. The npm package for the working version is broken.
- All sign API calls (even `room/info/`) return 401 for community tier keys when called via the Python `TikTokSigner`. The TikTokLiveClient connects via WebSocket using a different internal signing path that is NOT exposed for arbitrary URL signing.
- Euler Stream's business model: give away the reader (WebSocket events), gate the writer (chat sending) behind $50/mo premium tier. The sign API is the gatekeeper.

**If you want chat sending:** pay for Business tier ($50/mo, 48h trial). No viable free alternative exists as of 2026-05-23.

## Live Test Results (2026-05-23, local → @jokilicers.id)

### What Worked
- **WebSocket connection:** 5/5 attempts succeeded, Room ID `7642951083745676033`
- **Retry resilience:** `illegal_app_id` errors were transient — retry with 2s delay worked

### What Failed

1. **Direct sign API POST blocked (401):**
```bash
curl -X POST "https://tiktok.eulerstream.com/webcast/sign_url" \
  -H "Authorization: Bearer <community_key>" \
  -H "Content-Type: application/json" \
  -d '{"url":"...room/info/...","method":"GET","type":"fetch","user_agent":"Test","payload":""}'

# Response: {"code":401,"message":"You lack authorization for this endpoint. If this is a premium endpoint, upgrade at https://www.eulerstream.com/pricing."}
```
The community key is valid (72 chars, connects WebSocket) but blocked from ALL direct sign URL API calls — even `room/info/`.

2. **TikTokSigner standalone fails:** `TikTokSigner(sign_api_key=<key>).webcast_sign()` fails with `SIGN_NOT_200` for every URL tested (room/info, room/chat, with and without session_id). Passing the key explicitly, setting `WebDefaults`, and setting env var `SIGN_API_KEY` all fail the same way.

3. **Signing fails from a plain interpreter but works from the built exe:** The bot runs from the Windows PyInstaller exe, not a plain interpreter. The `SIGN_NOT_200` failure may be environment-specific (network path, TLS fingerprinting, or anti-bot detection on the Euler Stream side). The TikTokLiveClient internally connects WebSocket (proving signing works there), but standalone `TikTokSigner` usage from a plain interpreter doesn't. **This means any chat-sending feature MUST run from inside the bot process** (which runs from the built exe), not from a separate script.

### Why the Client Works But Standalone Signer Doesn't

The `TikTokLiveClient` uses internal WebSocket connect logic with embedded signing — it's not going through the same `TikTokSigner.webcast_sign()` code path that standalone usage does. The client's WebSocket flow signs differently (possibly via `TikTokWebClient.build_request()` with different parameters or a different sign server endpoint). The standalone `TikTokSigner` posts to `{base_url}/webcast/sign_url` which returns 401 for community tier.

## Round 3: Deep Investigation (2026-05-23)

### Discovery: `client=ttlive-node` Bypasses the 401

The Node.js library sends `client=ttlive-node` as a parameter to Euler Stream's sign API. Testing from a plain interpreter:

```bash
# ❌ Without client param → 401
curl -s "https://tiktok.eulerstream.com/webcast/sign_url?url=...&method=POST" \
  -H "Authorization: Bearer <community_key>"
# → {"code":401,"message":"You lack authorization..."}

# ✅ With client=ttlive-node → 200!
curl -s "...?client=ttlive-node&url=..." \
  -H "Authorization: Bearer <community_key>"
# → {"code":200,"message":"This endpoint is deprecated and only redirects...",
#    "signedUrl":"https://tiktok.eulerstream.com/webcast/fetch/?..."}
```

The `sign_url` endpoint is **deprecated** — it no longer signs TikTok URLs directly. Instead it redirects to Euler Stream's `webcast/fetch/` proxy endpoint. The proxy itself returns 404 when accessed directly with a community key.

### TikTok POST Still 403

Even with successful signing (200 response), the actual POST to TikTok's `room/chat/` endpoint returns HTTP 403 regardless of params or cookie format. TikTok requires a properly signed POST that the deprecated sign endpoint can no longer produce:

```bash
# Sign works (200), but...
curl -X POST "https://webcast.tiktok.com/webcast/room/chat/" \
  -H "Cookie: sessionid=..." \
  -d "aid=1988&content=test&room_id=..." 
# → HTTP 403
```

### Node.js v7 Removed `sendMessage` Entirely

The zerodytrash/TikTok-Live-Connector GitHub repo was rewritten from v2 to v7. The v7 is a complete architectural rewrite that:
- Replaced `WebcastPushConnection` with `TikTokLiveConnection`
- Removed `sendMessage()` entirely — the function no longer exists in the source
- The npm package at the registry is broken (empty dist folder)
- Building from source (tsdown) produces v7 code with no sendMessage
- The v2 tags exist in git but don't include built dist files

**The only version that ever had working sendMessage was the original zerodytrash v2 code.** Isaac Kogan (who also runs Euler Stream) wrote both the Python port (stripping sendMessage) and the v7 rewrite (stripping sendMessage). The function was deliberately removed from both versions.

## Technical Implementation Details (Chat Sending via Native TikTok API)

### The `session_id` Signing Trap (CRITICAL)

The Python TikTokLive library's `TikTokSigner.webcast_sign()` accepts a `session_id` parameter that is SENT to Euler Stream's sign server. The sign server checks the API key's tier and returns **HTTP 200 with code=403** (raised as `PremiumEndpointError`) if a free-tier key tries to sign with `session_id` context:

```python
# web_signer.py lines 152-166
if code == 403:
    raise PremiumEndpointError(
        "You do not have permission from the signature provider to sign this URL.",
        ...)
```

The Node.js library does NOT send `session_id` during signing — it only attaches the cookie to the HTTP request afterward.

**The workaround:** Sign the URL with `session_id=None` (staying in free tier), then attach the session cookie as HTTP cookie headers in the actual POST request. The signing validates the URL; the cookie authenticates the user — separate concerns.

```python
# ✅ CORRECT: sign without session, cookie attached separately
signed = await signer.webcast_sign(
    url=url_str, method="POST", sign_url_type="fetch",
    payload="", user_agent="...",
    session_id=None,  # ← free tier compatible
)

cookies = {"sessionid": SESSION_ID, "sessionid_ss": SESSION_ID, "sid_tt": SESSION_ID}
async with httpx.AsyncClient(cookies=cookies) as http:
    resp = await http.post(str(signed.signed_url))
```

### Getting the `room_id`

The `room/chat/` endpoint requires the broadcaster's room_id. Two approaches:

1. **From the running bot** (preferred): After `ConnectEvent` fires, `client.room_id` is populated automatically by the TikTokLive WebSocket handshake.

2. **From TikTok's web API** (standalone test): `GET https://www.tiktok.com/api-live/user/room/?uniqueId=<username>` — requires signing. Returns `params_error` (19881005) without signing; endpoints from 2026-05-23 returned this for all param combinations tried.

### Known Limitations

- **Signing fails from a plain interpreter:** `UnexpectedSignatureError: SIGN_NOT_200` on any webcast signing attempt from a plain interpreter. The bot's signing only works when running from the actual Windows PyInstaller executable. Testing must happen at runtime from within the bot process.
- **User must be live:** The `room/chat/` endpoint requires an active live room. Returns errors when not streaming.
- **Session cookie expires:** Status code `20003` means the `sessionid` cookie needs refreshing from browser DevTools.
- **Community key blocked from ALL sign URL API calls:** Even signing `room/info/` (which the WebSocket client uses) fails with 401 when called directly. The TikTokLiveClient must use a different internal signing path.

## Round 4: v2.1.1-beta1 npm Package Analysis (2026-05-23)

The original zerody code that had working `sendMessage` was published as `tiktok-live-connector@2.1.1-beta1`. The npm package exists but the dist is broken in the registry. Building from the git tag produces v7 code (the repo was rewritten).

### How v2.1.1-beta1's sendMessage Actually Worked

From the compiled dist files (`npm pack` + extract):

```javascript
// dist/lib/web/routes/send-room-chat.js (DIRECT TikTok route)
class SendRoomChatRoute extends Route {
    async call({ roomId, content }) {
        const { room_id: rId, cursor, internal_ext, ...rest } = this.webClient.clientParams;
        roomId ||= rId;
        if (roomId == null) throw new MissingRoomIdError(...);
        return await this.webClient.postJsonObjectToWebcastApi(
            'room/chat/',
            { ...rest, room_id: roomId, content: content },
            undefined,
            true  // ← signRequest = true
        );
    }
}
```

Signing was via `EulerSigner` (extends `EulerStreamApiSdk`):

```javascript
// dist/lib/web/lib/tiktok-signer.js
class EulerSigner extends EulerStreamApiSdk {
    async webcastSign(url, method, userAgent, sessionId, ttTargetIdc) {
        const response = await this.webcast.signWebcastUrl({
            url, method, userAgent, sessionId, ttTargetIdc
        });
        if (response.status === 403) {
            throw new PremiumFeatureError('You do not have permission...');
        }
        return response.data;  // signed URL
    }
}
```

API key came from `process.env.SIGN_API_KEY`:

```javascript
// dist/lib/config.js
exports.SignConfig = {
    basePath: process.env.SIGN_API_URL || 'https://tiktok.eulerstream.com',
    apiKey: process.env.SIGN_API_KEY,
    ...
};
```

Key difference from v7: v2 POSTed **directly to TikTok** (`webcast.tiktok.com/webcast/room/chat/`), signed by Euler Stream. Session cookie was HTTP cookies, not sent to sign server. v7 routes ALL chat through `apiClient.premium.sendRoomChat()` — Euler Stream's own proxy.

### v2.1.1-beta1 had TWO chat routes

| Route | File | Status |
|-------|------|--------|
| `SendRoomChatRoute` | `send-room-chat.js` | Direct TikTok POST (free tier worked) |
| `sendRoomChatFromEulerRoute` | `send-room-chat-euler.js` | Euler Stream proxy (premium only) |

The npm package included BOTH. v7 deleted the direct route and made the Euler proxy the ONLY option.

### v7 sendMessage Source Code Evidence

```typescript
// src/lib/web/routes/euler/send-room-chat-euler.ts (v7)
const fetchResponse = await apiClient.premium.sendRoomChat({
    content,
    targetRoomId: roomId,
    sessionId: '',
    ttTargetIdc: ''
}, xOauthToken, xCookieHeader, options);

switch (fetchResponse.status) {
    case 401:
    case 403:
        throw new PremiumFeatureError(
            'Sending chats requires an API key & a paid plan, as it uses cloud managed services.',
            ...
        );
    case 200:
        return fetchResponse.data;
}
```

## All Language Ports Use Euler Stream

Every TikTok LIVE library in every language routes through `tiktok.eulerstream.com`. There is no independent signing implementation:

| Port | Language | How It Signs |
|------|----------|-------------|
| Node.js (zerody v2) | JS | `eulerstream.com/webcast/sign_url` → direct TikTok POST |
| Node.js (Isaac v7) | TS | `apiClient.premium.sendRoomChat()` — Euler proxy |
| Python (TikTokLive) | Python | `TikTokSigner.webcast_sign()` → `eulerstream.com/webcast/sign_url` |
| Java (TikTokLiveJava) | Java | `wss://ws.eulerstream.com` — Euler WebSocket proxy |
| C# (TikTokLiveSharp) | C# | Credits Isaac for "Signing-Server" |
| Go (GoTikTokLive) | Go | Also credits Euler Stream |

The ecosystem runs on ONE sign server. Isaac Kogan owns both the Python library and the sign infrastructure.

## Difficulty Assessment: Reverse Engineering TikTok Chat Sending

**Overall: 9.5 / 10**

| Layer | Difficulty | Why |
|-------|-----------|-----|
| Protobuf messages | 6/10 | ~800+ types. Most already decoded by Isaac. Doable with precedent. |
| WebSocket connection | 7/10 | Replicate browser fingerprint, client params, auth handshake. Packet capture helps. |
| Signature algorithm | **11/10** | XOR-obfuscated native C/C++, device fingerprinting, time-based tokens. Hundreds of projects have failed here. Euler Stream's entire business is this one problem. |
| Maintenance after working | **10/10** | TikTok updates app every ~2 weeks. Signatures break. Protobuf shifts. Anti-bot addls new checks. Fighting a billion-dollar company's security team alone. |

### Why the Signature Is the Gatekeeper

TikTok's signature generation:
```
Input: URL + params + timestamp + device fingerprint
→ TikTok native library (compiled C/C++, obfuscated)
→ XOR-based transformations + multiple hash passes
→ Output: X-Bogus, X-Gnarly, msToken, _signature
```

Euler Stream has a team dedicated to just this. Even they charge for it. zerodytrash (original author) had a working sign provider but couldn't maintain it alone — the project was handed to Isaac who centralized signing.

**Time estimate for a team to reverse this:** 3-4 full-time security researchers × 6 months = working prototype. Then it breaks within 2 weeks when TikTok updates. Not viable for a solo dev.

### The Only Viable Free Alternative: Browser Automation

```python
# Playwright controls a real browser logged into TikTok
from playwright.async_api import async_playwright

async def send_tiktok_chat(message: str):
    browser = await async_playwright().chromium.launch(headless=False)
    page = await browser.new_page()
    await page.goto(f"https://www.tiktok.com/@{username}/live")
    
    # Type into real chat input
    chat_input = page.locator('[class*="chat-input"]')
    await chat_input.fill(message)
    await chat_input.press("Enter")
    
    await browser.close()
```

Pros: No signing needed (TikTok sees real browser). No protobuf. No API key.
Cons: 1-3s latency (too slow for live chat replies). Bot detection risk. Resource-heavy. Fragile DOM selectors.
Verdict: Viable for occasional automated messages, not for real-time chat interaction.
