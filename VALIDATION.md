# SafetySense software validation plan

This plan separates software evidence from Raspberry Pi and vehicle evidence. A passing host test does not establish hardware PASS.

## Gate 1: repository and configuration (host, no hardware)

Run from the repository root:

```bash
python3 tools/validate_repo.py
python3 -m unittest discover -s tests -v
git diff --check
git status --short --branch
```

Acceptance criteria:

- deployment files exist and use LF line endings;
- `config.json` is valid and its thresholds are ordered;
- the Python runtime compiles;
- the installer passes `bash -n` and its read-only summary matches the config;
- UART parser, distance handling, zone boundaries, rolling median, and zone filter regression tests pass;
- the worktree contains only reviewed changes on a non-`master` branch.

## Gate 2: clean Raspberry Pi diagnostics (read-only)

Collect and retain the output without restarting services or changing files:

```bash
hostname
uname -a
cat /proc/device-tree/model | tr -d '\0'
cat /etc/os-release
python3 --version
python3 -c 'import serial, lgpio; print(serial.__version__); print(lgpio.__file__)'
readlink -f /dev/serial0
ls -l /dev/serial0
systemctl is-enabled safety_sense
systemctl is-active safety_sense
systemctl status safety_sense --no-pager -l
journalctl -u safety_sense -b --no-pager -n 200
systemctl cat safety_sense
sha256sum /opt/safety_sense/safety_sense.py /opt/safety_sense/config.json
find /var/log/safety_sense -maxdepth 1 -type f -printf '%TY-%Tm-%Td %TH:%TM %s %p\n' | sort
```

Compare deployed hashes and service content with the intended release. Diagnose any UART mapping, import, permission, restart-loop, or log-retention issue before proceeding.

## Gate 3: controlled Pi software test (maintenance window)

Requires explicit authorization because it can install files or restart the service.

- back up `/opt/safety_sense`, the unit file, and deployed config;
- run the repository validation on the Pi;
- deploy the reviewed commit with the installer;
- verify `systemctl is-active`, startup logs, stable process uptime, UART target, and JSONL log validity;
- power-cycle and confirm automatic start;
- confirm the buzzer is LOW when the service is stopped and after graceful shutdown.

## Gate 4: bench hardware validation

Requires an approved test setup and observer. Record Pi model, OS image, code commit, config hash, sensor serial number, wiring revision, supply voltage, and test timestamp.

- validate startup indication and normal CLEAR behavior;
- inject known TFmini frames or use measured targets at every boundary and just outside each boundary;
- verify actual buzzer patterns and response latency with instrumentation;
- disconnect UART and verify watchdog timing and failure pattern;
- test corrupted/partial frames and reconnection recovery;
- verify GPIO goes LOW on service stop, crash/restart, and shutdown;
- inspect logs for correct timestamps, zone transitions, failure events, retention, and no restart loop.

## Gate 5: vehicle/site acceptance

Run the approved mock-up and warehouse scenarios for each mounting configuration. Include sunlight, open-area `dist=0`, rapid approach, vibration, power interruption, and reboot cases. Hardware PASS may be recorded only from observed results with retained evidence; host tests and remote logs alone are insufficient.
