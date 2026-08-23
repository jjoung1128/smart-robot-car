#!/usr/bin/env python3
"""Verify the N:21 / N:22 sensor-query serial replies against a live car.

Stdlib only on purpose -- no pyserial, no venv. The port is configured with
stty(1) and then read/written as a plain character device.

  ./tools/serial_check.py                 # run the checks, print a table
  ./tools/serial_check.py --watch         # live values, for the hand-wave test
  ./tools/serial_check.py --port /dev/cu.usbserial-1234

Exit status is 0 when every check passes, 1 otherwise.
"""

import argparse
import glob
import json
import os
import re
import select
import subprocess
import sys
import time

BAUD = 9600  # ApplicationFunctionSet_Init

# {"H":"<serial no>","N":<cmd>,...} -> {<serial no>_<payload>}
REPLY_RE = re.compile(r"\{(?P<h>[^_{}]*)_(?P<payload>[^{}]*)\}")

# The ultrasonic driver clamps at 150cm; the ITR20001 values are 10-bit
# analogRead results.
DISTANCE_MAX = 150
ANALOG_MAX = 1023


def find_port():
    """Pick the likeliest USB-serial device, skipping macOS's built-ins."""
    candidates = []
    for pattern in ("/dev/cu.usbserial*", "/dev/cu.usbmodem*", "/dev/cu.wchusbserial*"):
        candidates.extend(glob.glob(pattern))
    candidates = [c for c in candidates if "Bluetooth" not in c and "debug-console" not in c]
    if not candidates:
        sys.exit(
            "No USB serial port found.\n"
            "Plug the car in and check `arduino-cli board list`, "
            "or pass --port explicitly."
        )
    if len(candidates) > 1:
        sys.exit(
            "Multiple candidate ports; pass one with --port:\n  "
            + "\n  ".join(sorted(candidates))
        )
    return candidates[0]


def configure(port):
    """Put the tty in raw mode at 9600 baud.

    Done after the open() so the driver can't reset termios underneath us.
    """
    cmd = ["stty", "-f", port, str(BAUD), "cs8", "-cstopb", "-parenb", "raw", "-echo"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  warning: stty failed ({result.stderr.strip()}); "
              f"continuing with the port's existing settings", file=sys.stderr)


def drain(fd, seconds):
    """Swallow boot chatter. Init prints 'MPU6050_chip_id: ...' among others."""
    deadline = time.monotonic() + seconds
    noise = b""
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], deadline - time.monotonic())
        if ready:
            noise += os.read(fd, 4096)
    return noise.decode("utf-8", "replace")


def send(fd, **fields):
    frame = json.dumps(fields, separators=(",", ":")).encode()
    os.write(fd, frame)
    return frame.decode()


def read_reply(fd, timeout):
    """Accumulate until '}' closes a frame. Replies carry no newline."""
    deadline = time.monotonic() + timeout
    buf = ""
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], max(0.0, deadline - time.monotonic()))
        if not ready:
            continue
        chunk = os.read(fd, 4096)
        if not chunk:
            continue
        buf += chunk.decode("utf-8", "replace")
        if "}" in buf:
            return buf
    return buf


def bounded_int(payload, lo, hi):
    if not re.fullmatch(r"-?\d+", payload):
        return False, "not an integer"
    value = int(payload)
    if not lo <= value <= hi:
        return False, f"out of range {lo}..{hi}"
    return True, str(value)


CHECKS = [
    # label, frame, validator, exercises_changed_code
    ("obstacle flag (control)", {"N": 21, "D1": 1},
     lambda p: (p in ("true", "false"), p if p in ("true", "false") else "expected true/false"),
     False),
    ("ultrasonic distance", {"N": 21, "D1": 2},
     lambda p: bounded_int(p, 0, DISTANCE_MAX), True),
    ("tracking left", {"N": 22, "D1": 0},
     lambda p: bounded_int(p, 0, ANALOG_MAX), True),
    ("tracking middle", {"N": 22, "D1": 1},
     lambda p: bounded_int(p, 0, ANALOG_MAX), True),
    ("tracking right", {"N": 22, "D1": 2},
     lambda p: bounded_int(p, 0, ANALOG_MAX), True),
]


def run_check(fd, index, label, frame, validator, timeout):
    serial_no = f"t{index}"
    sent = send(fd, H=serial_no, **frame)
    raw = read_reply(fd, timeout)
    match = REPLY_RE.search(raw)
    if not match:
        shown = raw.strip().replace("\r", "").replace("\n", " ") or "(nothing)"
        return False, sent, shown, "no reply frame"
    if match.group("h") != serial_no:
        return False, sent, match.group(0), f"serial no mismatch, wanted {serial_no}"
    ok, detail = validator(match.group("payload"))
    return ok, sent, match.group(0), detail


def restore_standby(fd, timeout):
    """N:22 leaves Functional_Mode in CMD_Programming_mode; N:100 clears it."""
    send(fd, H="t0", N=100)
    read_reply(fd, timeout)


def cmd_check(fd, args):
    print(f"port {args.port} @ {BAUD} baud\n")
    rows, failures, control_ok = [], [], True
    for i, (label, frame, validator, changed) in enumerate(CHECKS, start=1):
        ok, sent, got, detail = run_check(fd, i, label, frame, validator, args.timeout)
        rows.append((ok, label, sent, got, detail, changed))
        if not ok:
            failures.append((label, changed))
            if not changed:
                control_ok = False

    width = max(len(r[1]) for r in rows)
    for ok, label, sent, got, detail, changed in rows:
        mark = "PASS" if ok else "FAIL"
        tag = "" if changed else "  [untouched code]"
        print(f"  {mark}  {label:<{width}}  {sent}  ->  {got}")
        if not ok:
            print(f"        {detail}{tag}")
        elif not changed:
            print(f"        {detail}{tag}")
        else:
            print(f"        value {detail}")

    restore_standby(fd, args.timeout)
    print("\n  sent {\"H\":\"t0\",\"N\":100} to return the car to standby")

    if not failures:
        print("\nAll checks passed. Values are well-formed and in range.")
        print("Now confirm they track reality -- rerun with --watch and move "
              "your hand in front of the sensor.")
        return 0

    print(f"\n{len(failures)} check(s) failed.")
    changed_failed = [lbl for lbl, changed in failures if changed]
    if not control_ok:
        print("The untouched control check failed too, so this is most likely a\n"
              "link-level problem -- wrong port, wrong baud, a failed upload, or\n"
              "the ESP32 camera module contending for the UART -- not the\n"
              "formatting change.")
    elif changed_failed:
        print("The untouched control check passed while these failed:\n  - "
              + "\n  - ".join(changed_failed)
              + "\nThat isolates the fault to the changed formatting path.")
    return 1


def cmd_watch(fd, args):
    print(f"port {args.port} @ {BAUD} baud -- Ctrl-C to stop\n")
    print("  Move a hand toward the ultrasonic head; lift the car off the "
          "ground.\n  Values should track what you do. All three tracking "
          "channels read\n  >950 when the car is sitting on a surface.\n")
    print(f"  {'distance':>10}  {'left':>6}  {'middle':>6}  {'right':>6}")
    probes = [("N", 21, "D1", 2), ("N", 22, "D1", 0), ("N", 22, "D1", 1), ("N", 22, "D1", 2)]
    try:
        while True:
            values = []
            for i, (_, n, _, d1) in enumerate(probes, start=1):
                send(fd, H=f"w{i}", N=n, D1=d1)
                match = REPLY_RE.search(read_reply(fd, args.timeout))
                values.append(match.group("payload") if match else "--")
            # flush so values stream when stdout is a pipe or a log file
            print(f"  {values[0]:>10}  {values[1]:>6}  {values[2]:>6}  {values[3]:>6}",
                  flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n\n  stopping")
    finally:
        restore_standby(fd, args.timeout)
        print("  sent {\"H\":\"t0\",\"N\":100} to return the car to standby")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", help="serial device (auto-detected if omitted)")
    parser.add_argument("--watch", action="store_true",
                        help="poll continuously instead of running the checks")
    parser.add_argument("--timeout", type=float, default=2.0,
                        help="seconds to wait for one reply (default 2.0)")
    parser.add_argument("--settle", type=float, default=3.0,
                        help="seconds to wait for the board to boot after "
                             "opening the port (default 3.0)")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="--watch poll interval in seconds (default 0.5)")
    args = parser.parse_args()

    if not args.port:
        args.port = find_port()

    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        configure(args.port)
        if args.settle > 0:
            print(f"waiting {args.settle:g}s for the board to boot...")
            noise = drain(fd, args.settle)
            if noise.strip():
                first = noise.strip().splitlines()[0]
                print(f"  boot output: {first}")
        return cmd_watch(fd, args) if args.watch else cmd_check(fd, args)
    finally:
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
