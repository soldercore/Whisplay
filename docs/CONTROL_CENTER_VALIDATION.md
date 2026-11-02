# Control Center validation — 2026-11-02

Scope: candidate daemon branch based on installed custom `5533f54`, all three
phases, local privilege boundary, UI wiring and cleanup. No chatbot edits,
driver build/install, genuine control mutations or production restart.

## Executed

- 84 daemon tests + 8 example tests pass on the Pi, zero skips; real Pillow and
  numpy, fake boards, processes and destructive commands. `compileall`, Bash
  installer syntax, `visudo -cf` on a temporary proposed rule and Git whitespace
  checks pass. Running the permission installer itself is not authorized/tested.
- The original four-click PTT events, Home tap/hold, focus handoff, normal exit,
  hung/crashed apps, button-release suppression and real daemon Network/Back
  dispatch are exercised. Home stays visible while an app stops.
- The shell-exit/orphan-child regression fails before the fix and passes after;
  snapshots use PID/starttime identity and never signal a replaced/reused group.
  A pre-fix Home-render test fails because a running modal covers the controls;
  the updated path passes. No real signal was sent during tests.
- Wi-Fi status has no mutation/rescan side effect, saved profiles use UUID,
  button-only password entry works with masking/edit/cancel, root command argv
  has no password, and temporary synthetic credential files are removed.
- Bluetooth status never powers/scans; disconnect does not forget pairing;
  inactive/unrequested pairing cannot open/accept a confirmation. Pairing agent
  cancellation is checked. The real BlueZ agent is never started by tests.
- Audio preserves the old speaker curve, never writes microphone gain or plays
  preview audio. Recording settings are atomic, failed unlock writes retain the
  runtime lock, invalid settings fail closed, launch and focus enforce the lock.
- Screen wake restores brightness and consumes the wake event. Unavailable
  metrics stay unavailable, zero stays zero. Service reads/actions have fixed
  allowlists, the daemon cannot restart itself, maintenance blocks launch, and
  failure releases its reservation. Cancel/expiry/navigation cannot run power
  actions; errors/timeouts cannot report command acceptance.
- Fifteen synthetic 240x280 pages rendered through the actual cyber renderer,
  with classic counterparts, into an in-memory RGB565 board. Contact sheet and
  raw PNGs were inspected; classic clipping was corrected, including power
  warnings and long SSID targets. No GPIO, SPI or physical display was used.
- Navigation and action-dispatch timings are in the accompanying `timings.json`.
  Real public metrics and fixed Wi-Fi/service status reads were timed separately.
  Destructive action timings are mocked; GPIO/SPI and GLaDOS speech latency have
  not been benchmarked. The off-screen navigation median is approximately 3 ms.

## Production preserved — read-only verification

Daemon source remains `5533f544aad29ef4297b0466f1a328d7d93ad5a6`, active/running
with the original PID 1136. Its only existing untracked file is
`example/data/run_test_record.wav`. The paired `Whisplay-next` checkout stays clean
at the same revision. No daemon/menu source was copied to either installation.

The registered original chatbot is **running=true, foreground=true, selected=true,
autostart=true**, with its existing `quad_click` gesture and registered launch
command. Production remains on `test/glados-d` / `de8a196...`, with only the
previously approved memory subject patch dirty in tracked source and existing
environment backups. No branch was switched, merged or deployed.

Exact protected hashes match the pre-development baseline:

| File in production chatbot | SHA-256 |
| --- | --- |
| `.env` | `f60eff97d7d123db320986c1cc511e2f89268124344c9189943d83c50647fcc1` |
| `src/config/persona.ts` | `71ce60f223e739ed1e97606ed36abe9e51108d0558df424b9f3ead93f4493599` |
| `dist/config/persona.js` | `671c8ea21d85ab2bbbca3d6ce52adfc591d54e9e7475b93a1c760f386a64ff0b` |
| `src/config/local-memory.ts` | `7c56fe3c21778511e213493d564e0fcea58ed8b92242fdc322b62701e4a92bf5` |
| `dist/config/local-memory.js` | `b67dbe6ea8a502b605e829b138f095afcd761c2eb295262d8971a40cfb5823dc` |

Configuration still selects original GLaDOS A, `qwen3.5:2b-q4_K_M`,
`ENABLE_THINKING=false`, Faster-Whisper, Piper HTTP voice `glados`. A read-only
Ollama `/api/ps` query confirms that model is resident with context length 4096.
Ollama, Whisper and Piper systemd units remain active/running at their original
PIDs. Real saved memories were not opened, modified or used by tests.

## Audit conclusion and acceptance gaps

Three high-risk verification rows:

1. **Fail closed:** arbitrary helper commands/units, inactive pairing, invalid
   recording state, blocked launches and expired confirmations are denied in tests.
2. **Wiring:** actual daemon release-handler → manager → Network child → Back →
   Home runs in tests; all eight built-ins are registered; IPC keeps child IDs.
3. **Production isolation:** source/config/persona/memory-patch hashes and live
   app/service state above match baseline; only disposable temporary staging ran.

No known unaddressed critical/high source finding from the scoped audit. This is
not physical certification: codec mute audibility, permissions installation,
Wi-Fi/BlueZ recovery and credential persistence, real service/power actions,
button timing/SPI under generation load, production group/lock cleanup, cold boot
and actual battery support require an approved controlled hardware test. Existing
daemon IPC/app registration trusts local users and is not a sandbox for arbitrary
registered software; this change creates no network interface or model tool.

Deployment and rollback steps are in [CONTROL_CENTER.md](CONTROL_CENTER.md).
The next step is review/approval of a controlled deployment and hardware test.
Nothing auto-deploys; no further development task is started.
