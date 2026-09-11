#!/usr/bin/env python3
"""Generate all icon assets for the TikTokMCIntegrator desktop shell from one source PNG.

Produces:
  - icon.ico          multi-size, referenced in TikTokMCIntegrator.spec EXE block (icon='icon.ico')
  - static/logo.png   256px, loaded by pystray for the tray icon
  - .logo_datauri.txt  base64 data URI to inline into templates/splash.html

Run with the Windows Python that has PIL:
  C:\Python313\python.exe scripts/make_icons.py "C:\\Users\\yusar\\Downloads\\logo (2).png"
"""
import sys, os, io, base64
from PIL import Image

PROJ = r"D:\Ikhito\Code\TikTokMCIntegrator"

def main(src):
    img = Image.open(src).convert("RGBA")
    print("source:", img.size, img.mode)

    ico = os.path.join(PROJ, "icon.ico")
    img.save(ico, format="ICO", sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    print("ICO:", ico, os.path.getsize(ico))

    os.makedirs(os.path.join(PROJ, "static"), exist_ok=True)
    logo = os.path.join(PROJ, "static", "logo.png")
    img.resize((256,256), Image.LANCZOS).save(logo, format="PNG")
    print("PNG:", logo, os.path.getsize(logo))

    buf = io.BytesIO()
    img.resize((200,200), Image.LANCZOS).save(buf, format="PNG")
    datauri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    out = os.path.join(PROJ, ".logo_datauri.txt")
    with open(out, "w") as f:
        f.write(datauri)
    print("data URI written to", out, "len", len(datauri))
    print("\nNow inject into splash.html, e.g.:")
    print("  re.sub(r'<div class=\"diamond\"[^>]*>.*?</div>', new_block_with_img, html, count=1, flags=re.DOTALL)")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yusar\Downloads\logo (2).png")
