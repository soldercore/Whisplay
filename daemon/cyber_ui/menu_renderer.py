"""Cyber-terminal launcher renderer.

Drop-in replacement for daemon_renderer.DesktopRenderer: the same two entry
points (render, render_internal_app) with the same arguments. It only draws;
app discovery, navigation, button handling and focus stay in the daemon.

Home uses a compact status bar and seven application rows. Internal pages retain
their existing cyber-terminal layout. No rendering method reads device state.
"""
from __future__ import annotations

import os
import time

from PIL import Image, ImageDraw

from daemon_shared import image_to_rgb565_bytes, app_display_name

from . import theme
from .draw_util import corner_brackets, dotted, draw_text, fit_text
from .fonts import Fonts
from .statusbar import StatusBar
from .home_icons import application_icon

# Base font for glyphs the bundled fonts lack (CJK app names, symbols).
# CJK-capable fonts first; DejaVu is what the classic launcher uses.
BASE_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

FOOTER_Y = theme.HEIGHT - theme.APPROVAL_H
FOOTER_MID = theme.APPROVAL_H // 2 - 2
DESKTOP_ROWS = 7
HOME_LIST_TOP = 34
HOME_ROW_H = 28
LIST_ROW_H = 40
LIST_ROWS = 3
LIST_TOP = theme.PANE_Y + theme.STRIP_H
STATUS_PANE_H = 44


def default_base_font():
    for path in BASE_FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


class CyberDesktopRenderer:
    def __init__(self, board, script_dir: str, base_font_path: str | None = None, font_dir: str | None = None):
        self.board = board
        self.script_dir = script_dir
        base = base_font_path if base_font_path is not None else default_base_font()
        self.fonts = Fonts(base, font_dir=font_dir) if font_dir else Fonts(base)
        self.statusbar = StatusBar(self.fonts)
        # Internal app pages get no status data from the daemon; reuse the
        # last values the desktop received so the status bar stays consistent.
        self._wifi_signal_level = None
        self._battery_level = None
        self._wireless_status = None
        print(f"[WhisplayDaemon] Cyber menu UI fonts: {self.fonts.loaded}")

    # ------------------------------------------------------------ helpers
    def _frame(self):
        image = Image.new("RGB", (theme.WIDTH, theme.HEIGHT), theme.VOID)
        return image, ImageDraw.Draw(image)

    def _push(self, image):
        self.board.draw_image(0, 0, theme.WIDTH, theme.HEIGHT, image_to_rgb565_bytes(image))

    def _status(self, image, label, color):
        bar = self.statusbar.render(label, color, self._battery_level, self._wifi_signal_level, wireless_status=self._wireless_status)
        image.paste(bar, (0, 0))

    def _chips(self, draw, image, chips, y_mid, top_line=True):
        """Approval-bar style key chips, centred as a group."""
        fonts = self.fonts
        if top_line:
            draw.line([(theme.CHROME_LEFT, FOOTER_Y), (theme.CHROME_RIGHT - 1, FOOTER_Y)], fill=theme.LINE)
        widths = []
        for key, label, _fg, _border in chips:
            key_w = int(fonts.pixel8.width(key)) + 7
            widths.append(key_w + 6 + int(fonts.meta_bold.width(label)))
        gap = 12
        total = sum(widths) + gap * (len(chips) - 1)
        x = max(theme.CHROME_LEFT, int((theme.WIDTH - total) / 2))
        for (key, label, fg, border), width in zip(chips, widths):
            key_w = int(fonts.pixel8.width(key)) + 7
            draw.rectangle([x, y_mid - 7, x + key_w, y_mid + 6], outline=border)
            draw_text(draw, image, fonts.pixel8, x + 4, y_mid, key, fg)
            draw_text(draw, image, fonts.meta_bold, x + key_w + 6, y_mid, label, theme.TEXT)
            x += width + gap

    def _cursor(self, draw, x, baseline, color=theme.GREEN):
        draw.rectangle([x, baseline - 12, x + theme.CURSOR_W - 1, baseline + 1], fill=color)

    # ------------------------------------------------------------ desktop
    def render(
        self,
        apps,
        selected_index: int,
        pending_app_id: str | None = None,
        running_app_id: str | None = None,
        wifi_signal_level: int | None = None,
        battery_level: int | None = None,
        wireless_status=None,
    ):
        self._wifi_signal_level = wifi_signal_level
        self._battery_level = battery_level
        self._wireless_status = wireless_status
        image = Image.new("RGB", (theme.WIDTH, theme.HEIGHT), theme.HOME_BG)
        draw = ImageDraw.Draw(image)
        apps = list(apps or [])
        if apps:
            selected_index %= len(apps)
        bar = self.statusbar.render_home(self._battery_level, self._wireless_status,
                                         wifi_level=self._wifi_signal_level, clock=time.strftime("%H:%M"))
        image.paste(bar, (0, 0))
        if not apps:
            draw_text(draw, image, self.fonts.body, 36, 116, "No applications", theme.MUTED)
        else:
            self._render_app_list(draw, image, apps, selected_index, pending_app_id)
            error = str(getattr(apps[selected_index], "last_error", "") or "")
            if error:
                draw_text(draw, image, self.fonts.meta, 24, 235,
                          fit_text(self.fonts.meta, error, 192), theme.AMBER)
        self._chips(draw, image, (
            ("TAP", "NEXT", theme.GREEN, theme.GREEN_DIM),
            ("HOLD", "OPEN", theme.GREEN, theme.GREEN_DIM),
        ), FOOTER_Y + FOOTER_MID)
        self._push(image)

    def _visible_rows(self, total, selected_index):
        """Keep a contiguous viewport still until selection reaches its edge."""
        start = min(getattr(self, "_home_start", 0), max(0, total - DESKTOP_ROWS))
        if selected_index < start:
            start = selected_index
        elif selected_index >= start + DESKTOP_ROWS:
            start = selected_index - DESKTOP_ROWS + 1
        self._home_start = start
        return list(range(start, min(total, start + DESKTOP_ROWS)))

    def _render_app_list(self, draw, image, apps, selected_index, pending_app_id):
        fonts, total = self.fonts, len(apps)
        visible = self._visible_rows(total, selected_index)
        for row, idx in enumerate(visible):
            app = apps[idx]
            y = HOME_LIST_TOP + row * HOME_ROW_H
            mid = y + HOME_ROW_H // 2
            selected = idx == selected_index
            if selected:
                draw.rounded_rectangle((14, y+1, 220, y+HOME_ROW_H-2), radius=4,
                                       fill=theme.RAISED, outline=theme.GREEN_MID)
                draw_text(draw, image, fonts.pixel8, 21, mid, ">", theme.GREEN)
            else:
                draw.line((60, y+HOME_ROW_H-1, 218, y+HOME_ROW_H-1), fill=theme.LINE)
            icon = application_icon(app.app_id, selected)
            image.paste(icon, (31, mid-8), icon)
            draw.line((52, mid-6, 52, mid+6), fill=theme.LINE)
            marker = "OPEN" if pending_app_id == app.app_id else "RUN" if app.is_running() else ""
            marker_width = fonts.pixel8.width(marker) + 10 if marker else 0
            name = fit_text(fonts.body, app_display_name(app), 154-marker_width)
            draw_text(draw, image, fonts.body, 60, mid, name, theme.BRIGHT if selected else theme.TEXT)
            if marker:
                draw_text(draw, image, fonts.pixel8, int(213-fonts.pixel8.width(marker)), mid,
                          marker, theme.GREEN if marker == "RUN" else theme.CYAN)
        if total > DESKTOP_ROWS:
            top, bottom = HOME_LIST_TOP+3, HOME_LIST_TOP+DESKTOP_ROWS*HOME_ROW_H-4
            span = bottom-top
            thumb = max(12, int(span*DESKTOP_ROWS/total))
            pos = top+int((span-thumb)*visible[0]/max(1,total-DESKTOP_ROWS))
            draw.line((226, top, 226, bottom), fill=theme.LINE)
            draw.line((226, pos, 226, pos+thumb), fill=theme.GREEN_MID)

    # ------------------------------------------------------- internal apps
    def render_internal_app(self, view_model: dict):
        if view_model.get("kind") == "keyboard":
            self._render_keyboard(view_model)
            return
        self._render_list_page(view_model)

    def _render_list_page(self, view_model: dict):
        fonts = self.fonts
        image, draw = self._frame()
        title = str(view_model.get("title") or "System")
        subtitle = str(view_model.get("subtitle") or "")
        items = list(view_model.get("items") or [])
        selected_index = int(view_model.get("selected_index") or 0)
        status = str(view_model.get("status") or "")
        busy = bool(view_model.get("busy"))
        detail_lines = [str(line) for line in (view_model.get("detail_lines") or [])]
        accent = theme.AMBER if busy else theme.GREEN
        self._status(image, title.upper(), accent)

        # Strip: subtitle left, position right (console strip of the chatbot).
        mid = theme.PANE_Y + 12
        x = theme.CHROME_LEFT
        draw_text(draw, image, fonts.pixel8, x, mid, ">", accent)
        end = draw_text(draw, image, fonts.pixel8, x + 9, mid, fit_text(fonts.pixel8, (subtitle or title).upper(), 150), accent)
        if items:
            selected_index = max(0, min(selected_index, len(items) - 1))
            pos = "%02d/%02d" % (selected_index + 1, len(items))
            width = fonts.pixel8.width(pos)
            if theme.CHROME_RIGHT - width > end + 8:
                draw_text(draw, image, fonts.pixel8, int(theme.CHROME_RIGHT - width), mid, pos, theme.DIM)
        dotted(draw, LIST_TOP - 1)

        if not items:
            fonts.prompt.draw(draw, image, theme.TEXT_LEFT, LIST_TOP + 26, "no items", theme.AMBER)
        else:
            visible = min(LIST_ROWS, len(items))
            start = max(0, min(selected_index, len(items) - visible))
            for row, idx in enumerate(range(start, start + visible)):
                item = items[idx]
                y = LIST_TOP + 4 + row * LIST_ROW_H
                selected = idx == selected_index
                if selected:
                    draw.rectangle([10, y, theme.WIDTH - 11, y + LIST_ROW_H - 3], fill=theme.RAISED, outline=theme.GREEN_DIM)
                    draw_text(draw, image, fonts.pixel8, theme.CHROME_LEFT, y + 11, ">", theme.GREEN)
                    title_color, meta_color = theme.BRIGHT, theme.GREEN_MID
                elif abs(idx - selected_index) == 1:
                    title_color, meta_color = theme.MUTED, theme.DIM
                else:
                    title_color, meta_color = theme.DIM, theme.DIM
                text_x = theme.CHROME_LEFT + 14
                max_w = theme.CHROME_RIGHT - 4 - text_x
                fonts.body.draw(draw, image, text_x, y + 16, fit_text(fonts.body, str(item.get("title") or ""), max_w), title_color)
                meta = str(item.get("meta") or "")
                if meta:
                    fonts.meta.draw(draw, image, text_x, y + 31, fit_text(fonts.meta, meta, max_w), meta_color)
            if len(items) > LIST_ROWS:
                span_top = LIST_TOP + 2
                span_bottom = LIST_TOP + LIST_ROWS * LIST_ROW_H
                span = span_bottom - span_top
                thumb = max(8, int(span * LIST_ROWS / float(len(items))))
                pos = span_top + int((span - thumb) * selected_index / float(max(1, len(items) - 1)))
                draw.line([(theme.WIDTH - 6, pos), (theme.WIDTH - 6, pos + thumb)], fill=theme.GREEN_DIM)

        lines = detail_lines[:2] if detail_lines else [status]
        self._status_pane(draw, image, lines, busy)
        self._chips(draw, image, (
            ("TAP", "NEXT", theme.GREEN, theme.GREEN_DIM),
            ("HOLD", "SELECT", theme.GREEN, theme.GREEN_DIM),
        ), FOOTER_Y + FOOTER_MID)
        self._push(image)

    def _status_pane(self, draw, image, lines, busy):
        """Command-output pane of the chatbot ('$ EXEC' header + mono lines)."""
        fonts = self.fonts
        top = FOOTER_Y - STATUS_PANE_H
        x = theme.CHROME_LEFT
        draw_text(draw, image, fonts.pixel8, x, top + 7, "$ STATUS", theme.CYAN)
        draw.line([(x + 50, top + 7), (theme.CHROME_RIGHT - 1, top + 7)], fill=theme.CYAN_DIM)
        width = theme.CHROME_RIGHT - x
        for index, line in enumerate(lines[:2]):
            if not line:
                continue
            color = (theme.AMBER if busy else theme.GREEN) if index == 0 else theme.MUTED
            fonts.meta.draw(draw, image, x, top + 24 + index * 12, fit_text(fonts.meta, line, width), color)

    def _render_keyboard(self, view_model: dict):
        fonts = self.fonts
        image, draw = self._frame()
        title = str(view_model.get("title") or "Keyboard")
        subtitle = str(view_model.get("subtitle") or "")
        password = str(view_model.get("password") or "")
        password_length = int(view_model.get("password_length") or 0)
        status = str(view_model.get("status") or "")
        self._status(image, title.upper(), theme.GREEN)

        mid = theme.PANE_Y + 12
        draw_text(draw, image, fonts.pixel8, theme.CHROME_LEFT, mid, ">", theme.GREEN)
        draw_text(draw, image, fonts.pixel8, theme.CHROME_LEFT + 9, mid, fit_text(fonts.pixel8, subtitle.upper() or "NETWORK", 190), theme.GREEN)
        dotted(draw, LIST_TOP - 1)

        top = LIST_TOP + 8
        draw_text(draw, image, fonts.pixel8, theme.CHROME_LEFT, top + 4, "PASSWORD", theme.DIM)
        box_top = top + 12
        draw.rectangle([10, box_top, theme.WIDTH - 11, box_top + 26], fill=theme.RAISED, outline=theme.GREEN_DIM)
        baseline = box_top + 19
        text_x = theme.CHROME_LEFT
        max_w = theme.CHROME_RIGHT - text_x - theme.CURSOR_W - 6
        if password:
            shown = password
            while shown and fonts.body.width(shown) > max_w:
                shown = shown[1:]
            end = fonts.body.draw(draw, image, text_x, baseline, shown, theme.GREEN)
        else:
            end = text_x
        self._cursor(draw, int(end + 2), baseline)

        count_y = box_top + 52
        fonts.prompt.draw(draw, image, theme.CHROME_LEFT, count_y, "%d chars typed" % password_length, theme.AMBER)
        fonts.meta.draw(draw, image, theme.CHROME_LEFT, count_y + 18, "Type on the external keyboard.", theme.MUTED)
        self._chips(draw, image, (
            ("ENTER", "CONNECT", theme.GREEN, theme.GREEN_DIM),
            ("ESC", "CANCEL", theme.RED, theme.RED_DIM),
        ), count_y + 40, top_line=False)

        self._status_pane(draw, image, [status], False)
        self._chips(draw, image, (
            ("BKSP", "DELETE", theme.CYAN, theme.CYAN_DIM),
        ), FOOTER_Y + FOOTER_MID)
        self._push(image)
