"""Cyber-terminal launcher renderer.

Drop-in replacement for daemon_renderer.DesktopRenderer: the same two entry
points (render, render_internal_app) with the same arguments. It only draws;
app discovery, navigation, button handling and focus stay in the daemon.

Layout mirrors the chatbot's terminal UI (soldercore/whisplay-ai-chatbot,
python/whisplay_ui): 23 px status bar, a bracketed 80 px "stage" with a 24 px
caption row, a 20 px-line body, and the approval-bar style action chips at the
bottom. Frames are static: the only motion is the launch progress dots, which
the daemon already re-renders while an app is starting.
"""
from __future__ import annotations

import os
import time

from PIL import Image, ImageDraw

from daemon_shared import image_to_rgb565_bytes

from . import theme
from .draw_util import corner_brackets, dotted, draw_text, fit_text
from .fonts import Fonts
from .statusbar import StatusBar

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

PROMPT = (("pi@whisplay", theme.GREEN), (":", theme.MUTED), ("~", theme.CYAN), ("$", theme.MUTED))
MID = theme.STAGE_VISUAL_H // 2
CAPTION_MID = theme.STAGE_H - theme.STAGE_VISUAL_H - 11   # caption centre line (caption coords)
FOOTER_Y = theme.HEIGHT - theme.APPROVAL_H
FOOTER_MID = theme.APPROVAL_H // 2 - 2
DESKTOP_ROWS = 5
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
        print(f"[WhisplayDaemon] Cyber menu UI fonts: {self.fonts.loaded}")

    # ------------------------------------------------------------ helpers
    def _frame(self):
        image = Image.new("RGB", (theme.WIDTH, theme.HEIGHT), theme.VOID)
        return image, ImageDraw.Draw(image)

    def _push(self, image):
        self.board.draw_image(0, 0, theme.WIDTH, theme.HEIGHT, image_to_rgb565_bytes(image))

    def _status(self, image, label, color):
        bar = self.statusbar.render(label, color, self._battery_level, self._wifi_signal_level)
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

    def _caption(self, draw, image, top, label, color, right="", right_color=theme.DIM):
        """Chatbot caption row: '> LABEL' left, detail right, dotted rule."""
        fonts = self.fonts
        mid = top + CAPTION_MID
        x = theme.CHROME_LEFT
        draw_text(draw, image, fonts.pixel8, x, mid, ">", color)
        end = draw_text(draw, image, fonts.pixel8, x + 9, mid, fit_text(fonts.pixel8, label, 150), color)
        if right:
            text = fit_text(fonts.pixel8, right, theme.CHROME_RIGHT - end - 10)
            width = fonts.pixel8.width(text)
            draw_text(draw, image, fonts.pixel8, int(theme.CHROME_RIGHT - width), mid, text, right_color)
        dotted(draw, top + (theme.STAGE_H - theme.STAGE_VISUAL_H) - 1)

    def _prompt(self, draw, image, center_x, baseline, suffix="", stack=None):
        stack = stack or self.fonts.meta_bold
        parts = list(PROMPT) + ([(" " + suffix, theme.MUTED)] if suffix else [])
        width = sum(stack.width(text) for text, _ in parts)
        x = int(center_x - width / 2) if center_x is not None else theme.CHROME_LEFT
        for text, fill in parts:
            x = stack.draw(draw, image, x, baseline, text, fill)
        return x

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
    ):
        self._wifi_signal_level = wifi_signal_level
        self._battery_level = battery_level
        image, draw = self._frame()
        apps = list(apps or [])
        total = len(apps)
        modal_app_id = pending_app_id or running_app_id
        if pending_app_id:
            label, color = "LAUNCH", theme.CYAN
        elif running_app_id:
            label, color = "RUNNING", theme.GREEN
        else:
            label, color = "HOME", theme.GREEN
        self._status(image, label, color)

        stage_top = theme.PANE_Y
        corner_brackets(draw, 8, stage_top + 3, theme.WIDTH - 9, stage_top + theme.STAGE_VISUAL_H - 4, 5, theme.LINE)
        if not apps:
            self._render_empty(draw, image, stage_top)
        else:
            selected_index %= total
            selected = apps[selected_index]
            self._render_hero(draw, image, stage_top, selected, selected_index, total, pending_app_id)
            self._caption(
                draw, image, stage_top + theme.STAGE_VISUAL_H, "APPS", theme.GREEN,
                "%d INSTALLED" % total,
            )
            self._render_app_list(draw, image, apps, selected_index, pending_app_id)
        self._chips(draw, image, (
            ("TAP", "NEXT", theme.GREEN, theme.GREEN_DIM),
            ("HOLD", "OPEN", theme.GREEN, theme.GREEN_DIM),
            ("4X", "HOME", theme.CYAN, theme.CYAN_DIM),
        ), FOOTER_Y + FOOTER_MID)
        if modal_app_id:
            self._render_modal(draw, image, apps, modal_app_id, bool(pending_app_id))
        self._push(image)

    def _render_hero(self, draw, image, top, app, index, total, pending_app_id):
        fonts = self.fonts
        cx = theme.WIDTH // 2
        self._prompt(draw, image, cx, top + 22, "open")
        stack = fonts.prompt
        name = fit_text(stack, app.display_name or app.app_id, 190)
        width = stack.width(name) + 4 + theme.CURSOR_W
        x = int(cx - width / 2)
        baseline = top + MID + 6
        name_color = theme.GREEN if pending_app_id == app.app_id else theme.BRIGHT
        end = stack.draw(draw, image, x, baseline, name, name_color)
        self._cursor(draw, int(end + 4), baseline)
        running = app.is_running()
        state = "RUNNING" if running else "STOPPED"
        meta = "%s  %02d/%02d" % (state, index + 1, total)
        meta_w = fonts.pixel8.width(meta) + 9
        mx = int(cx - meta_w / 2)
        my = top + 62
        if running:
            draw.rectangle([mx, my - 3, mx + 5, my + 2], fill=theme.GREEN)
        else:
            draw.rectangle([mx, my - 3, mx + 5, my + 2], outline=theme.DIM)
        draw_text(draw, image, fonts.pixel8, mx + 9, my, meta, theme.GREEN if running else theme.DIM)

    def _visible_rows(self, total, selected_index):
        """Indices to show: everything when it fits, otherwise a circular
        window centred on the selection (navigation wraps around)."""
        if total <= DESKTOP_ROWS:
            return list(range(total))
        half = DESKTOP_ROWS // 2
        return [(selected_index + offset) % total for offset in range(-half, half + 1)]

    def _render_app_list(self, draw, image, apps, selected_index, pending_app_id):
        fonts = self.fonts
        total = len(apps)
        top = theme.BODY_TOP_STAGE + theme.BODY_PAD
        for row, idx in enumerate(self._visible_rows(total, selected_index)):
            app = apps[idx]
            y = top + row * theme.LINE_H
            mid = y + theme.LINE_H // 2
            selected = idx == selected_index
            distance = 0
            if not selected:
                distance = min((idx - selected_index) % total, (selected_index - idx) % total)
            if selected:
                draw.rectangle([10, y + 1, theme.WIDTH - 11, y + theme.LINE_H - 2], fill=theme.RAISED, outline=theme.GREEN_DIM)
                draw_text(draw, image, fonts.pixel8, theme.CHROME_LEFT, mid, ">", theme.GREEN)
                color = theme.GREEN if pending_app_id == app.app_id else theme.BRIGHT
            else:
                draw_text(draw, image, fonts.pixel8, theme.CHROME_LEFT, mid, "%02d" % (idx + 1), theme.DIM)
                color = theme.MUTED if distance <= 1 else theme.DIM
            tag_w = 0
            if app.is_running():
                tag_w = self._tag(draw, image, theme.CHROME_RIGHT - 2, mid, "RUN", theme.GREEN, theme.GREEN_DIM) + 6
            name_x = theme.CHROME_LEFT + 16
            name = fit_text(fonts.body, app.display_name or app.app_id, theme.CHROME_RIGHT - 4 - tag_w - name_x)
            fonts.body.draw(draw, image, name_x, y + 15, name, color)
        if total > DESKTOP_ROWS:
            self._scrollbar(draw, theme.BODY_TOP_STAGE, FOOTER_Y - 2, selected_index, total)

    def _tag(self, draw, image, right, mid, text, fg, border):
        stack = self.fonts.pixel8
        width = int(stack.width(text)) + 5
        x0 = right - width
        draw.rectangle([x0, mid - 5, right - 1, mid + 4], outline=border)
        draw_text(draw, image, stack, x0 + 3, mid, text, fg)
        return width

    def _scrollbar(self, draw, top, bottom, index, total):
        span = bottom - top - 8
        thumb = max(8, int(span * DESKTOP_ROWS / float(total)))
        pos = top + 4 + int((span - thumb) * index / float(max(1, total - 1)))
        draw.line([(theme.WIDTH - 6, pos), (theme.WIDTH - 6, pos + thumb)], fill=theme.GREEN_DIM)

    def _render_empty(self, draw, image, top):
        fonts = self.fonts
        cx = theme.WIDTH // 2
        self._prompt(draw, image, cx, top + 22, "ls apps")
        text = "no apps registered"
        width = fonts.prompt.width(text) + 4 + theme.CURSOR_W
        x = int(cx - width / 2)
        baseline = top + MID + 6
        end = fonts.prompt.draw(draw, image, x, baseline, text, theme.AMBER)
        self._cursor(draw, int(end + 4), baseline)
        self._caption(draw, image, top + theme.STAGE_VISUAL_H, "APPS", theme.AMBER, "0 INSTALLED")
        body = theme.BODY_TOP_STAGE + theme.BODY_PAD
        fonts.meta.draw(draw, image, theme.TEXT_LEFT, body + 14, "Apps register through the daemon", theme.MUTED)
        fonts.meta.draw(draw, image, theme.TEXT_LEFT, body + 28, "socket (app.register).", theme.MUTED)

    def _render_modal(self, draw, image, apps, app_id, pending):
        fonts = self.fonts
        color = theme.CYAN if pending else theme.GREEN
        dim = theme.CYAN_DIM if pending else theme.GREEN_DIM
        # The modal replaces the app list instead of floating over it.
        body_top, body_bottom = theme.BODY_TOP_STAGE, FOOTER_Y - 1
        draw.rectangle([0, body_top, theme.WIDTH - 1, body_bottom], fill=theme.VOID)
        w, h = 200, 70
        x0 = (theme.WIDTH - w) // 2
        y0 = body_top + (body_bottom - body_top - h) // 2
        draw.rectangle([x0, y0, x0 + w - 1, y0 + h - 1], fill=theme.RAISED, outline=color)
        draw.rectangle([x0 + 2, y0 + 2, x0 + w - 3, y0 + h - 3], outline=dim)
        label = "LAUNCHING" if pending else "APP RUNNING"
        end = draw_text(draw, image, fonts.pixel8, x0 + 10, y0 + 14, "> " + label, color)
        if pending:
            lit = int(time.time() * 6) % 4
            for i in range(3):
                fill = color if i < lit else dim
                draw.rectangle([int(end) + 6 + i * 5, y0 + 14, int(end) + 7 + i * 5, y0 + 15], fill=fill)
        app = next((a for a in apps if a.app_id == app_id), None)
        name = (app.display_name if app is not None else "") or app_id
        fonts.prompt.draw(draw, image, x0 + 10, y0 + 40, fit_text(fonts.prompt, name, w - 20), theme.TEXT)
        fonts.meta.draw(draw, image, x0 + 10, y0 + 57, fit_text(fonts.meta, app_id, w - 20), theme.DIM)

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
