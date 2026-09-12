#!/bin/bash
# TikTokMCIntegrator — Safe build + deploy to release/ ROOT
# Khito only ever needs to run this. Click release/TikTokMCIntegrator.exe to launch.
#
# Rules:
#   - Deploy to release/ ROOT (NOT release/TikTokMCIntegrator/)
#   - Preserve runtime state: release/{config/,data/,logs/,assets/,addons/} + legacy root runtime files
#   - Replace deployable artifacts only: exe/_internal/templates/static; merge bundled addons without deleting user addons
#   - Never rm -rf release/ — only the artifacts/subdirs we're replacing
#
# Modes:
#   ./deploy.sh          Auto: full PyInstaller build only when backend/spec changed; otherwise fast static/template deploy
#   ./deploy.sh --full   Force full PyInstaller build
#   ./deploy.sh --fast   Force static/template deploy from source into release + release/_internal

set -euo pipefail
cd "$(dirname "$0")"

RELEASE="release"
DIST="dist/TikTokMCIntegrator"
NEW_TS=$(date +%s)
MODE="auto"
if [ "${1:-}" = "--full" ]; then MODE="full"; fi
if [ "${1:-}" = "--fast" ]; then MODE="fast"; fi

WIN_PY="${PYTHON_EXE:-/mnt/c/Python313/python.exe}"

run_win_python() {
    if [ -x "$WIN_PY" ]; then
        "$WIN_PY" "$@"
    else
        cmd.exe /c "py -3 $*"
    fi
}

latest_mtime() {
    # Print latest mtime among existing paths/globs. Returns 0 if nothing matched.
    python3 - "$@" <<'PY'
import glob, os, sys
latest = 0
for pattern in sys.argv[1:]:
    for root in glob.glob(pattern, recursive=True):
        if not os.path.exists(root):
            continue
        if os.path.isdir(root):
            for dirpath, dirnames, filenames in os.walk(root):
                parts = set(os.path.normpath(dirpath).split(os.sep))
                if parts & {'.git', 'dist', 'build', 'release', 'release_test', '__pycache__'}:
                    continue
                try:
                    latest = max(latest, int(os.path.getmtime(dirpath)))
                except OSError:
                    pass
                for name in filenames:
                    path = os.path.join(dirpath, name)
                    try:
                        latest = max(latest, int(os.path.getmtime(path)))
                    except OSError:
                        pass
        else:
            try:
                latest = max(latest, int(os.path.getmtime(root)))
            except OSError:
                pass
print(latest)
PY
}

needs_full_build() {
    [ "$MODE" = "full" ] && return 0
    [ "$MODE" = "fast" ] && return 1
    [ ! -f "$DIST/TikTokMCIntegrator.exe" ] && return 0
    [ ! -d "$DIST/_internal" ] && return 0

    local dist_ts src_ts
    dist_ts=$(stat -c %Y "$DIST/TikTokMCIntegrator.exe")
    # Backend/build inputs only. templates/static are handled by fast deploy.
    src_ts=$(latest_mtime "*.py" "routes/**/*.py" "assets/**/*.py" "gift_assets/**/*.py" "addons/**/*.py" "addons/**/*.yml" "addons/**/*.yaml" "*.spec" "requirements.txt" "config.example.yml" "icon.ico" "build.bat")
    [ "$src_ts" -gt "$dist_ts" ]
}

print_preserved_state() {
    mkdir -p "$RELEASE"
    local PRESERVED=""
    for d in config data logs assets addons; do
        [ -d "$RELEASE/$d" ] && PRESERVED="$PRESERVED $d/"
    done
    for f in config.yml active_profile.txt active_streaks.json available_gifts.json \
             song_config.json song_queue.json song_history.json \
             song_spotify_token.json song_feedback.json song_blocked_uris.json \
             superfan_log.json stream_state.json tts_config.json tts_history.json \
             tts_debug.log coin_goal.json viewer_stats.json gift_log.json \
             follow_log.json chat_log.json sim_console.log; do
        [ -f "$RELEASE/$f" ] && PRESERVED="$PRESERVED $f"
    done
    for d in profiles sounds tts reports gift_assets; do
        [ -d "$RELEASE/$d" ] && PRESERVED="$PRESERVED $d/"
    done
    echo "  Preserved:$PRESERVED"
}

copy_templates_static_from_source() {
    mkdir -p "$RELEASE/_internal"
    rm -rf "$RELEASE/templates" "$RELEASE/static" \
           "$RELEASE/_internal/templates" "$RELEASE/_internal/static"
    cp -r templates "$RELEASE/templates"
    cp -r static "$RELEASE/static"
    cp -r templates "$RELEASE/_internal/templates"
    cp -r static "$RELEASE/_internal/static"
}

copy_bundled_addons_from_source() {
    # Merge bundled source add-ons into both runtime-visible locations without
    # deleting user-installed add-ons from release/addons.
    mkdir -p "$RELEASE/addons" "$RELEASE/_internal/addons"
    if [ -d "addons" ]; then
        find addons -mindepth 1 -maxdepth 1 -type d -print0 | while IFS= read -r -d '' addon_dir; do
            cp -r "$addon_dir" "$RELEASE/addons/"
            cp -r "$addon_dir" "$RELEASE/_internal/addons/"
        done
    fi
}

copy_full_dist_to_release() {
    if [ ! -f "$DIST/TikTokMCIntegrator.exe" ] || [ ! -d "$DIST/_internal" ]; then
        echo "dist/ missing exe or _internal — build broken"
        exit 1
    fi
    if powershell.exe -NoProfile -Command \
        'if (Get-CimInstance Win32_Process | Where-Object { $_.Name -eq "TikTokMCIntegrator.exe" }) { exit 0 } else { exit 1 }' \
        >/dev/null 2>&1; then
        echo "DEPLOY BLOCKED: release/TikTokMCIntegrator.exe is running. Close it before --full deploy."
        echo "No release artifacts were modified."
        exit 1
    fi
    rm -rf "$RELEASE/_internal" "$RELEASE/templates" "$RELEASE/static"
    cp -f "$DIST/TikTokMCIntegrator.exe" "$RELEASE/TikTokMCIntegrator.exe"
    cp -r "$DIST/_internal" "$RELEASE/_internal"
    cp -r "$DIST/_internal/templates" "$RELEASE/templates"
    cp -r "$DIST/_internal/static" "$RELEASE/static"
    rm -rf "$RELEASE/TikTokMCIntegrator"
}

verify_common() {
    for f in templates static _internal/templates _internal/static; do
        if [ ! -e "$RELEASE/$f" ]; then
            echo "  MISSING: $RELEASE/$f"
            exit 1
        fi
    done
    local tpl_ts stc_ts itpl_ts istc_ts
    tpl_ts=$(stat -c %Y "$RELEASE/templates/index.html")
    stc_ts=$(stat -c %Y "$RELEASE/static/script.js")
    itpl_ts=$(stat -c %Y "$RELEASE/_internal/templates/index.html")
    istc_ts=$(stat -c %Y "$RELEASE/_internal/static/script.js")
    if [ "$tpl_ts" -lt $((NEW_TS - 60)) ] || \
       [ "$stc_ts" -lt $((NEW_TS - 60)) ] || \
       [ "$itpl_ts" -lt $((NEW_TS - 60)) ] || \
       [ "$istc_ts" -lt $((NEW_TS - 60)) ]; then
        echo "  WARNING: templates/static not refreshed (timestamps too old)"
        exit 1
    fi
    if [ -d "addons/oneblock" ] && [ ! -e "$RELEASE/addons/oneblock/addon.yml" ]; then
        echo "  WARNING: OneBlock add-on not refreshed"
        exit 1
    fi
    if [ -d "addons/survival_rush" ] && { [ ! -e "$RELEASE/addons/survival_rush/addon.yml" ] || [ ! -e "$RELEASE/_internal/addons/survival_rush/addon.yml" ]; }; then
        echo "  WARNING: Survival Rush add-on not refreshed in both release locations"
        exit 1
    fi
}

verify_full() {
    for f in TikTokMCIntegrator.exe _internal templates static; do
        if [ ! -e "$RELEASE/$f" ]; then
            echo "  MISSING: $RELEASE/$f"
            exit 1
        fi
    done
    verify_common
    local exe_ts int_ts
    exe_ts=$(stat -c %Y "$RELEASE/TikTokMCIntegrator.exe")
    int_ts=$(stat -c %Y "$RELEASE/_internal")
    if [ "$exe_ts" -lt $((NEW_TS - 60)) ] || [ "$int_ts" -lt $((NEW_TS - 60)) ]; then
        echo "  WARNING: exe/_internal not refreshed (timestamps too old)"
        exit 1
    fi
    test ! -d "$RELEASE/TikTokMCIntegrator" || { echo "  WARNING: nested release artifact exists"; exit 1; }
}

echo "============================================"
echo " TikTokMCIntegrator — Smart Deploy"
echo "============================================"

FULL_BUILD=0
if needs_full_build; then FULL_BUILD=1; fi

if [ "$FULL_BUILD" -eq 1 ]; then
    echo "[1/4] Building executable (backend/spec changed or --full)..."
    run_win_python -m PyInstaller TikTokMCIntegrator.spec --noconfirm >/dev/null 2>&1 || {
        echo "BUILD FAILED"
        exit 1
    }
    echo "  OK — dist ready"
else
    echo "[1/4] Skipping PyInstaller build (frontend/static-only deploy)..."
    if [ ! -f "$RELEASE/TikTokMCIntegrator.exe" ] && [ ! -f "$DIST/TikTokMCIntegrator.exe" ]; then
        echo "  No existing exe found — rerun with ./deploy.sh --full"
        exit 1
    fi
fi

echo "[2/4] Preserving runtime state in $RELEASE/..."
print_preserved_state

echo "[3/4] Deploying to $RELEASE/ ROOT..."
if [ "$FULL_BUILD" -eq 1 ]; then
    copy_full_dist_to_release
else
    copy_templates_static_from_source
fi
copy_bundled_addons_from_source

echo "[4/4] Verifying..."
if [ "$FULL_BUILD" -eq 1 ]; then
    verify_full
else
    verify_common
fi

echo ""
echo "============================================"
if [ "$FULL_BUILD" -eq 1 ]; then
    echo " FULL BUILD + DEPLOY COMPLETE"
else
    echo " FAST STATIC/TEMPLATE DEPLOY COMPLETE"
fi
echo " Run:  $RELEASE/TikTokMCIntegrator.exe"
echo "============================================"
