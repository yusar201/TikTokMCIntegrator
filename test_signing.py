"""Debug: test with EXPLICIT sign_api_key parameter"""
import asyncio, sys, yaml, os
sys.path.insert(0, "/home/yusar/.hermes/hermes-agent/venv/lib/python3.11/site-packages")

with open("/mnt/d/Ikhito/Code/TikTokMCIntegrator/profiles/Survival.yml") as f:
    cfg = yaml.safe_load(f)
API_KEY = cfg.get("Settings", {}).get("EulerApiKey", "")

# Also set env var (signer reads os.environ FIRST)
os.environ["SIGN_API_KEY"] = API_KEY

from TikTokLive.client.web.web_settings import WebDefaults
from TikTokLive.client.web.web_signer import TikTokSigner

# Set BOTH
WebDefaults.tiktok_sign_api_key = API_KEY

print(f"API Key: {API_KEY[:12]}...")
print(f"WebDefaults: {WebDefaults.tiktok_sign_api_key[:12] if WebDefaults.tiktok_sign_api_key else 'None'}...")
print(f"Env: {os.environ.get('SIGN_API_KEY', 'None')[:12]}...")

async def test(url, method, sign_type, desc):
    signer = TikTokSigner(sign_api_key=API_KEY)  # EXPLICIT
    try:
        result = await signer.webcast_sign(
            url=url, method=method, sign_url_type=sign_type,
            payload="", user_agent="Mozilla/5.0",
            session_id=None,
        )
        print(f"✅ {desc}")
        return True
    except Exception as e:
        print(f"❌ {desc}: {type(e).__name__}: {str(e)[:200]}")
        return False

async def main():
    await test(
        "https://webcast.tiktok.com/webcast/room/info/?room_id=7642951083745676033&aid=1988",
        "GET", "fetch", "room/info (GET)"
    )
    await test(
        "https://webcast.tiktok.com/webcast/room/chat/?room_id=7642951083745676033&content=test&aid=1988&live_id=12",
        "POST", "fetch", "room/chat (POST)"
    )

asyncio.run(main())
