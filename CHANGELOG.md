# Changelog

All notable changes to Column Correction. Versions follow the release tags on GitHub.

## 2.1 (2026-11)

### App
- New **Calibration tools** screen (button at the bottom of the app):
  - test patterns **Grey**, **Green** and **Blue**: a large flat background fixed in the room about 2 m in front of you;
  - **Ghosting** test: a high-contrast checkerboard that moves with the head for 5 minutes, then a grey background with a check question;
  - **Display warm-up delay** (`LAG_MIN`) with −/+ buttons (5–60 minutes), no need to edit the settings file anymore.
- **Undo** after saving a cold or hot point (available for 20 seconds): restores the previous point and trims.
- The confirm button now shows the temperature that will be saved ("Press again to save at 44 °C").
- **German** user interface. The app keeps its English name "Column Correction" in German.
- Language buttons are now in the order EN, DE, RU.
- The app shows when the service has paused because of an unknown display driver.

### Service
- **Driver compatibility check** before the first write: the factory VCOM values reported by the driver (`panel_info`) must match the displays' own memory (`panel_mfg_info`), and all expected debugfs files must exist. If not, the service writes nothing and reports `error=unknown_driver`.
- The state file `/run/vcom-fix.state` now also reports `compat`, `kernel` and `version`.

### Documentation
- FAQ in English, Russian and German.
- This changelog.

### Upgrading from 2.0
Install as usual (see *Update* in the README). Settings are kept; nothing needs to be recalibrated.

## 2.0 (2026-11)

First public release.

- `vcom-fix` service: shifts each display's VCOM relative to its own factory value, following a lagged display temperature estimate derived from the camera sensors (cold point, hot point, linear in between).
- Factory values are read automatically for each headset, for the current refresh rate; the correction is re-applied after a refresh-rate change or wake-up.
- Safety limits: −10 … +45 steps from the factory value; nothing is written if the factory values cannot be read.
- SteamVR dashboard app "Column Correction" ("Коррекция столбцов"): on/off, per-display trims, saving the cold and hot calibration points, English and Russian.
- Installer and uninstaller; settings are kept on update.
