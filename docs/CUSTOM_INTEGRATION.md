# Custom Whisplay launcher: v3.2.7 integration

Reference: `cyber-terminal-menu` at `53a9d6e237d8612b15374d0ec74191d52ea9495f`, based on v3.2.3. Target: official v3.2.7 at `736975188ebbe146d319e450aad19c218a310611`. The published stable release, annotated tag object and verification time are recorded in `../upstream-integration.json`.

Actual test results and unverified builds/hardware are recorded in [VALIDATION.md](VALIDATION.md).

The later, isolated control-center candidate based on installed revision `5533f54`
is documented in [CONTROL_CENTER.md](CONTROL_CENTER.md). It extends the daemon's
built-in menus without changing drivers or chatbot code. Its Pi checks use a
fake board and read-only status probes; physical controls remain unverified.

This isolated development branch preserves the three custom launcher commits, font licences/vendoring provenance, palette/safe area, desktop/internal screens and permanent classic fallback. It includes the complete official v3.2.7 history: autostart, Joy input/Wi-Fi keyboard, platform/audio work, MP4 cleanup and image overlay fix. No driver, service or production image has been installed.

## Renderer conflict resolution

The new daemon initializes `model`, joystick input and autostart before creating the selected renderer. It passes `joy_mode` as a keyword to either the custom adapter or upstream renderer. `FallbackDesktopRenderer` accepts that keyword while preserving its existing optional positional `cyber_factory` argument.

Ordinary Whisplay retains the cyber renderer and classic fallback. Whisplay Joy deliberately uses the complete upstream classic renderer so joystick legends and screen-keyboard controls remain available. There was no prior custom Joy UI to preserve; this branch does not claim to implement one. Actual constructor tests exercise both models and autostart configuration using a fake board, in addition to the original UI and upstream control tests.

The chatbot companion is a separate branch based on chatbot v2.1.9. That app's new `app.autostart.set` path requires a capable daemon (official v3.2.5+); application registration does not establish physical readiness.

## Validation commands

Run off-device tests without invoking installer scripts or accessing real GPIO/I2C:

```sh
python3 -B -m unittest discover -s daemon/tests -v
python3 -B -m unittest discover -s example/tests -v
git diff --check
```

Pillow and NumPy are required for real rendering in the fake-board tests. Check that tests are not skipped due to missing imaging packages. Existing tests use hardware substitutes; their success does not establish real display/input/driver behavior.

The kernel module's `make -C audio/whisplay-soundcard/src` additionally needs a compatible kernel build tree and target configuration. Missing headers in a development container is a documented unverified build, not successful compilation. Do not run `make install`, `install_driver.sh`, daemon service installation or a release-image workflow as part of a source integration check.

## Physical tests still required

- Identify installed Whisplay variant, custom driver/daemon revision, OS/kernel/firmware and local service overrides before deployment.
- On a separate system copy, build/install against the actual Pi kernel and verify codec detection, capture/playback, mixer, GPIO/SPI and cold boot.
- Verify cyber layout/fallback, rounded corners, fonts, battery/Wi-Fi status, short/long/quad press, Home, foreground focus/framebuffer and app exit/relaunch.
- Verify autostart and restart together with the paired chatbot's per-user lock/owned-process cleanup. No duplicated app or unrelated backend termination.
- Test actual Joy navigation/keyboard only if Joy is a required hardware profile; do not infer that support from standard Whisplay tests.
- Keep driver/kernel rollback independent of application rollback. No physical Pi has been accessed in this work.

## Small incremental-update process

1. Preserve this branch's accepted tip and historical reference `53a9d6e`; never rebase/overwrite stable published branches.
2. Verify the newest official stable release through release metadata and the peeled Git tag; update `upstream-integration.json` with exact identities.
3. Start a new isolated worktree/branch from the accepted custom tip. Read only the new upstream delta and the custom overlap, then merge the verified commit with history.
4. Review daemon/renderer constructors, view models, input, focus, autostart and cleanup. Keep custom fonts/provenance and safe-area constants aligned with the chatbot. If preserving a required contract cannot be demonstrated, stop that integration and document the conflict.
5. Run both complete Python suites and syntax checks, then build/test for the actual target kernel. Record omissions and remaining physical checks before review.
6. Deliver the development branch for review. Preparing/testing an app/driver pair is separate from publishing releases, enabling services or deploying production. No automatic updater is introduced.
