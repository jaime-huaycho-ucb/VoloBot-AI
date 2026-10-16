"""Esquema del protocolo WebSocket IoT, fase actual (sin altavoz).

Mensajes del ESP32 -> backend (upstream):
    {"action": "START_SPEECH"}              (botón pulsado)
    <frames binarios PCM 16-bit mono, mientras se mantiene el botón>
    {"action": "END_SPEECH", "device_id": "..."}   (botón soltado)
    {"action": "WAKE"}                      (botón físico; equivale a "Hey VoloBot")
    {"action": "PING"}                      (opcional, cada ~25s)

Modo alternativo (WAKE_WORD_ENABLED=true en el backend): el ESP32 transmite audio
continuo y el backend detecta "Hey VoloBot" y el fin de frase; WAKE equivale a ese gesto.

Mensajes del backend -> ESP32 (downstream):
    {"type": "PONG"}
    {"type": "STATE", "state": "IDLE"|"LISTENING"|"THINKING"|"SPEAKING", "mood": "neutral|happy|sad|..."}
    {"type": "MOUTH", "level": 0|1|2}     (con SPEAKING: la boca se mueve al ritmo de la voz que suena en el Mac)
    {"type": "DISPLAY", "text": "<respuesta del RAG, lista para mostrar en pantalla>"}
    {"type": "IMAGE_BEGIN", "kind": "product|qr|payment|text", "width": 240, "height": 240, "size": 115200}
    <frames binarios RGB565 big-endian que suman `size` bytes; el ESP32 los vuelca a la pantalla>

Pensado para crecer: cuando haya altavoz/TTS se puede agregar, por ejemplo,
{"type": "SPEAKING"} + frames binarios de audio de salida, sin romper lo anterior.
"""

from __future__ import annotations

from typing import Any, Literal

State = Literal["IDLE", "LISTENING", "THINKING", "SPEAKING"]


def state_message(state: State, mood: str | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"type": "STATE", "state": state}
    if mood:
        msg["mood"] = mood   # neutral | happy | curious | excited | sad
    return msg


def mouth_message(level: int) -> dict[str, Any]:
    """Apertura de la boca de la carita mientras habla: 0 cerrada, 1 media, 2 abierta."""
    return {"type": "MOUTH", "level": level}


def image_begin_message(kind: str, size: int) -> dict[str, Any]:
    """Anuncia una imagen RGB565 240x240; los `size` bytes llegan después en frames binarios."""
    return {"type": "IMAGE_BEGIN", "kind": kind, "width": 240, "height": 240, "size": size}


def pong_message() -> dict[str, Any]:
    return {"type": "PONG"}


def display_message(text: str) -> dict[str, Any]:
    return {"type": "DISPLAY", "text": text}
