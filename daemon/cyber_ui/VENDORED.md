# Vendored from the Whisplay AI Chatbot terminal UI

Source: `soldercore/whisplay-ai-chatbot`, branch `cyber-terminal-ui`,
commit `2dd608b`, folder `python/whisplay_ui/` (and `python/fonts/`).
Copied, not imported, so the daemon never depends on the chatbot at runtime.

| File here | Origin | Changes |
|---|---|---|
| `fonts.py` | `whisplay_ui/fonts.py` | `FONT_DIR` points at `cyber_ui/fonts/`; docstring |
| `theme.py` | `whisplay_ui/theme.py` | palette and layout tokens only (no timing/flags) |
| `draw_util.py` | `whisplay_ui/draw_util.py` | subset: mix, clamp01, cap_height, draw_text, fit_text, corner_brackets; `dotted` from `panes.py` |
| `statusbar.py` | `whisplay_ui/statusbar.py` | battery + Wi-Fi + badge only; clock optional |
| `fonts/*.ttf`, `fonts/OFL-*.txt` | `python/fonts/` | unchanged (SIL Open Font License) |

Launcher-specific code (not vendored): `menu_renderer.py` (screens),
`fallback.py` (classic fallback), `preview.py` (PNG preview, test fixtures).

When the chatbot design changes, copy the matching functions across and keep
the values identical so both screens stay one product.
