# VoloBot AI

Agente de voz tipo "Alexa" para compras, sobre un nodo **ESP32** (pantalla + micrófono) y un **backend intermediario** en Python que transcribe la voz y consulta un RAG ya armado para generar una respuesta dinámica.

Esta carpeta (`projects/VoloBot-AI/`) es la versión que se está construyendo **desde cero, de forma oficial**, reemplazando al prototipo rápido de `VoloBot-IA/` (que se deja intacto como referencia histórica). Todo el stack es **Python**: backend (FastAPI) y firmware (MicroPython).

## Fase actual (importante)

Por ahora **no hay altavoz**. El flujo es:

```
ESP32 (mic) --audio--> Backend --STT--> texto --> RAG --> respuesta dinámica (texto)
                                                              |
                                                              v
                                                   ESP32 muestra el texto en pantalla
```

No hay TTS, ni voz de salida, ni flujo de producto/QR/pago todavía. Eso se agrega después (ver "Próximos pasos"), sin tener que rehacer esta base: el protocolo ya está pensado para crecer (se puede agregar un nuevo tipo de mensaje y, cuando haya altavoz, frames binarios de audio de salida).

> Nota: la especificación `especificacion_equipo_iot_esp32.md` (carpeta raíz) describe la arquitectura de **otro proyecto ya bastante avanzado** (DarkoSync AI, en C++ con MAX98357A, TTS con ElevenLabs y flujo de pago). Se usó solo como referencia de buenas prácticas (protocolo WebSocket, pinout de pantalla/mic), pero esta carpeta prioriza lo que Jaime está construyendo ahora: todo desde cero, en Python, y sin altavoz.

## Estructura

```
VoloBot-AI/
├── backend/        # Backend intermediario (FastAPI + WebSocket), dockerizado
├── firmware/        # Firmware ESP32 en MicroPython
└── docs/
    └── PINOUT.md    # Pinout oficial y notas de cableado (pantalla + mic, sin altavoz)
```

## Levantar el backend (Docker)

```bash
cd projects/VoloBot-AI
cp backend/.env.example backend/.env
# edita backend/.env: RAG_API_URL, RAG_API_KEY, DEVICE_TOKEN
docker compose up --build
```

- WebSocket: `ws://<ip-de-tu-pc>:8000/ws/iot?token=<DEVICE_TOKEN>&role=device&device_id=<ID>`
- Healthcheck: `GET http://localhost:8000/health`

## Flashear el firmware (MicroPython / Thonny)

```bash
cd projects/VoloBot-AI/firmware
# edita config.py: WIFI_SSID, WIFI_PASSWORD, WS_HOST, WS_PORT, DEVICE_TOKEN
```

Con Thonny (igual que el prototipo): abre cada archivo (`config.py`,
`display.py`, `mic.py`, `mic_base.py`, `mic_adc.py`, `mic_i2s.py`, `ws_client.py`, `main.py`) y "Guardar como… →
MicroPython device", con el mismo nombre en la placa. Detalle en
`firmware/README.md`.

## Protocolo WebSocket (versión actual, simplificada)

**ESP32 → backend:**
- `{"action": "START_SPEECH"}`
- frames binarios: audio PCM 16-bit, 16000 Hz, mono
- `{"action": "END_SPEECH", "device_id": "..."}`
- `{"action": "PING"}` (opcional)

**backend → ESP32:**
- `{"type": "PONG"}`
- `{"type": "STATE", "state": "IDLE"|"LISTENING"|"THINKING"}` (para animar la pantalla)
- `{"type": "DISPLAY", "text": "<respuesta del RAG, lista para mostrar>"}`

Detalle completo en `backend/app/protocol.py` y `firmware/ws_client.py`.

## Próximos pasos (cuando haya altavoz / se avance el proyecto)

1. Agregar TTS en el backend (texto del RAG → audio) y un nuevo tipo de mensaje, p. ej. `SPEAKING` + frames binarios de audio de salida.
2. Agregar el amplificador I2S (MAX98357A o similar) y su driver (`firmware/speaker_io.py`).
3. Si se necesita, retomar el flujo comercial (mostrar producto, QR, confirmación de pago) como mensajes adicionales del mismo protocolo — el diseño actual no lo bloquea.
4. Ajustar `backend/app/rag_client.py` al contrato exacto del RAG real (hoy está genérico, documentado en el propio archivo).

## Conexión con el servidor real (DarkoSync)

Con `DARKOSYNC_WS_URL` en `backend/.env`, el backend hace de **intermediario**: el botón graba, el
audio se manda tal cual al servidor (`START_SPEECH` + PCM 16 kHz + `END_SPEECH`) y las respuestas se
traducen a la pantalla del ESP32. Sin esa variable se usa el RAG simulado local (Whisper + `mock_rag.py`).

| Servidor → backend | Backend → ESP32 (pantalla 240×240) |
| --- | --- |
| `STATE THINKING` / `SPEAKING` | `STATE THINKING` ("PENSANDO...") |
| mensaje con texto (`text`, `reply`, `message`...) | `IMAGE_BEGIN` kind `text` (texto con acentos, en páginas si es largo) |
| `SHOW_PRODUCT` | `IMAGE_BEGIN` kind `product`: foto + barra con nombre y precio; 8 s y luego el texto |
| `SHOW_QR` | `IMAGE_BEGIN` kind `qr`: "TOTAL: Bs. XX" + QR (60 s o hasta la próxima pregunta) |
| `PAYMENT_CONFIRMED` | se ignora (`SHOW_PAYMENT_CONFIRMED=false`): por ahora solo se muestra información |
| audio binario del bot | se ignora (no hay parlante) |
| `STATE IDLE` | vuelve la cara, salvo que ya haya una respuesta en pantalla |

Las imágenes las compone el backend con Pillow y llegan al ESP32 ya en RGB565 (`IMAGE_BEGIN` +
frames binarios de 4800 bytes que suman 115200); el ESP32 solo las vuelca a la pantalla. Al ser de
solo lectura, no hay ninguna acción de compra o pago de nuestro lado: lo único que sale hacia el
servidor es el audio de la pregunta y `PING`.

## Voz de las respuestas (suena en tu Mac)

El ESP32 no tiene parlante: la voz del bot suena en los altavoces del Mac y la pantallita muestra la
carita hablando; al terminar, aparece la ficha del producto o el QR (ya no se muestra texto). Docker en
macOS no puede usar los altavoces, así que hay un reproductor aparte que corre **en el Mac**:

```bash
python3 tools/play_replies.py          # déjalo abierto en otra terminal
python3 tools/play_replies.py --dry-run  # baja la voz pero no suena (para probar)
```

Si no está corriendo, el backend avisa en el log (`No hay reproductor conectado`) y la carita habla igual,
pero en silencio.

