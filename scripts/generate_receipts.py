"""Generador determinista de recibos sintéticos para las pruebas de la Etapa 3.

Crea en `data/receipts/` tres imágenes con comercios FICTICIOS y sin datos
personales, más `expected.json` con los valores esperados:

- `receipt_normal.jpg`: recibo nítido.
- `receipt_hard.jpg`: rotado, con ruido, bajo contraste, fecha dd/mm/aaaa y
  monto con separador de miles.
- `receipt_illegible.jpg`: muy desenfocado y cortado; fecha y total ilegibles.

Dependencia solo de generación de datos: Pillow (no se usa para OCR).

Uso:
    .venv\\Scripts\\python scripts\\generate_receipts.py
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "receipts"
SEED = 20260930
WIDTH = 520

Item = tuple[str, int]


def _money(value: int) -> str:
    """Formato CLP con punto como separador de miles (ej.: $12.990)."""
    return "$" + f"{value:,}".replace(",", ".")


def render_receipt(
    merchant: str,
    subtitle: str,
    date_text: str,
    items: list[Item],
    total: int,
    ink: tuple[int, int, int] = (25, 25, 25),
    paper: tuple[int, int, int] = (250, 249, 244),
    money_style: str = "plain",
) -> Image.Image:
    """Dibuja un recibo simple de ancho fijo y devuelve la imagen RGB."""
    title_font = ImageFont.load_default(size=30)
    body_font = ImageFont.load_default(size=22)
    small_font = ImageFont.load_default(size=17)
    total_font = ImageFont.load_default(size=28)
    fmt = _money if money_style == "thousands" else (lambda v: f"${v}")

    height = 330 + 40 * len(items)
    img = Image.new("RGB", (WIDTH, height), paper)
    draw = ImageDraw.Draw(img)
    margin = 32
    y = 28

    def centered(text: str, font: ImageFont.FreeTypeFont, y_pos: int) -> None:
        w = draw.textlength(text, font=font)
        draw.text(((WIDTH - w) / 2, y_pos), text, font=font, fill=ink)

    centered(merchant, title_font, y)
    y += 46
    centered(subtitle, small_font, y)
    y += 40
    draw.line((margin, y, WIDTH - margin, y), fill=ink, width=2)
    y += 14
    draw.text((margin, y), f"FECHA: {date_text}", font=body_font, fill=ink)
    y += 40
    draw.line((margin, y, WIDTH - margin, y), fill=ink, width=1)
    y += 14
    for name, price in items:
        draw.text((margin, y), name, font=body_font, fill=ink)
        text = fmt(price)
        w = draw.textlength(text, font=body_font)
        draw.text((WIDTH - margin - w, y), text, font=body_font, fill=ink)
        y += 40
    y += 4
    draw.line((margin, y, WIDTH - margin, y), fill=ink, width=2)
    y += 16
    draw.text((margin, y), "TOTAL", font=total_font, fill=ink)
    text = fmt(total)
    w = draw.textlength(text, font=total_font)
    draw.text((WIDTH - margin - w, y), text, font=total_font, fill=ink)
    y += 60
    centered("Documento sintetico, sin validez", small_font, y)
    return img


def make_normal() -> tuple[Image.Image, dict]:
    items = [
        ("Pan molde", 1990),
        ("Leche 1 L x2", 2180),
        ("Arroz 1 kg", 1590),
        ("Aceite 900 ml", 3290),
        ("Detergente", 4890),
        ("Queso laminado", 4550),
    ]
    total = sum(p for _, p in items)
    img = render_receipt(
        "SUPERMERCADO LOS AROMOS",
        "Sucursal Centro - Boleta N 000123",
        "2026-09-12",
        items,
        total,
    )
    expected = {
        "fecha": "2026-09-12",
        "comercio": "Los Aromos",
        "monto": total,
        "categoria": "Supermercado",
        "dificultad": "normal",
    }
    return img, expected


def make_hard(rng: random.Random) -> tuple[Image.Image, dict]:
    items = [
        ("Sandwich de pollo", 4990),
        ("Jugo natural", 2500),
        ("Torta de manzana", 5500),
    ]
    total = sum(p for _, p in items)
    img = render_receipt(
        "CAFETERIA LUNA AZUL",
        "Local 12 - Boleta N 004871",
        "05/09/2026",
        items,
        total,
        ink=(90, 90, 90),
        paper=(205, 200, 190),
        money_style="thousands",
    )
    # Ruido gaussiano aproximado y determinista (suma de bytes aleatorios).
    w, h = img.size
    noise = Image.frombytes("L", (w, h), rng.randbytes(w * h)).convert("RGB")
    img = Image.blend(img, noise, 0.12)
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    img = img.rotate(4.5, expand=True, resample=Image.BICUBIC, fillcolor=(150, 148, 142))
    expected = {
        "fecha": "2026-09-05",
        "comercio": "Luna Azul",
        "monto": total,
        "categoria": "Alimentación",
        "dificultad": "difícil",
    }
    return img, expected


def make_illegible() -> tuple[Image.Image, dict]:
    items = [
        ("Tornillos 50 un", 2490),
        ("Pintura 1 gal", 15990),
        ("Brocha 3 in", 3290),
    ]
    total = sum(p for _, p in items)
    img = render_receipt(
        "FERRETERIA PIEDRA AZUL",
        "Sucursal Norte - Boleta N 000777",
        "17/09/2026",
        items,
        total,
    )
    # Desenfoque fuerte y recorte: se pierden fecha y total.
    img = img.filter(ImageFilter.GaussianBlur(11))
    img = img.crop((0, 0, img.width, int(img.height * 0.55)))
    expected = {
        "fecha": "desconocido",
        "comercio": "desconocido",
        "monto": "desconocido",
        "categoria": "desconocido",
        "dificultad": "ilegible",
    }
    return img, expected


def generate(out_dir: Path = DEFAULT_OUT) -> dict[str, dict]:
    """Genera las imágenes y `expected.json`; devuelve lo esperado por archivo."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    builders = {
        "receipt_normal.jpg": make_normal,
        "receipt_hard.jpg": lambda: make_hard(rng),
        "receipt_illegible.jpg": make_illegible,
    }
    expected: dict[str, dict] = {}
    for name, build in builders.items():
        img, exp = build()
        img.save(out_dir / name, format="JPEG", quality=80)
        expected[name] = exp
    (out_dir / "expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return expected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    expected = generate(args.out_dir)
    for name in expected:
        print(f"generado: {args.out_dir / name}")
    print(f"generado: {args.out_dir / 'expected.json'}")


if __name__ == "__main__":
    main()
