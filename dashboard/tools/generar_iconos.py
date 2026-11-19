"""Genera los íconos del PWA (marca de hoja bermellón con reloj, sobre papel). Uso, desde la raíz del proyecto:

    python dashboard/tools/generar_iconos.py

Escribe en dashboard/app/static/pwa/: icon-192.png, icon-512.png, icon-maskable-512.png y apple-touch-icon.png.
(icon.svg se mantiene a mano con el mismo dibujo.) Requiere Pillow.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

SALIDA = Path(__file__).resolve().parent.parent / "app" / "static" / "pwa"
PAPEL, LINEA, TINTA, ACENTO = "#f3ecdb", "#e1d6bd", "#1f1b14", "#b8381a"
SS = 4  # supermuestreo para bordes suaves


def _hoja(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: str) -> None:
    """Círculo con la esquina inferior izquierda cuadrada (el mismo `.app-mark` del dashboard)."""
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    draw.rectangle((cx - r, cy, cx, cy + r), fill=color)


def _marca(tam: int, radio: float) -> Image.Image:
    """Capa transparente con la hoja (con sombra dura), el anillo y las manecillas del reloj, rotada -8°."""
    capa = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    c = tam / 2
    desplaz = radio * 0.07
    _hoja(d, c + desplaz, c + desplaz, radio, TINTA)       # sombra dura
    _hoja(d, c, c, radio, ACENTO)
    ancho = max(2, round(radio * 0.10))
    ring = radio * 0.56
    d.ellipse((c - ring, c - ring, c + ring, c + ring), outline=PAPEL, width=ancho)
    d.line((c, c, c, c - ring * 0.62), fill=PAPEL, width=ancho)                                      # minutero
    d.line((c, c, c + ring * 0.46 * math.cos(math.radians(30)), c + ring * 0.46 * math.sin(math.radians(30))),
           fill=PAPEL, width=ancho)                                                                    # horario
    d.ellipse((c - ancho, c - ancho, c + ancho, c + ancho), fill=PAPEL)
    return capa.rotate(8, resample=Image.BICUBIC)  # PIL rota en sentido antihorario; 8° ≈ -8° del CSS


def _fondo(tam: int, redondeado: bool) -> Image.Image:
    img = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cuerpo = Image.new("RGBA", (tam, tam), PAPEL)
    cd = ImageDraw.Draw(cuerpo)
    paso = tam / 16
    for i in range(1, 16):                                   # renglones de cuaderno
        y = round(i * paso)
        cd.line((0, y, tam, y), fill=LINEA, width=max(1, tam // 256))
    cd.line((tam * 0.16, 0, tam * 0.16, tam), fill="#e7b9a8", width=max(1, tam // 170))  # margen rojo
    if redondeado:
        mascara = Image.new("L", (tam, tam), 0)
        ImageDraw.Draw(mascara).rounded_rectangle((0, 0, tam - 1, tam - 1), radius=round(tam * 0.22), fill=255)
        img.paste(cuerpo, (0, 0), mascara)
    else:
        img.paste(cuerpo, (0, 0))
    return img


def icono(tam: int, maskable: bool = False) -> Image.Image:
    g = tam * SS
    img = _fondo(g, redondeado=not maskable)
    # maskable: todo el contenido dentro de la zona segura (círculo central del 80 %)
    radio = g * (0.27 if maskable else 0.33)
    img = Image.alpha_composite(img, _marca(g, radio))
    return img.resize((tam, tam), Image.LANCZOS)


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    for nombre, tam, mask in (("icon-192.png", 192, False), ("icon-512.png", 512, False),
                              ("icon-maskable-512.png", 512, True), ("apple-touch-icon.png", 180, False)):
        icono(tam, mask).save(SALIDA / nombre, optimize=True)
        print("escrito", SALIDA / nombre)


if __name__ == "__main__":
    main()
