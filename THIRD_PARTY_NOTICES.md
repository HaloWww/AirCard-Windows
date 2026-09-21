# Third-party notices

AirCard for Windows depends on open-source packages installed from PyPI. The
most significant runtime dependencies are:

- `pymobiledevice3` — GPL-3.0
- `Flet` and `flet-desktop` — Apache-2.0
- `Pillow` — HPND
- `Rich` — MIT

Their transitive dependencies retain their respective licenses. Package and
license versions can change when dependency constraints are updated; review the
resolved environment before redistributing a binary.

Apple's `AirTrafficHost.dll`, `MobileDevice.dll`, and `CoreFoundation.dll` are
not part of this repository or its build artifacts. They are loaded from the
user's official Apple Mobile Device Support installation.
