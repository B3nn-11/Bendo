# Bendo

A multi-purpose, all-in-one desktop toolbox for Windows. Cut your internet
with a hotkey when you need to focus, schedule a shutdown/restart/hibernate,
control app and master volume, jot notes, and more - all from one window
that tucks into the system tray.

## Features

- **Internet Blocker** - global hotkey cuts internet access for a set
  number of seconds via Windows Firewall rules (loopback stays open, so
  local dev servers keep working); includes network info, ping, and a
  speed test
- **Shutdown Scheduler** - delayed shut down, restart, or hibernate
- **Volume Mixer** - master volume/mute plus per-application volume, with
  its own global mute hotkey
- **Notes** - autosaving notepad, exportable to `.txt`
- **Power** - immediate lock / sign out / sleep / hibernate / restart
- **Auto Clicker**, **Timer**, **Clipboard History** (in-memory only),
  **System Stats**, **Bookshelf**, **Drawing Notepad**, **Photo Tool**,
  **Reminders & Alarms**, **Media Controller**, **File Converter**, and a
  **Calendar** - optional tabs you can turn on from Settings
- **Settings** - drag-to-reorder tabs, show/hide tabs, light/dark/custom
  themes with an optional background image, Start-with-Windows, and
  Backup & Restore (export/import all settings as JSON)
- Minimizes to the **system tray** instead of closing, with quick actions
  and shutdown-countdown notifications

Bendo needs administrator rights (to modify firewall rules and schedule a
shutdown) and relaunches itself elevated automatically.

## Install

Download the latest installer from the
[Releases](https://github.com/B3nn-11/Bendo/releases) page and run it. It
adds Start Menu/desktop shortcuts and a proper uninstaller, and includes a
**"which tools would you like?"** step so Bendo starts with exactly the
tools you want. You can add or remove any tool later with one click in
Bendo's Settings tab - nothing to reinstall.

### Bendo Lite

Prefer something smaller? `Bendo-Lite.exe` (also on the Releases page) is
a portable, no-install build with five everyday tools - Shutdown
Scheduler, Volume Mixer, Notes, Power, and Bookshelf. Trade-offs versus
the full edition: no Internet Blocker, no system tray (closing the window
exits), and no speed test, since the libraries behind those are compiled
out. Download it and run it - nothing to install or uninstall.

## Run from source

```
pip install keyboard pycaw comtypes pystray Pillow psutil speedtest-cli winrt-runtime "winrt-Windows.Media.Control" "winrt-Windows.Foundation" "winrt-Windows.Foundation.Collections"
python bendo.py
```

All third-party packages are optional - Bendo runs without them, just with
the tab(s) that need them disabled.

## Build

```
python -m PyInstaller Bendo.spec        # full edition -> dist\Bendo.exe
python -m PyInstaller Bendo-Lite.spec   # Lite edition -> dist\Bendo-Lite.exe
```

Both are self-contained single files (the specs carry the icon, UAC-admin
manifest, and version resource). The Lite spec flips the app into
core-tools-only mode via a runtime hook and compiles out the optional
tools' libraries.

### Build the installer

Requires [Inno Setup](https://jrsoftware.org/isinfo.php):

```
ISCC.exe Bendo_installer.iss
```

Produces `installer\Bendo-Setup-<version>.exe`, ready to attach to a
GitHub Release.
