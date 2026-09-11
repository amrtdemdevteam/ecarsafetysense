# KURURU SafetySense software and deployment audit

Date: 2026-09-11 (Asia/Bangkok)

Repository: `C:\TPCAP_SAFETYSENSE\01_CODE\ecarsafetysense`

Audited baseline: `pi4-pi5-support` at `b783e61`

Work branch: `test/audit-validation-20260911`

## Executive status

- The baseline worktree was clean and `pi4-pi5-support` tracked `origin/pi4-pi5-support` at `b783e61`.
- A read-only `git ls-remote` confirmed that the GitHub `pi4-pi5-support` and `master` refs still matched the local remote-tracking refs (`b783e61` and `aae36c8`, respectively) at audit time.
- `pi4-pi5-support` contains two commits beyond `master`. No merge, push, or edit to `master` was performed.
- Static validation and 12 hardware-free regression tests pass on the audit branch. This is software evidence only.
- `safetysenseno2@192.168.0.12` did not answer ping or TCP port 22 from the maintenance host. No SSH session was opened and no Raspberry Pi diagnostics were collected.
- Raspberry Pi, UART, GPIO, buzzer, sensor, boot, and vehicle behavior are **NOT VERIFIED** by this audit. No hardware PASS is claimed.

## Prioritized findings

### High

1. **The deployment guidance can bypass the production-support branch.** `readme.md:187-197` and `KURURU2_codebase_context.md:310-325` instruct operators to push/pull `master`; a fresh clone also defaults to `master`. That conflicts with the declared `pi4-pi5-support` production-support workflow and can deploy the Pi 4/Pi 5 compatibility work incorrectly. Replace this only under an approved Git/deployment requirement.

2. **The installer overwrites live code and configuration without backup, staging, rollback, or config preservation.** `install.sh:137-152` copies directly into `/opt` and immediately restarts the service. A partial install or unintended repository config can replace field-tuned thresholds. A future approved change should use preflight validation, staged files, explicit config migration/preservation, atomic replacement, post-start health checks, and rollback.

3. **Runtime configuration is trusted without semantic validation.** `safety_sense.py:31-70` reads required values but does not enforce ordered zones, supported frame rate, positive timing/frequency values, valid GPIO, or a sane median window. Bad-but-valid JSON can yield wrong alert behavior or a restart loop. The new host validator detects these conditions before deployment; runtime/startup validation remains missing.

4. **A buzzer worker failure can be silent while systemd still reports the service active.** GPIO writes occur in a daemon thread (`safety_sense.py:374-445`) without exception propagation or liveness supervision. An `lgpio` error can terminate only that thread while the main UART loop continues. This needs an approved fail-safe requirement before behavior is changed.

5. **A credential is stored in tracked documentation.** `KURURU2_codebase_context.md:337-343` contains SSH connection details including a plaintext password. Treat the credential as exposed: rotate it, move access data to an approved secret store, and decide separately whether Git history remediation is required. No credential or history change was made in this audit.

### Medium

6. **Two buzzer settings are misleading/dead configuration.** `FREQ_NEAR` and `DUTY` are loaded (`safety_sense.py:50-53`) but are not used to generate the waveform. `interpolate_freq()` returns MID frequency between FAR and NEAR, then SOLID at/below NEAR. The current config disables NEAR, so current observed mapping is internally consistent, but enabling NEAR later would not use `freq_near_hz`, and changing duty cycle would have no effect. Correcting this would change safety behavior and requires an approved requirement.

7. **The startup beep races the already-running buzzer worker.** `BuzzerController.__init__()` starts `_run()` before `_startup_beep()` (`safety_sense.py:374-378`). The worker writes LOW repeatedly while the startup routine writes HIGH, so the indication may be shortened or inconsistent. Hardware timing must be measured before changing it.

8. **Logging failures can stop the main safety loop.** `LogManager.write()` does not handle directory creation, open, encoding, or disk-full failures (`safety_sense.py:204-219`). Such a failure escapes the main loop and causes a systemd restart. Define the desired fail-safe behavior and add fault-injection tests before changing this.

9. **The installer is not reproducible or offline-safe.** It runs `apt-get update`, installs unpinned distro packages, and falls back to unpinned system-wide pip packages (`install.sh:118-126`). There is no supported OS matrix, version capture, lock file, package cache, or image manifest.

10. **Service privilege and hardening are broader than documented need.** The unit runs as root and has no systemd sandboxing (`safety_sense.service:5-20`). GPIO/UART/log access may require specific groups/capabilities, but least-privilege operation, filesystem protections, and device restrictions have not been evaluated on target hardware.

11. **Service readiness is time-based.** The installer sleeps two seconds and calls `systemctl status` (`install.sh:155-157`), but does not verify sustained uptime, a successful UART frame, log write, buzzer-thread liveness, deployed hashes, or rollback on failure.

12. **Desktop monitor deployment has an undeclared dependency and global scope.** The installer copies a global XDG autostart entry that assumes `lxterminal` exists (`safety_sense_monitor.desktop:4`) but does not install/check it. Headless and non-LXDE images may not provide the monitor, and every desktop user receives the entry.

13. **UART frame-rate configuration is not acknowledged.** `_set_framerate()` writes a command, sleeps, flushes input, and logs success without checking a sensor response (`safety_sense.py:261-269`). Actual sensor rate remains a hardware verification item.

14. **Documentation has stale operational examples/comments.** The README JSONL example shows an enabled NEAR-style record and a non-step frequency (`readme.md:172-179`), while the active config disables NEAR and runtime is step-based. `config.json:48-50` says the watchdog increased to five seconds, but the value is ten seconds. These do not change runtime but can mislead diagnostics.

### Low / maintainability

15. `Watchdog._logged` is created dynamically rather than initialized (`safety_sense.py:344-350, 503-507`), and main code writes this internal attribute directly.
16. Broad `except Exception` blocks in config and log retention code reduce diagnostic specificity.
17. UART parsing, application orchestration, GPIO output, config loading, and logging are tightly coupled through import-time globals, making isolation and dependency injection difficult.
18. The project has no packaging metadata, dependency declaration, CI workflow, release/version identifier, changelog, or documented rollback procedure.

## Automated test inventory

Before this audit, no automated tests or repository validation scripts were present.

Added on `test/audit-validation-20260911`:

- `tools/validate_repo.py`: 37 static checks covering required files, LF endings, service essentials, config schema/ranges, Python compilation, installer shell syntax, and the read-only installer summary.
- `tests/test_safety_sense.py`: 12 regression tests covering current distance-to-zone/frequency boundaries, rolling median, UART noise resynchronization, valid/bad checksum frames, zero/out-of-range handling, and zone-filter hysteresis/hold behavior.
- `VALIDATION.md`: gated host, read-only Pi, controlled deployment, bench, and vehicle/site validation plan.

Important missing automated coverage:

- full main-loop state transitions and precedence among normal, SENSOR_WARN, and SENSOR_FAIL states;
- watchdog thread timing/recovery using a controllable clock;
- buzzer waveform timing, target changes mid-pulse, GPIO exceptions, worker liveness, cleanup, and startup indication;
- logging I/O failures, JSONL integrity, retention boundaries, concurrent access, clock changes, and disk-full behavior;
- serial partial-read timing, long noise streams, back-to-back frames, frame-rate command/ack behavior, disconnect/reconnect, and exceptions;
- installer tests in containers/images for every supported Raspberry Pi OS release, including rollback and preserved local config;
- systemd unit verification with `systemd-analyze verify` on Linux and reboot/startup integration tests;
- Pi 4/Pi 5 UART alias mapping and `lgpio` integration;
- instrumented hardware and vehicle acceptance tests.

## Validation evidence

Completed successfully on the audit host:

```text
tools/validate_repo.py                    PASS (37 checks)
python -m unittest discover -s tests -v  PASS (12 tests)
git diff --check                         PASS
install.sh bash -n                       PASS
install.sh --print-summary               PASS (read-only mode)
remote refs                              MATCH local tracking refs at audit time
```

Not executed or not available:

```text
SSH / Raspberry Pi diagnostics           UNAVAILABLE (ping and TCP/22 failed)
systemd-analyze on target OS              NOT RUN
UART / lgpio / buzzer / sensor tests      NOT RUN
installer deployment or service restart   NOT AUTHORIZED / NOT RUN
hardware or vehicle acceptance            NOT RUN
```

## Recommended sequence

1. Rotate the documented SSH credential and approve a branch-based deployment policy that never instructs routine pushes to `master`.
2. Run the read-only Gate 2 checklist in `VALIDATION.md` when the Pi is reachable; archive command output, deployed hashes, unit contents, and journal evidence.
3. Approve requirements for runtime config validation, actuator-thread failure behavior, startup indication, logging failure behavior, and use/removal of the unused buzzer settings before code changes.
4. Make installer/config-preservation and rollback work a separate reviewed change, tested on disposable Pi 4 and Pi 5 images.
5. Complete bench and vehicle gates with retained measurements before recording hardware PASS.

## Change-control statement

This audit did not modify runtime logic, zone thresholds, alert behavior, installer behavior, systemd behavior, `master`, the Raspberry Pi, or the Git remote. Only validation/tests, a validation plan, ignore rules for Python bytecode, and this report were added on the dedicated test branch.
