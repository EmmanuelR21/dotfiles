#!/usr/bin/env python3
"""Speaker/mic popup for the Waybar audio module.

Running it opens the popup; running it again while it's open closes it, so it
works directly as a Waybar "on-click" command. Volume and mute go through
wpctl (WirePlumber), the same tool the bar already uses.

Requires: python-gobject (gtk3 and gtk-layer-shell are already Waybar deps).
"""
import os
import signal
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, Gtk, Gdk, GtkLayerShell  # noqa: E402

# Position, measured from the screen's top-right corner (logical pixels).
# TOP = bar margin (6) + bar height (30) + 4px gap.
# RIGHT = distance to the audio module's right edge: bar margin (6) +
# power (~34) + network (~38) + 6px spacing each. The battery module only shows
# on machines with a battery, so its width is added when one exists.
# Fine-tune these if the panel doesn't line up exactly under the module.
MARGIN_TOP = 40
MARGIN_RIGHT = 90
BATTERY_WIDTH = 76  # battery module (~70) + spacing (6)


def has_battery():
    try:
        return any(n.startswith("BAT") for n in os.listdir("/sys/class/power_supply"))
    except OSError:
        return False

POLL_MS = 1000  # how often to pick up volume changes made elsewhere

ICONS = {
    "sink": ("\U000f057e", "\U000f0581"),    # speaker, speaker-off
    "source": ("\U000f036c", "\U000f036d"),  # mic, mic-off
}
TARGETS = {"sink": "@DEFAULT_AUDIO_SINK@", "source": "@DEFAULT_AUDIO_SOURCE@"}

PID_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "waybar-audio-popup.pid")

CSS = b"""
* {
    font-family: "FreeSans", "Symbols Nerd Font";
    font-weight: bold;
    font-size: 13px;
    color: #ffffff;
}
window, #catcher { background-color: transparent; }

#panel {
    background-color: #1e1e1e;
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 5px;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.07);
    padding: 10px 14px;
}

.icon  { font-size: 17px; color: #d6dde9; min-width: 22px; }
.name  { min-width: 58px; }
.pct   { color: #e6e6e6; font-size: 12px; min-width: 36px; }

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
    background-color: #d6dde9;
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

/* Muted row: dusty-red icon (matches the bar), dimmed level, and the
   button turns into a red-tinted "Unmute" */
.muted .icon { color: #ea6a5f; }
.muted .name { color: #9499a2; }
.muted .pct { color: #7a7a7a; }
.muted scale highlight { background-color: #555a62; }
.muted button { background-color: rgba(234, 106, 95, 0.18); }
.muted button:hover { background-color: rgba(234, 106, 95, 0.28); }
.muted button label { color: #ea6a5f; }
"""


def wpctl(*args):
    try:
        return subprocess.run(["wpctl", *args], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def read_state(kind):
    """Return (volume 0-100, muted) for the default sink/source."""
    out = wpctl("get-volume", TARGETS[kind])  # e.g. "Volume: 0.75 [MUTED]"
    try:
        vol = round(float(out.split()[1]) * 100)
    except (IndexError, ValueError):
        vol = 0
    return min(vol, 100), "[MUTED]" in out


class Row(Gtk.Box):
    def __init__(self, kind, label):
        super().__init__(spacing=8)
        self.kind = kind
        self.updating = False   # set while we move the slider ourselves
        self.dragging = False
        self.pending = None

        self.icon = Gtk.Label(xalign=0)
        self.icon.get_style_context().add_class("icon")
        name = Gtk.Label(label=label, xalign=0)
        name.get_style_context().add_class("name")

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.connect("value-changed", self.on_slide)
        self.scale.connect("button-press-event", lambda *_: self._set_drag(True))
        self.scale.connect("button-release-event", lambda *_: self._set_drag(False))

        self.pct = Gtk.Label(xalign=1)
        self.pct.get_style_context().add_class("pct")

        self.button = Gtk.Button()
        self.button.connect("clicked", self.on_mute)

        for w in (self.icon, name, self.scale, self.pct, self.button):
            self.pack_start(w, w is self.scale, w is self.scale, 0)
        self.refresh()

    def _set_drag(self, state):
        self.dragging = state
        return False

    def refresh(self):
        if self.dragging:
            return
        vol, muted = read_state(self.kind)
        self.updating = True
        self.scale.set_value(vol)
        self.updating = False
        self.pct.set_text(f"{vol}%")
        self.icon.set_text(ICONS[self.kind][1 if muted else 0])
        self.button.set_label("Unmute" if muted else "Mute")
        ctx = self.get_style_context()
        (ctx.add_class if muted else ctx.remove_class)("muted")

    def on_slide(self, scale):
        if self.updating:
            return
        vol = int(scale.get_value())
        self.pct.set_text(f"{vol}%")
        # Coalesce rapid drag events into one wpctl call every ~40ms
        if self.pending is None:
            self.pending = GLib.timeout_add(40, self._apply)

    def _apply(self):
        self.pending = None
        vol = int(self.scale.get_value())
        wpctl("set-volume", TARGETS[self.kind], f"{vol / 100:.2f}")
        return False

    def on_mute(self, _button):
        wpctl("set-mute", TARGETS[self.kind], "toggle")
        self.refresh()


class Popup(Gtk.Window):
    """A transparent full-screen overlay holding the panel in the top-right.

    Any click that lands on the overlay (i.e. anywhere outside the panel,
    including the bar itself) closes the popup, so clicking out always works.
    """

    def __init__(self):
        super().__init__()
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "waybar-audio-popup")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        # -1: ignore the bar's reserved space, so margins count from the screen edge
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        panel.set_name("panel")
        self.rows = [Row("sink", "Speaker"), Row("source", "Mic")]
        for r in self.rows:
            panel.pack_start(r, False, False, 0)

        # Clicks inside the panel (padding, labels) are swallowed here so they
        # don't reach the overlay and close it. Sliders/buttons handle their own.
        panel_box = Gtk.EventBox()
        panel_box.set_visible_window(False)
        panel_box.add(panel)
        panel_box.connect("button-press-event", lambda *_: True)
        panel_box.set_halign(Gtk.Align.END)
        panel_box.set_valign(Gtk.Align.START)
        panel_box.set_margin_top(MARGIN_TOP)
        panel_box.set_margin_end(MARGIN_RIGHT + (BATTERY_WIDTH if has_battery() else 0))

        catcher = Gtk.EventBox()
        catcher.set_name("catcher")
        catcher.set_visible_window(False)
        catcher.add(panel_box)
        catcher.connect("button-press-event", lambda *_: Gtk.main_quit())
        self.add(catcher)

        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)
        GLib.timeout_add(POLL_MS, self.poll)

    def poll(self):
        for r in self.rows:
            r.refresh()
        return True

    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()


def running_pid():
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            if b"audio-popup" in f.read():
                return pid
    except (OSError, ValueError):
        pass
    return None


def main():
    pid = running_pid()
    if pid:  # already open -> this click closes it
        os.kill(pid, signal.SIGTERM)
        return

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    try:
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
        Popup().show_all()
        Gtk.main()
    finally:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
