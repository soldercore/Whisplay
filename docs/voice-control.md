# Conversational control candidate

Paired with the chatbot branch `codex/whisplay-voice-control`, base `3157bed`; this daemon branch starts at Control Center `6008414`. Source-only development; no production replacement or optional privilege installation is authorized. Read the chatbot's `docs/whisplay-voice-control.md` for actual model evidence, limits and deployment/rollback procedure.

The existing version-1 Unix socket advertises `control_api:1` in `health.ping` and accepts:

- `control.read {scope}`: capabilities/apps/display/audio/network/services; same UID.
- `control.execute {action,...}`: fixed validated allowlist, only the daemon-tracked live foreground GLaDOS process group. Existing internal app operations perform all effects.
- `control.present {ticket}`: speech/memory completed; request existing app exit, then wait for owned cleanup before showing the existing physical confirmation or Home/screen lock.
- `control.cancel {ticket}`: cancel an unpresented/pending handoff without changing settings.

No shell text, arbitrary path or arbitrary service name is accepted. Volume 0–100%, brightness 20–100%, relative changes ±20; Boolean enabled; services limited to start/restart ssh/ollama/whisper/piper. Wi-Fi/service/power capability requires the existing fixed root-owned, non-writable executable helper plus noninteractive sudo authorization. Missing binaries/controller/helper fail closed. Helper installation is separately scoped and was not performed.

Risky effects reuse existing 30-second Cancel-first confirmation and button recovery. Merely presenting a request does not perform it. A pending ticket expires after 120 seconds and is bound to the original process. New app focus wins over delayed handoff. The API serializes operations without holding the button/state lock over blocking Linux commands; the existing monitor uses a nonblocking advance. Read-only network/status operations may time out; they never establish internet/backend health.

`daemon/tests/voice_live_harness.py` is a deliberately restricted development test executable, not installed service code. It does not start hardware or a microphone. It permits real volume only, reports all other mutations unavailable, holds the chatbot kernel lock, and restores the original mixer value. Its test-only authorization differs explicitly from the production dispatcher. Do not deploy the harness or treat its successful text tests as physical acceptance.

Verification on the Pi: 93 daemon tests and 8 example tests pass. New tests cover authorization, validated bounds, missing/timed-out helper, actual mixer readback path, no action before physical selection, cancel/confirm, replay/expiry, and rejection of a stale ticket targeting a restarted chatbot. Actual Qwen capability/health/volume calls are preserved in the paired chatbot evidence. Full deployed speech, process-group authorization and physical handoff remain approval-gated acceptance work.
