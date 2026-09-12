"""Gift Card Studio — isolated engine for designing TikTok gift overlay cards.

Design contract (see .hermes/plans/2026-08-28_091243-gift-card-studio.md):

* **Zero inactive runtime.** Importing this package must not start a thread,
  timer, watcher, network call, or subprocess, and must not import the export
  stack (Pillow, rasterizers). Only ``models`` / ``grid`` / ``validation`` are
  eagerly importable here because they are pure-Python data helpers.
* **Structured projects, not flattened images.** Versioned JSON is the source of
  truth; PNG/GIF are exports only.
* **No mutation of live config.** The catalog adapter reads gift/action
  assignments; design projects are stored separately under
  ``data/gift_card_studio/``.

Heavier submodules (``catalog``, ``classifier``, ``storage``, ``exporter``) are
imported lazily by their callers so the dashboard process never pays for them
until the Studio panel is actually opened.
"""

from . import grid, models, validation

SCHEMA_VERSION: int = models.SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION", "grid", "models", "validation"]
