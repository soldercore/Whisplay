# Driver/launcher validation — 2026-10-31

Development branch: `integrate/driver-v3.2.7`. Custom reference: `53a9d6e`; official target: `736975188ebbe146d319e450aad19c218a310611` (v3.2.7). Published release/tag metadata is recorded in `../upstream-integration.json`.

| Check | Result |
|---|---|
| Custom baseline daemon suite | 24 tests passed before integration |
| Complete integrated daemon/UI suite | **48 passed**, including original cyber screens, constructor compatibility, Joy fallback, autostart, input, Wi-Fi keyboard and PiSugar tests |
| Complete example suite | **8 passed**, including MP4 process cleanup |
| Static syntax checks | 21 shell files and 39 Python files passed |
| Shared font assets | Byte-identical to the custom chatbot's bundled fonts |
| Historical refs/reference worktree | Unchanged/clean |
| Kernel module build | **Not verified**: `make` fails because `/lib/modules/6.18.57/build` is absent in the development container |
| Physical Pi, GPIO/SPI/I2C, ALSA, Joy and cold boot | **Not tested** |
| Driver/image installation or publication | **Not performed** |

Tests use fake boards and installed UI libraries on x86_64 (Python 3.12, Pillow 13.0.0, NumPy). No tests were skipped for missing imaging support. Some font ResourceWarnings occur in existing rendering paths; both complete suites finish successfully. Test success does not establish real kernel-driver or peripheral compatibility.

Ordinary Whisplay keeps custom cyber UI. Joy intentionally uses the complete upstream classic renderer for joystick legends and screen keyboard; custom Joy styling is not implemented or claimed. No previously available custom launcher feature was deliberately removed.

See `CUSTOM_INTEGRATION.md` for build prerequisites, the remaining physical acceptance checklist and the small manual upstream-update process. GitHub authentication failed in this environment; the review branch and portable Git bundle are local deliverables. No stable branch, production service, Raspberry Pi or release was changed.
