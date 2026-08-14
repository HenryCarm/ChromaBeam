"""
ChromaBeam Secure HTTPS & LAN Server
Serves over HTTPS to enable camera/microphone permissions in mobile Chrome, Brave, Safari, and Samsung Internet.
"""

import http.server
import socketserver
import ssl
import socket
import os
import sys

PORT = 8443
HTTP_PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
CERT_DIR = os.path.join(DIRECTORY, "cert")
CERT_FILE = os.path.join(CERT_DIR, "cert.pem")
KEY_FILE = os.path.join(CERT_DIR, "key.pem")


def get_local_ip() -> str:
    """Returns local LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def log_message(self, format, *args):
        print(f"[ChromaBeam Server] {args[0]} - {args[1]}")


def run_https_server(port: int = PORT):
    local_ip = get_local_ip()
    server_address = ('0.0.0.0', port)
    
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(server_address, Handler)

    # SSL Context
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        proto = "https"
    else:
        proto = "http"

    print("\n" + "=" * 65)
    print("  ⚡ CHROMABEAM SECURE OPTICAL FILE TRANSFER SERVER ⚡")
    print("=" * 65)
    print(f"  • Secure Mobile / LAN Link:   {proto}://{local_ip}:{port}")
    print(f"  • Local Machine Link:         {proto}://localhost:{port}")
    print("=" * 65)
    print("  📱 Open the link on your phone in Chrome / Samsung Internet / Safari.")
    print("  ⚠️  Because this uses a local self-signed certificate:")
    print("     Tap 'Advanced' -> 'Proceed to site (unsafe)' once.")
    print("  📸 Then tap 'Start Camera Receiver' — camera will activate instantly!")
    print("=" * 65 + "\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[ChromaBeam] Server stopped.")


if __name__ == '__main__':
    p = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run_https_server(p)
