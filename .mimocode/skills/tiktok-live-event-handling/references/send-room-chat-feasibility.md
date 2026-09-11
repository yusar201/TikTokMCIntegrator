# Sending Chat — Feasibility, Paywalls, and Credential Safety (verified 2026-09-02)

## The hard gate in TikTokLive

`client.web.send_room_chat()` (`client/web/routes/send_room_chat.py`) calls `check_authenticated_session(..., session_required=True)` — **a real `sessionid` cookie is mandatory**; there is no anonymous path.

The route does NOT call TikTok directly. It proxies **EulerApiSdk's premium route**: `POST https://tiktok.eulerstream.com/webcast/chat` with body `{content, targetRoomId | targetUniqueId}` and header `x-cookie-header: sessionid=...; tt-target-idc=...`. The real TikTok endpoint it forwards to is `POST https://webcast.tiktok.com/webcast/chat/` (JSON body, not query params).

## Where the actual lock is

The endpoint is public knowledge; the lock is TikTok's **rotating request-signature tokens** (`msToken`, `X-Bogus`, `X-Gnarly`). `web_signer.py` strips all three before signing — the presence of `X-Gnarly` there (TikTokLive 7.0.0b2) is evidence of the newest signature layer. Whoever can sign, can chat; Euler's product is exactly that signer.

## Verified paywalls (Community key, live requests — not docs)

| Request | Result |
|---|---|
| `POST tiktok.eulerstream.com/webcast/sign_url` (generic signer) | `401` — "This endpoint requires a Business plan. Purchase one at https://www.eulerstream.com/pricing." |
| `POST tiktok.eulerstream.com/webcast/chat` (premium chat proxy) | `401` — "This endpoint requires the Webcast Premium add-on." |

Euler pricing (their pricing page): Community $0 (2,500 req/day); **Business $50/mo, 48-hour free trial** (10,000 req/day) unlocks `/webcast/sign_url`; **Send room chat** is listed only under the Webcast Premium add-on column.

## Credential safety

- **The paid path ships your `sessionid` to Euler** (`x-cookie-header`) — the account cookie is held server-side by Euler while they proxy the send.
- TikTokLive refuses to forward a session ID to a sign host unless `WHITELIST_AUTHENTICATED_SESSION_ID_HOST` is set. Nothing in the project sets a session ID today — keep it that way unless Khito explicitly opts in.
- Chat automation is against TikTok ToS regardless of path: use a **dedicated bot account**, never the main.
- **Measured fact (dummy session, 2026-09-02):** a session ID does NOT widen the gift catalog — `fetch_gift_list` is unsigned; anonymous vs `user_is_login=true` returned identical panels (701/703 gifts). Session ID's only documented uses: age-restricted rooms, `send_room_chat`, MOBILE platform connect.

## Options if Khito wants chat-send

1. **Euler Business trial → wire `send_room_chat`.** Fastest, an afternoon of work; cookie leaves the machine.
2. **Local Node signer** running TikTok's own signing JS. Free; cookie stays local; but an arms race — X-Bogus is publicly solved, X-Gnarly is the current wall, and it breaks when TikTok rotates the algorithm.
3. **Browser automation (Playwright, logged-in bot account).** The real browser generates valid signatures natively → robust to algorithm changes; ~300–500 MB RAM during stream; cookie stays in the local profile.

**Ask the use case first:** if it's announcements (gifts/welcomes), overlays may already cover it without any chat-send infrastructure.

## Communication pitfall (Khito correction, 2026-09-02)

When reporting auth experiments, **always state explicitly whether a real user credential or a dummy was used** — e.g. "a dummy string of 32 zeros passed to `set_session`". Writing "with a session ID set" read as if the user's real credential had been in play, and he called it out ("i never sent u my session id").
