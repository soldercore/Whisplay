"""Design tokens shared with the chatbot's cyber-terminal UI.

VENDORED (subset) from soldercore/whisplay-ai-chatbot @ 2dd608b,
python/whisplay_ui/theme.py: palette and the layout tokens the launcher uses.
Values are unchanged so both screens look like one product.

Every colour is RGB565-exact: each 8-bit channel is the bit-replicated 5/6-bit
value, so the truncating RGB888 -> RGB565 conversion leaves it unchanged.
"""


def _hex(value):
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


# ---- Palette (identical to the chatbot UI) -------------------------------
VOID = _hex("000000")
RAISED = _hex("080C08")
PANEL = _hex("101810")
LINE = _hex("182821")
DIM = _hex("5A6D5A")
MUTED = _hex("9CAA9C")
TEXT = _hex("E7F7DE")
BRIGHT = _hex("FFFFFF")
GREEN = _hex("4AEB7B")
GREEN_MID = _hex("29A24A")
GREEN_DIM = _hex("186931")
GREEN_DEEP = _hex("083018")
CYAN = _hex("5ACBDE")
CYAN_DIM = _hex("215152")
AMBER = _hex("FFB231")
AMBER_MID = _hex("B57D21")
AMBER_DIM = _hex("634510")
RED = _hex("FF5952")
RED_DIM = _hex("521818")

# ---- Layout (identical to the chatbot UI) --------------------------------
WIDTH = 240
HEIGHT = 280

# ---- Safe area: rounded LCD corners ---------------------------------------
# Identical in soldercore/Whisplay daemon/cyber_ui/theme.py and
# soldercore/whisplay-ai-chatbot python/whisplay_ui/theme.py; keep in sync.
# The Whisplay panel has rounded corners (radius about 40 px). Status-bar
# content stays between STATUS_SAFE_LEFT and STATUS_SAFE_RIGHT on the
# STATUS_CENTER_Y line, and content that runs to the side margins ends above
# CONTENT_SAFE_BOTTOM, so nothing reaches the curve even for a 44 px radius
# (SAFE_CHECK_RADIUS, enforced by the tests in both repos).
SCREEN_CORNER_RADIUS = 40
SAFE_CHECK_RADIUS = 44
STATUS_SAFE_LEFT = 24     # first usable column
STATUS_SAFE_RIGHT = 216   # last usable column (inclusive), = WIDTH - 24
STATUS_CENTER_Y = 13      # centre line of badge, labels, battery and Wi-Fi
STATUS_H = 27             # status bar rows 0..25 plus the divider row 26
DIVIDER_Y = 26
PANE_Y = 27               # content top: first row under the status bar
CONTENT_SAFE_BOTTOM = 264 # = HEIGHT - 16

CHROME_LEFT = 14
CHROME_RIGHT = 226
TEXT_LEFT = 12
TEXT_WIDTH = 216
LINE_H = 20
CURSOR_W = 8
CURSOR_H = 15
STAGE_H = 104             # hero frame: 80 px visual + 24 px caption row
STAGE_VISUAL_H = 80
BODY_TOP_STAGE = PANE_Y + STAGE_H
BODY_PAD = 6
STRIP_H = 26              # console strip height under the status bar
APPROVAL_H = 38           # bottom action bar (chatbot approval bar)
