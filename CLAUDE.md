# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Firmware for the ELEGOO Smart Robot Car V4.0 (Arduino Uno / AVR). This is a single Arduino sketch: `SmartRobotCarV4.0_V1_20230201.ino` plus vendored libraries, all flat in the repo root. `SmartRobotCarV4.0_V1_20230201.hex` is a prebuilt artifact of that sketch, not a build input.

Hardware (per `README.txt`): Uno MCU, HC-SR04 ultrasonic, LTI-PCB/ITR20001 line-tracking, GY-521 (MPU6050) gyro, TB6612 motor driver, ESP32-WROVER camera module. There are two board revisions of this car; the V4.0 pin sets are active and the V3.0 ones are left commented out in `DeviceDriverSet_xxx0.h` — do not "clean up" those comments.

## Build & flash

There is no build script, test suite, or linter in this repo. It is built by the Arduino toolchain.

Two gotchas before any compile:
- The Arduino toolchain requires the sketch folder to contain an `.ino` matching the folder name. This repo's folder is `smart-robot-car`, so `arduino-cli compile .` fails with `main file missing from sketch: .../smart-robot-car.ino`. Pointing at the `.ino` directly does **not** help — arduino-cli resolves it back to the parent folder and fails the same way. You must build from a copy or symlink tree in a directory named `SmartRobotCarV4.0_V1_20230201`.
- `.vscode/arduino.json` is stale: it names `SmartRobotCarV4.0_V1_20201229.ino` (a file that no longer exists) and a Windows `COM13` port. On macOS the port is typically `/dev/cu.usbserial-*` or `/dev/cu.usbmodem*`.
- **Unplug the ESP32-WROVER camera module before uploading.** It is wired to the Uno's UART by design (the phone app path is app → WiFi → ESP32 → serial → Uno), so it holds the same RX line the USB adapter needs. With it attached, `avrdude` reports `not in sync: resp=0x00` ten times and serial writes are silently dropped — while *reads* keep working fine, so boot chatter still appears and the port looks healthy. A one-directional failure like that is the signature of this problem, not a bad cable: USB carries both directions on one differential pair, so a cable fault cannot be direction-asymmetric.

Verified working recipe (arduino-cli 1.5.1, core `arduino:avr` 1.8.8):

```bash
arduino-cli core install arduino:avr
arduino-cli lib install FastLED@3.2.10 Servo     # version pin matters — see below

BUILD=/tmp/SmartRobotCarV4.0_V1_20230201         # folder name must match the .ino
mkdir -p "$BUILD" && cp *.ino *.h *.cpp "$BUILD"/
arduino-cli compile --fqbn arduino:avr:uno "$BUILD"
arduino-cli upload  --fqbn arduino:avr:uno -p /dev/cu.usbserial-XXXX "$BUILD"
arduino-cli monitor -p /dev/cu.usbserial-XXXX -c baudrate=9600
```

Serial is 9600 baud (`ApplicationFunctionSet_Init`).

### Flash is nearly full

A clean build is **29970 / 32256 bytes of flash (93%)** and 1165 / 2048 bytes of RAM (57%). There are roughly 2.3 KB of program space left. Any non-trivial feature addition can overflow the Uno, so check the size line on every compile; the compile-time debug gates (`_is_print`, `_Test_print`, `_Test_DeviceDriverSet`) are the usual place to buy space back (`_is_print 0` is worth ~600 bytes).

**Do not use `sprintf`/`printf` here.** A single `sprintf` links AVR's `vfprintf`, which costs ~950 bytes for float and width-specifier support this firmware never uses. Reintroducing one costs about 4% of total program space. Integer formatting for the serial replies uses `String(value)` inside the existing concatenation instead; `itoa(value, buf, 10)` is 186 bytes cheaper still if space ever gets tight again.

There is no C++ standard library on this target — the AVR toolchain ships no libstdc++, so `<format>`, `<string>`, `<vector>`, and `<cstdio>` are all absent, and the core builds with `-std=gnu++11 -fno-exceptions` on avr-g++ 7.3.0. Arduino's `String` and the vendored header-only libraries are what's available; `std::` anything is not.

Measuring where flash went, when you need to:

```bash
ELF=$(find ~/Library/Caches/arduino/sketches -name '*.ino.elf' | head -1)
NM=$(find ~/Library/Arduino15/packages -name avr-nm -type f | head -1)
"$NM" --size-sort -S -C "$ELF" | tail -20
```

Note that `main` shows up at ~8 KB because `loop()` inlines every mode handler into it, so per-function attribution above it is misleading.

### Library situation

`addLibrary/` holds zipped copies of FastLED, IRremote, NewPing, and pitches for install via the Arduino IDE. What actually resolves at compile time:

- **FastLED must be pinned to 3.2.10** — the version in `addLibrary/FastLED-master.zip`. Modern FastLED (3.10.5) fails to link: `multiple definition of __vector_11`, because it claims the TIMER1 vector that `Servo` also needs. `arduino-cli lib install FastLED` unpinned installs the broken version.
- **Servo is required** and is *not* bundled with the AVR core — without it the build dies at `DeviceDriverSet_xxx0.h:140: Servo.h: No such file or directory`.
- **Wire** is pulled in transitively (by the vendored I2Cdev/MPU6050) but ships with the core, so it needs no install.
- Those three — FastLED, Servo, Wire — are the only libraries resolved from outside the sketch folder.
- **IRremote, MPU6050, I2Cdev, and ArduinoJson v6.11.1 are vendored** in the repo root. The vendored headers win over same-named global libraries, so a globally installed IRremote (e.g. 4.7.1) sits there unused rather than causing a conflict — but keep edits in the vendored copies, since those are what compile.
- **NewPing is unused** — the ultrasonic driver hand-rolls `pulseIn`; the `NewPing` include is commented out.

## Architecture

Two layers, both implemented as classes with a single global instance each:

1. **`DeviceDriverSet_xxx0.{h,cpp}`** — one class per peripheral (`DeviceDriverSet_Motor`, `_ULTRASONIC`, `_Servo`, `_IRrecv`, `_RBGLED`, `_Key`, `_ITR20001`, `_Voltage`). All pin numbers live here as `#define`s inside the class bodies; this file is the single source of truth for the pinout. Drivers are stateless-ish and know nothing about modes.
2. **`ApplicationFunctionSet_xxx0.{h,cpp}`** — behavior. Instantiates every driver as a file-scope global (`AppMotor`, `AppServo`, `AppIRrecv`, …) and exposes `Application_FunctionSet`, the object the `.ino` drives.

`MPU6050_getdata.{h,cpp}` is a thin yaw-only wrapper over the vendored MPU6050/I2Cdev drivers (`MPU6050_dveGetEulerAngles` integrates `gz` with a calibrated offset).

### The mode state machine

Everything hangs off `Application_SmartRobotCarxxx0.Functional_Mode` (enum `SmartRobotCarFunctionalModel` in `ApplicationFunctionSet_xxx0.cpp`) — modes like `Standby_mode`, `TraceBased_mode`, `ObstacleAvoidance_mode`, `Follow_mode`, `Rocker_mode`, and the `CMD_*` programming/command modes.

`loop()` calls **every** application function unconditionally on every pass. Each function's first statement is an `if (Functional_Mode == X)` guard and it returns immediately otherwise. So:

- **Input sources set the mode**, they never act directly: `ApplicationFunctionSet_KeyCommand` (button on INT0), `ApplicationFunctionSet_IRrecv` (IR remote), `ApplicationFunctionSet_SerialPortDataAnalysis` (app/ESP32 JSON commands).
- **Mode handlers do the work** on subsequent loop passes.
- To add a behavior you add an enum value, a mode-guarded handler, a call in `loop()`, and a command that sets the mode. Skipping the `loop()` call is the usual reason new modes appear dead.

Non-blocking timing is done throughout with `static unsigned long` + `millis()` deltas inside functions. Keep that pattern — see below.

### Watchdog constraint (important)

`setup()` enables a 2-second watchdog (`wdt_enable(WDTO_2S)`) and `loop()` calls `wdt_reset()` once per pass. Any long blocking wait in the loop path will reboot the car. That is why:
- `delay_xxx()` in both `.cpp` files calls `wdt_reset()` then loops `delay(1)` — use it instead of `delay()` for anything over a few ms.
- Servo moves are inherently blocking (`attach` → `write` → `delay_xxx(450..500)` → `detach`), which is also why the servo is detached when idle.

### Straight-line control

`ApplicationFunctionSet_SmartRobotCarMotionControl(direction, speed)` is the single entry point for movement. For `Forward`/`Backward` it delegates to `ApplicationFunctionSet_SmartRobotCarLinearMotionControl`, which closes a proportional loop on MPU6050 yaw to compensate for motor mismatch. `Kp` and `UpperLimit` are selected per mode in a `switch` at the top of `MotionControl` (`TraceBased_mode` bypasses yaw correction entirely and drives the motors directly). Motor A is the **right** side, motor B the **left**.

Yaw calibration (`MPU6050_calibration`) runs at init and again from `ApplicationFunctionSet_Standby` once the ITR20001 sensors have reported the car on the ground for ~10 consecutive samples — `Car_LeaveTheGround` also forces a yaw-reference reset in the linear control loop.

### Serial command protocol

`ApplicationFunctionSet_SerialPortDataAnalysis` accumulates bytes until `}`, then parses with ArduinoJson (`StaticJsonDocument<200>`). Frames look like `{"H":"<serial no>","N":<cmd>,"D1":..,"D2":..,"T":..}`. `N` selects the command; the `switch` on `control_mode_N` in that function is the authoritative list (1–8 motion/servo/lighting, 21–23 sensor queries, 100/101/102/105/106/110 mode and app control). Replies are `{<H>_ok}`, `{<H>_<value>}`, or bare `{ok}`, gated on `#define _is_print 1`. Handler bodies live in the `CMD_*_xxx0` methods; note the overload pattern — the no-arg overload is the loop-driven one that reads the `CMD_is_*` member fields, the parameterized overload does the work.

The documentation of record for this protocol is ELEGOO's "Communication protocol for Smart Robot Car.pdf", which is not in this repo.

`tools/serial_check.py` exercises the `N:21` / `N:22` query replies against a connected car and validates the values are in range. Stdlib only — it configures the tty with `stty` and reads the device file, so it needs no pyserial. `--watch` polls continuously for checking that readings track physical reality. `tools/test_serial_check.py` covers it against a simulated car over a pty, so it runs with no hardware attached:

```bash
python3 tools/test_serial_check.py     # no car needed
python3 tools/serial_check.py          # against a real car
python3 tools/serial_check.py --watch
```

Note that `N:22` leaves `Functional_Mode` in `CMD_Programming_mode`; the script sends `N:100` afterward to restore standby.

## Conventions

- The `_xxx0` / `_xxx` suffixes are the vendor's naming, not a placeholder to fix.
- Code and comments are mixed English/Chinese; `README.txt` changelog entries are Chinese. Match the surrounding language when editing a block.
- Debug output is compile-time gated: `_is_print` and `_Test_print` in `ApplicationFunctionSet_xxx0.cpp`, `_Test_DeviceDriverSet` in `DeviceDriverSet_xxx0.h` (which also compiles in each driver's `*_Test()` method).
- Sensor thresholds are tunable members on `ApplicationFunctionSet` (`TrackingDetection_S/E/V`, `ObstacleDetection`, `VoltageDetection`, `Rocker_CarSpeed`); the IR remote adjusts `TrackingDetection_S` and `Rocker_CarSpeed` live.
- Files under root that are third-party and should not be hand-edited: `ArduinoJson-v6.11.1.h`, `MPU6050.*`, `I2Cdev.*`, `IRremote*`.
