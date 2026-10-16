# Firmware VoloBot (ESP32, MicroPython)

Firmware oficial en **MicroPython**, pensado para flashearse igual que el
prototipo (Thonny, por USB), pero con la arquitectura definitiva: WiFi +
WebSocket hacia el backend (en vez de USB-serial), y pantalla + micrófono
cableados a los pines oficiales. Fase actual: sin altavoz.

## Requisitos
- ESP32 con firmware **MicroPython** ya flasheado (build genérica
  "esp32-generic", con soporte de `machine.I2S`).
- [Thonny](https://thonny.org/) para subir los archivos.
- Cableado según `../docs/PINOUT.md`.

## Configurar
Edita `config.py` antes de subir:
- `WIFI_SSID`, `WIFI_PASSWORD`
- `WS_HOST` (IP de la máquina donde corre `docker compose up`), `WS_PORT`
- `DEVICE_TOKEN` (igual al `DEVICE_TOKEN` del backend)
- `DEVICE_ID`

## Subir los archivos
Con Thonny, interprete MicroPython (ESP32) seleccionado y el puerto USB de la
placa:

1. Abre cada archivo de esta carpeta (`config.py`, `display.py`, `mic.py`,
   `mic_base.py`, `mic_adc.py`, `mic_i2s.py`, `ws_client.py`, `main.py`) y usa **Archivo → Guardar como… → MicroPython
   device**, guardando cada uno con el mismo nombre en la placa.
2. Reinicia el ESP32 (botón RESET o reconectar USB). Debe conectarse al WiFi,
   luego al backend, y la pantalla debe mostrar la cara en reposo (IDLE).
3. Cierra la sesión serie de Thonny antes de iniciar el backend si vas a
   mirar logs por USB; no es necesario para el funcionamiento normal (el
   ESP32 ya no depende del USB una vez conectado al WiFi).

## Archivos
- `display.py`: driver ST7789 (sin librerías externas, portado del
  prototipo) + wrap de texto para la respuesta del RAG.
- `mic.py`, `mic_base.py`, `mic_adc.py`, `mic_i2s.py`: micrófonos con el patrón
  Adapter. `MIC_TYPE` en `config.py` elige `"adc"` (MAX4466) o `"i2s"` (INMP441);
  `mic_compare.py` los compara a la vez (ver `../docs/ARQUITECTURA.md`).
- `ws_client.py`: cliente WebSocket mínimo (handshake + frames), sin
  dependencias externas.
- `main.py`: máquina de estados (botón → START_SPEECH → streaming de audio →
  END_SPEECH → espera DISPLAY).

## Pendiente
- Altavoz/TTS (ver `../README.md` → "Próximos pasos").
