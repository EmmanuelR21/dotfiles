#!/usr/bin/env python3
"""Speaker/mic popup for the Waybar audio module.

Click to open, click again to close (see popup_common.py). Volume, mute
and the default device go through wpctl (WirePlumber), the same tool the bar
already uses; the device list comes from pw-dump. Both ship with PipeWire.
"""

import json
import subprocess

from popup_common import GLib, Gtk, Popup, label, run, set_class

# The panel's right edge sits CURSOR_OFFSET px right of the mouse at click time
CURSOR_OFFSET = 40
FALLBACK_MARGIN_RIGHT = 130

# How often to pick up volume/device changes made elsewhere (media keys, other
# apps, plugging a headset in). Each poll runs wpctl twice and pw-dump once, so
# this is kept slow; changes made in the popup itself update instantly.
POLL_MS = 2000

ICONS = {
    "sink": ("\U000f057e", "\U000f0581"),  # speaker, speaker-off
    "source": ("\U000f036c", "\U000f036d"),  # mic, mic-off
}
TARGETS = {"sink": "@DEFAULT_AUDIO_SINK@", "source": "@DEFAULT_AUDIO_SOURCE@"}
MEDIA_CLASS = {"sink": "Audio/Sink", "source": "Audio/Source"}
DEFAULT_KEY = {"sink": "default.audio.sink", "source": "default.audio.source"}
ICON_DEVICE = {"sink": "\U000f02cb", "source": "\U000f036c"}  # headphones, mic
ICON_EXPAND = "\U000f0140"  # chevron-down
ICON_CHECK = "\U000f012c"

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

/* Device picker under each row: current device, click to list the others */
button.device {
    min-width: 0;
    padding: 3px 8px;
    margin-left: 30px;
    background-color: transparent;
}
button.device:hover, button.device.open { background-color: #262626; }
.device label { font-size: 11px; font-weight: normal; color: #8a8f98; }
.device .d-icon { font-size: 13px; color: #6f747d; }
.device.open .d-icon, .device.open .chev { color: #d6dde9; }

.devices { margin: 2px 0 0 30px; background-color: #232323; border-radius: 4px; padding: 3px; }
button.choice { min-width: 0; padding: 4px 8px; background-color: transparent; }
button.choice:hover { background-color: #2e2e2e; }
.choice label { font-size: 12px; font-weight: normal; color: #cfcfcf; }
.choice.current label { color: #ffffff; font-weight: bold; }
.empty { font-size: 11px; font-weight: normal; color: #6f747d; padding: 4px 8px; }
"""


def wpctl(*args):
    try:
        return subprocess.run(
            ["wpctl", *args], capture_output=True, text=True, timeout=2, check=False
        ).stdout
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


def read_devices():
    """{"sink"/"source": ([(id, name), ...], default id)} from one pw-dump call."""
    try:
        out = subprocess.run(
            ["pw-dump"], capture_output=True, text=True, timeout=2, check=False
        ).stdout
        objs = json.loads(out)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {k: ([], None) for k in MEDIA_CLASS}
    defaults, nodes = {}, {k: [] for k in MEDIA_CLASS}
    for o in objs:
        if (
            o.get("type") == "PipeWire:Interface:Metadata"
            and o.get("props", {}).get("metadata.name") == "default"
        ):
            for m in o.get("metadata") or []:
                if isinstance(m.get("value"), dict):
                    defaults[m["key"]] = m["value"].get("name")
        props = (o.get("info") or {}).get("props") or {}
        for kind, cls in MEDIA_CLASS.items():
            if props.get("media.class") == cls:
                nodes[kind].append(
                    (
                        o["id"],
                        props.get("node.name"),
                        props.get("node.description")
                        or props.get("node.nick")
                        or props.get("node.name", "?"),
                    )
                )
    result = {}
    for kind, items in nodes.items():
        default = next(
            (i for i, name, _ in items if name == defaults.get(DEFAULT_KEY[kind])), None
        )
        result[kind] = (
            [(i, desc) for i, _, desc in sorted(items, key=lambda x: x[2])],
            default,
        )
    return result


class DevicePicker(Gtk.Box):
    """Current device under a row; clicking it lists the others to switch to."""

    def __init__(self, kind, on_switch):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.kind, self.on_switch = kind, on_switch
        self.devices, self.default = [], None

        row = Gtk.Box(spacing=6)
        row.pack_start(label(ICON_DEVICE[kind], "d-icon"), False, False, 0)
        self.name = label("")
        self.name.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self.name.set_max_width_chars(36)
        row.pack_start(self.name, True, True, 0)
        row.pack_start(label(ICON_EXPAND, "chev"), False, False, 0)
        self.head = Gtk.Button()
        self.head.add(row)
        self.head.get_style_context().add_class("device")
        self.head.connect(
            "clicked", lambda *_: self.set_open(not self.revealer.get_reveal_child())
        )
        self.pack_start(self.head, False, False, 0)

        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.list.get_style_context().add_class("devices")
        self.revealer = Gtk.Revealer(transition_duration=150)
        self.revealer.add(self.list)
        self.pack_start(self.revealer, False, False, 0)

    def update(self, devices, default):
        if (devices, default) == (self.devices, self.default):
            return
        self.devices, self.default = devices, default
        current = next((d for i, d in devices if i == default), None)
        self.name.set_text(current or "No device")
        for child in self.list.get_children():
            child.destroy()
        if not devices:
            self.list.pack_start(label("No devices found", "empty"), False, False, 0)
        for dev_id, desc in devices:
            box = Gtk.Box(spacing=8)
            name = label(desc)
            name.set_ellipsize(3)
            name.set_max_width_chars(40)
            box.pack_start(name, True, True, 0)
            if dev_id == default:
                box.pack_start(label(ICON_CHECK), False, False, 0)
            b = Gtk.Button()
            b.add(box)
            b.get_style_context().add_class("choice")
            set_class(b, "current", dev_id == default)
            b.connect("clicked", lambda _b, i=dev_id: self.choose(i))
            self.list.pack_start(b, False, False, 0)
        self.list.show_all()

    def choose(self, dev_id):
        wpctl("set-default", str(dev_id))
        self.set_open(False)
        self.on_switch()

    def set_open(self, on):
        self.revealer.set_reveal_child(on)
        set_class(self.head, "open", on)


class Row(Gtk.Box):
    def __init__(self, kind, text):
        super().__init__(spacing=8)
        self.kind = kind
        self.updating = False  # set while we move the slider ourselves
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
        super().__init__(
            spacing=10,
            cursor_offset=CURSOR_OFFSET,
            fallback_margin=FALLBACK_MARGIN_RIGHT,
        )
        self.rows = [Row("sink", "Speaker"), Row("source", "Mic")]
        self.pickers = [DevicePicker(r.kind, self.poll) for r in self.rows]
        for row, picker in zip(self.rows, self.pickers):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.pack_start(row, False, False, 0)
            box.pack_start(picker, False, False, 0)
            self.panel.pack_start(box, False, False, 0)
        self.refresh_devices()
        GLib.timeout_add(POLL_MS, self.poll)

    def refresh_devices(self):
        devices = read_devices()
        for picker in self.pickers:
            picker.update(*devices[picker.kind])

    def poll(self):
        # Also catches devices plugged in/out or switched elsewhere
        for r in self.rows:
            r.refresh()
        self.refresh_devices()
        return True


if __name__ == "__main__":
    run(AudioPopup, CSS)
