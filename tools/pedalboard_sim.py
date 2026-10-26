"""Simulateur de pédalier pour essayer le contrôleur sans matériel.

Il joue le rôle du pédalier : il écoute sur un port TCP, le contrôleur s'y connecte
(``python3 -m stage_control --pedalboard tcp:127.0.0.1:7000``), et on tape des commandes au clavier :

    1 .. 7        appui puis relâchement de la pédale (7 = blackout)
    d N / u N     maintenir (down) / relâcher (up) la pédale N, par exemple « d 4 » pour un flash
    q             quitter

Les LED envoyées par le contrôleur s'affichent : ``[●][ ][ ][ ][ ][ ]  blackout ●``.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading


def show(line: str) -> None:
    try:
        _, slots, bo = line.split()
    except ValueError:
        print("<<", line)
        return
    cells = "".join("[●]" if c == "1" else "[ ]" for c in slots)
    print(f"<< {cells}  blackout {'●' if bo == '1' else '○'}", flush=True)


def reader(conn: socket.socket) -> None:
    buf = b""
    while True:
        try:
            data = conn.recv(256)
        except OSError:
            return
        if not data:
            print("-- le contrôleur s'est déconnecté", flush=True)
            return
        buf += data
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            line = raw.decode("ascii", "replace").strip()
            if line == "WHO":
                conn.sendall(b"HELLO sim 7\n")
            elif line == "PING":
                conn.sendall(b"PONG\n")
            elif line.startswith("LED"):
                show(line)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--port", type=int, default=7000)
    args = p.parse_args()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", args.port))
    srv.listen(1)
    print(f"En attente du contrôleur sur 127.0.0.1:{args.port} …", flush=True)
    conn, _ = srv.accept()
    print("Contrôleur connecté. Commandes : 1-7, d N, u N, q", flush=True)
    threading.Thread(target=reader, args=(conn,), daemon=True).start()
    for raw in sys.stdin:
        cmd = raw.split()
        try:
            if cmd == ["q"]:
                break
            if len(cmd) == 1 and cmd[0].isdigit() and 1 <= int(cmd[0]) <= 7:
                conn.sendall(f"BTN {cmd[0]} 1\nBTN {cmd[0]} 0\n".encode())
            elif len(cmd) == 2 and cmd[0] in ("d", "u") and cmd[1].isdigit() and 1 <= int(cmd[1]) <= 7:
                conn.sendall(f"BTN {cmd[1]} {1 if cmd[0] == 'd' else 0}\n".encode())
            elif cmd:
                print("commande inconnue")
        except OSError:
            print("-- liaison perdue")
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
