#!/usr/bin/env python3
"""Power popup (suspend / reboot / shut down) for the Waybar power module.

Running it opens the popup; running it again while it's open closes it, so it
works directly as a Waybar "on-click" command (same as the other popups).
Arrow keys / Tab move between actions, Enter runs one, Escape closes.

Requires: python-gobject, gtk3, gtk-layer-shell, hyprshutdown.
"""
import os
import signal
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, Gtk, Gdk, GtkLayerShell  # noqa: E402

# TOP = bar margin (6) + bar height (30) + 4px gap. The power module is the
# rightmost one, so the panel's right edge lines up with the bar's (6px).
MARGIN_TOP = 40
MARGIN_RIGHT = 6

# (label, icon, command)
ACTIONS = [
    ("Suspend", "\U000f04b2", ["systemctl", "suspend"]),
    ("Reboot", "\U000f0709", ["hyprshutdown", "-p", "systemctl reboot"]),
    ("Shut down", "\u23fb", ["hyprshutdown", "-p", "systemctl poweroff"]),
]

PID_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "waybar-power-popup.pid")

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
    padding: 6px;
    min-width: 150px;
}

button {
    padding: 6px 10px;
    border-radius: 4px;
    border: none;
    box-shadow: none;
    outline: none;
    background-image: none;
    background-color: transparent;
    transition: background-color 150ms ease-out;
}
button .icon { font-size: 16px; color: #fb4934; min-width: 22px; }
button .name { color: #d8d8d8; font-weight: normal; transition: color 150ms ease-out; }

/* Red accent (the bar's power color) on hover / keyboard focus */
button:hover, button:focus { background-color: rgba(251, 73, 52, 0.12); }
button:hover .name, button:focus .name { color: #ff7a7a; }
"""


def run(cmd):
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    Gtk.main_quit()


def action_button(name, icon, cmd):
    box = Gtk.Box(spacing=10)
    for text, cls in ((icon, "icon"), (name, "name")):
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.get_style_context().add_class(cls)
        box.pack_start(lbl, False, False, 0)
    button = Gtk.Button()
    button.add(box)
    button.connect("clicked", lambda *_: run(cmd))
    return button


class Popup(Gtk.Window):
    """A transparent full-screen overlay holding the panel in the top-right.

    Any click outside the panel (including on the bar) closes the popup.
    """

    def __init__(self):
        super().__init__()
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "waybar-power-popup")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        panel.set_name("panel")
        for action in ACTIONS:
            panel.pack_start(action_button(*action), False, False, 0)

        panel_box = Gtk.EventBox()
        panel_box.set_visible_window(False)
        panel_box.add(panel)
        panel_box.connect("button-press-event", lambda *_: True)
        panel_box.set_halign(Gtk.Align.END)
        panel_box.set_valign(Gtk.Align.START)
        panel_box.set_margin_top(MARGIN_TOP)
        panel_box.set_margin_end(MARGIN_RIGHT)

        catcher = Gtk.EventBox()
        catcher.set_name("catcher")
        catcher.set_visible_window(False)
        catcher.add(panel_box)
        catcher.connect("button-press-event", lambda *_: Gtk.main_quit())
        self.add(catcher)

        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)

    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()


def running_pid():
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            if b"power-popup" in f.read():
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
        popup = Popup()
        popup.show_all()
        # Nothing focused at open, so a stray Enter can't trigger an action
        popup.set_focus(None)
        Gtk.main()
    finally:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
