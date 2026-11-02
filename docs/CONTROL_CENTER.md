# Whisplay Control Center candidate

Development branch: `codex/whisplay-control-center`, based on the **installed**
custom daemon `5533f544aad29ef4297b0466f1a328d7d93ad5a6`, not a new upstream release.
This is source for review. Nothing here has been installed or enabled in production.

## Contract and wiring

The existing daemon still owns LCD, RGB, button, framebuffer, app registry and
local Unix IPC. There is no new daemon, listener, model tool or remote control API.
`InternalAppManager` registers the existing Bluetooth, Wi-Fi, Audio and Power IDs,
plus Network, Display, System Info and Services. Network children remain in
`app.list` but are absent from the Home root; existing clients keep their IDs.
Other registered applications remain available after the seven primary entries.
The existing cyber renderer and permanent classic fallback consume list view
models. Joystick/external keyboard entry remains optional; ordinary Whisplay
password entry uses the same keyboard characters in button-selectable rows.

Home/menu input: tap next, hold (0.7 s) open/select. Every menu has Back; Network
children return to Network. Password entry offers Cancel, Delete, Join and key
rows; selecting a row exposes individual characters, Back and Shift. Passwords
are masked, bounded, discarded on leaving, and never rendered or logged in clear.
Saved Wi-Fi uses profile UUID, not an assumed SSID/profile-name equivalence.
New joins support broadcast open/WPA Personal networks; enterprise/WEP requires
an existing saved profile. Hidden SSID/manual enterprise setup is not added.

GLaDOS retains normal push-to-talk and the original four-click escape. Returning
Home requests cooperative shutdown rather than retaining an idle chatbot in the
background: current focus release alone is not a safe recording-lifecycle contract.
Ollama/Whisper/Piper services remain resident. After 1.5 s, a stuck daemon-launched
session loses focus and receives TERM; after a further 2 s, KILL. Only that tracked
session is eligible. `/proc` PID/starttime snapshots retain known group children
even if their launcher exits, and reject reused identities. An unverifiable group
is left alone with a visible error and blocks new external launches; Power remains
available. This is not a general supervisor for arbitrary self-detaching programs.
The chatbot's existing Sox capture children inherit its group. Physical cleanup,
lock release and relaunch still need acceptance testing with the installed app.

Audio extends the existing mixer detection and gain curve. Speaker +/-10 and
zero/restore read back the value; no preview tone or microphone gain change is
introduced. Zero-volume audibility needs physical confirmation on the actual codec.
The approved **GLaDOS recording lock** blocks daemon launch/focus for the fixed
chatbot ID. It can be enabled/disabled locally after the chatbot has stopped.
It does not mute other programs or prevent a user launching software outside the
daemon. Its bool is stored atomically in `~/.whisplay-daemon/control-center.json`;
missing file preserves the original enabled state, invalid content locks recording.
No chatbot `.env`, persona, model, voice or memory format changes are required.
Voice-input status reads only the registered app's wake-word configuration; it
is configuration status, not a measurement that recording is currently inactive.

Display shows the last commanded brightness/RGB (no physical light sensor), uses
20–100% settings and restores brightness after screen-off/lock. Release of the wake
press returns Home and is consumed. RGB requests keep the existing behavior;
hardware fade leaves reported RGB unavailable. System Info samples public Linux
metrics in a worker; missing values remain unavailable. Battery uses the existing
detected PiSugar poller; no unsupported power-source value is invented. Throttling
flags are the actual `vcgencmd` mask, including historical bits, not a health verdict.

Services reads only five fixed units and the daemon's actual chatbot process state.
Running/Stopped/Starting/Stopping/Failed/Unavailable are process/systemd states,
not proof that an ASR, LLM or TTS API is ready. Only SSH, Ollama, Faster-Whisper and
Piper can start/restart. The daemon is read-only; there is no arbitrary unit or stop
action. A maintenance reservation excludes external app launch/focus while actions
run, and requires existing apps to have stopped first. GLaDOS launch uses its
original registered command and ordinary focus/lock path.

## Local confirmation and permissions

Wi-Fi radio changes, joins, saved-profile switches and disconnects, Bluetooth
radio/device changes, recording-lock changes, service operations and power actions
use a separate confirmation screen. Cancel is initially selected; tap to Confirm,
hold to execute. Confirmations expire after 30 s and are discarded on navigation.
Wi-Fi/SSH warnings explain lost connectivity and local recovery. Power reports
command acceptance only after a successful return; shutdown requires actual
hardware support to power on again. No claim is made that GPIO software can wake
a fully shut-down Pi.

Installed NetworkManager reported `no` for Wi-Fi radio control and `auth` for
network-control. A desktop polkit agent cannot be assumed. The candidate therefore
includes an **optional, not installed** root-owned helper and one narrowly scoped
sudoers entry. It accepts only fixed Wi-Fi operations, the four mapped services,
and reboot/poweroff. It uses isolated Python (`-I`), fixed executable paths, a fixed
environment, no shell, argument validation and finite command timeouts. No Qwen
tool can invoke these actions. BlueZ and mixer calls retain the existing user's
authorization; actual authorization requires a controlled hardware test.

New Wi-Fi credentials travel through stdin as bounded JSON. The root helper uses
a root-private temporary `passwd-file`, never a password argument. NetworkManager
manages normal saved-profile persistence. Failed new joins may leave a newly
created `Whisplay-<random>` profile; existing profiles are never removed by tests or
the helper. Enterprise credentials cannot be edited through this UI.

**Do not run the existing daemon/driver installer for this candidate.** It can
replace unrelated integration and restart production. After separate deployment
approval, the optional permission installation command is:

```sh
sudo bash install_control_center_permissions.sh hamad
```

It installs only `/usr/lib/whisplay/control-action` and
`/etc/sudoers.d/whisplay-control-center`, validates sudoers first, and refuses to
replace existing files. It does not restart services, change networks or install
a driver. Review/verify the exact source before running it. Missing privileges
produce an honest action failure; read-only menus remain available.

## Verification and limits

Phase 1: 56 daemon tests passed on Pi in `/tmp/whisplay-control-center.W8UppT`.
Phase 2: 67 passed in `/tmp/whisplay-control-center-phase2.ui2r7khb`.
Phase 3 plus audit: **84 daemon tests and 8 example tests pass, zero skips** on
the Pi in an isolated temporary checkout. See [CONTROL_CENTER_VALIDATION.md](CONTROL_CENTER_VALIDATION.md)
for the final evidence and the production comparison.
All boards, processes/signals, privileged commands and destructive operations in
these suites are mocked. Tests include the real daemon button-dispatch path,
Home escape, process/focus failures, password entry by button only, unavailable
metrics, fixed allowlists, no secret argv, canceled/expired confirmations and
service reservations. The old immediate-reboot test was replaced with a test
requiring a distinct confirmation. The shell-exits-before-child defect was
reproduced failing before its ownership fix, then passed.

Reproduce without starting hardware or the daemon:

```sh
python3 -B -m unittest discover -s daemon/tests -v
python3 -B -m unittest discover -s example/tests -v
bash -n install_control_center_permissions.sh
python3 daemon/tests/control_center_review.py --out /tmp/control-center-preview
# Optional actual read-only public Linux/status probes, still a fake display:
python3 daemon/tests/control_center_review.py --out /tmp/control-center-preview --read-only
```

Rendering uses real Pillow/numpy and RGB565 frames in an in-memory board, at
240x280, including cyber and classic paths. No physical display/button test has
been performed. Windows lacks imaging dependencies, so its skipped rendering
tests are not accepted as Pi evidence. No kernel/audio-driver changes or new
dependencies were introduced. Source syntax and installer syntax are checked;
the optional privilege installation and genuine mutations are unverified.

Measured on the Pi using a fake board (50 input samples): Home event plus render
median 3.061 ms / p95 5.989 ms; menu during a deliberately blocked worker median
3.040 ms / p95 3.108 ms. This excludes GPIO, real SPI transfer and physical debounce.
Read-only Linux metrics median 102.199 ms (includes 100 ms CPU sample), fixed unit
queries 39.735 ms, Wi-Fi status 94.080 ms. Mock power dispatch median 0.009 ms is
only dispatch overhead; real network/service/power latency was not measured.
Owned-group read-only snapshots median 7.219 ms. No chatbot latency/model inference
benchmark was run; no speech-latency improvement is claimed. Polling is limited
to the foreground built-in menu, at 20 s, paused during selection/input/confirmation.
Blocking commands run in bounded workers; Back stays usable. No background ASR
or additional polling while GLaDOS is foreground is added.

## Review, deployment and rollback

The delivery is an isolated driver Git branch/bundle; the chatbot repository is
unchanged. Before approval, compare against the installed `5533f54`, review the
helper/sudoers scope, and preserve this evidence. A future controlled test must:

1. Preserve the installed driver commit, unit, settings, registration and any
   local files in a separate timestamped backup. Keep all chatbot memory untouched.
   Verify no competing task/process, and stop GLaDOS through its normal manager.
2. Install only reviewed daemon/menu source at the existing driver path, with the
   existing service/driver/config/registration retained. Install permissions only
   if explicitly approved. Restart the existing daemon by its normal manager.
3. Test tap/hold, quad escape during generation/recording, crash/hung child cleanup,
   lock release/relaunch, password editing/cancel, Wi-Fi off then physical on,
   Bluetooth off/on, audio zero/restore, recording lock/unlock and brightness wake.
   Network/SSH/power mutations each require their own controlled local approval.
4. Confirm only one chatbot, correct focus and unchanged personality/model/voice/
   memory, then test cold boot/autostart and actual backend readiness.

Rollback, after approval: stop the registered app normally; stop the existing
daemon via systemd; restore **only candidate-changed daemon/menu source** to the
preserved installed revision, leaving user files, app registry and settings intact;
start the same daemon and original registered chatbot and verify
`running=true foreground=true selected=true`. Do not run reset/clean or remove
lock files. Preserve the optional recording-state file; the old daemon ignores it.
If this candidate installed the two previously absent permission files, remove
only those exact verified files during rollback (never shared sudoers rules), then
restart normally. No chatbot rollback is needed: this candidate has no chatbot
changes and must retain the approved `3157bed` memory source/compiled patch.

Classic list labels now fit measured font widths; Wi-Fi target SSIDs/profile
UUIDs have complete two-line details, including the 32-character review case.

Remaining acceptance risks: actual button timing under load, codec zero-volume
behavior, BlueZ authorization/pairing, NetworkManager credential persistence and
recovery, root helper installation, service startup durations, lock/process-group
cleanup with production GLaDOS, daemon restart/cold boot, actual battery hardware
and SPI frame latency. None is labeled physically verified.
