"""Gift Card Studio — zero-idle-cost contract (Phase 0 guardrails).

The Studio is a heavy editor living inside a process that also dispatches
Minecraft commands during a live stream. These tests encode the plan's hard
performance requirement: **an unopened Studio costs nothing**.

They are deliberately structural (source + import assertions) rather than
wall-clock benchmarks, so they are deterministic on Khito's machine and can't
go flaky mid-stream. Runtime CPU/RAM comparison against the Phase 0 baseline is
a separate live-verification step in Phase 11.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDIO_PKG = ROOT / "gift_card_studio"
SCRIPT_JS = ROOT / "static" / "script.js"
INDEX_HTML = ROOT / "templates" / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Import cost
# ---------------------------------------------------------------------------

class TestImportIsCheap:

    def test_importing_the_package_starts_no_thread_timer_or_subprocess(self):
        """A fresh interpreter importing the package must add no live threads."""
        code = (
            "import threading, sys; "
            "before = threading.active_count(); "
            "import gift_card_studio; "
            "after = threading.active_count(); "
            "print(before, after)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=120
        )

        assert result.returncode == 0, result.stderr
        before, after = (int(n) for n in result.stdout.split())
        assert after == before

    def test_importing_the_package_does_not_pull_in_the_export_stack(self):
        """Pillow/rasterizers stay unimported until an export actually runs."""
        code = (
            "import sys; "
            "import gift_card_studio; "
            "leaked = [m for m in ('PIL', 'PIL.Image', 'cairosvg', 'flask') if m in sys.modules]; "
            "print(','.join(leaked))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=120
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == ""

    def test_importing_the_job_registry_starts_no_worker(self):
        """Generate jobs spawn threads on demand, never at import.

        The registry is the one module here that legitimately creates threads,
        so it gets its own assertion rather than relying on the package-level
        check above.
        """
        code = (
            "import threading; "
            "before = threading.active_count(); "
            "from gift_card_studio import jobs; "
            "after = threading.active_count(); "
            "print(before, after, len(jobs.list_jobs()), jobs.active_count())"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=120
        )

        assert result.returncode == 0, result.stderr
        before, after, job_count, active = (int(n) for n in result.stdout.split())
        assert after == before
        assert job_count == 0
        assert active == 0

    def test_importing_generate_does_not_pull_in_the_image_stack(self):
        """The Generate module is validation + orchestration only."""
        code = (
            "import sys; "
            "from gift_card_studio import generate, jobs; "
            "leaked = [m for m in ('PIL', 'PIL.Image', 'resvg_py') if m in sys.modules]; "
            "print(','.join(leaked))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=120
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == ""

    def test_importing_the_package_creates_no_directories(self, tmp_path):
        """ensure_dirs is explicit; import must not touch the filesystem."""
        code = (
            "import os, sys; "
            "sys.argv = ['x']; "
            "import gift_card_studio, gift_card_studio.storage as s; "
            f"print(os.path.exists(s.studio_root({str(tmp_path)!r})))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=120
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False"


# ---------------------------------------------------------------------------
# Source-level guardrails
# ---------------------------------------------------------------------------

class TestNoAmbientWork:

    def _python_sources(self):
        return sorted(STUDIO_PKG.glob("*.py"))

    def test_no_module_level_thread_timer_or_scheduler_start(self):
        forbidden = (
            "threading.Thread(",
            "threading.Timer(",
            "sched.scheduler(",
            "subprocess.Popen(",
            "asyncio.get_event_loop()",
        )
        offenders = []
        for path in self._python_sources():
            source = _read(path)
            for line in source.splitlines():
                stripped = line.strip()
                # Module level == no leading indentation. Inside a function is
                # fine (the export worker legitimately spawns a process).
                if line and not line[0].isspace() and any(f in stripped for f in forbidden):
                    offenders.append(f"{path.name}: {stripped}")

        assert offenders == []

    def test_pure_modules_do_not_import_pillow_at_module_scope(self):
        for name in ("models.py", "grid.py", "validation.py", "storage.py"):
            source = _read(STUDIO_PKG / name)
            assert "from PIL" not in source
            assert "import PIL" not in source

    def test_no_network_calls_in_the_pure_engine(self):
        """The catalog reads local config/cache; it never fetches at render time."""
        for name in ("models.py", "grid.py", "validation.py", "storage.py"):
            source = _read(STUDIO_PKG / name)
            assert "requests." not in source
            assert "urlopen" not in source
