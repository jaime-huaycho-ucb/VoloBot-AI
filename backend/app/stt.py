"""Speech-to-text local con faster-whisper."""

from __future__ import annotations

import logging
import re
import unicodedata

import numpy as np
from faster_whisper import WhisperModel

from .config import settings

log = logging.getLogger("volobot.stt")

_model: WhisperModel | None = None

# Frases que Whisper inventa cuando el audio es ruido o casi silencio (ya normalizadas).
_HALLUCINATIONS = (
    "nos vemos en el proximo video",
    "gracias por ver",
    "gracias por vernos",
    "suscribete",
    "no olvides suscribirte",
    "subtitulos realizados por",
    "subtitulos por la comunidad",
    "amara org",
    "hasta la proxima",
)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text)).strip()


def is_hallucination(text: str) -> bool:
    norm = _norm(text)
    return any(h in norm for h in _HALLUCINATIONS)


def warm_up() -> None:
    """Carga el modelo y hace una transcripción corta para que la primera frase real no espere."""
    transcribe_pcm16(b"\x00\x00" * 16000)


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        log.info(
            "Cargando faster-whisper '%s' (%s/%s)...",
            settings.whisper_model, settings.whisper_device, settings.whisper_compute_type,
        )
        _model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
        log.info("Modelo de STT listo.")
    return _model


def transcribe_pcm16(pcm_bytes: bytes, initial_prompt: str | None = None) -> str:
    """Transcribe audio PCM 16-bit signed mono (little-endian) a texto.

    Asume 16000 Hz, igual que especifica el protocolo. Si en algún momento el
    ESP32 muestrea a otra frecuencia, hay que re-muestrear antes de llamar aquí.
    """
    if not pcm_bytes:
        return ""
    audio = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32) / 32768.0
    model = get_model()
    segments, _info = model.transcribe(
        audio,
        language=settings.whisper_language,
        beam_size=settings.whisper_beam_size,
        vad_filter=settings.whisper_vad_filter,
        temperature=0.0,                    # sin reintentos con temperatura: el doble de rápido
        condition_on_previous_text=False,
        initial_prompt=initial_prompt,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    if text and is_hallucination(text):
        log.info("Descartada alucinación de Whisper: %r", text)
        return ""
    return text
