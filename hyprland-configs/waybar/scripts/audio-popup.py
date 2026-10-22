#!/usr/bin/env python3
"""Speaker/mic popup for the Waybar audio module.

Click to open, click again to close (see popup_common.py). Volume and mute
go through wpctl (WirePlumber), the same tool the bar already uses.
"""
import os
import subprocess

from popup_common import GLib, Gtk, Popup, label, run, set_class

# RIGHT = distance to the audio module's right edge: bar margin (6) +
# power (~34) + network (~38) + 6px spacing each. The battery module only shows
# on machines with a battery, so its width is added when one exists.
# Fine-tune these if the panel doesn't line up exactly under the module.
MARGIN_RIGHT = 90
BATTERY_WIDTH = 76  # battery module (~70) + spacing (6)


def has_battery():
    try:
        return any(n.startswith("BAT") for n in os.listdir("/sys/class/power_supply"))
    except OSError:
        return False

# How often to pick up volume changes made elsewhere (media keys, other apps).
# Each poll runs wpctl twice, so this is kept slow; changes made in the popup
# itself update instantly regardless.
POLL_MS = 2000

ICONS = {
    "sink": ("\U000f057e", "\U000f0581"),    # speaker, speaker-off
    "source": ("\U000f036c", "\U000f036d"),  # mic, mic-off
}
TARGETS = {"sink": "@DEFAULT_AUDIO_SINK@", "source": "@DEFAULT_AUDIO_SOURCE@"}

CSS = """
#panel { padding: 10px 14px; }

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
        return subprocess.run(["wpctl", *args], capture_output=True, text=True, timeout=2, check=False).stdout
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
    def __init__(self, kind, text):
        super().__init__(spacing=8)
        self.kind = kind
        self.updating = False   # set while we move the slider ourselves
        self.dragging = False
        self.pending = None

        self.icon = label("", "icon")
        name = label(text, "name")

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.connect("value-changed", self.on_slide)
        self.scale.connect("button-press-event", lambda *_: self._set_drag(True))
        self.scale.connect("button-release-event", lambda *_: self._set_drag(False))

        self.pct = label("", "pct", xalign=1)

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
        set_class(self, "muted", muted)

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


class AudioPopup(Popup):
    NAME = "audio"

    def __init__(self):
        super().__init__(spacing=10,
                         margin_end=MARGIN_RIGHT + (BATTERY_WIDTH if has_battery() else 0))
        self.rows = [Row("sink", "Speaker"), Row("source", "Mic")]
        for r in self.rows:
            self.panel.pack_start(r, False, False, 0)
        GLib.timeout_add(POLL_MS, self.poll)

    def poll(self):
        for r in self.rows:
            r.refresh()
        return True


if __name__ == "__main__":
    run(AudioPopup, CSS)
