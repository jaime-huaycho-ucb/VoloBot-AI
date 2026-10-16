"""Compara los dos micrófonos a la vez para decidir cuál conviene (Ctrl+C para salir).

Con los DOS cableados (MAX4466 en GPIO34 e INMP441 en GPIO32/25/33), detén el programa principal
(Ctrl+C -> >>>) y escribe:
    >>> import mic_compare

Imprime el nivel de cada uno en la escala 0..65535. Habla igual para los dos, a la misma distancia:
  - el que NO se queda en 0 y sube claro al hablar, sin pegarse a ~65000, es el que funciona bien
  - mira también el nivel en silencio: cuanto más bajo y estable, menos ruido tiene
"""

import time

from mic import create_microphone

BAR = 20
FULL = 65535


def _bar(level):
    n = min(BAR, level * BAR // FULL)
    return "#" * n + " " * (BAR - n)


def _flag(level):
    if level == 0:
        return "SIN SEÑAL"
    if level >= 64000:
        return "SATURADO"
    return ""


def run():
    mics = []
    for kind in ("adc", "i2s"):
        try:
            mic = create_microphone(kind)
            mic.init()
            mics.append(mic)
        except Exception as exc:   # un módulo no cableado/soportado no debe impedir probar el otro
            print("No se pudo iniciar %s: %s" % (kind, exc))
    if not mics:
        print("Ningún micrófono disponible.")
        return
    print("Comparación de micrófonos (Ctrl+C para salir). Habla igual para los dos.")
    top = [0] * len(mics)
    try:
        while True:
            parts = []
            for i, mic in enumerate(mics):
                level = mic.measure_level()
                if level > top[i]:
                    top[i] = level
                parts.append("%-14s %5d |%s| %s" % (mic.name, level, _bar(level), _flag(level)))
            print("   ".join(parts))
            time.sleep_ms(100)
    except KeyboardInterrupt:
        print("\nFin. Nivel máximo visto:")
        for mic, t in zip(mics, top):
            print("  %-14s %d" % (mic.name, t))


run()
