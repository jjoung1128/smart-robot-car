#!/usr/bin/env python3
"""Exercise serial_check.py against a simulated car over a pty.

No hardware needed. Spawns a fake firmware on the master side of a pty and
points serial_check.py at the slave, so the framing, timeout, validation and
diagnostic logic all get covered.

  ./tools/test_serial_check.py
"""

import json
import os
import pty
import select
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "serial_check.py")

BOOT_CHATTER = b"MPU6050_chip_id: 104\r\n"


def healthy(frame):
    """Byte-for-byte what the real firmware sends when everything works."""
    h, n, d1 = frame.get("H"), frame.get("N"), frame.get("D1")
    if n == 21 and d1 == 1:
        return "{%s_false}" % h
    if n == 21 and d1 == 2:
        return "{%s_37}" % h
    if n == 22:
        return "{%s_%d}" % (h, {0: 988, 1: 991, 2: 975}[d1])
    if n == 100:
        return "{ok}"
    return None


def broken_changed_path(frame):
    """Control branch fine, changed formatting path emits junk."""
    h, n, d1 = frame.get("H"), frame.get("N"), frame.get("D1")
    if n == 21 and d1 == 1:
        return "{%s_false}" % h          # untouched code, still correct
    if n == 21 and d1 == 2:
        return "{%s_}" % h               # empty payload
    if n == 22:
        return "{%s_@#!}" % h            # not an integer
    if n == 100:
        return "{ok}"
    return None


def out_of_range(frame):
    """Well-formed integers, implausible magnitudes."""
    h, n, d1 = frame.get("H"), frame.get("N"), frame.get("D1")
    if n == 21 and d1 == 1:
        return "{%s_true}" % h
    if n == 21 and d1 == 2:
        return "{%s_99999}" % h          # past the 150cm clamp
    if n == 22:
        return "{%s_4096}" % h           # past 10-bit analogRead
    if n == 100:
        return "{ok}"
    return None


def dead(frame):
    return None


def serve(master_fd, responder, stop):
    """Mimic ApplicationFunctionSet_SerialPortDataAnalysis: read until '}'."""
    os.write(master_fd, BOOT_CHATTER)
    buf = ""
    while not stop.is_set():
        ready, _, _ = select.select([master_fd], [], [], 0.05)
        if not ready:
            continue
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            return
        if not chunk:
            return
        buf += chunk.decode("utf-8", "replace")
        while "}" in buf:
            end = buf.index("}") + 1
            frame, buf = buf[:end], buf[end:]
            start = frame.find("{")
            if start == -1:
                continue
            try:
                obj = json.loads(frame[start:end])
            except json.JSONDecodeError:
                os.write(master_fd, b"error:deserializeJson\r\n")
                continue
            reply = responder(obj)
            if reply:
                os.write(master_fd, reply.encode())


def run_against(responder, extra_args=()):
    master, slave = pty.openpty()
    stop = threading.Event()
    thread = threading.Thread(target=serve, args=(master, responder, stop), daemon=True)
    thread.start()
    try:
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--port", os.ttyname(slave),
             "--settle", "0", "--timeout", "0.5", *extra_args],
            capture_output=True, text=True, timeout=60,
        )
        return proc
    finally:
        stop.set()
        thread.join(timeout=2)
        os.close(master)
        os.close(slave)


FAILURES = []


def expect(condition, message):
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  FAIL {message}")
        FAILURES.append(message)


def main():
    print("healthy car:")
    proc = run_against(healthy)
    expect(proc.returncode == 0, f"exit 0 (got {proc.returncode})")
    expect(proc.stdout.count("PASS") == 5, f"5 PASS rows (got {proc.stdout.count('PASS')})")
    expect("All checks passed" in proc.stdout, "reports success")
    expect("standby" in proc.stdout, "mentions restoring standby")
    # The pty emits BOOT_CHATTER before any reply, so 5 passing rows is itself
    # the evidence that leading non-frame noise is tolerated.
    expect("37" in proc.stdout and "988" in proc.stdout, "surfaces the parsed values")
    if proc.returncode != 0:
        print(proc.stdout, proc.stderr)

    print("\nbroken changed path (control still good):")
    proc = run_against(broken_changed_path)
    expect(proc.returncode == 1, f"exit 1 (got {proc.returncode})")
    expect("isolates the fault to the changed formatting path" in proc.stdout,
           "blames the changed path, not the link")
    expect("ultrasonic distance" in proc.stdout, "names the failing check")
    expect(proc.stdout.count("FAIL") == 4, f"4 FAIL rows (got {proc.stdout.count('FAIL')})")

    print("\nvalues out of physical range:")
    proc = run_against(out_of_range)
    expect(proc.returncode == 1, f"exit 1 (got {proc.returncode})")
    expect("out of range" in proc.stdout, "rejects implausible magnitudes")

    print("\ndead link (no replies):")
    proc = run_against(dead)
    expect(proc.returncode == 1, f"exit 1 (got {proc.returncode})")
    expect("link-level problem" in proc.stdout,
           "blames the link when the control check also fails")

    print("\nwatch mode:")
    master, slave = pty.openpty()
    stop = threading.Event()
    thread = threading.Thread(target=serve, args=(master, healthy, stop), daemon=True)
    thread.start()
    try:
        proc = subprocess.Popen(
            [sys.executable, SCRIPT, "--port", os.ttyname(slave), "--settle", "0",
             "--timeout", "0.5", "--interval", "0.05", "--watch"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(2.0)
        proc.send_signal(signal.SIGINT)   # exercise the Ctrl-C path
        out, _ = proc.communicate(timeout=10)
        expect("37" in out and "988" in out, "streams live values")
        expect("standby" in out, "restores standby on Ctrl-C")
    finally:
        stop.set()
        thread.join(timeout=2)
        os.close(master)
        os.close(slave)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} assertion(s) failed")
        return 1
    print("all assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
