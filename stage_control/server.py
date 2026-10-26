"""Serveur HTTP (stdlib) : API JSON, flux SSE d'état et fichiers statiques de l'interface.

Routes (corps et réponses en JSON) :

    GET    /api/state                     tout l'état pour l'affichage
    GET    /api/events                    flux SSE : événements ``status`` et ``config``
    POST   /api/scenes/<id>/recall
    POST   /api/scenes                    créer  (name, fade_s, states | capture)
    PUT    /api/scenes/<id>               remplacer
    DELETE /api/scenes/<id>
    POST   /api/sequences                 créer  (name, loop, steps)
    PUT    /api/sequences/<id>
    DELETE /api/sequences/<id>
    POST   /api/sequences/<id>/toggle     lancer / arrêter
    POST   /api/sequence/next|prev|stop
    POST   /api/blackout                  {"on": true|false} ; sans corps : bascule
    POST   /api/flash/<scene_id>          {"down": true|false}
    POST   /api/fixtures/<id>/state       champs partiels : rgb, white, amber, intensity, strobe
    POST   /api/pedal/<n>                 {"down": true|false}, n = 1..7 (7 = blackout)
    PUT    /api/settings                  master, default_fade, blackout_fade, flash_fade, pedals

Sans authentification : prévu pour le WiFi fermé de la scène (voir la spécification §9).
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import queue
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, List, Tuple
from urllib.parse import unquote, urlsplit

from .controller import Conflict, Controller

log = logging.getLogger("stage_control.server")

MAX_BODY = 64 * 1024
SSE_PING_S = 15.0

Route = Tuple[str, "re.Pattern", Callable]


def _ok(obj=None, status: int = 200):
    return status, {} if obj is None else obj


def build_routes(c: Controller) -> List[Route]:
    """Table des routes ; chaque fonction reçoit ``(match, body)`` et renvoie ``(statut, objet)``."""
    routes: List[Route] = []

    def route(method: str, pattern: str):
        def deco(fn):
            routes.append((method, re.compile("^" + pattern + "$"), fn))
            return fn
        return deco

    @route("GET", r"/api/state")
    def state(m, body):
        return _ok(c.dump())

    @route("POST", r"/api/scenes/([^/]+)/recall")
    def recall(m, body):
        c.recall(m.group(1))
        return _ok(c.status())

    @route("POST", r"/api/scenes")
    def scene_create(m, body):
        return _ok(c.save_scene(None, body).to_dict(), 201)

    @route("PUT", r"/api/scenes/([^/]+)")
    def scene_put(m, body):
        return _ok(c.save_scene(m.group(1), body).to_dict())

    @route("DELETE", r"/api/scenes/([^/]+)")
    def scene_delete(m, body):
        c.delete_scene(m.group(1))
        return _ok()

    @route("POST", r"/api/sequences")
    def seq_create(m, body):
        return _ok(c.save_sequence(None, body).to_dict(), 201)

    @route("PUT", r"/api/sequences/([^/]+)")
    def seq_put(m, body):
        return _ok(c.save_sequence(m.group(1), body).to_dict())

    @route("DELETE", r"/api/sequences/([^/]+)")
    def seq_delete(m, body):
        c.delete_sequence(m.group(1))
        return _ok()

    @route("POST", r"/api/sequences/([^/]+)/toggle")
    def seq_toggle(m, body):
        if m.group(1) not in c.engine.sequences:
            raise KeyError(m.group(1))
        return _ok({"running": c.toggle_sequence(m.group(1))})

    @route("POST", r"/api/sequence/(next|prev|stop)")
    def seq_nav(m, body):
        {"next": c.next_step, "prev": c.prev_step, "stop": c.stop_sequence}[m.group(1)]()
        return _ok(c.status())

    @route("POST", r"/api/blackout")
    def blackout(m, body):
        on = body.get("on")
        if on is not None and not isinstance(on, bool):
            raise ValueError("« on » doit être un booléen")
        return _ok({"blackout": c.set_blackout(on)})

    @route("POST", r"/api/flash/([^/]+)")
    def flash(m, body):
        if m.group(1) not in c.engine.scenes:
            raise KeyError(m.group(1))
        c.flash(m.group(1), bool(body.get("down", True)))
        return _ok(c.status())

    @route("POST", r"/api/fixtures/([^/]+)/state")
    def fixture_state(m, body):
        return _ok(c.set_fixture(m.group(1), body).to_dict())

    @route("POST", r"/api/pedal/(\d+)")
    def pedal(m, body):
        c.pedal(int(m.group(1)), bool(body.get("down", True)))
        return _ok(c.status())

    @route("PUT", r"/api/settings")
    def settings(m, body):
        return _ok(c.update_settings(body).to_dict())

    return routes


class Handler(BaseHTTPRequestHandler):
    server_version = "stage-control"
    controller: Controller
    routes: List[Route]
    static_dir: str = ""

    def log_message(self, fmt, *args):  # journal discret
        log.debug("%s - %s", self.address_string(), fmt % args)

    # -- réponses ----------------------------------------------------------

    def _send_json(self, status: int, obj) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("corps trop volumineux")
        if length == 0:
            return {}
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("JSON invalide") from None
        if not isinstance(body, dict):
            raise ValueError("un objet JSON est attendu")
        return body

    # -- routage -----------------------------------------------------------

    def _dispatch(self, method: str) -> None:
        path = unquote(urlsplit(self.path).path)
        if method == "GET" and path == "/api/events":
            return self._sse()
        if path.startswith("/api/"):
            for m, pattern, fn in self.routes:
                match = pattern.match(path)
                if m == method and match:
                    try:
                        status, obj = fn(match, self._read_body())
                    except KeyError as exc:
                        return self._error(404, f"introuvable : {exc.args[0]}")
                    except Conflict as exc:
                        return self._error(409, str(exc))
                    except (ValueError, TypeError) as exc:
                        return self._error(400, str(exc))
                    except Exception:
                        log.exception("erreur interne sur %s %s", method, path)
                        return self._error(500, "erreur interne")
                    return self._send_json(status, obj)
            return self._error(404, "route inconnue")
        if method == "GET":
            return self._static(path)
        self._error(405, "méthode non permise")

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    # -- fichiers statiques ------------------------------------------------

    def _static(self, path: str) -> None:
        root = os.path.realpath(self.static_dir) if self.static_dir else ""
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        full = os.path.realpath(os.path.join(root, rel)) if root else ""
        if not root or not (full == root or full.startswith(root + os.sep)) or not os.path.isfile(full):
            return self._error(404, "introuvable")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- SSE ---------------------------------------------------------------

    def _sse(self) -> None:
        bus = self.controller.bus
        q = bus.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self._sse_write("status", self.controller.status(), retry=2000)
            while True:
                try:
                    event, data = q.get(timeout=SSE_PING_S)
                    self._sse_write(event, data)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass  # client parti
        finally:
            bus.unsubscribe(q)

    def _sse_write(self, event: str, data, retry: int = 0) -> None:
        head = f"retry: {retry}\n" if retry else ""
        payload = json.dumps(data, ensure_ascii=False)
        self.wfile.write(f"{head}event: {event}\ndata: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(controller: Controller, host: str = "0.0.0.0", port: int = 8080,
                static_dir: str = "") -> Server:
    handler = type("BoundHandler", (Handler,), {
        "controller": controller, "routes": build_routes(controller), "static_dir": static_dir})
    return Server((host, port), handler)
