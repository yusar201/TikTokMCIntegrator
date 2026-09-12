"""Short-lived export jobs for Gift Card Studio.

Khito's flow is: design in the Studio, press **Generate**, get a finished PNG or
GIF to download and drop into OBS as an image source. Nothing here streams to
OBS — the artifact is the product.

Why a job registry rather than rendering inside the request:

* A 20-second scroll GIF at 15fps is 300 rasterized frames. Doing that inline
  would hold a Flask worker for tens of seconds and, on a streaming PC, compete
  with gift->command dispatch. Generation runs on a daemon thread and the UI
  polls.
* Generation must be cancellable. A wrong 20s/30fps setting should be
  abandonable without waiting it out.
* The UI needs honest progress, not a spinner.

**Idle cost.** Importing this module starts nothing: no thread, no timer, no
lock contention. The registry is an empty dict until the first Generate. Each
job's thread exits when its work finishes, and finished artifacts are swept on
the next registry touch, so an idle app holds no export machinery at all.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
import uuid

# Concurrency cap. Generation is CPU-bound rasterization; letting several run at
# once on a live-streaming PC is exactly the wrong trade. Queueing is not needed
# — the UI simply reports "busy".
MAX_ACTIVE_JOBS = 1

# Finished artifacts are kept this long so the user can download them, then
# swept. Long enough to survive a slow click, short enough that the data dir
# does not accumulate GIFs.
ARTIFACT_TTL_SECONDS = 30 * 60

# A job that somehow never reports completion is treated as dead after this, so
# a crashed worker cannot occupy the single active slot forever.
STALE_JOB_SECONDS = 20 * 60

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"

TERMINAL_STATUSES = (STATUS_DONE, STATUS_ERROR, STATUS_CANCELLED)

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _now() -> float:
    return time.time()


def exports_dir(data_dir=None) -> str:
    """Where generated artifacts live. Separate from projects/ and assets/."""
    from . import storage

    return os.path.join(storage.studio_root(data_dir), "exports")


def job_dir(job_id: str, data_dir=None) -> str:
    return os.path.join(exports_dir(data_dir), job_id)


def _public(job: dict) -> dict:
    """The client-facing view of a job. Never leaks absolute paths."""
    view = {
        "id": job["id"],
        "status": job["status"],
        "kind": job["kind"],
        "project_id": job["project_id"],
        "progress": job["progress"],
        "total": job["total"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "message": job["message"],
    }
    if job["status"] == STATUS_DONE:
        view["download_name"] = job.get("download_name") or ""
        view["bytes"] = job.get("bytes") or 0
        view["report"] = job.get("report") or {}
        # Where it landed in the user's folder. This is the whole point of the
        # feature, so it is a first-class field rather than buried in report.
        view["saved_path"] = job.get("saved_path") or ""
        view["saved_name"] = os.path.basename(job.get("saved_path") or "")
        view["delivery_error"] = job.get("delivery_error") or ""
    if job["progress"] and job["total"]:
        view["percent"] = round(100.0 * job["progress"] / job["total"], 1)
    else:
        view["percent"] = 0.0
    return view


def _sweep_locked(data_dir=None) -> None:
    """Drop expired jobs and their artifacts. Caller must hold ``_lock``."""
    now = _now()
    for job_id in list(_jobs):
        job = _jobs[job_id]
        finished = job.get("finished_at") or 0
        expired = finished and (now - finished) > ARTIFACT_TTL_SECONDS
        stale = (
            job["status"] in (STATUS_PENDING, STATUS_RUNNING)
            and (now - job["created_at"]) > STALE_JOB_SECONDS
        )
        if not (expired or stale):
            continue
        if stale:
            # Mark rather than silently delete, so a UI still polling gets a
            # real answer instead of a 404 it cannot explain.
            job["status"] = STATUS_ERROR
            job["message"] = "generation timed out"
            job["finished_at"] = now
            continue
        _remove_artifacts(job_id, job.get("data_dir"))
        _jobs.pop(job_id, None)


def _remove_artifacts(job_id: str, data_dir=None) -> None:
    path = job_dir(job_id, data_dir)
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def active_count() -> int:
    with _lock:
        return sum(
            1 for job in _jobs.values()
            if job["status"] in (STATUS_PENDING, STATUS_RUNNING)
        )


def list_jobs(project_id=None, data_dir=None) -> list[dict]:
    with _lock:
        _sweep_locked(data_dir)
        jobs = [
            _public(job) for job in _jobs.values()
            if project_id is None or job["project_id"] == project_id
        ]
    jobs.sort(key=lambda item: item["created_at"], reverse=True)
    return jobs


def get_job(job_id: str, data_dir=None) -> dict | None:
    with _lock:
        _sweep_locked(data_dir)
        job = _jobs.get(job_id)
        return _public(job) if job else None


def artifact_path(job_id: str) -> str | None:
    """Absolute path of a finished job's downloadable file, if any."""
    with _lock:
        job = _jobs.get(job_id)
        if not job or job["status"] != STATUS_DONE:
            return None
        path = job.get("artifact")
    if not path or not os.path.isfile(path):
        return None
    return path


def cancel_job(job_id: str) -> bool:
    """Request cancellation. The worker notices at its next frame boundary."""
    with _lock:
        job = _jobs.get(job_id)
        if not job or job["status"] in TERMINAL_STATUSES:
            return False
        job["cancel"].set()
        job["message"] = "cancelling"
        return True


def delete_job(job_id: str, data_dir=None) -> bool:
    with _lock:
        job = _jobs.pop(job_id, None)
        if job is None:
            return False
        job["cancel"].set()
        stored_dir = job.get("data_dir")
    _remove_artifacts(job_id, stored_dir if stored_dir is not None else data_dir)
    return True


class JobBusy(RuntimeError):
    """Raised when the single generation slot is already taken."""


def submit(kind: str, project_id: str, work, data_dir=None,
           deliver_to=None) -> dict:
    """Start ``work`` on a daemon thread and return the public job view.

    ``work(context)`` receives a context exposing:

    * ``context.output_dir`` — a fresh directory for this job's files
    * ``context.progress(done, total)`` — report progress
    * ``context.cancelled()`` — True once cancellation was requested
    * ``context.check_cancelled()`` — raise ``JobCancelled`` if cancelled

    It must return ``(artifact_path, report_dict)``.

    ``deliver_to`` is the user's chosen output folder. When set, the finished
    artifact is copied there and the saved location is reported on the job, so
    the file lands where Khito wants it without a browser download step.
    """
    with _lock:
        _sweep_locked(data_dir)
        active = sum(
            1 for job in _jobs.values()
            if job["status"] in (STATUS_PENDING, STATUS_RUNNING)
        )
        if active >= MAX_ACTIVE_JOBS:
            raise JobBusy("a generation is already running")

        job_id = uuid.uuid4().hex[:16]
        job = {
            "id": job_id,
            "kind": kind,
            "project_id": project_id,
            "status": STATUS_PENDING,
            "progress": 0,
            "total": 0,
            "message": "",
            "created_at": _now(),
            "started_at": 0.0,
            "finished_at": 0.0,
            "cancel": threading.Event(),
            "artifact": "",
            "download_name": "",
            "bytes": 0,
            "report": {},
            "data_dir": data_dir,
            "deliver_to": deliver_to or "",
            "saved_path": "",
            "delivery_error": "",
        }
        _jobs[job_id] = job

    output_dir = job_dir(job_id, data_dir)
    os.makedirs(output_dir, exist_ok=True)

    context = _JobContext(job, output_dir)
    thread = threading.Thread(
        target=_run, args=(job, context, work), name=f"gift-studio-{kind}-{job_id}",
        daemon=True,
    )
    with _lock:
        job["thread"] = thread
    thread.start()

    return _public(job)


class JobCancelled(RuntimeError):
    """Raised inside a worker when cancellation was requested."""


class _JobContext:

    def __init__(self, job, output_dir):
        self._job = job
        self.output_dir = output_dir

    def progress(self, done, total):
        with _lock:
            self._job["progress"] = int(done)
            self._job["total"] = int(total)

    def cancelled(self) -> bool:
        return self._job["cancel"].is_set()

    def check_cancelled(self) -> None:
        if self.cancelled():
            raise JobCancelled("generation cancelled")


def _finish_cancelled(job) -> None:
    # Clean up *before* publishing the terminal status. A client that polls and
    # sees "cancelled" must be able to trust that nothing is left on disk; doing
    # the rmtree afterwards leaves a window where the job looks finished but its
    # partial GIF is still there.
    with _lock:
        stored_dir = job.get("data_dir")
    _remove_artifacts(job["id"], stored_dir)
    with _lock:
        job["status"] = STATUS_CANCELLED
        job["message"] = "cancelled"
        job["finished_at"] = _now()


def _finish_error(job, message) -> None:
    with _lock:
        stored_dir = job.get("data_dir")
    _remove_artifacts(job["id"], stored_dir)
    with _lock:
        job["status"] = STATUS_ERROR
        job["message"] = message
        job["finished_at"] = _now()


def _run(job, context, work) -> None:
    with _lock:
        job["status"] = STATUS_RUNNING
        job["started_at"] = _now()

    try:
        artifact, report = work(context)
    except JobCancelled:
        _finish_cancelled(job)
        return
    except BaseException as exc:  # noqa: BLE001 - reported to the user verbatim
        # A worker that cooperates with cancellation raises whatever its own
        # layer uses (the exporter raises ExportCancelled, not JobCancelled).
        # Trust the cancel flag over the exception type, or a user-requested
        # cancel gets reported as a crash — which is what happened before this
        # check existed.
        if context.cancelled():
            _finish_cancelled(job)
            return
        # The exception text is the whole diagnostic the user gets; a bare
        # "export failed" would make a bad fps or an oversized canvas
        # impossible to self-diagnose.
        _finish_error(job, f"{type(exc).__name__}: {exc}")
        return

    size = 0
    try:
        size = os.path.getsize(artifact)
    except OSError:
        pass

    # Deliver into the user's chosen folder. A copy failure does NOT fail the
    # job: the render succeeded and the artifact is still downloadable, so the
    # honest outcome is "generated, but could not save there" with the reason
    # attached — not a discarded 30-second render.
    saved_path = ""
    delivery_error = ""
    with _lock:
        destination = job.get("deliver_to") or ""
    if destination:
        try:
            from . import output as output_settings

            saved_path = output_settings.deliver(artifact, destination)
        except BaseException as exc:  # noqa: BLE001 - surfaced to the user
            delivery_error = f"{type(exc).__name__}: {exc}"

    with _lock:
        job["status"] = STATUS_DONE
        job["artifact"] = artifact
        job["download_name"] = os.path.basename(artifact)
        job["bytes"] = size
        job["report"] = report or {}
        job["finished_at"] = _now()
        job["saved_path"] = saved_path
        job["delivery_error"] = delivery_error
        job["message"] = "saved" if saved_path else ("ready" if not delivery_error else "generated, not saved")


def reset_for_tests() -> None:
    """Drop all job state. Tests only."""
    with _lock:
        for job in _jobs.values():
            job["cancel"].set()
        ids = [(job_id, job.get("data_dir")) for job_id, job in _jobs.items()]
        _jobs.clear()
    for job_id, stored_dir in ids:
        _remove_artifacts(job_id, stored_dir)
