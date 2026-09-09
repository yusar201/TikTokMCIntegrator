"""Gift Card Studio HTTP API.

Blueprint factory rather than a module-level Blueprint with globals, so tests
can build an isolated app against a tmp data dir and the frozen app can inject
``paths``-derived directories. Registered under ``/api/gift-studio``.

Security posture:

* Project ids and asset names are validated by ``gift_card_studio.storage``
  before they ever reach the filesystem — path traversal is rejected, not
  sanitized-and-hoped.
* Uploaded images are verified by **decoding** them with Pillow, not by trusting
  the client's filename or Content-Type. Pillow is imported inside the upload
  handler so the export/image stack stays out of the idle process.
* Asset serving is a strict allowlist of extensions with a fixed root and no
  user-controlled directory component.
* There is **no authentication here**: this API rides on the same local-only
  Flask app as the rest of the dashboard, which binds to localhost for the
  desktop shell. If that app is ever exposed beyond localhost, these endpoints
  (project write + file upload) become remotely writable and need auth.
"""
from __future__ import annotations

import io
import os

from flask import Blueprint, jsonify, request, send_file, send_from_directory

from gift_card_studio import assets, catalog, generate, jobs, models, output, storage
from gift_card_studio.validation import ValidationError

# Uploads are overlay artwork, not video; 6MB is generous for a card asset.
MAX_ASSET_BYTES = 6 * 1024 * 1024

# Pillow format name -> extension we will store it as.
VERIFIED_FORMATS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif"}


def _error(message, status=400):
    return jsonify({"status": "error", "message": str(message)}), status


def create_gift_studio_blueprint(data_dir, assets_dir, load_config, base_dir=None):
    """Build the Studio blueprint.

    ``load_config`` is a zero-arg callable returning the live config dict — the
    catalog must read config *at request time* so newly configured gifts show up
    without restarting the app (project invariant: settings apply live).

    ``base_dir`` is the app root used to resolve relative asset paths while
    rasterizing an export. Exports inline every asset as base64 and never touch
    the network, so this must point at a directory that actually contains the
    fonts and cached gift icons.
    """
    bp = Blueprint("gift_studio", __name__)

    # ---- Projects -------------------------------------------------------

    @bp.route("/projects", methods=["GET"])
    def list_projects():
        return jsonify({"projects": storage.list_projects(data_dir)})

    @bp.route("/projects", methods=["POST"])
    def create_project():
        payload = request.get_json(silent=True) or {}
        name = (payload.get("name") or "Untitled Project").strip() or "Untitled Project"
        try:
            project = storage.create_project(name, data_dir)
        except ValidationError as exc:
            return _error(exc)
        return jsonify({"status": "success", "project": project}), 201

    @bp.route("/projects/<project_id>", methods=["GET"])
    def get_project(project_id):
        try:
            project = storage.load_project(project_id, data_dir)
        except ValidationError as exc:
            return _error(exc)
        if project is None:
            return _error("project not found", 404)
        return jsonify({"project": project})

    @bp.route("/projects/<project_id>", methods=["PUT"])
    def save_project(project_id):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("request body must be a JSON object")
        nested = payload.get("project")
        body = nested if isinstance(nested, dict) else payload
        try:
            # project_id from the URL wins: a client cannot rename/relocate a
            # project by putting a different id in the body.
            saved = storage.save_project(body, data_dir, project_id=project_id)
        except ValidationError as exc:
            return _error(exc)
        return jsonify({"status": "success", "project": saved})

    @bp.route("/projects/<project_id>", methods=["DELETE"])
    def delete_project(project_id):
        try:
            removed = storage.delete_project(project_id, data_dir)
        except ValidationError as exc:
            return _error(exc)
        if not removed:
            return _error("project not found", 404)
        return jsonify({"status": "success"})

    # ---- Catalog --------------------------------------------------------

    @bp.route("/catalog", methods=["GET"])
    def get_catalog():
        """Configured gifts joined to catalog metadata + draft suggestions."""
        entries = catalog.build_catalog(load_config() or {}, data_dir, assets_dir)
        return jsonify({"entries": entries, "stats": catalog.catalog_stats(entries)})

    @bp.route("/catalog/preview", methods=["POST"])
    def preview_catalog_import():
        """Dry run: what an import would add/change/remove. Writes nothing."""
        payload = request.get_json(silent=True) or {}
        project_id = payload.get("project_id")
        try:
            project = (
                storage.load_project(project_id, data_dir) if project_id
                else models.new_project("Preview")
            )
        except ValidationError as exc:
            return _error(exc)
        if project is None:
            return _error("project not found", 404)

        entries = catalog.build_catalog(load_config() or {}, data_dir, assets_dir)
        diff = catalog.diff_catalog(project, entries)
        return jsonify({
            "counts": diff["counts"],
            "new": [item["key"] for item in diff["new"]],
            "changed": [
                {"key": item["key"], "protected": item["protected"]}
                for item in diff["changed"]
            ],
            "missing": [item["key"] for item in diff["missing"]],
            "stats": catalog.catalog_stats(entries),
        })

    @bp.route("/catalog/import", methods=["POST"])
    def import_catalog():
        """Apply an import to a saved project. Customized cards are preserved."""
        payload = request.get_json(silent=True) or {}
        project_id = payload.get("project_id")
        if not project_id:
            return _error("project_id is required")
        try:
            project = storage.load_project(project_id, data_dir)
        except ValidationError as exc:
            return _error(exc)
        if project is None:
            return _error("project not found", 404)

        keys = payload.get("keys")
        if keys is not None and not isinstance(keys, list):
            return _error("keys must be a list when provided")

        entries = catalog.build_catalog(load_config() or {}, data_dir, assets_dir)
        # Export is deliberately offline, so every approved catalog row needs a
        # static local still before its card is drafted. Cache only the selected
        # subset: importing one gift must not download all 500 catalog icons.
        selected_keys = {str(key) for key in keys} if keys is not None else None
        cache_entries = [
            entry for entry in entries
            if selected_keys is None or str(entry.get("key")) in selected_keys
        ]
        icon_cache = assets.cache_catalog_icons(cache_entries, data_dir)
        report = catalog.apply_catalog_import(
            project,
            entries,
            keys=keys,
            refresh_changed=bool(payload.get("refresh_changed", True)),
            assign_to_page=bool(payload.get("assign_to_page", True)),
            include_action_icon=bool(payload.get("include_action_icon", True)),
        )
        try:
            saved = storage.save_project(report["project"], data_dir, project_id=project_id)
        except ValidationError as exc:
            return _error(exc)

        return jsonify({
            "status": "success",
            "project": saved,
            "added": report["added"],
            "refreshed": report["refreshed"],
            "skipped_customized": report["skipped_customized"],
            "diff_counts": report["diff_counts"],
            "icon_cache": icon_cache,
        })

    # ---- Assets ---------------------------------------------------------

    @bp.route("/assets", methods=["GET"])
    def list_assets():
        return jsonify({"assets": storage.list_assets(data_dir)})

    @bp.route("/assets", methods=["POST"])
    def upload_asset():
        """Store an uploaded image after verifying it really decodes."""
        file = request.files.get("file")
        if file is None:
            return _error("no file uploaded")

        raw = file.read(MAX_ASSET_BYTES + 1)
        if not raw:
            return _error("uploaded file is empty")
        if len(raw) > MAX_ASSET_BYTES:
            return _error(f"file exceeds {MAX_ASSET_BYTES // (1024 * 1024)}MB limit", 413)

        # Imported here, not at module scope: the image stack must stay out of
        # the dashboard's idle footprint.
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover - Pillow is a hard requirement
            return _error("image support unavailable on this build", 500)

        try:
            with Image.open(io.BytesIO(raw)) as probe:
                probe.verify()
                image_format = (probe.format or "").upper()
        except Exception:
            return _error("file is not a decodable image")

        if image_format not in VERIFIED_FORMATS:
            return _error(f"unsupported image format: {image_format or 'unknown'}")

        # Trust the decoded format over the client's filename extension.
        stem = os.path.splitext(file.filename or "asset")[0]
        try:
            name = storage.save_asset_bytes(stem + VERIFIED_FORMATS[image_format], raw, data_dir)
        except ValidationError as exc:
            return _error(exc)

        return jsonify({"status": "success", "asset": {"name": name, "size": len(raw)}}), 201

    @bp.route("/assets/<asset_name>", methods=["DELETE"])
    def delete_asset(asset_name):
        try:
            removed = storage.delete_asset(asset_name, data_dir)
        except ValidationError as exc:
            return _error(exc)
        if not removed:
            return _error("asset not found", 404)
        return jsonify({"status": "success"})

    # ---- Output folder --------------------------------------------------
    #
    # Generated files are written straight into a folder the user picks once, so
    # they can be added to OBS as an image source without a download step.

    @bp.route("/output-folder", methods=["GET"])
    def get_output_folder():
        """Current destination and whether it is still usable.

        Status is re-checked on every read: an external drive can be unplugged
        or a folder renamed between generates, and finding that out *before* a
        30-second render is the whole point.
        """
        return jsonify({"output": output.get_output_folder(data_dir)})

    @bp.route("/output-folder", methods=["POST"])
    def set_output_folder():
        """Set the destination from an explicit path."""
        payload = request.get_json(silent=True) or {}
        try:
            info = output.set_output_folder(payload.get("path"), data_dir)
        except ValidationError as exc:
            return _error(exc)
        return jsonify({"status": "success", "output": info})

    @bp.route("/output-folder/browse", methods=["POST"])
    def browse_output_folder():
        """Open the native folder dialog and store what the user picks.

        The dialog is owned by the desktop shell; in a plain browser there is no
        picker, which returns 501 so the UI can fall back to a path field
        instead of appearing broken.
        """
        if not output.has_folder_picker():
            return _error(
                "the folder picker is only available in the desktop app; "
                "type a path instead",
                501,
            )
        try:
            chosen = output.pick_folder()
        except ValidationError as exc:
            return _error(exc, 501)
        if not chosen:
            # Cancelling is a normal outcome, not an error.
            return jsonify({"status": "cancelled", "output": output.get_output_folder(data_dir)})

        try:
            info = output.set_output_folder(chosen, data_dir)
        except ValidationError as exc:
            return _error(exc)
        return jsonify({"status": "success", "output": info})

    @bp.route("/output-folder", methods=["DELETE"])
    def clear_output_folder():
        output.clear_output_folder(data_dir)
        return jsonify({"status": "success", "output": output.get_output_folder(data_dir)})

    # ---- Generate & download -------------------------------------------
    #
    # This is the Studio's product: the user designs, presses Generate, and the
    # finished PNG or GIF is written into their chosen folder for OBS. The app
    # never serves the overlay live, so these endpoints are the whole delivery
    # path (the download route remains as a fallback).

    def _resolve_project(payload):
        """Project from a saved id, or an inline project for unsaved previews."""
        project_id = payload.get("project_id")
        if project_id:
            project = storage.load_project(project_id, data_dir)
            if project is None:
                return None, _error("project not found", 404)
            return project, None
        inline = payload.get("project")
        if isinstance(inline, dict):
            # Lets the user generate before saving; normalize_project rejects
            # anything malformed.
            return models.normalize_project(inline), None
        return None, _error("project_id or project is required")

    @bp.route("/generate/estimate", methods=["POST"])
    def estimate_generate():
        """What a generate would produce — file count, frames, pixels.

        Lets the UI warn about a 300-frame job *before* the user commits, and
        surfaces an impossible setting immediately rather than mid-render.
        """
        payload = request.get_json(silent=True) or {}
        try:
            project, failure = _resolve_project(payload)
        except ValidationError as exc:
            return _error(exc)
        if failure is not None:
            return failure

        try:
            settings = generate.normalize_settings(payload.get("settings"))
            info = generate.check_feasible(project, settings)
        except generate.SettingsError as exc:
            return _error(exc)
        except ValidationError as exc:
            return _error(exc)

        return jsonify({"status": "success", "settings": settings, "estimate": info})

    @bp.route("/generate", methods=["POST"])
    def start_generate():
        """Kick off generation on a worker thread; poll the returned job id.

        The output folder is resolved here so a missing/stale destination is
        rejected before any rasterization happens. ``save=false`` opts out for a
        download-only generate.
        """
        payload = request.get_json(silent=True) or {}
        try:
            project, failure = _resolve_project(payload)
        except ValidationError as exc:
            return _error(exc)
        if failure is not None:
            return failure

        deliver_to = None
        if payload.get("save", True):
            try:
                deliver_to = output.require_output_folder(data_dir)
            except ValidationError as exc:
                # 409: the request is fine, the app just is not configured yet.
                return _error(exc, 409)

        try:
            job = generate.submit_generate(
                project, payload.get("settings"), data_dir=data_dir,
                base_dir=base_dir, deliver_to=deliver_to,
            )
        except generate.SettingsError as exc:
            return _error(exc)
        except jobs.JobBusy as exc:
            # 409, not 500: the request was valid, the resource is busy.
            return _error(exc, 409)
        except ValidationError as exc:
            return _error(exc)

        return jsonify({"status": "success", "job": job}), 202

    @bp.route("/generate/jobs", methods=["GET"])
    def list_generate_jobs():
        project_id = request.args.get("project_id") or None
        return jsonify({"jobs": jobs.list_jobs(project_id, data_dir)})

    @bp.route("/generate/jobs/<job_id>", methods=["GET"])
    def get_generate_job(job_id):
        job = jobs.get_job(job_id, data_dir)
        if job is None:
            return _error("job not found", 404)
        return jsonify({"job": job})

    @bp.route("/generate/jobs/<job_id>", methods=["DELETE"])
    def delete_generate_job(job_id):
        """Cancel if running, and drop the artifact either way."""
        jobs.cancel_job(job_id)
        if not jobs.delete_job(job_id, data_dir):
            return _error("job not found", 404)
        return jsonify({"status": "success"})

    @bp.route("/generate/jobs/<job_id>/cancel", methods=["POST"])
    def cancel_generate_job(job_id):
        if not jobs.cancel_job(job_id):
            return _error("job is not running", 409)
        return jsonify({"status": "success"})

    @bp.route("/generate/jobs/<job_id>/download", methods=["GET"])
    def download_generated(job_id):
        """Send the finished artifact as an attachment.

        ``as_attachment`` matters: without it the browser renders the PNG/GIF in
        a tab instead of saving it, and the user cannot point OBS at a file that
        was never written to disk.
        """
        job = jobs.get_job(job_id, data_dir)
        if job is None:
            return _error("job not found", 404)
        if job["status"] != jobs.STATUS_DONE:
            return _error(f"job is {job['status']}, not ready to download", 409)

        path = jobs.artifact_path(job_id)
        if not path:
            return _error("generated file is no longer available", 410)

        return send_file(
            path,
            as_attachment=True,
            download_name=job.get("download_name") or os.path.basename(path),
            max_age=0,
        )

    return bp


def create_gift_studio_assets_blueprint(data_dir):
    """Serve uploaded Studio assets read-only, outside the /api namespace."""
    bp = Blueprint("gift_studio_assets", __name__)

    @bp.route("/gift-studio-assets/<asset_name>", methods=["GET"])
    def serve_asset(asset_name):
        # Validate before touching disk: send_from_directory alone would accept
        # names we do not want to serve (e.g. a stray .json or .tmp).
        if not storage.is_safe_asset_name(asset_name):
            return _error("invalid asset name", 404)
        directory = storage.assets_dir(data_dir)
        if not os.path.exists(os.path.join(directory, asset_name)):
            return _error("asset not found", 404)
        return send_from_directory(directory, asset_name)

    return bp
