"""Configuración centralizada del backend, leída de variables de entorno (.env)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    device_token: str = "volobot-secret-2026"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    whisper_model: str = "small"
    whisper_language: str = "es"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = 1          # 1 = voraz, mucho más rápido en CPU
    whisper_vad_filter: bool = False    # el VAD de energía de session.py ya recorta las frases

    # Modo de activación: por defecto solo botón (push-to-talk). Con WAKE_WORD_ENABLED=true el
    # backend además escucha el audio continuo del ESP32 buscando "Hey VoloBot".
    wake_word_enabled: bool = False
    ptt_max_seconds: float = 15.0        # tope de una grabación con el botón

    # Detección de voz (VAD por energía) y wake word. Ajustar según el micrófono.
    audio_gain: float = 8.0              # el INMP441 en 16 bit suele llegar muy bajo
    vad_min_rms: float = 300.0           # umbral mínimo (tras la ganancia)
    vad_noise_factor: float = 3.0        # umbral = ruido de fondo * factor
    vad_end_silence_ms: float = 800.0    # silencio que cierra una frase
    vad_min_speech_ms: float = 300.0     # frases más cortas se descartan
    vad_max_utterance_ms: float = 8000.0
    vad_preroll_chunks: int = 10         # ~320 ms de audio previo al inicio de la voz
    wake_max_utterance_ms: float = 5000.0  # en IDLE, frases más largas se ignoran (no gastan Whisper)
    listen_timeout_seconds: float = 8.0  # espera de la petición tras "Hey VoloBot"
    log_audio_levels: bool = False       # true para calibrar umbrales

    # Servidor real (DarkoSync) por WebSocket. Si está vacío se usa el RAG simulado / HTTP de abajo.
    # Con valor, este backend hace de intermediario: manda el audio grabado y traduce los eventos
    # del servidor (STATE, SHOW_PRODUCT, SHOW_QR, PAYMENT_CONFIRMED, audio) a la pantalla del ESP32.
    darkosync_ws_url: str = ""
    upstream_timeout_seconds: float = 45.0   # sin respuesta del servidor -> vuelve a IDLE
    product_hold_seconds: float = 8.0
    qr_hold_seconds: float = 60.0            # el QR se queda este tiempo (o hasta la próxima pregunta)
    # Por ahora solo se MUESTRA información (texto, fichas, QR). No se maneja el pago: el servidor es
    # el real y ahí sí hay dinero y pedidos. Con true se mostraría la pantalla de "pago confirmado".
    show_payment_confirmed: bool = False
    payment_hold_seconds: float = 6.0
    text_page_seconds: float = 5.0           # (modo local) respuestas largas: segundos por página

    # La voz del servidor suena en el Mac (reproductor tools/play_replies.py; Docker no tiene altavoces)
    # y la carita del ESP32 "habla" mientras tanto. La ficha/QR se muestra al terminar de hablar.
    voice_gap_seconds: float = 3.0           # sin audio del servidor durante esto = la voz terminó
    speech_tail_seconds: float = 0.4         # margen tras la voz antes de mostrar la ficha/QR
    mouth_window_ms: int = 150               # cada cuánto se actualiza la boca de la carita
    error_face_seconds: float = 2.5          # carita triste ante un fallo, antes de volver a la normal

    # Verificación de lo que se manda al servidor real (no retrasa el envío):
    transcribe_sent_audio: bool = True   # Whisper local imprime en la consola lo que se dijo
    save_sent_audio: bool = True         # guarda el último audio enviado para poder escucharlo
    debug_dir: str = "/app/debug"        # en el Mac: backend/debug/ultimo_enviado.wav

    rag_api_url: str = ""
    rag_api_key: str = ""
    rag_timeout_seconds: float = 15.0


settings = Settings()
