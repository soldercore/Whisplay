"""Status bar: state badge plus battery / Wi-Fi indicators.

VENDORED (subset) from soldercore/whisplay-ai-chatbot @ 2dd608b,
python/whisplay_ui/statusbar.py. Same geometry and colours; the launcher only
has battery and Wi-Fi data, so VPN/RAG/image tags and plugin icons are left
out. The clock is optional because the launcher only redraws on events and a
stale clock would be misleading.
"""
from PIL import Image, ImageDraw

from . import theme
from .draw_util import draw_text, fit_text

CENTER_Y = 11
GAP = 6


def battery_color(level):
    if level <= 10:
        return theme.RED
    if level <= 30:
        return theme.AMBER
    return theme.GREEN


class StatusBar:
    def __init__(self, fonts):
        self.fonts = fonts

    def render(self, label, color, battery_level=None, wifi_level=None, clock=None):
        image = Image.new("RGB", (theme.WIDTH, theme.STATUS_H), theme.VOID)
        draw = ImageDraw.Draw(image)
        fonts = self.fonts

        # Divider with a state-coloured accent under the badge.
        draw.line([(0, theme.DIVIDER_Y), (theme.WIDTH - 1, theme.DIVIDER_Y)], fill=theme.LINE)

        # ---- left: state badge
        x = theme.CHROME_LEFT
        draw.rectangle([x, CENTER_Y - 3, x + 5, CENTER_Y + 2], fill=color)
        label = fit_text(fonts.pixel8, label, 86)
        left_end = draw_text(draw, image, fonts.pixel8, x + 10, CENTER_Y, label, color)
        draw.line([(x, theme.DIVIDER_Y), (int(left_end), theme.DIVIDER_Y)], fill=color)

        # ---- right cluster, laid out right to left
        right = theme.CHROME_RIGHT
        if isinstance(battery_level, int) and not isinstance(battery_level, bool):
            right = self._battery(draw, image, right, battery_level)
        if wifi_level:
            right = self._wifi(draw, right - GAP, wifi_level)

        if clock:
            stack = fonts.meta_bold
            width = stack.width(clock)
            cx = max(int((theme.WIDTH - width) / 2), int(left_end + GAP))
            if cx + width <= right - GAP:
                draw_text(draw, image, stack, cx, CENTER_Y, clock, theme.MUTED)
        return image

    def _battery(self, draw, image, right, level):
        level = max(0, min(100, int(level)))
        fill = battery_color(level)
        nub_w, body_w, body_h = 2, 20, 10
        x1 = right - nub_w
        x0 = x1 - body_w
        y0 = CENTER_Y - body_h // 2
        y1 = y0 + body_h - 1
        draw.rectangle([x1 + 1, CENTER_Y - 2, x1 + nub_w, CENTER_Y + 1], fill=theme.MUTED)
        draw.rectangle([x0, y0, x1, y1], outline=theme.MUTED)
        inner = body_w - 4
        filled = int(round(inner * level / 100.0))
        if filled > 0:
            draw.rectangle([x0 + 2, y0 + 2, x0 + 1 + filled, y1 - 2], fill=fill)
        text = "%d" % level
        stack = self.fonts.pixel8
        tx = x0 - 3 - stack.width(text)
        draw_text(draw, image, stack, tx, CENTER_Y, text, fill if level <= 30 else theme.MUTED)
        return int(tx)

    def _wifi(self, draw, right, level):
        try:
            level = max(0, min(3, int(level)))
        except (TypeError, ValueError):
            level = 0
        bar_w, gap = 2, 1
        width = 3 * bar_w + 2 * gap
        x = right - width
        base = CENTER_Y + 4
        for index in range(3):
            height = 3 + index * 3
            bx = x + index * (bar_w + gap)
            fill = theme.GREEN if index < level else theme.LINE
            draw.rectangle([bx, base - height + 1, bx + bar_w - 1, base], fill=fill)
        return x
