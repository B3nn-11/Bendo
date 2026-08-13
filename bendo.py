"""
Bendo - a focus tool for Windows.

Press a global hotkey to cut internet access for a set number of seconds.
Uses Windows Firewall block rules: fast, clean, locale-independent, and it
leaves loopback (127.0.0.1) alone so local dev servers keep working.

Also supports scheduling a delayed shutdown, restart, or hibernate (Shut
down/Restart use Windows' own delayed timer; Hibernate is timed in-app since
shutdown.exe has no delay flag for it); a volume mixer tab for adjusting the
master volume and per-application volume/mute (via pycaw), with its own
global mute hotkey; a notes tab that autosaves locally and can be exported
to .txt; a Power tab for immediate lock/sign out/sleep/hibernate/restart; an
Auto Clicker tab (background-thread mouse clicking via ctypes, with a
current-cursor or fixed-position mode and its own toggle hotkey); a plain
countdown Timer tab; a Clipboard History tab (in-memory only, never written
to disk); a System Stats tab (CPU/RAM/disk/network via psutil); Settings
with tab reordering (drag while on the Settings tab)/visibility, a Start
with Windows toggle, and Backup & Restore (export/import all settings as
JSON); and a system tray icon (via pystray) that the window can minimize to
instead of closing (configurable in Settings), with quick actions and a
shutdown-countdown notification.

Requires administrator privileges (needed to modify firewall rules and to
schedule a shutdown) - the app relaunches itself elevated automatically.

Run:   pip install keyboard pycaw comtypes pystray Pillow psutil speedtest-cli winrt-runtime "winrt-Windows.Media.Control" "winrt-Windows.Foundation" "winrt-Windows.Foundation.Collections"  &&  python bendo.py
Build: python -m PyInstaller Bendo.spec
       (the spec carries the icon, UAC-admin manifest, and version resource;
       building from the .py with CLI flags would regenerate it without them)
Installer: ISCC.exe Bendo_installer.iss
       (Inno Setup; wraps dist/Bendo.exe into installer/Bendo-Setup-<ver>.exe
       with Start Menu/desktop shortcuts, an uninstaller, and uninstall-time
       cleanup of the startup task and firewall rule)
"""

import base64
import copy
import ctypes
import ctypes.wintypes
import io
import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import asyncio
import calendar as calendar_module
import datetime
import tkinter as tk
import winreg
import winsound
from tkinter import colorchooser, filedialog, ttk

# Built with --windowed (no console), so sys.stdout/stderr are None. Some
# libraries (speedtest-cli) call .fileno() on them at import time for
# Windows binary-mode setup, which crashes without this.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

try:
    import keyboard
except ImportError:
    keyboard = None

try:
    from pycaw.pycaw import AudioUtilities
except ImportError:
    AudioUtilities = None

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageTk
except ImportError:
    Image = None

try:
    import pystray
except ImportError:
    pystray = None

try:
    import psutil
except ImportError:
    psutil = None

try:
    import speedtest
except ImportError:
    speedtest = None

# Media controls: prefer the modular winrt-* packages over the deprecated
# monolithic winsdk - same pywinrt API, but winsdk ships a single ~38 MB
# _winrt.pyd while the modular projection is a few hundred KB. The winsdk
# fallback keeps old dev environments working (the build excludes it).
try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as MediaSessionManager,
    )
    HAS_MEDIA_CONTROL = True
except ImportError:
    try:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaSessionManager,
        )
        HAS_MEDIA_CONTROL = True
    except ImportError:
        HAS_MEDIA_CONTROL = False

# Bendo.png, embedded so the exe is fully self-contained (no external
# icon file to ship or lose track of). Used for the window/taskbar icon
# and, when pystray is available, the tray icon.
BENDO_ICON_PNG_B64 = (
    "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"
    "AAAAAEDcSPo/m7tCd8M+IMkAAAAASUVORK5CYII="
)


# Multi-resolution .ico version of the same artwork. Windows derives the
# taskbar (including pinned-tile) icon from a real .ico's HICON rather
# than the live window's WM_SETICON, so we write this to a small file at
# startup and point iconbitmap at it - the PNG via iconphoto alone left
# the pinned taskbar icon blank/generic.
BENDO_ICON_ICO_B64 = (
    "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"
    "YII="
)


APP_NAME = "Bendo"
RULE_NAME = "Bendo_InternetBlock"

# Set by the Lite build's PyInstaller runtime hook (see Bendo-Lite.spec).
# Lite ships only the five core tools and compiles out the heavy optional
# libraries (Pillow/pystray/winrt/speedtest/psutil) for a smaller exe -
# which also means no system tray and no speed test in that edition.
LITE_BUILD = os.environ.get("BENDO_LITE") == "1"
APPDATA_DIR = os.environ.get("APPDATA", os.path.expanduser("~"))
CONFIG_PATH = os.path.join(APPDATA_DIR, "bendo_config.json")
NOTES_AUTOSAVE_PATH = os.path.join(APPDATA_DIR, "bendo_notes_autosave.txt")
ICON_ICO_PATH = os.path.join(APPDATA_DIR, "bendo_icon.ico")
DEFAULT_CONFIG = {
    "hotkey": "ctrl+alt+k",
    "duration": 60,
    "on_top": False,
    "armed": True,
    "shutdown_days": 0,
    "shutdown_hours": 1,
    "shutdown_minutes": 0,
    "shutdown_seconds": 0,
    "shutdown_force": True,
    "shutdown_action": "shutdown",  # "shutdown", "restart", or "hibernate"
    "mute_hotkey": "ctrl+alt+m",
    "mute_hotkey_armed": True,
    "start_with_windows": False,
    "power_force": True,
    "close_behavior": "tray",  # "tray" or "exit"
    "clicker_interval_ms": 100,
    "clicker_button": "left",
    "clicker_limit": 0,  # 0 = unlimited
    "clicker_hotkey": "f6",
    "clicker_hotkey_armed": True,
    "timer_days": 0,
    "timer_hours": 0,
    "timer_minutes": 5,
    "timer_seconds": 0,
    "theme": "light",  # "light", "dark", or "custom"
    "custom_bg_color": "#202020",
    "custom_fg_color": "#e0e0e0",
    "background_image_path": None,
    "bookshelf_items": [],
    "reminders": [],
    "calendar_events": {},
    "onboarding_shown": False,
    "tab_rows": "Auto",  # "Auto", "1", "2", "3", or "4"
    "tab_order": ["internet", "shutdown", "mixer", "notes", "power",
                  "clicker", "timer", "clipboard", "stats", "bookshelf",
                  "drawpad", "photo", "reminders", "media", "converter",
                  "calendar"],
    # Only the core tabs show by default; the rest can be turned on during
    # onboarding (or later from Settings) so a fresh install isn't a wall
    # of 16 tabs.
    "tab_visible": {
        "internet": True, "shutdown": True, "mixer": True, "notes": True,
        "power": True, "clicker": False, "timer": False, "clipboard": False,
        "stats": False, "bookshelf": False, "drawpad": False, "photo": False,
        "reminders": False, "media": False, "converter": False, "calendar": False,
    },
}

CORE_TAB_IDS = {"internet", "shutdown", "mixer", "notes", "power"}

# The Lite edition's tab set: it trades the Internet Blocker for the
# Bookshelf (no firewall tooling in Lite, and Bookshelf has no heavy deps).
LITE_TAB_IDS = {"shutdown", "mixer", "notes", "power", "bookshelf"}

# Hide the console windows that netsh/shutdown would otherwise flash on screen.
NO_WINDOW = 0x08000000


# ---------- admin elevation ----------
def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """Relaunch elevated; returns True if the elevated copy started
    (ShellExecute returns a value > 32 on success, so a declined UAC
    prompt shows up here as False)."""
    if getattr(sys, "frozen", False):  # packaged exe
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, None, None, 1)
    else:  # running as a .py script
        params = " ".join(f'"{a}"' for a in sys.argv)
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1)
    return ret > 32


# ---------- firewall control ----------
def run_netsh(args):
    return subprocess.run(
        ["netsh"] + args, capture_output=True, text=True, creationflags=NO_WINDOW
    )


def block_internet():
    unblock_internet()  # clear any stale rule first
    for direction in ("out", "in"):
        run_netsh([
            "advfirewall", "firewall", "add", "rule",
            f"name={RULE_NAME}", f"dir={direction}", "action=block",
            "enable=yes", "profile=any",
        ])


def unblock_internet():
    run_netsh(["advfirewall", "firewall", "delete", "rule", f"name={RULE_NAME}"])


# ---------- network info ----------
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # doesn't actually send anything (UDP)
        return s.getsockname()[0]
    except OSError:
        return "unknown"
    finally:
        s.close()


def ping_host(host, timeout_ms=1000):
    return subprocess.run(
        ["ping", "-n", "1", "-w", str(timeout_ms), host],
        capture_output=True, text=True, creationflags=NO_WINDOW,
    )


# ---------- shutdown control ----------
def run_shutdown(args):
    return subprocess.run(
        ["shutdown"] + args, capture_output=True, text=True, creationflags=NO_WINDOW
    )


SHUTDOWN_ACTION_FLAGS = {"shutdown": "/s", "restart": "/r"}


def schedule_power_action(action, total_seconds, force):
    """Schedule a shutdown or restart via Windows' own delayed timer.

    Hibernate has no equivalent flag in shutdown.exe (only /f is documented
    for /h, no /t), so it's handled separately with an in-app countdown.
    """
    args = [SHUTDOWN_ACTION_FLAGS[action], "/t", str(total_seconds)]
    if force:
        args.append("/f")
    return run_shutdown(args)


def cancel_shutdown():
    return run_shutdown(["/a"])


def restart_now(force):
    args = ["/r", "/t", "0"]
    if force:
        args.append("/f")
    return run_shutdown(args)


# ---------- power actions (immediate, no countdown) ----------
def lock_workstation():
    return bool(ctypes.windll.user32.LockWorkStation())


def sleep_now():
    return bool(ctypes.windll.powrprof.SetSuspendState(False, True, False))


def hibernate_now():
    return bool(ctypes.windll.powrprof.SetSuspendState(True, True, False))


def sign_out():
    EWX_LOGOFF = 0
    return bool(ctypes.windll.user32.ExitWindowsEx(EWX_LOGOFF, 0))


# ---------- auto clicker ----------
MOUSE_CLICK_FLAGS = {
    "left": (0x0002, 0x0004),     # MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    "right": (0x0008, 0x0010),    # MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    "middle": (0x0020, 0x0040),   # MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
}


def click_mouse(button):
    down, up = MOUSE_CLICK_FLAGS[button]
    ctypes.windll.user32.mouse_event(down, 0, 0, 0, 0)
    ctypes.windll.user32.mouse_event(up, 0, 0, 0, 0)


def get_cursor_pos():
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def set_cursor_pos(x, y):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))


# ---------- start with Windows ----------
# Startup uses a Task Scheduler task rather than the HKCU Run key: Bendo's
# manifest requires elevation, and Windows won't silently auto-elevate a
# Run-key entry at logon (it gets blocked or prompts, depending on the
# version). A task with "highest privileges" starts elevated with no prompt.
STARTUP_TASK_NAME = "Bendo Startup"
STARTUP_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def get_startup_command():
    if getattr(sys, "frozen", False):  # packaged exe
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'


def _remove_legacy_startup_run_key():
    """Older Bendo versions used the Run key; clear any leftover entry."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY_PATH, 0,
                             winreg.KEY_SET_VALUE)
    except OSError:
        return
    try:
        winreg.DeleteValue(key, APP_NAME)
    except OSError:
        pass
    finally:
        winreg.CloseKey(key)


def set_startup_enabled(enabled):
    _remove_legacy_startup_run_key()
    if enabled:
        result = subprocess.run(
            ["schtasks", "/Create", "/F", "/TN", STARTUP_TASK_NAME,
             "/SC", "ONLOGON", "/RL", "HIGHEST", "/TR", get_startup_command()],
            capture_output=True, text=True, creationflags=NO_WINDOW)
        return result.returncode == 0
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", STARTUP_TASK_NAME],
                   capture_output=True, text=True, creationflags=NO_WINDOW)
    return True  # deleting a task that doesn't exist is fine


# ---------- volume mixer ----------
def get_master_endpoint():
    return AudioUtilities.GetSpeakers().EndpointVolume


def get_audio_sessions():
    """Return {pid: {"name": str, "sessions": [ISimpleAudioVolume, ...]}}.

    Grouped by pid because a single app (e.g. a browser) can own several
    audio sessions at once - they should all move together, like the
    built-in Windows volume mixer does.
    """
    grouped = {}
    for session in AudioUtilities.GetAllSessions():
        if session.Process:
            pid = session.Process.pid
            name = session.Process.name()
        else:
            pid, name = 0, "System Sounds"
        grouped.setdefault(pid, {"name": name, "sessions": []})
        grouped[pid]["sessions"].append(session.SimpleAudioVolume)
    return grouped


# ---------- config ----------
def sanitize_config(cfg):
    """Coerce a loaded or imported config back to sane shapes.

    Config files can be hand-edited (or come from Import settings), so
    anything whose type or allowed values don't match the defaults falls
    back to the default instead of crashing the UI later.
    """
    for key, default in DEFAULT_CONFIG.items():
        value = cfg.get(key)
        if default is None:
            continue
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, int):
            ok = isinstance(value, int) and not isinstance(value, bool)
        else:
            ok = isinstance(value, type(default))
        if not ok:
            cfg[key] = copy.deepcopy(default)

    if cfg["background_image_path"] is not None and not isinstance(
            cfg["background_image_path"], str):
        cfg["background_image_path"] = None
    if cfg["shutdown_action"] not in ("shutdown", "restart", "hibernate"):
        cfg["shutdown_action"] = "shutdown"
    if cfg["clicker_button"] not in ("left", "right", "middle"):
        cfg["clicker_button"] = "left"
    if cfg["theme"] not in ("light", "dark", "custom"):
        cfg["theme"] = "light"
    if cfg["close_behavior"] not in ("tray", "exit"):
        cfg["close_behavior"] = "tray"
    for key in ("custom_bg_color", "custom_fg_color"):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", cfg[key] or ""):
            cfg[key] = DEFAULT_CONFIG[key]

    cfg["bookshelf_items"] = [p for p in cfg["bookshelf_items"]
                              if isinstance(p, str)]
    reminders = []
    for r in cfg["reminders"]:
        if not isinstance(r, dict):
            continue
        try:
            datetime.datetime.fromisoformat(str(r.get("when")))
        except ValueError:
            continue
        sound = r.get("sound_path")
        reminders.append({
            "when": str(r["when"]),
            "note": str(r.get("note") or "Reminder"),
            "repeat_daily": bool(r.get("repeat_daily")),
            "sound_path": sound if isinstance(sound, str) else None,
            "enabled": bool(r.get("enabled", True)),
        })
    cfg["reminders"] = reminders
    events = {}
    for day, items in cfg["calendar_events"].items():
        if isinstance(items, list):
            texts = [str(item) for item in items]
            if texts:
                events[str(day)] = texts
    cfg["calendar_events"] = events
    cfg["tab_order"] = [t for t in cfg["tab_order"] if isinstance(t, str)]
    cfg["tab_visible"] = {str(t): bool(v) for t, v in cfg["tab_visible"].items()}
    return cfg


def _read_install_preset():
    """Tool choices from the installer, or None.

    The setup wizard has a "which tools would you like?" page and records
    the answer as a preset.ini next to the exe. It only seeds a brand-new
    config (each user's first run); after that the user's own Settings
    choices are the truth and the preset is ignored.
    """
    base = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))
    path = os.path.join(base, "preset.ini")
    if not os.path.exists(path):
        return None
    choices = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                key, sep, value = line.strip().partition("=")
                key = key.strip()
                if sep and key in DEFAULT_CONFIG["tab_visible"]:
                    choices[key] = value.strip() == "1"
    except OSError:
        return None
    return choices or None


def load_config():
    # deepcopy so appends/edits to nested lists and dicts never mutate
    # DEFAULT_CONFIG itself (a shallow merge shares those objects, which
    # then leaks session data into Import settings / Reset to default)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    fresh = True
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
            fresh = False
    except Exception:
        pass
    if fresh:
        preset = _read_install_preset()
        if preset:
            cfg["tab_visible"].update(
                {t: v for t, v in preset.items() if t not in CORE_TAB_IDS})
            cfg["onboarding_shown"] = True  # tools were already chosen in setup
        if LITE_BUILD:
            # all of Lite's tabs start visible (bookshelf is hidden by
            # default in the full edition, but it's core in Lite)
            cfg["tab_visible"].update({t: True for t in LITE_TAB_IDS})
    return sanitize_config(cfg)


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print("Could not save config:", e)


# ---------- tray icon ----------
def build_tray_image():
    raw = base64.b64decode(BENDO_ICON_PNG_B64)
    return Image.open(io.BytesIO(raw)).convert("RGBA")


def ensure_icon_file():
    """Write the embedded .ico to disk once, returning its path (or None)."""
    try:
        raw = base64.b64decode(BENDO_ICON_ICO_B64)
        existing = None
        if os.path.exists(ICON_ICO_PATH):
            with open(ICON_ICO_PATH, "rb") as f:
                existing = f.read()
        if existing != raw:
            with open(ICON_ICO_PATH, "wb") as f:
                f.write(raw)
        return ICON_ICO_PATH
    except OSError:
        return None


# ---------- themes ----------
LIGHT_PALETTE = {"bg": "#f0f0f0", "fg": "#000000", "field_bg": "#ffffff",
                 "button_bg": "#e1e1e1", "select_bg": "#0078d7", "select_fg": "#ffffff"}
DARK_PALETTE = {"bg": "#1e1e1e", "fg": "#e6e6e6", "field_bg": "#2b2b2b",
                "button_bg": "#3a3a3a", "select_bg": "#094771", "select_fg": "#ffffff"}

# Status-label text colors, chosen per theme so messages stay readable on a
# dark background. Labels set these imperatively as messages come and go,
# so _apply_theme also re-tints whatever is currently shown (see
# _retint_status_labels).
STATUS_FG_LIGHT = {"normal": "#333333", "muted": "#666666",
                   "faint": "#888888", "error": "#bb3300"}
STATUS_FG_DARK = {"normal": "#d4d4d4", "muted": "#a6a6a6",
                  "faint": "#8c8c8c", "error": "#ff8a70"}
_STATUS_FG_BY_COLOR = {color: kind
                       for palette in (STATUS_FG_LIGHT, STATUS_FG_DARK)
                       for kind, color in palette.items()}


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _adjust_hex(hex_color, amount):
    r, g, b = _hex_to_rgb(hex_color)
    r, g, b = (max(0, min(255, c + amount)) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def build_custom_palette(bg, fg):
    luminance = sum(_hex_to_rgb(bg)) / 3
    amount = 25 if luminance < 128 else -25
    field_bg = _adjust_hex(bg, amount)
    button_bg = _adjust_hex(bg, amount // 2)
    return {"bg": bg, "fg": fg, "field_bg": field_bg, "button_bg": button_bg,
            "select_bg": "#0a84ff", "select_fg": "#ffffff"}


def format_hms(total_seconds):
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or parts:
        parts.append(f"{hours}h")
    if minutes or parts:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


# ---------- app ----------
class BendoApp:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.events = queue.Queue()
        self.blocking = False
        self.remaining = 0
        self.hotkey_handle = None
        self.capturing = False
        self.mute_hotkey_handle = None
        self.mute_capturing = False
        self.shutdown_target = None  # epoch time the PC will shut down, or None
        self._shutdown_notified = False
        self._shutdown_os_managed = False
        self._scheduled_action = None  # snapshot of the action at schedule time
        # Hotkey captures are abandoned after a timeout so the Set button
        # can't stay stuck; each flow's generation counter lets a late
        # result from an abandoned reader thread be ignored.
        self._capture_gens = {"main": 0, "mute": 0, "clicker": 0}
        self._status_fg = STATUS_FG_LIGHT  # replaced by _apply_theme
        self._pillow_installing = False
        self.tray_icon = None
        self.clicker_running = False
        self.clicker_stop_event = threading.Event()
        self.clicker_hotkey_handle = None
        self.clicker_capturing = False
        self.clicker_fixed_pos = None
        self.timer_target = None
        self.clipboard_history = []
        self._last_clipboard_value = None
        self.converter_files = []
        self.converter_output_dir = None
        self._theme_palette = LIGHT_PALETTE
        self._themed_widgets = []
        self.bg_label = None
        self._bg_photo = None
        self._bg_image_pil = None
        if HAS_MEDIA_CONTROL:
            self._media_loop = asyncio.new_event_loop()
            threading.Thread(target=self._media_loop.run_forever, daemon=True).start()
        self._media_user_seeking = False

        root.title(APP_NAME + (" Lite" if LITE_BUILD else ""))
        root.resizable(False, False)
        icon_path = ensure_icon_file()
        try:
            if icon_path is None:
                raise tk.TclError("no icon file")
            root.iconbitmap(default=icon_path)
        except tk.TclError:
            try:
                self._icon_photo = tk.PhotoImage(data=BENDO_ICON_PNG_B64)
                root.iconphoto(True, self._icon_photo)
            except tk.TclError:
                pass
        self._build_ui()
        bg_path = self.cfg.get("background_image_path")
        if bg_path and Image is not None:
            try:
                self._bg_image_pil = Image.open(bg_path).convert("RGB")
            except Exception:
                self._bg_image_pil = None
        self._apply_theme()
        self._update_background_image()
        self._register_hotkey()
        self._register_mute_hotkey()
        self._register_clicker_hotkey()
        self._build_tray_icon()
        # Lite has no optional tools to offer, so onboarding is skipped
        if not self.cfg.get("onboarding_shown") and not LITE_BUILD:
            self.root.after(400, self._show_onboarding)
        self._maybe_auto_install_pillow()
        self.root.attributes("-topmost", self.cfg["on_top"])

        unblock_internet()  # recover if a previous run crashed while blocking

        self.root.after(100, self._poll_events)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        if keyboard is None and hasattr(self, "status"):
            self.status.config(
                text="Install the 'keyboard' package for global hotkeys "
                     "(pip install keyboard).",
                foreground=self._fg("error"),
            )

    TAB_LABELS = {
        "internet": "Internet & Network",
        "shutdown": "Shutdown Scheduler",
        "mixer": "Volume Mixer",
        "notes": "Notes",
        "power": "Power",
        "clicker": "Auto Clicker",
        "timer": "Timer",
        "clipboard": "Clipboard History",
        "stats": "System Stats",
        "bookshelf": "Bookshelf",
        "drawpad": "Drawing Notepad",
        "photo": "Photo Tool",
        "reminders": "Reminders & Alarms",
        "media": "Media Controller",
        "converter": "File Converter",
        "calendar": "Calendar",
    }

    THEME_LABELS = {"light": "Light", "dark": "Dark", "custom": "Custom"}
    THEME_LABELS_REV = {v: k for k, v in THEME_LABELS.items()}

    def _known_tab_ids(self):
        """All tab ids this edition offers (Lite = its own five-tool set)."""
        if LITE_BUILD:
            return [t for t in self.TAB_LABELS if t in LITE_TAB_IDS]
        return list(self.TAB_LABELS)

    TAB_ROW_OPTIONS = ["Auto", "1", "2", "3", "4"]

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # ttk.Notebook's native tab strip doesn't support forcing a chosen
        # number of rows (it either fits on one line or just overflows,
        # depending on theme) - so its own tab strip is hidden entirely and
        # a custom row/column of buttons above it drives tab selection
        # instead. That gives exact control over row count for the "Tab
        # rows" setting, and exact control over drag-to-reorder too.
        style = ttk.Style()
        style.theme_use("clam")  # also (re)applied in _apply_theme; set early so
                                  # the custom layout below is defined for real
        style.layout("Hidden.TNotebook.Tab", [])  # empty layout -> each tab renders as nothing

        self.tab_bar_frame = ttk.Frame(self.root)
        self.tab_bar_frame.grid(row=0, column=0, padx=12, pady=(12, 0), sticky="w")

        self.notebook = ttk.Notebook(self.root, takefocus=0, style="Hidden.TNotebook")
        self.notebook.grid(row=1, column=0, padx=12, pady=(6, 12))

        # Drop any stale ids from an old config and append any new ones,
        # so tab_order/tab_visible always cover exactly the known tabs.
        known = self._known_tab_ids()
        order = [t for t in self.cfg.get("tab_order", []) if t in known]
        order += [t for t in known if t not in order]
        self.cfg["tab_order"] = order
        visible = self.cfg.get("tab_visible", {})
        self.cfg["tab_visible"] = {t: visible.get(t, True) for t in known}

        self.tab_frames = {}
        for tab_id in self.cfg["tab_order"]:
            frame = ttk.Frame(self.notebook, padding=16)
            self.tab_frames[tab_id] = frame
            getattr(self, f"_build_{tab_id}_tab")(frame, pad)
            self.notebook.add(frame, text=self.TAB_LABELS[tab_id])

        self.settings_frame = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(self.settings_frame, text="Settings")
        self._build_settings_tab(self.settings_frame, pad)

        self._drag = None  # live drag state for tab reordering
        self.tab_buttons = {}

        self._update_status()
        self._refresh_controls()
        self.root.bind_all("<Button-1>", self._on_click_anywhere, add="+")
        self._rebuild_tab_bar()

    def _build_internet_tab(self, frm, pad):
        ttk.Label(frm, text="Hotkey").grid(row=0, column=0, sticky="w", **pad)
        self.hotkey_var = tk.StringVar(value=self.cfg["hotkey"])
        ttk.Entry(frm, textvariable=self.hotkey_var, width=22,
                  state="readonly", takefocus=0).grid(row=0, column=1, **pad)
        self.capture_btn = ttk.Button(frm, text="Set", width=8,
                                      command=self._capture_hotkey, takefocus=0)
        self.capture_btn.grid(row=0, column=2, **pad)

        ttk.Label(frm, text="Duration (seconds)").grid(row=1, column=0, sticky="w", **pad)
        self.duration_var = tk.StringVar(value=str(self.cfg["duration"]))
        ttk.Spinbox(frm, from_=1, to=86400, textvariable=self.duration_var,
                    width=20).grid(row=1, column=1, **pad)
        self.duration_var.trace_add("write", self._on_duration_change)

        self.on_top_var = tk.BooleanVar(value=self.cfg["on_top"])
        ttk.Checkbutton(frm, text="Pin on top", variable=self.on_top_var,
                        command=self._toggle_on_top, takefocus=0).grid(
            row=2, column=1, sticky="w", **pad)

        self.armed_var = tk.BooleanVar(value=self.cfg["armed"])
        ttk.Checkbutton(frm, text="Armed", variable=self.armed_var,
                        command=self._toggle_armed, takefocus=0).grid(
            row=3, column=1, sticky="w", **pad)

        self.status = ttk.Label(frm, text="", foreground=self._fg("normal"))
        self.status.grid(row=4, column=0, columnspan=3, sticky="w", **pad)

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=3, sticky="ew", **pad)
        self.trigger_btn = ttk.Button(btns, text="Trigger now",
                                      command=self._trigger, takefocus=0)
        self.trigger_btn.grid(row=0, column=0, padx=4)
        self.restore_btn = ttk.Button(btns, text="Restore internet",
                                      command=self._restore, state="disabled",
                                      takefocus=0)
        self.restore_btn.grid(row=0, column=1, padx=4)

        ttk.Separator(frm, orient="horizontal").grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=(4, 10))

        ttk.Label(frm, text="Network", font=("", 9, "bold")).grid(
            row=7, column=0, columnspan=3, sticky="w", padx=10)

        net_info_row = ttk.Frame(frm)
        net_info_row.grid(row=8, column=0, columnspan=3, sticky="w", **pad)
        self.network_info_label = ttk.Label(net_info_row, text="")
        self.network_info_label.grid(row=0, column=0, sticky="w")
        ttk.Button(net_info_row, text="Refresh", command=self._refresh_network_info,
                  takefocus=0).grid(row=0, column=1, padx=(12, 0))

        ping_row = ttk.Frame(frm)
        ping_row.grid(row=9, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(ping_row, text="Ping").grid(row=0, column=0, padx=(0, 8))
        self.ping_host_var = tk.StringVar(value="8.8.8.8")
        ttk.Entry(ping_row, textvariable=self.ping_host_var, width=18).grid(
            row=0, column=1, padx=(0, 8))
        ttk.Button(ping_row, text="Ping", command=self._ping_host,
                  takefocus=0).grid(row=0, column=2)

        self.ping_status = ttk.Label(frm, text="", foreground=self._fg("normal"))
        self.ping_status.grid(row=10, column=0, columnspan=3, sticky="w", **pad)

        if not LITE_BUILD:  # the speed test isn't part of the Lite edition
            speed_row = ttk.Frame(frm)
            speed_row.grid(row=11, column=0, columnspan=3, sticky="w", **pad)
            self.speedtest_btn = ttk.Button(speed_row, text="Run Speed Test",
                                            command=self._run_speed_test, takefocus=0)
            self.speedtest_btn.grid(row=0, column=0)
            if speedtest is None:
                self.speedtest_btn.config(state="disabled")

            self.speedtest_status = ttk.Label(
                frm, text="" if speedtest is not None else
                "Install 'speedtest-cli' for the speed test (pip install speedtest-cli).",
                foreground=self._fg("normal") if speedtest is not None
                           else self._fg("error"))
            self.speedtest_status.grid(row=12, column=0, columnspan=3, sticky="w", **pad)

        self._refresh_network_info()

    def _run_speed_test(self):
        if speedtest is None:
            return
        self.speedtest_btn.config(state="disabled")
        self.speedtest_status.config(text="Running speed test - this can take "
                                          "a while...", foreground=self._fg("normal"))
        threading.Thread(target=self._speed_test_worker, daemon=True).start()

    def _speed_test_worker(self):
        try:
            st = speedtest.Speedtest()
            st.get_best_server()
            ping = st.results.ping
            down = st.download()
            up = st.upload()
            self.events.put(("speedtest_result", (ping, down, up, None)))
        except Exception as e:
            self.events.put(("speedtest_result", (None, None, None, str(e))))

    def _handle_speedtest_result(self, ping, down, up, error):
        self.speedtest_btn.config(state="normal")
        if error:
            self.speedtest_status.config(text=f"Speed test failed: {error}",
                                         foreground=self._fg("error"))
            return
        self.speedtest_status.config(
            text=f"Ping: {ping:.0f} ms   Download: {down / 1_000_000:.1f} Mbps   "
                 f"Upload: {up / 1_000_000:.1f} Mbps",
            foreground=self._fg("normal"))

    def _refresh_network_info(self):
        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = "unknown"
        self.network_info_label.config(
            text=f"Hostname: {hostname}    Local IP: {get_local_ip()}")

    def _ping_host(self):
        host = self.ping_host_var.get().strip()
        if not host:
            return
        self.ping_status.config(text=f"Pinging {host}...", foreground=self._fg("normal"))
        threading.Thread(target=self._ping_host_worker, args=(host,), daemon=True).start()

    def _ping_host_worker(self, host):
        self.events.put(("ping_result", (host, ping_host(host))))

    def _handle_ping_result(self, host, result):
        out = result.stdout or ""
        # Exit code 0 alone isn't success: "Destination host unreachable" is
        # itself a reply, so ping still exits 0. A TTL= field only appears
        # on a real echo reply, and it's locale-invariant (unlike "time=",
        # which is translated on non-English Windows).
        if result.returncode != 0 or "ttl=" not in out.lower():
            self.ping_status.config(text=f"{host}: unreachable", foreground=self._fg("error"))
            return
        match = re.search(r"[=<](\d+)\s*ms", out)
        latency = f"{match.group(1)}ms" if match else "reachable"
        self.ping_status.config(text=f"{host}: {latency}", foreground=self._fg("normal"))

    SHUTDOWN_ACTION_LABELS = {"shutdown": "Shut down", "restart": "Restart",
                              "hibernate": "Hibernate"}
    SHUTDOWN_ACTION_LABELS_REV = {v: k for k, v in SHUTDOWN_ACTION_LABELS.items()}

    def _build_shutdown_tab(self, frm, pad):
        action_row = ttk.Frame(frm)
        action_row.grid(row=0, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(action_row, text="Action").grid(row=0, column=0, padx=(0, 8))
        self.shutdown_action_var = tk.StringVar(
            value=self.SHUTDOWN_ACTION_LABELS[self.cfg.get("shutdown_action", "shutdown")])
        action_combo = ttk.Combobox(
            action_row, textvariable=self.shutdown_action_var,
            values=list(self.SHUTDOWN_ACTION_LABELS.values()),
            state="readonly", width=12, takefocus=0)
        action_combo.grid(row=0, column=1)
        action_combo.bind("<<ComboboxSelected>>", self._on_shutdown_action_change)

        sd_frame = ttk.Frame(frm)
        sd_frame.grid(row=1, column=0, columnspan=3, sticky="w", **pad)

        self.days_var = tk.StringVar(value=f"{self.cfg['shutdown_days']:02d}")
        self.hours_var = tk.StringVar(value=f"{self.cfg['shutdown_hours']:02d}")
        self.minutes_var = tk.StringVar(value=f"{self.cfg['shutdown_minutes']:02d}")
        self.seconds_var = tk.StringVar(value=f"{self.cfg['shutdown_seconds']:02d}")

        self._add_time_box(sd_frame, "Days", self.days_var, 0, 365, 0)
        self._add_time_box(sd_frame, "Hours", self.hours_var, 0, 23, 1)
        self._add_time_box(sd_frame, "Minutes", self.minutes_var, 0, 59, 2)
        self._add_time_box(sd_frame, "Seconds", self.seconds_var, 0, 59, 3)

        for var in (self.days_var, self.hours_var, self.minutes_var, self.seconds_var):
            var.trace_add("write", self._on_shutdown_fields_change)

        self.shutdown_force_var = tk.BooleanVar(value=self.cfg["shutdown_force"])
        ttk.Checkbutton(frm, text="Force-close apps (/f) - Shut down / Restart only",
                        variable=self.shutdown_force_var,
                        command=self._toggle_shutdown_force, takefocus=0).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=10)

        self.shutdown_status = ttk.Label(frm, text="Nothing scheduled.",
                                         foreground=self._fg("normal"))
        self.shutdown_status.grid(row=3, column=0, columnspan=3, sticky="w", **pad)

        sd_btns = ttk.Frame(frm)
        sd_btns.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)
        self.schedule_btn = ttk.Button(sd_btns, text="Schedule",
                                       command=self._schedule_shutdown, takefocus=0)
        self.schedule_btn.grid(row=0, column=0, padx=4)
        self.cancel_shutdown_btn = ttk.Button(sd_btns, text="Cancel",
                                              command=self._cancel_shutdown,
                                              state="disabled", takefocus=0)
        self.cancel_shutdown_btn.grid(row=0, column=1, padx=4)

        ttk.Label(frm, text="Shut down and Restart use Windows' own delayed "
                             "timer, so they still fire even if Bendo is closed. "
                             "Hibernate has no such OS timer, so it only fires "
                             "while Bendo keeps running.",
                  foreground=self._fg("muted"), wraplength=360, justify="left").grid(
            row=5, column=0, columnspan=3, sticky="w", padx=10, pady=(4, 0))

    def _on_shutdown_action_change(self, event=None):
        self.cfg["shutdown_action"] = self.SHUTDOWN_ACTION_LABELS_REV[
            self.shutdown_action_var.get()]
        save_config(self.cfg)

    CLICKER_BUTTON_LABELS = {"left": "Left", "right": "Right", "middle": "Middle"}
    CLICKER_BUTTON_LABELS_REV = {v: k for k, v in CLICKER_BUTTON_LABELS.items()}

    def _build_clicker_tab(self, frm, pad):
        ttk.Label(frm, text="Interval (ms)").grid(row=0, column=0, sticky="w", **pad)
        self.clicker_interval_var = tk.StringVar(value=str(self.cfg["clicker_interval_ms"]))
        ttk.Spinbox(frm, from_=10, to=600000, textvariable=self.clicker_interval_var,
                    width=20).grid(row=0, column=1, **pad)
        self.clicker_interval_var.trace_add("write", self._on_clicker_settings_change)

        ttk.Label(frm, text="Button").grid(row=1, column=0, sticky="w", **pad)
        self.clicker_button_var = tk.StringVar(
            value=self.CLICKER_BUTTON_LABELS[self.cfg["clicker_button"]])
        ttk.Combobox(frm, textvariable=self.clicker_button_var,
                    values=list(self.CLICKER_BUTTON_LABELS.values()),
                    state="readonly", width=17, takefocus=0).grid(
            row=1, column=1, sticky="w", **pad)
        self.clicker_button_var.trace_add("write", self._on_clicker_settings_change)

        ttk.Label(frm, text="Click limit (0 = unlimited)").grid(
            row=2, column=0, sticky="w", **pad)
        self.clicker_limit_var = tk.StringVar(value=str(self.cfg["clicker_limit"]))
        ttk.Spinbox(frm, from_=0, to=1000000, textvariable=self.clicker_limit_var,
                    width=20).grid(row=2, column=1, **pad)
        self.clicker_limit_var.trace_add("write", self._on_clicker_settings_change)

        self.clicker_position_var = tk.StringVar(value="current")
        ttk.Radiobutton(frm, text="Click at current cursor position",
                        variable=self.clicker_position_var, value="current",
                        takefocus=0).grid(row=3, column=0, columnspan=2, sticky="w", padx=10)
        pos_row = ttk.Frame(frm)
        pos_row.grid(row=4, column=0, columnspan=2, sticky="w", padx=10)
        ttk.Radiobutton(pos_row, text="Click at a fixed position:",
                        variable=self.clicker_position_var, value="fixed",
                        takefocus=0).grid(row=0, column=0)
        self.clicker_pos_label = ttk.Label(pos_row, text="(not set)")
        self.clicker_pos_label.grid(row=0, column=1, padx=(6, 6))
        ttk.Button(pos_row, text="Capture in 3s", command=self._capture_clicker_position,
                  takefocus=0).grid(row=0, column=2)

        hotkey_row = ttk.Frame(frm)
        hotkey_row.grid(row=5, column=0, columnspan=2, sticky="w", **pad)
        ttk.Label(hotkey_row, text="Toggle hotkey").grid(row=0, column=0, padx=(0, 8))
        self.clicker_hotkey_var = tk.StringVar(value=self.cfg["clicker_hotkey"])
        ttk.Entry(hotkey_row, textvariable=self.clicker_hotkey_var, width=18,
                  state="readonly", takefocus=0).grid(row=0, column=1, padx=(0, 8))
        self.clicker_capture_btn = ttk.Button(hotkey_row, text="Set", width=8,
                                              command=self._capture_clicker_hotkey,
                                              takefocus=0)
        self.clicker_capture_btn.grid(row=0, column=2, padx=(0, 8))
        self.clicker_hotkey_armed_var = tk.BooleanVar(value=self.cfg["clicker_hotkey_armed"])
        ttk.Checkbutton(hotkey_row, text="Enabled", variable=self.clicker_hotkey_armed_var,
                        command=self._toggle_clicker_hotkey_armed, takefocus=0).grid(
            row=0, column=3)

        self.clicker_status = ttk.Label(frm, text="Stopped.", foreground=self._fg("normal"))
        self.clicker_status.grid(row=6, column=0, columnspan=2, sticky="w", **pad)

        clicker_btns = ttk.Frame(frm)
        clicker_btns.grid(row=7, column=0, columnspan=2, sticky="ew", **pad)
        self.clicker_start_btn = ttk.Button(clicker_btns, text="Start",
                                            command=self._start_clicker, takefocus=0)
        self.clicker_start_btn.grid(row=0, column=0, padx=4)
        self.clicker_stop_btn = ttk.Button(clicker_btns, text="Stop",
                                           command=self._stop_clicker, state="disabled",
                                           takefocus=0)
        self.clicker_stop_btn.grid(row=0, column=1, padx=4)

    def _on_clicker_settings_change(self, *_):
        try:
            interval = int(self.clicker_interval_var.get())
            limit = int(self.clicker_limit_var.get())
        except ValueError:
            return  # ignore partial/invalid typing
        self.cfg["clicker_interval_ms"] = interval
        self.cfg["clicker_limit"] = limit
        self.cfg["clicker_button"] = self.CLICKER_BUTTON_LABELS_REV[
            self.clicker_button_var.get()]
        save_config(self.cfg)

    def _capture_clicker_position(self):
        self.clicker_pos_label.config(text="Move mouse...")
        self.root.after(3000, self._finish_capture_clicker_position)

    def _finish_capture_clicker_position(self):
        self.clicker_fixed_pos = get_cursor_pos()
        self.clicker_position_var.set("fixed")
        self.clicker_pos_label.config(text=f"({self.clicker_fixed_pos[0]}, "
                                            f"{self.clicker_fixed_pos[1]})")

    # ----- clicker toggle hotkey -----
    def _capture_clicker_hotkey(self):
        if keyboard is None or self.clicker_capturing:
            return
        self.clicker_capturing = True
        self._capture_gens["clicker"] += 1
        gen = self._capture_gens["clicker"]
        self.clicker_capture_btn.config(state="disabled")
        self.clicker_status.config(text="Press the key combination...",
                                   foreground=self._fg("error"))
        threading.Thread(
            target=lambda: self.events.put(
                ("clicker_hotkey_captured",
                 (gen, keyboard.read_hotkey(suppress=False)))),
            daemon=True,
        ).start()
        self.root.after(self.CAPTURE_TIMEOUT_MS,
                        lambda: self._capture_timed_out("clicker", gen))

    def _toggle_clicker_hotkey_armed(self):
        self.cfg["clicker_hotkey_armed"] = self.clicker_hotkey_armed_var.get()
        save_config(self.cfg)
        self._register_clicker_hotkey()

    def _apply_clicker_hotkey(self):
        self.cfg["clicker_hotkey"] = self.clicker_hotkey_var.get()
        save_config(self.cfg)
        self._register_clicker_hotkey()

    def _register_clicker_hotkey(self):
        if keyboard is None or "clicker" not in self.tab_frames:
            return
        if self.clicker_hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.clicker_hotkey_handle)
            except Exception:
                pass
            self.clicker_hotkey_handle = None
        if not self.cfg["clicker_hotkey_armed"]:
            return
        try:
            self.clicker_hotkey_handle = keyboard.add_hotkey(
                self.cfg["clicker_hotkey"],
                lambda: self.events.put(("toggle_clicker", None)))
        except Exception as e:
            self.clicker_status.config(text=f"Bad hotkey: {e}", foreground=self._fg("error"))

    def _toggle_clicker(self):
        if "clicker" not in self.tab_frames:
            return
        if self.clicker_running:
            self._stop_clicker()
        else:
            self._start_clicker()

    # ----- clicker run loop -----
    def _start_clicker(self):
        if self.clicker_running:
            return
        try:
            interval_ms = int(self.clicker_interval_var.get())
        except ValueError:
            interval_ms = self.cfg["clicker_interval_ms"]
        try:
            limit = int(self.clicker_limit_var.get())
        except ValueError:
            limit = 0
        use_fixed = self.clicker_position_var.get() == "fixed"
        if use_fixed and self.clicker_fixed_pos is None:
            self.clicker_status.config(text="Capture a fixed position first.",
                                       foreground=self._fg("error"))
            return
        button = self.CLICKER_BUTTON_LABELS_REV[self.clicker_button_var.get()]
        self.clicker_stop_event.clear()
        self.clicker_running = True
        self.clicker_start_btn.config(state="disabled")
        self.clicker_stop_btn.config(state="normal")
        self.clicker_status.config(text="Running - 0 clicks", foreground=self._fg("error"))
        threading.Thread(
            target=self._clicker_loop,
            args=(max(interval_ms, 10) / 1000, button, limit, use_fixed,
                  self.clicker_fixed_pos),
            daemon=True,
        ).start()

    def _stop_clicker(self):
        self.clicker_stop_event.set()
        self.clicker_running = False
        self.clicker_start_btn.config(state="normal")
        self.clicker_stop_btn.config(state="disabled")
        self.clicker_status.config(text="Stopped.", foreground=self._fg("normal"))

    def _clicker_loop(self, interval_s, button, limit, use_fixed, fixed_pos):
        count = 0
        while not self.clicker_stop_event.is_set():
            if use_fixed:
                set_cursor_pos(*fixed_pos)
            click_mouse(button)
            count += 1
            self.events.put(("clicker_tick", count))
            if limit and count >= limit:
                self.events.put(("clicker_done", None))
                return
            if self.clicker_stop_event.wait(interval_s):
                return

    def _build_timer_tab(self, frm, pad):
        t_frame = ttk.Frame(frm)
        t_frame.grid(row=0, column=0, columnspan=3, sticky="w", **pad)

        self.timer_days_var = tk.StringVar(value=f"{self.cfg['timer_days']:02d}")
        self.timer_hours_var = tk.StringVar(value=f"{self.cfg['timer_hours']:02d}")
        self.timer_minutes_var = tk.StringVar(value=f"{self.cfg['timer_minutes']:02d}")
        self.timer_seconds_var = tk.StringVar(value=f"{self.cfg['timer_seconds']:02d}")

        self._add_time_box(t_frame, "Days", self.timer_days_var, 0, 365, 0)
        self._add_time_box(t_frame, "Hours", self.timer_hours_var, 0, 23, 1)
        self._add_time_box(t_frame, "Minutes", self.timer_minutes_var, 0, 59, 2)
        self._add_time_box(t_frame, "Seconds", self.timer_seconds_var, 0, 59, 3)

        for var in (self.timer_days_var, self.timer_hours_var,
                   self.timer_minutes_var, self.timer_seconds_var):
            var.trace_add("write", self._on_timer_fields_change)

        self.timer_status = ttk.Label(frm, text="Not running.", foreground=self._fg("normal"))
        self.timer_status.grid(row=1, column=0, columnspan=3, sticky="w", **pad)

        timer_btns = ttk.Frame(frm)
        timer_btns.grid(row=2, column=0, columnspan=3, sticky="ew", **pad)
        self.timer_start_btn = ttk.Button(timer_btns, text="Start",
                                          command=self._start_timer, takefocus=0)
        self.timer_start_btn.grid(row=0, column=0, padx=4)
        self.timer_cancel_btn = ttk.Button(timer_btns, text="Cancel",
                                           command=self._cancel_timer,
                                           state="disabled", takefocus=0)
        self.timer_cancel_btn.grid(row=0, column=1, padx=4)

    def _on_timer_fields_change(self, *_):
        try:
            self.cfg["timer_days"] = int(self.timer_days_var.get())
            self.cfg["timer_hours"] = int(self.timer_hours_var.get())
            self.cfg["timer_minutes"] = int(self.timer_minutes_var.get())
            self.cfg["timer_seconds"] = int(self.timer_seconds_var.get())
        except ValueError:
            return  # ignore partial/invalid typing
        save_config(self.cfg)

    def _timer_total_seconds(self):
        try:
            days = int(self.timer_days_var.get())
            hours = int(self.timer_hours_var.get())
            minutes = int(self.timer_minutes_var.get())
            seconds = int(self.timer_seconds_var.get())
        except ValueError:
            return None
        return days * 86400 + hours * 3600 + minutes * 60 + seconds

    def _start_timer(self):
        total = self._timer_total_seconds()
        if not total:
            self.timer_status.config(text="Set a duration greater than 0.",
                                     foreground=self._fg("error"))
            return
        self.timer_target = time.time() + total
        self.timer_start_btn.config(state="disabled")
        self.timer_cancel_btn.config(state="normal")
        self._tick_timer()

    def _cancel_timer(self):
        self.timer_target = None
        self.timer_start_btn.config(state="normal")
        self.timer_cancel_btn.config(state="disabled")
        self.timer_status.config(text="Cancelled.", foreground=self._fg("normal"))

    def _tick_timer(self):
        if self.timer_target is None:
            return
        remaining = int(round(self.timer_target - time.time()))
        if remaining <= 0:
            self.timer_status.config(text="Time's up!", foreground=self._fg("error"))
            self._notify("Timer finished.")
            try:
                winsound.MessageBeep()
            except Exception:
                pass
            self.timer_target = None
            self.timer_start_btn.config(state="normal")
            self.timer_cancel_btn.config(state="disabled")
            return
        self.timer_status.config(text=f"{format_hms(remaining)} remaining",
                                 foreground=self._fg("normal"))
        self.root.after(1000, self._tick_timer)

    def _build_mixer_tab(self, frm, pad):
        if AudioUtilities is None:
            ttk.Label(frm, text="Install 'pycaw' and 'comtypes' for the volume "
                                 "mixer (pip install pycaw comtypes).",
                      foreground=self._fg("error")).grid(row=0, column=0, sticky="w", **pad)
            return

        ttk.Label(frm, text="Master Volume", font=("", 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=10)

        master_row = ttk.Frame(frm)
        master_row.grid(row=1, column=0, sticky="ew", **pad)
        self.master_vol_var = tk.DoubleVar()
        ttk.Scale(master_row, from_=0, to=100, orient="horizontal", length=260,
                  variable=self.master_vol_var,
                  command=self._on_master_volume_change, takefocus=0).grid(
            row=0, column=0, padx=(0, 8))
        self.master_mute_var = tk.BooleanVar()
        ttk.Checkbutton(master_row, text="Mute", variable=self.master_mute_var,
                        command=self._on_master_mute_toggle, takefocus=0).grid(
            row=0, column=1)

        hotkey_row = ttk.Frame(frm)
        hotkey_row.grid(row=2, column=0, sticky="w", **pad)
        ttk.Label(hotkey_row, text="Mute hotkey").grid(row=0, column=0, padx=(0, 8))
        self.mute_hotkey_var = tk.StringVar(value=self.cfg["mute_hotkey"])
        ttk.Entry(hotkey_row, textvariable=self.mute_hotkey_var, width=18,
                  state="readonly", takefocus=0).grid(row=0, column=1, padx=(0, 8))
        self.mute_capture_btn = ttk.Button(hotkey_row, text="Set", width=8,
                                           command=self._capture_mute_hotkey,
                                           takefocus=0)
        self.mute_capture_btn.grid(row=0, column=2, padx=(0, 8))
        self.mute_hotkey_armed_var = tk.BooleanVar(value=self.cfg["mute_hotkey_armed"])
        ttk.Checkbutton(hotkey_row, text="Enabled", variable=self.mute_hotkey_armed_var,
                        command=self._toggle_mute_hotkey_armed, takefocus=0).grid(
            row=0, column=3)

        self.mixer_hotkey_status = ttk.Label(frm, text="", foreground=self._fg("normal"))
        self.mixer_hotkey_status.grid(row=3, column=0, sticky="w", padx=10)

        ttk.Separator(frm, orient="horizontal").grid(
            row=4, column=0, sticky="ew", pady=(4, 10))

        header = ttk.Frame(frm)
        header.grid(row=5, column=0, sticky="ew", padx=10)
        ttk.Label(header, text="Applications", font=("", 9, "bold")).grid(
            row=0, column=0, sticky="w")
        self.mixer_filter_var = tk.StringVar()
        ttk.Entry(header, textvariable=self.mixer_filter_var, width=16).grid(
            row=0, column=1, padx=(12, 4))
        self.mixer_filter_var.trace_add(
            "write", lambda *_: self._refresh_mixer_sessions())
        ttk.Button(header, text="Refresh", command=self._refresh_mixer_sessions,
                  takefocus=0).grid(row=0, column=2, padx=(4, 0))

        self.mixer_list = ttk.Frame(frm)
        self.mixer_list.grid(row=6, column=0, sticky="ew", **pad)
        self.mixer_rows = {}  # pid -> row dict

        self._sync_master_volume()
        self._refresh_mixer_sessions()
        self._tick_mixer()

    def _build_notes_tab(self, frm, pad):
        text_frame = ttk.Frame(frm)
        text_frame.grid(row=0, column=0, sticky="nsew", **pad)

        self.notes_text = self._register_themed_widget(
            tk.Text(text_frame, width=50, height=16, wrap="word", undo=True))
        self.notes_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical",
                                  command=self.notes_text.yview, takefocus=0)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.notes_text.config(yscrollcommand=scrollbar.set)

        try:
            if os.path.exists(NOTES_AUTOSAVE_PATH):
                with open(NOTES_AUTOSAVE_PATH, "r", encoding="utf-8") as f:
                    self.notes_text.insert("1.0", f.read())
        except Exception:
            pass

        self.notes_status = ttk.Label(frm, text="", foreground=self._fg("normal"))
        self.notes_status.grid(row=1, column=0, sticky="w", **pad)

        self.notes_autosave_label = ttk.Label(frm, text="", foreground=self._fg("faint"))
        self.notes_autosave_label.grid(row=2, column=0, sticky="w", **pad)

        ttk.Button(frm, text="Save as .txt", command=self._save_notes,
                  takefocus=0).grid(row=3, column=0, sticky="w", padx=10)

        self._tick_notes_autosave()

    def _tick_notes_autosave(self):
        try:
            with open(NOTES_AUTOSAVE_PATH, "w", encoding="utf-8") as f:
                f.write(self.notes_text.get("1.0", "end-1c"))
            self.notes_autosave_label.config(
                text=f"Autosaved locally at {time.strftime('%H:%M:%S')}")
        except Exception:
            pass
        self.root.after(15000, self._tick_notes_autosave)

    def _save_notes(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save notes as")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.notes_text.get("1.0", "end-1c"))
        except Exception as e:
            self.notes_status.config(text=f"Failed to save: {e}", foreground=self._fg("error"))
            return
        self.notes_status.config(text=f"Saved to {path}", foreground=self._fg("normal"))

    def _build_clipboard_tab(self, frm, pad):
        ttk.Label(frm, text="Clipboard History", font=("", 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=10)
        ttk.Label(frm, text="Kept in memory only for this session (never written "
                             "to disk), up to the last 50 items. Double-click an "
                             "entry to copy it again.",
                  foreground=self._fg("muted"), wraplength=360, justify="left").grid(
            row=1, column=0, sticky="w", padx=10, pady=(0, 8))

        list_frame = ttk.Frame(frm)
        list_frame.grid(row=2, column=0, sticky="ew", **pad)
        self.clipboard_listbox = self._register_themed_widget(
            tk.Listbox(list_frame, width=50, height=14, activestyle="none",
                      exportselection=False))
        self.clipboard_listbox.grid(row=0, column=0, sticky="nsew")
        clip_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                    command=self.clipboard_listbox.yview, takefocus=0)
        clip_scroll.grid(row=0, column=1, sticky="ns")
        self.clipboard_listbox.config(yscrollcommand=clip_scroll.set)
        self.clipboard_listbox.bind("<Double-Button-1>",
                                    lambda e: self._copy_selected_clipboard_item())

        clip_btns = ttk.Frame(frm)
        clip_btns.grid(row=3, column=0, sticky="w", padx=10)
        ttk.Button(clip_btns, text="Copy selected",
                  command=self._copy_selected_clipboard_item, takefocus=0).grid(
            row=0, column=0, padx=(0, 4))
        ttk.Button(clip_btns, text="Clear history",
                  command=self._clear_clipboard_history, takefocus=0).grid(
            row=0, column=1, padx=4)

        self._tick_clipboard_watch()

    def _tick_clipboard_watch(self):
        try:
            current = self.root.clipboard_get()
        except tk.TclError:
            current = None
        if current and current != self._last_clipboard_value:
            self._last_clipboard_value = current
            if not self.clipboard_history or self.clipboard_history[0] != current:
                self.clipboard_history.insert(0, current)
                del self.clipboard_history[50:]
                self._refresh_clipboard_list()
        self.root.after(1000, self._tick_clipboard_watch)

    def _refresh_clipboard_list(self):
        self.clipboard_listbox.delete(0, "end")
        for text in self.clipboard_history:
            preview = " ".join(text.split())
            if len(preview) > 60:
                preview = preview[:60] + "..."
            self.clipboard_listbox.insert("end", preview or "(empty)")

    def _copy_selected_clipboard_item(self):
        selection = self.clipboard_listbox.curselection()
        if not selection:
            return
        text = self.clipboard_history[selection[0]]
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._last_clipboard_value = text  # don't re-add it as "new" next tick

    def _clear_clipboard_history(self):
        self.clipboard_history = []
        self._refresh_clipboard_list()

    def _build_stats_tab(self, frm, pad):
        if psutil is None:
            ttk.Label(frm, text="Install 'psutil' for the system stats tab "
                                 "(pip install psutil).",
                      foreground=self._fg("error")).grid(row=0, column=0, sticky="w", **pad)
            return

        self.cpu_label = ttk.Label(frm, text="CPU: -")
        self.cpu_label.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        self.cpu_bar = ttk.Progressbar(frm, length=280, maximum=100)
        self.cpu_bar.grid(row=1, column=0, sticky="w", **pad)

        self.ram_label = ttk.Label(frm, text="RAM: -")
        self.ram_label.grid(row=2, column=0, sticky="w", padx=10)
        self.ram_bar = ttk.Progressbar(frm, length=280, maximum=100)
        self.ram_bar.grid(row=3, column=0, sticky="w", **pad)

        self.disk_label = ttk.Label(frm, text="Disk: -")
        self.disk_label.grid(row=4, column=0, sticky="w", padx=10)
        self.disk_bar = ttk.Progressbar(frm, length=280, maximum=100)
        self.disk_bar.grid(row=5, column=0, sticky="w", **pad)

        self.net_label = ttk.Label(frm, text="Network: -")
        self.net_label.grid(row=6, column=0, sticky="w", **pad)

        psutil.cpu_percent(None)  # first call is meaningless; primes the average
        self._last_net_io = psutil.net_io_counters()
        self._last_net_time = time.time()
        self._tick_stats()

    def _tick_stats(self):
        cpu = psutil.cpu_percent(None)
        mem = psutil.virtual_memory()
        drive = os.path.splitdrive(sys.executable)[0] + "\\"
        disk = psutil.disk_usage(drive)

        now = time.time()
        io = psutil.net_io_counters()
        elapsed = max(now - self._last_net_time, 0.001)
        up_kbps = (io.bytes_sent - self._last_net_io.bytes_sent) / 1024 / elapsed
        down_kbps = (io.bytes_recv - self._last_net_io.bytes_recv) / 1024 / elapsed
        self._last_net_io = io
        self._last_net_time = now

        self.cpu_label.config(text=f"CPU: {cpu:.0f}%")
        self.cpu_bar["value"] = cpu
        self.ram_label.config(
            text=f"RAM: {mem.percent:.0f}%  "
                 f"({mem.used / 2**30:.1f} / {mem.total / 2**30:.1f} GB)")
        self.ram_bar["value"] = mem.percent
        self.disk_label.config(
            text=f"Disk ({drive}): {disk.percent:.0f}%  "
                 f"({disk.used / 2**30:.0f} / {disk.total / 2**30:.0f} GB)")
        self.disk_bar["value"] = disk.percent
        self.net_label.config(
            text=f"Network: Up {up_kbps:.0f} KB/s   Down {down_kbps:.0f} KB/s")

        self.root.after(1500, self._tick_stats)

    # ----- bookshelf -----
    def _build_bookshelf_tab(self, frm, pad):
        ttk.Label(frm, text="Bookshelf", font=("", 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=10)
        ttk.Label(frm, text="Quick access to files and folders you use often. "
                             "Double-click an item to open it.",
                  foreground=self._fg("muted"), wraplength=360, justify="left").grid(
            row=1, column=0, sticky="w", padx=10, pady=(0, 8))

        list_frame = ttk.Frame(frm)
        list_frame.grid(row=2, column=0, sticky="ew", **pad)
        self.bookshelf_listbox = self._register_themed_widget(
            tk.Listbox(list_frame, width=52, height=12, activestyle="none",
                      exportselection=False))
        self.bookshelf_listbox.grid(row=0, column=0, sticky="nsew")
        bs_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                  command=self.bookshelf_listbox.yview, takefocus=0)
        bs_scroll.grid(row=0, column=1, sticky="ns")
        self.bookshelf_listbox.config(yscrollcommand=bs_scroll.set)
        self.bookshelf_listbox.bind("<Double-Button-1>",
                                    lambda e: self._open_bookshelf_item())

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, sticky="w", padx=10)
        ttk.Button(btns, text="Add file...", command=self._add_bookshelf_file,
                  takefocus=0).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(btns, text="Add folder...", command=self._add_bookshelf_folder,
                  takefocus=0).grid(row=0, column=1, padx=4)
        ttk.Button(btns, text="Remove", command=self._remove_bookshelf_item,
                  takefocus=0).grid(row=0, column=2, padx=4)

        self.bookshelf_status = ttk.Label(frm, text="", foreground=self._fg("normal"))
        self.bookshelf_status.grid(row=4, column=0, sticky="w", padx=10, pady=(4, 0))

        self._refresh_bookshelf_list()

    def _refresh_bookshelf_list(self):
        self.bookshelf_listbox.delete(0, "end")
        for path in self.cfg["bookshelf_items"]:
            self.bookshelf_listbox.insert("end", path)

    def _add_bookshelf_file(self):
        path = filedialog.askopenfilename(title="Add file to Bookshelf")
        if not path:
            return
        self.cfg["bookshelf_items"].append(path)
        save_config(self.cfg)
        self._refresh_bookshelf_list()

    def _add_bookshelf_folder(self):
        path = filedialog.askdirectory(title="Add folder to Bookshelf")
        if not path:
            return
        self.cfg["bookshelf_items"].append(path)
        save_config(self.cfg)
        self._refresh_bookshelf_list()

    def _remove_bookshelf_item(self):
        selection = self.bookshelf_listbox.curselection()
        if not selection:
            return
        del self.cfg["bookshelf_items"][selection[0]]
        save_config(self.cfg)
        self._refresh_bookshelf_list()

    def _open_bookshelf_item(self):
        selection = self.bookshelf_listbox.curselection()
        if not selection:
            return
        path = self.cfg["bookshelf_items"][selection[0]]
        try:
            os.startfile(path)
        except OSError as e:
            self.bookshelf_status.config(text=f"Failed to open: {e}", foreground=self._fg("error"))

    # ----- drawing notepad -----
    def _build_drawpad_tab(self, frm, pad):
        if Image is None:
            ttk.Label(frm, text="Install 'Pillow' for the drawing notepad "
                                 "(pip install Pillow).",
                      foreground=self._fg("error")).grid(row=0, column=0, sticky="w", **pad)
            return

        ttk.Label(frm, text="Draw below with the mouse.", foreground=self._fg("muted")).grid(
            row=0, column=0, columnspan=5, sticky="w", padx=10, pady=(6, 4))

        canvas_w, canvas_h = 460, 300
        self.drawpad_canvas = tk.Canvas(frm, width=canvas_w, height=canvas_h,
                                        bg="white", highlightthickness=1)
        self.drawpad_canvas.grid(row=1, column=0, columnspan=5, sticky="w", padx=10)
        self.drawpad_canvas.bind("<Button-1>", self._drawpad_start)
        self.drawpad_canvas.bind("<B1-Motion>", self._drawpad_draw)
        self.drawpad_canvas.bind("<ButtonRelease-1>",
                                 lambda e: setattr(self, "_drawpad_last", None))

        self._drawpad_image = Image.new("RGB", (canvas_w, canvas_h), "white")
        self._drawpad_draw_ctx = ImageDraw.Draw(self._drawpad_image)
        self._drawpad_last = None
        self.drawpad_color = "#000000"

        controls = ttk.Frame(frm)
        controls.grid(row=2, column=0, columnspan=5, sticky="w", padx=10, pady=(6, 0))
        ttk.Label(controls, text="Brush size").grid(row=0, column=0, padx=(0, 6))
        self.drawpad_size_var = tk.IntVar(value=3)
        ttk.Spinbox(controls, from_=1, to=30, textvariable=self.drawpad_size_var,
                    width=5).grid(row=0, column=1, padx=(0, 10))
        ttk.Button(controls, text="Color...", command=self._pick_drawpad_color,
                  takefocus=0).grid(row=0, column=2, padx=(0, 4))
        ttk.Button(controls, text="Clear", command=self._clear_drawpad,
                  takefocus=0).grid(row=0, column=3, padx=4)
        ttk.Button(controls, text="Save as PNG...", command=self._save_drawpad,
                  takefocus=0).grid(row=0, column=4, padx=4)

        self.drawpad_status = ttk.Label(frm, text="", foreground=self._fg("normal"))
        self.drawpad_status.grid(row=3, column=0, columnspan=5, sticky="w",
                                 padx=10, pady=(4, 0))

    def _drawpad_start(self, event):
        self._drawpad_last = (event.x, event.y)

    def _drawpad_draw(self, event):
        if self._drawpad_last is None:
            self._drawpad_last = (event.x, event.y)
            return
        x0, y0 = self._drawpad_last
        x1, y1 = event.x, event.y
        size = self.drawpad_size_var.get()
        self.drawpad_canvas.create_line(x0, y0, x1, y1, fill=self.drawpad_color,
                                        width=size, capstyle="round", smooth=True)
        self._drawpad_draw_ctx.line([x0, y0, x1, y1], fill=self.drawpad_color, width=size)
        self._drawpad_last = (x1, y1)

    def _pick_drawpad_color(self):
        color = colorchooser.askcolor(color=self.drawpad_color, title="Choose brush color")
        if color[1]:
            self.drawpad_color = color[1]

    def _clear_drawpad(self):
        self.drawpad_canvas.delete("all")
        self._drawpad_draw_ctx.rectangle(
            [0, 0, self._drawpad_image.width, self._drawpad_image.height], fill="white")

    def _save_drawpad(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG files", "*.png")],
            title="Save drawing as")
        if not path:
            return
        try:
            self._drawpad_image.save(path)
        except Exception as e:
            self.drawpad_status.config(text=f"Failed to save: {e}", foreground=self._fg("error"))
            return
        self.drawpad_status.config(text=f"Saved to {path}", foreground=self._fg("normal"))

    # ----- mini photo tool -----
    def _build_photo_tab(self, frm, pad):
        if Image is None:
            ttk.Label(frm, text="Install 'Pillow' for the photo tool "
                                 "(pip install Pillow).",
                      foreground=self._fg("error")).grid(row=0, column=0, sticky="w", **pad)
            return

        btns = ttk.Frame(frm)
        btns.grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(6, 4))
        ttk.Button(btns, text="Open image...", command=self._open_photo,
                  takefocus=0).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(btns, text="Save as...", command=self._save_photo,
                  takefocus=0).grid(row=0, column=1, padx=4)

        # Label's -width/-height switch from character units to pixel units
        # the moment it displays an image instead of text, so we show a
        # blank placeholder image from the start rather than mixing modes -
        # that mismatch was what made loaded photos render tiny/cropped.
        self._photo_placeholder = ImageTk.PhotoImage(Image.new("RGB", (420, 300), "#cccccc"))
        self.photo_preview_label = tk.Label(frm, image=self._photo_placeholder,
                                            borderwidth=0)
        self.photo_preview_label.grid(row=1, column=0, columnspan=4, sticky="w", padx=10)

        adjust_row = ttk.Frame(frm)
        adjust_row.grid(row=2, column=0, columnspan=4, sticky="w", padx=10, pady=(6, 0))
        ttk.Label(adjust_row, text="Brightness").grid(row=0, column=0, padx=(0, 6))
        self.photo_brightness_var = tk.DoubleVar(value=1.0)
        ttk.Scale(adjust_row, from_=0.2, to=2.0, variable=self.photo_brightness_var,
                  orient="horizontal", length=140, takefocus=0,
                  command=lambda v: self._update_photo_preview()).grid(row=0, column=1)
        ttk.Label(adjust_row, text="Contrast").grid(row=0, column=2, padx=(12, 6))
        self.photo_contrast_var = tk.DoubleVar(value=1.0)
        ttk.Scale(adjust_row, from_=0.2, to=2.0, variable=self.photo_contrast_var,
                  orient="horizontal", length=140, takefocus=0,
                  command=lambda v: self._update_photo_preview()).grid(row=0, column=3)

        tool_row = ttk.Frame(frm)
        tool_row.grid(row=3, column=0, columnspan=4, sticky="w", padx=10, pady=(6, 0))
        ttk.Button(tool_row, text="Rotate 90", takefocus=0,
                  command=lambda: self._transform_photo("rotate")).grid(
            row=0, column=0, padx=(0, 4))
        ttk.Button(tool_row, text="Flip H", takefocus=0,
                  command=lambda: self._transform_photo("fliph")).grid(
            row=0, column=1, padx=4)
        ttk.Button(tool_row, text="Flip V", takefocus=0,
                  command=lambda: self._transform_photo("flipv")).grid(
            row=0, column=2, padx=4)
        ttk.Button(tool_row, text="Grayscale", takefocus=0,
                  command=lambda: self._transform_photo("gray")).grid(
            row=0, column=3, padx=4)
        ttk.Button(tool_row, text="Reset adjustments", command=self._reset_photo,
                  takefocus=0).grid(row=0, column=4, padx=4)

        self.photo_status = ttk.Label(frm, text="", foreground=self._fg("normal"))
        self.photo_status.grid(row=4, column=0, columnspan=4, sticky="w", padx=10, pady=(4, 0))

        self._photo_original = None
        self._photo_current = None
        self._photo_tk = None

    def _open_photo(self):
        path = filedialog.askopenfilename(
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif"),
                      ("All files", "*.*")],
            title="Open image")
        if not path:
            return
        try:
            img = Image.open(path).convert("RGB")
        except Exception as e:
            self.photo_status.config(text=f"Failed to open: {e}", foreground=self._fg("error"))
            return
        self._photo_original = img
        self.photo_brightness_var.set(1.0)
        self.photo_contrast_var.set(1.0)
        self._update_photo_preview()
        self.photo_status.config(text=os.path.basename(path), foreground=self._fg("normal"))

    def _update_photo_preview(self):
        if self._photo_original is None:
            return
        img = ImageEnhance.Brightness(self._photo_original).enhance(
            self.photo_brightness_var.get())
        img = ImageEnhance.Contrast(img).enhance(self.photo_contrast_var.get())
        self._photo_current = img
        preview = img.copy()
        preview.thumbnail((420, 300))
        self._photo_tk = ImageTk.PhotoImage(preview)
        self.photo_preview_label.config(image=self._photo_tk, text="")

    def _transform_photo(self, kind):
        if self._photo_original is None:
            return
        if kind == "rotate":
            self._photo_original = self._photo_original.rotate(-90, expand=True)
        elif kind == "fliph":
            self._photo_original = self._photo_original.transpose(Image.FLIP_LEFT_RIGHT)
        elif kind == "flipv":
            self._photo_original = self._photo_original.transpose(Image.FLIP_TOP_BOTTOM)
        elif kind == "gray":
            self._photo_original = self._photo_original.convert("L").convert("RGB")
        self._update_photo_preview()

    def _reset_photo(self):
        if self._photo_original is None:
            return
        self.photo_brightness_var.set(1.0)
        self.photo_contrast_var.set(1.0)
        self._update_photo_preview()

    def _save_photo(self):
        if self._photo_current is None:
            self.photo_status.config(text="No image to save.", foreground=self._fg("error"))
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG files", "*.png"), ("JPEG files", "*.jpg")],
            title="Save image as")
        if not path:
            return
        try:
            self._photo_current.save(path)
        except Exception as e:
            self.photo_status.config(text=f"Failed to save: {e}", foreground=self._fg("error"))
            return
        self.photo_status.config(text=f"Saved to {path}", foreground=self._fg("normal"))

    # ----- reminders & alarms -----
    def _build_reminders_tab(self, frm, pad):
        ttk.Label(frm, text="Reminders & Alarms", font=("", 9, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=10)

        form = ttk.Frame(frm)
        form.grid(row=1, column=0, columnspan=4, sticky="w", padx=10, pady=(6, 4))
        ttk.Label(form, text="Date (YYYY-MM-DD)").grid(row=0, column=0, padx=(0, 6))
        self.reminder_date_var = tk.StringVar(value=datetime.date.today().isoformat())
        ttk.Entry(form, textvariable=self.reminder_date_var, width=12).grid(
            row=0, column=1, padx=(0, 10))
        ttk.Label(form, text="Time (HH:MM)").grid(row=0, column=2, padx=(0, 6))
        self.reminder_time_var = tk.StringVar(value="09:00")
        ttk.Entry(form, textvariable=self.reminder_time_var, width=8).grid(row=0, column=3)

        form2 = ttk.Frame(frm)
        form2.grid(row=2, column=0, columnspan=4, sticky="w", padx=10, pady=(0, 4))
        ttk.Label(form2, text="Note").grid(row=0, column=0, padx=(0, 6))
        self.reminder_note_var = tk.StringVar()
        ttk.Entry(form2, textvariable=self.reminder_note_var, width=30).grid(
            row=0, column=1, padx=(0, 10))
        self.reminder_repeat_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form2, text="Repeat daily", variable=self.reminder_repeat_var,
                        takefocus=0).grid(row=0, column=2, padx=(0, 10))

        form3 = ttk.Frame(frm)
        form3.grid(row=3, column=0, columnspan=4, sticky="w", padx=10, pady=(0, 6))
        self.reminder_sound_path = None
        self.reminder_sound_label = ttk.Label(form3, text="Sound: default beep")
        self.reminder_sound_label.grid(row=0, column=0, padx=(0, 6))
        ttk.Button(form3, text="Choose sound...", command=self._choose_reminder_sound,
                  takefocus=0).grid(row=0, column=1, padx=(0, 4))
        ttk.Button(form3, text="Default sound", command=self._clear_reminder_sound,
                  takefocus=0).grid(row=0, column=2, padx=4)
        ttk.Button(form3, text="Add Reminder", command=self._add_reminder,
                  takefocus=0).grid(row=0, column=3, padx=(12, 0))

        list_frame = ttk.Frame(frm)
        list_frame.grid(row=4, column=0, columnspan=4, sticky="ew", **pad)
        self.reminders_listbox = self._register_themed_widget(
            tk.Listbox(list_frame, width=58, height=9, activestyle="none",
                      exportselection=False))
        self.reminders_listbox.grid(row=0, column=0, sticky="nsew")
        rem_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                   command=self.reminders_listbox.yview, takefocus=0)
        rem_scroll.grid(row=0, column=1, sticky="ns")
        self.reminders_listbox.config(yscrollcommand=rem_scroll.set)

        ttk.Button(frm, text="Remove selected", command=self._remove_reminder,
                  takefocus=0).grid(row=5, column=0, sticky="w", padx=10)

        self.reminders_status = ttk.Label(frm, text="", foreground=self._fg("normal"))
        self.reminders_status.grid(row=6, column=0, columnspan=4, sticky="w",
                                   padx=10, pady=(4, 0))

        self._refresh_reminders_list()
        self._tick_reminders()

    def _choose_reminder_sound(self):
        path = filedialog.askopenfilename(
            filetypes=[("WAV files", "*.wav"), ("All files", "*.*")],
            title="Choose alarm sound")
        if not path:
            return
        self.reminder_sound_path = path
        self.reminder_sound_label.config(text=os.path.basename(path))

    def _clear_reminder_sound(self):
        self.reminder_sound_path = None
        self.reminder_sound_label.config(text="Sound: default beep")

    def _add_reminder(self):
        try:
            when = datetime.datetime.strptime(
                f"{self.reminder_date_var.get()} {self.reminder_time_var.get()}",
                "%Y-%m-%d %H:%M")
        except ValueError:
            self.reminders_status.config(
                text="Invalid date/time. Use YYYY-MM-DD and HH:MM.", foreground=self._fg("error"))
            return
        note = self.reminder_note_var.get().strip() or "Reminder"
        self.cfg["reminders"].append({
            "when": when.isoformat(),
            "note": note,
            "repeat_daily": self.reminder_repeat_var.get(),
            "sound_path": self.reminder_sound_path,
            "enabled": True,
        })
        save_config(self.cfg)
        self.reminder_note_var.set("")
        self._refresh_reminders_list()
        self.reminders_status.config(text="Reminder added.", foreground=self._fg("normal"))

    def _remove_reminder(self):
        selection = self.reminders_listbox.curselection()
        if not selection:
            return
        del self.cfg["reminders"][selection[0]]
        save_config(self.cfg)
        self._refresh_reminders_list()

    def _refresh_reminders_list(self):
        self.reminders_listbox.delete(0, "end")
        for r in self.cfg["reminders"]:
            when = datetime.datetime.fromisoformat(r["when"])
            repeat = " (daily)" if r.get("repeat_daily") else ""
            fired = "" if r.get("enabled", True) else " [fired]"
            self.reminders_listbox.insert(
                "end", f"{when.strftime('%Y-%m-%d %H:%M')}{repeat} - {r['note']}{fired}")

    def _tick_reminders(self):
        now = datetime.datetime.now()
        changed = False
        for r in self.cfg["reminders"]:
            if not r.get("enabled", True):
                continue
            when = datetime.datetime.fromisoformat(r["when"])
            if now >= when:
                self._fire_reminder(r)
                if r.get("repeat_daily"):
                    # Catch up in one jump if the PC was off for several
                    # days - otherwise it would fire once per missed day.
                    while when <= now:
                        when += datetime.timedelta(days=1)
                    r["when"] = when.isoformat()
                else:
                    r["enabled"] = False
                changed = True
        if changed:
            save_config(self.cfg)
            self._refresh_reminders_list()
        self.root.after(20000, self._tick_reminders)

    def _fire_reminder(self, r):
        self._notify(r["note"], title="Bendo Reminder")
        try:
            if r.get("sound_path"):
                winsound.PlaySound(r["sound_path"], winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                winsound.MessageBeep()
        except Exception:
            pass

    # ----- media controller -----
    def _build_media_tab(self, frm, pad):
        if not HAS_MEDIA_CONTROL:
            ttk.Label(frm, text="Install the winrt media packages for the media "
                                 "controller (pip install winrt-runtime "
                                 "\"winrt-Windows.Media.Control\").",
                      foreground=self._fg("error")).grid(row=0, column=0, sticky="w", **pad)
            return

        self.media_title_label = ttk.Label(frm, text="No media playing",
                                           font=("", 10, "bold"))
        self.media_title_label.grid(row=0, column=0, columnspan=3, sticky="w",
                                    padx=10, pady=(10, 0))
        self.media_artist_label = ttk.Label(frm, text="")
        self.media_artist_label.grid(row=1, column=0, columnspan=3, sticky="w", padx=10)

        self.media_position_var = tk.DoubleVar(value=0)
        self.media_scale = ttk.Scale(frm, from_=0, to=100, orient="horizontal",
                                     length=340, variable=self.media_position_var,
                                     takefocus=0)
        self.media_scale.grid(row=2, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 0))
        self.media_scale.bind("<ButtonPress-1>",
                              lambda e: setattr(self, "_media_user_seeking", True))
        self.media_scale.bind("<ButtonRelease-1>", self._media_seek_release)

        self.media_time_label = ttk.Label(frm, text="0:00 / 0:00")
        self.media_time_label.grid(row=3, column=0, columnspan=3, sticky="w", padx=10)

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 0))
        ttk.Button(btns, text="Previous", takefocus=0,
                  command=lambda: self._media_action("prev")).grid(row=0, column=0, padx=4)
        ttk.Button(btns, text="Play/Pause", takefocus=0,
                  command=lambda: self._media_action("play_pause")).grid(
            row=0, column=1, padx=4)
        ttk.Button(btns, text="Next", takefocus=0,
                  command=lambda: self._media_action("next")).grid(row=0, column=2, padx=4)

        self._media_duration = 0
        self._tick_media()

    def _media_action(self, action):
        asyncio.run_coroutine_threadsafe(self._media_control_action(action),
                                         self._media_loop)

    async def _media_control_action(self, action):
        try:
            mgr = await MediaSessionManager.request_async()
            session = mgr.get_current_session()
            if session is None:
                return
            if action == "play_pause":
                await session.try_toggle_play_pause_async()
            elif action == "next":
                await session.try_skip_next_async()
            elif action == "prev":
                await session.try_skip_previous_async()
        except Exception:
            pass

    def _media_seek_release(self, event):
        self._media_user_seeking = False
        seconds = self.media_position_var.get()
        asyncio.run_coroutine_threadsafe(self._media_seek_async(seconds), self._media_loop)

    async def _media_seek_async(self, seconds):
        try:
            mgr = await MediaSessionManager.request_async()
            session = mgr.get_current_session()
            if session is None:
                return
            await session.try_change_playback_position_async(int(seconds * 10_000_000))
        except Exception:
            pass

    def _tick_media(self):
        if HAS_MEDIA_CONTROL:
            fut = asyncio.run_coroutine_threadsafe(self._media_poll_async(), self._media_loop)
            fut.add_done_callback(
                lambda f: self.events.put(
                    ("media_update", f.result() if not f.exception() else None)))
        self.root.after(1000, self._tick_media)

    MEDIA_PLAYING_STATUS = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING

    async def _media_poll_async(self):
        try:
            mgr = await MediaSessionManager.request_async()
            session = mgr.get_current_session()
            if session is None:
                return None
            props = await session.try_get_media_properties_async()
            timeline = session.get_timeline_properties()
            playback = session.get_playback_info()

            # timeline.position is only a snapshot as of last_updated_time -
            # source apps push new timeline events occasionally, not every
            # second, so the raw value can sit frozen between pushes even
            # while actually playing. Interpolate with elapsed real time so
            # the displayed position still advances every second.
            position = timeline.position.total_seconds()
            playing = int(playback.playback_status) == self.MEDIA_PLAYING_STATUS
            if playing:
                now = datetime.datetime.now(datetime.timezone.utc)
                elapsed = (now - timeline.last_updated_time).total_seconds()
                position = min(position + max(elapsed, 0), timeline.end_time.total_seconds())

            return {
                "title": props.title or "",
                "artist": props.artist or "",
                "position": position,
                "duration": timeline.end_time.total_seconds(),
                "playing": playing,
            }
        except Exception:
            return None

    def _handle_media_update(self, info):
        if not hasattr(self, "media_title_label"):
            return  # tab not built (winsdk missing)
        if info is None:
            self.media_title_label.config(text="No media playing")
            self.media_artist_label.config(text="")
            self.media_time_label.config(text="0:00 / 0:00")
            if not self._media_user_seeking:
                self.media_position_var.set(0)
            return
        self.media_title_label.config(text=info["title"] or "(untitled)")
        self.media_artist_label.config(text=info["artist"])
        self._media_duration = info["duration"]
        self.media_scale.config(to=max(info["duration"], 1))
        if not self._media_user_seeking:
            self.media_position_var.set(info["position"])
        self.media_time_label.config(
            text=f"{self._format_mmss(info['position'])} / {self._format_mmss(info['duration'])}")

    @staticmethod
    def _format_mmss(seconds):
        seconds = int(seconds)
        return f"{seconds // 60}:{seconds % 60:02d}"

    # ----- file converter -----
    CONVERTIBLE_FORMATS = ["PNG", "JPEG", "BMP", "GIF", "WEBP", "TIFF", "ICO"]

    def _build_converter_tab(self, frm, pad):
        if Image is None:
            self.converter_missing_label = ttk.Label(
                frm, text="Install 'Pillow' for the file converter "
                          "(pip install Pillow).",
                foreground=self._fg("error"), wraplength=360, justify="left")
            self.converter_missing_label.grid(row=0, column=0, sticky="w", **pad)
            return

        ttk.Label(frm, text="File Converter", font=("", 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=10)
        ttk.Label(frm, text="Converts images between formats.",
                  foreground=self._fg("muted")).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 6))

        list_frame = ttk.Frame(frm)
        list_frame.grid(row=2, column=0, sticky="ew", **pad)
        self.converter_listbox = self._register_themed_widget(
            tk.Listbox(list_frame, width=52, height=10, selectmode="extended",
                      exportselection=False))
        self.converter_listbox.grid(row=0, column=0, sticky="nsew")
        conv_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                    command=self.converter_listbox.yview, takefocus=0)
        conv_scroll.grid(row=0, column=1, sticky="ns")
        self.converter_listbox.config(yscrollcommand=conv_scroll.set)

        file_btns = ttk.Frame(frm)
        file_btns.grid(row=3, column=0, sticky="w", padx=10)
        ttk.Button(file_btns, text="Add files...", command=self._add_converter_files,
                  takefocus=0).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(file_btns, text="Remove selected", command=self._remove_converter_files,
                  takefocus=0).grid(row=0, column=1, padx=4)
        ttk.Button(file_btns, text="Clear", command=self._clear_converter_files,
                  takefocus=0).grid(row=0, column=2, padx=4)

        format_row = ttk.Frame(frm)
        format_row.grid(row=4, column=0, sticky="w", padx=10, pady=(8, 0))
        ttk.Label(format_row, text="Convert to").grid(row=0, column=0, padx=(0, 6))
        self.converter_format_var = tk.StringVar(value="PNG")
        ttk.Combobox(format_row, textvariable=self.converter_format_var,
                    values=self.CONVERTIBLE_FORMATS, state="readonly", width=8,
                    takefocus=0).grid(row=0, column=1)

        output_row = ttk.Frame(frm)
        output_row.grid(row=5, column=0, sticky="w", padx=10, pady=(6, 0))
        ttk.Label(output_row, text="Output folder:").grid(row=0, column=0, padx=(0, 6))
        self.converter_output_label = ttk.Label(output_row, text="Same folder as source")
        self.converter_output_label.grid(row=0, column=1, padx=(0, 6))
        ttk.Button(output_row, text="Choose...", command=self._choose_converter_output_dir,
                  takefocus=0).grid(row=0, column=2, padx=(0, 4))
        ttk.Button(output_row, text="Reset", command=self._reset_converter_output_dir,
                  takefocus=0).grid(row=0, column=3)

        self.converter_convert_btn = ttk.Button(frm, text="Convert", takefocus=0,
                                                 command=self._start_conversion)
        self.converter_convert_btn.grid(row=6, column=0, sticky="w", padx=10, pady=(10, 0))

        self.converter_status = ttk.Label(frm, text="", foreground=self._fg("normal"))
        self.converter_status.grid(row=7, column=0, sticky="w", padx=10, pady=(4, 0))

    def _add_converter_files(self):
        paths = filedialog.askopenfilenames(
            title="Add files to convert",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tiff *.ico"),
                      ("All files", "*.*")])
        self.converter_files.extend(paths)
        self._refresh_converter_list()

    def _remove_converter_files(self):
        for idx in reversed(self.converter_listbox.curselection()):
            del self.converter_files[idx]
        self._refresh_converter_list()

    def _clear_converter_files(self):
        self.converter_files = []
        self._refresh_converter_list()

    def _refresh_converter_list(self):
        self.converter_listbox.delete(0, "end")
        for path in self.converter_files:
            self.converter_listbox.insert("end", os.path.basename(path))

    def _choose_converter_output_dir(self):
        path = filedialog.askdirectory(title="Choose output folder")
        if not path:
            return
        self.converter_output_dir = path
        self.converter_output_label.config(text=path)

    def _reset_converter_output_dir(self):
        self.converter_output_dir = None
        self.converter_output_label.config(text="Same folder as source")

    def _start_conversion(self):
        if not self.converter_files:
            self.converter_status.config(text="Add files first.", foreground=self._fg("error"))
            return
        self.converter_convert_btn.config(state="disabled")
        self.converter_status.config(text="Converting...", foreground=self._fg("normal"))
        threading.Thread(
            target=self._convert_worker,
            args=(list(self.converter_files), self.converter_format_var.get().lower(),
                  self.converter_output_dir),
            daemon=True,
        ).start()

    def _convert_worker(self, files, target_ext, output_dir):
        errors = []
        for i, path in enumerate(files, 1):
            try:
                img = Image.open(path)
                save_kwargs = {}
                # keep animation when both source and target support it
                if (target_ext in ("gif", "webp", "tiff")
                        and getattr(img, "n_frames", 1) > 1):
                    save_kwargs["save_all"] = True
                elif target_ext in ("jpeg", "jpg", "bmp") and img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")  # covers RGBA/P and also LA/CMYK
                out_dir = output_dir or os.path.dirname(path)
                base = os.path.splitext(os.path.basename(path))[0]
                out_path = os.path.join(out_dir, f"{base}.{target_ext}")
                if os.path.normcase(os.path.abspath(out_path)) == \
                        os.path.normcase(os.path.abspath(path)):
                    # converting to the file's own format+folder would
                    # silently overwrite the original
                    out_path = os.path.join(out_dir, f"{base}_converted.{target_ext}")
                img.save(out_path, **save_kwargs)
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")
            self.events.put(("converter_progress", (i, len(files))))
        self.events.put(("converter_done", errors))

    # ----- automatic Pillow install (source runs only) -----
    def _maybe_auto_install_pillow(self):
        """If the File Converter is enabled but Pillow is missing, install
        it in the background automatically. Only applies when running from
        source - the packaged full exe always ships Pillow, and Lite
        doesn't offer the converter at all."""
        if (getattr(sys, "frozen", False) or Image is not None
                or self._pillow_installing
                or not self.cfg["tab_visible"].get("converter")
                or "converter" not in self.tab_frames):
            return
        self._pillow_installing = True
        if hasattr(self, "converter_missing_label"):
            self.converter_missing_label.config(
                text="Installing Pillow automatically - the converter will "
                     "be ready in a moment...",
                foreground=self._fg("normal"))
        threading.Thread(target=self._pillow_install_worker, daemon=True).start()

    def _pillow_install_worker(self):
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "Pillow"],
            capture_output=True, text=True, creationflags=NO_WINDOW)
        self.events.put(("pillow_install_done", result.returncode == 0))

    def _handle_pillow_install_done(self, ok):
        self._pillow_installing = False
        global Image, ImageDraw, ImageEnhance, ImageTk
        if ok:
            try:
                import importlib
                importlib.invalidate_caches()
                from PIL import (Image as pil_image, ImageDraw as pil_draw,
                                 ImageEnhance as pil_enhance, ImageTk as pil_tk)
                Image, ImageDraw = pil_image, pil_draw
                ImageEnhance, ImageTk = pil_enhance, pil_tk
            except ImportError:
                ok = False
        if not ok:
            if hasattr(self, "converter_missing_label"):
                self.converter_missing_label.config(
                    text="Automatic Pillow install failed - run "
                         "'pip install Pillow' yourself and restart Bendo.",
                    foreground=self._fg("error"))
            return
        self._rebuild_pillow_tabs()
        if hasattr(self, "converter_status"):
            self.converter_status.config(
                text="Pillow installed - the converter is ready.",
                foreground=self._fg("normal"))

    def _rebuild_pillow_tabs(self):
        """Re-run the builders for the Pillow-dependent tabs so their real
        UIs replace the 'install Pillow' placeholders without a restart.
        (The tray icon and background images still need a restart.)"""
        pad = {"padx": 10, "pady": 6}
        for tab_id, builder in (("converter", self._build_converter_tab),
                                ("drawpad", self._build_drawpad_tab),
                                ("photo", self._build_photo_tab)):
            frame = self.tab_frames.get(tab_id)
            if frame is None:
                continue
            for child in frame.winfo_children():
                child.destroy()
            builder(frame, pad)
        self._apply_theme()  # the new widgets pick up the current theme
        self._resize_to_tab()

    def _handle_converter_progress(self, done, total):
        self.converter_status.config(text=f"Converting {done}/{total}...", foreground=self._fg("normal"))

    def _handle_converter_done(self, errors):
        self.converter_convert_btn.config(state="normal")
        if errors:
            self.converter_status.config(
                text=f"Done with {len(errors)} error(s): " + "; ".join(errors[:3]),
                foreground=self._fg("error"))
        else:
            self.converter_status.config(text="All files converted.", foreground=self._fg("normal"))

    # ----- calendar -----
    def _build_calendar_tab(self, frm, pad):
        today = datetime.date.today()
        self.calendar_year = today.year
        self.calendar_month = today.month
        self.calendar_selected_date = today.isoformat()

        nav = ttk.Frame(frm)
        nav.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        ttk.Button(nav, text="< Prev", command=self._calendar_prev_month,
                  takefocus=0).grid(row=0, column=0, padx=(0, 8))
        self.calendar_month_label = ttk.Label(nav, text="", font=("", 10, "bold"), width=16,
                                              anchor="center")
        self.calendar_month_label.grid(row=0, column=1)
        ttk.Button(nav, text="Next >", command=self._calendar_next_month,
                  takefocus=0).grid(row=0, column=2, padx=(8, 0))

        self.calendar_grid_frame = ttk.Frame(frm)
        self.calendar_grid_frame.grid(row=1, column=0, sticky="w", padx=10)

        ttk.Separator(frm, orient="horizontal").grid(
            row=2, column=0, sticky="ew", padx=10, pady=(10, 8))

        self.calendar_selected_label = ttk.Label(frm, text="", font=("", 9, "bold"))
        self.calendar_selected_label.grid(row=3, column=0, sticky="w", padx=10)

        events_list_frame = ttk.Frame(frm)
        events_list_frame.grid(row=4, column=0, sticky="ew", **pad)
        self.calendar_events_listbox = self._register_themed_widget(
            tk.Listbox(events_list_frame, width=50, height=6, activestyle="none",
                      exportselection=False))
        self.calendar_events_listbox.grid(row=0, column=0, sticky="nsew")
        cal_scroll = ttk.Scrollbar(events_list_frame, orient="vertical",
                                   command=self.calendar_events_listbox.yview, takefocus=0)
        cal_scroll.grid(row=0, column=1, sticky="ns")
        self.calendar_events_listbox.config(yscrollcommand=cal_scroll.set)

        add_row = ttk.Frame(frm)
        add_row.grid(row=5, column=0, sticky="w", padx=10, pady=(4, 0))
        self.calendar_event_var = tk.StringVar()
        ttk.Entry(add_row, textvariable=self.calendar_event_var, width=32).grid(
            row=0, column=0, padx=(0, 6))
        ttk.Button(add_row, text="Add Event", command=self._add_calendar_event,
                  takefocus=0).grid(row=0, column=1, padx=(0, 4))
        ttk.Button(add_row, text="Remove Selected", command=self._remove_calendar_event,
                  takefocus=0).grid(row=0, column=2)

        self._render_calendar_grid()
        self._render_calendar_day_events()

    def _render_calendar_grid(self):
        for widget in self.calendar_grid_frame.winfo_children():
            widget.destroy()
        self.calendar_month_label.config(
            text=f"{calendar_module.month_name[self.calendar_month]} {self.calendar_year}")

        for i, day_name in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            ttk.Label(self.calendar_grid_frame, text=day_name, width=4,
                     anchor="center").grid(row=0, column=i, padx=1, pady=1)

        cal = calendar_module.Calendar(firstweekday=0)
        for row, week in enumerate(
                cal.monthdayscalendar(self.calendar_year, self.calendar_month), start=1):
            for col, day in enumerate(week):
                if day == 0:
                    ttk.Label(self.calendar_grid_frame, text="", width=4).grid(
                        row=row, column=col, padx=1, pady=1)
                    continue
                date_str = datetime.date(self.calendar_year, self.calendar_month, day).isoformat()
                has_events = bool(self.cfg["calendar_events"].get(date_str))
                text = f"{day}*" if has_events else str(day)
                ttk.Button(self.calendar_grid_frame, text=text, width=4, takefocus=0,
                          command=lambda d=date_str: self._select_calendar_date(d)).grid(
                    row=row, column=col, padx=1, pady=1)

    def _select_calendar_date(self, date_str):
        self.calendar_selected_date = date_str
        self._render_calendar_day_events()

    def _render_calendar_day_events(self):
        self.calendar_selected_label.config(text=f"Events on {self.calendar_selected_date}")
        self.calendar_events_listbox.delete(0, "end")
        for event_text in self.cfg["calendar_events"].get(self.calendar_selected_date, []):
            self.calendar_events_listbox.insert("end", event_text)

    def _add_calendar_event(self):
        text = self.calendar_event_var.get().strip()
        if not text:
            return
        self.cfg["calendar_events"].setdefault(self.calendar_selected_date, []).append(text)
        save_config(self.cfg)
        self.calendar_event_var.set("")
        self._render_calendar_day_events()
        self._render_calendar_grid()

    def _remove_calendar_event(self):
        selection = self.calendar_events_listbox.curselection()
        if not selection:
            return
        events = self.cfg["calendar_events"].get(self.calendar_selected_date, [])
        del events[selection[0]]
        if not events:
            self.cfg["calendar_events"].pop(self.calendar_selected_date, None)
        save_config(self.cfg)
        self._render_calendar_day_events()
        self._render_calendar_grid()

    def _calendar_prev_month(self):
        self.calendar_month -= 1
        if self.calendar_month == 0:
            self.calendar_month = 12
            self.calendar_year -= 1
        self._render_calendar_grid()

    def _calendar_next_month(self):
        self.calendar_month += 1
        if self.calendar_month == 13:
            self.calendar_month = 1
            self.calendar_year += 1
        self._render_calendar_grid()

    def _toggle_start_with_windows(self):
        enabled = self.start_with_windows_var.get()
        self.cfg["start_with_windows"] = enabled
        save_config(self.cfg)
        if set_startup_enabled(enabled):
            self.startup_status.config(text="", foreground=self._fg("normal"))
        else:
            self.startup_status.config(
                text="Failed to update the startup scheduled task.", foreground=self._fg("error"))

    def _build_power_tab(self, frm, pad):
        ttk.Label(frm, text="Power actions", font=("", 9, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10)
        ttk.Label(frm, text="These run immediately - there is no countdown, "
                             "unlike the Shutdown Scheduler tab.",
                  foreground=self._fg("muted"), wraplength=360, justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 8))

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=2, sticky="w", **pad)
        ttk.Button(btns, text="Lock", width=12, command=self._power_lock,
                  takefocus=0).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(btns, text="Sign out", width=12, command=self._power_sign_out,
                  takefocus=0).grid(row=0, column=1, padx=4, pady=4)
        ttk.Button(btns, text="Sleep", width=12, command=self._power_sleep,
                  takefocus=0).grid(row=1, column=0, padx=4, pady=4)
        ttk.Button(btns, text="Hibernate", width=12, command=self._power_hibernate,
                  takefocus=0).grid(row=1, column=1, padx=4, pady=4)
        ttk.Button(btns, text="Restart", width=12, command=self._power_restart,
                  takefocus=0).grid(row=2, column=0, padx=4, pady=4)

        self.power_force_var = tk.BooleanVar(value=self.cfg["power_force"])
        ttk.Checkbutton(frm, text="Force-close apps on restart (/f)",
                        variable=self.power_force_var,
                        command=self._toggle_power_force, takefocus=0).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=10)

        self.power_status = ttk.Label(frm, text="", foreground=self._fg("normal"))
        self.power_status.grid(row=4, column=0, columnspan=2, sticky="w", **pad)

    def _toggle_power_force(self):
        self.cfg["power_force"] = self.power_force_var.get()
        save_config(self.cfg)

    def _power_lock(self):
        if not lock_workstation():
            self.power_status.config(text="Failed to lock the workstation.",
                                     foreground=self._fg("error"))

    def _power_sign_out(self):
        if not sign_out():
            self.power_status.config(text="Failed to sign out.", foreground=self._fg("error"))

    def _power_sleep(self):
        if not sleep_now():
            self.power_status.config(text="Failed to sleep.", foreground=self._fg("error"))

    def _power_hibernate(self):
        if not hibernate_now():
            self.power_status.config(text="Failed to hibernate.", foreground=self._fg("error"))

    def _power_restart(self):
        result = restart_now(self.power_force_var.get())
        if result.returncode != 0:
            self.power_status.config(
                text=f"Failed to restart: {result.stderr.strip()}", foreground=self._fg("error"))

    def _export_settings(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Export settings")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2)
        except Exception as e:
            self.backup_status.config(text=f"Failed to export: {e}", foreground=self._fg("error"))
            return
        self.backup_status.config(text=f"Exported settings to {path}", foreground=self._fg("normal"))

    def _import_settings(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Import settings")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("file does not contain a settings object")
        except Exception as e:
            self.backup_status.config(text=f"Failed to import: {e}", foreground=self._fg("error"))
            return

        merged = copy.deepcopy(DEFAULT_CONFIG)
        merged.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
        sanitize_config(merged)
        known = self._known_tab_ids()
        order = [t for t in merged.get("tab_order", []) if t in known]
        order += [t for t in known if t not in order]
        merged["tab_order"] = order
        visible = merged.get("tab_visible", {})
        merged["tab_visible"] = {t: visible.get(t, True) for t in known}

        self.cfg = merged
        save_config(self.cfg)
        self._apply_imported_config()
        self.backup_status.config(text=f"Imported settings from {path}", foreground=self._fg("normal"))

    def _apply_imported_config(self):
        if "internet" in self.tab_frames:  # absent in the Lite edition
            self.hotkey_var.set(self.cfg["hotkey"])
            self.duration_var.set(str(self.cfg["duration"]))
            self.on_top_var.set(self.cfg["on_top"])
            self.armed_var.set(self.cfg["armed"])
        self.root.attributes("-topmost", self.cfg["on_top"])
        self._register_hotkey()
        self._update_status()
        self._refresh_controls()

        self.days_var.set(f"{self.cfg['shutdown_days']:02d}")
        self.hours_var.set(f"{self.cfg['shutdown_hours']:02d}")
        self.minutes_var.set(f"{self.cfg['shutdown_minutes']:02d}")
        self.seconds_var.set(f"{self.cfg['shutdown_seconds']:02d}")
        self.shutdown_force_var.set(self.cfg["shutdown_force"])
        self.shutdown_action_var.set(
            self.SHUTDOWN_ACTION_LABELS[self.cfg.get("shutdown_action", "shutdown")])

        if AudioUtilities is not None:
            self.mute_hotkey_var.set(self.cfg["mute_hotkey"])
            self.mute_hotkey_armed_var.set(self.cfg["mute_hotkey_armed"])
            self._register_mute_hotkey()

        self.start_with_windows_var.set(self.cfg["start_with_windows"])
        set_startup_enabled(self.cfg["start_with_windows"])

        self.power_force_var.set(self.cfg["power_force"])

        if hasattr(self, "close_behavior_var"):
            self.close_behavior_var.set(self.cfg["close_behavior"])

        if "clicker" in self.tab_frames:  # absent in the Lite edition
            self.clicker_interval_var.set(str(self.cfg["clicker_interval_ms"]))
            self.clicker_button_var.set(self.CLICKER_BUTTON_LABELS[self.cfg["clicker_button"]])
            self.clicker_limit_var.set(str(self.cfg["clicker_limit"]))
            self.clicker_hotkey_var.set(self.cfg["clicker_hotkey"])
            self.clicker_hotkey_armed_var.set(self.cfg["clicker_hotkey_armed"])
            self._register_clicker_hotkey()

        if "timer" in self.tab_frames:  # absent in the Lite edition
            self.timer_days_var.set(f"{self.cfg['timer_days']:02d}")
            self.timer_hours_var.set(f"{self.cfg['timer_hours']:02d}")
            self.timer_minutes_var.set(f"{self.cfg['timer_minutes']:02d}")
            self.timer_seconds_var.set(f"{self.cfg['timer_seconds']:02d}")

        self.tab_rows_var.set(self.cfg.get("tab_rows", "Auto"))

        self.theme_var.set(self.THEME_LABELS[self.cfg.get("theme", "light")])
        self._apply_theme()
        bg_path = self.cfg.get("background_image_path")
        if bg_path and Image is not None:
            try:
                self._bg_image_pil = Image.open(bg_path).convert("RGB")
            except Exception:
                self._bg_image_pil = None
        else:
            self._bg_image_pil = None
        self.background_label.config(text=os.path.basename(bg_path) if bg_path else "None")
        self._update_background_image()

        if hasattr(self, "bookshelf_listbox"):
            self._refresh_bookshelf_list()
        if hasattr(self, "reminders_listbox"):
            self._refresh_reminders_list()
        if hasattr(self, "calendar_grid_frame"):
            self._render_calendar_grid()
            self._render_calendar_day_events()

        self._apply_tab_order()
        self._refresh_settings_rows()

    def _build_settings_tab(self, frm, pad):
        # Settings is far taller than any other tab, so its content lives
        # inside a scrollable canvas capped to a fraction of the screen
        # height - otherwise the window grows past the bottom of the screen
        # and the user has to drag it up to reach the last sections.
        self.settings_canvas = tk.Canvas(frm, highlightthickness=0, borderwidth=0)
        settings_scroll = ttk.Scrollbar(frm, orient="vertical",
                                        command=self.settings_canvas.yview,
                                        takefocus=0)
        self.settings_canvas.grid(row=0, column=0, sticky="nsew")
        settings_scroll.grid(row=0, column=1, sticky="ns")
        self.settings_canvas.configure(yscrollcommand=settings_scroll.set)
        self._settings_inner = ttk.Frame(self.settings_canvas)
        self.settings_canvas.create_window((0, 0), window=self._settings_inner,
                                           anchor="nw")
        self._settings_inner.bind("<Configure>", self._on_settings_inner_configure)
        self.root.bind_all("<MouseWheel>", self._on_settings_mousewheel, add="+")
        frm = self._settings_inner  # everything below builds into the scroller

        row = iter(range(1000))  # simple auto-incrementing row counter

        ttk.Label(frm, text="Tools", font=("", 9, "bold")).grid(
            row=next(row), column=0, sticky="w", padx=10)
        ttk.Label(frm, text="Untick a tool to remove it from Bendo - its tab "
                             "disappears immediately. Tick it again any time "
                             "to bring it back (nothing is lost). Reorder "
                             "tools by dragging the tab buttons above or with "
                             "the arrows below. The Settings tab always stays "
                             "visible and last.",
                  foreground=self._fg("muted"), wraplength=360, justify="left").grid(
            row=next(row), column=0, sticky="w", padx=10, pady=(0, 8))

        self.settings_list = ttk.Frame(frm)
        self.settings_list.grid(row=next(row), column=0, sticky="ew", **pad)

        ttk.Button(frm, text="Reset to default", command=self._reset_tab_settings,
                  takefocus=0).grid(row=next(row), column=0, sticky="w", padx=10, pady=(8, 0))

        ttk.Label(frm, text="Tab rows").grid(
            row=next(row), column=0, sticky="w", padx=10, pady=(10, 0))
        rows_frame = ttk.Frame(frm)
        rows_frame.grid(row=next(row), column=0, sticky="w", padx=10)
        self.tab_rows_var = tk.StringVar(value=str(self.cfg.get("tab_rows", "Auto")))
        for i, label in enumerate(self.TAB_ROW_OPTIONS):
            ttk.Radiobutton(rows_frame, text=label, variable=self.tab_rows_var,
                            value=label, command=self._on_tab_rows_change,
                            takefocus=0).grid(row=0, column=i, padx=(0, 10))
        ttk.Label(frm, text="Forces the tab strip to wrap into that many rows "
                             "(evenly divided) instead of sizing to fit them all "
                             "on one line.",
                  foreground=self._fg("muted"), wraplength=360, justify="left").grid(
            row=next(row), column=0, sticky="w", padx=10, pady=(2, 0))

        ttk.Separator(frm, orient="horizontal").grid(
            row=next(row), column=0, sticky="ew", padx=10, pady=(14, 10))

        ttk.Label(frm, text="Closing the window", font=("", 9, "bold")).grid(
            row=next(row), column=0, sticky="w", padx=10)

        if pystray is not None:
            self.close_behavior_var = tk.StringVar(
                value=self.cfg.get("close_behavior", "tray"))
            ttk.Radiobutton(frm, text="Minimize to the system tray",
                            variable=self.close_behavior_var, value="tray",
                            command=self._on_close_behavior_change, takefocus=0).grid(
                row=next(row), column=0, sticky="w", padx=10, pady=(4, 0))
            ttk.Radiobutton(frm, text="Fully close the app",
                            variable=self.close_behavior_var, value="exit",
                            command=self._on_close_behavior_change, takefocus=0).grid(
                row=next(row), column=0, sticky="w", padx=10)
        else:
            no_tray_msg = ("Bendo Lite doesn't include the system tray, so "
                           "closing the window exits the app."
                           if LITE_BUILD else
                           "System tray isn't available (install pystray), "
                           "so closing the window always exits the app.")
            ttk.Label(frm, text=no_tray_msg,
                      foreground=self._fg("muted"), wraplength=360, justify="left").grid(
                row=next(row), column=0, sticky="w", padx=10, pady=(4, 0))

        ttk.Separator(frm, orient="horizontal").grid(
            row=next(row), column=0, sticky="ew", padx=10, pady=(14, 10))

        ttk.Label(frm, text="Startup", font=("", 9, "bold")).grid(
            row=next(row), column=0, sticky="w", padx=10)
        ttk.Label(frm, text="Launch Bendo automatically when you sign in to "
                             "Windows. This uses a scheduled task that starts "
                             "Bendo with administrator rights, so there is no "
                             "UAC prompt at sign-in.",
                  foreground=self._fg("muted"), wraplength=360, justify="left").grid(
            row=next(row), column=0, sticky="w", padx=10, pady=(0, 8))

        self.start_with_windows_var = tk.BooleanVar(value=self.cfg["start_with_windows"])
        ttk.Checkbutton(frm, text="Start with Windows",
                        variable=self.start_with_windows_var,
                        command=self._toggle_start_with_windows, takefocus=0).grid(
            row=next(row), column=0, sticky="w", padx=10, pady=(0, 6))

        self.startup_status = ttk.Label(frm, text="", foreground=self._fg("normal"))
        self.startup_status.grid(row=next(row), column=0, sticky="w", padx=10)

        # Reconcile the scheduled task with the saved preference right away,
        # in case the user (or another tool) removed it by hand.
        if not set_startup_enabled(self.cfg["start_with_windows"]):
            self.startup_status.config(
                text="Could not create the startup scheduled task.",
                foreground=self._fg("error"))

        ttk.Separator(frm, orient="horizontal").grid(
            row=next(row), column=0, sticky="ew", padx=10, pady=(14, 10))

        ttk.Label(frm, text="Backup & Restore", font=("", 9, "bold")).grid(
            row=next(row), column=0, sticky="w", padx=10)
        ttk.Label(frm, text="Export all Bendo settings to a JSON file, or import "
                             "a previously exported file. Importing applies "
                             "immediately.",
                  foreground=self._fg("muted"), wraplength=360, justify="left").grid(
            row=next(row), column=0, sticky="w", padx=10, pady=(0, 8))

        backup_btns = ttk.Frame(frm)
        backup_btns.grid(row=next(row), column=0, sticky="w", padx=10)
        ttk.Button(backup_btns, text="Export settings...", command=self._export_settings,
                  takefocus=0).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(backup_btns, text="Import settings...", command=self._import_settings,
                  takefocus=0).grid(row=0, column=1, padx=4)

        self.backup_status = ttk.Label(frm, text="", foreground=self._fg("normal"))
        self.backup_status.grid(row=next(row), column=0, sticky="w", padx=10, pady=(4, 0))

        ttk.Separator(frm, orient="horizontal").grid(
            row=next(row), column=0, sticky="ew", padx=10, pady=(14, 10))

        ttk.Label(frm, text="Appearance", font=("", 9, "bold")).grid(
            row=next(row), column=0, sticky="w", padx=10)

        self.theme_var = tk.StringVar(value=self.THEME_LABELS[self.cfg.get("theme", "light")])
        theme_row = ttk.Frame(frm)
        theme_row.grid(row=next(row), column=0, sticky="w", padx=10, pady=(4, 0))
        for i, label in enumerate(self.THEME_LABELS.values()):
            ttk.Radiobutton(theme_row, text=label, variable=self.theme_var, value=label,
                            command=self._on_theme_change, takefocus=0).grid(
                row=0, column=i, padx=(0, 10))

        custom_row = ttk.Frame(frm)
        custom_row.grid(row=next(row), column=0, sticky="w", padx=10, pady=(6, 0))
        ttk.Button(custom_row, text="Custom background color...",
                  command=lambda: self._pick_custom_color(
                      "custom_bg_color", "Choose background color"),
                  takefocus=0).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(custom_row, text="Custom text color...",
                  command=lambda: self._pick_custom_color(
                      "custom_fg_color", "Choose text color"),
                  takefocus=0).grid(row=0, column=1)

        bg_row = ttk.Frame(frm)
        bg_row.grid(row=next(row), column=0, sticky="w", padx=10, pady=(6, 0))
        ttk.Label(bg_row, text="Background image:").grid(row=0, column=0, padx=(0, 6))
        bg_name = (os.path.basename(self.cfg["background_image_path"])
                  if self.cfg.get("background_image_path") else "None")
        self.background_label = ttk.Label(bg_row, text=bg_name)
        self.background_label.grid(row=0, column=1, padx=(0, 6))
        ttk.Button(bg_row, text="Choose...", command=self._choose_background_image,
                  takefocus=0).grid(row=0, column=2, padx=(0, 4))
        ttk.Button(bg_row, text="Clear", command=self._clear_background_image,
                  takefocus=0).grid(row=0, column=3)
        ttk.Label(frm, text="The image shows as a border around the tab "
                             "content (the tabs themselves stay solid).",
                  foreground=self._fg("muted"), wraplength=360, justify="left").grid(
            row=next(row), column=0, sticky="w", padx=10, pady=(2, 0))

        self.appearance_status = ttk.Label(frm, text="", foreground=self._fg("normal"))
        self.appearance_status.grid(row=next(row), column=0, sticky="w", padx=10, pady=(4, 0))

        ttk.Separator(frm, orient="horizontal").grid(
            row=next(row), column=0, sticky="ew", padx=10, pady=(14, 10))

        if not LITE_BUILD:  # Lite has no optional tools, so no onboarding
            ttk.Label(frm, text="Help", font=("", 9, "bold")).grid(
                row=next(row), column=0, sticky="w", padx=10)
            ttk.Button(frm, text="Show onboarding again", command=self._show_onboarding,
                      takefocus=0).grid(row=next(row), column=0, sticky="w", padx=10, pady=(4, 0))

        self._refresh_settings_rows()

    def _on_settings_inner_configure(self, event=None):
        """Size the settings canvas to its content, capped so the window
        never grows taller than a comfortable fraction of the screen."""
        inner_w = self._settings_inner.winfo_reqwidth()
        inner_h = self._settings_inner.winfo_reqheight()
        max_h = max(320, int(self.root.winfo_screenheight() * 0.55))
        self.settings_canvas.configure(width=inner_w,
                                       height=min(inner_h, max_h),
                                       scrollregion=(0, 0, inner_w, inner_h))

    def _on_settings_mousewheel(self, event):
        if self._current_tab_id() != "settings":
            return
        self.settings_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_close_behavior_change(self):
        self.cfg["close_behavior"] = self.close_behavior_var.get()
        save_config(self.cfg)

    def _refresh_settings_rows(self):
        for child in self.settings_list.winfo_children():
            child.destroy()

        last = len(self.cfg["tab_order"]) - 1
        for idx, tab_id in enumerate(self.cfg["tab_order"]):
            row = ttk.Frame(self.settings_list)
            row.grid(row=idx, column=0, sticky="ew", pady=2)

            visible_var = tk.BooleanVar(value=self.cfg["tab_visible"][tab_id])
            ttk.Checkbutton(row, variable=visible_var,
                            command=lambda t=tab_id, v=visible_var:
                                self._toggle_tab_visible(t, v),
                            takefocus=0).grid(row=0, column=0, padx=(0, 8))
            ttk.Label(row, text=self.TAB_LABELS[tab_id], width=22, anchor="w").grid(
                row=0, column=1, padx=(0, 8))
            ttk.Button(row, text="↑", width=2, takefocus=0,
                       state="normal" if idx > 0 else "disabled",
                       command=lambda t=tab_id: self._nudge_tab(t, -1)).grid(
                row=0, column=2, padx=(0, 2))
            ttk.Button(row, text="↓", width=2, takefocus=0,
                       state="normal" if idx < last else "disabled",
                       command=lambda t=tab_id: self._nudge_tab(t, 1)).grid(
                row=0, column=3)

    # ----- resize window to fit the current tab -----
    def _content_only_width(self):
        self.root.update_idletasks()
        frames = list(self.tab_frames.values()) + [self.settings_frame]
        return max(f.winfo_reqwidth() for f in frames)

    def _compute_fixed_width(self):
        bar_width = self.tab_bar_frame.winfo_reqwidth()
        self._fixed_width = max(self._content_only_width(), bar_width)

    def _resize_to_tab(self, frame=None):
        if frame is None:
            selected = self.notebook.select()
            if not selected:
                return
            frame = self.notebook.nametowidget(selected)
        frame.update_idletasks()
        self._compute_fixed_width()
        # Width is pinned to the widest tab/tab-bar row so the window never
        # changes width when switching tabs. Height is fixed to just this
        # pane's requested height (rather than Tk's default of the max
        # height across every pane), so the window still shrinks/grows
        # vertically to match whichever tab is showing.
        self.notebook.configure(width=self._fixed_width, height=frame.winfo_reqheight())
        self.root.update_idletasks()
        self.root.geometry("")  # let the toplevel re-fit itself to the new size
        self._update_background_image()

    def _on_tab_rows_change(self):
        self.cfg["tab_rows"] = self.tab_rows_var.get()
        save_config(self.cfg)
        self._rebuild_tab_bar()

    # ----- appearance: theme + background -----
    def _register_themed_widget(self, widget):
        """Plain tk widgets (Text/Listbox/Canvas) don't follow ttk styles."""
        self._themed_widgets.append(widget)
        return widget

    def _apply_theme(self):
        theme = self.cfg.get("theme", "light")
        if theme == "dark":
            pal = DARK_PALETTE
        elif theme == "custom":
            pal = build_custom_palette(self.cfg.get("custom_bg_color", "#202020"),
                                       self.cfg.get("custom_fg_color", "#e0e0e0"))
        else:
            pal = LIGHT_PALETTE
        self._theme_palette = pal

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=pal["bg"], foreground=pal["fg"],
                        fieldbackground=pal["field_bg"])
        for name in ("TFrame", "TLabel", "TCheckbutton", "TRadiobutton", "TNotebook"):
            style.configure(name, background=pal["bg"], foreground=pal["fg"])
        style.configure("TButton", background=pal["button_bg"], foreground=pal["fg"])
        style.map("TButton", background=[("active", pal["select_bg"])],
                 foreground=[("active", pal["select_fg"])])
        for name in ("TEntry", "TSpinbox", "TCombobox"):
            style.configure(name, fieldbackground=pal["field_bg"], foreground=pal["fg"],
                            background=pal["field_bg"])
        style.map("TCombobox", fieldbackground=[("readonly", pal["field_bg"])],
                  foreground=[("readonly", pal["fg"])])
        style.configure("TNotebook.Tab", background=pal["button_bg"], foreground=pal["fg"])
        style.map("TNotebook.Tab", background=[("selected", pal["select_bg"])],
                 foreground=[("selected", pal["select_fg"])])
        style.configure("TScale", background=pal["bg"], troughcolor=pal["field_bg"])
        style.configure("TProgressbar", background=pal["select_bg"],
                        troughcolor=pal["field_bg"])
        style.configure("TSeparator", background=pal["field_bg"])
        style.configure("TScrollbar", background=pal["button_bg"],
                        troughcolor=pal["field_bg"])

        self.root.configure(bg=pal["bg"])
        for widget in self._themed_widgets:
            try:
                widget.configure(bg=pal["field_bg"], fg=pal["fg"],
                                 insertbackground=pal["fg"],
                                 selectbackground=pal["select_bg"],
                                 selectforeground=pal["select_fg"])
            except tk.TclError:
                pass  # e.g. a Canvas doesn't take all of these options

        if getattr(self, "settings_canvas", None) is not None:
            self.settings_canvas.configure(bg=pal["bg"])

        is_dark = sum(_hex_to_rgb(pal["bg"])) / 3 < 128
        self._status_fg = STATUS_FG_DARK if is_dark else STATUS_FG_LIGHT
        self._retint_status_labels()

    def _fg(self, kind):
        """Theme-aware status text color: normal / muted / faint / error."""
        return self._status_fg[kind]

    def _retint_status_labels(self):
        """Re-map every status label's current color onto the new theme's
        equivalent (they're set imperatively, so styles can't cover them)."""
        stack = [self.root]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if isinstance(widget, ttk.Label):
                try:
                    kind = _STATUS_FG_BY_COLOR.get(str(widget.cget("foreground")))
                except tk.TclError:
                    continue
                if kind:
                    widget.configure(foreground=self._fg(kind))

    def _on_theme_change(self):
        self.cfg["theme"] = self.THEME_LABELS_REV[self.theme_var.get()]
        save_config(self.cfg)
        self._apply_theme()

    def _pick_custom_color(self, cfg_key, title):
        color = colorchooser.askcolor(color=self.cfg.get(cfg_key), title=title)
        if color[1] is None:
            return
        self.cfg[cfg_key] = color[1]
        save_config(self.cfg)
        if self.theme_var.get() == self.THEME_LABELS["custom"]:
            self._apply_theme()

    def _choose_background_image(self):
        path = filedialog.askopenfilename(
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.bmp"),
                      ("All files", "*.*")],
            title="Choose a background image")
        if not path:
            return
        try:
            self._bg_image_pil = Image.open(path).convert("RGB")
        except Exception as e:
            self.appearance_status.config(text=f"Failed to load image: {e}",
                                          foreground=self._fg("error"))
            return
        self.cfg["background_image_path"] = path
        save_config(self.cfg)
        self.background_label.config(text=os.path.basename(path))
        self._update_background_image()

    def _clear_background_image(self):
        self.cfg["background_image_path"] = None
        save_config(self.cfg)
        self._bg_image_pil = None
        self.background_label.config(text="None")
        self._update_background_image()

    def _apply_content_margins(self):
        """Widen the window margins while a background image is set - the
        notebook and tab frames are opaque, so the margins are the only
        place the image can actually show; a wider border makes the
        feature visible instead of a 12px sliver."""
        m = 28 if self._bg_image_pil is not None else 12
        self.tab_bar_frame.grid_configure(padx=m, pady=(m, 0))
        self.notebook.grid_configure(padx=m, pady=(6, m))

    def _update_background_image(self):
        if Image is None or ImageTk is None:
            return
        self._apply_content_margins()
        if self._bg_image_pil is None:
            if self.bg_label is not None:
                self.bg_label.place_forget()
            return
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if w < 2 or h < 2:
            return
        try:
            resized = self._bg_image_pil.resize((w, h))
        except Exception:
            return
        self._bg_photo = ImageTk.PhotoImage(resized)
        if self.bg_label is None:
            self.bg_label = tk.Label(self.root, borderwidth=0)
            self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)
            self.bg_label.lower()
        self.bg_label.configure(image=self._bg_photo)

    # ----- onboarding -----
    def _show_onboarding(self):
        win = tk.Toplevel(self.root)
        win.title("Welcome to Bendo")
        win.resizable(False, False)
        win.transient(self.root)
        pal = self._theme_palette
        win.configure(bg=pal["bg"])

        frm = ttk.Frame(win, padding=20)
        frm.grid()
        ttk.Label(frm, text="Welcome to Bendo", font=("", 12, "bold")).grid(
            row=0, column=0, sticky="w")
        ttk.Label(frm, justify="left", wraplength=380, text=
                 "Bendo is an all-in-one desktop toolbox. Internet Blocker & "
                 "Network, Shutdown Scheduler, Volume Mixer, Notes, and Power "
                 "are on by default. Turn on any extras you'd like below - "
                 "you can always change this later from Settings."
                 ).grid(row=1, column=0, sticky="w", pady=(8, 12))

        optional_ids = [t for t in self.TAB_LABELS if t not in CORE_TAB_IDS]
        self._onboarding_vars = {}
        extras_frame = ttk.Frame(frm)
        extras_frame.grid(row=2, column=0, sticky="w")
        for i, tab_id in enumerate(optional_ids):
            var = tk.BooleanVar(value=self.cfg["tab_visible"].get(tab_id, False))
            self._onboarding_vars[tab_id] = var
            ttk.Checkbutton(extras_frame, text=self.TAB_LABELS[tab_id], variable=var,
                            takefocus=0).grid(row=i // 2, column=i % 2, sticky="w",
                                              padx=(0, 16), pady=2)

        ttk.Button(frm, text="Get Started",
                  command=lambda: self._dismiss_onboarding(win), takefocus=0).grid(
            row=3, column=0, sticky="e", pady=(16, 0))

        win.protocol("WM_DELETE_WINDOW", lambda: self._dismiss_onboarding(win))
        win.grab_set()

    def _dismiss_onboarding(self, win):
        for tab_id, var in getattr(self, "_onboarding_vars", {}).items():
            self.cfg["tab_visible"][tab_id] = var.get()
        self.cfg["onboarding_shown"] = True
        save_config(self.cfg)
        self._rebuild_tab_bar()
        if hasattr(self, "settings_list"):
            self._refresh_settings_rows()
        win.destroy()
        self._maybe_auto_install_pillow()

    # ----- custom tab bar (native ttk.Notebook tabs are hidden) -----
    def _visible_tab_ids(self):
        return [t for t in self.cfg["tab_order"]
               if self.cfg["tab_visible"].get(t, True)] + ["settings"]

    def _tab_bar_positions(self, visible_ids):
        rows_setting = self.cfg.get("tab_rows", "Auto")
        if rows_setting == "Auto":
            return self._flow_wrap_positions(visible_ids)
        try:
            row_count = max(1, int(rows_setting))
        except ValueError:
            row_count = 1
        columns = -(-len(visible_ids) // row_count)  # ceil, divided evenly
        return [(i // columns, i % columns) for i in range(len(visible_ids))]

    def _rebuild_tab_bar(self):
        for widget in self.tab_bar_frame.winfo_children():
            widget.destroy()
        self.tab_buttons = {}

        visible_ids = self._visible_tab_ids()
        for tab_id, (r, c) in zip(visible_ids, self._tab_bar_positions(visible_ids)):
            label = "Settings" if tab_id == "settings" else self.TAB_LABELS[tab_id]
            btn = ttk.Button(self.tab_bar_frame, text=label, takefocus=0)
            btn.bind("<ButtonPress-1>", lambda e, t=tab_id: self._on_tab_press(t, e))
            btn.bind("<B1-Motion>", self._on_tab_drag_motion)
            btn.bind("<ButtonRelease-1>", self._on_tab_drag_release)
            btn.grid(row=r, column=c, sticky="ew", padx=1, pady=1)
            self.tab_buttons[tab_id] = btn

        current = self._current_tab_id()
        if current not in self.tab_buttons:
            current = visible_ids[0]
            frame = self.settings_frame if current == "settings" else self.tab_frames[current]
            self.notebook.select(frame)
        self._highlight_tab_button(current)
        self._resize_to_tab()

    def _flow_wrap_positions(self, tab_ids):
        """Auto mode: fill each row until the next button would overflow
        the content-driven width, matching how a browser wraps flowed text."""
        max_width = self._content_only_width()
        positions = []
        row = col = 0
        row_width = 0
        for tab_id in tab_ids:
            label = "Settings" if tab_id == "settings" else self.TAB_LABELS[tab_id]
            estimate = 14 + 8 * len(label)  # rough px estimate, refined by real content elsewhere
            if col > 0 and row_width + estimate > max_width:
                row += 1
                col = 0
                row_width = 0
            positions.append((row, col))
            col += 1
            row_width += estimate
        return positions

    def _current_tab_id(self):
        selected = self.notebook.select()
        if not selected:
            return None
        by_widget = {str(frame): tab_id for tab_id, frame in self.tab_frames.items()}
        by_widget[str(self.settings_frame)] = "settings"
        return by_widget.get(selected)

    def _highlight_tab_button(self, tab_id):
        for tid, btn in self.tab_buttons.items():
            btn.state(["pressed"] if tid == tab_id else ["!pressed"])

    def _select_tab_id(self, tab_id):
        frame = self.settings_frame if tab_id == "settings" else self.tab_frames.get(tab_id)
        if frame is None:
            return
        self.notebook.select(frame)
        self._highlight_tab_button(tab_id)
        self._resize_to_tab(frame)

    # ----- tab drag & drop -----
    # Press-and-drag any tab button, any time (no edit mode): once the
    # pointer moves past a small threshold a floating ghost of the tab
    # follows the cursor, and the bar reorders itself live as the ghost
    # crosses other tabs, so the result is always visible before dropping.
    # A short click (below the threshold) still just selects the tab.
    DRAG_THRESHOLD_PX = 8

    def _on_tab_press(self, tab_id, event):
        self._drag = {"tab_id": tab_id, "x": event.x_root, "y": event.y_root,
                      "active": False, "moved": False, "ghost": None}

    def _on_tab_drag_motion(self, event):
        d = self._drag
        if d is None or d["tab_id"] == "settings":  # settings stays last
            return
        if not d["active"]:
            if (abs(event.x_root - d["x"]) + abs(event.y_root - d["y"])
                    < self.DRAG_THRESHOLD_PX):
                return
            d["active"] = True
            d["ghost"] = self._make_drag_ghost(d["tab_id"])
        d["ghost"].geometry(f"+{event.x_root + 14}+{event.y_root + 12}")
        target = self._tab_at_pointer(event.x_root, event.y_root)
        if target is not None and target != d["tab_id"]:
            self._move_tab_in_order(d["tab_id"], target)
            d["moved"] = True

    def _on_tab_drag_release(self, event):
        d = self._drag
        self._drag = None
        if d is None:
            return
        if d["ghost"] is not None:
            d["ghost"].destroy()
        if not d["active"]:
            self._select_tab_id(d["tab_id"])  # plain click
            return
        if d["moved"]:
            save_config(self.cfg)
            self._refresh_settings_rows()
        self._select_tab_id(d["tab_id"])  # follow the tab to its new home

    def _make_drag_ghost(self, tab_id):
        ghost = tk.Toplevel(self.root)
        ghost.overrideredirect(True)
        try:
            ghost.attributes("-alpha", 0.85)
            ghost.attributes("-topmost", True)
        except tk.TclError:
            pass
        pal = self._theme_palette
        tk.Label(ghost, text=self.TAB_LABELS[tab_id], bg=pal["select_bg"],
                 fg=pal["select_fg"], padx=10, pady=4).pack()
        return ghost

    def _tab_at_pointer(self, x_root, y_root):
        for tab_id, btn in self.tab_buttons.items():
            bx, by = btn.winfo_rootx(), btn.winfo_rooty()
            if (bx <= x_root < bx + btn.winfo_width()
                    and by <= y_root < by + btn.winfo_height()):
                return tab_id
        return None

    def _move_tab_in_order(self, dragged, target):
        order = self.cfg["tab_order"]
        di = order.index(dragged)
        if target == "settings":
            # settings itself can't move, but dropping on it means
            # "put this tab at the end"
            if order[-1] == dragged:
                return
            order.pop(di)
            order.append(dragged)
        else:
            ti = order.index(target)
            order.pop(di)
            # take the target's slot: insert after it when moving right,
            # before it when moving left (plain insert-before can't move
            # a tab rightward at all)
            order.insert(order.index(target) + (1 if di < ti else 0), dragged)
        self._reflow_tab_buttons()

    def _reflow_tab_buttons(self):
        """Re-grid the existing buttons in the new order without destroying
        them - the pressed button must survive so the drag keeps its grab."""
        visible_ids = self._visible_tab_ids()
        for tab_id, (r, c) in zip(visible_ids, self._tab_bar_positions(visible_ids)):
            self.tab_buttons[tab_id].grid(row=r, column=c, sticky="ew",
                                          padx=1, pady=1)

    def _nudge_tab(self, tab_id, delta):
        """Arrow-button alternative to dragging, from the Settings list."""
        order = self.cfg["tab_order"]
        i = order.index(tab_id)
        j = i + delta
        if not 0 <= j < len(order):
            return
        order[i], order[j] = order[j], order[i]
        save_config(self.cfg)
        self._rebuild_tab_bar()
        self._refresh_settings_rows()

    def _apply_tab_order(self):
        self._rebuild_tab_bar()

    def _toggle_tab_visible(self, tab_id, var):
        self.cfg["tab_visible"][tab_id] = var.get()
        save_config(self.cfg)
        self._rebuild_tab_bar()
        if tab_id == "converter" and var.get():
            self._maybe_auto_install_pillow()

    def _reset_tab_settings(self):
        self.cfg["tab_order"] = self._known_tab_ids()
        self.cfg["tab_visible"] = {t: DEFAULT_CONFIG["tab_visible"][t]
                                   for t in self._known_tab_ids()}
        save_config(self.cfg)
        self._rebuild_tab_bar()
        self._refresh_settings_rows()

    def _add_time_box(self, parent, label, var, lo, hi, col):
        box = ttk.Frame(parent)
        box.grid(row=0, column=col, padx=6)
        ttk.Label(box, text=label).grid(row=0, column=0)
        ttk.Spinbox(box, from_=lo, to=hi, textvariable=var, width=5,
                    format="%02.0f", wrap=True).grid(row=1, column=0)

    # ----- status / control state -----
    def _update_status(self):
        if "internet" not in self.tab_frames or keyboard is None or self.blocking:
            return
        if self.cfg["armed"]:
            self.status.config(
                text=f"Armed. Press  {self.cfg['hotkey']}  to cut internet "
                     f"for {self.cfg['duration']}s.",
                foreground=self._fg("normal"),
            )
        else:
            self.status.config(text="Disarmed. Tick 'Armed' to enable.",
                               foreground=self._fg("faint"))

    def _refresh_controls(self):
        if "internet" not in self.tab_frames:
            return
        if self.blocking:
            self.trigger_btn.config(state="disabled")
            self.restore_btn.config(state="normal")
        else:
            self.trigger_btn.config(
                state="normal" if self.cfg["armed"] else "disabled")
            self.restore_btn.config(state="disabled")

    # ----- auto-saving setting changes -----
    def _on_duration_change(self, *_):
        try:
            dur = int(self.duration_var.get())
        except ValueError:
            return  # ignore partial/invalid typing
        if dur < 1:
            return
        self.cfg["duration"] = dur
        save_config(self.cfg)
        self._update_status()

    def _on_shutdown_fields_change(self, *_):
        try:
            days = int(self.days_var.get())
            hours = int(self.hours_var.get())
            minutes = int(self.minutes_var.get())
            seconds = int(self.seconds_var.get())
        except ValueError:
            return  # ignore partial/invalid typing
        self.cfg["shutdown_days"] = days
        self.cfg["shutdown_hours"] = hours
        self.cfg["shutdown_minutes"] = minutes
        self.cfg["shutdown_seconds"] = seconds
        save_config(self.cfg)

    def _toggle_shutdown_force(self):
        self.cfg["shutdown_force"] = self.shutdown_force_var.get()
        save_config(self.cfg)

    def _toggle_on_top(self):
        on = self.on_top_var.get()
        self.root.attributes("-topmost", on)
        self.cfg["on_top"] = on
        save_config(self.cfg)

    def _toggle_armed(self):
        armed = self.armed_var.get()
        self.cfg["armed"] = armed
        save_config(self.cfg)
        self._register_hotkey()
        if not armed and self.blocking:
            self.remaining = 0  # disarming cancels an active block and restores
        self._update_status()
        self._refresh_controls()

    def _apply_hotkey(self):
        self.cfg["hotkey"] = self.hotkey_var.get()
        save_config(self.cfg)
        self._register_hotkey()
        self._update_status()

    # ----- hotkey capture -----
    CAPTURE_TIMEOUT_MS = 15000

    def _capture_hotkey(self):
        if keyboard is None or self.capturing:
            return
        self.capturing = True
        self._capture_gens["main"] += 1
        gen = self._capture_gens["main"]
        self.capture_btn.config(state="disabled")
        self.status.config(text="Press the key combination...",
                           foreground=self._fg("error"))
        threading.Thread(
            target=lambda: self.events.put(
                ("hotkey_captured", (gen, keyboard.read_hotkey(suppress=False)))),
            daemon=True,
        ).start()
        self.root.after(self.CAPTURE_TIMEOUT_MS,
                        lambda: self._capture_timed_out("main", gen))

    def _capture_timed_out(self, flow, gen):
        """Give up on a capture nobody completed, so its Set button doesn't
        stay disabled forever. The reader thread stays blocked until the
        next keypress, but bumping the generation makes its result stale."""
        active = {"main": self.capturing, "mute": self.mute_capturing,
                  "clicker": self.clicker_capturing}[flow]
        if not active or self._capture_gens[flow] != gen:
            return
        self._capture_gens[flow] += 1
        if flow == "main":
            self.capturing = False
            self.capture_btn.config(state="normal")
            self.status.config(text="Hotkey capture timed out.",
                               foreground=self._fg("error"))
        elif flow == "mute":
            self.mute_capturing = False
            self.mute_capture_btn.config(state="normal")
            self.mixer_hotkey_status.config(text="Hotkey capture timed out.",
                                            foreground=self._fg("error"))
        else:
            self.clicker_capturing = False
            self.clicker_capture_btn.config(state="normal")
            self.clicker_status.config(text="Hotkey capture timed out.",
                                       foreground=self._fg("error"))

    # ----- registration (respects armed state) -----
    def _register_hotkey(self):
        if keyboard is None or "internet" not in self.tab_frames:
            return
        if self.hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.hotkey_handle)
            except Exception:
                pass
            self.hotkey_handle = None
        if not self.cfg["armed"]:
            return
        try:
            self.hotkey_handle = keyboard.add_hotkey(
                self.cfg["hotkey"], lambda: self.events.put(("trigger", None)))
        except Exception as e:
            self.status.config(text=f"Bad hotkey: {e}", foreground=self._fg("error"))

    # ----- actions -----
    def _trigger(self):
        self.events.put(("trigger", None))

    def _restore(self):
        self.remaining = 0  # tick loop finishes and restores

    # ----- blocking lifecycle -----
    def _start_block(self):
        if ("internet" not in self.tab_frames or self.blocking
                or not self.cfg["armed"]):
            return
        try:
            self.remaining = int(self.duration_var.get())
        except ValueError:
            self.remaining = self.cfg["duration"]
        self.blocking = True
        self._refresh_controls()
        threading.Thread(target=block_internet, daemon=True).start()
        self._tick()

    def _tick(self):
        if self.remaining > 0 and self.blocking:
            self.status.config(text=f"Internet OFF - {self.remaining}s remaining",
                               foreground=self._fg("error"))
            self.remaining -= 1
            self.root.after(1000, self._tick)
        else:
            self._end_block()

    def _end_block(self):
        threading.Thread(target=unblock_internet, daemon=True).start()
        self.blocking = False
        self._update_status()
        self._refresh_controls()

    # ----- shutdown scheduling -----
    def _shutdown_total_seconds(self):
        try:
            days = int(self.days_var.get())
            hours = int(self.hours_var.get())
            minutes = int(self.minutes_var.get())
            seconds = int(self.seconds_var.get())
        except ValueError:
            return None
        return days * 86400 + hours * 3600 + minutes * 60 + seconds

    def _schedule_shutdown(self):
        total = self._shutdown_total_seconds()
        if not total:
            self.shutdown_status.config(
                text="Set a delay greater than 0 before scheduling.",
                foreground=self._fg("error"))
            return
        action = self.SHUTDOWN_ACTION_LABELS_REV[self.shutdown_action_var.get()]
        if action in SHUTDOWN_ACTION_FLAGS:
            result = schedule_power_action(action, total, self.shutdown_force_var.get())
            if result.returncode != 0:
                self.shutdown_status.config(
                    text=f"Failed to schedule: {result.stderr.strip()}",
                    foreground=self._fg("error"))
                return
            self._shutdown_os_managed = True
        else:  # hibernate: no OS-native delay flag, so we time it ourselves
            self._shutdown_os_managed = False
        # Snapshot the action: the combobox can change during the countdown,
        # and the countdown must keep acting on what was actually scheduled.
        self._scheduled_action = action
        self.shutdown_target = time.time() + total
        self._shutdown_notified = False
        self.schedule_btn.config(state="disabled")
        self.cancel_shutdown_btn.config(state="normal")
        self._tick_shutdown()

    def _cancel_shutdown(self):
        if self._shutdown_os_managed:
            cancel_shutdown()
        self.shutdown_target = None
        self._scheduled_action = None
        self._shutdown_notified = False
        self.schedule_btn.config(state="normal")
        self.cancel_shutdown_btn.config(state="disabled")
        self.shutdown_status.config(text="Cancelled.", foreground=self._fg("normal"))

    def _tick_shutdown(self):
        if self.shutdown_target is None or self._scheduled_action is None:
            return
        action = self._scheduled_action
        label = self.SHUTDOWN_ACTION_LABELS[action]
        remaining = int(round(self.shutdown_target - time.time()))
        if remaining <= 0:
            gerund = {"shutdown": "Shutting down", "restart": "Restarting",
                     "hibernate": "Hibernating"}[action]
            self.shutdown_status.config(text=f"{gerund}...", foreground=self._fg("error"))
            if action == "hibernate":
                hibernate_now()
                self.shutdown_target = None
                self._scheduled_action = None
                self.schedule_btn.config(state="normal")
                self.cancel_shutdown_btn.config(state="disabled")
            else:
                # The OS timer ends the session now; if we're still running
                # a few seconds later, it was cancelled outside Bendo (e.g.
                # "shutdown /a" in a terminal) - unstick the UI.
                self.root.after(5000, self._check_shutdown_happened)
            return
        if remaining <= 60 and not self._shutdown_notified:
            self._shutdown_notified = True
            self._notify(f"{label} in {remaining}s.")
        self.shutdown_status.config(
            text=f"{label} scheduled - {format_hms(remaining)} remaining",
            foreground=self._fg("error"))
        self.root.after(1000, self._tick_shutdown)

    def _check_shutdown_happened(self):
        if self.shutdown_target is None or time.time() < self.shutdown_target:
            return  # already cancelled/rescheduled from within Bendo
        self.shutdown_target = None
        self._scheduled_action = None
        self.schedule_btn.config(state="normal")
        self.cancel_shutdown_btn.config(state="disabled")
        self.shutdown_status.config(
            text="The scheduled action didn't run - it may have been "
                 "cancelled outside Bendo.", foreground=self._fg("error"))

    # ----- volume mixer -----
    def _sync_master_volume(self):
        try:
            endpoint = get_master_endpoint()
            self.master_vol_var.set(round(endpoint.GetMasterVolumeLevelScalar() * 100))
            self.master_mute_var.set(bool(endpoint.GetMute()))
        except Exception:
            pass

    def _on_master_volume_change(self, value):
        try:
            get_master_endpoint().SetMasterVolumeLevelScalar(float(value) / 100, None)
        except Exception:
            pass

    def _on_master_mute_toggle(self):
        try:
            get_master_endpoint().SetMute(self.master_mute_var.get(), None)
        except Exception:
            pass

    def _refresh_mixer_sessions(self):
        try:
            grouped = get_audio_sessions()
        except Exception:
            return

        filter_text = self.mixer_filter_var.get().strip().lower()
        if filter_text:
            grouped = {pid: info for pid, info in grouped.items()
                      if filter_text in info["name"].lower()}

        for row_index, (pid, info) in enumerate(
                sorted(grouped.items(), key=lambda kv: kv[1]["name"].lower())):
            if pid in self.mixer_rows:
                row = self.mixer_rows[pid]
                row["sessions"] = info["sessions"]
            else:
                row = self._add_mixer_row(info["name"], info["sessions"])
                self.mixer_rows[pid] = row
            row["frame"].grid(row=row_index, column=0, sticky="ew", pady=2)

        for pid in list(self.mixer_rows):
            if pid not in grouped:
                self.mixer_rows[pid]["frame"].destroy()
                del self.mixer_rows[pid]

        # The app list's height changes as apps open/close; keep the window
        # sized to match, but only while this tab is the one actually shown.
        if self.notebook.select() == str(self.tab_frames.get("mixer")):
            self._resize_to_tab()

    def _add_mixer_row(self, name, sessions):
        frame = ttk.Frame(self.mixer_list)
        ttk.Label(frame, text=name, width=22, anchor="w").grid(
            row=0, column=0, padx=(0, 8))

        vol_var = tk.DoubleVar(value=round(sessions[0].GetMasterVolume() * 100))
        mute_var = tk.BooleanVar(value=bool(sessions[0].GetMute()))
        row = {"frame": frame, "vol_var": vol_var, "mute_var": mute_var,
               "sessions": sessions}

        ttk.Scale(frame, from_=0, to=100, orient="horizontal", length=180,
                  variable=vol_var,
                  command=lambda v, r=row: self._on_app_volume_change(r, v),
                  takefocus=0).grid(row=0, column=1, padx=(0, 8))
        ttk.Checkbutton(frame, text="Mute", variable=mute_var,
                        command=lambda r=row: self._on_app_mute_toggle(r),
                        takefocus=0).grid(row=0, column=2)
        return row

    def _on_app_volume_change(self, row, value):
        for session in row["sessions"]:
            try:
                session.SetMasterVolume(float(value) / 100, None)
            except Exception:
                pass

    def _on_app_mute_toggle(self, row):
        for session in row["sessions"]:
            try:
                session.SetMute(row["mute_var"].get(), None)
            except Exception:
                pass

    def _tick_mixer(self):
        self._refresh_mixer_sessions()
        self.root.after(2000, self._tick_mixer)

    # ----- master-mute hotkey -----
    def _capture_mute_hotkey(self):
        if keyboard is None or self.mute_capturing:
            return
        self.mute_capturing = True
        self._capture_gens["mute"] += 1
        gen = self._capture_gens["mute"]
        self.mute_capture_btn.config(state="disabled")
        self.mixer_hotkey_status.config(text="Press the key combination...",
                                        foreground=self._fg("error"))
        threading.Thread(
            target=lambda: self.events.put(
                ("mute_hotkey_captured",
                 (gen, keyboard.read_hotkey(suppress=False)))),
            daemon=True,
        ).start()
        self.root.after(self.CAPTURE_TIMEOUT_MS,
                        lambda: self._capture_timed_out("mute", gen))

    def _apply_mute_hotkey(self):
        self.cfg["mute_hotkey"] = self.mute_hotkey_var.get()
        save_config(self.cfg)
        self._register_mute_hotkey()

    def _toggle_mute_hotkey_armed(self):
        self.cfg["mute_hotkey_armed"] = self.mute_hotkey_armed_var.get()
        save_config(self.cfg)
        self._register_mute_hotkey()

    def _register_mute_hotkey(self):
        if keyboard is None or AudioUtilities is None:
            return
        if self.mute_hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.mute_hotkey_handle)
            except Exception:
                pass
            self.mute_hotkey_handle = None
        if not self.cfg["mute_hotkey_armed"]:
            return
        try:
            self.mute_hotkey_handle = keyboard.add_hotkey(
                self.cfg["mute_hotkey"], lambda: self.events.put(("toggle_mute", None)))
        except Exception as e:
            self.mixer_hotkey_status.config(text=f"Bad hotkey: {e}", foreground=self._fg("error"))

    def _toggle_master_mute_via_hotkey(self):
        if AudioUtilities is None or not hasattr(self, "master_mute_var"):
            return
        self.master_mute_var.set(not self.master_mute_var.get())
        self._on_master_mute_toggle()

    # ----- click-to-defocus -----
    # Widgets a user can type or drag into keep normal click behavior; a
    # click anywhere else (frames, labels, separators, blank tab space)
    # moves focus off whatever text box/spinbox currently has it.
    _FOCUSABLE_CLASSES = {"TEntry", "TSpinbox", "TCombobox", "Text", "Listbox",
                          "TButton", "TCheckbutton", "TRadiobutton", "TScale",
                          "TNotebook"}

    def _on_click_anywhere(self, event):
        widget = event.widget
        if widget.winfo_class() in self._FOCUSABLE_CLASSES:
            return
        widget.focus_set()

    # ----- system tray -----
    def _build_tray_icon(self):
        if pystray is None or Image is None:
            self.tray_icon = None
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show Bendo", self._tray_show, default=True),
            pystray.MenuItem("Trigger Internet Block", self._tray_trigger_block),
            pystray.MenuItem("Cancel Shutdown", self._tray_cancel_shutdown),
            pystray.MenuItem("Toggle Master Mute", self._tray_toggle_mute),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Bendo", self._tray_quit),
        )
        self.tray_icon = pystray.Icon(APP_NAME, build_tray_image(), APP_NAME, menu)
        self.tray_icon.run_detached()

    # pystray invokes these on its own thread, so just hand off to the
    # cross-thread event queue like the hotkey callbacks already do.
    def _tray_show(self, icon, item):
        self.events.put(("tray_show", None))

    def _tray_trigger_block(self, icon, item):
        self.events.put(("trigger", None))

    def _tray_cancel_shutdown(self, icon, item):
        self.events.put(("tray_cancel_shutdown", None))

    def _tray_toggle_mute(self, icon, item):
        self.events.put(("toggle_mute", None))

    def _tray_quit(self, icon, item):
        self.events.put(("tray_quit", None))

    def _notify(self, message, title=APP_NAME):
        if self.tray_icon is not None:
            try:
                self.tray_icon.notify(message, title)
            except Exception:
                pass

    # ----- cross-thread event pump (runs on main thread) -----
    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "trigger" and self.cfg["armed"]:
                    self._start_block()
                elif kind == "hotkey_captured":
                    gen, hotkey = payload
                    if gen == self._capture_gens["main"]:
                        self.capturing = False
                        self.capture_btn.config(state="normal")
                        if hotkey:
                            self.hotkey_var.set(hotkey)
                            self._apply_hotkey()
                        else:
                            self._update_status()
                elif kind == "mute_hotkey_captured":
                    gen, hotkey = payload
                    if gen == self._capture_gens["mute"]:
                        self.mute_capturing = False
                        self.mute_capture_btn.config(state="normal")
                        if hotkey:
                            self.mute_hotkey_var.set(hotkey)
                            self._apply_mute_hotkey()
                        self.mixer_hotkey_status.config(
                            text="", foreground=self._fg("normal"))
                elif kind == "toggle_mute":
                    self._toggle_master_mute_via_hotkey()
                elif kind == "tray_show":
                    self.root.deiconify()
                    self.root.lift()
                    self.root.focus_force()
                elif kind == "tray_cancel_shutdown":
                    self._cancel_shutdown()
                elif kind == "tray_quit":
                    self._quit_app()
                    return
                elif kind == "ping_result":
                    self._handle_ping_result(*payload)
                elif kind == "speedtest_result":
                    self._handle_speedtest_result(*payload)
                elif kind == "media_update":
                    self._handle_media_update(payload)
                elif kind == "converter_progress":
                    self._handle_converter_progress(*payload)
                elif kind == "pillow_install_done":
                    self._handle_pillow_install_done(payload)
                elif kind == "converter_done":
                    self._handle_converter_done(payload)
                elif kind == "clicker_hotkey_captured":
                    gen, hotkey = payload
                    if gen == self._capture_gens["clicker"]:
                        self.clicker_capturing = False
                        self.clicker_capture_btn.config(state="normal")
                        if hotkey:
                            self.clicker_hotkey_var.set(hotkey)
                            self._apply_clicker_hotkey()
                        self.clicker_status.config(
                            text="Running" if self.clicker_running else "Stopped.",
                            foreground=self._fg("normal"))
                elif kind == "toggle_clicker":
                    self._toggle_clicker()
                elif kind == "clicker_tick":
                    if self.clicker_running:
                        self.clicker_status.config(text=f"Running - {payload} clicks",
                                                   foreground=self._fg("error"))
                elif kind == "clicker_done":
                    self._stop_clicker()
                    self.clicker_status.config(text="Reached click limit.",
                                               foreground=self._fg("normal"))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _on_close(self):
        if self.tray_icon is not None and self.cfg.get("close_behavior", "tray") == "tray":
            self.root.withdraw()  # minimize to tray instead of exiting
        else:
            self._quit_app()

    def _quit_app(self):
        unblock_internet()  # never leave the internet blocked on exit
        # Note: a scheduled shutdown is left running - it's an OS-level timer,
        # independent of this app, matching how Windows' own shutdown /t works.
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()


def main():
    if os.name != "nt":
        print("This tool is Windows-only.")
        sys.exit(1)
    if not is_admin():
        if not relaunch_as_admin():
            ctypes.windll.user32.MessageBoxW(
                None,
                "Bendo needs administrator rights (for firewall and shutdown "
                "control) and cannot start without them.",
                APP_NAME, 0x10)  # MB_ICONERROR
        sys.exit(0)
    # Single-instance guard: two copies would fight over the global hotkeys
    # and share the same firewall rule name (quitting one would delete the
    # other's active block). The handle stays open for the process lifetime;
    # Windows cleans it up on exit.
    ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\Bendo_SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(
            None, "Bendo is already running - check the system tray.",
            APP_NAME, 0x40)  # MB_ICONINFORMATION
        sys.exit(0)
    try:
        # Ties the running process to a distinct app identity instead of
        # being lumped in with python.exe/pythonw.exe - without this,
        # pinning the window to the taskbar can show a blank/generic icon.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Bendo.FocusTool")
    except OSError:
        pass
    root = tk.Tk()
    BendoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
