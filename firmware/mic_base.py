"""Interfaz común de los micrófonos (patrón Adapter: es el "Target").

main.py solo conoce esta interfaz. Cada hardware tiene su adaptador que la implementa:
    mic_adc.AdcMicrophone   MAX4466 analógico (ADC, GPIO34)
    mic_i2s.I2sMicrophone   INMP441 digital (I2S)
y mic.create_microphone() elige cuál usar según config.MIC_TYPE.

Para agregar otro micrófono basta con una clase nueva que herede de Microphone.
"""


class Microphone:
    name = "base"        # nombre legible, para los mensajes del repl
    sample_rate = 16000  # Hz del audio que devuelve read_chunk()
    last_peak = 0        # máximo |muestra| del último bloque leído (16 bits; 0 = sin señal)

    def init(self):
        """Configura el hardware. Se llama una vez antes de leer."""
        raise NotImplementedError

    def read_chunk(self):
        """Bloquea hasta tener un bloque y lo devuelve como bytes: PCM 16-bit con signo, mono,
        a self.sample_rate. Actualiza self.last_peak. Devuelve None si no hay datos."""
        raise NotImplementedError

    def flush(self):
        """Descarta audio viejo acumulado (se llama al empezar a grabar). Por defecto no hace nada."""

    def measure_level(self):
        """Nivel actual en la escala 0..65535: 0 = sin señal, cientos = silencio, miles = voz."""
        raise NotImplementedError
