"""Configuración del firmware MicroPython. Editar antes de flashear."""

WIFI_SSID = "volobot"
WIFI_PASSWORD = "12345678"

# IP de la máquina donde corre "docker compose up" (backend), puerto 8000 por defecto
WS_HOST = "10.220.77.247"
WS_PORT = 8000
WS_PATH = "/ws/iot"

DEVICE_TOKEN = "volobot-secret-2026"   # debe coincidir con backend/.env
DEVICE_ID = "ESP32-TOTEM-01"

# Pantalla ST7789 240x240 (ver ../docs/PINOUT.md)
TFT_SCK_PIN = 18
TFT_MOSI_PIN = 23
# Velocidad del SPI de la pantalla. 1 MHz es lo probado; si la pantalla lo aguanta (cables cortos),
# 8000000 hace que dibuje ~8 veces más rápido. Si salen colores raros o basura, vuelve a 1000000.
TFT_SPI_BAUD = 1000000
TFT_RST_PIN = 21   # como en el prototipo (VoloBot-IA)
TFT_DC_PIN = 27    # como en el prototipo (VoloBot-IA)
TFT_BLK_PIN = None   # BLK cableado fijo a 3V3

# Qué micrófono hay conectado: "adc" = MAX4466 analógico (módulo morado, GPIO34)
#                              "i2s" = INMP441 digital (placa redonda negra, pines de abajo)
MIC_TYPE = "adc"

# Micrófono MAX4466 (analógico, ADC1). OUT -> GPIO34, VCC -> 3V3, GND -> GND
MIC_ADC_PIN = 34
MIC_SAMPLE_RATE = 8000

# Micrófono INMP441 (I2S) — solo lo usa mic_i2s.py (MIC_TYPE = "i2s").
# VDD->3V3, GND->GND, L/R->GND, SCK->GPIO32, WS->GPIO25, SD->GPIO33
MIC_I2S_SHIFT = 9    # 16 = sin ganancia; cada punto menos duplica el volumen (9 = x128)
MIC_SCK_PIN = 32
MIC_WS_PIN = 25
MIC_SD_PIN = 33

# Cada cuántos ms se imprime en el repl el nivel del micrófono (0..65535), hables o no. 0 = no imprimir.
MIC_LEVEL_INTERVAL_MS = 2000

# True: mantén el botón pulsado y habla; al soltarlo se manda al backend (sin "Hey VoloBot").
# False: audio continuo + "Hey VoloBot" (necesita WAKE_WORD_ENABLED=true en backend/.env).
PUSH_TO_TALK = True

# Botón TEMPORAL (equivale a decir "Hey VoloBot"). Un pie a GPIO13 y el
# otro a GND; usa el pull-up interno. Poner USE_BUTTON = False para desactivarlo.
USE_BUTTON = True
BUTTON_PIN = 13

AUDIO_SAMPLE_RATE = 16000
MIC_CHUNK_SAMPLES = 1024  # muestras por bloque (2 bytes cada una)
