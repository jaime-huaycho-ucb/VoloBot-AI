"""Máquina de estados por conexión de dispositivo (un ESP32 = una sesión).

Modo por defecto (botón / push-to-talk):
  - Botón pulsado  -> START_SPEECH: el ESP32 manda audio mientras se mantiene.
  - Botón soltado  -> END_SPEECH: Whisper -> RAG -> DISPLAY.

Modo opcional (WAKE_WORD_ENABLED=true), sin botón:
  - El ESP32 transmite audio continuo; un VAD por energía segmenta frases y
    Whisper busca "Hey VoloBot". Tras la activación, la siguiente frase es la
    petición. WAKE (botón) equivale a decir la palabra de activación.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import unicodedata
import uuid
import wave
from collections import deque

import httpx
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from . import images, protocol, speaker
from .config import settings
from .rag_client import query_rag
from .stt import transcribe_pcm16
from .upstream import UpstreamClient

log = logging.getLogger("volobot.session")

SAMPLE_RATE = 16000
WAKE_PROMPT = "Hey VoloBot."
# Tolera cómo suele transcribir Whisper: "volobot", "volo bot", "bolobot", "volobod"...
WAKE_RE = re.compile(r"[vb][oua]l[oua]?\s*[bv][oua][td]")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text)).strip()


class DeviceSession:
    def __init__(self, websocket: WebSocket, device_id: str, sample_rate: int = SAMPLE_RATE):
        self.ws = websocket
        self.device_id = device_id
        self.sample_rate = sample_rate
        self.session_id = str(uuid.uuid4())
        self.mode: protocol.State = "IDLE"
        self._listen_deadline = 0.0
        self._closed = False
        self._processing = False

        # Botón (push-to-talk)
        self._ptt = False
        self._ptt_buf = bytearray()

        # Wake word: VAD por energía
        self._noise = 100.0
        self._preroll: deque[bytes] = deque(maxlen=max(1, settings.vad_preroll_chunks))
        self._reset_utterance()
        self._last_level_log = 0.0

        # Las frases se procesan en orden en un worker; el audio sigue entrando mientras
        # Whisper trabaja, así no se pierde el principio de la siguiente frase.
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._worker = asyncio.create_task(self._run_worker())

        # Servidor real (DarkoSync): este backend hace de intermediario.
        self._up: UpstreamClient | None = None
        self._mood = "happy"                  # ánimo de la carita mientras habla
        self._voice_pcm = bytearray()         # voz de la respuesta que va llegando del servidor
        self._voice_timer: asyncio.TimerHandle | None = None
        self._speaking = False                # suena la respuesta y la carita habla
        self._speak_task: asyncio.Task | None = None
        self._pending: tuple | None = None    # (tipo, imagen, segundos): se muestra al terminar de hablar
        self._holding = False                 # hay una imagen (producto/QR/pago) en pantalla
        self._hold_task: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self._error_task: asyncio.Task | None = None
        if settings.darkosync_ws_url:
            self._up = UpstreamClient(
                settings.darkosync_ws_url, device_id, self._on_upstream_event, self._on_upstream_audio
            )
            asyncio.create_task(self._up.ensure_connected())  # conexión lista antes del primer uso

    def _reset_utterance(self):
        self._utt = bytearray()
        self._in_speech = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._utt_ms = 0.0

    # ------------------------------------------------------------- envío

    async def _send(self, payload: dict):
        """Envía al ESP32; si ya se desconectó, no revienta."""
        if self._closed:
            return
        try:
            await self.ws.send_json(payload)
        except (RuntimeError, WebSocketDisconnect):
            self._closed = True

    async def send_state(self, state: protocol.State, mood: str | None = None):
        self.mode = state
        await self._send(protocol.state_message(state, mood))

    async def _send_bytes(self, data: bytes):
        if self._closed:
            return
        try:
            await self.ws.send_bytes(data)
        except (RuntimeError, WebSocketDisconnect):
            self._closed = True

    def close(self):
        self._closed = True
        self._worker.cancel()
        self._cancel_hold()
        self._cancel_watchdog()
        self._cancel_speaking()
        if self._up:
            asyncio.create_task(self._up.close())

    # ------------------------------------------------------------- audio

    def _to_16k(self, chunk: bytes) -> np.ndarray:
        """PCM del ESP32 -> float32 a 16 kHz con la ganancia configurada."""
        samples = np.frombuffer(chunk[: len(chunk) // 2 * 2], dtype="<i2").astype(np.float32)
        if self.sample_rate != SAMPLE_RATE:  # el ESP32 puede muestrear a menos de 16 kHz
            n_out = int(len(samples) * SAMPLE_RATE / self.sample_rate)
            samples = np.interp(
                np.linspace(0, len(samples) - 1, n_out), np.arange(len(samples)), samples
            ).astype(np.float32)
        return np.clip(samples * settings.audio_gain, -32768, 32767)

    async def on_audio_chunk(self, chunk: bytes):
        if len(chunk) < 2:
            return

        if self._ptt:  # grabando mientras se mantiene el botón
            if len(self._ptt_buf) < settings.ptt_max_seconds * SAMPLE_RATE * 2:
                self._ptt_buf.extend(self._to_16k(chunk).astype("<i2").tobytes())
            return
        if not settings.wake_word_enabled:
            return

        await self._vad_chunk(chunk)

    # ----------------------------------------------------------- botón (PTT)

    async def on_start_speech(self):
        """Botón pulsado: empieza a grabar."""
        if self._processing or self.mode == "THINKING":
            return
        self._cancel_hold()          # una nueva pregunta quita la imagen que hubiera en pantalla
        self._holding = False
        self._cancel_speaking()      # y corta la voz, la boca y la ficha pendiente de la respuesta anterior
        speaker.hub.clear()
        self._mood = "happy"
        self._ptt = True
        self._ptt_buf.clear()
        await self.send_state("LISTENING")
        log.info("[%s] Botón: grabando", self.device_id)

    async def on_end_speech(self):
        """Botón soltado: manda lo grabado a Whisper y luego al RAG."""
        if not self._ptt:
            return
        self._ptt = False
        pcm = np.frombuffer(bytes(self._ptt_buf), dtype="<i2").astype(np.float32)
        self._ptt_buf.clear()
        seconds = len(pcm) / SAMPLE_RATE
        peak = float(np.abs(pcm).max()) if len(pcm) else 0.0
        rms = float(np.sqrt(np.mean(pcm ** 2))) if len(pcm) else 0.0
        clipped = float(np.mean(np.abs(pcm) >= 32000)) * 100 if len(pcm) else 0.0
        log.info("[%s] Botón soltado: %.1f s de audio, pico %.0f, rms %.0f, saturado %.1f %%",
                 self.device_id, seconds, peak, rms, clipped)
        if clipped > 1.0:
            log.warning("[%s] AUDIO SATURADO (%.1f %% de las muestras al máximo): baja la ganancia del micrófono",
                        self.device_id, clipped)
        elif 0 < peak < 1500:
            log.warning("[%s] Audio MUY BAJO (pico %.0f): habla más cerca o sube la ganancia", self.device_id, peak)
        if seconds < 0.4 or peak < 300:
            await self._notify("no se escuchó nada")
            return
        # Normaliza el volumen: el micrófono analógico llega muy variable.
        pcm = pcm - pcm.mean()
        peak = float(np.abs(pcm).max())
        if peak < 20000:
            pcm = pcm * min(20000.0 / peak, 20.0)
        audio = np.clip(pcm, -32768, 32767).astype("<i2").tobytes()
        if self._up:
            if settings.save_sent_audio:
                self._save_wav(audio)
            asyncio.create_task(self._send_upstream(audio))
            if settings.transcribe_sent_audio:
                asyncio.create_task(self._log_local_transcription(audio))
        else:
            self._queue.put_nowait(audio)

    # ------------------------------------- servidor real (DarkoSync), proxy

    def _save_wav(self, audio: bytes):
        """Guarda exactamente el audio que se manda al servidor, para poder escucharlo."""
        self._save_wav_file(audio, "ultimo_enviado.wav")

    def _save_wav_file(self, audio: bytes, name: str):
        try:
            os.makedirs(settings.debug_dir, exist_ok=True)
            path = os.path.join(settings.debug_dir, name)
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLE_RATE)
                w.writeframes(audio)
            log.info("[%s] Audio guardado en %s", self.device_id, path)
        except OSError as exc:
            log.warning("[%s] No se pudo guardar el audio: %s", self.device_id, exc)

    async def _log_local_transcription(self, audio: bytes):
        """Whisper local pasa a texto lo que se mandó, solo para mostrarlo en la consola."""
        t0 = time.monotonic()
        try:
            text = await asyncio.to_thread(transcribe_pcm16, audio)
        except Exception:
            log.exception("[%s] Falló la transcripción local de verificación", self.device_id)
            return
        log.info("[%s] ══ LO QUE SE DIJO (Whisper local): %r   [%.1f s]",
                 self.device_id, text or "(no se entendió nada)", time.monotonic() - t0)

    async def _send_upstream(self, audio: bytes):
        log.info("[%s] ══> ENVIADO al servidor: audio de %.1f s (%d bytes, PCM 16 kHz)",
                 self.device_id, len(audio) / 2 / SAMPLE_RATE, len(audio))
        await self.send_state("THINKING")
        try:
            if not await self._up.ensure_connected():
                raise ConnectionError("sin conexión")
            await self._up.send_speech(audio)
        except Exception as exc:
            log.warning("[%s] No se pudo enviar al servidor: %s", self.device_id, exc)
            await self._error_face("sin conexión con el servidor")
            return
        self._arm_watchdog()

    def _arm_watchdog(self):
        self._cancel_watchdog()
        self._watchdog = asyncio.create_task(self._watchdog_run())

    def _cancel_watchdog(self):
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None

    async def _watchdog_run(self):
        await asyncio.sleep(settings.upstream_timeout_seconds)
        if self.mode == "THINKING" and not self._holding and not self._speaking:
            if self._pending:
                await self._show_pending()
                return
            log.warning("[%s] El servidor no respondió a tiempo", self.device_id)
            await self._error_face("el servidor no respondió a tiempo")

    def _cancel_hold(self):
        if self._hold_task:
            self._hold_task.cancel()
            self._hold_task = None

    # ---- carita triste: los fallos se muestran con la cara, ya no con texto

    async def _error_face(self, reason: str):
        log.info("[%s] Carita triste: %s", self.device_id, reason)
        self._cancel_error()
        await self.send_state("IDLE", mood="sad")
        self._error_task = asyncio.create_task(self._calm_down())

    async def _calm_down(self):
        await asyncio.sleep(settings.error_face_seconds)
        self._error_task = None
        if self.mode == "IDLE" and not self._holding and not self._speaking:
            await self.send_state("IDLE")

    def _cancel_error(self):
        if self._error_task:
            self._error_task.cancel()
            self._error_task = None

    async def _notify(self, text: str):
        """Aviso al usuario: con el servidor real, carita triste; en modo local, texto en pantalla."""
        if self._up:
            await self._error_face(text)
        else:
            await self.send_state("IDLE")
            await self._send(protocol.display_message(text))

    # ---- voz de la respuesta: suena en el Mac y la carita habla

    def _cancel_speaking(self):
        if self._voice_timer:
            self._voice_timer.cancel()
            self._voice_timer = None
        if self._speak_task:
            self._speak_task.cancel()
            self._speak_task = None
        self._speaking = False
        self._voice_pcm.clear()
        self._pending = None
        self._cancel_error()

    async def _on_upstream_audio(self, data: bytes):
        """Voz del bot (TTS): se junta completa y luego suena en el Mac."""
        if self._speaking:
            return
        if not self._voice_pcm:
            log.info("[%s] <══ RECIBIDO del servidor: llegando audio de voz", self.device_id)
        if len(self._voice_pcm) < 120 * SAMPLE_RATE * 2:
            self._voice_pcm.extend(data)
        self._cancel_watchdog()
        if self._voice_timer:
            self._voice_timer.cancel()
        loop = asyncio.get_running_loop()   # respaldo: si no llega STATE IDLE, una pausa marca el final
        self._voice_timer = loop.call_later(
            settings.voice_gap_seconds, lambda: asyncio.create_task(self._finish_reply("pausa en el audio"))
        )

    async def _finish_reply(self, reason: str):
        """El servidor terminó: hablar si hay voz; si no, mostrar la ficha/QR pendiente o avisar."""
        if self._voice_timer:
            self._voice_timer.cancel()
            self._voice_timer = None
        if self._speaking:
            return
        pcm = bytes(self._voice_pcm)
        self._voice_pcm.clear()
        self._cancel_watchdog()
        if len(pcm) >= SAMPLE_RATE * 2 * 0.3:
            log.info("[%s] <══ RECIBIDO del servidor: audio de voz, %d bytes (%.1f s) [fin: %s]",
                     self.device_id, len(pcm), len(pcm) / 2 / SAMPLE_RATE, reason)
            await self._speak(pcm)
        elif self._pending:
            await self._show_pending()
        elif self.mode == "THINKING":
            await self._error_face("el servidor terminó sin responder")

    async def _speak(self, pcm: bytes):
        self._speaking = True
        seconds = len(pcm) / 2 / SAMPLE_RATE
        if settings.save_sent_audio:
            self._save_wav_file(pcm, "ultima_respuesta.wav")
        if not speaker.hub.player_connected:
            log.warning("[%s] No hay reproductor conectado, la voz no sonará. En tu Mac ejecuta: "
                        "python3 tools/play_replies.py", self.device_id)
        speaker.hub.enqueue(speaker.pcm_to_wav(pcm))
        levels = await asyncio.to_thread(speaker.mouth_levels, pcm, settings.mouth_window_ms)
        log.info("[%s] ══> REPRODUCIENDO la respuesta de voz en el Mac (%.1f s); la carita habla", self.device_id, seconds)
        await self.send_state("SPEAKING", mood=self._mood)
        self._speak_task = asyncio.create_task(self._lipsync(levels, seconds))

    async def _lipsync(self, levels: list[int], seconds: float):
        """Mueve la boca de la carita al ritmo de la voz y, al terminar, muestra lo pendiente."""
        step = settings.mouth_window_ms / 1000
        t0 = time.monotonic()
        last = 0
        try:
            for i, level in enumerate(levels):
                delay = t0 + i * step - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                if level != last:
                    await self._send(protocol.mouth_message(level))
                    last = level
            rest = t0 + seconds + settings.speech_tail_seconds - time.monotonic()
            if rest > 0:
                await asyncio.sleep(rest)
        except asyncio.CancelledError:
            return
        self._speak_task = None
        self._speaking = False
        log.info("[%s] La respuesta de voz terminó", self.device_id)
        if self._pending:
            await self._show_pending()
        else:
            await self.send_state("IDLE")

    # ---- fichas y QR: se muestran cuando termina de hablar

    async def _on_upstream_event(self, data: dict):
        kind = data.get("type")
        shown = {k: (v[:40] + "…" if k == "qr_data" and isinstance(v, str) and len(v) > 40 else v) for k, v in data.items()}
        log.info("[%s] <══ RECIBIDO del servidor: %s", self.device_id, json.dumps(shown, ensure_ascii=False))
        try:
            if kind == "SHOW_PRODUCT":
                await self._show_product(data)
            elif kind == "SHOW_QR":
                await self._show_qr(data)
            elif kind == "PAYMENT_CONFIRMED":
                if settings.show_payment_confirmed:
                    await self._show_payment(data)
                else:
                    log.info("[%s] PAYMENT_CONFIRMED ignorado (solo se muestra información)", self.device_id)
            elif kind in ("PONG", "SPEECH_RECEIVED"):   # acuses del servidor, sin contenido para mostrar
                pass
            elif kind == "STATE":
                await self._on_upstream_state(data.get("state"), data.get("mood"))
            else:
                log.info("[%s] Evento no documentado del servidor: %r (se ignora)", self.device_id, kind)
        except Exception:
            log.exception("[%s] Error manejando evento %s del servidor", self.device_id, kind)
            if self.mode == "THINKING":
                await self._error_face("error procesando la respuesta")

    async def _on_upstream_state(self, state: str | None, mood: str | None = None):
        if mood and mood != "neutral":
            self._mood = mood
        if self._holding:   # con ficha/QR en pantalla, los STATE del servidor no la deben borrar
            return
        if state == "THINKING":
            if self.mode not in ("THINKING", "SPEAKING"):
                await self.send_state("THINKING")
        elif state == "SPEAKING":
            self._cancel_watchdog()   # la voz viene en camino; la carita habla cuando ya esté completa
        elif state == "IDLE":
            self._cancel_watchdog()
            await self._finish_reply("STATE IDLE")

    async def _fetch(self, url: str | None) -> bytes | None:
        if not url:
            return None
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.content
        except Exception as exc:
            log.warning("No se pudo bajar %s: %s", url.split("?")[0], exc)
            return None

    async def _show_product(self, data: dict):
        log.info("[%s] Ficha de producto: %s, %s", self.device_id, data.get("name"), data.get("price"))
        photo = await self._fetch(data.get("image_url"))
        img = await asyncio.to_thread(
            images.render_product, str(data.get("name", "")), str(data.get("price", "")), photo
        )
        await self._offer_image("product", img, settings.product_hold_seconds)

    async def _show_qr(self, data: dict):
        log.info("[%s] QR de cobro: total %s, pedido %s", self.device_id, data.get("amount"), data.get("order_id"))
        photo = await self._fetch(data.get("qr_image_url"))
        img = await asyncio.to_thread(
            images.render_qr, str(data.get("amount", "")), photo, data.get("qr_data")
        )
        await self._offer_image("qr", img, settings.qr_hold_seconds)

    async def _show_payment(self, data: dict):
        img = await asyncio.to_thread(
            images.render_payment, str(data.get("amount", "")), str(data.get("message", ""))
        )
        await self._offer_image("payment", img, settings.payment_hold_seconds)

    async def _offer_image(self, kind: str, img, hold_seconds: float):
        """Mientras el bot responde la imagen espera; si llega fuera de una respuesta, se muestra ya."""
        if self.mode == "THINKING" or self._speaking:
            self._pending = (kind, img, hold_seconds)
            log.info("[%s] Imagen '%s' lista: se mostrará cuando termine de hablar", self.device_id, kind)
        else:
            await self._show_image(kind, img, hold_seconds)

    async def _show_pending(self):
        kind, img, hold_seconds = self._pending
        self._pending = None
        await self._show_image(kind, img, hold_seconds)

    async def _show_image(self, kind: str, img, hold_seconds: float):
        """Manda una pantalla al ESP32 y la mantiene `hold_seconds`; luego vuelve a la cara."""
        log.info("[%s] ══> MOSTRADO en pantalla (%s)", self.device_id, kind)
        await self._push_image(kind, img)
        self._cancel_watchdog()
        self._cancel_hold()
        self._holding = True
        self._hold_task = asyncio.create_task(self._release_after(hold_seconds))

    async def _release_after(self, seconds: float):
        await asyncio.sleep(seconds)
        self._hold_task = None
        self._holding = False
        await self.send_state("IDLE")

    async def _push_image(self, kind: str, img):
        data = await asyncio.to_thread(images.to_rgb565, img)
        self.mode = "IDLE"   # el ESP32 ya puede volver a grabar; sin STATE para no borrar la imagen
        await self._send(protocol.image_begin_message(kind, len(data)))
        for i in range(0, len(data), 4800):
            await self._send_bytes(data[i:i + 4800])
        log.info("[%s] Imagen '%s' enviada (%d bytes)", self.device_id, kind, len(data))

    # ------------------------------------------------- wake word (opcional)

    async def on_wake(self):
        """Activación manual: igual que detectar "Hey VoloBot"."""
        if self.mode == "THINKING":
            return
        while not self._queue.empty():  # frases pendientes de antes
            self._queue.get_nowait()
        self._reset_utterance()
        self._preroll.clear()
        self._listen_deadline = time.monotonic() + settings.listen_timeout_seconds
        await self.send_state("LISTENING")
        log.info("[%s] Activación manual", self.device_id)

    async def _vad_chunk(self, chunk: bytes):
        # Timeout de seguridad: si tras "Hey VoloBot" no llega una petición, volver a IDLE.
        if (
            self.mode == "LISTENING"
            and not self._in_speech
            and not self._processing
            and self._queue.empty()
            and time.monotonic() > self._listen_deadline
        ):
            log.info("[%s] Sin petición tras la activación; vuelvo a IDLE", self.device_id)
            self._reset_utterance()
            self._preroll.clear()
            await self.send_state("IDLE")
            return

        samples = self._to_16k(chunk)
        rms = float(np.sqrt(np.mean(samples**2)))
        pcm = samples.astype("<i2").tobytes()
        chunk_ms = len(pcm) / 2 / SAMPLE_RATE * 1000

        threshold = max(settings.vad_min_rms, self._noise * settings.vad_noise_factor)
        is_speech = rms > threshold

        now = time.monotonic()
        if settings.log_audio_levels and now - self._last_level_log > 2:
            self._last_level_log = now
            log.info("[%s] nivel rms=%.0f umbral=%.0f ruido=%.0f", self.device_id, rms, threshold, self._noise)

        if not self._in_speech:
            if not is_speech:
                self._noise = 0.95 * self._noise + 0.05 * rms
                self._preroll.append(pcm)
                return
            self._in_speech = True
            self._utt = bytearray(b"".join(self._preroll))
            self._preroll.clear()

        self._utt.extend(pcm)
        self._utt_ms += chunk_ms
        if is_speech:
            self._speech_ms += chunk_ms
            self._silence_ms = 0.0
        else:
            self._silence_ms += chunk_ms

        if self._silence_ms >= settings.vad_end_silence_ms or self._utt_ms >= settings.vad_max_utterance_ms:
            audio, speech_ms = bytes(self._utt), self._speech_ms
            self._reset_utterance()
            if speech_ms >= settings.vad_min_speech_ms:
                self._queue.put_nowait(audio)

    # ------------------------------------------------------------ frases

    async def _run_worker(self):
        while True:
            audio = await self._queue.get()
            self._processing = True
            try:
                await self._process_utterance(audio)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("[%s] Error procesando frase", self.device_id)
                await self.send_state("IDLE")
            finally:
                self._processing = False

    async def _process_utterance(self, audio: bytes):
        mode_before = self.mode
        if mode_before == "IDLE":
            dur_ms = len(audio) / 2 / SAMPLE_RATE * 1000
            if dur_ms > settings.wake_max_utterance_ms:
                log.info("[%s] Frase de %.1f s ignorada (demasiado larga para ser activación)", self.device_id, dur_ms / 1000)
                return
        elif mode_before == "LISTENING":
            await self.send_state("THINKING")

        prompt = WAKE_PROMPT if mode_before == "IDLE" else None
        t0 = time.monotonic()
        text = await asyncio.to_thread(transcribe_pcm16, audio, prompt)
        log.info("[%s] (%s) frase: %r  [whisper %.1f s]", self.device_id, mode_before, text, time.monotonic() - t0)

        if mode_before == "LISTENING":
            if not text:
                await self.send_state("IDLE")
                await self._send(protocol.display_message("No te entendí, intenta otra vez."))
                return
            await self._answer(text)
            return

        if not text:
            return
        norm = _normalize(text)
        match = WAKE_RE.search(norm)
        if not match:
            return
        command = norm[match.end():].strip()
        if len(command.split()) < 2:
            self._listen_deadline = time.monotonic() + settings.listen_timeout_seconds
            await self.send_state("LISTENING")
            log.info("[%s] Palabra de activación detectada", self.device_id)
            return
        log.info("[%s] Activación + petición en la misma frase", self.device_id)
        await self._answer(command)

    async def _answer(self, text: str):
        if self.mode != "THINKING":
            await self.send_state("THINKING")
        reply = await query_rag(text, self.device_id, self.session_id)
        # IDLE primero: set_state() limpia la pantalla; el texto va después para que se quede.
        await self.send_state("IDLE")
        await self._send(protocol.display_message(reply.reply_text))

    async def on_ping(self):
        await self._send(protocol.pong_message())
