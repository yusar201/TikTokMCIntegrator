import asyncio
from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent
import sys

client = TikTokLiveClient(unique_id="@tiktok")

@client.on(CommentEvent)
async def on_comment(event: CommentEvent):
    u = event.user
    follow_info = getattr(u, 'follow_info', None)
    follow_status = getattr(follow_info, 'follow_status', None) if follow_info else None
    print(f"User: {u.nick_name}")
    print(f"is_follower: {getattr(u, 'is_follower', 'Not Found')}")
    print(f"follow_status: {follow_status}")
    print(f"is_friend: {getattr(u, 'is_friend', 'Not Found')}")
    sys.exit(0)

if __name__ == '__main__':
    client.run()
