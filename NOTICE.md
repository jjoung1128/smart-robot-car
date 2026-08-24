# Notices and provenance

This repository has no repo-wide `LICENSE` file, and that is deliberate rather
than an oversight. Most of the code here is ELEGOO's, and a fork can't grant
rights over code it doesn't own — adding an MIT `LICENSE` at the root would
advertise a permission that isn't ours to give. What follows is the accurate
picture instead, component by component.

Not legal advice. If the answer matters to you commercially, ask a lawyer.

## Components

| Component | Files | Copyright | License |
| --- | --- | --- | --- |
| Smart Robot Car V4.0 firmware | `SmartRobotCarV4.0_V1_20230201.ino`, `ApplicationFunctionSet_xxx0.*`, `DeviceDriverSet_xxx0.*`, `MPU6050_getdata.*`, `README.txt`, `*.hex` | ELEGOO | None stated — see [ELEGOO's firmware](#elegoos-firmware) |
| ArduinoJson 6.11.1 | `ArduinoJson-v6.11.1.h` | Benoît Blanchon, 2014–2019 | MIT (notice retained inline in the header) |
| I2Cdevlib (I2Cdev + MPU6050) | `I2Cdev.*`, `MPU6050.*` | Jeff Rowberg, 2013 | MIT — [`licenses/I2Cdevlib-MIT.txt`](licenses/I2Cdevlib-MIT.txt) |
| IRremote 0.1 | `IRremote.*`, `IRremoteInt.h`, `addLibrary/IRremote.zip` | Ken Shirriff, 2009, and contributors | LGPL 2.1 — [`licenses/IRremote-LGPL-2.1.txt`](licenses/IRremote-LGPL-2.1.txt) |
| FastLED (3.2.10) | `addLibrary/FastLED-master.zip` | FastLED, 2013 | MIT (`LICENSE` inside the archive) |
| NewPing, pitches | `addLibrary/NewPing.zip`, `addLibrary/pitches.zip` | respective authors | No license file in either archive; NewPing is unused by this firmware |
| Fixes, tooling and docs added here | `tools/*`, `README.md`, `CLAUDE.md`, `NOTICE.md`, and the diffs against ELEGOO's release | this repository's contributors | MIT — [`licenses/Contributions-MIT.txt`](licenses/Contributions-MIT.txt) |

`Servo` and `Wire` are resolved from the installed Arduino AVR core and are not
redistributed here.

## Restored notices

ELEGOO's distribution stripped the license headers from several third-party
files. Retaining those notices is an obligation that lands on anyone
redistributing the code, so they are restored under `licenses/` rather than by
editing the vendored sources (which this repo otherwise leaves untouched):

- **I2Cdevlib** — `I2Cdev.cpp` still carries Jeff Rowberg's MIT notice inline.
  It is absent from `I2Cdev.h`, `MPU6050.h` and `MPU6050.cpp`. MIT requires the
  notice to travel with all copies.
- **IRremote** — the root copies retain only the line `Copyright 2009 Ken
  Shirriff`, with no license text. The library is LGPL 2.1, and the full text
  was in this repo all along inside `addLibrary/IRremote.zip`; it is now also at
  `licenses/IRremote-LGPL-2.1.txt`, which is where LGPL 2.1 expects it.

## ELEGOO's firmware

ELEGOO publishes this firmware, along with the manual, phone app and datasheets,
from its
[Smart Robot Car Kit V4.0 tutorial page](https://us.elegoo.com/blogs/arduino-projects/elegoo-smart-robot-car-kit-v4-0-tutorial),
as customer support material for the kit. It ships with no license file and no
license notice in any source file.

Public availability is not the same thing as a license. Copyright attaches
automatically, so absent an explicit grant the default is that ELEGOO reserves
its rights. Distributing the files to kit owners plainly implies permission to
use and modify them with the product; it says nothing explicit about
redistribution, which is what a fork like this one does. That leaves the status
of the ELEGOO-authored files genuinely unsettled, and no file added to this
repository can settle it.

In practice this is how the whole ELEGOO ecosystem on GitHub operates — there
are many such forks, and ELEGOO has shown no sign of objecting. The realistic
worst case is a takedown request, which we would honour. Two things follow for
anyone reading this:

- **Don't treat the ELEGOO-authored files as open source.** They aren't marked
  as such, and nothing here makes them so. Reusing them in a product is a
  question for ELEGOO, not for this repo.
- **The third-party libraries are separately licensed** and those licenses do
  grant redistribution rights, on the terms in `licenses/`. That part is clear
  even where the ELEGOO layer isn't.

If you are ELEGOO and would like this repository changed or removed, open an
issue and we will comply.
