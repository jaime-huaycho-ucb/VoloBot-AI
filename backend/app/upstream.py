"""Conexión de este backend (como "dispositivo") con el servidor real de DarkoSync.

Protocolo del servidor (ver especificacion_equipo_iot_esp32.md, sección 4):
  hacia el servidor : {"action":"START_SPEECH"} + frames PCM 16 kHz/16-bit/mono
                      + {"action":"END_SPEECH","device_id":"..."} + {"action":"PING"}
  desde el servidor : JSON (STATE, SHOW_PRODUCT, SHOW_QR, PAYMENT_CONFIRMED, PONG)
                      + frames binarios de audio de voz (PCM 16 kHz/16-bit/mono)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

from websockets.asyncio.client import ClientConnection, connect

log = logging.getLogger("volobot.upstream")

CHUNK_BYTES = 2048  # tamaño de bloque recomendado por la especificación
KEEPALIVE_SECONDS = 25


class UpstreamClient:
    def __init__(
        self,
        url: str,
        device_id: str,
        on_event: Callable[[dict], Awaitable[None]],
        on_audio: Callable[[bytes], Awaitable[None]],
    ):
        self._url = url
        self._device_id = device_id
        self._on_event = on_event
        self._on_audio = on_audio
        self._ws: ClientConnection | None = None
        self._tasks: list[asyncio.Task] = []
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def ensure_connected(self) -> bool:
        async with self._lock:
            if self._ws is not None:
                return True
            try:
                ws = await connect(self._url, open_timeout=8, max_size=4 * 1024 * 1024)
            except Exception as exc:
                log.warning("No se pudo conectar al servidor: %s", exc)
                return False
            self._ws = ws
            self._tasks = [
                asyncio.create_task(self._reader(ws)),
                asyncio.create_task(self._keepalive(ws)),
            ]
            log.info("[%s] Conectado al servidor DarkoSync", self._device_id)
            return True

    async def send_speech(self, pcm: bytes) -> None:
        """Manda una grabación completa: START_SPEECH + bloques PCM + END_SPEECH."""
        ws = self._ws
        if ws is None:
            raise ConnectionError("sin conexión con el servidor")
        await ws.send(json.dumps({"action": "START_SPEECH"}))
        for i in range(0, len(pcm), CHUNK_BYTES):
            await ws.send(pcm[i:i + CHUNK_BYTES])
        await ws.send(json.dumps({"action": "END_SPEECH", "device_id": self._device_id}))

    async def _reader(self, ws: ClientConnection) -> None:
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    await self._on_audio(message)
                    continue
                try:
                    data = json.loads(message)
                except ValueError:
                    log.warning("Mensaje no JSON del servidor: %r", message[:100])
                    continue
                await self._on_event(data)
        except Exception as exc:
            log.warning("[%s] Se cerró la conexión con el servidor: %s", self._device_id, exc)
        finally:
            if self._ws is ws:
                self._ws = None

    async def _keepalive(self, ws: ClientConnection) -> None:
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_SECONDS)
                await ws.send(json.dumps({"action": "PING"}))
        except Exception:
            pass

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
