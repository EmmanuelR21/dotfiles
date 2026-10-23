"""Shared pieces of the Waybar popups in this folder.

Every popup is a short-lived process: the module's "on-click" runs the
script, which opens the popup; running it again while it's open closes it.
Closed popups cost nothing (no process, no polling).

A popup script subclasses Popup, fills self.panel, and calls run():

    class AudioPopup(Popup):
        NAME = "audio"  # layer-shell namespace + PID file name
        def __init__(self):
            super().__init__(spacing=10)
            self.panel.pack_start(...)

    run(AudioPopup, CSS)

Requires: python-gobject, gtk3, gtk-layer-shell.
"""

import json
import os
import signal
import subprocess

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

try:  # GLib.unix_signal_add is deprecated in favor of GLibUnix (GLib >= 2.80)
    gi.require_version("GLibUnix", "2.0")
    from gi.repository import GLibUnix

    signal_add = GLibUnix.signal_add
except (ValueError, ImportError):
    signal_add = GLib.unix_signal_add

# TOP = bar margin (6) + bar height (31) + 4px gap
MARGIN_TOP = 41
EDGE_GAP = 6
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")

# Matches the bar's module boxes (style.css). Scripts add their own #panel
# padding/size and widget styles on top.
BASE_CSS = """
* {
    font-family: "FreeSans", "Symbols Nerd Font";
    font-weight: bold;
    font-size: 13px;
    color: #ffffff;
    /* Adwaita (light) gives button text/icons a white 1px shadow, which looks
       doubled on these dark panels */
    text-shadow: none;
    -gtk-icon-shadow: none;
}
window, #catcher { background-color: transparent; }

#panel {
    background-color: #1e1e1e;
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 5px;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.07);
}
"""


def label(text="", *classes, xalign=0.0):
    w = Gtk.Label(label=text, xalign=xalign)
    for c in classes:
        w.get_style_context().add_class(c)
    return w


def button(text, on_click, *classes, sensitive=True):
    b = Gtk.Button(label=text)
    for c in classes:
        b.get_style_context().add_class(c)
    b.set_sensitive(sensitive)
    b.set_valign(Gtk.Align.CENTER)
    b.connect("clicked", lambda *_: on_click())
    return b


def set_class(widget, name, on):
    ctx = widget.get_style_context()
    (ctx.add_class if on else ctx.remove_class)(name)


def hyprctl_json(*args):
    out = subprocess.run(
        ["hyprctl", *args, "-j"], capture_output=True, text=True, timeout=2, check=False
    ).stdout
    return json.loads(out)


def panel_right_margin(cursor_offset, fallback):
    """Distance from the screen's right edge to cursor_offset px right of the
    mouse at click time, so the panel lines up under the clicked module no
    matter how wide the modules are. fallback is used if hyprctl fails."""
    try:
        cur = hyprctl_json("cursorpos")
        for m in hyprctl_json("monitors"):
            w, h = m["width"], m["height"]
            if m["transform"] % 2:  # rotated 90/270
                w, h = h, w
            lw, lh = w / m["scale"], h / m["scale"]
            if m["x"] <= cur["x"] < m["x"] + lw and m["y"] <= cur["y"] < m["y"] + lh:
                return max(EDGE_GAP, int(m["x"] + lw - cur["x"] - cursor_offset))
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        pass
    return fallback


class Popup(Gtk.Window):
    """A transparent full-screen overlay holding self.panel.

    Any click that lands on the overlay (i.e. anywhere outside the panel,
    including the bar itself) closes the popup, so clicking out always works.

    align=END puts the panel's right edge cursor_offset px right of the mouse,
    or margin_end px from the screen edge if given; align=CENTER centers it;
    align=START puts it margin_start px from the left edge.
    """

    NAME = "popup"

    def __init__(
        self,
        spacing=8,
        align=Gtk.Align.END,
        margin_end=None,
        cursor_offset=24,
        fallback_margin=60,
        margin_start=EDGE_GAP,
    ):
        super().__init__()
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, f"waybar-{self.NAME}-popup")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        for edge in (
            GtkLayerShell.Edge.TOP,
            GtkLayerShell.Edge.BOTTOM,
            GtkLayerShell.Edge.LEFT,
            GtkLayerShell.Edge.RIGHT,
        ):
            GtkLayerShell.set_anchor(self, edge, True)
        # -1: ignore the bar's reserved space, so margins count from the screen edge
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
        self.panel.set_name("panel")

        # Clicks inside the panel (padding, labels) are swallowed here so they
        # don't reach the overlay and close it. Widgets handle their own.
        self.panel_box = Gtk.EventBox()
        self.panel_box.set_visible_window(False)
        self.panel_box.add(self.panel)
        self.panel_box.connect("button-press-event", lambda *_: True)
        self.panel_box.set_halign(align)
        self.panel_box.set_valign(Gtk.Align.START)
        self.panel_box.set_margin_top(MARGIN_TOP)
        if align == Gtk.Align.END:
            if margin_end is None:
                margin_end = panel_right_margin(cursor_offset, fallback_margin)
            self.panel_box.set_margin_end(margin_end)
        elif align == Gtk.Align.START:
            self.panel_box.set_margin_start(margin_start)

        catcher = Gtk.EventBox()
        catcher.set_name("catcher")
        catcher.set_visible_window(False)
        catcher.add(self.panel_box)
        catcher.connect("button-press-event", lambda *_: Gtk.main_quit())
        self.add(catcher)

        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)

    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()
            return True
        return False

    def cleanup(self):
        """Runs once the popup is hidden; for work that may take a moment."""


def _running_pid(pid_file, name):
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            if f"{name}-popup".encode() in f.read():
                return pid
    except (OSError, ValueError):
        pass
    return None


def run(popup_cls, css=""):
    """Open popup_cls, or close it if it's already open."""
    pid_file = os.path.join(RUNTIME, f"waybar-{popup_cls.NAME}-popup.pid")
    pid = _running_pid(pid_file, popup_cls.NAME)
    if pid:  # already open -> this click closes it
        os.kill(pid, signal.SIGTERM)
        return

    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))
    popup = None
    try:
        provider = Gtk.CssProvider()
        provider.load_from_data((BASE_CSS + css).encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

        signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
        popup = popup_cls()
        popup.show_all()
        # Nothing focused at open, so a stray Enter/Space can't trigger a button
        popup.set_focus(None)
        Gtk.main()
    finally:
        if popup:  # disappear right away, even if cleanup takes a moment
            popup.hide()
            Gdk.Display.get_default().flush()
        try:
            os.remove(pid_file)  # a new click may open a fresh popup from here on
        except OSError:
            pass
        if popup:
            popup.cleanup()
