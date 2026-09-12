"""Generate job lifecycle: threading, cancellation, sweeping, idle cost.

The Studio's Generate button hands work to a background thread so a 300-frame
GIF cannot hold a Flask worker or compete with gift->command dispatch during a
live stream. These tests pin the parts that are easy to get subtly wrong:
the single-slot concurrency guard, cancellation actually stopping work,
artifacts being cleaned up, and the module costing nothing at idle.
"""

import os
import threading
import time

import pytest

from gift_card_studio import jobs, storage


@pytest.fixture
def data_dir(tmp_path):
    root = tmp_path / "data"
    storage.ensure_dirs(str(root))
    return str(root)


@pytest.fixture(autouse=True)
def clean_registry():
    jobs.reset_for_tests()
    yield
    jobs.reset_for_tests()


def _wait_for(predicate, timeout=5.0):
    """Poll until true. Threads make sleeps unavoidable; keep them bounded."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _write_artifact(context, name="out.png", body=b"x" * 32):
    path = os.path.join(context.output_dir, name)
    with open(path, "wb") as handle:
        handle.write(body)
    return path


class TestIdleCost:

    def test_importing_jobs_starts_no_threads(self):
        """Hard requirement: nothing in the Studio runs when it is closed."""
        before = threading.active_count()

        import importlib
        importlib.reload(jobs)

        assert threading.active_count() == before

    def test_the_registry_is_empty_until_a_generate(self):
        assert jobs.list_jobs() == []
        assert jobs.active_count() == 0

    def test_a_finished_job_leaves_no_live_thread(self, data_dir):
        def work(context):
            return _write_artifact(context), {}

        job = jobs.submit("png", "p1", work, data_dir)
        assert _wait_for(lambda: jobs.get_job(job["id"], data_dir)["status"] == jobs.STATUS_DONE)

        # The worker thread must have exited, not be parked waiting for more.
        assert not any(
            thread.name.startswith("gift-studio-") and thread.is_alive()
            for thread in threading.enumerate()
        )


class TestSuccessPath:

    def test_a_job_runs_and_reports_done(self, data_dir):
        def work(context):
            context.progress(3, 3)
            return _write_artifact(context), {"ok": True}

        job = jobs.submit("png", "p1", work, data_dir)
        assert _wait_for(lambda: jobs.get_job(job["id"], data_dir)["status"] == jobs.STATUS_DONE)

        final = jobs.get_job(job["id"], data_dir)
        assert final["progress"] == 3
        assert final["percent"] == 100.0
        assert final["report"] == {"ok": True}

    def test_the_artifact_is_downloadable_and_real(self, data_dir):
        def work(context):
            return _write_artifact(context, "board.gif", b"GIF89a" + b"\0" * 20), {}

        job = jobs.submit("gif", "p1", work, data_dir)
        assert _wait_for(lambda: jobs.get_job(job["id"], data_dir)["status"] == jobs.STATUS_DONE)

        path = jobs.artifact_path(job["id"])
        assert path and os.path.isfile(path)
        assert jobs.get_job(job["id"], data_dir)["download_name"] == "board.gif"
        assert jobs.get_job(job["id"], data_dir)["bytes"] == os.path.getsize(path)

    def test_progress_percentages_are_reported_mid_run(self, data_dir):
        gate = threading.Event()
        seen = []

        def work(context):
            context.progress(1, 4)
            gate.wait(5)
            return _write_artifact(context), {}

        job = jobs.submit("gif", "p1", work, data_dir)
        assert _wait_for(lambda: jobs.get_job(job["id"], data_dir)["progress"] == 1)
        seen.append(jobs.get_job(job["id"], data_dir)["percent"])
        gate.set()

        assert seen == [25.0]

    def test_each_job_gets_its_own_output_directory(self, data_dir):
        seen = []

        def work(context):
            seen.append(context.output_dir)
            return _write_artifact(context), {}

        first = jobs.submit("png", "p1", work, data_dir)
        assert _wait_for(lambda: jobs.get_job(first["id"], data_dir)["status"] == jobs.STATUS_DONE)
        second = jobs.submit("png", "p1", work, data_dir)
        assert _wait_for(lambda: jobs.get_job(second["id"], data_dir)["status"] == jobs.STATUS_DONE)

        assert seen[0] != seen[1]


class TestConcurrencyGuard:

    def test_a_second_generate_is_refused_while_one_runs(self, data_dir):
        """Parallel rasterization on a streaming PC is the wrong trade."""
        gate = threading.Event()

        def work(context):
            gate.wait(5)
            return _write_artifact(context), {}

        jobs.submit("gif", "p1", work, data_dir)
        assert _wait_for(lambda: jobs.active_count() == 1)

        with pytest.raises(jobs.JobBusy):
            jobs.submit("gif", "p1", work, data_dir)

        gate.set()

    def test_the_slot_frees_up_after_completion(self, data_dir):
        def work(context):
            return _write_artifact(context), {}

        first = jobs.submit("png", "p1", work, data_dir)
        assert _wait_for(lambda: jobs.get_job(first["id"], data_dir)["status"] == jobs.STATUS_DONE)

        second = jobs.submit("png", "p1", work, data_dir)
        assert second["id"] != first["id"]

    def test_the_slot_frees_up_after_a_failure(self, data_dir):
        def failing(context):
            raise RuntimeError("boom")

        first = jobs.submit("png", "p1", failing, data_dir)
        assert _wait_for(lambda: jobs.get_job(first["id"], data_dir)["status"] == jobs.STATUS_ERROR)

        def work(context):
            return _write_artifact(context), {}

        assert jobs.submit("png", "p1", work, data_dir)["id"] != first["id"]


class TestCancellation:

    def test_a_worker_raising_its_own_cancel_type_is_still_cancelled(self, data_dir):
        """The exporter raises ExportCancelled, not JobCancelled.

        Regression: the registry originally keyed cancellation off the exception
        type, so a real cancelled GIF export was reported to the user as
        `ExportCancelled: export cancelled` under status=error. The cancel flag
        is the authority, not the exception class.
        """
        started = threading.Event()

        class ExporterStyleCancel(RuntimeError):
            pass

        def work(context):
            started.set()
            for _ in range(500):
                if context.cancelled():
                    raise ExporterStyleCancel("export cancelled")
                time.sleep(0.01)
            return _write_artifact(context), {}

        job = jobs.submit("gif", "p1", work, data_dir)
        assert started.wait(5)
        jobs.cancel_job(job["id"])
        assert _wait_for(
            lambda: jobs.get_job(job["id"], data_dir)["status"] in jobs.TERMINAL_STATUSES
        )

        final = jobs.get_job(job["id"], data_dir)
        assert final["status"] == jobs.STATUS_CANCELLED
        assert "ExporterStyleCancel" not in final["message"]

    def test_a_running_job_can_be_cancelled(self, data_dir):
        started = threading.Event()

        def work(context):
            started.set()
            for _ in range(500):
                context.check_cancelled()
                time.sleep(0.01)
            return _write_artifact(context), {}

        job = jobs.submit("gif", "p1", work, data_dir)
        assert started.wait(5)

        assert jobs.cancel_job(job["id"]) is True
        assert _wait_for(
            lambda: jobs.get_job(job["id"], data_dir)["status"] == jobs.STATUS_CANCELLED
        )

    def test_cancelling_removes_the_partial_artifact(self, data_dir):
        started = threading.Event()
        captured = {}

        def work(context):
            captured["dir"] = context.output_dir
            _write_artifact(context, "partial.gif")
            started.set()
            for _ in range(500):
                context.check_cancelled()
                time.sleep(0.01)
            return _write_artifact(context), {}

        job = jobs.submit("gif", "p1", work, data_dir)
        assert started.wait(5)
        jobs.cancel_job(job["id"])
        assert _wait_for(
            lambda: jobs.get_job(job["id"], data_dir)["status"] == jobs.STATUS_CANCELLED
        )

        assert not os.path.exists(captured["dir"])

    def test_a_cancelled_job_offers_no_download(self, data_dir):
        started = threading.Event()

        def work(context):
            started.set()
            for _ in range(500):
                context.check_cancelled()
                time.sleep(0.01)
            return _write_artifact(context), {}

        job = jobs.submit("gif", "p1", work, data_dir)
        assert started.wait(5)
        jobs.cancel_job(job["id"])
        assert _wait_for(
            lambda: jobs.get_job(job["id"], data_dir)["status"] == jobs.STATUS_CANCELLED
        )

        assert jobs.artifact_path(job["id"]) is None

    def test_cancelling_a_finished_job_is_a_no_op(self, data_dir):
        def work(context):
            return _write_artifact(context), {}

        job = jobs.submit("png", "p1", work, data_dir)
        assert _wait_for(lambda: jobs.get_job(job["id"], data_dir)["status"] == jobs.STATUS_DONE)

        assert jobs.cancel_job(job["id"]) is False

    def test_cancelling_an_unknown_job_is_false_not_an_error(self):
        assert jobs.cancel_job("nope") is False


class TestFailurePath:

    def test_the_error_message_reaches_the_user(self, data_dir):
        """A bare 'export failed' would make a bad setting undiagnosable."""
        def failing(context):
            raise ValueError("fps must be one of (10, 15, 20, 30)")

        job = jobs.submit("gif", "p1", failing, data_dir)
        assert _wait_for(lambda: jobs.get_job(job["id"], data_dir)["status"] == jobs.STATUS_ERROR)

        message = jobs.get_job(job["id"], data_dir)["message"]
        assert "ValueError" in message
        assert "fps must be one of" in message

    def test_a_failed_job_leaves_no_artifacts_behind(self, data_dir):
        captured = {}

        def failing(context):
            captured["dir"] = context.output_dir
            _write_artifact(context, "half.gif")
            raise RuntimeError("boom")

        job = jobs.submit("gif", "p1", failing, data_dir)
        assert _wait_for(lambda: jobs.get_job(job["id"], data_dir)["status"] == jobs.STATUS_ERROR)

        assert not os.path.exists(captured["dir"])

    def test_a_failed_job_offers_no_download(self, data_dir):
        def failing(context):
            raise RuntimeError("boom")

        job = jobs.submit("png", "p1", failing, data_dir)
        assert _wait_for(lambda: jobs.get_job(job["id"], data_dir)["status"] == jobs.STATUS_ERROR)

        assert jobs.artifact_path(job["id"]) is None


class TestRegistryHousekeeping:

    def test_jobs_can_be_filtered_by_project(self, data_dir):
        def work(context):
            return _write_artifact(context), {}

        first = jobs.submit("png", "alpha", work, data_dir)
        assert _wait_for(lambda: jobs.get_job(first["id"], data_dir)["status"] == jobs.STATUS_DONE)
        second = jobs.submit("png", "beta", work, data_dir)
        assert _wait_for(lambda: jobs.get_job(second["id"], data_dir)["status"] == jobs.STATUS_DONE)

        assert [j["id"] for j in jobs.list_jobs("alpha", data_dir)] == [first["id"]]

    def test_deleting_a_job_removes_its_files(self, data_dir):
        captured = {}

        def work(context):
            captured["dir"] = context.output_dir
            return _write_artifact(context), {}

        job = jobs.submit("png", "p1", work, data_dir)
        assert _wait_for(lambda: jobs.get_job(job["id"], data_dir)["status"] == jobs.STATUS_DONE)

        assert jobs.delete_job(job["id"], data_dir) is True
        assert not os.path.exists(captured["dir"])
        assert jobs.get_job(job["id"], data_dir) is None

    def test_deleting_an_unknown_job_is_false(self, data_dir):
        assert jobs.delete_job("nope", data_dir) is False

    def test_an_expired_artifact_is_swept(self, data_dir, monkeypatch):
        captured = {}

        def work(context):
            captured["dir"] = context.output_dir
            return _write_artifact(context), {}

        job = jobs.submit("png", "p1", work, data_dir)
        assert _wait_for(lambda: jobs.get_job(job["id"], data_dir)["status"] == jobs.STATUS_DONE)

        # Pretend the TTL elapsed rather than sleeping through it.
        monkeypatch.setattr(jobs, "ARTIFACT_TTL_SECONDS", -1)

        assert jobs.list_jobs(None, data_dir) == []
        assert not os.path.exists(captured["dir"])

    def test_a_stale_running_job_cannot_hold_the_slot_forever(self, data_dir, monkeypatch):
        """A crashed worker must not block every future generate."""
        gate = threading.Event()

        def work(context):
            gate.wait(10)
            return _write_artifact(context), {}

        stuck = jobs.submit("gif", "p1", work, data_dir)
        assert _wait_for(lambda: jobs.active_count() == 1)

        monkeypatch.setattr(jobs, "STALE_JOB_SECONDS", -1)

        # The sweep marks it errored, which frees the slot.
        assert jobs.get_job(stuck["id"], data_dir)["status"] == jobs.STATUS_ERROR
        assert jobs.active_count() == 0
        gate.set()

    def test_the_public_view_never_leaks_absolute_paths(self, data_dir):
        def work(context):
            return _write_artifact(context, "board.png"), {}

        job = jobs.submit("png", "p1", work, data_dir)
        assert _wait_for(lambda: jobs.get_job(job["id"], data_dir)["status"] == jobs.STATUS_DONE)

        view = jobs.get_job(job["id"], data_dir)
        assert "artifact" not in view
        assert data_dir not in repr(view)
        assert view["download_name"] == "board.png"
