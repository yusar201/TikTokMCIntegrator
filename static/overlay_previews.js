(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.OverlayPreviewManager = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const STORAGE_KEY = 'tiktokmc.overlayPreviews.v1';

  function readSettings(storage) {
    try {
      const raw = storage && storage.getItem(STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function isEnabled(type, storage) {
    return readSettings(storage)[type] === true;
  }

  function setEnabled(type, enabled, storage) {
    const settings = readSettings(storage);
    settings[type] = enabled === true;
    try {
      if (storage) storage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch (_) {
      // Storage can be unavailable in hardened/private WebView2 profiles.
    }
    return settings[type];
  }

  function buildPreviewUrl(overlayUrl) {
    return overlayUrl + (overlayUrl.includes('?') ? '&' : '?') + 'preview=true';
  }

  function syncFrame(type, frame, overlayUrl, panelActive, storage) {
    if (!frame) return false;
    const shouldRun = panelActive === true && isEnabled(type, storage);
    const target = shouldRun ? buildPreviewUrl(overlayUrl) : 'about:blank';
    if (frame.src !== target) frame.src = target;
    return shouldRun;
  }

  return {
    STORAGE_KEY,
    readSettings,
    isEnabled,
    setEnabled,
    buildPreviewUrl,
    syncFrame,
  };
});
