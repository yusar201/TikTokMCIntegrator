import ast
from pathlib import Path


APP_PATH = Path(__file__).with_name("app.py")


def _warmup_probe_text():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "start_tts_warmup_once":
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                func = child.func
                if not (isinstance(func, ast.Attribute) and func.attr == "Communicate"):
                    continue
                if child.args and isinstance(child.args[0], ast.Constant):
                    return child.args[0].value
    raise AssertionError("TTS warmup edge_tts.Communicate call not found")


def test_tts_warmup_uses_speakable_probe_text():
    probe = _warmup_probe_text()
    assert isinstance(probe, str)
    assert any(ch.isalnum() for ch in probe), (
        "Warmup must send speakable text; punctuation-only input produces "
        "NoAudioReceived and leaves the first viewer request cold"
    )
