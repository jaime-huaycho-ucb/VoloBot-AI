# Pinout — VoloBot AI (ESP32, MicroPython)

Cableado real (igual al del prototipo VoloBot-IA, sin botón: la activación es por
voz, "Hey VoloBot"). Fase actual: **pantalla + micrófono únicamente** (todavía no
hay altavoz). Firmware en MicroPython.

## Componentes de esta fase
1. ESP32 DevKit V1 (30/38 pines) o ESP32-S3, con MicroPython flasheado.
2. Pantalla LCD TFT 1.3" IPS 240×240 (controlador ST7789, SPI de 7 pines, sin pin CS).
3. Micrófono analógico MAX4466 en GPIO34 (igual que el prototipo VoloBot-IA). El código de audio está
   aislado con el patrón Adapter (`firmware/mic_base.py`, `mic_adc.py`, `mic_i2s.py`): cambiar de
   micrófono es cambiar `MIC_TYPE` en `config.py`, sin tocar el resto del firmware.

## Tabla de pines

| Periférico | Pin del módulo | Pin del ESP32 | Función |
| :--- | :--- | :--- | :--- |
| Pantalla ST7789 | GND | GND | Tierra |
| | VCC | 3V3 | Alimentación lógica |
| | SCL | GPIO 18 | SPI Clock (SCK) |
| | SDA | GPIO 23 | SPI Data (MOSI) |
| | RES | GPIO 21 | Reset |
| | DC | GPIO 27 | Data/Command |
| | BLK | 3V3 | Backlight |
| Mic MAX4466 (analógico), `MIC_TYPE = "adc"` | VCC | 3V3 | Alimentar a 3,3 V (rango del ADC) |
| | GND | GND | Tierra común |
| | OUT | GPIO 34 | ADC1, solo entrada |
| Mic INMP441 (I2S, placa redonda), `MIC_TYPE = "i2s"` | VDD | 3V3 | Nunca a 5V |
| | GND | GND | Tierra |
| | L/R | GND | Canal izquierdo (mono); si queda al aire llegan ceros |
| | SCK | GPIO 32 | BCLK |
| | WS | GPIO 25 | LRCLK |
| | SD | GPIO 33 | Datos del micrófono |

Los dos micrófonos pueden estar cableados a la vez (usan pines distintos); `MIC_TYPE` en
`firmware/config.py` decide cuál se lee. Los módulos vienen sin pines: hay que soldarlos.

## Advertencias
- El módulo ST7789 de 7 pines no tiene `CS`: queda a tierra de fábrica y
  escucha todo en GPIO18/GPIO23. No comparas esos pines con ningún otro
  periférico SPI.
- Si todavía tienen el MAX4466 cableado del prototipo (GPIO34, analógico) en
  vez del INMP441, basta con poner `MIC_TYPE = "adc"` en `firmware/config.py`
  (`"i2s"` para el INMP441); el resto del firmware no depende de cuál mic se use.
- `machine.I2S` requiere una build de MicroPython para ESP32 con soporte de
  I2S habilitado (estándar en las builds genéricas "esp32-generic" desde
  ~v1.19). Si el `import I2S` falla, hay que reflashear con una build que lo
  incluya.

## Pendiente para cuando haya altavoz
Agregar amplificador I2S (p. ej. MAX98357A) en un segundo bus I2S, un nuevo
módulo `speaker_io.py`, y el TTS en el backend. No afecta lo que ya está
armado.
