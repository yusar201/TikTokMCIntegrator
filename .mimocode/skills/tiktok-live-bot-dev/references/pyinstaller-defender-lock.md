# Windows Defender Locks PyInstaller dist/ Folder

## Symptom
PyInstaller build fails with "The process cannot access the file because it is being used by another process" when trying to delete or write to `dist/TikTokMCIntegrator/`. The folder appears empty but cannot be deleted, renamed, or overwritten.

## Root Cause
Windows Defender Real-Time Protection scans files PyInstaller creates in the dist/ output folder. After the build completes, Defender holds a file handle on the directory itself (not individual files). This lock persists even after:
- Killing all Python/PyInstaller processes
- Restarting Windows Explorer
- Stopping Windows Search service

The lock is held by `Microsoft Defender Antivirus Service` (MsMpEng.exe). It typically releases after 1-5 minutes, but can persist longer for large builds.

## Diagnosis
```powershell
# Confirm the folder is empty but locked
Get-ChildItem -Path 'D:\Ikhito\Code\TikTokMCIntegrator\dist\TikTokMCIntegrator' -Force
# Returns 0 items, but Remove-Item still fails

# Verify no Python processes are running
tasklist /FI 'IMAGENAME eq python*' /FO TABLE
```

## Solutions (in order of preference)

### 1. Add Defender Exclusion (permanent fix, requires Admin)
```powershell
# Run PowerShell as Administrator
Add-MpPreference -ExclusionPath 'D:\Ikhito\Code\TikTokMCIntegrator\dist'
```
Or via GUI: Windows Security > Virus & threat protection > Manage settings > Exclusions > Add folder > `D:\Ikhito\Code\TikTokMCIntegrator`

### 2. Temporarily disable Real-Time Protection
Windows Security > Virus & threat protection > Manage settings > toggle OFF "Real-time protection" > build > toggle back ON

### 3. Build script fallback (rename if delete fails)
Updated `build.bat` clean step:
```bat
echo [2/4] Cleaning previous builds...
if exist dist\TikTokMCIntegrator_old rmdir /s /q dist\TikTokMCIntegrator_old
if exist dist\TikTokMCIntegrator (
  rmdir /s /q dist\TikTokMCIntegrator 2>nul
  if exist dist\TikTokMCIntegrator (
    echo Folder locked, renaming old build...
    ren dist\TikTokMCIntegrator TikTokMCIntegrator_old 2>nul
    if exist dist\TikTokMCIntegrator (
      echo WARNING: Could not clean old build. Close any programs using dist\TikTokMCIntegrator and retry.
      pause
      exit /b 1
    )
  )
)
if exist build rmdir /s /q build
echo Done.
```
This renames the locked folder (Windows allows renaming even when delete is blocked) so PyInstaller can create a fresh one.

### 4. Run build.bat as Administrator
Admin privileges override most Defender locks. Right-click > Run as administrator.

## Why Explorer restart doesn't help
Unlike thumbnail/shell-extension locks (which Explorer restart fixes), Defender locks are held by a kernel-level service. Restarting Explorer has no effect.

## Related
- `references/pyinstaller-path-resolution.md` — different PyInstaller issue (`__file__` resolves to `_internal/` in frozen exe)
