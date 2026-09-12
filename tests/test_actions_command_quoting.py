import asyncio

import actions


def test_minecraft_template_exposes_safe_quoted_values():
    sent = []

    async def send(command):
        sent.append(command)

    asyncio.run(actions.execute_actions(
        [{"type": "minecraft", "command": "spawn {mc} minecraft:zombie 2 {user_q}"}],
        {"mc": "Ikhito17", "user": 'Saucy Soup 🔥 "VIP"'},
        send,
    ))

    assert sent == ['spawn Ikhito17 minecraft:zombie 2 "Saucy Soup 🔥 \\"VIP\\""']


def test_quoted_values_neutralize_command_line_breaks():
    sent = []

    async def send(command):
        sent.append(command)

    asyncio.run(actions.execute_actions(
        [{"type": "minecraft", "command": "titlecustom {user_q} {mc} Hello"}],
        {"mc": "Ikhito17", "user": "viewer\nkill @e"},
        send,
    ))

    assert sent == ['titlecustom "viewer kill @e" Ikhito17 Hello']


def test_plain_placeholders_remain_backward_compatible():
    sent = []

    async def send(command):
        sent.append(command)

    asyncio.run(actions.execute_actions(
        [{"type": "minecraft", "command": "give {mc} minecraft:stone {amount}"}],
        {"mc": "Ikhito17", "amount": "3"},
        send,
    ))

    assert sent == ["give Ikhito17 minecraft:stone 3"]
