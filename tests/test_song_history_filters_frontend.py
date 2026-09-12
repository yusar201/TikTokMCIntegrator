import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_song_history_controls_and_cache_busted_module_exist():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="song-history-viewer"' in html
    assert 'id="song-history-date"' in html
    assert 'id="song-history-sort"' in html
    assert 'id="song-history-count"' in html
    assert '/static/song_history_filters.js?v=1' in html


def test_song_history_filter_module_filters_and_sorts_without_network_work():
    script = r'''
const f = require('./static/song_history_filters.js');
const history = [
  {track_name:'Zed', requested_by:'Alice', completed_at:1722558600},
  {track_name:'Alpha', requested_by:'bob', completed_at:1722470400},
  {track_name:'Beta', requested_by:'alice2', completed_at:1722555000}
];
const day = f.localDateKey(1722558600);
const filtered = f.filterAndSortSongHistory(history, {viewer:'ALI', date:day, sort:'oldest'});
if (filtered.length !== 2 || filtered[0].track_name !== 'Beta' || filtered[1].track_name !== 'Zed') process.exit(1);
const byViewer = f.filterAndSortSongHistory(history, {viewer:'', date:'', sort:'viewer'});
if (byViewer.map(x => x.requested_by).join(',') !== 'Alice,alice2,bob') process.exit(2);
console.log(JSON.stringify({filtered: filtered.length, total: history.length}));
'''
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"filtered": 2, "total": 3}


def test_history_rendering_uses_all_retained_entries_and_played_timestamp():
    js = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
    assert "history.slice(0, 20)" not in js
    assert "completed_at" in js
    assert "filterAndSortSongHistory" in js
