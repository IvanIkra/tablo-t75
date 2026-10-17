"""Full-screen overlays drawn by the service: Wi-Fi QR and message (§5)."""

import segno
from segno import helpers

from ..config import WifiNetwork
from . import fonts
from .canvas import BLACK, Canvas

MARGIN = 40


def wifi_qr(networks: list[WifiNetwork], font_mode: str = "aliased") -> Canvas:
    c = Canvas(font_mode)
    c.text((400, 24), "Scan to join Wi-Fi", fonts.inter(22, "semibold"), anchor="ma")
    networks = networks[:3]
    if not networks:
        c.text((400, 240), "No Wi-Fi networks configured", fonts.inter(20), anchor="mm")
        return c
    col_w = 800 // len(networks)
    label_h = 40
    top = 70
    max_side = min(col_w - 40, 480 - top - label_h - 20)
    for i, net in enumerate(networks):
        data = helpers.make_wifi_data(
            ssid=net.ssid,
            password=net.password or None,
            security=net.security if net.password else "nopass",
            hidden=net.hidden,
        )
        qr = segno.make(data, error="m", micro=False)
        _draw_qr(c, qr, cx=col_w * i + col_w // 2, top=top, max_side=max_side)
        c.text((col_w * i + col_w // 2, top + max_side + 12), c.fit(net.ssid, fonts.inter(22, "semibold"), col_w - 20),
               fonts.inter(22, "semibold"), anchor="ma")
    return c


def _draw_qr(c: Canvas, qr: segno.QRCode, cx: int, top: int, max_side: int) -> None:
    matrix = [list(row) for row in qr.matrix]
    n = len(matrix)
    quiet = 2
    module = max(1, max_side // (n + 2 * quiet))
    side = module * n
    x0 = cx - side // 2
    y0 = top + (max_side - side) // 2
    for r, row in enumerate(matrix):
        for col, dark in enumerate(row):
            if dark:
                c.rect(x0 + col * module, y0 + r * module, module, module, fill=BLACK)


def message(title: str, text: str, icon: str | None = None, font_mode: str = "aliased") -> Canvas:
    c = Canvas(font_mode)
    x = MARGIN
    if icon:
        c.icon(icon, MARGIN + 32, MARGIN + 32, 64)
        x = MARGIN + 88
    title_font = fonts.inter(34, "semibold")
    c.text((x, MARGIN + 12), c.fit(title or "", title_font, 800 - MARGIN - x), title_font)
    body = fonts.inter(24)
    y = MARGIN + 100
    line_h = 34
    max_lines = (480 - MARGIN - y) // line_h
    lines: list[str] = []
    for para in (text or "").split("\n"):
        lines += c.wrap(para, body, 800 - 2 * MARGIN, max_lines) or [""]
    for i, line in enumerate(lines[:max_lines]):
        c.text((MARGIN, y + i * line_h), line, body)
    return c
