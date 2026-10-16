"""Cliente HTTP hacia el RAG ya armado.

Contrato esperado (ajustar según el RAG real que ya tienen):

Request  (POST {RAG_API_URL}):
    {
        "text": "<texto transcrito del usuario>",
        "device_id": "<id del ESP32>",
        "session_id": "<id de sesión/conexión>"
    }

Response (200 JSON):
    {
        "reply_text": "<respuesta en lenguaje humano, lista para mostrar/leer>"
        ... (campos extra que el RAG real agregue quedan disponibles en `raw`)
    }

Si RAG_API_URL no está configurado, responde con un eco (útil para probar el
firmware/backend sin depender todavía del RAG real).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import settings
from .mock_rag import mock_query

log = logging.getLogger("volobot.rag")


@dataclass
class RagReply:
    reply_text: str
    raw: dict[str, Any] = field(default_factory=dict)


async def query_rag(text: str, device_id: str, session_id: str) -> RagReply:
    log.info("[%s] ══> ENVIADO al RAG: %r", device_id, text)
    reply = await _query_rag(text, device_id, session_id)
    log.info("[%s] <══ RECIBIDO del RAG: %r", device_id, reply.reply_text)
    return reply


async def _query_rag(text: str, device_id: str, session_id: str) -> RagReply:
    if not settings.rag_api_url:
        log.warning("RAG_API_URL no configurado; usando RAG simulado (mock_rag).")
        data = mock_query(text)
        return RagReply(reply_text=data["reply_text"], raw=data)

    headers = {}
    if settings.rag_api_key:
        headers["Authorization"] = f"Bearer {settings.rag_api_key}"

    payload = {"text": text, "device_id": device_id, "session_id": session_id}

    try:
        async with httpx.AsyncClient(timeout=settings.rag_timeout_seconds) as client:
            response = await client.post(settings.rag_api_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.exception("Error consultando el RAG: %s", exc)
        return RagReply(reply_text="Tuve un problema para procesar tu pedido, intenta de nuevo.")

    return RagReply(reply_text=data.get("reply_text", ""), raw=data)
