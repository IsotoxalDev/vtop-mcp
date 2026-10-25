"""
Best-effort local OCR for VTOP's plain text/image login captcha.

This deliberately does NOT attempt to solve Google reCAPTCHA (VTOP sometimes serves
that instead of the plain image captcha): reCAPTCHA is specifically designed to resist
automated solving, and defeating it generally means paying a third-party captcha-solving
service -- that crosses from "automating my own tedious login" into circumventing another
site's (Google's) anti-bot protections, which this project won't do. When VTOP serves
reCAPTCHA, vtop_login falls back to a visible browser window for a human to solve it.
"""

import base64
import io
import re

import pytesseract
from PIL import Image, ImageOps

_ALLOWED_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def solve_default_captcha(data_uri: str) -> str:
    """OCR VTOP's default captcha image (a data: URI) into its best-guess text.

    Not guaranteed correct -- the caller should retry with a fresh captcha on rejection."""
    match = re.match(r"data:image/[^;]+;base64,(.*)", data_uri, re.DOTALL)
    raw = base64.b64decode(match.group(1) if match else data_uri)

    image = Image.open(io.BytesIO(raw)).convert("L")
    scale = max(1, 300 // max(image.width, 1))
    if scale > 1:
        image = image.resize((image.width * scale, image.height * scale), Image.LANCZOS)
    image = ImageOps.autocontrast(image)
    image = image.point(lambda p: 255 if p > 140 else 0)

    text = pytesseract.image_to_string(
        image,
        config=f'--psm 7 -c tessedit_char_whitelist="{_ALLOWED_CHARS}"',
    )
    return "".join(ch for ch in text if ch in _ALLOWED_CHARS)
