# ELEGOO Smart Robot Car V4.0 — firmware

Arduino sketch for the ELEGOO Smart Robot Car V4.0 (Uno / ATmega328P), based on
ELEGOO's `SmartRobotCarV4.0_V1_20230201` release with a small number of fixes on
top. See [Changes from the ELEGOO original](#changes-from-the-elegoo-original).

`README.txt` is the vendor's original changelog and is left as-is.
[`CLAUDE.md`](CLAUDE.md) has the deeper architecture notes — the mode state
machine, the driver layer, the serial protocol, and the sensor quirks.

## Hardware

| Part | Module |
| --- | --- |
| MCU | Arduino Uno |
| Ultrasonic rangefinder | HC-SR04 |
| Line tracking | LTI-PCB (3× ITR20001 reflective IR) |
| Gyro / accelerometer | GY-521 (MPU6050) |
| Motor driver | TB6612 |
| Camera / WiFi | ESP32-WROVER |

Motor A is the **right** side, motor B the **left**. All pin assignments live in
`DeviceDriverSet_xxx0.h`; that file is the single source of truth for the pinout.
Both board revisions are in there — the V4.0 pin set is active, the V3.0 one is
commented out.

## Before you upload: unplug the camera module

**Disconnect the ESP32-WROVER camera module before every upload.** It shares the
Uno's UART by design — the phone-app path is app → WiFi → ESP32 → serial → Uno —
so it holds the RX line that the USB adapter needs.

Leave it attached and `avrdude` reports `not in sync: resp=0x00` ten times.
The confusing part is that *reads* keep working: boot chatter still appears on
the monitor and the port looks perfectly healthy, so it reads like a bad cable.
It isn't. USB carries both directions on one differential pair, so a cable fault
cannot be direction-asymmetric — a failure that is one-directional is this
problem, every time.

Re-plug the module afterwards if you want to use the phone app.

## Build and flash

Verified with arduino-cli 1.5.1 and core `arduino:avr` 1.8.8.

### One-time setup

```bash
arduino-cli core install arduino:avr
arduino-cli lib install FastLED@3.2.10 Servo
```

The FastLED version pin is not optional. Modern FastLED (3.10.x) fails to link
with `multiple definition of __vector_11`, because it claims the TIMER1
interrupt vector that `Servo` also needs. Plain `arduino-cli lib install
FastLED` installs that broken version — pin it to 3.2.10, which is the copy in
`addLibrary/FastLED-master.zip`.

`Servo` is required and is *not* bundled with the AVR core. `Wire` is pulled in
transitively by the vendored MPU6050/I2Cdev drivers, but ships with the core, so
it needs no install. Those three are the only libraries resolved from outside
the sketch folder — IRremote, MPU6050, I2Cdev and ArduinoJson v6.11.1 are
vendored in the repo root.

### Compile and upload

The Arduino toolchain requires the sketch folder to be named after its `.ino`
file. This repo's folder isn't, so `arduino-cli compile .` fails with `main file
missing from sketch`. Pointing arduino-cli at the `.ino` directly does **not**
help — it resolves back to the parent folder and fails identically. Build from a
copy in a correctly named directory:

```bash
BUILD=/tmp/SmartRobotCarV4.0_V1_20230201     # folder name must match the .ino
mkdir -p "$BUILD" && cp *.ino *.h *.cpp "$BUILD"/

arduino-cli compile --fqbn arduino:avr:uno "$BUILD"
arduino-cli upload  --fqbn arduino:avr:uno -p PORT "$BUILD"
```

Find `PORT` with `arduino-cli board list`. On macOS it is typically
`/dev/cu.usbserial-XXXX` or `/dev/cu.usbmodemXXXX`; on Linux `/dev/ttyUSB0`; on
Windows a `COMn`.

A clean build reports:

```
Sketch uses 30020 bytes (93%) of program storage space. Maximum is 32256 bytes.
Global variables use 1166 bytes (56%) of dynamic memory ...
```

### Verify the flash

Serial is **9600 baud** (set in `ApplicationFunctionSet_Init`).

```bash
arduino-cli monitor -p PORT -c baudrate=9600
```

`tools/serial_check.py` automates the check — it sends the `N:21` / `N:22`
sensor queries and validates that the replies are well-formed and physically
plausible. Stdlib only, no pyserial or venv needed:

```bash
python3 tools/serial_check.py                  # one pass, prints a table
python3 tools/serial_check.py --watch          # poll continuously
python3 tools/test_serial_check.py             # self-test, no car needed
```

`--watch` is the useful one for confirming the readings track physical reality:
wave a hand at the ultrasonic head, lift the car off the ground, and watch the
numbers move.

### Flash is nearly full

93% of program space is used, leaving roughly 2.3 KB. Any non-trivial feature
can overflow the Uno, so **read the size line on every compile**. Two things to
know before you add code:

- The compile-time debug gates are where space comes back. `_is_print 0` in
  `ApplicationFunctionSet_xxx0.cpp` is worth about 600 bytes.
- **Don't use `sprintf`/`printf`.** One call links AVR's `vfprintf`, costing
  ~950 bytes (≈4% of total flash) for float and width-specifier support this
  firmware never uses. Use `String(value)` in a concatenation, or
  `itoa(value, buf, 10)` if you need the last 186 bytes.

There is also no C++ standard library on this target: the AVR toolchain ships no
libstdc++, so `<string>`, `<vector>`, `<format>` and `<cstdio>` are all absent.
Arduino's `String` and the vendored header-only libraries are what you have.

`SmartRobotCarV4.0_V1_20230201.hex` in the repo root is a prebuilt artifact, not
a build input.

## Driving the car

### IR remote

| Key | Effect |
| --- | --- |
| ▲ ▼ ◀ ▶ | Momentary drive (forward / back / left / right); stops ~300 ms after release |
| OK | Standby |
| 1 | Line-tracking mode |
| 2 | Obstacle-avoidance mode |
| 3 | Follow mode |
| 4 / 5 / 6 | `TrackingDetection_S` +10 / reset to 250 / −10 — **line-tracking mode only** |
| 7 / 8 / 9 | `Rocker_CarSpeed` +5 / reset to 250 / −5 |

The button on INT0 cycles the same modes: successive presses step through
line-tracking → obstacle-avoidance → follow → standby, then wrap. It debounces
at 500 ms, so press deliberately.

### Line tracking: pick your tape for infrared, not by eye

The ITR20001 channels measure near-IR (~940 nm) reflectance, and the value
*rises* as reflected IR falls. Measured on a working car: **~40 sitting on a
white table, ~1000 held in the air.**

So the detection window is looking for the *dark line*, not the bright floor.
`TrackingDetection_S = 250` is the darkness threshold and
`TrackingDetection_E = 850` rejects "no surface at all" (a table edge, or a
lifted car).

**Matte black tape works. Blue painter's tape does not** — verified on this car.
Blue pigments reflect near-IR nearly as well as a white tabletop does, so there
is no contrast for the sensor even though it looks obvious to you. Carbon black
absorbs across the near-IR, which is why black works. Any line you choose has to
read ≥ 250 against a table reading of ~40.

If tracking misbehaves, tune `TrackingDetection_S` live with remote keys 4/5/6
while in line-tracking mode. Note the bottom of the range is degenerate: at
`S = 30` a ~40 floor reading falls *inside* the window, so every channel reports
"on the line" and the car drives straight, blind. Useful values start around 50.

To watch the tuning take effect, set `_Test_print 1` in
`ApplicationFunctionSet_xxx0.cpp` and rebuild — it prints all three channels plus
the live threshold. It costs 458 bytes of flash, which fits, but not alongside
much else.

### Phone app

Commands arrive as JSON frames over the ESP32's serial link:
`{"H":"<serial no>","N":<cmd>,"D1":..,"D2":..,"T":..}`. The `switch` on
`control_mode_N` in `ApplicationFunctionSet_SerialPortDataAnalysis` is the
authoritative command list. ELEGOO's "Communication protocol for Smart Robot
Car.pdf" documents it and is not in this repo.

## Repo layout

```
SmartRobotCarV4.0_V1_20230201.ino   sketch entry point
DeviceDriverSet_xxx0.{h,cpp}        one class per peripheral; all pin #defines
ApplicationFunctionSet_xxx0.{h,cpp} behavior, mode state machine, serial protocol
MPU6050_getdata.{h,cpp}             yaw-only wrapper over the MPU6050 driver
ArduinoJson-v6.11.1.h               vendored, do not hand-edit
MPU6050.*  I2Cdev.*  IRremote*      vendored, do not hand-edit
addLibrary/                         zipped libraries for Arduino IDE install
tools/                              serial verification scripts
README.txt                          ELEGOO's original changelog
CLAUDE.md                           architecture and gotcha notes
```

There is no build script, test suite, or linter for the firmware itself.

## Changes from the ELEGOO original

- Replaced `sprintf` in the serial replies with `String` concatenation,
  reclaiming ~950 bytes of flash ([#2](../../pull/2)).
- Fixed a `uint8_t` overflow in `TrackingDetection_S`: the remote's "increase
  threshold" key wrapped 250 to 4, which put the bare floor inside the detection
  window and made the car drive straight through the line — the exact failure
  the key exists to fix. Also repaired the `_Test_print` debug gate, which no
  longer compiled ([#3](../../pull/3)).
- Documented the ITR20001 polarity, the inverted `Car_LeaveTheGround` flag, the
  camera-module upload conflict, and the flash budget in `CLAUDE.md`.

## Provenance

The firmware and the vendored libraries are ELEGOO's, redistributed here with
fixes; ELEGOO publishes them without a license file, so this repo has none
either and the terms are whatever ELEGOO's own distribution implies. Treat it as
a hardware-support dump rather than something you can relicense. The vendored
third-party libraries (ArduinoJson, MPU6050, I2Cdev, IRremote, FastLED) carry
their own upstream licenses.
