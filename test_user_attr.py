import asyncio
from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent
import sys

client = TikTokLiveClient(unique_id="@crainer")

@client.on(CommentEvent)
async def on_comment(event: CommentEvent):
    u = event.user
    print(f"User: {u.nick_name}")
    print(f"is_follower: {getattr(u, 'is_follower', 'Not Found')}")
    print(f"follow_info: {getattr(u, 'follow_info', 'Not Found')}")
    print(f"is_subscribe: {getattr(u, 'is_subscribe', 'Not Found')}")
    print(f"fans_club: {getattr(u, 'fans_club', 'Not Found')}")
    print(f"fans_club_info: {getattr(u, 'fans_club_info', 'Not Found')}")
    print(f"is_subscriber: {getattr(u, 'is_subscriber', 'Not Found')}")
    sys.exit(0)

if __name__ == '__main__':
    client.run()
