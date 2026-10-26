#!/usr/bin/env python3
"""Mini serveur « faux internet » : répond HTTP 204 à tout GET sur le port 80.

Les tests de connectivité d'Android (``/generate_204``) attendent un 204 ;
iOS/macOS (``captive.apple.com``) attendent une page « Success ». On répond
donc 204 sur les chemins ``generate_204``/``gen_204`` et la page Apple
ailleurs. À associer à une redirection DNS sur l'Opal (voir ``opal.md``).
Efficacité non garantie selon les versions d'Android **(à vérifier)**.
"""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer

APPLE_BODY = b"<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"


class Handler(BaseHTTPRequestHandler):
    def _respond(self, body=True):
        path = self.path.lower()
        if "generate_204" in path or "gen_204" in path:
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(APPLE_BODY)))
        self.end_headers()
        if body:
            self.wfile.write(APPLE_BODY)

    def do_GET(self):
        self._respond()

    def do_HEAD(self):
        self._respond(body=False)

    def log_message(self, fmt, *args):
        pass


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bind", default="0.0.0.0")
    p.add_argument("--port", type=int, default=80)
    a = p.parse_args()
    HTTPServer((a.bind, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
