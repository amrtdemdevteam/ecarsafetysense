#!/usr/bin/env python3
"""Static, hardware-free validation for the SafetySense repository."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"PASS: {message}")
    else:
        print(f"FAIL: {message}")
        ERRORS.append(message)


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def nested(config: dict, section: str, key: str) -> object:
    try:
        return config[section][key]
    except (KeyError, TypeError):
        ERRORS.append(f"config contains {section}.{key}")
        print(f"FAIL: config contains {section}.{key}")
        return None


def validate_config() -> None:
    config_path = ROOT / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        check(False, f"config.json is readable JSON ({exc})")
        return

    check(True, "config.json is readable JSON")

    port = nested(config, "uart", "port")
    baud = nested(config, "uart", "baud")
    pin = nested(config, "pins", "buzzer")
    clear = nested(config, "zones", "clear_cm")
    far = nested(config, "zones", "far_cm")
    mid = nested(config, "zones", "mid_cm")
    near = nested(config, "zones", "near_cm")
    median = nested(config, "sensor", "median_window")
    minimum = nested(config, "sensor", "min_dist_cm")
    maximum = nested(config, "sensor", "max_dist_cm")
    strength = nested(config, "sensor", "min_strength")
    rate = nested(config, "sensor", "frame_rate_hz")
    hysteresis = nested(config, "filter", "hysteresis_frames")
    hold = nested(config, "filter", "min_hold_sec")
    timeout = nested(config, "watchdog", "timeout_sec")
    fail_threshold = nested(config, "health", "fail_count_threshold")
    log_dir = nested(config, "log", "dir")
    log_max = nested(config, "log", "max_mb")
    retain = nested(config, "log", "retain_days")
    log_check = nested(config, "log", "check_every_sec")

    check(isinstance(port, str) and port.startswith("/dev/"), "UART port is an absolute device path")
    check(isinstance(baud, int) and baud > 0, "UART baud is a positive integer")
    check(isinstance(pin, int) and 0 <= pin <= 27, "buzzer pin is a valid BCM GPIO number")

    zones = (clear, far, mid, near)
    check(all(is_number(value) for value in zones), "zone thresholds are numeric")
    if all(is_number(value) for value in zones):
        check(clear >= far >= mid >= near > 0, "zone thresholds satisfy clear >= far >= mid >= near > 0")

    check(isinstance(median, int) and median > 0 and median % 2 == 1, "median window is a positive odd integer")
    check(is_number(minimum) and is_number(maximum) and 0 <= minimum <= maximum, "sensor distance range is ordered and non-negative")
    check(is_number(strength) and strength >= 0, "minimum signal strength is non-negative")
    check(rate in {10, 20, 50, 100}, "sensor frame rate has a supported command")
    check(isinstance(hysteresis, int) and hysteresis >= 1, "hysteresis frame count is a positive integer")
    check(is_number(hold) and hold >= 0, "minimum hold time is non-negative")
    check(is_number(timeout) and timeout > 0, "watchdog timeout is positive")
    check(isinstance(fail_threshold, int) and fail_threshold >= 1, "health failure threshold is a positive integer")
    check(isinstance(log_dir, str) and log_dir.startswith("/"), "log directory is absolute")
    check(is_number(log_max) and log_max > 0, "log size limit is positive")
    check(isinstance(retain, int) and retain >= 1, "log retention is at least one day")
    check(is_number(log_check) and log_check > 0, "log maintenance interval is positive")

    buzzer_keys = ("freq_far_hz", "freq_mid_hz", "freq_near_hz")
    frequencies = [nested(config, "buzzer", key) for key in buzzer_keys]
    duty = nested(config, "buzzer", "duty_cycle_pct")
    check(all(is_number(value) and value > 0 for value in frequencies), "configured buzzer frequencies are positive")
    check(is_number(duty) and 0 < duty <= 100, "buzzer duty cycle is in (0, 100]")


def validate_files() -> None:
    required = (
        "safety_sense.py",
        "config.json",
        "install.sh",
        "safety_sense.service",
        "safety_sense_monitor.desktop",
    )
    for name in required:
        check((ROOT / name).is_file(), f"required deployment file exists: {name}")

    for name in required:
        path = ROOT / name
        if path.is_file():
            check(b"\r\n" not in path.read_bytes(), f"deployment file uses LF endings: {name}")

    service = (ROOT / "safety_sense.service").read_text(encoding="utf-8")
    check("ExecStart=/usr/bin/python3 /opt/safety_sense/safety_sense.py" in service, "systemd ExecStart targets the installed runtime")
    check("Restart=on-failure" in service, "systemd restart policy is configured")
    check("WantedBy=multi-user.target" in service, "systemd unit is enabled for multi-user boot")


def validate_python() -> None:
    try:
        source = (ROOT / "safety_sense.py").read_text(encoding="utf-8")
        compile(source, str(ROOT / "safety_sense.py"), "exec")
    except (OSError, UnicodeError, SyntaxError) as exc:
        check(False, f"safety_sense.py compiles ({exc})")
    else:
        check(True, "safety_sense.py compiles")


def validate_shell() -> None:
    bash = shutil.which("bash")
    if bash is None and os.name == "nt":
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            candidate = Path(program_files) / "Git" / "bin" / "bash.exe"
            if candidate.is_file():
                bash = str(candidate)
    if bash is None:
        print("SKIP: bash syntax and installer summary checks (bash not available)")
        return

    shell_env = os.environ.copy()
    if os.name == "nt":
        git_root = Path(bash).resolve().parent.parent
        shell_env["PATH"] = os.pathsep.join(
            (str(git_root / "usr" / "bin"), str(git_root / "bin"), shell_env.get("PATH", ""))
        )

    syntax = subprocess.run(
        [bash, "-n", str(ROOT / "install.sh")],
        capture_output=True,
        text=True,
        env=shell_env,
        check=False,
    )
    check(syntax.returncode == 0, f"install.sh passes bash -n{': ' + syntax.stderr.strip() if syntax.stderr.strip() else ''}")

    if os.name == "nt":
        shell_env["PYTHON_BIN"] = sys.executable
        summary_command = [bash, "-lc", "./install.sh --print-summary ./config.json"]
    else:
        summary_command = [bash, str(ROOT / "install.sh"), "--print-summary", str(ROOT / "config.json")]

    summary = subprocess.run(
        summary_command,
        capture_output=True,
        text=True,
        env=shell_env,
        cwd=ROOT,
        check=False,
    )
    details = summary.stderr.strip()
    check(summary.returncode == 0, f"installer config summary runs without changing the system{': ' + details if details else ''}")
    check("NEAR" in summary.stdout and "disabled" in summary.stdout, "installer summary reflects the disabled NEAR zone")


def main() -> int:
    validate_files()
    validate_config()
    validate_python()
    validate_shell()
    if ERRORS:
        print(f"\nValidation failed: {len(ERRORS)} check(s)")
        return 1
    print("\nValidation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
