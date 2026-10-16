"""Adaptador del micrófono digital INMP441 (I2S) a la interfaz Microphone.

Cableado: VDD -> 3V3 (nunca 5V), GND -> GND, L/R -> GND (canal izquierdo), SCK -> GPIO32,
WS -> GPIO25, SD -> GPIO33. La placa viene sin pines: hay que soldarla.

El INMP441 entrega 24 bits en una ranura de 32, así que se lee en 32 bits y se baja a 16 con un
desplazamiento (config.MIC_I2S_SHIFT): 16 = los 16 bits altos tal cual; cada punto menos duplica el
volumen (9 = x128). El audio sale a 16 kHz, continuo y sin huecos (lo captura el hardware por DMA).

Requiere una build de MicroPython para ESP32 con machine.I2S (las genéricas desde ~v1.19).
"""

from array import array
from machine import I2S, Pin

import config
from mic_base import Microphone

_IBUF_CHUNKS = 4


class I2sMicrophone(Microphone):
    name = "INMP441 (I2S)"

    def __init__(self):
        self.sample_rate = config.AUDIO_SAMPLE_RATE
        self.last_peak = 0
        self._n = config.MIC_CHUNK_SAMPLES
        self._i2s = None
        self._raw = array("i", [0] * self._n)   # muestras de 32 bits tal como salen del I2S
        self._out = array("h", [0] * self._n)   # muestras de 16 bits listas para mandar

    def init(self):
        self._i2s = I2S(
            0,
            sck=Pin(config.MIC_SCK_PIN),
            ws=Pin(config.MIC_WS_PIN),
            sd=Pin(config.MIC_SD_PIN),
            mode=I2S.RX,
            bits=32,
            format=I2S.MONO,   # solo el canal izquierdo (L/R a GND)
            rate=self.sample_rate,
            ibuf=self._n * 4 * _IBUF_CHUNKS,
        )

    def read_chunk(self):
        """Bloque PCM 16-bit mono a 16 kHz (bloquea hasta tenerlo); None si no hay datos."""
        got = self._i2s.readinto(self._raw)
        if not got:
            return None
        count = got // 4
        shift = config.MIC_I2S_SHIFT
        raw = self._raw
        out = self._out
        peak = 0
        for i in range(count):
            v = raw[i] >> shift
            if v > 32767:
                v = 32767
            elif v < -32768:
                v = -32768
            out[i] = v
            if v < 0:
                v = -v
            if v > peak:
                peak = v
        self.last_peak = peak
        data = bytes(out)
        return data if count == self._n else data[:count * 2]

    def flush(self):
        """Descarta el audio que el I2S haya acumulado (al empezar a grabar)."""
        for _ in range(_IBUF_CHUNKS + 1):
            self._i2s.readinto(self._raw)

    def measure_level(self, chunks=4):
        """Pico más alto de ~0,25 s en la escala 0..65535 (el doble del pico de 16 bits)."""
        self.flush()   # datos frescos, no los de hace unos segundos
        top = 0
        for _ in range(chunks):
            self.read_chunk()
            if self.last_peak > top:
                top = self.last_peak
        return min(65535, top * 2)
