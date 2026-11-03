# Home UI polish (development only)

The 240x280 Home renderer now starts the actual application list below its 27px
status bar: seven 28px rows, a quiet selected outline/chevron, stable contiguous
viewport and an overflow-only scrollbar. Names, order and selection still come
from the daemon. Running/opening markers and selected-app failures remain visible.
The hero, duplicate app name/state and launch modal were removed from Home.

Home has its own charcoal canvas, a current minute clock and percentage-only
battery (unknown is --%). Radio positions reserve the width of 100%, avoiding
movement as the battery changes. Existing fonts and internal menu layouts remain.
The byte-identical shared wireless renderer uses curved Wi-Fi arcs in both repos,
with the existing fixed 21px allocation; GLaDOS changes only that shared glyph.

Home advertises TAP NEXT / HOLD OPEN, matching the actual release dispatcher.
The foreground four-click escape is unchanged and covered by the existing tests.
The clock invalidates Home once per minute through the existing monitor, without
adding device reads, polling loops or a new thread. Sleeping/foreground apps are
not redrawn by that clock trigger. Classic fallback remains available.

Validation on Pi 5, offscreen only: 166/166 daemon tests, two chatbot status tests,
full chatbot UI self-tests. Real RGB565-renderer screenshots were inspected at
240x280, with the installed 11-app list and selected app; 3/5-app, scrolled, empty,
wireless off/disconnected/unknown and battery states were also inspected.
Warm 30-frame offscreen timings: median 2.726ms (max 3.768ms), installed baseline
2.917ms (max 5.159ms). These are renderer timings, not speech or LCD transfer time.
No font files, control paths, security, permissions, models or memory were changed.
No production deployment or physical acceptance is claimed.
