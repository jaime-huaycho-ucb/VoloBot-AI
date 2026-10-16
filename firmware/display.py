"""Driver ST7789 (SPI, sin pin CS) + fuente bitmap + wrap de texto.

Portado del prototipo (VoloBot-IA/firmware/main.py), adaptado a los pines
oficiales de esta fase y al nuevo protocolo (estados IDLE/LISTENING/THINKING
+ mensaje DISPLAY con el texto de respuesta del RAG).
"""

from machine import Pin, SPI
import random
import time

import config

WIDTH = 240
HEIGHT = 240
SCALE = 2
CHAR_W = 5
CHAR_H = 7
TEXT_WIDTH_CHARS = 18
LINES_PER_PAGE = 8

BLACK = 0x0000
WHITE = 0xFFFF
CYAN = 0x07FF
NAVY = 0x0841
GREEN = 0x07E0

FONT = {
    "A": (14,17,17,31,17,17,17), "B": (30,17,17,30,17,17,30),
    "C": (14,17,16,16,16,17,14), "D": (30,17,17,17,17,17,30),
    "E": (31,16,16,30,16,16,31), "F": (31,16,16,30,16,16,16),
    "G": (14,17,16,23,17,17,14), "H": (17,17,17,31,17,17,17),
    "I": (31,4,4,4,4,4,31), "J": (7,2,2,2,18,18,12),
    "K": (17,18,20,24,20,18,17), "L": (16,16,16,16,16,16,31),
    "M": (17,27,21,21,17,17,17), "N": (17,25,21,19,17,17,17),
    "O": (14,17,17,17,17,17,14), "P": (30,17,17,30,16,16,16),
    "Q": (14,17,17,17,21,18,13), "R": (30,17,17,30,20,18,17),
    "S": (15,16,16,14,1,1,30), "T": (31,4,4,4,4,4,4),
    "U": (17,17,17,17,17,17,14), "V": (17,17,17,17,17,10,4),
    "W": (17,17,17,21,21,21,10), "X": (17,17,10,4,10,17,17),
    "Y": (17,17,10,4,4,4,4), "Z": (31,1,2,4,8,16,31),
    "0": (14,17,19,21,25,17,14), "1": (4,12,4,4,4,4,14),
    "2": (14,17,1,2,4,8,31), "3": (30,1,1,14,1,1,30),
    "4": (2,6,10,18,31,2,2), "5": (31,16,16,30,1,1,30),
    "6": (14,16,16,30,17,17,14), "7": (31,1,2,4,8,8,8),
    "8": (14,17,17,14,17,17,14), "9": (14,17,17,15,1,1,14),
    " ": (0,0,0,0,0,0,0), ".": (0,0,0,0,0,12,12),
    ",": (0,0,0,0,0,12,8), "!": (4,4,4,4,4,0,4),
    "?": (14,17,1,2,4,0,4), ":": (0,12,12,0,12,12,0),
    ";": (0,12,12,0,12,8,0), "-": (0,0,0,31,0,0,0),
    "_": (0,0,0,0,0,0,31), "'": (4,4,8,0,0,0,0),
    '"': (10,10,0,0,0,0,0), "/": (1,2,2,4,8,8,16),
    "(": (2,4,8,8,8,4,2), ")": (8,4,2,2,2,4,8),
    "+": (0,4,4,31,4,4,0), "=": (0,31,0,31,0,0,0),
    "*": (0,17,10,31,10,17,0), "%": (17,2,4,8,16,17,0),
}

spi = SPI(2, baudrate=getattr(config, "TFT_SPI_BAUD", 1_000_000), polarity=1, phase=1,
          sck=Pin(config.TFT_SCK_PIN), mosi=Pin(config.TFT_MOSI_PIN))
dc = Pin(config.TFT_DC_PIN, Pin.OUT)
rst = Pin(config.TFT_RST_PIN, Pin.OUT)
if config.TFT_BLK_PIN is not None:
    blk = Pin(config.TFT_BLK_PIN, Pin.OUT)
    blk.value(1)


def _command(cmd, data=None):
    dc.value(0)
    spi.write(bytes((cmd,)))
    if data is not None:
        dc.value(1)
        spi.write(data)


def _set_window(x0, y0, x1, y1):
    _command(0x2A, bytes((x0 >> 8, x0 & 255, x1 >> 8, x1 & 255)))
    _command(0x2B, bytes((y0 >> 8, y0 & 255, y1 >> 8, y1 & 255)))
    _command(0x2C)


def fill_rect(x, y, width, height, color):
    if x < 0:
        width += x
        x = 0
    if y < 0:
        height += y
        y = 0
    if x + width > WIDTH:
        width = WIDTH - x
    if y + height > HEIGHT:
        height = HEIGHT - y
    if width <= 0 or height <= 0:
        return
    _set_window(x, y, x + width - 1, y + height - 1)
    dc.value(1)
    pixel = bytes((color >> 8, color & 255))
    row = pixel * width
    for _ in range(height):
        spi.write(row)


def draw_char(x, y, char, color, scale=SCALE):
    glyph = FONT.get(char, (0, 0, 0, 0, 0, 0, 0))
    for row, bits in enumerate(glyph):
        col = 0
        while col < CHAR_W:
            if bits & (1 << (CHAR_W - 1 - col)):
                start = col
                while col < CHAR_W and bits & (1 << (CHAR_W - 1 - col)):
                    col += 1
                fill_rect(x + start * scale, y + row * scale,
                          (col - start) * scale, scale, color)
            else:
                col += 1


def draw_text(x, y, text, color, scale=SCALE):
    step = (CHAR_W + 1) * scale
    for char in text.upper():
        draw_char(x, y, char, color, scale)
        x += step


def wrap_text(text):
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        line = ""
        for word in words:
            while len(word) > TEXT_WIDTH_CHARS:
                if line:
                    lines.append(line)
                    line = ""
                lines.append(word[:TEXT_WIDTH_CHARS])
                word = word[TEXT_WIDTH_CHARS:]
            candidate = word if not line else line + " " + word
            if len(candidate) <= TEXT_WIDTH_CHARS:
                line = candidate
            else:
                lines.append(line)
                line = word
        if line or not words:
            lines.append(line)
    return lines or [""]


def init():
    rst.value(1); time.sleep_ms(100)
    rst.value(0); time.sleep_ms(100)
    rst.value(1); time.sleep_ms(200)
    _command(0x01); time.sleep_ms(150)   # SWRESET
    _command(0x11); time.sleep_ms(150)   # SLPOUT
    _command(0x3A, b"\x55")               # RGB565
    _command(0x36, b"\x00")
    _command(0x21)                         # INVON (requerido por este módulo)
    _command(0x13)                         # NORON
    _command(0x29); time.sleep_ms(100)   # DISPON
    fill_rect(0, 0, WIDTH, HEIGHT, NAVY)


# ------------------------------------------------------------------ cara del bot
# Se dibuja con formas simples (círculos, elipses, líneas) sobre fondo negro. Cada estado tiene su
# expresión; en reposo parpadea y de vez en cuando mira a un lado (tick()). Las transiciones solo
# borran las zonas que cambian, porque el SPI es lento y mientras se dibuja no se lee el micrófono.

def rgb(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


EYE = rgb(0, 225, 195)
PUPIL = rgb(0, 30, 50)
BROW = rgb(0, 165, 145)
MOUTH = rgb(0, 225, 195)
CHEEK = rgb(185, 55, 90)
MOUTH_IN = rgb(110, 15, 40)   # interior de la boca abierta
EYE_Y = 98
EYE_X = (70, 170)
_LOOKS = ((0, 0), (-9, 2), (9, 2))

_state = None
_mood = "neutral"
_screen = "other"   # "face" mientras la cara está en pantalla; "other" con imagen o texto
_eye_r = 0          # radio de los ojos dibujados ahora
_mouth = 0          # apertura de la boca al hablar: 0 cerrada, 1 media, 2 abierta
_look = (0, 0)
_next_blink = 0


def fill_circle(cx, cy, r, color):
    r2 = r * r
    for dy in range(-r, r + 1):
        dx = int((r2 - dy * dy) ** 0.5)
        fill_rect(cx - dx, cy + dy, 2 * dx + 1, 1, color)


def fill_ellipse(cx, cy, rx, ry, color):
    for dy in range(-ry, ry + 1):
        dx = int(rx * (1 - (dy * dy) / (ry * ry)) ** 0.5)
        fill_rect(cx - dx, cy + dy, 2 * dx + 1, 1, color)


def _line(x0, y0, x1, y1, t, color):
    n = max(abs(x1 - x0), 1)
    for i in range(0, n + 1, 2):
        fill_rect(x0 + (x1 - x0) * i // n - 1, y0 + (y1 - y0) * i // n - t // 2, 4, t, color)


def _arc(cx, cy, half_w, depth, t, color):
    """Curva tipo sonrisa: extremos en cy y centro `depth` px más abajo (depth negativo = triste)."""
    hw2 = half_w * half_w
    for x in range(-half_w, half_w + 1, 2):
        y = cy + depth * (hw2 - x * x) // hw2
        fill_rect(cx + x - 1, y - t // 2, 4, t, color)


def _eye(cx, r, pr, look):
    fill_circle(cx, EYE_Y, r, EYE)
    px = cx + look[0]
    py = EYE_Y + look[1]
    fill_circle(px, py, pr, PUPIL)
    fill_circle(px - pr // 3, py - pr // 3, max(3, pr // 4), WHITE)       # brillo grande
    fill_circle(px + pr // 3, py + pr // 3, max(2, pr // 8), WHITE)       # brillo chico


def _eye_closed(cx, r):
    fill_rect(cx - r - 1, EYE_Y - r - 1, 2 * r + 3, 2 * r + 3, BLACK)   # +1: el círculo llega hasta cx±r
    _arc(cx, EYE_Y - 4, r - 8, 9, 6, EYE)


def _brow(cx, by, tilt, color=BROW):
    _line(cx - 22, by + tilt[0], cx + 22, by + tilt[1], 5, color)


def _face_params(state, mood):
    """(radio, pupila, mirada, ceja izq, ceja der, alzada, boca, sonrisa, mejillas)"""
    r, pr, look = 36, 20, _look
    lb, rb, up = (2, -2), (-2, 2), 0
    mouth, depth, cheeks = "smile", 12, True
    if state == "LISTENING":                      # atento: ojos grandes, cejas arriba, boca en "o"
        r, pr, look = 42, 26, (0, 0)
        lb, rb, up = (0, -4), (-4, 0), 6
        mouth, cheeks = "o", False
    elif state == "THINKING":                     # pensando: mira arriba a un lado, una ceja alzada
        r, pr, look = 36, 18, (12, -12)
        lb, rb = (4, 2), (-6, -10)
        mouth, cheeks = "flat", False
    else:                                         # IDLE o SPEAKING
        if state == "SPEAKING":
            mouth = "speak"                       # la boca la mueve set_mouth() al ritmo de la voz
        if mood == "happy":
            depth = 18
        elif mood == "curious":
            rb = (-8, -10)
        elif mood == "excited":
            r, pr, up, depth = 40, 24, 4, 20
        elif mood == "sad":                       # triste: cejas caídas por fuera, mira abajo, boca al revés
            look, lb, rb = (0, 6), (6, -2), (-2, 6)
            mouth, cheeks = "frown", False
    return r, pr, look, lb, rb, up, mouth, depth, cheeks


def _draw_face(p):
    global _eye_r
    r, pr, look, lb, rb, up, mouth, depth, cheeks = p
    _eye_r = r
    for cx in EYE_X:
        _eye(cx, r, pr, look)
    by = EYE_Y - r - 14 - up
    _brow(EYE_X[0], by, lb)
    _brow(EYE_X[1], by, rb)
    if cheeks:
        fill_circle(38, 150, 11, CHEEK)
        fill_circle(202, 150, 11, CHEEK)
    if mouth == "smile":
        _arc(120, 166, 30, depth, 5, MOUTH)
    elif mouth == "o":
        fill_ellipse(120, 176, 13, 15, MOUTH)
        fill_ellipse(120, 176, 7, 9, BLACK)
    elif mouth == "frown":
        _arc(120, 184, 26, -10, 5, MOUTH)
    elif mouth == "speak":
        _draw_mouth_level(0)
    else:
        _line(100, 176, 140, 170, 5, MOUTH)


def _draw_mouth_level(level):
    if level == 0:                                # cerrada: sonrisa chica
        _arc(120, 168, 22, 7, 5, MOUTH)
    elif level == 1:                              # media
        fill_ellipse(120, 174, 17, 8, MOUTH)
    else:                                         # abierta, con interior
        fill_ellipse(120, 176, 20, 17, MOUTH)
        fill_ellipse(120, 180, 14, 11, MOUTH_IN)


def set_mouth(level):
    """Mueve la boca mientras habla (0, 1 o 2). Solo redibuja la boca, así es rápido."""
    global _mouth
    if _screen != "face" or _state != "SPEAKING" or level == _mouth:
        return
    _mouth = level
    fill_rect(86, 150, 68, 46, BLACK)
    _draw_mouth_level(level)


def _erase_zones(old_r, new_r, old_state):
    """Borra solo lo que puede cambiar entre dos caras (mucho más rápido que limpiar todo)."""
    for cx in EYE_X:
        fill_rect(cx - 34, 20, 68, 42, BLACK)                        # cejas (los ojos se redibujan encima)
        if new_r < old_r:                                            # ojos que se achican
            e = old_r + 2
            fill_rect(cx - e, EYE_Y - e, 2 * e, 2 * e, BLACK)
    fill_rect(60, 150, 120, 56, BLACK)                               # boca
    fill_rect(22, 136, 30, 30, BLACK)                                # mejillas
    fill_rect(188, 136, 30, 30, BLACK)
    if old_state in ("LISTENING", "THINKING"):                       # barras / texto de abajo
        fill_rect(0, 200, WIDTH, 40, BLACK)


def set_state(state, mood="neutral"):
    """Muestra la cara del estado (IDLE, LISTENING, THINKING). Si ya está, no redibuja."""
    global _state, _mood, _screen, _look, _next_blink, _mouth
    if _screen == "face" and state == _state and mood == _mood:
        return
    _look = (0, 0)
    p = _face_params(state, mood)
    if _screen != "face":
        fill_rect(0, 0, WIDTH, HEIGHT, BLACK)                        # venía de una imagen o texto
    else:
        _erase_zones(_eye_r, p[0], _state)
    _mouth = 0
    _state, _mood, _screen = state, mood, "face"
    _draw_face(p)
    if state == "LISTENING":                                         # ecualizador
        for i, h in enumerate((10, 18, 30, 20, 28, 14, 8)):
            fill_rect(63 + i * 17, 232 - h, 11, h, CYAN)
    elif state == "THINKING":
        draw_text(34, 205, "PENSANDO", WHITE, 1)
        for i in range(3):
            fill_circle(112 + i * 14, 209, 3, CYAN)
    _next_blink = time.ticks_add(time.ticks_ms(), 3000)


def tick():
    """Animación en reposo (parpadeo y mirada). Llamar seguido; solo actúa con la cara en IDLE."""
    global _next_blink, _look
    if _screen != "face" or _state != "IDLE":
        return
    if time.ticks_diff(time.ticks_ms(), _next_blink) < 0:
        return
    p = _face_params("IDLE", _mood)
    for cx in EYE_X:
        _eye_closed(cx, p[0])
    time.sleep_ms(90)
    if random.getrandbits(2) == 0:                                   # 1 de cada 4 veces mira a un lado
        _look = _LOOKS[random.getrandbits(2) % 3]
    for cx in EYE_X:
        _eye(cx, p[0], p[1], _look)
    _next_blink = time.ticks_add(time.ticks_ms(), 2500 + random.getrandbits(11) * 2)


def image_begin():
    global _screen
    _screen = "other"
    """Prepara la pantalla para recibir una imagen RGB565 240x240 (big-endian) por trozos."""
    _set_window(0, 0, WIDTH - 1, HEIGHT - 1)
    dc.value(1)


def image_chunk(data):
    spi.write(data)


def show_text(text):
    global _screen
    _screen = "other"
    fill_rect(0, 0, WIDTH, HEIGHT, NAVY)
    draw_text(10, 12, "VOLOBOT", CYAN, 2)
    lines = wrap_text(text)
    shown = lines[:LINES_PER_PAGE]
    for idx, line in enumerate(shown):
        draw_text(10, 44 + idx * 20, line, WHITE, SCALE)
    if len(lines) > LINES_PER_PAGE:
        draw_text(10, 224, "...", CYAN, 1)  # TODO: paginar si el texto es largo
