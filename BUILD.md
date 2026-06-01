How to build after this session:

Option 1: Safe build (recommended)
  Open D:\Ikhito\Code\TikTokMCIntegrator\ in File Explorer
  Double-click build.bat

Option 2: Manual
  Open CMD in D:\Ikhito\Code\TikTokMCIntegrator  python -m PyInstaller TikTokMCIntegrator.spec --noconfirm
  Then copy dist\* to release\ (but restore config.yml + profiles\ first!)
