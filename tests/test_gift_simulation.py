import asyncio

import gift_simulation
import actions


def _config():
    return {
        "Settings": {
            "MinecraftUsername": "KhitoMC",
            "ConnectorType": "rcon",
        },
        "Gifts": {
            "GlobalActions": [
                {"type": "minecraft", "command": "global {gift_name} {repeat_count} {user} {total_coin} {mc}"},
            ],
            "5655": [
                {"type": "minecraft", "command": "give {mc} diamond {amount}"},
                {"type": "sound", "file": "sound-{user}.mp3"},
                {"type": "random", "actions": [
                    {"type": "minecraft", "command": "random {user} {amount}"},
                ]},
            ],
        },
        "GiftNames": {"5655": "Rose"},
    }


def test_simulate_gift_runs_global_and_specific_actions_with_context(monkeypatch):
    captured = []

    async def fake_execute(actions, context, send_mc_command):
        captured.append((actions, dict(context)))

    monkeypatch.setattr(gift_simulation, "execute_actions", fake_execute)

    result = asyncio.run(gift_simulation.simulate_gift(
        _config(),
        gift_key="5655",
        user="TestViewer",
        amount=3,
        gift_meta={"name": "Rose", "diamond_count": 1},
        send_mc_command=lambda command: None,
    ))

    assert [batch[0] for batch in captured] == [
        _config()["Gifts"]["GlobalActions"],
        _config()["Gifts"]["5655"],
    ]
    assert captured[0][1] == captured[1][1] == {
        "gift_name": "Rose",
        "repeat_count": "3",
        "user": "TestViewer",
        "total_coin": "3",
        "mc": "KhitoMC",
        "amount": "3",
        "gift_id": "5655",
        "asset_url": "",
    }
    assert result["actions"] == 4
    assert result["batches"] == 2


def test_simulate_gift_reports_roulette_skip_instead_of_claiming_it_ran(monkeypatch):
    """A roulette action needs the live bot, so the simulator must say so.

    Regression guard for the Hermes/MiMo seam: when Roulette became a general
    action type, the simulator kept calling the raw dispatcher with no spinner,
    so a gift containing `{"type": "roulette"}` silently no-oped while the
    result still counted it as an executed action.
    """
    captured = []

    async def fake_execute(actions, context, send_mc_command):
        captured.append(actions)

    monkeypatch.setattr(gift_simulation, "execute_actions", fake_execute)

    config = _config()
    config["Gifts"]["5655"] = [
        {"type": "minecraft", "command": "give {mc} diamond {amount}"},
        {"type": "roulette"},
    ]

    result = asyncio.run(gift_simulation.simulate_gift(
        config, "5655", "TestViewer", 1,
        {"name": "Rose", "diamond_count": 1}, lambda command: None,
    ))

    assert result["skipped_actions"] == ["roulette"]
    assert "Roulette" in result["note"]
    assert result["actions"] == 3  # global (1) + gift-specific (2), for the record
    assert captured  # the executable actions still ran


def test_simulate_gift_has_no_skip_note_without_roulette(monkeypatch):
    async def fake_execute(actions, context, send_mc_command):
        return None

    monkeypatch.setattr(gift_simulation, "execute_actions", fake_execute)

    result = asyncio.run(gift_simulation.simulate_gift(
        _config(), "5655", "TestViewer", 1,
        {"name": "Rose", "diamond_count": 1}, lambda command: None,
    ))

    assert "skipped_actions" not in result
    assert "note" not in result


def test_simulate_gift_rejects_invalid_payloads():
    config = _config()
    for key, user, amount, message in [
        ("missing", "Viewer", 1, "not configured"),
        ("GlobalActions", "Viewer", 1, "not a gift"),
        ("5655", "", 1, "user"),
        ("5655", "Viewer", 0, "amount"),
        ("5655", "Viewer", 10001, "amount"),
    ]:
        try:
            asyncio.run(gift_simulation.simulate_gift(config, key, user, amount))
        except ValueError as exc:
            assert message in str(exc).lower()
        else:
            raise AssertionError(f"Expected ValueError for {key!r}, {user!r}, {amount!r}")


def test_real_dispatcher_exercises_minecraft_sound_and_random(monkeypatch):
    sent = []
    sounds = []

    async def send(command):
        sent.append(command)

    monkeypatch.setattr(actions, "_play_sound", lambda **kwargs: sounds.append(kwargs))
    monkeypatch.setattr(actions._random, "choice", lambda choices: choices[0])
    config = _config()

    result = asyncio.run(gift_simulation.simulate_gift(
        config, "5655", "TestViewer", 3,
        {"name": "Rose", "diamond_count": 1}, send,
    ))

    # execute_actions starts independent actions concurrently, so compare sets.
    assert set(sent) == {
        "global Rose 3 TestViewer 3 KhitoMC",
        "give KhitoMC diamond 3",
        "random TestViewer 3",
    }
    assert sounds == [{"file_path": "sound-TestViewer.mp3", "url": None, "volume": 0.8}]
    assert result["actions"] == 4


def test_flask_gift_simulation_endpoint(monkeypatch):
    import app as app_module

    seen = {}

    async def fake_simulate(config, gift_key, user, amount, gift_meta=None, send_mc_command=None):
        seen.update({
            "gift_key": gift_key,
            "user": user,
            "amount": amount,
            "gift_meta": gift_meta,
            "mc": config["Settings"]["MinecraftUsername"],
        })
        return {"status": "success", "gift": "Rose", "actions": 3, "batches": 2}

    monkeypatch.setattr(app_module, "load_config", _config)
    monkeypatch.setattr(app_module, "simulate_gift", fake_simulate)
    monkeypatch.setattr(app_module.gift_catalog, "load_catalog", lambda path: [
        {"id": 5655, "name": "Rose", "diamond_count": 1},
    ])

    client = app_module.app.test_client()
    response = client.post("/api/gifts/simulate", json={
        "gift_key": "5655", "user": "TestViewer", "amount": 3,
    })

    assert response.status_code == 200
    assert response.get_json()["actions"] == 3
    assert seen == {
        "gift_key": "5655",
        "user": "TestViewer",
        "amount": 3,
        "gift_meta": {"id": 5655, "name": "Rose", "diamond_count": 1},
        "mc": "KhitoMC",
    }


def test_gift_simulation_frontend_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    html = (root / "templates" / "index.html").read_text(encoding="utf-8")
    js = (root / "static" / "script.js").read_text(encoding="utf-8")

    panel = html[html.index('id="panel-gifts"'):html.index('id="panel-gift-studio"')]
    assert 'id="gift-sim-select"' in panel
    assert 'id="gift-sim-picker-button"' in panel
    assert 'id="gift-sim-picker-list"' in panel
    assert 'id="gift-sim-user"' in panel
    assert 'id="gift-sim-amount"' in panel
    assert 'id="btn-simulate-gift"' in panel
    assert "'/api/gifts/simulate'" in js or '"/api/gifts/simulate"' in js
    assert 'giftIconMap[key]' in js
    assert 'class="gift-sim-picker-option"' in js
    css = (root / "static" / "style.css").read_text(encoding="utf-8")
    assert "#panel-gifts > .form-card.gift-simulator" in css
    assert "overflow: visible" in css
