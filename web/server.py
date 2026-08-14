"""
ChromaBeam LAN Web Server
Serves the web client to mobile phones and PCs on the local network.
"""

import http.server
import socketserver
import socket
import os
import sys

PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))


def get_local_ip() -> str:
    """Returns local LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't actually have to be reachable
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
        # Keep console output clean
        pass


def run_server(port: int = PORT):
    local_ip = get_local_ip()
    server_address = ('0.0.0.0', port)
    
    # Allow address reuse
    socketserver.TCPServer.allow_reuse_address = True
    
    with socketserver.TCPServer(server_address, Handler) as httpd:
        print("\n" + "=" * 60)
        print("  ⚡ CHROMABEAM UNIVERSAL OPTICAL FILE TRANSFER SERVER ⚡")
        print("=" * 60)
        print(f"  • Local Machine:    http://localhost:{port}")
        print(f"  • Mobile / LAN:     http://{local_ip}:{port}")
        print("=" * 60)
        print("  📱 Open the Mobile/LAN link on your Android/iPhone browser")
        print("     to use the camera receiver with zero installation!")
        print("  Press Ctrl+C to stop server.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[ChromaBeam] Server stopped.")


if __name__ == '__main__':
    p = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run_server(p)
