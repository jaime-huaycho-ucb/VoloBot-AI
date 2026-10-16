"""Prueba del micrófono: imprime el nivel una y otra vez en el repl (Ctrl+C para salir).

Uso, con el programa principal detenido (Ctrl+C -> aparece >>>):
    >>> import mic_test

Escala 0..32767 (así lo ve el backend). Habla normal y mira hasta dónde sube:
  - SIN SEÑAL : siempre 0 -> cable OUT/VCC/GND flojo o módulo sin contacto
  - bajo      : < 500, casi no se oye (acércate o sube un poco la ganancia)
  - OK        : 1000 a 20000 al hablar
  - SATURADO  : llega a ~32000 -> baja la ganancia con el tornillito del módulo
"""

import time

from mic import create_microphone

mic = create_microphone()

BAR = 40
FULL = 32767


def _label(peak):
    if peak == 0:
        return "SIN SEÑAL (revisa cables)"
    if peak >= 32000:
        return "SATURADO: baja la ganancia"
    if peak < 500:
        return "bajo"
    return "OK"


def run():
    mic.init()
    print("Prueba de micrófono (Ctrl+C para salir). Habla cerca del módulo.")
    print("nivel  0 %s %d" % ("-" * BAR, FULL))
    top = 0
    try:
        while True:
            mic.read_chunk()  # ~128 ms por bloque a 8 kHz
            mic.read_chunk()
            peak = mic.last_peak
            if peak > top:
                top = peak
            filled = min(BAR, peak * BAR // FULL)
            print("%5d |%s%s| máx %5d  %s" % (peak, "#" * filled, " " * (BAR - filled), top, _label(peak)))
    except KeyboardInterrupt:
        print("\nFin. Nivel máximo visto: %d" % top)


run()
