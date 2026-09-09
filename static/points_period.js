(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.getPointsPeriodBounds = api.getPointsPeriodBounds;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  function localDate(value) {
    const parts = String(value || '').split('-').map(Number);
    if (parts.length !== 3 || parts.some(Number.isNaN)) return null;
    const date = new Date(parts[0], parts[1] - 1, parts[2]);
    if (date.getFullYear() !== parts[0] || date.getMonth() !== parts[1] - 1 || date.getDate() !== parts[2]) return null;
    return date;
  }

  function startOfDay(value) {
    return new Date(value.getFullYear(), value.getMonth(), value.getDate());
  }

  function addDays(value, days) {
    return new Date(value.getFullYear(), value.getMonth(), value.getDate() + days);
  }

  function seconds(value) {
    return Math.floor(value.getTime() / 1000);
  }

  function customLabel(start, end) {
    const startText = start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const endText = end.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    return `${startText} - ${endText}`;
  }

  function getPointsPeriodBounds(period, startValue, endValue, now) {
    const selected = String(period || 'all');
    const today = startOfDay(now instanceof Date ? now : new Date());
    const tomorrow = addDays(today, 1);

    if (selected === 'all') return { since: null, until: null, label: 'All time' };
    if (selected === 'today') return { since: seconds(today), until: seconds(tomorrow), label: 'Today' };
    if (selected === '3d') return { since: seconds(addDays(today, -2)), until: seconds(tomorrow), label: 'Last 3 days' };
    if (selected === '7d') return { since: seconds(addDays(today, -6)), until: seconds(tomorrow), label: 'Last 7 days' };

    if (selected === 'custom') {
      const start = localDate(startValue);
      const end = localDate(endValue);
      if (!start || !end) return { error: 'Choose both custom dates' };
      if (end < start) return { error: 'End date must be on or after start date' };
      return {
        since: seconds(start),
        until: seconds(addDays(end, 1)),
        label: customLabel(start, end),
      };
    }

    return { since: null, until: null, label: 'All time' };
  }

  return { getPointsPeriodBounds };
});
