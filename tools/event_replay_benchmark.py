"""Offline event-path replay and resource benchmark.

This harness deliberately avoids TikTok, Minecraft, Spotify, OBS, and production
state. It measures the local bookkeeping components that can be safely replayed
while the operator is away.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

# Allow direct execution from the repository's tools/ directory on Windows.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import points_store
import stream_ranking


def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return ordered[index]


def run(gifts: int, viewers: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="tiktokmc-replay-") as temp:
        root = Path(temp)
        db = root / "points.db"
        ranking = root / "ranking.json"
        points_store.init(str(db))
        stream_ranking._state.clear()
        stream_ranking._last_flush.clear()

        point_ms = []
        rank_ms = []
        started = time.perf_counter()
        for i in range(gifts):
            uid = f"viewer-{i % max(1, viewers)}"
            t = time.perf_counter()
            points_store.record_gift(uid, uid, uid, "", 1, "gift", "Replay Gift")
            point_ms.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter()
            stream_ranking.update(str(ranking), uid, "", 1, unique_id=uid)
            rank_ms.append((time.perf_counter() - t) * 1000)
        stream_ranking.flush_all()
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "gifts": gifts,
            "viewers": viewers,
            "elapsed_ms": round(elapsed, 3),
            "gift_db_ms": {
                "p50": round(percentile(point_ms, 0.50), 3),
                "p95": round(percentile(point_ms, 0.95), 3),
                "max": round(max(point_ms, default=0), 3),
            },
            "ranking_ms": {
                "p50": round(percentile(rank_ms, 0.50), 3),
                "p95": round(percentile(rank_ms, 0.95), 3),
                "max": round(max(rank_ms, default=0), 3),
            },
            "points_db_bytes": db.stat().st_size,
            "ranking_bytes": ranking.stat().st_size if ranking.exists() else 0,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gifts", type=int, default=1000)
    parser.add_argument("--viewers", type=int, default=200)
    args = parser.parse_args()
    if args.gifts < 1 or args.viewers < 1:
        parser.error("gifts and viewers must be positive")
    print(json.dumps(run(args.gifts, args.viewers), indent=2))


if __name__ == "__main__":
    main()
