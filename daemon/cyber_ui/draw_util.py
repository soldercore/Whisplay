"""Small drawing helpers.

VENDORED (subset) from soldercore/whisplay-ai-chatbot @ 2dd608b,
python/whisplay_ui/draw_util.py: mix, clamp01, cap_height, draw_text,
fit_text, corner_brackets, dotted. Behaviour unchanged.
"""
from . import theme


def clamp01(t):
    return 0.0 if t < 0.0 else 1.0 if t > 1.0 else t


def mix(c1, c2, t):
    t = clamp01(t)
    return (
        int(round(c1[0] + (c2[0] - c1[0]) * t)),
        int(round(c1[1] + (c2[1] - c1[1]) * t)),
        int(round(c1[2] + (c2[2] - c1[2]) * t)),
    )


_CAP_CACHE = {}


def cap_height(stack):
    key = id(stack)
    cap = _CAP_CACHE.get(key)
    if cap is None:
        try:
            bbox = stack.primary.font.getbbox("H")
            cap = max(1, bbox[3] - bbox[1])
        except Exception:
            cap = 8
        _CAP_CACHE[key] = cap
    return cap


def draw_text(draw, image, stack, x, center_y, text, fill, cap=None):
    """Draw text vertically centred on center_y using the stack's cap height.
    Returns the x after the text."""
    if cap is None:
        cap = cap_height(stack)
    baseline = int(round(center_y + cap / 2.0))
    return stack.draw(draw, image, x, baseline, text, fill)


def fit_text(stack, text, max_width, ellipsis="…"):
    if stack.width(text) <= max_width:
        return text
    if not stack.primary.covers(ellipsis):
        ellipsis = "..."
    budget = max_width - stack.width(ellipsis)
    out = []
    used = 0.0
    for ch in text:
        w = stack.advance(ch)
        if used + w > budget:
            break
        out.append(ch)
        used += w
    return "".join(out).rstrip() + ellipsis


def corner_brackets(draw, x0, y0, x1, y1, size, fill):
    """Viewfinder-style corner marks (the chatbot stage frame)."""
    draw.line([(x0, y0), (x0 + size, y0)], fill=fill)
    draw.line([(x0, y0), (x0, y0 + size)], fill=fill)
    draw.line([(x1 - size, y0), (x1, y0)], fill=fill)
    draw.line([(x1, y0), (x1, y0 + size)], fill=fill)
    draw.line([(x0, y1), (x0 + size, y1)], fill=fill)
    draw.line([(x0, y1 - size), (x0, y1)], fill=fill)
    draw.line([(x1 - size, y1), (x1, y1)], fill=fill)
    draw.line([(x1, y1 - size), (x1, y1)], fill=fill)


def dotted(draw, y, fill=theme.LINE):
    """Dotted divider used under the chatbot caption/strip rows."""
    for dx in range(theme.CHROME_LEFT, theme.CHROME_RIGHT, 3):
        draw.point((dx, y), fill=fill)
