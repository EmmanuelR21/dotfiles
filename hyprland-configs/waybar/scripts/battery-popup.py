#!/usr/bin/env python3
"""Battery / power profile popup for the Waybar battery module.

Click to open, click again to close (see popup_common.py).

Battery info comes from UPower and profiles from power-profiles-daemon, both
over D-Bus through Gio. Needs: power-profiles-daemon, upower (a dependency of
it), python-gobject, gtk3 and gtk-layer-shell.
"""
from gi.repository import Gio
from popup_common import GLib, Gtk, Popup, label, run

# The panel's right edge sits CURSOR_OFFSET px right of the mouse at click time
CURSOR_OFFSET = 30
FALLBACK_MARGIN_RIGHT = 50

POLL_MS = 5000  # time estimates drift slowly; profile/charge changes are pushed instantly

UPOWER = "org.freedesktop.UPower"
UPOWER_DISPLAY = "/org/freedesktop/UPower/devices/DisplayDevice"
UPOWER_DEVICE = "org.freedesktop.UPower.Device"
PPD = "org.freedesktop.UPower.PowerProfiles"
PPD_PATH = "/org/freedesktop/UPower/PowerProfiles"

# Same icon sets as the bar's battery module (0%, 10%, ... 100%)
ICONS = ["\U000f008e", "\U000f007a", "\U000f007b", "\U000f007c", "\U000f007d", "\U000f007e",
         "\U000f007f", "\U000f0080", "\U000f0081", "\U000f0082", "\U000f0079"]
ICONS_CHARGING = ["\U000f089f", "\U000f089c", "\U000f0086", "\U000f0087", "\U000f0088", "\U000f089d",
                  "\U000f0089", "\U000f089e", "\U000f008a", "\U000f008b", "\U000f0085"]
ICON_AC = "\U000f06a5"  # power-plug, for machines without a battery

# profile id -> (label, icon, one-line description)
PROFILES = {
    "power-saver": ("Power Saver", "\U000f032a",
                    "Lower CPU speeds and quieter fans, for the longest battery life."),
    "balanced": ("Balanced", "\U000f05d1",
                 "Full speed when needed, saves power when idle."),
    "performance": ("Performance", "\U000f04c5",
                    "Maximum speed. Runs warmer and drains the battery faster."),
}
PROFILE_ORDER = ["power-saver", "balanced", "performance"]

# UPower Device.State
CHARGING, DISCHARGING, EMPTY, FULL, PENDING_CHARGE, PENDING_DISCHARGE = 1, 2, 3, 4, 5, 6
STATE_TEXT = {CHARGING: "Charging", DISCHARGING: "On battery", EMPTY: "Empty", FULL: "Fully charged",
              PENDING_CHARGE: "Plugged in, not charging", PENDING_DISCHARGE: "On battery"}

DEGRADED_TEXT = {"lap-detected": "laptop is on your lap",
                 "high-operating-temperature": "running hot"}


# Each profile has its own accent: mint (saver), silver (balanced, the bar's
# battery color family), peach (performance).
CSS = """
#panel { padding: 12px 14px; min-width: 320px; }

.head-icon { font-size: 24px; color: #f0f0f0; min-width: 28px; }
.head-icon.charging { color: #8ec07c; }
.head-icon.low { color: #fb4934; }
.title { font-size: 14px; }
.pct { font-size: 14px; color: #f0f0f0; }
.sub, .detail, .desc { font-size: 11px; font-weight: normal; color: #8a8f98; }
.section { font-size: 10px; color: #6f747d; margin-top: 2px; }
.warn { font-size: 11px; font-weight: normal; color: #e0b44c; }

separator { background-color: #333333; min-height: 1px; }

/* Thin charge bar under the header */
levelbar trough { min-height: 4px; border-radius: 2px; border: none; background-color: #333333; }
levelbar block { min-height: 4px; border-radius: 2px; border: none; }
levelbar block.filled { background-color: #f0f0f0; }
levelbar block.empty { background-color: transparent; }
.charging levelbar block.filled { background-color: #8ec07c; }
.low levelbar block.filled { background-color: #fb4934; }

/* Profile cards: a 3-way segmented picker. Inactive cards are dim; the
   active one lights up in its own accent with a tinted fill. */
button.profile {
    padding: 8px 4px;
    border-radius: 5px;
    border: 1px solid transparent;
    box-shadow: none;
    background-image: none;
    background-color: #262626;
    transition: background-color 150ms ease-out, border-color 150ms ease-out;
}
button.profile:hover { background-color: #2e2e2e; }
button.profile .p-icon { font-size: 20px; color: #6f747d; }
button.profile .p-name { font-size: 11px; color: #9a9fa8; }

button.profile.active.power-saver { background-color: rgba(142, 192, 124, 0.14); border-color: rgba(142, 192, 124, 0.45); }
button.profile.active.balanced    { background-color: rgba(214, 221, 233, 0.10); border-color: rgba(214, 221, 233, 0.40); }
button.profile.active.performance { background-color: rgba(245, 169, 127, 0.14); border-color: rgba(245, 169, 127, 0.45); }
button.profile.active.power-saver label { color: #8ec07c; }
button.profile.active.balanced label    { color: #d6dde9; }
button.profile.active.performance label { color: #f5a97f; }
"""

BUS = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


def get_all(name, path, iface):
    try:
        reply = BUS.call_sync(name, path, "org.freedesktop.DBus.Properties", "GetAll",
                              GLib.Variant("(s)", (iface,)), None, Gio.DBusCallFlags.NONE, 2000, None)
        return reply.unpack()[0]
    except GLib.Error:
        return None


def fmt_duration(secs):
    if not secs or secs <= 0:
        return None
    h, m = divmod(int(secs) // 60, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def battery_path():
    """UPower path of the first real battery (for health info), if any."""
    try:
        reply = BUS.call_sync(UPOWER, "/org/freedesktop/UPower", UPOWER, "EnumerateDevices",
                              None, None, Gio.DBusCallFlags.NONE, 2000, None)
    except GLib.Error:
        return None
    for path in reply.unpack()[0]:
        props = get_all(UPOWER, path, UPOWER_DEVICE) or {}
        if props.get("Type") == 2 and props.get("PowerSupply"):  # 2 = battery
            return path
    return None


class BatteryPopup(Popup):
    NAME = "battery"

    def __init__(self):
        super().__init__(cursor_offset=CURSOR_OFFSET, fallback_margin=FALLBACK_MARGIN_RIGHT)
        self.battery = battery_path()
        self.status = ""
        self.signature = None
        self.refresh_id = None

        # Profile switches (from here, powerprofilesctl or anything else) and
        # charge/plug changes arrive as PropertiesChanged signals
        for sender in (PPD, UPOWER):
            BUS.signal_subscribe(sender, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                 None, None, Gio.DBusSignalFlags.NONE, lambda *_: self.schedule())
        GLib.timeout_add(POLL_MS, self.poll)
        self.rebuild()

    # ---- state -------------------------------------------------------------

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

    def read_state(self):
        disp = get_all(UPOWER, UPOWER_DISPLAY, UPOWER_DEVICE) or {}
        health = get_all(UPOWER, self.battery, UPOWER_DEVICE) if self.battery else None
        ppd = get_all(PPD, PPD_PATH, PPD)
        return {
            "has_battery": bool(disp.get("IsPresent")) and self.battery is not None,
            "pct": round(disp.get("Percentage", 0)),
            "state": disp.get("State", 0),
            "to_empty": disp.get("TimeToEmpty", 0),
            "to_full": disp.get("TimeToFull", 0),
            "rate": disp.get("EnergyRate", 0.0),
            "capacity": round(health.get("Capacity", 0)) if health else None,
            "cycles": health.get("ChargeCycles", -1) if health else -1,
            "ppd": ppd is not None,
            "profile": ppd.get("ActiveProfile") if ppd else None,
            "available": [p["Profile"] for p in ppd.get("Profiles", [])] if ppd else [],
            "degraded": ppd.get("PerformanceDegraded", "") if ppd else "",
            "holds": [(h.get("ApplicationId", "?"), h.get("Profile", "?"))
                      for h in ppd.get("ActiveProfileHolds", [])] if ppd else [],
        }

    # ---- UI ----------------------------------------------------------------

    def rebuild(self):
        st = self.read_state()
        sig = (tuple(sorted((k, str(v)) for k, v in st.items())), self.status)
        if sig == self.signature:
            return
        self.signature = sig

        for child in self.panel.get_children():
            child.destroy()

        self.panel.pack_start(self.header(st), False, False, 0)
        if st["has_battery"]:
            self.panel.pack_start(self.charge_bar(st), False, False, 0)
            details = []
            if st["capacity"]:
                details.append(f"Health {st['capacity']}%")
            if st["cycles"] is not None and st["cycles"] >= 0:
                details.append(f"{st['cycles']} charge cycles")
            if details:
                self.panel.pack_start(label(" \u00b7 ".join(details), "detail"), False, False, 0)

        self.panel.pack_start(Gtk.Separator(), False, False, 2)
        self.panel.pack_start(label("POWER PROFILE", "section"), False, False, 0)
        if not st["ppd"]:
            msg = label("power-profiles-daemon isn't running.\n"
                        "sudo systemctl enable --now power-profiles-daemon", "desc")
            self.panel.pack_start(msg, False, False, 0)
        else:
            self.panel.pack_start(self.profile_picker(st), False, False, 0)
            if st["profile"] in PROFILES:
                desc = label(PROFILES[st["profile"]][2], "desc")
                desc.set_line_wrap(True)
                desc.set_max_width_chars(44)
                self.panel.pack_start(desc, False, False, 0)
            if st["degraded"] and st["profile"] == "performance":
                reason = DEGRADED_TEXT.get(st["degraded"], st["degraded"])
                self.panel.pack_start(label(f"Performance limited: {reason}.", "warn"), False, False, 0)
            for app, prof in st["holds"]:
                name = PROFILES.get(prof, (prof,))[0]
                self.panel.pack_start(label(f"{app} is holding {name}.", "warn"), False, False, 0)

        if self.status:
            msg = label(self.status, "warn")
            msg.set_line_wrap(True)
            msg.set_max_width_chars(44)
            self.panel.pack_start(msg, False, False, 0)
        self.panel.show_all()

    def header(self, st):
        row = Gtk.Box(spacing=10)
        if not st["has_battery"]:
            row.pack_start(label(ICON_AC, "head-icon"), False, False, 0)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            text.pack_start(label("Power", "title"), False, False, 0)
            text.pack_start(label("On AC power, no battery", "sub"), False, False, 0)
            row.pack_start(text, True, True, 0)
            return row

        pct, state = st["pct"], st["state"]
        charging = state in (CHARGING, FULL, PENDING_CHARGE)
        icons = ICONS_CHARGING if state == CHARGING else ICONS
        icon = label(icons[min(10, pct // 10)], "head-icon")
        if state == CHARGING:
            icon.get_style_context().add_class("charging")
        elif pct <= 15 and not charging:
            icon.get_style_context().add_class("low")
        row.pack_start(icon, False, False, 0)

        parts = [STATE_TEXT.get(state, "Battery")]
        if state == CHARGING:
            left = fmt_duration(st["to_full"])
            if left:
                parts.append(f"{left} to full")
        elif state == DISCHARGING:
            left = fmt_duration(st["to_empty"])
            if left:
                parts.append(f"{left} left")
        if st["rate"] >= 0.1 and state in (CHARGING, DISCHARGING):
            parts.append(f"{st['rate']:.1f} W")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.pack_start(label("Battery", "title"), False, False, 0)
        text.pack_start(label(" \u00b7 ".join(parts), "sub"), False, False, 0)
        row.pack_start(text, True, True, 0)
        row.pack_start(label(f"{pct}%", "pct", xalign=1.0), False, False, 0)
        return row

    def charge_bar(self, st):
        box = Gtk.Box()
        if st["state"] == CHARGING:
            box.get_style_context().add_class("charging")
        elif st["pct"] <= 15 and st["state"] not in (FULL, PENDING_CHARGE):
            box.get_style_context().add_class("low")
        bar = Gtk.LevelBar.new_for_interval(0, 100)
        # Drop GTK's default low/high/full offsets so the bar uses our colors
        for name in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
            bar.remove_offset_value(name)
        bar.set_value(st["pct"])
        bar.set_hexpand(True)
        box.pack_start(bar, True, True, 0)
        return box

    def profile_picker(self, st):
        grid = Gtk.Box(spacing=6, homogeneous=True)
        for pid in PROFILE_ORDER:
            if pid not in st["available"]:
                continue  # e.g. no Performance on hardware that can't do it
            name, icon, _ = PROFILES[pid]
            b = Gtk.Button()
            ctx = b.get_style_context()
            for c in ("profile", pid) + (("active",) if pid == st["profile"] else ()):
                ctx.add_class(c)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            inner.pack_start(label(icon, "p-icon", xalign=0.5), False, False, 0)
            inner.pack_start(label(name, "p-name", xalign=0.5), False, False, 0)
            b.add(inner)
            b.connect("clicked", lambda _b, p=pid: self.set_profile(p))
            grid.pack_start(b, True, True, 0)
        return grid

    # ---- actions -----------------------------------------------------------

    def set_profile(self, profile):
        def done(bus, res):
            try:
                bus.call_finish(res)
                self.status = ""
            except GLib.Error as e:
                msg = e.message.split(": ", 1)[-1] if ": " in e.message else e.message
                self.status = f"Couldn't switch profile: {msg}"
            self.schedule()
        BUS.call(PPD, PPD_PATH, "org.freedesktop.DBus.Properties", "Set",
                 GLib.Variant("(ssv)", (PPD, "ActiveProfile", GLib.Variant("s", profile))),
                 None, Gio.DBusCallFlags.NONE, 5000, None, done)


if __name__ == "__main__":
    run(BatteryPopup, CSS)
