"""Render the launcher to PNG without Whisplay hardware.

Uses the production FallbackDesktopRenderer (and the classic DesktopRenderer
for comparison) with an in-memory board that decodes the RGB565 frames back
to pixels, so the PNGs show exactly what the LCD receives.

Run from the daemon directory:
    python3 -m cyber_ui.preview                    # -> cyber_ui/preview_out/
    python3 -m cyber_ui.preview --out /tmp/menu
"""
from __future__ import annotations

import argparse
import os
import sys

DAEMON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if DAEMON_DIR not in sys.path:
    sys.path.insert(0, DAEMON_DIR)

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from daemon_models import AppRecord  # noqa: E402

W, H = 240, 280


class FakeBoard:
    """Stands in for WhisplayBoard: keeps the last frame as RGB pixels."""

    LCD_WIDTH = W
    LCD_HEIGHT = H

    def __init__(self):
        self.fb = np.zeros((H, W, 3), dtype=np.uint8)
        self.draws = []

    def draw_image(self, x, y, width, height, pixel_data):
        if x + width > W or y + height > H or x < 0 or y < 0:
            raise ValueError("Image dimensions exceed screen bounds")
        data = np.frombuffer(bytes(pixel_data), dtype=">u2").reshape(height, width)
        r = ((data >> 11) & 0x1F).astype(np.uint16)
        g = ((data >> 5) & 0x3F).astype(np.uint16)
        b = (data & 0x1F).astype(np.uint16)
        rgb = np.dstack(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))).astype(np.uint8)
        self.fb[y:y + height, x:x + width] = rgb
        self.draws.append((x, y, width, height))

    def image(self):
        return Image.fromarray(self.fb.copy(), "RGB")


class _RunningProcess:
    def poll(self):
        return None


def make_app(app_id, display_name, running=False, priority=0):
    app = AppRecord(app_id=app_id, display_name=display_name, priority=priority)
    if running:
        app.process = _RunningProcess()
    return app


def default_apps(running_id=None):
    """The apps a stock daemon shows, in daemon order (priority, then name)."""
    specs = [
        ("whisplay-bluetooth", "Bluetooth", 200),
        ("whisplay-wifi", "WiFi", 190),
        ("whisplay-volume", "Volume", 180),
        ("whisplay-system", "Power", 170),
        ("whisplay-ai-chatbot", "AI Chatbot", 100),
        ("whisplay-jump", "Jump Game", 25),
        ("whisplay-flappy-bird", "Flappy Bird", 20),
        ("whisplay-play-mp4", "Play MP4", 10),
        ("whisplay-run-test", "Run Test", 10),
    ]
    return [make_app(a, n, a == running_id, p) for a, n, p in specs]


LIST_POWER = {
    "kind": "list",
    "title": "Power Menu",
    "subtitle": "Device controls",
    "items": [
        {"title": "Back", "meta": "Return to desktop"},
        {"title": "Lock screen", "meta": "Sleep display"},
        {"title": "Reboot", "meta": "Restart device"},
        {"title": "Shutdown", "meta": "Power off device"},
    ],
    "selected_index": 1,
    "status": "Ready",
    "busy": False,
}
LIST_WIFI_BUSY = {
    "kind": "list",
    "title": "WiFi",
    "subtitle": "",
    "items": [
        {"title": "Back", "meta": "Return to desktop"},
        {"title": "Refresh list", "meta": "Long press to rescan"},
        {"title": "HomeNetwork-5G", "meta": "82% WPA2 | connected"},
        {"title": "A very long hotspot name that will not fit", "meta": "40% WPA2 | saved"},
    ],
    "selected_index": 2,
    "status": "Scanning...",
    "busy": True,
    "detail_lines": ["Scanning for networks...", "IP 192.168.1.42"],
}
LIST_VOLUME = {
    "kind": "list",
    "title": "Volume",
    "subtitle": "Current 60%",
    "items": [{"title": "Back", "meta": "Return to desktop"}]
    + [{"title": f"{p}%", "meta": "current" if p == 60 else "set level"} for p in range(0, 101, 20)],
    "selected_index": 4,
    "status": "Volume 60%",
    "busy": False,
}
LIST_EMPTY = {"kind": "list", "title": "Bluetooth", "items": [], "status": "Bluetooth off", "busy": False}
KEYBOARD = {
    "kind": "keyboard",
    "title": "WiFi Password",
    "subtitle": "HomeNetwork-5G",
    "password": "correct-horse-battery-staple",
    "password_length": 28,
    "status": "Press Enter to connect",
}


def scenarios():
    """(name, callable(renderer)) pairs covering every launcher screen."""
    long_names = [
        make_app("long-1", "Extremely Long Application Name For Testing Overflow", priority=9),
        make_app("long-2", "另一个非常长的中文应用名称测试", priority=8),
        make_app("long-3", "Short", priority=7),
    ]
    many = [make_app(f"app-{i:02d}", f"Application {i:02d}", priority=50 - i) for i in range(14)]
    return [
        ("desktop", lambda r: r.render(default_apps(), 0, None, None, 3, 87)),
        ("desktop_selected", lambda r: r.render(default_apps(), 4, None, None, 2, 64)),
        ("desktop_app_running_list", lambda r: r.render(default_apps("whisplay-jump"), 5, None, None, 3, 25)),
        ("desktop_many_apps", lambda r: r.render(many, 9, None, None, 1, 8)),
        ("desktop_two_apps", lambda r: r.render(default_apps()[:2], 1, None, None, 3, 100)),
        ("desktop_long_names", lambda r: r.render(long_names, 0, None, None, 3, 87)),
        ("desktop_empty", lambda r: r.render([], 0, None, None, None, None)),
        ("launch_pending", lambda r: r.render(default_apps(), 4, "whisplay-ai-chatbot", None, 3, 87)),
        ("app_running_modal", lambda r: r.render(default_apps("whisplay-jump"), 5, None, "whisplay-jump", 3, 87)),
        ("power_menu", lambda r: r.render_internal_app(LIST_POWER)),
        ("wifi_busy", lambda r: r.render_internal_app(LIST_WIFI_BUSY)),
        ("volume", lambda r: r.render_internal_app(LIST_VOLUME)),
        ("list_empty", lambda r: r.render_internal_app(LIST_EMPTY)),
        ("wifi_keyboard", lambda r: r.render_internal_app(KEYBOARD)),
    ]


def safe_area_violations(fb, theme):
    """Pixels that break the rounded-corner safe area (same check as the
    chatbot's dev/preview_ui.py). fb is an (H, W, 3) frame.

    - nothing lit inside any corner curve of radius SAFE_CHECK_RADIUS, except
      the full-width status divider hairline;
    - status-bar content (rows above DIVIDER_Y) only between
      STATUS_SAFE_LEFT and STATUS_SAFE_RIGHT (both columns inclusive).
    """
    problems = []
    radius = theme.SAFE_CHECK_RADIUS
    ys, xs = np.mgrid[0:radius, 0:radius]
    curve = (radius - xs) ** 2 + (radius - ys) ** 2 > radius ** 2
    lit = fb.any(axis=2)
    corners = {
        "top-left": (slice(0, radius), slice(0, radius), False, False),
        "top-right": (slice(0, radius), slice(W - radius, W), False, True),
        "bottom-left": (slice(H - radius, H), slice(0, radius), True, False),
        "bottom-right": (slice(H - radius, H), slice(W - radius, W), True, True),
    }
    for name, (rows, cols, flip_y, flip_x) in corners.items():
        mask = curve[::-1] if flip_y else curve
        mask = mask[:, ::-1] if flip_x else mask
        for y, x in zip(*np.nonzero(lit[rows, cols] & mask)):
            ay, ax = y + rows.start, x + cols.start
            if ay == theme.DIVIDER_Y and tuple(fb[ay, ax]) == theme.LINE:
                continue
            problems.append(f"{name} corner pixel at ({ax},{ay})")
    status = lit[:theme.DIVIDER_Y]
    cols = np.flatnonzero(status.any(axis=0))
    if cols.size and (cols[0] < theme.STATUS_SAFE_LEFT or cols[-1] > theme.STATUS_SAFE_RIGHT):
        problems.append(f"status content spans x={cols[0]}..{cols[-1]}")
    return problems


def render_all(make_renderer):
    shots = []
    for name, action in scenarios():
        board = FakeBoard()
        renderer = make_renderer(board)
        action(renderer)
        shots.append((name, board.image()))
    return shots


def lcd_view(image, scale=1):
    if scale != 1:
        image = image.resize((W * scale, H * scale), Image.NEAREST)
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, image.width - 1, image.height - 1], radius=20 * scale, fill=255)
    return Image.composite(image, Image.new("RGB", image.size, (24, 24, 24)), mask)


def contact_sheet(shots, columns=4):
    pad, label_h = 12, 18
    rows = (len(shots) + columns - 1) // columns
    sheet = Image.new("RGB", (pad + columns * (W + pad), pad + rows * (H + label_h + pad)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(os.path.join(os.path.dirname(__file__), "fonts", "JetBrainsMono-Medium.ttf"), 12)
    except Exception:
        font = ImageFont.load_default()
    for index, (name, image) in enumerate(shots):
        x = pad + (index % columns) * (W + pad)
        y = pad + (index // columns) * (H + label_h + pad)
        draw.text((x, y), name, font=font, fill=(200, 200, 200))
        sheet.paste(lcd_view(image), (x, y + label_h))
    return sheet


def main():
    from cyber_ui.fallback import FallbackDesktopRenderer
    from daemon_renderer import DesktopRenderer

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview_out"))
    parser.add_argument("--scale", type=int, default=2, help="pixel scale for single-screen PNGs")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    os.environ.pop("WHISPLAY_MENU_UI", None)
    cyber = render_all(lambda board: FallbackDesktopRenderer(board, DAEMON_DIR))
    classic = render_all(lambda board: DesktopRenderer(board, DAEMON_DIR))
    for name, image in cyber:
        lcd_view(image, args.scale).save(os.path.join(args.out, f"{name}.png"))
    contact_sheet(cyber).save(os.path.join(args.out, "contact_sheet.png"))
    pairs = []
    for (name, c), (_, k) in zip(cyber, classic):
        pairs += [(name + " / cyber", c), (name + " / classic", k)]
    contact_sheet(pairs[:8], columns=4).save(os.path.join(args.out, "compare_classic.png"))
    print(f"[preview] {len(cyber)} screens -> {args.out}")


if __name__ == "__main__":
    main()
