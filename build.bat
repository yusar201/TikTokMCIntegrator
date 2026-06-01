@echo off
title TikTokMC Integrator - Safe Build

echo ============================================
echo  TikTokMC Integrator - Safe Build
echo ============================================
echo.

REM Always run from this script's folder.
cd /d "%~dp0"

REM Pick Python. Prefer Windows py launcher, fallback to python.
where py >nul 2>&1
if errorlevel 1 (
    set PY_CMD=python
) else (
    set PY_CMD=py -3
)

echo Using Python command: %PY_CMD%
%PY_CMD% --version
if errorlevel 1 (
    echo.
    echo FAILED: Python was not found.
    echo Install Python or make sure python/py is available in PATH.
    pause
    exit /b 1
)

REM ---- Step 1: Backup release config ----
set RELEASE_DIR=release\TikTokMCIntegrator
set BACKUP_DIR=build_backup

if exist "%RELEASE_DIR%\" (
    echo [1/4] Backing up release config...
    if exist "%BACKUP_DIR%\" rmdir /S /Q "%BACKUP_DIR%" >nul 2>&1
    mkdir "%BACKUP_DIR%" >nul 2>&1
    
    if exist "%RELEASE_DIR%\config.yml" copy "%RELEASE_DIR%\config.yml" "%BACKUP_DIR%\config.yml" >nul
    if exist "%RELEASE_DIR%\profiles\" (
        mkdir "%BACKUP_DIR%\profiles" >nul 2>&1
        copy "%RELEASE_DIR%\profiles\*.yml" "%BACKUP_DIR%\profiles\" >nul 2>&1
    )
    if exist "%RELEASE_DIR%\sounds\" (
        mkdir "%BACKUP_DIR%\sounds" >nul 2>&1
        xcopy "%RELEASE_DIR%\sounds\*" "%BACKUP_DIR%\sounds\" /E /I /Q >nul 2>&1
    )
    if exist "%RELEASE_DIR%\song_config.json" copy "%RELEASE_DIR%\song_config.json" "%BACKUP_DIR%\song_config.json" >nul 2>&1
    if exist "%RELEASE_DIR%\song_queue.json" copy "%RELEASE_DIR%\song_queue.json" "%BACKUP_DIR%\song_queue.json" >nul 2>&1
    if exist "%RELEASE_DIR%\song_history.json" copy "%RELEASE_DIR%\song_history.json" "%BACKUP_DIR%\song_history.json" >nul 2>&1
    if exist "%RELEASE_DIR%\song_spotify_token.json" copy "%RELEASE_DIR%\song_spotify_token.json" "%BACKUP_DIR%\song_spotify_token.json" >nul 2>&1
    echo   OK - Backed up to %BACKUP_DIR%\
) else (
    echo [1/4] No release folder found, skipping backup.
)

REM ---- Step 2: Check dependencies ----
echo [2/4] Checking dependencies...
%PY_CMD% -m pip show spotipy >nul 2>&1
if errorlevel 1 (
    echo   Installing spotipy and requests...
    %PY_CMD% -m pip install "spotipy>=2.24.0" "requests>=2.28.0"
    if errorlevel 1 (
        echo.
        echo   FAILED to install dependencies.
        echo   Try this manually in CMD:
        echo   %PY_CMD% -m pip install "spotipy>=2.24.0" "requests>=2.28.0"
        pause
        exit /b 1
    )
) else (
    echo   OK - spotipy already installed
)

REM ---- Step 3: Build ----
echo [3/4] Building executable...
%PY_CMD% -m PyInstaller TikTokMCIntegrator.spec --noconfirm
if errorlevel 1 (
    echo.
    echo   BUILD FAILED. Check errors above.
    pause
    exit /b 1
)
echo   OK - Build complete

REM ---- Step 4: Deploy + restore ----
echo [4/4] Deploying to release folder...
if exist "%RELEASE_DIR%\" (
    rmdir /S /Q "%RELEASE_DIR%" >nul 2>&1
)
xcopy dist\TikTokMCIntegrator "%RELEASE_DIR%\" /E /I /Q >nul
if errorlevel 1 (
    echo.
    echo   DEPLOY FAILED. Release folder was not copied.
    pause
    exit /b 1
)

REM Restore config/runtime files
if exist "%BACKUP_DIR%\" (
    echo   Restoring config...
    if exist "%BACKUP_DIR%\config.yml" copy "%BACKUP_DIR%\config.yml" "%RELEASE_DIR%\config.yml" /Y >nul 2>&1
    if exist "%BACKUP_DIR%\profiles\" (
        if not exist "%RELEASE_DIR%\profiles\" mkdir "%RELEASE_DIR%\profiles\" >nul 2>&1
        copy "%BACKUP_DIR%\profiles\*.yml" "%RELEASE_DIR%\profiles\" /Y >nul 2>&1
    )
    if exist "%BACKUP_DIR%\sounds\" (
        if not exist "%RELEASE_DIR%\sounds\" mkdir "%RELEASE_DIR%\sounds\" >nul 2>&1
        xcopy "%BACKUP_DIR%\sounds\*" "%RELEASE_DIR%\sounds\" /E /I /Y /Q >nul 2>&1
    )
    if exist "%BACKUP_DIR%\song_config.json" copy "%BACKUP_DIR%\song_config.json" "%RELEASE_DIR%\song_config.json" /Y >nul 2>&1
    if exist "%BACKUP_DIR%\song_queue.json" copy "%BACKUP_DIR%\song_queue.json" "%RELEASE_DIR%\song_queue.json" /Y >nul 2>&1
    if exist "%BACKUP_DIR%\song_history.json" copy "%BACKUP_DIR%\song_history.json" "%RELEASE_DIR%\song_history.json" /Y >nul 2>&1
    if exist "%BACKUP_DIR%\song_spotify_token.json" copy "%BACKUP_DIR%\song_spotify_token.json" "%RELEASE_DIR%\song_spotify_token.json" /Y >nul 2>&1
)
echo   OK - Config restored

echo.
echo ============================================
echo  BUILD COMPLETE
echo  Release: %RELEASE_DIR%\
echo  Backup:  %BACKUP_DIR%\
echo ============================================
echo.
pause
