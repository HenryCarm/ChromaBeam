"""
ChromaBeam Offline HTML Bundler
Inlines HTML, CSS, and JavaScript into a single, 100% self-contained offline HTML file.
Requires zero server, zero internet, and zero LAN connection — works in pure airplane mode.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
OUT_FILE = os.path.join(BASE_DIR, "chromabeam_offline.html")


def bundle():
    with open(os.path.join(WEB_DIR, "index.html"), "r", encoding="utf-8") as f:
        html = f.read()

    with open(os.path.join(WEB_DIR, "style.css"), "r", encoding="utf-8") as f:
        css = f.read()

    # JS files in dependency order
    js_files = ["fountain.js", "protocol.js", "matrix.js", "vision_engine.js", "sender.js", "receiver.js"]
    combined_js = ""
    for js_file in js_files:
        with open(os.path.join(WEB_DIR, js_file), "r", encoding="utf-8") as f:
            combined_js += f"\n/* --- {js_file} --- */\n" + f.read() + "\n"

    # Replace <link rel="stylesheet" href="style.css"> with <style>
    html = html.replace('<link rel="stylesheet" href="style.css">', f"<style>\n{css}\n</style>")

    # Replace <script src="..."></script> tags with inline script
    for js_file in js_files:
        html = html.replace(f'<script src="{js_file}"></script>', "")

    html = html.replace("</body>", f"<script>\n{combined_js}\n</script>\n</body>")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[ChromaBeam] Successfully bundled offline app -> {OUT_FILE} ({os.path.getsize(OUT_FILE)} bytes)")


if __name__ == '__main__':
    bundle()
