# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=['D:\\Ikhito\\Code\\TikTokMCIntegrator'],
    binaries=[],
    datas=[('templates', 'templates'), ('static', 'static'), ('addons', 'addons')],
    hiddenimports=[
        'spotipy', 'spotipy.oauth2', 'spotipy.client', 'spotify_handler',
        # Imported only inside minecraft_main.run_bot(), so declare explicitly.
        'reconnect_policy', 'reconnect_diagnostics',
        'edge_tts', 'tts_effects',
        # pywebview native window (Edge WebView2 via pythonnet/WinForms).
        # These are resolved at RUNTIME through the CLR, so PyInstaller can't
        # trace them statically — must be declared (fusion-panel guidance).
        'webview', 'webview.platforms.edgechromium', 'webview.platforms.winforms',
        'webview.platforms.cef', 'webview.platforms.mshtml',
        'clr', 'clr_loader', 'pythonnet',
        # tray + socketio async driver
        'pystray._win32', 'engineio.async_drivers.threading',
        # dynamic import used by optional Gift Animation Downloader
        'assets.gift_assets.downloader', 'assets.gift_assets.manifest',
        # Gift catalog union/sync/backfill. httpx is imported lazily inside
        # gift_catalog_sync so the sync never costs anything when disabled.
        'gift_catalog', 'gift_catalog_sync', 'gift_catalog_backfill', 'httpx',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TikTokMCIntegrator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TikTokMCIntegrator',
)
