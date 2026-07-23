import asyncio
import time

from actions import execute_actions


def test_minecraft_actions_start_concurrently():
    starts = []

    async def send(command):
        starts.append((command, time.perf_counter()))
        await asyncio.sleep(0.08)

    actions = [
        {"type": "minecraft", "command": "first"},
        {"type": "minecraft", "command": "second"},
        {"type": "minecraft", "command": "third"},
    ]

    started = time.perf_counter()
    asyncio.run(execute_actions(actions, send_mc_command=send))
    elapsed = time.perf_counter() - started

    assert [command for command, _ in starts] == ["first", "second", "third"]
    assert max(timestamp for _, timestamp in starts) - min(timestamp for _, timestamp in starts) < 0.04
    assert elapsed < 0.16
