import asyncio
from TikTokLive import TikTokLiveClient
from TikTokLive.events import BarrageEvent
import sys

client = TikTokLiveClient(unique_id="@crainer")

@client.on(BarrageEvent)
async def on_barrage(event: BarrageEvent):
    print("Barrage event received!")
    try:
        print(event.to_dict())
    except Exception as e:
        print(f"Error printing dict: {e}")
    sys.exit(0)

if __name__ == '__main__':
    client.run()
