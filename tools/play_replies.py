#!/usr/bin/env python3
"""Reproduce en este equipo la voz de las respuestas del bot.

El backend corre en Docker y Docker en macOS no tiene acceso a los altavoces, así que deja la voz
de cada respuesta en una cola (GET /speaker/next). Este programa se queda pidiéndola y la reproduce.
Solo usa la librería estándar de Python; en macOS reproduce con `afplay` (ya viene instalado).

Uso (en otra terminal, en tu Mac, mientras corre el backend):
    python3 tools/play_replies.py
    python3 tools/play_replies.py --url http://192.168.0.10:8000      # backend en otro equipo
    python3 tools/play_replies.py --dry-run                           # baja el audio pero no suena

Ctrl+C para salir.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_token():
    """Lee DEVICE_TOKEN de backend/.env para no tener que escribirlo."""
    try:
        with open(os.path.join(ROOT, "backend", ".env"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("DEVICE_TOKEN="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return "volobot-secret-2026"


def find_player():
    for cmd in (["afplay"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"], ["aplay", "-q"], ["paplay"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def duration(path):
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, OSError):
        return 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000", help="dirección del backend")
    parser.add_argument("--token", default=default_token(), help="DEVICE_TOKEN (por defecto, el de backend/.env)")
    parser.add_argument("--dry-run", action="store_true", help="descarga el audio pero no lo reproduce")
    args = parser.parse_args()

    player = None if args.dry_run else find_player()
    if not args.dry_run and player is None:
        sys.exit("No encuentro un reproductor de audio (afplay, ffplay, aplay, paplay). Usa --dry-run para probar sin sonido.")

    print("Reproductor de respuestas listo. Esperando la voz del bot en %s (Ctrl+C para salir)" % args.url)
    waiting_msg = False
    while True:
        try:
            req = urllib.request.Request("%s/speaker/next?wait=25&token=%s" % (args.url.rstrip("/"), args.token))
            with urllib.request.urlopen(req, timeout=40) as resp:
                if resp.status == 204:
                    continue
                data = resp.read()
            waiting_msg = False
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                sys.exit("El backend rechazó el token (401). Revisa DEVICE_TOKEN en backend/.env o usa --token.")
            print("Error del backend: %s. Reintento en 3 s..." % exc)
            time.sleep(3)
            continue
        except (urllib.error.URLError, OSError) as exc:
            if not waiting_msg:
                print("Sin conexión con el backend (%s). Reintento cada 3 s..." % getattr(exc, "reason", exc))
                waiting_msg = True
            time.sleep(3)
            continue
        except KeyboardInterrupt:
            print("\nFin.")
            return

        fd, path = tempfile.mkstemp(suffix=".wav", prefix="volobot_")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            secs = duration(path)
            if args.dry_run:
                print("(dry-run) llegó una respuesta de voz de %.1f s (%d bytes); no se reproduce" % (secs, len(data)))
            else:
                print("▶ reproduciendo respuesta (%.1f s)" % secs)
                try:
                    subprocess.run(player + [path], check=False)
                except KeyboardInterrupt:
                    print("\nFin.")
                    return
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nFin.")
