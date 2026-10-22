#!/usr/bin/env python3
"""Wi-Fi / network popup for the Waybar network module.

Click to open, click again to close (see popup_common.py).

Talks to NetworkManager through libnm, so it needs nothing beyond the other
popups' dependencies and networkmanager (which ships libnm). Passwords go straight to NetworkManager over D-Bus, never
on a command line.
"""
import gi
from popup_common import Gdk, GLib, Gtk, Popup, button, label, run

gi.require_version("NM", "1.0")
gi.require_version("Pango", "1.0")
from gi.repository import NM, Pango

# The panel's right edge sits CURSOR_OFFSET px right of the mouse at click time
CURSOR_OFFSET = 24
FALLBACK_MARGIN_RIGHT = 60

MAX_NETWORKS = 10
POLL_MS = 1000  # also the traffic strip's sample rate
TRAFFIC_SAMPLES = 20  # seconds of history in the traffic strip
SPARK = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"  # ▁ .. █
SPARK_FLOOR = 50_000  # B/s; below this the graph stays flat so idle noise doesn't look busy
SCAN_SPIN_MS = 4000  # how long the spinner shows after asking for a scan

# Access point flag bits (NM80211ApFlags / NM80211ApSecurityFlags)
AP_PRIVACY = 0x1
KEY_PSK, KEY_8021X, KEY_SAE = 0x100, 0x200, 0x400

ICON_WIFI, ICON_WIFI_OFF = "\U000f05a9", "\U000f05aa"   # same as the bar
ICON_ETHERNET = "\U000f1616"                            # same as the bar
ICON_EYE, ICON_EYE_OFF = "\U000f0208", "\U000f0209"
# md-wifi-strength-1..4, plus their -lock variants for secured networks
SIGNAL = ["\U000f091f", "\U000f0922", "\U000f0925", "\U000f0928"]
SIGNAL_LOCK = ["\U000f0921", "\U000f0924", "\U000f0927", "\U000f092a"]

SECURITY_LABEL = {"open": "Open", "psk": "WPA2", "sae": "WPA3",
                  "enterprise": "Enterprise", "wep": "WEP"}

# Enterprise (802.1X) login types: (button label, EAP method, inner auth).
# PEAP/MSCHAPv2 is what eduroam and most school/work networks use.
EAP_METHODS = [("PEAP \u00b7 MSCHAPv2", "peap", "mschapv2"),
               ("TTLS \u00b7 PAP", "ttls", "pap"),
               ("TTLS \u00b7 MSCHAPv2", "ttls", "mschapv2")]



# #fe8019 matches #network in style.css; #ffa55c (its hover shade) is used
# for small text so it stays readable on the dark panel.
CSS = """
#panel { padding: 12px 14px; min-width: 340px; }

.head-icon { font-size: 22px; color: #fe8019; min-width: 26px; }
.head-icon.off { color: #7c6f64; }
.title { font-size: 14px; }
.sub, .state, .empty { font-size: 11px; font-weight: normal; color: #8a8f98; }
.section { font-size: 10px; color: #6f747d; margin-top: 2px; }

.net-icon { font-size: 17px; color: #fe8019; min-width: 24px; }
.weak .net-icon { color: #9c6b45; }
.active .state { color: #ffa55c; }

/* Live traffic strip under the active connection: download in the module's
   orange, upload in silver, each with a mini graph of the last 20s */
.traffic { margin-left: 32px; }
.arrow { font-size: 12px; }
.rate { font-size: 11px; color: #e6e6e6; }
.spark { font-size: 10px; font-weight: normal; }
.down .arrow, .down .spark { color: #fe8019; }
.up .arrow, .up .spark { color: #d6dde9; }

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

/* Orange-tinted primary actions (Turn on, Connect, Scan) */
button.accent { background-color: rgba(254, 128, 25, 0.18); }
button.accent:hover { background-color: rgba(254, 128, 25, 0.30); }
button.accent label { color: #ffa55c; }

/* Small icon buttons: "x" to forget a saved network (dusty red on hover)
   and the eye that shows/hides the password */
button.forget, button.eye { min-width: 0; padding: 3px 6px; background-color: transparent; }
button.forget label, button.eye label { font-size: 13px; color: #6f747d; }
button.forget:hover { background-color: rgba(234, 106, 95, 0.15); }
button.forget:hover label { color: #ea6a5f; }
button.eye:hover { background-color: #2a2a2a; }
button.eye:hover label { color: #cfcfcf; }

entry {
    min-height: 0;
    padding: 4px 8px;
    border-radius: 4px;
    border: 1px solid #3c3c3c;
    box-shadow: none;
    background-image: none;
    background-color: #151515;
    color: #ffffff;
    caret-color: #ffa55c;
}
entry:focus { border-color: rgba(254, 128, 25, 0.6); }
entry, entry text { font-weight: normal; }

spinner { color: #ffa55c; }
.status { font-size: 11px; font-weight: normal; color: #e0b44c; }
"""


def nice(err):
    # "GDBus.Error:org.freedesktop.NetworkManager.Foo: Some text" -> "Some text"
    return err.message.split(": ", 1)[-1] if ": " in err.message else err.message


def ssid_of(ap):
    raw = ap.get_ssid() if ap else None
    return NM.utils_ssid_to_utf8(raw.get_data()) if raw else ""


def security_of(ap):
    flags, wpa, rsn = int(ap.get_flags()), int(ap.get_wpa_flags()), int(ap.get_rsn_flags())
    keys = wpa | rsn
    if keys & KEY_8021X:
        return "enterprise"
    if rsn & KEY_SAE and not keys & KEY_PSK:
        return "sae"
    if keys & KEY_PSK:
        return "psk"
    if flags & AP_PRIVACY:
        return "wep"
    return "open"


def bars(strength):
    return 0 if strength < 30 else 1 if strength < 55 else 2 if strength < 75 else 3


def ip4_of(device):
    cfg = device.get_ip4_config()
    addrs = cfg.get_addresses() if cfg else []
    return addrs[0].get_address() if addrs else None


class Traffic:
    """Down/up byte rates for one interface, from /sys/class/net counters."""

    def __init__(self):
        self.iface = None
        self.reset()

    def reset(self):
        self.last = None
        self.rates = 0  # samples that produced a rate (needs two readings)
        self.hist = ([0.0] * TRAFFIC_SAMPLES, [0.0] * TRAFFIC_SAMPLES)

    def follow(self, iface):
        if iface != self.iface:  # switched networks: start the graph fresh
            self.iface = iface
            self.reset()

    def read(self):
        base = f"/sys/class/net/{self.iface}/statistics/"
        try:
            with open(base + "rx_bytes") as rx, open(base + "tx_bytes") as tx:
                return int(rx.read()), int(tx.read())
        except (OSError, ValueError, TypeError):
            return None

    def sample(self):
        now = (self.read(), GLib.get_monotonic_time()) if self.iface else (None, 0)
        if now[0] and self.last and self.last[0]:
            secs = max((now[1] - self.last[1]) / 1e6, 0.001)
            for i, h in enumerate(self.hist):
                h.append(max(0, now[0][i] - self.last[0][i]) / secs)
                del h[0]
            self.rates += 1
        self.last = now

    def view(self):
        """[(current B/s or None, history)] for down and up."""
        return [(h[-1] if self.rates else None, h) for h in self.hist]


def fmt_rate(bps):
    if bps is None:
        return "\u2014"
    if bps < 1000:
        return f"{bps:.0f} B/s"
    if bps < 1_000_000:
        return f"{bps / 1000:.0f} kB/s"
    return f"{bps / 1_000_000:.1f} MB/s"


def sparkline(hist):
    top = max(max(hist), SPARK_FLOOR)
    return "".join(SPARK[min(len(SPARK) - 1, int(v / top * len(SPARK)))] for v in hist)


class NetworkPopup(Popup):
    NAME = "network"

    def __init__(self):
        super().__init__(cursor_offset=CURSOR_OFFSET, fallback_margin=FALLBACK_MARGIN_RIGHT)
        self.client = NM.Client.new(None)
        self.wifi = None          # NM.DeviceWifi, if the machine has one
        self.busy = {}            # ssid -> label shown while an action runs
        self.password_for = None  # network dict whose password row is open
        self.show_password = False
        self.form = {}            # enterprise form values, kept across redraws
        self.scanning = False
        self.status = ""
        self.signature = None
        self.traffic = Traffic()
        self.traffic_widgets = None  # (down, up) labels of the strip, if shown

        # libnm keeps its objects up to date on its own; this just redraws
        # when something changed (the signature check skips no-op rebuilds)
        GLib.timeout_add(POLL_MS, self.poll)
        self.rebuild()
        self.update_traffic()
        if self.wifi and self.client.wireless_get_enabled():
            self.scan()

    # ---- state -------------------------------------------------------------

    def read_state(self):
        devices = self.client.get_devices()
        self.wifi = next((d for d in devices if isinstance(d, NM.DeviceWifi)), None)
        ether = next((d for d in devices if isinstance(d, NM.DeviceEthernet)), None)
        st = {"wifi_on": self.client.wireless_get_enabled(),
              "wifi_hw": self.client.wireless_hardware_get_enabled(),
              "ether": None, "networks": [], "active": None, "ip": None, "bitrate": 0}

        # Interface carrying the default route; the traffic strip follows it
        primary = self.client.get_primary_connection()
        primary_devs = primary.get_devices() if primary else []
        st["primary"] = primary_devs[0].get_ip_iface() if primary_devs else None

        if ether and ether.get_carrier():  # only show ethernet when a cable is in
            up = ether.get_state() == NM.DeviceState.ACTIVATED
            st["ether"] = {"iface": ether.get_iface(), "up": up, "speed": ether.get_speed(),
                           "ip": ip4_of(ether) if up else None}

        if not (self.wifi and st["wifi_on"]):
            return st

        saved = {}
        for conn in self.client.get_connections():
            s = conn.get_setting_wireless()
            if s and s.get_ssid():
                saved[NM.utils_ssid_to_utf8(s.get_ssid().get_data())] = conn

        dev_state = self.wifi.get_state()
        active_ap = self.wifi.get_active_access_point()
        active_ssid = ssid_of(active_ap)
        connecting = NM.DeviceState.PREPARE <= dev_state < NM.DeviceState.ACTIVATED

        networks = {}
        for ap in self.wifi.get_access_points():
            ssid = ssid_of(ap)
            if not ssid:
                continue  # hidden network
            prev = networks.get(ssid)
            if prev and (prev["ap"] == active_ap or prev["strength"] >= ap.get_strength()):
                continue  # one row per name: the connected AP, else the strongest
            is_current = ssid == active_ssid
            networks[ssid] = {
                "ssid": ssid, "ap": ap, "conn": saved.get(ssid),
                "strength": ap.get_strength(), "security": security_of(ap),
                "active": is_current and dev_state == NM.DeviceState.ACTIVATED,
                "connecting": is_current and connecting,
                "band": "5 GHz" if ap.get_frequency() > 4900 else "2.4 GHz",
            }

        st["networks"] = sorted(networks.values(), key=lambda n: (
            not (n["active"] or n["connecting"]), n["conn"] is None, -n["strength"]))[:MAX_NETWORKS]
        st["active"] = next((n for n in st["networks"] if n["active"]), None)
        if st["active"]:
            st["ip"] = ip4_of(self.wifi)
            st["bitrate"] = self.wifi.get_bitrate() // 1000
        return st

    def poll(self):
        if self.password_for is None:  # don't rebuild (and lose focus) mid-typing
            self.rebuild()
        self.update_traffic()
        return True

    def update_traffic(self):
        """Sample byte counters and refresh the strip in place (no rebuild)."""
        self.traffic.sample()
        if self.traffic_widgets:
            for (rate, spark), (bps, hist) in zip(self.traffic_widgets, self.traffic.view()):
                rate.set_text(fmt_rate(bps))
                spark.set_text(sparkline(hist))

    def set_status(self, text):
        self.status = text
        self.rebuild(force=True)

    # ---- UI ----------------------------------------------------------------

    def rebuild(self, force=False):
        st = self.read_state()
        sig = (st["primary"], st["wifi_on"], st["wifi_hw"], self.wifi is not None, str(st["ether"]), st["ip"],
               st["bitrate"], self.scanning, self.status, tuple(sorted(self.busy.items())),
               tuple((n["ssid"], bars(n["strength"]), n["security"], n["conn"] is not None,
                      n["active"], n["connecting"]) for n in st["networks"]))
        if sig == self.signature and not force:
            return
        self.signature = sig

        for child in self.panel.get_children():
            child.destroy()
        self.traffic_widgets = None
        self.traffic.follow(st["primary"])

        if self.wifi:
            self.build_wifi(st)
        if st["ether"]:
            if self.wifi:
                self.panel.pack_start(Gtk.Separator(), False, False, 2)
            self.panel.pack_start(self.ethernet_row(st["ether"]), False, False, 0)
            if st["ether"]["up"] and st["ether"]["iface"] == st["primary"]:
                self.panel.pack_start(self.traffic_strip(), False, False, 0)
        if not self.wifi and not st["ether"]:
            self.panel.pack_start(self.header(ICON_WIFI_OFF, "Network", "No Wi-Fi adapter or cable", None,
                                              off=True), False, False, 0)

        if self.status:
            msg = label(self.status, "status")
            msg.set_line_wrap(True)
            msg.set_max_width_chars(46)
            self.panel.pack_start(msg, False, False, 0)
        self.panel.show_all()

    def build_wifi(self, st):
        on = st["wifi_on"]
        if not st["wifi_hw"]:
            sub = "Blocked by hardware switch"
        elif not on:
            sub = "Wi-Fi is off"
        elif st["active"]:
            parts = [st["active"]["ssid"], st["ip"], f"{st['bitrate']} Mb/s" if st["bitrate"] else None]
            sub = " \u00b7 ".join(p for p in parts if p)
        else:
            sub = "Not connected"
        toggle = button("Turn off" if on else "Turn on", self.toggle_wifi,
                        *(() if on else ("accent",)), sensitive=st["wifi_hw"])
        self.panel.pack_start(self.header(ICON_WIFI if on else ICON_WIFI_OFF, "Wi-Fi", sub, toggle,
                                          off=not on), False, False, 0)
        if not on:
            return

        # The network in use (or being joined) gets its own section on top
        current = [n for n in st["networks"] if n["active"] or n["connecting"]]
        others = [n for n in st["networks"] if n not in current]
        if current:
            self.panel.pack_start(Gtk.Separator(), False, False, 2)
            self.panel.pack_start(label("ACTIVE NETWORK", "section"), False, False, 0)
            for n in current:
                self.panel.pack_start(self.network_row(n), False, False, 0)
                if n["active"] and self.wifi.get_ip_iface() == st["primary"]:
                    self.panel.pack_start(self.traffic_strip(), False, False, 0)

        self.panel.pack_start(Gtk.Separator(), False, False, 2)
        head = Gtk.Box(spacing=8)
        head.pack_start(label("AVAILABLE NETWORKS", "section"), True, True, 0)
        if self.scanning:
            spinner = Gtk.Spinner()
            spinner.start()
            head.pack_start(spinner, False, False, 0)
        head.pack_start(button("Scan", self.scan, "accent", sensitive=not self.scanning), False, False, 0)
        self.panel.pack_start(head, False, False, 0)

        if not others:
            self.panel.pack_start(label("No other networks found yet." if current
                                        else "No networks found yet.", "empty"), False, False, 0)
        for n in others:
            self.panel.pack_start(self.network_row(n), False, False, 0)
            if self.password_for and self.password_for["ssid"] == n["ssid"]:
                form = self.enterprise_form(n) if n["security"] == "enterprise" else self.password_row(n)
                self.panel.pack_start(form, False, False, 0)

    def traffic_strip(self):
        """↓ rate + graph | ↑ rate + graph. Text is filled in by update_traffic."""
        strip = Gtk.Box(spacing=14)
        strip.get_style_context().add_class("traffic")
        widgets = []
        for arrow, cls, (bps, hist) in zip(("\u2193", "\u2191"), ("down", "up"), self.traffic.view()):
            box = Gtk.Box(spacing=4)
            box.get_style_context().add_class(cls)
            rate = label(fmt_rate(bps), "rate")
            rate.set_width_chars(9)  # fixed width so the graph doesn't jiggle
            spark = label(sparkline(hist), "spark")
            for w in (label(arrow, "arrow"), rate, spark):
                box.pack_start(w, False, False, 0)
            strip.pack_start(box, False, False, 0)
            widgets.append((rate, spark))
        self.traffic_widgets = widgets
        return strip

    def header(self, icon, title, sub, action, off=False):
        row = Gtk.Box(spacing=10)
        ic = label(icon, "head-icon")
        if off:
            ic.get_style_context().add_class("off")
        row.pack_start(ic, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.pack_start(label(title, "title"), False, False, 0)
        subl = label(sub, "sub")
        subl.set_ellipsize(Pango.EllipsizeMode.END)
        subl.set_max_width_chars(34)
        text.pack_start(subl, False, False, 0)
        row.pack_start(text, True, True, 0)
        if action:
            row.pack_start(action, False, False, 0)
        return row

    def network_row(self, n):
        row = Gtk.Box(spacing=8)
        ctx = row.get_style_context()
        if n["active"]:
            ctx.add_class("active")
        if bars(n["strength"]) == 0:
            ctx.add_class("weak")
        icons = SIGNAL if n["security"] == "open" else SIGNAL_LOCK
        row.pack_start(label(icons[bars(n["strength"])], "net-icon"), False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        name = label(n["ssid"])
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(22)
        text.pack_start(name, False, False, 0)
        if n["active"]:
            state = f"Connected \u00b7 {n['band']}"
        elif n["connecting"]:
            state = "Connecting\u2026"
        else:
            state = " \u00b7 ".join(p for p in ("Saved" if n["conn"] else None,
                                                  SECURITY_LABEL[n["security"]]) if p)
        text.pack_start(label(state, "state"), False, False, 0)
        row.pack_start(text, True, True, 0)

        busy = self.busy.get(n["ssid"])
        if busy or n["connecting"]:
            action = button(busy or "Connecting\u2026", lambda: None, sensitive=False)
        elif n["active"]:
            action = button("Disconnect", self.disconnect)
        else:
            action = button("Connect", lambda: self.connect_net(n), "accent")
        row.pack_start(action, False, False, 0)

        if n["conn"]:
            row.pack_start(button("\u2715", lambda: self.forget(n), "forget",
                                  sensitive=not busy), False, False, 0)
        return row

    def password_row(self, n):
        row = Gtk.Box(spacing=6)
        row.set_margin_start(32)
        entry = Gtk.Entry()
        entry.set_placeholder_text("Password")
        entry.set_visibility(self.show_password)
        entry.set_hexpand(True)
        entry.connect("activate", lambda e: self.submit_password(n, e.get_text()))
        row.pack_start(entry, True, True, 0)

        def toggle_eye():
            self.show_password = not self.show_password
            entry.set_visibility(self.show_password)
            eye.set_label(ICON_EYE_OFF if self.show_password else ICON_EYE)
        eye = button(ICON_EYE_OFF if self.show_password else ICON_EYE, toggle_eye, "eye")
        row.pack_start(eye, False, False, 0)
        row.pack_start(button("Join", lambda: self.submit_password(n, entry.get_text()), "accent"),
                       False, False, 0)
        GLib.idle_add(entry.grab_focus)
        return row

    def enterprise_form(self, n):
        """Username/password login for 802.1X networks (eduroam, school, work)."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(32)

        def field(key, placeholder, secret=False):
            entry = Gtk.Entry()
            entry.set_placeholder_text(placeholder)
            entry.set_text(self.form.get(key, ""))
            entry.set_visibility(not secret or self.show_password)
            entry.set_hexpand(True)
            entry.connect("changed", lambda e: self.form.__setitem__(key, e.get_text()))
            entry.connect("activate", lambda _e: self.submit_enterprise(n))
            return entry

        user = field("user", "Username (often you@school.edu)")
        box.pack_start(user, False, False, 0)

        pw_row = Gtk.Box(spacing=6)
        pw = field("password", "Password", secret=True)
        pw_row.pack_start(pw, True, True, 0)

        def toggle_eye():
            self.show_password = not self.show_password
            pw.set_visibility(self.show_password)
            eye.set_label(ICON_EYE_OFF if self.show_password else ICON_EYE)
        eye = button(ICON_EYE_OFF if self.show_password else ICON_EYE, toggle_eye, "eye")
        pw_row.pack_start(eye, False, False, 0)
        box.pack_start(pw_row, False, False, 0)

        box.pack_start(field("domain", "Server domain, e.g. school.edu (recommended)"), False, False, 0)
        hint = label("The domain makes sure you're logging in to the real network, "
                     "not a look-alike. Your IT page usually lists it.", "empty")
        hint.set_line_wrap(True)
        hint.set_max_width_chars(44)
        box.pack_start(hint, False, False, 0)

        # Clicking the method button cycles through the login types
        actions = Gtk.Box(spacing=6)
        actions.pack_start(label("Method", "state"), False, False, 0)

        def cycle():
            self.form["method"] = (self.form.get("method", 0) + 1) % len(EAP_METHODS)
            method.set_label(EAP_METHODS[self.form["method"]][0])
        method = button(EAP_METHODS[self.form.get("method", 0)][0], cycle)
        actions.pack_start(method, False, False, 0)
        actions.pack_end(button("Join", lambda: self.submit_enterprise(n), "accent"), False, False, 0)
        box.pack_start(actions, False, False, 0)

        GLib.idle_add((pw if self.form.get("user") else user).grab_focus)
        return box

    def ethernet_row(self, e):
        parts = [e["iface"], e["ip"], f"{e['speed']} Mb/s" if e["speed"] else None]
        sub = " \u00b7 ".join(p for p in parts if p) if e["up"] else f"{e['iface']} \u00b7 cable plugged in, not connected"
        return self.header(ICON_ETHERNET, "Ethernet" + (" \u00b7 Connected" if e["up"] else ""), sub,
                           None, off=not e["up"])

    # ---- actions -----------------------------------------------------------

    def toggle_wifi(self):
        on = not self.client.wireless_get_enabled()
        self.password_for = None

        def done(client, res):
            try:
                client.dbus_set_property_finish(res)
            except GLib.Error as e:
                self.set_status(f"Wi-Fi: {nice(e)}")
                return
            if on:  # radio needs a moment before it can scan
                GLib.timeout_add(1500, lambda: self.scan() and False)
        self.client.dbus_set_property(NM.DBUS_PATH, NM.DBUS_INTERFACE, "WirelessEnabled",
                                      GLib.Variant("b", on), -1, None, done)

    def scan(self):
        if not self.wifi or self.scanning:
            return
        self.scanning = True

        def done(dev, res):
            try:
                dev.request_scan_finish(res)
            except GLib.Error:
                pass  # "scanning not allowed" right after a recent scan; harmless

        def stop():
            self.scanning = False
            self.rebuild()
            return False
        self.wifi.request_scan_async(None, done)
        GLib.timeout_add(SCAN_SPIN_MS, stop)
        self.rebuild()

    def connect_net(self, n):
        self.status = ""
        if n["conn"] or n["security"] == "open":
            self.activate(n)
        elif n["security"] in ("psk", "sae", "enterprise"):
            self.password_for = n
            self.show_password = False
            self.form = {}
            self.rebuild(force=True)
        else:
            self.set_status(f"{SECURITY_LABEL[n['security']]} networks aren't supported here; "
                            "connect with nmtui instead.")

    def submit_enterprise(self, n):
        user, password = self.form.get("user", "").strip(), self.form.get("password", "")
        if not user or not password:
            self.set_status("Enter a username and password.")
            return
        _, eap, phase2 = EAP_METHODS[self.form.get("method", 0)]
        self.activate(n, eap={"eap": eap, "phase2": phase2, "user": user, "password": password,
                              "domain": self.form.get("domain", "").strip()})
        self.form = {}

    def submit_password(self, n, password):
        if len(password) < 8:
            self.set_status("Wi-Fi passwords are at least 8 characters.")
            self.password_for = n  # keep the row open
            return
        self.password_for = None
        self.activate(n, password)

    def activate(self, n, password=None, eap=None):
        """Connect to a saved network, or create + connect a new one."""
        ssid, new = n["ssid"], n["conn"] is None
        self.busy[ssid] = "Connecting\u2026"
        self.password_for = None
        self.rebuild(force=True)

        def done(client, res):
            self.busy.pop(ssid, None)
            try:
                if new:
                    ac = client.add_and_activate_connection_finish(res)
                else:
                    ac = client.activate_connection_finish(res)
            except GLib.Error as e:
                self.set_status(f"{ssid}: {nice(e)}")
                return
            self.watch(ac, ssid, new)
            self.rebuild(force=True)

        ap_path = n["ap"].get_path()
        if not new:
            self.client.activate_connection_async(n["conn"], self.wifi, ap_path, None, done)
            return
        partial = None
        if password is not None:
            partial = NM.SimpleConnection.new()
            sec = NM.SettingWirelessSecurity.new()
            sec.set_property(NM.SETTING_WIRELESS_SECURITY_KEY_MGMT,
                             "sae" if n["security"] == "sae" else "wpa-psk")
            sec.set_property(NM.SETTING_WIRELESS_SECURITY_PSK, password)
            partial.add_setting(sec)
        elif eap is not None:
            partial = NM.SimpleConnection.new()
            sec = NM.SettingWirelessSecurity.new()
            sec.set_property(NM.SETTING_WIRELESS_SECURITY_KEY_MGMT, "wpa-eap")
            partial.add_setting(sec)
            s8 = NM.Setting8021x.new()
            s8.set_property("eap", [eap["eap"]])
            s8.set_property("identity", eap["user"])
            s8.set_property("password", eap["password"])
            s8.set_property("phase2-auth", eap["phase2"])
            if eap["domain"]:
                # Check the server's certificate against the system CA store
                # and the given domain. Without a domain there's no check.
                s8.set_property("system-ca-certs", True)
                s8.set_property("domain-suffix-match", eap["domain"])
            partial.add_setting(s8)
        self.client.add_and_activate_connection_async(partial, self.wifi, ap_path, None, done)

    def watch(self, ac, ssid, new):
        """Follow an activation; report failures and drop new profiles that
        never connected (e.g. a wrong password), so they don't pile up."""
        uuid = ac.get_uuid()

        def on_state(ac, _pspec):
            state = ac.get_state()
            if state == NM.ActiveConnectionState.ACTIVATED:
                ac.disconnect(handler)
                self.set_status("")
            elif state == NM.ActiveConnectionState.DEACTIVATED:
                ac.disconnect(handler)
                reason = ac.get_state_reason()
                if reason == NM.ActiveConnectionStateReason.USER_DISCONNECTED:
                    return  # canceled on purpose
                dev_reason = self.wifi.get_state_reason() if self.wifi else None
                wrong_pw = (reason in (NM.ActiveConnectionStateReason.NO_SECRETS,
                                       NM.ActiveConnectionStateReason.LOGIN_FAILED)
                            or dev_reason in (NM.DeviceStateReason.NO_SECRETS,
                                              NM.DeviceStateReason.SUPPLICANT_DISCONNECT))
                if new:
                    conn = self.client.get_connection_by_uuid(uuid)
                    if conn:
                        conn.delete_async(None, None)
                    self.set_status(f"Couldn't join {ssid}" +
                                    (": wrong password?" if wrong_pw else "."))
                else:
                    self.set_status(f"Couldn't connect to {ssid}" +
                                    (". Password changed? Forget it (\u2715) and join again."
                                     if wrong_pw else "."))
        handler = ac.connect("notify::state", on_state)

    def disconnect(self):
        def done(dev, res):
            try:
                dev.disconnect_finish(res)
            except GLib.Error as e:
                self.set_status(f"Disconnect: {nice(e)}")
        self.wifi.disconnect_async(None, done)

    def forget(self, n):
        def done(conn, res):
            try:
                conn.delete_finish(res)
            except GLib.Error as e:
                self.set_status(f"{n['ssid']}: {nice(e)}")
        n["conn"].delete_async(None, done)

    def on_key(self, _w, event):
        if event.keyval != Gdk.KEY_Escape:
            return False
        if self.password_for:  # first Esc closes the password / login form
            self.password_for = None
            self.form = {}
            self.rebuild(force=True)
        else:
            Gtk.main_quit()
        return True


if __name__ == "__main__":
    run(NetworkPopup, CSS)
