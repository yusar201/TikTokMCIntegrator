"""Test: sign with client=ttlive-node + POST with session cookie"""
import asyncio, yaml, httpx, os
from urllib.parse import urlencode

with open("/mnt/d/Ikhito/Code/TikTokMCIntegrator/profiles/Survival.yml") as f:
    cfg = yaml.safe_load(f)
API_KEY = cfg.get("Settings", {}).get("EulerApiKey", "")

SESSION_ID = "d98e394aa697cc69af66e746e2da4cec"
ROOM_ID = "7642951083745676033"
MESSAGE = "🤖 test from hermès"

async def main():
    # Step 1: Sign URL with ttlive-node client (PROVEN to work)
    sign_url = "https://tiktok.eulerstream.com/webcast/sign_url"
    target_url = f"https://webcast.tiktok.com/webcast/room/chat/?room_id={ROOM_ID}&content=test&aid=1988&live_id=12"
    
    async with httpx.AsyncClient() as http:
        sign_resp = await http.get(sign_url, params={
            "url": target_url,
            "client": "ttlive-node",
        }, headers={"Authorization": f"Bearer {API_KEY}"})
        
        sign_data = sign_resp.json()
        print(f"Sign: code={sign_data.get('code')}, msg={sign_data.get('message','')[:100]}")
        
        if sign_data.get("code") != 200:
            print(f"❌ Sign failed: {sign_data}")
            return
        
        # The deprecated sign_url endpoint redirects to fetch/
        # But we don't need the redirected URL — we need to POST directly
        # with the signed params
        
        # Step 2: POST with session cookie (no signing needed for POST according to Node.js lib)
        params = {
            "aid": "1988", "app_language": "en-US", "app_name": "tiktok_web",
            "browser_language": "en", "browser_name": "Mozilla",
            "browser_online": "true", "browser_platform": "Win32",
            "browser_version": "5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "content": MESSAGE,
            "cookie_enabled": "true", "device_platform": "web",
            "focus_state": "true", "from_page": "user", "history_len": "0",
            "is_fullscreen": "false", "is_page_visible": "true",
            "live_id": "12", "room_id": ROOM_ID,
            "tz_name": "Asia/Jakarta", "webcast_sdk_version": "1.3.0",
        }
        
        cookies = {"sessionid": SESSION_ID, "sessionid_ss": SESSION_ID, "sid_tt": SESSION_ID}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.tiktok.com/",
            "Origin": "https://www.tiktok.com",
        }
        
        # Try POST — Node.js lib sends POST without signing
        resp = await http.post(
            "https://webcast.tiktok.com/webcast/room/chat/",
            params=params,
            cookies=cookies,
            headers=headers,
        )
        print(f"POST HTTP {resp.status_code}: {resp.text[:300]}")
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status_code") == 0:
                print("\n✅✅✅ CHAT MESSAGE SENT!")
            elif data.get("status_code") == 20003:
                print("\n❌ Session expired")
            else:
                print(f"\n❌ code={data.get('status_code')}")

asyncio.run(main())
