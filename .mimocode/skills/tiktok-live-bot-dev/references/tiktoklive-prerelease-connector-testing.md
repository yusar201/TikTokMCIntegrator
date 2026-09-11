# TikTokLive prerelease connector testing

Use this when TikTokLive starts failing with WebSocket/app-id/connect errors and the next step is to verify whether a prerelease fixes it.

## Key lesson

Do not assume the newest prerelease fixes a TikTok-side protocol break. Test it in an isolated venv against a currently live username before touching project deps or release builds.

## Reproduction pattern

```bash
TMPDIR=$(mktemp -d)
python3 -m venv "$TMPDIR/venv"
. "$TMPDIR/venv/bin/activate"
python -m pip install -q --upgrade pip
python -m pip install -q 'TikTokLive==<version>'
python - <<'PY'
import asyncio, traceback, importlib.metadata as m
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, GiftEvent
import TikTokLive.__version__ as v

username='@example_live_user'
print('TikTokLive', getattr(v, 'PACKAGE_VERSION', 'unknown'))
try:
    print('EulerApiSdk', m.version('EulerApiSdk'))
except Exception:
    pass

client = TikTokLiveClient(unique_id=username)
connected = asyncio.Event()

@client.on(ConnectEvent)
async def on_connect(event):
    print('CONNECT_OK', getattr(event, 'room_id', None))
    connected.set()

@client.on(CommentEvent)
async def on_comment(event):
    print('COMMENT_OK', getattr(getattr(event, 'user', None), 'unique_id', None), getattr(event, 'comment', None))

@client.on(GiftEvent)
async def on_gift(event):
    print('GIFT_OK', getattr(getattr(event, 'user', None), 'unique_id', None), getattr(getattr(event, 'gift', None), 'name', None))

async def main():
    try:
        ws_task = await client.start(fetch_room_info=False, fetch_gift_info=False, fetch_live_check=True)
        print('START_RETURNED', ws_task)
        done, pending = await asyncio.wait({ws_task, asyncio.create_task(connected.wait())}, timeout=45, return_when=asyncio.FIRST_COMPLETED)
        if connected.is_set():
            print('RESULT: connected; listening 10s')
            await asyncio.sleep(10)
        elif ws_task.done():
            print('RESULT: ws task ended early')
            try:
                print('WS_RESULT', ws_task.result())
            except Exception as e:
                print('WS_EXCEPTION', type(e).__name__, str(e))
                traceback.print_exc()
        else:
            print('RESULT: timeout; ws_task still pending')
    except Exception as e:
        print('START_EXCEPTION', type(e).__name__, str(e))
        traceback.print_exc()
    finally:
        try:
            await client.disconnect()
        except Exception as e:
            print('DISCONNECT_ERROR', type(e).__name__, str(e))

asyncio.run(main())
PY
rm -rf "$TMPDIR"
```

## Pitfalls

- `client.start()` in TikTokLive v7 returns a task; `await client.start()` alone does not mean the WebSocket connected. Wait on the returned task and a `ConnectEvent`.
- Check PyPI JSON/metadata instead of relying on memory for latest prerelease names.
- If installing TikTokLive `7.0.0b1` pulls a newer incompatible EulerApiSdk, import can fail before connection testing. In the observed case, `EulerApiSdk==0.3.1` lacked `sign_webcast_url`; pinning `EulerApiSdk==0.1.0` allowed import and a real connector test.
- If the test still raises `WebcastBlocked200Error ... illegal app_id`, treat it as a TikTok/upstream protocol break, not a local app/RCON/overlay issue. Do not deploy that prerelease just because it is newer.

## Reporting pattern

Report the actual version combo, username tested, and exact terminal result. Keep recommendation direct: whether to deploy, wait for upstream, or add fallback/reconnect degradation.