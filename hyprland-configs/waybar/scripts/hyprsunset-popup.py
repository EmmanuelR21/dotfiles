#!/usr/bin/env python3
"""Brightness + night light popup for the Waybar hyprsunset module.

Click to open, click again to close (see popup_common.py).

Brightness, first available backend wins (so one config fits laptop and PC):
  1. A backlight (laptop): the real panel backlight via brightnessctl, using
     the same curve as hypr/scripts/osd.sh (-e4 -n2).
  2. DDC/CI monitors (desktop, needs ddcutil): the monitors' own brightness.
     One slider drives all of them. ddcutil is slow (~0.3s per call), so it
     runs in a background thread that only ever sends the latest value.
  3. Neither: software dimming through hyprsunset's gamma.

Night light: hyprsunset color temperature, adjusted live over its IPC socket.

Battery: hyprsunset only runs while it's doing something (night light on, or
software dimming below 100%); otherwise it's stopped so the compositor has no
color transform to apply. The popup itself polls nothing but the backlight
sysfs file, and only while it's open (ddcutil is only called on open and on
slider changes).

Requires: hyprsunset; brightnessctl (laptop) or ddcutil (desktop) for
hardware brightness.
"""
import json
import os
import shutil
import socket
import subprocess
import threading
import time

from popup_common import RUNTIME, GLib, Gtk, Popup, label, run, set_class

# The panel's right edge sits CURSOR_OFFSET px right of the mouse at click time
CURSOR_OFFSET = 24
FALLBACK_MARGIN_RIGHT = 250

# Picks up brightness-key changes while open (sysfs read, no subprocess)
POLL_MS = 2000

# Night light strength 0..100 maps linearly onto these color temperatures.
# 1000K is the warmest hyprsunset accepts.
TEMP_WEAK, TEMP_STRONG = 6500, 1000
DEFAULT_STRENGTH = 44  # ~4100K
SOFT_MIN = 20  # lowest software brightness, so the screen can't go black

ICON_BRIGHT = ("\U000f00de", "\U000f00df", "\U000f00e0")  # low, mid, high
ICON_NIGHT = "\U000f0594"
ICON_TEMP = "\U000f050f"

# Detected DDC buses; the runtime dir is cleared on reboot, when bus numbers may change
DDC_CACHE = os.path.join(RUNTIME, "waybar-ddc-buses.json")
_HIS = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
SOCK = os.path.join(RUNTIME, "hypr", _HIS or "", ".hyprsunset.sock")
STATE_FILE = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
                          "waybar-hyprsunset.json")

CSS = """
#panel { padding: 12px 14px; min-width: 300px; }

.icon { font-size: 17px; color: #fabd2f; min-width: 22px; }
.name { min-width: 76px; }
.val  { color: #e6e6e6; font-size: 12px; min-width: 44px; }
.sub  { font-size: 11px; font-weight: normal; color: #8a8f98; }

separator { background-color: #333333; min-height: 1px; }

scale { min-width: 140px; padding: 0 6px; }
scale trough {
    min-height: 4px;
    border-radius: 2px;
    border: none;
    background-color: #333333;
}
scale highlight {
    border-radius: 2px;
    border: none;
    background-image: none;
    background-color: #fabd2f;
}
scale slider {
    min-width: 12px;
    min-height: 12px;
    margin: -4px;
    border-radius: 6px;
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: #ffffff;
}

button {
    min-width: 58px;
    padding: 3px 0;
    border-radius: 4px;
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: #2a2a2a;
    transition: background-color 150ms ease-out;
}
button label { font-size: 11px; color: #cfcfcf; }
button:hover { background-color: #333333; }

/* Night light on: amber button; off: dimmed icon and strength row */
.night.on button { background-color: rgba(250, 189, 47, 0.18); }
.night.on button:hover { background-color: rgba(250, 189, 47, 0.28); }
.night.on button label { color: #fabd2f; }
.night.off .icon { color: #6f747d; }
.night.off .name, .night.off .val { color: #7a7a7a; }
.night.off scale highlight { background-color: #555a62; }
.night.off scale slider { background-color: #9a9fa8; }
"""


# ---------------------------------------------------------------- helpers

def strength_to_temp(s):
    return round(TEMP_WEAK - (TEMP_WEAK - TEMP_STRONG) * s / 100)


def temp_to_strength(t):
    s = (TEMP_WEAK - t) * 100 / (TEMP_WEAK - TEMP_STRONG)
    return int(min(100, max(0, round(s))))


def load_state():
    try:
        with open(STATE_FILE) as f:
            return int(json.load(f).get("strength", DEFAULT_STRENGTH))
    except (OSError, ValueError, TypeError, AttributeError):
        return DEFAULT_STRENGTH


def save_state(strength):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump({"strength": strength}, f)
    except OSError:
        pass


# ---------------------------------------------------------------- backends

def ipc(cmd):
    """Send one command to the running hyprsunset; None if it isn't running."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(SOCK)
            s.sendall(cmd.encode())
            return s.recv(1024).decode().strip()
    except OSError:
        return None


class Hyprsunset:
    """Night light + software gamma, starting/stopping the daemon on demand."""

    def __init__(self):
        self.strength = load_state()
        self.night = False
        self.gamma = 100
        ident = ipc("identity get")
        self.running = ident is not None
        if self.running:
            self.night = ident == "false"
            try:
                if self.night:
                    self.strength = temp_to_strength(int(ipc("temperature")))
                self.gamma = round(float(ipc("gamma")))
            except (TypeError, ValueError):
                pass

    @property
    def temp(self):
        return strength_to_temp(self.strength)

    def apply(self):
        if not (self.night or self.gamma < 100):
            if self.running:
                # Exiting drops hyprsunset's color transform entirely
                subprocess.run(["pkill", "-x", "hyprsunset"], check=False)
                self.running = False
            return
        if self.running and ipc(f"gamma {self.gamma}") is not None:
            ipc(f"temperature {self.temp}" if self.night else "identity")
            return
        self._start()

    def _start(self):
        args = ["-t", str(self.temp)] if self.night else ["-i"]
        if self.gamma < 100:
            args += ["-g", str(self.gamma)]
        subprocess.Popen(["hyprsunset", *args], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        # Wait for its socket so the next slider step goes over IPC instead of
        # launching a second instance (usually ready within a few ms)
        for _ in range(50):
            if ipc("identity get") is not None:
                break
            time.sleep(0.02)
        self.running = True


class Backlight:
    """Hardware backlight; same percentage curve as brightnessctl -e4."""

    def __init__(self, name):
        self.name = name
        self.path = f"/sys/class/backlight/{name}"
        with open(f"{self.path}/max_brightness") as f:
            self.max = max(1, int(f.read()))

    def get(self):
        try:
            with open(f"{self.path}/brightness") as f:
                cur = int(f.read())
        except (OSError, ValueError):
            return 100
        return round(100 * (cur / self.max) ** 0.25)

    def set(self, pct):
        try:
            subprocess.run(["brightnessctl", "-q", "-d", self.name, "-e4", "-n2", "set", f"{pct}%"],
                           timeout=2, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass


def find_backlight():
    try:
        names = sorted(os.listdir("/sys/class/backlight"))
        return Backlight(names[0]) if names else None
    except (OSError, ValueError):
        return None


def ddcutil(*args, timeout=5):
    try:
        r = subprocess.run(["ddcutil", *args], capture_output=True, text=True, timeout=timeout,
                           check=False)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


class DDC:
    """External monitors over DDC/CI. All ddcutil calls happen on a worker
    thread: it finds the monitors and reads the level (reported back through
    on_ready(pct or None), on the GTK thread), then applies set() requests.
    Requests that arrive while a call is running are collapsed to the newest.
    """

    def __init__(self, on_ready):
        self.on_ready = on_ready
        self.buses = []
        self.cond = threading.Condition()
        self.want = None
        self.closing = False
        # Not a daemon thread: the last value still gets sent after the popup closes
        self.thread = threading.Thread(target=self._worker)
        self.thread.start()

    def set(self, pct):
        with self.cond:
            self.want = pct
            self.cond.notify()

    def close(self):
        with self.cond:
            self.closing = True
            self.cond.notify()
        self.thread.join(timeout=10)

    @staticmethod
    def _read(bus):
        out = ddcutil("getvcp", "10", "--bus", bus, "--brief")  # "VCP 10 C <cur> <max>"
        try:
            parts = out.split()
            return round(int(parts[3]) * 100 / max(1, int(parts[4])))
        except (AttributeError, IndexError, ValueError):
            return None

    @staticmethod
    def _detect():
        out = ddcutil("detect", "--brief", timeout=15) or ""
        buses, valid = [], False
        for line in out.splitlines():
            if not line.startswith(" "):
                valid = line.startswith("Display ")  # skips "Invalid display" blocks
            elif valid and "/dev/i2c-" in line:
                buses.append(line.rsplit("/dev/i2c-", 1)[1].strip())
        try:
            with open(DDC_CACHE, "w") as f:
                json.dump(buses, f)
        except OSError:
            pass
        return buses

    def _init(self):
        try:
            with open(DDC_CACHE) as f:
                buses = [str(b) for b in json.load(f)]
        except (OSError, ValueError, TypeError):
            buses = []
        pct = self._read(buses[0]) if buses else None
        if pct is None:  # no cache, or a monitor changed: detect again
            buses = self._detect()
            pct = self._read(buses[0]) if buses else None
        self.buses = buses if pct is not None else []
        return pct

    def _worker(self):
        pct = self._init()
        GLib.idle_add(self.on_ready, pct)
        if not self.buses:
            return
        while True:
            with self.cond:
                while self.want is None and not self.closing:
                    self.cond.wait()
                pct, self.want = self.want, None
            if pct is None:  # closing with nothing left to send
                return
            for bus in self.buses:
                ddcutil("setvcp", "10", str(pct), "--bus", bus, "--noverify")


# ---------------------------------------------------------------- widgets

class SliderRow(Gtk.Box):
    """icon | name | slider | value. Drag events are coalesced (~40ms)."""

    def __init__(self, icon, name, lo, hi, fmt, on_change, icon_fn=None):
        super().__init__(spacing=8)
        self.fmt, self.on_change, self.icon_fn = fmt, on_change, icon_fn
        self.updating = False
        self.dragging = False
        self.pending = None

        self.icon = label(icon, "icon")
        self.name = label(name, "name")
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.connect("value-changed", self.on_slide)
        self.scale.connect("button-press-event", lambda *_: self._set_drag(True))
        self.scale.connect("button-release-event", lambda *_: self._set_drag(False))
        self.value = label("", "val", xalign=1)

        for w in (self.icon, self.name, self.scale, self.value):
            self.pack_start(w, w is self.scale, w is self.scale, 0)

    def _set_drag(self, state):
        self.dragging = state
        return False

    def _show(self, v):
        self.value.set_text(self.fmt(v))
        if self.icon_fn:
            self.icon.set_text(self.icon_fn(v))

    def set(self, v):
        if self.dragging:
            return
        self.updating = True
        self.scale.set_value(v)
        self.updating = False
        self._show(v)

    def on_slide(self, scale):
        if self.updating:
            return
        self._show(int(scale.get_value()))
        if self.pending is None:
            self.pending = GLib.timeout_add(40, self._apply)

    def _apply(self):
        self.pending = None
        self.on_change(int(self.scale.get_value()))
        return False

    def flush(self):
        """Apply a still-pending drag value right away (used on close)."""
        if self.pending is not None:
            GLib.source_remove(self.pending)
            self._apply()


class HyprsunsetPopup(Popup):
    NAME = "hyprsunset"

    def __init__(self):
        super().__init__(spacing=10, cursor_offset=CURSOR_OFFSET,
                         fallback_margin=FALLBACK_MARGIN_RIGHT)
        self.sunset = Hyprsunset()
        self.backlight = find_backlight()
        self.ddc = None

        # Brightness
        self.bright = SliderRow(
            ICON_BRIGHT[2], "Brightness", 1, 100,
            lambda v: f"{v}%", self.on_brightness,
            icon_fn=lambda v: ICON_BRIGHT[0 if v < 34 else 1 if v < 67 else 2])
        if self.backlight:
            self.bright.set(self.backlight.get())
        elif shutil.which("ddcutil"):
            # Show the panel now; the slider fills in once the monitor answers
            self.bright.scale.set_range(0, 100)
            self.bright.set_sensitive(False)
            self.bright.value.set_text("…")
            self.ddc = DDC(self.on_ddc_ready)
        else:
            self.use_software_dimming()
        self.panel.pack_start(self.bright, False, False, 0)

        self.panel.pack_start(Gtk.Separator(), False, False, 0)

        # Night light
        self.night_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.night_box.get_style_context().add_class("night")

        head = Gtk.Box(spacing=8)
        head.pack_start(label(ICON_NIGHT, "icon"), False, False, 0)
        head.pack_start(label("Night light", "name"), False, False, 0)
        self.state = label("", "sub")
        head.pack_start(self.state, True, True, 0)
        self.toggle = Gtk.Button()
        self.toggle.connect("clicked", self.on_toggle)
        head.pack_start(self.toggle, False, False, 0)
        self.night_box.pack_start(head, False, False, 0)

        self.strength = SliderRow(ICON_TEMP, "Strength", 0, 100,
                                  lambda v: f"{strength_to_temp(v)}K", self.on_strength)
        self.strength.set(self.sunset.strength)
        self.night_box.pack_start(self.strength, False, False, 0)
        self.panel.pack_start(self.night_box, False, False, 0)
        self.refresh_night()

        if self.backlight:
            GLib.timeout_add(POLL_MS, self.poll)

    def refresh_night(self):
        on = self.sunset.night
        self.toggle.set_label("Turn off" if on else "Turn on")
        self.state.set_text(f"{self.sunset.temp}K" if on else "Off")
        set_class(self.night_box, "on", on)
        set_class(self.night_box, "off", not on)

    def use_software_dimming(self):
        self.bright.scale.set_range(SOFT_MIN, 100)
        self.bright.set(self.sunset.gamma)
        self.bright.set_tooltip_text("Software dimming (no hardware brightness control found)")

    def on_ddc_ready(self, pct):
        if pct is None:
            self.ddc = None
            self.use_software_dimming()
        else:
            self.bright.set(pct)
        self.bright.set_sensitive(True)
        return False

    def on_brightness(self, v):
        if self.backlight:
            self.backlight.set(v)
        elif self.ddc:
            self.ddc.set(v)
        else:
            self.sunset.gamma = v
            self.sunset.apply()

    def on_toggle(self, _button):
        self.sunset.night = not self.sunset.night
        self.sunset.apply()
        self.refresh_night()

    def on_strength(self, v):
        # While off this just presets the strength for the next "Turn on"
        self.sunset.strength = v
        if self.sunset.night:
            self.state.set_text(f"{self.sunset.temp}K")
            self.sunset.apply()

    def poll(self):
        self.bright.set(self.backlight.get())
        return True

    def cleanup(self):
        self.bright.flush()
        self.strength.flush()
        save_state(self.sunset.strength)
        if self.ddc:
            self.ddc.close()  # waits for the last brightness value to be sent


if __name__ == "__main__":
    run(HyprsunsetPopup, CSS)
