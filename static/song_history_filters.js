(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.SongHistoryFilters = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  function localDateKey(timestampSeconds) {
    const seconds = Number(timestampSeconds || 0);
    if (!seconds) return '';
    const date = new Date(seconds * 1000);
    if (Number.isNaN(date.getTime())) return '';
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function filterAndSortSongHistory(history, options) {
    const opts = options || {};
    const viewer = String(opts.viewer || '').trim().toLocaleLowerCase();
    const date = String(opts.date || '');
    const sort = String(opts.sort || 'newest');
    const rows = Array.isArray(history) ? history.slice() : [];

    const filtered = rows.filter(entry => {
      const requester = String(entry.requested_by || '').toLocaleLowerCase();
      const playedAt = Number(entry.completed_at || entry.requested_at || 0);
      return (!viewer || requester.includes(viewer)) && (!date || localDateKey(playedAt) === date);
    });

    const playedAt = entry => Number(entry.completed_at || entry.requested_at || 0);
    filtered.sort((a, b) => {
      if (sort === 'oldest') return playedAt(a) - playedAt(b);
      if (sort === 'viewer') return String(a.requested_by || '').localeCompare(String(b.requested_by || ''), undefined, {sensitivity: 'base'});
      if (sort === 'song') return String(a.track_name || '').localeCompare(String(b.track_name || ''), undefined, {sensitivity: 'base'});
      return playedAt(b) - playedAt(a);
    });
    return filtered;
  }

  return { localDateKey, filterAndSortSongHistory };
});
