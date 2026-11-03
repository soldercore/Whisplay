# Privileged controls — security-fixed development candidate

Not deployed. Based on daemon `daf232d` and compatible with chatbot `ba8614d` (no chatbot source changes needed). Production remains the accepted voice-first installation. No new model, UI, microphone mode, dependency or memory format.

## IPC contract

- The Unix socket is created owner-only (0600, including the bind window). Existing non-socket, foreign-owned and symlink paths are refused.
- Every supported IPC command verifies kernel SO_PEERCRED. Only the daemon UID is authorized; audio group membership alone grants no access. Missing/unreadable credentials deny.
- The owner UID is the trusted local administrator. Management clients outside tracked app groups may register validated launch configurations, launch registered apps and manage autostart/exit. This is not isolation against arbitrary malicious code already running as that UID.
- A daemon-tracked running application process group may refresh only its own presentation, with unchanged persistence. It cannot register another app, replace an executable/cwd/env, change autostart or launch another app. Built-ins cannot be replaced by registration.
- Focus acquisition and app subscriptions require the matching tracked process group; framebuffer/release additionally require a nonempty live session token. Stolen tokens or app_id claims from another group do not authorize. Hardware writes require the tracked foreground app (or trusted owner diagnostics at Home).
- Tokens are returned only to the authorized acquiring process, never broadcast. Framebuffers are exclusively created mode 0600. Authorization and legacy mutations share the state lock.
- App launches use argv with shell=False. Shell evaluation, operators and privileged/wrapper executables are rejected. The installed GLaDOS command's exact trailing `>> absolute-log 2>&1` form is translated to an append-only file handle, preserving logging without a shell. Daemon-managed launch is required before external apps acquire focus; manually started untracked UI clients are intentionally denied.
- Home, PTT, release/cleanup and the four-click fallback retain their existing implementation. Voice controls share the same peer/process identity functions. Existing safe volume/Home commands add no model request or root capability probe.

## Network safety gate

Wi-Fi disable, saved-profile activation, join and disconnect are **disabled**, regardless of physical confirmation, active SSH or a previously installed helper. The shared physical-control client, voice capabilities/validation and root helper all deny these routes. There is no runtime/env override. Dormant algorithms are exercised only through explicit test mocks.

Wi-Fi status, ordinary scanning (fixed privileged fallback if needed) and radio-on remain available. Bluetooth retains its existing BlueZ operations and physical confirmation. No production network changes were used for development.

On a failed operation/verification the checkpoint context no longer calls CheckpointRollback or CheckpointDestroy: the finite 120-second NetworkManager timer is retained. The error explicitly says restoration is unverified. An ambiguous commit/destroy reply reports recovery state unknown, not a surviving timer or success. The old unsafe assumption that explicit rollback leaves a timer was removed.

This does **not** establish successful automatic recovery or restore global Wi-Fi radio state. Per-device rollback success has not been independently demonstrated. Those are reasons the disruptive routes stay disabled, not conditions inferred from a timer. Existing physical radio-on is retained, but is not claimed as unattended recovery. No unsuccessful/pending rollback is returned as success.

## Helper and remaining allowed privilege

Helper protocol 3 advertises disruptive_wifi=false. Discovery requires this protocol plus root-owned, nonwritable helper and parent paths; older helpers fail closed. The helper retains fixed absolute binaries, fixed environment/cwd, isolated Python, strict arguments/service map, stdin-only credentials, timeouts and the nonblocking root-owned lock. Service start/restart is limited to SSH, Ollama, Whisper and Piper. SSH restart is blocked while an established SSH session is detected; root helper rechecks. Restart and power still require the existing fresh physical Cancel-first workflow after app/microphone cleanup. No service stop, arbitrary systemd unit, shell or sudo command is exposed to Qwen.

Physical confirmation is an application boundary, not a restriction against an intentional trusted local administrator calling the helper. The SSH check/action race and the broader trusted account remain residual limits.

## Minimal privilege-reduction plan — not applied

Actual policy: `/etc/sudoers.d/010_hamad-nopasswd` grants `hamad ALL=(ALL) NOPASSWD: ALL`. A separate whisplay-daemon-power rule grants direct reboot/poweroff. The unrelated legacy jarvis rule grants only `/usr/bin/ip` and is outside this change.

Read-only dependency inspection found sudo in install_dependencies.sh, startup.sh's installation/legacy branches, cli/service.sh's legacy enable/disable/uninstall, deploy-aihat2.sh provisioning/maintenance, install_ollama.sh, driver installers and daemon service installer. These administrative workflows can require password-authenticated sudo; they do not justify unattended ALL. Runtime sudo mentions in hardware/model files are installation guidance, not normal capture/display calls. The inspected system/user units, cron directories, jarvis night timer units and OpenClaw entry point showed no direct blanket-sudo requirement. Arbitrary agent-generated routines/custom automations are not exhaustively certified.

Normal daemon-managed GLaDOS and hardware use run as hamad using existing audio/GPIO/SPI groups. Whisper/Piper are systemd-managed hamad services; Ollama uses its own account and SSH is root-managed. Their boot/runtime does not require hamad's blanket sudo.

The installer now prepares only:

```sudoers
hamad ALL=(root) NOPASSWD: NOSETENV: /usr/lib/whisplay/control-action
```

It does not remove/replace any existing rule. Adding this next to ALL does not reduce privileges. Before removal: independently verify password-authenticated sudo in a separate administrative session and a physical/local recovery path; preserve root-readable backups and validate the complete proposed policy with visudo. hamad has a password set and sudo membership, but those recovery checks have NOT been completed. Only after explicit approval should the blanket hamad rule and redundant direct power grant be retired, retaining password-authenticated administration. Do not touch the separate jarvis rule. Rollback is restoration of verified policy backups through that independently tested administrative route. No policy/service/driver change is authorized by this document.

## Development verification

Tests run on isolated source under `/tmp/whisplay-security-fix-dnmxhpjp`, never against real memory/config. All privileged changes are mocks or temporary installation fixtures. No real power, disconnect or service restart. Final counts/evidence accompany the development commit.

2026-11-03: 150/150 daemon and 8/8 example tests passed on the Pi, including a real unprivileged child/Unix-peer lifecycle test. Python compile, exact candidate visudo syntax, TypeScript source/test typechecks and diff checks passed. Unchanged chatbot suite: 579/580 passed after normalizing Windows shell line endings only in the isolated copy; one existing timing-sensitive Ollama bind-race test failed, then its complete 16-test file passed in isolation. No unrelated fix was made. No new physical performance measurement is claimed.

Self-verification: "Fail-closed proven" — foreign UID, missing peer, claimed app/stolen token and all unsafe Wi-Fi routes are negative tests. "Behavior executed" — actual Unix peer/socket permissions plus existing daemon button/voice handlers are exercised. "Labels honest" — live privilege restriction, physical acceptance and actual network restoration remain unverified; unsafe Wi-Fi is unavailable.
