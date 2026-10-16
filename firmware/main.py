"""VoloBot (fase sin altavoz).

Modo por defecto (config.PUSH_TO_TALK = True): mantén el botón pulsado y habla; el audio
del micrófono se manda al backend mientras el botón está presionado. Al soltarlo, el backend
transcribe, consulta el RAG y devuelve STATE / DISPLAY, que se muestran en la pantalla.

Con PUSH_TO_TALK = False el ESP32 transmite audio continuo y el backend detecta "Hey VoloBot"
(requiere WAKE_WORD_ENABLED=true en backend/.env); el botón, si USE_BUTTON, manda WAKE.
"""

import time
import ujson as json
import network
from machine import Pin

import config
import display
from ws_client import WebSocketClient

from mic import create_microphone

mic = create_microphone()   # adaptador según config.MIC_TYPE; main solo usa la interfaz Microphone

ws = None
server_state = "IDLE"
button = None
image_left = 0   # bytes de imagen que faltan por recibir (IMAGE_BEGIN + frames binarios)

# Solo modo wake word: la interrupción levanta una bandera (antirrebote 300 ms).
_button_flag = False
_button_last = 0


def _on_button(_pin):
    global _button_flag, _button_last
    now = time.ticks_ms()
    if time.ticks_diff(now, _button_last) > 300:
        _button_last = now
        _button_flag = True


def init_button():
    global button
    if config.PUSH_TO_TALK:
        button = Pin(config.BUTTON_PIN, Pin.IN, Pin.PULL_UP)
        print("Modo botón (mantener y hablar) en GPIO", config.BUTTON_PIN)
    elif config.USE_BUTTON:
        btn = Pin(config.BUTTON_PIN, Pin.IN, Pin.PULL_UP)
        btn.irq(trigger=Pin.IRQ_FALLING, handler=_on_button)
        print("Modo Hey VoloBot + botón WAKE en GPIO", config.BUTTON_PIN)


def take_button():
    global _button_flag
    if _button_flag:
        _button_flag = False
        return True
    return False


def connect_wifi():
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    if not sta.isconnected():
        print("Conectando a WiFi...")
        sta.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        while not sta.isconnected():
            time.sleep_ms(300)
    print("WiFi OK:", sta.ifconfig())


def ws_path():
    return "{}?token={}&role=device&device_id={}&rate={}".format(
        config.WS_PATH, config.DEVICE_TOKEN, config.DEVICE_ID, mic.sample_rate
    )


def send_action(action, extra=None):
    payload = {"action": action}
    if extra:
        payload.update(extra)
    ws.send_text(json.dumps(payload))


def handle_server_message(opcode, payload):
    global server_state, image_left
    if opcode == 0x2:  # binario: trozos de la imagen que anunció IMAGE_BEGIN
        if image_left > 0:
            display.image_chunk(payload)
            image_left -= len(payload)
            if image_left <= 0:
                image_left = 0
                print("<- imagen completa")
        return
    if opcode != 0x1:
        return
    image_left = 0  # cualquier mensaje de texto nuevo corta una imagen que haya quedado a medias
    try:
        data = json.loads(payload)
    except ValueError:
        print("JSON inválido:", payload)
        return

    msg_type = data.get("type")
    if msg_type == "STATE":
        server_state = data.get("state", "IDLE")
        print("<- STATE:", server_state, data.get("mood", ""))
        display.set_state(server_state, data.get("mood", "neutral"))
    elif msg_type == "MOUTH":
        display.set_mouth(data.get("level", 0))
    elif msg_type == "IMAGE_BEGIN":
        image_left = data.get("size", 0)
        server_state = "IDLE"   # con una imagen en pantalla ya se puede volver a grabar
        print("<- IMAGE_BEGIN:", data.get("kind"), image_left, "bytes")
        display.image_begin()
    elif msg_type == "DISPLAY":
        print("<- DISPLAY:", data.get("text", ""))
        display.show_text(data.get("text", ""))
    elif msg_type == "PONG":
        pass


def connect_ws():
    global ws
    ws = WebSocketClient(config.WS_HOST, config.WS_PORT, ws_path())
    ws.connect()
    print("WebSocket conectado a", config.WS_HOST, config.WS_PORT)


def main():
    display.init()
    display.set_state("IDLE")

    connect_wifi()
    mic.init()
    init_button()
    connect_ws()

    last_ping = time.ticks_ms()
    last_stat = time.ticks_ms()
    last_level = time.ticks_ms()
    sent_bytes = 0
    recording = False

    while True:
        if not ws.connected:
            if recording:
                print("Se cayó la conexión grabando; descarto la grabación")
                recording = False
            print("WS desconectado, reintentando en 2s...")
            time.sleep_ms(2000)
            try:
                connect_ws()
            except OSError as exc:
                print("Reintento falló:", exc)
            continue

        try:
            frame = ws.poll()
            if frame:
                handle_server_message(*frame)

            if config.PUSH_TO_TALK:
                if recording:
                    chunk = mic.read_chunk()
                    ws.send_binary(chunk)
                    sent_bytes += len(chunk)
                    if button.value() == 1:        # soltado
                        time.sleep_ms(20)          # antirrebote
                        if button.value() == 1:
                            ws.send_binary(mic.read_chunk())  # cola: no cortar la última palabra
                            send_action("END_SPEECH", {"device_id": config.DEVICE_ID})
                            recording = False
                            print("botón soltado -> END_SPEECH (nivel mic: %d)" % mic.last_peak)
                elif button.value() == 0 and server_state != "THINKING":
                    time.sleep_ms(20)              # antirrebote
                    if button.value() == 0:
                        display.set_state("LISTENING")   # primero la cara (el SPI es lento), luego a grabar
                        mic.flush()             # sin audio viejo del I2S
                        send_action("START_SPEECH")
                        recording = True
                        print("botón pulsado -> START_SPEECH")
            else:
                if take_button():
                    print("botón -> WAKE")
                    send_action("WAKE")
                chunk = mic.read_chunk()
                if chunk and ws.connected:
                    ws.send_binary(chunk)
                    sent_bytes += len(chunk)

            if time.ticks_diff(time.ticks_ms(), last_ping) > 25000:
                send_action("PING")
                last_ping = time.ticks_ms()
        except OSError as exc:
            print("Error de red:", exc)
            ws.close()
            continue

        if (
            config.MIC_LEVEL_INTERVAL_MS
            and not recording
            and time.ticks_diff(time.ticks_ms(), last_level) >= config.MIC_LEVEL_INTERVAL_MS
        ):
            level = mic.measure_level()
            last_level = time.ticks_ms()
            note = "  <- SIN SEÑAL" if level == 0 else ("  <- SATURADO" if level >= 64000 else "")
            print("nivel mic: %5d / 65535%s" % (level, note))

        if not config.PUSH_TO_TALK and time.ticks_diff(time.ticks_ms(), last_stat) > 5000:
            print("audio enviado: %d KB | nivel mic: %d" % (sent_bytes // 1024, mic.last_peak))
            last_stat = time.ticks_ms()

        if not recording:
            display.tick()   # parpadeo y mirada de la cara en reposo
            time.sleep_ms(5)


print("Iniciando en 3 s (Ctrl+C ahora para detener y poder copiar archivos)")
time.sleep(3)

while True:
    try:
        main()
    except Exception as exc:
        print("VOLOBOT_ERROR:", exc)
        time.sleep_ms(3000)
