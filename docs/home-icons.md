# Home visual refinement (development only)

Home keeps seven rows, the original fonts, stable viewport and TAP NEXT / HOLD
OPEN footer. Eleven fixed app-ID mappings select cached 16x16 Pillow icons;
unknown app IDs all share one generic icon. The cache is bounded at 24 sprites,
and no app ID becomes a path or asset name. No new fonts/assets/dependencies.

Only Home's header uses the refined symmetric 13x11 Wi-Fi sprite and conventional
Bluetooth sprite. Connected/off/disconnected/unknown remain distinct. Battery
percentage now uses the existing clock font/weight, reserving 100% width so neither
radios nor clock move. Classic, internal menus, GLaDOS, providers and shared
wireless_icons.py are unchanged. The existing event-driven provider is reused.

Pi offscreen verification: 170/170 daemon tests passed, including the new icon,
cache, symmetry, battery-weight and dynamic-app cases plus existing safe-area,
scroll, fallback, button and security contracts. Actual 240x280 RGB565 screenshots
were inspected for normal/selected/scrolled lists, all radio states, 9/55/100%
and a third-party app. Before/after use identical installed app data and clock.

Existing benchmark method: three warmup frames, 30 renders, same actual 11-app
registry. Installed 384c145 median 2.629ms / max 4.183ms; candidate median 2.684ms /
max 4.368ms. These are renderer times, excluding LCD transfer and speech.
No production deployment, model inference or physical acceptance was performed.
