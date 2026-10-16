"""Voz de la respuesta: cola hacia el reproductor del Mac y movimiento de la boca.

Docker en macOS no tiene acceso a los altavoces, así que el backend deja la voz del servidor en una
cola (GET /speaker/next) y un programa pequeño que corre en el Mac, tools/play_replies.py, la
descarga y la reproduce. Mientras suena, la carita del ESP32 mueve la boca con los niveles que se
calculan aquí a partir del mismo audio.
"""

from __future__ import annotations

import asyncio
import io
import time
import wave

import numpy as np

SAMPLE_RATE = 16000
MAX_QUEUED = 3          # si nadie reproduce, no acumular respuestas viejas
PLAYER_SEEN_SECONDS = 60


class SpeakerHub:
    def __init__(self):
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._last_seen = 0.0

    @property
    def player_connected(self) -> bool:
        return time.monotonic() - self._last_seen < PLAYER_SEEN_SECONDS

    def enqueue(self, wav: bytes) -> None:
        while self._queue.qsize() >= MAX_QUEUED:
            self._queue.get_nowait()
        self._queue.put_nowait(wav)

    async def next(self, timeout: float) -> bytes | None:
        self._last_seen = time.monotonic()
        try:
            return await asyncio.wait_for(self._queue.get(), timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._last_seen = time.monotonic()

    def clear(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()


hub = SpeakerHub()


def pcm_to_wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def mouth_levels(pcm: bytes, window_ms: int, rate: int = SAMPLE_RATE) -> list[int]:
    """Una apertura de boca (0 cerrada, 1 media, 2 abierta) por ventana de `window_ms`.

    Se compara el volumen de cada ventana con el de las partes fuertes de la propia respuesta, así
    funciona igual con voces suaves o fuertes. Se suaviza para que la boca no parpadee.
    """
    samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32)
    win = max(1, rate * window_ms // 1000)
    n = (len(samples) + win - 1) // win
    rms = np.array([float(np.sqrt(np.mean(samples[i * win:(i + 1) * win] ** 2))) if len(samples[i * win:(i + 1) * win]) else 0.0
                    for i in range(n)])
    if n == 0 or rms.max() < 150:
        return [0] * n
    ref = float(np.percentile(rms[rms > 150], 90))
    raw = np.where(rms < 150, 0, np.where(rms < 0.30 * ref, 0, np.where(rms < 0.65 * ref, 1, 2))).astype(int)
    out = raw.copy()
    for i in range(1, n - 1):                 # mediana de 3: quita parpadeos de una sola ventana
        out[i] = sorted((raw[i - 1], raw[i], raw[i + 1]))[1]
    return [int(v) for v in out]
