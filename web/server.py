"""
ChromaBeam Threaded HTTPS Server
Serves static assets over HTTPS with concurrent request handling for mobile devices.
"""

import http.server
import ssl
import socket
import os
import sys
import functools

PORT = 8443
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
CERT_FILE = os.path.join(DIRECTORY, "cert", "cert.pem")
KEY_FILE = os.path.join(DIRECTORY, "cert", "key.pem")


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


def run():
    handler_class = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIRECTORY)
    server = http.server.ThreadingHTTPServer(('0.0.0.0', PORT), handler_class)

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
    server.socket = ssl_context.wrap_socket(server.socket, server_side=True)

    ip = get_local_ip()
    print(f"\n[ChromaBeam] Threaded HTTPS Server is RUNNING at: https://{ip}:{PORT}/\n", flush=True)
    server.serve_forever()


if __name__ == '__main__':
    run()
