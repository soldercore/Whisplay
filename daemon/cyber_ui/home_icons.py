"""Small, bounded, cached Pillow sprites for Home only. No assets or system I/O."""
from functools import lru_cache
from PIL import Image, ImageDraw

from . import theme

APP_ICONS = {
    'whisplay-ai-chatbot': 'aperture', 'whisplay-network': 'network',
    'whisplay-volume': 'speaker', 'whisplay-display': 'display',
    'whisplay-information': 'information', 'whisplay-services': 'services',
    'whisplay-system': 'power', 'whisplay-jump': 'controller',
    'whisplay-flappy-bird': 'bird', 'whisplay-play-mp4': 'play',
    'whisplay-run-test': 'flask',
}

# Symmetric one-pixel arcs on a 13x11 grid. The point shares the same x centre.
WIFI_ARCS = (
    ((5, 6), (6, 6), (7, 6), (4, 7), (8, 7)),
    ((5, 3), (6, 3), (7, 3), (3, 4), (4, 4), (8, 4), (9, 4), (2, 5), (10, 5)),
    ((4, 0), (5, 0), (6, 0), (7, 0), (8, 0), (2, 1), (3, 1), (9, 1), (10, 1),
     (1, 2), (11, 2), (0, 3), (12, 3)),
)


def _wifi(draw, x, y, colors, point):
    for pixels, color in zip(WIFI_ARCS, colors):
        draw.point([(x+px, y+py) for px, py in pixels], fill=color)
    draw.point((x+6, y+10), fill=point)


@lru_cache(maxsize=24)
def _app_sprite(name, selected):
    tile = Image.new('RGBA', (16, 16))
    d = ImageDraw.Draw(tile)
    color = theme.GREEN if selected else theme.GREEN_MID
    line = lambda points: d.line(points, fill=color, width=1)
    if name == 'aperture':
        line(((4,1),(11,1),(15,7),(11,14),(4,14),(0,7),(4,1)))
        for points in (((4,1),(9,6)),((11,1),(10,9)),((15,7),(7,10)),
                       ((11,14),(6,9)),((4,14),(5,6)),((0,7),(8,5))):
            line(points)
    elif name == 'network':
        _wifi(d, 1, 2, (color, color, color), color)
    elif name == 'speaker':
        line(((1,6),(4,6),(8,2),(8,13),(4,9),(1,9),(1,6)))
        line(((11,5),(13,7),(13,8),(11,10)))
        line(((13,2),(15,5),(15,10),(13,13)))
    elif name == 'display':
        d.rectangle((1,2,14,11), outline=color)
        line(((7,11),(7,14))); line(((4,14),(11,14)))
    elif name == 'information':
        d.ellipse((1,1,14,14), outline=color)
        d.point((8,4),fill=color); line(((7,7),(8,7),(8,11)))
        line(((6,11),(10,11)))
    elif name == 'services':
        for cy in (4,8,12):
            line(((1,cy),(8,cy-3),(15,cy),(8,cy+3),(1,cy)))
    elif name == 'power':
        d.arc((1,2,14,15),310,230,fill=color)
        line(((8,0),(8,7)))
    elif name == 'controller':
        line(((3,4),(12,4),(15,12),(13,14),(10,11),(5,11),(2,14),(0,12),(3,4)))
        line(((3,8),(7,8))); line(((5,6),(5,10)))
        d.point(((11,7),(13,9)),fill=color)
    elif name == 'bird':
        line(((1,7),(5,7),(5,4),(7,2),(11,2),(13,4),(13,7),(15,7),
              (15,9),(12,9),(10,12),(6,12),(4,10),(1,10),(1,7)))
        d.point((10,5),fill=color);line(((5,8),(8,8),(8,10)))
    elif name == 'play':
        d.rounded_rectangle((1,2,14,13),radius=2,outline=color)
        d.polygon(((6,5),(6,10),(11,7)),fill=color)
    elif name == 'flask':
        line(((5,1),(10,1),(10,3),(9,3),(9,6),(14,13),(13,14),(2,14),
              (1,13),(6,6),(6,3),(5,3),(5,1)))
        line(((4,10),(11,10)))
    else:
        for x,y in ((2,2),(9,2),(2,9),(9,9)):
            d.rectangle((x,y,x+4,y+4),outline=color)
    return tile


def application_icon(app_id, selected=False):
    # Unknown IDs share one sprite; arbitrary plugin IDs never become cache keys/paths.
    return _app_sprite(APP_ICONS.get(app_id, 'generic'), bool(selected))


@lru_cache(maxsize=16)
def _wifi_sprite(mode, level):
    tile = Image.new('RGBA', (13,11))
    d = ImageDraw.Draw(tile)
    colors = tuple(theme.GREEN if mode == 'active' and i < level else theme.DIM for i in range(3))
    _wifi(d,0,0,colors,theme.GREEN if mode == 'active' else theme.DIM)
    if mode == 'disconnected':
        d.line((2,0,10,10),fill=theme.RED)
    elif mode == 'unknown' or mode == 'active' and level == 0:
        d.rectangle((10,0,12,2),outline=theme.AMBER)
    return tile


@lru_cache(maxsize=3)
def _bluetooth_sprite(mode):
    tile = Image.new('RGBA', (9,11))
    d = ImageDraw.Draw(tile)
    color = theme.TEXT if mode == 'active' else theme.DIM
    d.line(((3,0),(3,10),(7,7),(0,2)),fill=color)
    d.line(((3,0),(7,3),(0,8)),fill=color)
    if mode == 'unknown':
        d.point((8,0),fill=theme.AMBER)
    return tile


def draw_home_wireless(image, right, center, state):
    wifi, bt = state.get('wifi',{}), state.get('bluetooth',{})
    enabled, connected, signal = wifi.get('enabled'), wifi.get('connected'), wifi.get('signal')
    mode = ('disabled' if enabled is False else 'active' if enabled is True and connected is True
            else 'disconnected' if enabled is True and connected is False else 'unknown')
    level = (3 if signal >= 67 else 2 if signal >= 34 else 1) if type(signal) is int and 0 <= signal <= 100 else 0
    powered = bt.get('enabled')
    bt_mode = 'active' if powered is True else 'disabled' if powered is False else 'unknown'
    left = right-27
    for tile,x in ((_wifi_sprite(mode,level),left),(_bluetooth_sprite(bt_mode),right-9)):
        image.paste(tile,(x,center-5),tile)
    return left
