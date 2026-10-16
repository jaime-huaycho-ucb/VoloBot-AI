"""Pantallas 240x240 que el backend compone para el ESP32.

El ESP32 (MicroPython) no decodifica JPEG ni tiene fuentes con acentos, así que el
backend baja las fotos/QR del servidor, dibuja encima nombre, precio y textos con Pillow
y manda el resultado ya en RGB565 (lo que espera la pantalla ST7789), para que el ESP32
solo tenga que volcarlo a la pantalla.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W = H = 240
BAR_H = 50          # barra inferior de la ficha de producto
QR_SIZE = 180       # tamaño del QR (como indica la especificación)

NAVY = (8, 8, 40)
CYAN = (60, 220, 255)
WHITE = (255, 255, 255)
GREEN = (20, 140, 70)


_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",   # la instala el Dockerfile
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    # La fuente por defecto de Pillow no trae acentos ni ¿¡; se usa una TrueType con español.
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _fit(draw: ImageDraw.ImageDraw, text: str, max_width: int, sizes=(20, 18, 16, 14, 12)):
    """Devuelve (texto, fuente) con el mayor tamaño que cabe; si ni así, recorta con '...'."""
    for size in sizes:
        font = _font(size)
        if draw.textlength(text, font=font) <= max_width:
            return text, font
    font = _font(sizes[-1])
    while text and draw.textlength(text + "...", font=font) > max_width:
        text = text[:-1]
    return text + "...", font


def _open(data: bytes | None, size: tuple[int, int]) -> Image.Image | None:
    if not data:
        return None
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None
    return img if img.size == size else img.resize(size, Image.LANCZOS)


def render_product(name: str, price: str, photo: bytes | None) -> Image.Image:
    """Foto del producto + barra inferior con nombre y precio."""
    img = _open(photo, (W, H)) or Image.new("RGB", (W, H), (30, 40, 80))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle([0, H - BAR_H, W, H], fill=(0, 0, 0, 230))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)
    name_text, name_font = _fit(draw, name, W - 16, sizes=(18, 16, 14, 12))
    price_text, price_font = _fit(draw, price, W - 16, sizes=(22, 20, 18, 16))
    draw.text((8, H - BAR_H + 4), name_text, font=name_font, fill=WHITE)
    draw.text((8, H - 27), price_text, font=price_font, fill=(90, 255, 170))
    return img


def render_qr(amount: str, qr_jpeg: bytes | None, qr_data: str | None) -> Image.Image:
    """Fondo blanco, 'TOTAL: Bs. XX.XX' arriba y el QR centrado (180x180)."""
    qr = _open(qr_jpeg, (QR_SIZE, QR_SIZE))
    if qr is None and qr_data:
        import qrcode  # solo si no se pudo bajar la imagen del servidor

        code = qrcode.QRCode(border=2, box_size=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
        code.add_data(qr_data)
        code.make(fit=True)
        qr = code.make_image(fill_color="black", back_color="white").convert("RGB")
        qr = qr.resize((QR_SIZE, QR_SIZE), Image.NEAREST)
    if qr is None:
        raise ValueError("SHOW_QR sin imagen ni qr_data")

    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    title, font = _fit(draw, f"TOTAL: {amount}", W - 12, sizes=(24, 22, 20, 18, 16))
    draw.text(((W - draw.textlength(title, font=font)) / 2, 8), title, font=font, fill=(0, 0, 0))
    img.paste(qr, ((W - QR_SIZE) // 2, 48))
    return img


def render_payment(amount: str, message: str) -> Image.Image:
    """Pantalla de celebración: check verde grande + monto + mensaje."""
    img = Image.new("RGB", (W, H), GREEN)
    draw = ImageDraw.Draw(img)
    draw.ellipse([75, 22, 165, 112], fill=WHITE)
    draw.line([(95, 68), (113, 88), (148, 46)], fill=GREEN, width=11, joint="curve")

    for text, y, sizes in (
        ("PAGO CONFIRMADO", 126, (22, 20, 18, 16)),
        (amount, 156, (26, 24, 22, 20)),
        (message, 194, (16, 14, 12)),
    ):
        text, font = _fit(draw, text, W - 16, sizes=sizes)
        draw.text(((W - draw.textlength(text, font=font)) / 2, y), text, font=font, fill=WHITE)
    return img


def render_text_pages(text: str, title: str = "VOLOBOT", per_page: int = 10) -> list[Image.Image]:
    """Texto largo -> una o más pantallas (con acentos y minúsculas, sin recortar)."""
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = _font(17)
    max_w = W - 20

    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            trial = f"{line} {word}".strip()
            if probe.textlength(trial, font=font) <= max_w:
                line = trial
            else:
                if line:
                    lines.append(line)
                line = word
        lines.append(line)
    lines = lines or [""]

    pages = [lines[i:i + per_page] for i in range(0, len(lines), per_page)]
    images = []
    for n, chunk in enumerate(pages, start=1):
        img = Image.new("RGB", (W, H), NAVY)
        draw = ImageDraw.Draw(img)
        header = title if len(pages) == 1 else f"{title}  {n}/{len(pages)}"
        draw.text((10, 8), header, font=_font(18), fill=CYAN)
        for i, line in enumerate(chunk):
            draw.text((10, 38 + i * 20), line, font=font, fill=WHITE)
        images.append(img)
    return images


def to_rgb565(img: Image.Image) -> bytes:
    """RGB -> RGB565 big-endian (el orden de bytes que espera la ST7789)."""
    a = np.asarray(img.convert("RGB").resize((W, H)), dtype=np.uint16)
    v = ((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)
    return v.astype(">u2").tobytes()
