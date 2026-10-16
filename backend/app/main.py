"""Backend intermediario VoloBot: expone /ws/iot (protocolo del ESP32) y /health."""

from __future__ import annotations

import json
import logging

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Query, Response, WebSocket, WebSocketDisconnect, status

from .config import settings
from . import speaker
from .session import DeviceSession
from .stt import warm_up

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("volobot.main")



@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.darkosync_ws_url and not settings.transcribe_sent_audio:
        log.info("Modo servidor real (DarkoSync): no se usa Whisper local.")
    else:
        log.info("Precalentando Whisper...")
        await asyncio.to_thread(warm_up)
        log.info("Whisper listo.")
    yield


app = FastAPI(title="VoloBot AI Backend", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "volobot-backend"}


@app.get("/speaker/next")
async def speaker_next(
    token: str | None = Query(default=None),
    wait: float = Query(default=25.0, ge=0, le=55),
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
):
    """El reproductor del Mac (tools/play_replies.py) pide aquí la siguiente voz. 204 = nada nuevo."""
    if (token or x_device_token) != settings.device_token:
        return Response(status_code=401)
    wav = await speaker.hub.next(wait)
    if wav is None:
        return Response(status_code=204)
    return Response(content=wav, media_type="audio/wav")


@app.get("/speaker/status")
async def speaker_status():
    return {"player_connected": speaker.hub.player_connected}


@app.websocket("/ws/iot")
async def ws_iot(
    websocket: WebSocket,
    token: str | None = Query(default=None),
    device_id: str = Query(default="unknown"),
    rate: int = Query(default=16000),
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
):
    device_token = token or x_device_token
    if device_token != settings.device_token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    session = DeviceSession(websocket, device_id, rate)
    log.info("Dispositivo conectado: %s", device_id)
    await session.send_state("IDLE")

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                log.info("Dispositivo desconectado: %s", device_id)
                break
            if message.get("text") is not None:
                await _handle_text(session, message["text"])
            elif message.get("bytes") is not None:
                await session.on_audio_chunk(message["bytes"])
    except WebSocketDisconnect:
        log.info("Dispositivo desconectado: %s", device_id)
    finally:
        session.close()


async def _handle_text(session: DeviceSession, raw: str):
    try:
        payload = json.loads(raw)
    except ValueError:
        log.warning("Mensaje de texto no es JSON válido: %r", raw)
        return

    action = payload.get("action")
    if action == "START_SPEECH":
        await session.on_start_speech()
    elif action == "END_SPEECH":
        await session.on_end_speech()
    elif action == "WAKE":  # botón físico: equivale a decir "Hey VoloBot"
        await session.on_wake()
    elif action == "PING":
        await session.on_ping()
    else:
        log.warning("Acción desconocida del dispositivo: %r", action)
