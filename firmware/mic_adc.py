"""Adaptador del micrófono analógico MAX4466 (ADC del ESP32) a la interfaz Microphone.

Cableado: OUT -> GPIO34 (config.MIC_ADC_PIN), VCC -> 3V3, GND -> GND. El módulo viene sin pines:
hay que soldarlos o el contacto falla.

Muestrea por software a config.MIC_SAMPLE_RATE (8 kHz), así que entre bloques hay pequeños huecos
mientras se envía por WiFi. El backend recibe la frecuencia en la conexión y re-muestrea a 16 kHz.
"""

import time
from array import array
from machine import ADC, Pin

import config
from mic_base import Microphone


class AdcMicrophone(Microphone):
    name = "MAX4466 (ADC)"

    def __init__(self):
        self.sample_rate = config.MIC_SAMPLE_RATE
        self.last_peak = 0
        self._n = config.MIC_CHUNK_SAMPLES
        self._period_us = 1000000 // self.sample_rate
        self._adc = None
        self._raw = array("H", [0] * self._n)
        self._out = array("h", [0] * self._n)

    def init(self):
        self._adc = ADC(Pin(config.MIC_ADC_PIN))
        self._adc.atten(ADC.ATTN_11DB)  # rango completo ~0-3.3 V

    def read_chunk(self):
        """_n muestras PCM 16-bit con signo, mono, sin componente DC."""
        read = self._adc.read_u16
        raw = self._raw
        n = self._n
        t = time.ticks_us()
        for i in range(n):
            raw[i] = read()
            t = time.ticks_add(t, self._period_us)
            while time.ticks_diff(t, time.ticks_us()) > 0:
                pass

        mean = sum(raw) // n  # el MAX4466 sale centrado en ~VCC/2
        out = self._out
        peak = 0
        for i in range(n):
            v = raw[i] - mean
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
        return bytes(out)

    def measure_level(self, samples=400):
        """Pico a pico del ADC en ~50 ms: 0 = sin señal, 100-600 silencio, miles voz, ~65000 saturado."""
        read = self._adc.read_u16
        lo = 65535
        hi = 0
        for _ in range(samples):
            v = read()
            if v < lo:
                lo = v
            if v > hi:
                hi = v
            time.sleep_us(100)
        return hi - lo
