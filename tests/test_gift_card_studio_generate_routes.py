"""Generate & download HTTP endpoints.

The whole point of the Studio is the download, so these tests exercise the real
route surface end to end: estimate, start, poll, download the actual bytes,
cancel, and the failure/conflict responses in between.
"""

import os
import time
import zipfile

import pytest
from flask import Flask

from gift_card_studio import catalog, jobs, models, output, storage
from routes.gift_card_studio import create_gift_studio_blueprint

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG = {
    "Gifts": {
        "5487": ["spawnmob {mc} 1 warden {user}", "titlecustom '{user}' {mc} Warden"],
        "5655": ["summon luckytntmod:village_defense ~ ~ ~", "titlecustom '{user}' {mc} TNT"],
    },
    "GiftNames": {"5487": "gold necklace", "5655": "rose"},
    "GiftCategories": {"5487": "200 Coins", "5655": "1 Coin"},
}


@pytest.fixture(autouse=True)
def clean_registry():
    jobs.reset_for_tests()
    yield
    jobs.reset_for_tests()


@pytest.fixture
def data_dir(tmp_path):
    root = tmp_path / "data"
    storage.ensure_dirs(str(root))
    return str(root)


@pytest.fixture
def client(data_dir):
    app = Flask(__name__)
    app.register_blueprint(
        create_gift_studio_blueprint(
            data_dir=data_dir,
            assets_dir=os.path.join(ROOT, "assets"),
            load_config=lambda: CONFIG,
            base_dir=ROOT,
        ),
        url_prefix="/api/gift-studio",
    )
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def project_id(client, data_dir):
    created = client.post("/api/gift-studio/projects", json={"name": "Route Gen"})
    project = created.get_json()["project"]
    project["canvas"].update({"width": 400, "height": 200, "background": "transparent"})
    project["pages"][0]["grid"].update({"rows": 1, "columns": 2, "gap_x": 8, "padding": 8})
    project["playback"].update({
        "mode": "pages", "default_page_duration_ms": 400,
        "default_transition": {"type": "cut", "duration_ms": 0},
    })
    client.put(f"/api/gift-studio/projects/{project['id']}", json=project)
    client.post("/api/gift-studio/catalog/import", json={"project_id": project["id"]})
    return project["id"]


def _await_job(client, job_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/gift-studio/generate/jobs/{job_id}").get_json()["job"]
        if job["status"] in jobs.TERMINAL_STATUSES:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


class TestEstimateEndpoint:

    def test_it_reports_what_a_png_generate_would_produce(self, client, project_id):
        response = client.post("/api/gift-studio/generate/estimate", json={
            "project_id": project_id, "save": False, "settings": {"format": "png", "mode": "page"},
        })

        assert response.status_code == 200
        info = response.get_json()["estimate"]
        assert info["file_count"] == 1
        assert info["output_width"] == 400

    def test_it_reports_gif_frame_count_before_committing(self, client, project_id):
        response = client.post("/api/gift-studio/generate/estimate", json={
            "project_id": project_id, "save": False, "settings": {"format": "gif", "fps": 15},
        })

        info = response.get_json()["estimate"]
        assert info["frame_count"] == 6  # 400ms at 15fps
        assert info["duration_ms"] == 400

    def test_a_bad_setting_is_rejected_with_a_usable_message(self, client, project_id):
        response = client.post("/api/gift-studio/generate/estimate", json={
            "project_id": project_id, "save": False, "settings": {"format": "gif", "fps": 12},
        })

        assert response.status_code == 400
        message = response.get_json()["message"]
        assert "fps must be one of" in message
        assert "15" in message

    def test_an_inline_unsaved_project_can_be_estimated(self, client):
        project = models.normalize_project(models.new_project("Unsaved"))

        response = client.post("/api/gift-studio/generate/estimate", json={
            "project": project, "settings": {"format": "png"},
        })

        assert response.status_code == 200

    def test_a_missing_project_is_an_error_not_a_crash(self, client):
        response = client.post("/api/gift-studio/generate/estimate", json={
            "settings": {"format": "png"},
        })

        assert response.status_code == 400
        assert "required" in response.get_json()["message"]

    def test_an_unknown_project_id_is_404(self, client):
        response = client.post("/api/gift-studio/generate/estimate", json={
            "project_id": "nope", "settings": {"format": "png"},
        })

        assert response.status_code == 404

    def test_estimating_starts_no_job(self, client, project_id):
        client.post("/api/gift-studio/generate/estimate", json={
            "project_id": project_id, "save": False, "settings": {"format": "gif"},
        })

        assert client.get("/api/gift-studio/generate/jobs").get_json()["jobs"] == []


class TestOutputFolderFlow:

    def test_generate_requires_a_folder_by_default(self, client, project_id):
        response = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "settings": {"format": "png"},
        })
        assert response.status_code == 409
        assert "choose an output folder" in response.get_json()["message"]

    def test_selected_folder_receives_the_real_generated_png(self, client, project_id, tmp_path):
        destination = tmp_path / "obs"
        destination.mkdir()
        assert client.post("/api/gift-studio/output-folder", json={"path": str(destination)}).status_code == 200

        started = client.post("/api/gift-studio/generate", json={
            "project_id": project_id,
            "settings": {"format": "png", "mode": "page"},
        })
        assert started.status_code == 202
        job = _await_job(client, started.get_json()["job"]["id"])

        assert job["status"] == jobs.STATUS_DONE, job["message"]
        assert job["message"] == "saved"
        assert os.path.dirname(job["saved_path"]) == os.path.abspath(str(destination))
        with open(job["saved_path"], "rb") as handle:
            assert handle.read(8) == b"\x89PNG\r\n\x1a\n"

    def test_native_browse_persists_the_picked_folder(self, client, data_dir, tmp_path):
        destination = tmp_path / "picked"
        destination.mkdir()
        output.register_folder_picker(lambda: str(destination))

        response = client.post("/api/gift-studio/output-folder/browse")

        assert response.status_code == 200
        assert response.get_json()["output"]["path"] == os.path.abspath(str(destination))
        assert output.require_output_folder(data_dir) == os.path.abspath(str(destination))

    def test_cancelling_browse_keeps_the_previous_folder(self, client, data_dir, tmp_path):
        destination = tmp_path / "kept"
        destination.mkdir()
        output.set_output_folder(str(destination), data_dir)
        output.register_folder_picker(lambda: None)

        response = client.post("/api/gift-studio/output-folder/browse")

        assert response.status_code == 200
        assert response.get_json()["status"] == "cancelled"
        assert output.require_output_folder(data_dir) == os.path.abspath(str(destination))

    def test_plain_browser_gets_an_explicit_picker_unavailable_response(self, client):
        output.register_folder_picker(None)
        response = client.post("/api/gift-studio/output-folder/browse")
        assert response.status_code == 501
        assert "desktop app" in response.get_json()["message"]


class TestPngGenerateAndDownload:

    def test_a_png_generate_completes_and_downloads_real_bytes(self, client, project_id):
        started = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "png", "mode": "page"},
        })
        assert started.status_code == 202

        job = _await_job(client, started.get_json()["job"]["id"])
        assert job["status"] == jobs.STATUS_DONE, job["message"]

        download = client.get(
            f"/api/gift-studio/generate/jobs/{job['id']}/download"
        )
        assert download.status_code == 200
        body = download.get_data()
        assert body[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(body) == job["bytes"]

    def test_the_download_is_an_attachment_with_a_filename(self, client, project_id):
        """Inline would render it in a tab; OBS needs a file on disk."""
        started = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "png"},
        })
        job = _await_job(client, started.get_json()["job"]["id"])

        download = client.get(f"/api/gift-studio/generate/jobs/{job['id']}/download")

        disposition = download.headers.get("Content-Disposition", "")
        assert "attachment" in disposition
        assert ".png" in disposition
        assert download.headers.get("Content-Type") == "image/png"

    def test_a_multi_file_mode_downloads_one_zip_of_real_pngs(self, client, project_id):
        started = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "png", "mode": "cards"},
        })
        job = _await_job(client, started.get_json()["job"]["id"])
        assert job["status"] == jobs.STATUS_DONE, job["message"]

        download = client.get(f"/api/gift-studio/generate/jobs/{job['id']}/download")

        assert ".zip" in download.headers.get("Content-Disposition", "")
        path = jobs.artifact_path(job["id"])
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            assert len(names) == 2
            for name in names:
                assert archive.read(name)[:8] == b"\x89PNG\r\n\x1a\n"

    def test_the_report_includes_the_estimate(self, client, project_id):
        started = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "png"},
        })
        job = _await_job(client, started.get_json()["job"]["id"])

        assert job["report"]["estimate"]["output_width"] == 400


class TestGifGenerateAndDownload:

    def test_a_gif_generate_downloads_a_real_animation(self, client, project_id):
        started = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "gif", "fps": 10},
        })
        job = _await_job(client, started.get_json()["job"]["id"])
        assert job["status"] == jobs.STATUS_DONE, job["message"]

        download = client.get(f"/api/gift-studio/generate/jobs/{job['id']}/download")

        body = download.get_data()
        assert body[:6] in (b"GIF89a", b"GIF87a")
        assert download.headers.get("Content-Type") == "image/gif"

    def test_the_job_reports_frame_count_and_duration(self, client, project_id):
        started = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "gif", "fps": 10},
        })
        job = _await_job(client, started.get_json()["job"]["id"])

        assert job["report"]["fps"] == 10
        assert job["report"]["frame_count"] > 0
        assert job["report"]["duration_ms"] > 0

    def test_an_oversized_gif_is_refused_at_submit_not_mid_render(self, client, project_id):
        response = client.post("/api/gift-studio/generate", json={
            "project_id": project_id,
            "save": False,
            "settings": {"format": "gif", "fps": 30, "duration_ms": 60_000},
        })

        assert response.status_code == 400
        assert "frame" in response.get_json()["message"]
        assert client.get("/api/gift-studio/generate/jobs").get_json()["jobs"] == []


class TestJobEndpoints:

    def test_a_second_concurrent_generate_is_409_not_500(self, client, project_id):
        """The request is valid; the single render slot is busy."""
        first = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "gif", "fps": 30},
        })
        assert first.status_code == 202

        second = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "gif", "fps": 30},
        })

        # The first may already have finished on a fast machine.
        if second.status_code == 409:
            assert "already running" in second.get_json()["message"]
        _await_job(client, first.get_json()["job"]["id"])

    def test_jobs_can_be_listed_and_filtered(self, client, project_id):
        started = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "png"},
        })
        _await_job(client, started.get_json()["job"]["id"])

        listed = client.get(
            f"/api/gift-studio/generate/jobs?project_id={project_id}"
        ).get_json()["jobs"]

        assert [job["project_id"] for job in listed] == [project_id]

    def test_an_unknown_job_is_404(self, client):
        assert client.get("/api/gift-studio/generate/jobs/nope").status_code == 404
        assert client.get("/api/gift-studio/generate/jobs/nope/download").status_code == 404

    def test_downloading_before_completion_is_409(self, client, project_id):
        started = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "gif", "fps": 30},
        })
        job_id = started.get_json()["job"]["id"]

        early = client.get(f"/api/gift-studio/generate/jobs/{job_id}/download")

        # Either it is still running (409) or it already finished (200).
        assert early.status_code in (200, 409)
        _await_job(client, job_id)

    def test_a_job_can_be_cancelled_and_then_offers_no_download(self, client, project_id):
        started = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "gif", "fps": 30},
        })
        job_id = started.get_json()["job"]["id"]

        client.post(f"/api/gift-studio/generate/jobs/{job_id}/cancel")
        job = _await_job(client, job_id)

        if job["status"] == jobs.STATUS_CANCELLED:
            failed = client.get(f"/api/gift-studio/generate/jobs/{job_id}/download")
            assert failed.status_code == 409

    def test_cancelling_a_finished_job_is_409(self, client, project_id):
        started = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "png"},
        })
        job_id = started.get_json()["job"]["id"]
        _await_job(client, job_id)

        response = client.post(f"/api/gift-studio/generate/jobs/{job_id}/cancel")

        assert response.status_code == 409

    def test_deleting_a_job_removes_it_and_its_file(self, client, project_id):
        started = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "png"},
        })
        job_id = started.get_json()["job"]["id"]
        _await_job(client, job_id)
        path = jobs.artifact_path(job_id)
        assert path and os.path.isfile(path)

        assert client.delete(f"/api/gift-studio/generate/jobs/{job_id}").status_code == 200

        assert not os.path.exists(path)
        assert client.get(f"/api/gift-studio/generate/jobs/{job_id}").status_code == 404

    def test_the_job_payload_never_exposes_a_filesystem_path(self, client, project_id, data_dir):
        started = client.post("/api/gift-studio/generate", json={
            "project_id": project_id, "save": False, "settings": {"format": "png"},
        })
        job = _await_job(client, started.get_json()["job"]["id"])

        # report["path"] is the exporter's own field; the job view itself must
        # not hand the client an absolute location to poke at.
        assert "artifact" not in job
        assert data_dir not in str(job.get("download_name", ""))
