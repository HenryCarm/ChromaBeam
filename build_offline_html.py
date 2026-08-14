"""
ChromaBeam Offline HTML Bundler
Inlines HTML, CSS, JavaScript, and background Web Worker into a single, 100% self-contained offline HTML file.
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

    # JS files for main UI thread in dependency order
    main_js_files = ["fountain.js", "protocol.js", "matrix.js", "vision_engine.js", "sender.js", "receiver.js"]
    combined_js = ""
    for js_file in main_js_files:
        with open(os.path.join(WEB_DIR, js_file), "r", encoding="utf-8") as f:
            combined_js += f"\n/* --- {js_file} --- */\n" + f.read() + "\n"

    # Worker JS files: Dependencies + Worker core
    worker_dep_files = ["fountain.js", "protocol.js", "matrix.js", "vision_engine.js"]
    combined_worker_js = "/* ChromaBeam Standalone Offline Web Worker Engine */\n"
    for dep_file in worker_dep_files:
        with open(os.path.join(WEB_DIR, dep_file), "r", encoding="utf-8") as f:
            combined_worker_js += f"\n/* --- Worker Dep: {dep_file} --- */\n" + f.read() + "\n"

    with open(os.path.join(WEB_DIR, "scanner_worker.js"), "r", encoding="utf-8") as f:
        worker_main = f.read()

    # In bundled mode, skip redundant importScripts if dependencies are already inlined
    worker_main_bundled = worker_main.replace(
        "typeof importScripts === 'function'",
        "typeof importScripts === 'function' && typeof LTDecoder === 'undefined'"
    )
    combined_worker_js += f"\n/* --- scanner_worker.js --- */\n" + worker_main_bundled + "\n"

    # Replace <link rel="stylesheet" href="style.css"> with <style>
    html = html.replace('<link rel="stylesheet" href="style.css">', f"<style>\n{css}\n</style>")

    import re
    # Replace <script src="..."></script> tags with inline script
    for js_file in main_js_files:
        html = re.sub(rf'<script src="{re.escape(js_file)}(\?[^"]*)?"></script>', "", html)

    # Embed worker source as text/plain script tag, followed by main JS
    embedded_payload = (
        f'<script id="scanner-worker-src" type="text/plain">\n{combined_worker_js}\n</script>\n'
        f'<script>\n{combined_js}\n</script>\n'
    )
    html = html.replace("</body>", f"{embedded_payload}</body>")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[ChromaBeam] Successfully bundled offline app -> {OUT_FILE} ({os.path.getsize(OUT_FILE)} bytes)")


if __name__ == '__main__':
    bundle()

