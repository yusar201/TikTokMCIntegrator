"""Shared helper for the Python/JS parity tests.

The parity suites run a JS module through Node and compare its output to the
Python implementation. Two platform details bite here, and both are handled once
in this module rather than in each suite:

1. **ESM module paths.** Node's ESM loader accepts only ``file:``, ``data:`` and
   ``node:`` URLs, so a bare Windows path like ``D:\\repo\\static\\x.js`` fails
   with ``ERR_UNSUPPORTED_ESM_URL_SCHEME`` even though the identical bare POSIX
   path works. ``Path.as_uri()`` is correct on both.

2. **Command-line length.** Windows caps a command line at ~32k characters, so a
   large fixture payload inlined via ``node -e`` fails with
   ``[WinError 206] The filename or extension is too long``. Payloads are
   therefore written to a temp JSON file that the snippet reads.

This repo is exercised with both the WSL and the Windows interpreter, so neither
issue can be assumed away.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

NODE = shutil.which("node") or ""


def module_url(path: Path) -> str:
    """ESM-importable URL for a local JS module (works on Windows and POSIX)."""
    return path.resolve().as_uri()


def run_node_module_script(body: str, cwd: Path, timeout: int = 180):
    """Run an ES-module snippet in Node and parse its stdout as JSON."""
    if not NODE:
        raise RuntimeError("node is not installed")
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", body],
        cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def run_node_with_payload(body_template: str, payload, cwd: Path, module_path: Path,
                          timeout: int = 180):
    """Run an ES-module snippet that reads a large fixture from a temp file.

    ``body_template`` is formatted with ``module`` (an ESM URL) and ``payload``
    (a JS expression that evaluates to the parsed fixture). Keeping the fixture
    out of the command line avoids the Windows length limit.
    """
    if not NODE:
        raise RuntimeError("node is not installed")

    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    )
    try:
        json.dump(payload, handle)
        handle.close()
        payload_url = Path(handle.name).resolve().as_uri()
        body = body_template % {
            # json.dumps gives a valid JS string literal for both substitutions,
            # so the template writes `from %(module)s` with no quotes of its own.
            "module": json.dumps(module_url(module_path)),
            "payload": (
                "JSON.parse(await (await import('node:fs/promises'))"
                f".readFile(new URL({json.dumps(payload_url)}), 'utf-8'))"
            ),
        }
        result = subprocess.run(
            [NODE, "--input-type=module", "-e", body],
            cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
