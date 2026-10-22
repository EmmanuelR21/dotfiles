#!/usr/bin/env python3
"""Bluetooth popup for the Waybar bluetooth module.

Click to open, click again to close (see popup_common.py).

Talks to BlueZ directly over D-Bus through Gio, so it needs nothing beyond
the other popups' dependencies and bluez itself. While open it registers a pairing agent, so new devices can be
paired from the "Scan" list without bluetoothctl.
"""
import subprocess

import gi
from popup_common import GLib, Gtk, Popup, button, label, run

gi.require_version("Pango", "1.0")
from gi.repository import Gio, Pango

# The panel's right edge sits CURSOR_OFFSET px right of the mouse at click time
CURSOR_OFFSET = 24
FALLBACK_MARGIN_RIGHT = 160

MAX_FOUND = 8  # cap on unpaired devices listed while scanning

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"
AGENT_PATH = "/org/waybar/bluetooth_popup/agent"

ICON_ON, ICON_CONNECTED, ICON_OFF = "\U000f00af", "\U000f00b1", "\U000f00b2"
DEVICE_ICONS = [  # matched against the BlueZ "Icon" property prefix
    ("audio-head", "\U000f02cb"),     # headphones / headset
    ("audio-card", "\U000f04c3"),     # speaker
    ("input-mouse", "\U000f037d"),
    ("input-keyboard", "\U000f030c"),
    ("input-gaming", "\U000f02b4"),
    ("phone", "\U000f011c"),
    ("computer", "\U000f0322"),
]

FRIENDLY_ERRORS = {
    "br-connection-page-timeout": "device didn't respond (is it on and in range?)",
    "br-connection-profile-unavailable": "no usable profile (is the audio stack running?)",
    "br-connection-canceled": "connection canceled",
    "Page Timeout": "device didn't respond (is it on and in range?)",
    "Authentication Failed": "pairing failed, put the device in pairing mode and retry",
    "Authentication Rejected": "pairing was rejected",
    "Already Exists": "already paired",
}


AGENT_XML = """
<node><interface name="org.bluez.Agent1">
  <method name="Release"/>
  <method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
  <method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
  <method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
  <method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
  <method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
  <method name="RequestAuthorization"><arg type="o" direction="in"/></method>
  <method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
  <method name="Cancel"/>
</interface></node>
"""

# BLUE matches #bluetooth in style.css; BLUE_TEXT is a lighter shade for
# small text so it stays readable on the dark panel.
CSS = """
#panel { padding: 12px 14px; min-width: 320px; }

.head-icon { font-size: 22px; color: #3567d0; min-width: 26px; }
.head-icon.off { color: #45526b; }
.title { font-size: 14px; }
.sub, .state, .empty { font-size: 11px; font-weight: normal; color: #8a8f98; }
.section { font-size: 10px; color: #6f747d; margin-top: 2px; }

.dev-icon { font-size: 18px; color: #3567d0; min-width: 24px; }
.connected .state { color: #6f98ee; }
/* Device battery: tinted pill. Silver (matches the bar) when healthy,
   amber/red warnings when low (same family as the bar's accents) */
.batt {
    font-size: 11px;
    padding: 1px 7px;
    border-radius: 9px;
    color: #d6dde9;
    background-color: rgba(214, 221, 233, 0.14);
}
.batt.mid { color: #fabd2f; background-color: rgba(250, 189, 47, 0.14); }
.batt.low { color: #fb4934; background-color: rgba(251, 73, 52, 0.16); }

separator { background-color: #333333; min-height: 1px; }

button {
    min-width: 78px;
    padding: 3px 8px;
    border-radius: 4px;
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: #2a2a2a;
    transition: background-color 150ms ease-out;
}
button label { font-size: 11px; color: #cfcfcf; }
button:hover { background-color: #333333; }
button:disabled { background-color: #242424; }
button:disabled label { color: #6f747d; }

/* Blue-tinted primary actions (Turn on, Connect, Pair, Scan) */
button.accent { background-color: rgba(53, 103, 208, 0.22); }
button.accent:hover { background-color: rgba(53, 103, 208, 0.34); }
button.accent label { color: #6f98ee; }

/* Small "x" to forget a paired device; turns dusty red on hover */
button.forget { min-width: 0; padding: 3px 6px; background-color: transparent; }
button.forget label { font-size: 13px; color: #6f747d; }
button.forget:hover { background-color: rgba(234, 106, 95, 0.15); }
button.forget:hover label { color: #ea6a5f; }

spinner { color: #6f98ee; }
.status { font-size: 11px; font-weight: normal; color: #e0b44c; }
"""

BUS = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


def call(path, iface, method, params=None, cb=None, timeout=25000):
    """Async BlueZ method call; cb(error_or_None) runs on the GTK main loop."""
    def done(bus, res):
        err = None
        try:
            bus.call_finish(res)
        except GLib.Error as e:
            err = e
        if cb:
            cb(err)
    BUS.call(BLUEZ, path, iface, method, params, None,
             Gio.DBusCallFlags.NONE, timeout, None, done)


def set_prop(path, iface, name, value, cb=None):
    call(path, "org.freedesktop.DBus.Properties", "Set",
         GLib.Variant("(ssv)", (iface, name, value)), cb)


def get_objects():
    try:
        reply = BUS.call_sync(BLUEZ, "/", "org.freedesktop.DBus.ObjectManager",
                              "GetManagedObjects", None, None,
                              Gio.DBusCallFlags.NONE, 2000, None)
        return reply.unpack()[0]
    except GLib.Error:
        return {}


def nice(err):
    # "GDBus.Error:org.bluez.Error.Failed: br-connection-page-timeout" -> last part
    msg = err.message.split(": ", 1)[-1] if ": " in err.message else err.message
    return FRIENDLY_ERRORS.get(msg, msg)


def device_icon(kind):
    for prefix, glyph in DEVICE_ICONS:
        if kind.startswith(prefix):
            return glyph
    return ICON_ON


class BluetoothPopup(Popup):
    NAME = "bluetooth"

    def __init__(self):
        super().__init__(cursor_offset=CURSOR_OFFSET, fallback_margin=FALLBACK_MARGIN_RIGHT)
        self.adapter = None      # (path, props) of the first adapter
        self.busy = {}           # device path -> label shown while an action runs
        self.pairing = set()     # device paths we started pairing (agent accepts only these)
        self.scanning = False
        self.status = ""
        self.signature = None
        self.refresh_id = None
        self.agent_ok = False

        self.register_agent()
        # Any BlueZ signal (property change, device found/removed) -> refresh
        BUS.signal_subscribe(BLUEZ, None, None, None, None,
                             Gio.DBusSignalFlags.NONE, lambda *_: self.schedule())
        GLib.timeout_add(2000, self.poll)  # safety net, e.g. if bluetoothd restarts
        self.rebuild()

    # ---- state -------------------------------------------------------------

    def read_state(self):
        objs = get_objects()
        adapter = next(((p, i[ADAPTER]) for p, i in sorted(objs.items()) if ADAPTER in i), None)
        devices = []
        if adapter:
            for path, ifaces in objs.items():
                d = ifaces.get(DEVICE)
                if not d or not path.startswith(adapter[0] + "/"):
                    continue
                devices.append({
                    "path": path,
                    "name": d.get("Alias") or d.get("Address", "?"),
                    "named": "Name" in d,  # unnamed = random beacons, skip in scan list
                    "paired": bool(d.get("Paired") or d.get("Bonded")),
                    "connected": bool(d.get("Connected")),
                    "icon": d.get("Icon", ""),
                    "battery": ifaces.get(BATTERY, {}).get("Percentage"),
                })
        return adapter, devices

    def schedule(self):
        if self.refresh_id is None:
            self.refresh_id = GLib.timeout_add(100, self._refresh)

    def _refresh(self):
        self.refresh_id = None
        self.rebuild()
        return False

    def poll(self):
        self.rebuild()
        return True

    def set_status(self, text):
        self.status = text
        self.schedule()

    # ---- UI ----------------------------------------------------------------

    def rebuild(self):
        adapter, devices = self.read_state()
        a = adapter[1] if adapter else {}
        powered = bool(a.get("Powered"))
        if not powered:
            self.scanning = False
        sig = (adapter and adapter[0], powered, a.get("Discovering"), a.get("Alias"),
               a.get("Address"), self.scanning, self.status, tuple(sorted(self.busy.items())),
               tuple(tuple(sorted((k, str(v)) for k, v in d.items())) for d in
                     sorted(devices, key=lambda d: d["path"])))
        if sig == self.signature:
            return
        self.signature = sig
        self.adapter = adapter

        for child in self.panel.get_children():
            child.destroy()

        if not adapter:
            self.panel.pack_start(self.header(ICON_OFF, "Bluetooth", "No adapter found", None, off=True), False, False, 0)
            self.panel.pack_start(label("Is bluetooth.service running?\n"
                                        "systemctl enable --now bluetooth", "empty"), False, False, 0)
            self.panel.show_all()
            return

        connected = [d for d in devices if d["connected"]]
        sub = f"{a.get('Alias', 'Adapter')} \u00b7 {a.get('Address', '')}"
        if powered:
            sub += f" \u00b7 {len(connected)} connected"
        toggle = button("Turn off" if powered else "Turn on", self.toggle_power,
                        *(() if powered else ("accent",)))
        icon = ICON_CONNECTED if connected else (ICON_ON if powered else ICON_OFF)
        self.panel.pack_start(self.header(icon, "Bluetooth", sub, toggle, off=not powered), False, False, 0)

        if not powered:
            if a.get("PowerState") == "off-blocked":
                self.panel.pack_start(label("Blocked by rfkill. \"Turn on\" will unblock it.", "empty"), False, False, 0)
        else:
            self.panel.pack_start(Gtk.Separator(), False, False, 2)
            self.panel.pack_start(label("PAIRED DEVICES", "section"), False, False, 0)
            paired = sorted((d for d in devices if d["paired"]),
                            key=lambda d: (not d["connected"], d["name"].lower()))
            if not paired:
                self.panel.pack_start(label("No paired devices yet, scan below to add one.", "empty"), False, False, 0)
            for d in paired:
                self.panel.pack_start(self.device_row(d), False, False, 0)

            self.panel.pack_start(Gtk.Separator(), False, False, 2)
            scan_row = Gtk.Box(spacing=8)
            scan_row.pack_start(label("NEW DEVICES", "section"), True, True, 0)
            if a.get("Discovering"):
                spinner = Gtk.Spinner()
                spinner.start()
                scan_row.pack_start(spinner, False, False, 0)
            scan_row.pack_start(button("Stop scan" if self.scanning else "Scan",
                                       self.toggle_scan, "accent"), False, False, 0)
            self.panel.pack_start(scan_row, False, False, 0)

            if self.scanning:
                found = sorted((d for d in devices if not d["paired"] and d["named"]),
                               key=lambda d: d["name"].lower())[:MAX_FOUND]
                if not found:
                    self.panel.pack_start(label("Searching\u2026 put your device in pairing mode.", "empty"), False, False, 0)
                for d in found:
                    self.panel.pack_start(self.device_row(d), False, False, 0)

        if self.status:
            st = label(self.status, "status")
            st.set_line_wrap(True)
            st.set_max_width_chars(42)
            self.panel.pack_start(st, False, False, 0)
        self.panel.show_all()

    def header(self, icon, title, sub, action, off=False):
        row = Gtk.Box(spacing=10)
        ic = label(icon, "head-icon")
        if off:
            ic.get_style_context().add_class("off")
        row.pack_start(ic, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.pack_start(label(title, "title"), False, False, 0)
        text.pack_start(label(sub, "sub"), False, False, 0)
        row.pack_start(text, True, True, 0)
        if action:
            row.pack_start(action, False, False, 0)
        return row

    def device_row(self, d):
        row = Gtk.Box(spacing=8)
        if d["connected"]:
            row.get_style_context().add_class("connected")
        row.pack_start(label(device_icon(d["icon"]), "dev-icon"), False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        name = label(d["name"])
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(20)
        text.pack_start(name, False, False, 0)
        state = "Connected" if d["connected"] else ("Paired" if d["paired"] else "Not paired")
        text.pack_start(label(state, "state"), False, False, 0)
        row.pack_start(text, True, True, 0)

        if d["connected"] and d["battery"] is not None:
            pct = int(d["battery"])
            level = "low" if pct < 20 else ("mid" if pct < 50 else "high")
            # md-battery-10 .. md-battery (f007a..f0082 step by 10%, f0079 = full)
            glyph = "\U000f0079" if pct >= 95 else chr(0xF007A + max(0, min(8, pct // 10 - 1)))
            pill = label(f"{glyph} {pct}%", "batt", level)
            pill.set_valign(Gtk.Align.CENTER)
            row.pack_start(pill, False, False, 0)

        busy = self.busy.get(d["path"])
        if busy:
            action = button(busy, lambda: None, sensitive=False)
        elif d["connected"]:
            action = button("Disconnect", lambda: self.disconnect(d))
        elif d["paired"]:
            action = button("Connect", lambda: self.connect_dev(d), "accent")
        else:
            action = button("Pair", lambda: self.pair(d), "accent")
        row.pack_start(action, False, False, 0)

        if d["paired"]:
            row.pack_start(button("\u2715", lambda: self.forget(d), "forget",
                                  sensitive=not busy), False, False, 0)
        return row

    # ---- actions -----------------------------------------------------------

    def run(self, d, busy_label, method, then=None, timeout=25000):
        path = d["path"]
        self.busy[path] = busy_label
        self.status = ""
        self.schedule()

        def done(err):
            self.busy.pop(path, None)
            self.pairing.discard(path)
            if err:
                self.status = f"{d['name']}: {nice(err)}"
            elif then:
                then()
            self.schedule()
        call(path, DEVICE, method, None, done, timeout)

    def connect_dev(self, d):
        self.run(d, "Connecting\u2026", "Connect")

    def disconnect(self, d):
        self.run(d, "Disconnecting\u2026", "Disconnect")

    def pair(self, d):
        self.pairing.add(d["path"])

        def paired():
            # Trusted = it can reconnect on its own later without asking
            set_prop(d["path"], DEVICE, "Trusted", GLib.Variant("b", True))
            self.connect_dev(d)


        if not self.agent_ok:
            self.set_status("Pairing agent unavailable; pair with bluetoothctl instead.")
            return
        self.run(d, "Pairing\u2026", "Pair", then=paired, timeout=60000)

    def forget(self, d):
        call(self.adapter[0], ADAPTER, "RemoveDevice", GLib.Variant("(o)", (d["path"],)),
             lambda err: err and self.set_status(f"{d['name']}: {nice(err)}"))

    def toggle_power(self):
        path, props = self.adapter
        turn_on = not props.get("Powered")
        report = lambda err: err and self.set_status(f"Bluetooth: {nice(err)}")
        if not turn_on:
            self.scanning = False
            set_prop(path, ADAPTER, "Powered", GLib.Variant("b", False), report)
            return
        blocked = props.get("PowerState") == "off-blocked"
        if blocked:
            # Soft rfkill block (airplane mode, laptop switch); /dev/rfkill is
            # writable by the logged-in user, so no sudo needed.
            try:
                subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True, timeout=3,
                               check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
        # Give bluetoothd a moment to notice the unblock before powering on
        GLib.timeout_add(400 if blocked else 0,
                         lambda: set_prop(path, ADAPTER, "Powered", GLib.Variant("b", True), report) and False)

    def toggle_scan(self):
        path = self.adapter[0]
        if self.scanning:
            self.scanning = False
            call(path, ADAPTER, "StopDiscovery")
        else:
            self.scanning = True

            def started(err):
                if err:
                    self.scanning = False
                    self.set_status(f"Scan: {nice(err)}")
            call(path, ADAPTER, "StartDiscovery", cb=started)
        self.schedule()

    # ---- pairing agent -----------------------------------------------------

    def register_agent(self):
        try:
            info = Gio.DBusNodeInfo.new_for_xml(AGENT_XML).interfaces[0]
            BUS.register_object(AGENT_PATH, info, self.on_agent_call, None, None)
            BUS.call_sync(BLUEZ, "/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                          GLib.Variant("(os)", (AGENT_PATH, "DisplayYesNo")),
                          None, Gio.DBusCallFlags.NONE, 2000, None)
            self.agent_ok = True
        except GLib.Error as e:
            self.status = f"Pairing agent unavailable: {nice(e)}"

    def unregister_agent(self):
        if self.agent_ok:
            try:
                BUS.call_sync(BLUEZ, "/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent",
                              GLib.Variant("(o)", (AGENT_PATH,)), None,
                              Gio.DBusCallFlags.NONE, 1000, None)
            except GLib.Error:
                pass

    def on_agent_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        args = params.unpack()
        ours = bool(args) and args[0] in self.pairing  # only answer pairings we started
        ok = lambda: invocation.return_value(None)
        reject = lambda: invocation.return_dbus_error("org.bluez.Error.Rejected", "Rejected")

        if method == "RequestConfirmation":
            if not ours:
                return reject()
            self.set_status(f"Pairing code {args[1]:06d}. Confirm it on the device if asked.")
            ok()
        elif method in ("RequestAuthorization", "AuthorizeService"):
            ok() if ours else reject()
        elif method == "DisplayPasskey":
            self.set_status(f"Type {args[1]:06d} on the device, then press Enter.")
            ok()
        elif method == "DisplayPinCode":
            self.set_status(f"Type {args[1]} on the device, then press Enter.")
            ok()
        elif method == "RequestPinCode":
            # Old devices with a fixed PIN; 0000 is the near-universal default
            if not ours:
                return reject()
            invocation.return_value(GLib.Variant("(s)", ("0000",)))
        elif method == "RequestPasskey":
            invocation.return_dbus_error("org.bluez.Error.Rejected",
                                         "Typing a passkey isn't supported here; use bluetoothctl")
            self.set_status("This device wants a typed passkey; pair it with bluetoothctl.")
        else:  # Release, Cancel
            ok()

    def cleanup(self):
        if self.scanning and self.adapter:
            try:
                BUS.call_sync(BLUEZ, self.adapter[0], ADAPTER, "StopDiscovery", None, None,
                              Gio.DBusCallFlags.NONE, 1000, None)
            except GLib.Error:
                pass
        self.unregister_agent()


if __name__ == "__main__":
    run(BluetoothPopup, CSS)
