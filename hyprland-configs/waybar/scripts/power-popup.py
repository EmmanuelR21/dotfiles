#!/usr/bin/env python3
"""Power popup (suspend / reboot / shut down) for the Waybar power module.

Click to open, click again to close (see popup_common.py).
Arrow keys / Tab move between actions, Enter runs one, Escape closes.

Requires: hyprshutdown.
"""

import subprocess

from popup_common import Gtk, Popup, label, run

# The power module is the rightmost one, so the panel's right edge lines up
# with the bar's (6px margin).
MARGIN_RIGHT = 6

# (label, icon, command). All Material Design glyphs from Symbols Nerd Font,
# so they share one size and stroke: power-sleep, restart, power.
ACTIONS = [
    ("Suspend", "\U000f0904", ["systemctl", "suspend"]),
    ("Reboot", "\U000f0709", ["hyprshutdown", "-p", "systemctl reboot"]),
    ("Shut down", "\U000f0425", ["hyprshutdown", "-p", "systemctl poweroff"]),
]

CSS = """
#panel { padding: 6px; min-width: 150px; }

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


def launch(cmd):
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    Gtk.main_quit()


def action_button(name, icon, cmd):
    box = Gtk.Box(spacing=10)
    box.pack_start(label(icon, "icon"), False, False, 0)
    box.pack_start(label(name, "name"), False, False, 0)
    b = Gtk.Button()
    b.add(box)
    b.connect("clicked", lambda *_: launch(cmd))
    return b


class PowerPopup(Popup):
    NAME = "power"

    def __init__(self):
        super().__init__(spacing=2, margin_end=MARGIN_RIGHT)
        for action in ACTIONS:
            self.panel.pack_start(action_button(*action), False, False, 0)


if __name__ == "__main__":
    run(PowerPopup, CSS)
