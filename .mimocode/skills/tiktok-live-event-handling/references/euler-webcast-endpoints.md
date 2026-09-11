# Euler Stream Webcast Endpoints — Complete Reference

Euler Stream (`https://tiktok.eulerstream.com/`) exposes three endpoints relevant to TikTok LIVE clients. The TikTokLive library uses endpoint 1 internally; endpoints 2 and 3 are exposed via the `EulerApiSdk` Python package and useful for direct API calls.

## Endpoint 1: `GET /webcast/fetch` — WebSocket Handshake (the one your library uses)

**Called from:** `TikTokLive/client/web/routes/fetch_signed_websocket.py:76-87` (via `fetch_webcast_url._get_kwargs`)

**Purpose:** Returns a raw protobuf `WebcastPushFrame` containing the WebSocket URL and the first `WebcastResponseMessage` to use as the initial ack. This is the very first call when the client connects to a live.

**Request:**
- **Method:** `GET`
- **Query params:**
  - `client=ttlive-other` (your SDK identity — Euler uses this for rate limits + analytics)
  - `room_id=<int as string>` (resolved room ID, or omit if you have `unique_id`)
  - `unique_id=<str>` (fallback if no room_id)
  - `cursor=<str>` (pagination cursor)
  - `user_agent=<str>` (the browser UA the lib pretends to be)
  - `client_enter=true` (signals "user is entering the room")
  - `platform=WebcastFetchPlatform.WEB|MOBILE` (determines which TikTok client the signature mimics)
  - `session_id=<str>` (TikTok `sessionid` cookie — required for MOBILE, optional for WEB)
  - `tt_target_idc=<str>` (TikTok `tt-target-idc` cookie)
  - `country=<SoaxProxyRegion>` (optional, for geo-spoofing via Soax proxies)
- **Headers:**
  - `x-oauth-token=<str>` (optional OAuth bearer)
  - `x-cookie-header=<str>` (optional full cookie string)

**Response:**
- **200:** Raw protobuf bytes (a `WebcastPushFrame` containing `ProtoMessageFetchResult`). The protobuf carries the `wss://` URL with signature params baked in (X-MS-STUB, etc.). **NOT JSON** — calling `response.json()` on it will fail.
- **429:** Rate limited. Body is JSON: `{"message": "...", "limit_label": "..."}`. Library throws `SignatureRateLimitError`.
- **Empty payload:** `SignAPIError(ErrorReason.EMPTY_PAYLOAD)`. Usually means "you are being detected as a bot".
- **Other non-200:** `SignAPIError(ErrorReason.SIGN_NOT_200)` with the response payload included.

## Endpoint 2: `POST /webcast/sign_url` — Per-Request Signer for Ad-Hoc HTTP Calls

**Called from:** `EulerApiSdk/api/tik_tok_live/sign_webcast_url.py` (sibling of `fetch_webcast_url.py`)

**Purpose:** Signs an *individual* HTTP/XHR request that TikTok would otherwise reject. Unlike endpoint 1, you don't go through the full WebSocket flow — useful for ad-hoc REST calls to TikTok's webcast API (e.g. `send_room_chat` to post a message, or any other `/webcast/...` endpoint).

**Request:**
- **Method:** `POST`
- **Body (JSON):**
  ```json
  {
    "url": "https://webcast.tiktok.com/webcast/room/chat/?room_id=...&content=...&aid=1988",
    "userAgent": "Mozilla/5.0 ...",
    "method": "GET",  // or POST, DELETE, etc.
    "sessionId": "...",
    "ttTargetIdc": "...",
    "ttwid": "...",
    "payload": "<base64 protobuf payload if method=POST>",
    "type": "fetch",  // or "xhr"
    "includeBrowserParams": true,
    "includeVerifyFp": true
  }
  ```
- **Query params:** `client=ttlive-other`

**Response:**
- **200:** JSON `SignTikTokUrlResponse` with the signed URL or signed request params (signature headers/query strings injected).
- **200 (fallback):** JSON `JSONResponse` if the typed parsing fails.

The library's `TikTokSigner.webcast_sign()` method is a thin wrapper around this endpoint. See `test_signing.py` in the project for a working invocation example.

**Verified paywall (2026-09-02, Community key):** signing an arbitrary `/webcast/chat/` URL now returns `401 {"code":401,"message":"This endpoint requires a Business plan. Purchase one at https://www.eulerstream.com/pricing."}` — ad-hoc signing needs the Business plan ($50/mo, 48h trial). The premium chat proxy `POST /webcast/chat` separately returns `401 ... requires the Webcast Premium add-on` and takes your `sessionid` in `x-cookie-header` (the account cookie leaves your machine). See `references/send-room-chat-feasibility.md`.

## Endpoint 3: `GET /webcast/region_rankings` — On-Demand Leaderboard Poll

**Called from:** `EulerApiSdk/api/tik_tok_live/retrieve_webcast_rankings.py`

**Purpose:** Polls the current leaderboard for a region on demand. Alternative to relying on real-time `GameRankNotifyEvent` / `RankUpdateEvent` pushes over the WebSocket.

**Request:**
- **Method:** `GET`
- **Query params:**
  - `region=<OxyLabsProxyRegion>` (e.g. `US`, `ID`, `JP`, etc. — uses OxyLabs proxy regions, NOT Soax)
  - `rank_type=<RetrieveWebcastRankingsRankType>` (the kind of leaderboard to fetch — exact enum values TBD, check `retrieve_webcast_rankings_rank_type.py`)
  - `session_id=<str>` (optional)
  - `tt_target_idc=<str>` (optional)
- **Headers:**
  - `x-oauth-token=<str>` (optional)
  - `x-cookie-header=<str>` (optional)

**Response:**
- **200:** JSON `WebcastRegionRankingsResponse` with current leaderboard data for the requested region.

**When to use this vs real-time events:**
- Use the real-time events (`GameRankNotifyEvent` etc.) when you want to react instantly to a rank change happening on the streamer's room.
- Use this endpoint when you want a snapshot of the leaderboard at any time (e.g. on a dashboard refresh, or on `!top` command from a viewer).

## Gift Catalog Endpoints (verified 2026-09-02)

Base: `https://tiktok.eulerstream.com`. Headers: `x-api-key` **plus a browser User-Agent** — plain `urllib`/no-UA requests are rejected by Cloudflare with 403 `error code: 1010`. Per docs these routes do not count against rate limits.

| Route | Purpose | Verified behavior |
|---|---|---|
| `GET /webcast/gifts?region=XX&webcast_language=en&redirect=false` | Regional gift panel | 20/20 regions ok; 1,767 unique gifts; recovered Game Controller (US panel only) |
| `GET /webcast/gifts/catalog?page=N&pageSize=100` | Full gift mirror | 2,783 rows over 28 pages; `pageSize` silently clamped to 100 |
| `GET /webcast/gifts/catalog/{gift_id}` | Single gift | Game Controller = 6581/7569 (100 coins, type 2); Super GG 12988 → 404 |
| `GET /webcast/gifts/catalog/search` | Search (docs; not exercised) | — |

Responses are JSON `{"code": 200, "data": {...}}`. Euler rows carry `imageUri`, but Euler's own image host 403s server-side fetches (`Origin not allowed`) — store empty icons rather than hotlinking. Room-panel gifts' icons use TikTok CDN hosts (`p16/p19-webcast.tiktokcdn.com`); retired gifts are absent from the CDN entirely. Project integration lives in `gift_catalog_sync.py` / `gift_catalog.py` — see `references/gift-catalog-union.md`.

## Why Some Events Don't Fire Over the WebSocket

`GameRankNotifyEvent` (gaming rank notification) is the most-requested but most-frequently-missing event. Common reasons:

1. **Platform mismatch** — `WebcastPlatform.WEB` doesn't subscribe to all topics. Try `WebcastPlatform.MOBILE` (requires a real `sessionid` cookie). To switch, set `WebDefaults.tiktok_sign_url` and pass the platform through the client's constructor.

2. **Streamer tier/state** — Some rank events only fire at certain streamer tiers, or only when the live is in a specific state (PK battle, gaming mode, etc.).

3. **Bot account permissions** — The bot account may not be subscribed to the room's rank topics. Real viewers typically are; bots sometimes aren't.

If `rank_events.log` stays empty for an entire stream, the most likely culprit is #1. The next thing to try is switching the platform and seeing if the event appears.

## Quick Diagnostic: Is the Webcast Endpoint Working?

Add a one-time probe at bot startup:

```python
import httpx
async def probe_euler():
    r = await httpx.AsyncClient().get(
        "https://tiktok.eulerstream.com/webcast/fetch",
        params={"client": "ttlive-other", "room_id": "0", "user_agent": "test"},
        headers={"x-api-key": "<YOUR_EULER_KEY>"},
        timeout=10,
    )
    print(f"Euler status: {r.status_code}, content-type: {r.headers.get('content-type')}")
```

A 200 with `content-type: application/octet-stream` is the "working" response. A 401 means your key is bad. A 429 means rate limited. A 5xx means Euler is down.
