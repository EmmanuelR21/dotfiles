#!/usr/bin/env python3
"""System popup for the Waybar Arch logo: who/what this machine is, plus
default apps and explicitly installed packages.

Click to open, click again to close (see popup_common.py).

Hardware info is read once at open from /proc and /sys (GPU names from
hwdata's pci.ids). Default apps go through Gio, which reads and writes
~/.config/mimeapps.list, the same file xdg-open, browsers and file managers
use. Clicking a tile lists the installed apps that can open that type.

The Pacman / AUR tabs list explicitly installed repo (pacman -Qen) and
foreign (pacman -Qem, i.e. AUR via paru) packages. Each list is loaded in the
background the first time its tab is opened, never at popup open.
"""
import contextlib
import os
import platform
import pwd
import shutil
import socket

from gi.repository import Gio
from popup_common import GLib, Gtk, Popup, label, run, set_class

ICON_ARCH = "\uf303"
ICON_CPU = "\U000f0ee0"
ICON_GPU = "\U000f08ae"
ICON_RAM = "\U000f035b"
ICON_DISK = "\U000f02ca"
ICON_CHECK = "\U000f012c"

# (tab label, pacman flags, required helper or None)
PACKAGE_TABS = [("Pacman", "-Qen", None), ("AUR", "-Qem", "paru")]

# (label, icon, mime types). Candidates are listed for the first type; the
# chosen app becomes the default for all of them.
CATEGORIES = [
    ("Browser", "\U000f059f", ["x-scheme-handler/https", "x-scheme-handler/http",
                               "text/html", "application/xhtml+xml"]),
    ("PDF", "\U000f0226", ["application/pdf"]),
    ("Documents", "\U000f0219", [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword", "application/vnd.oasis.opendocument.text", "application/rtf"]),
    ("Files", "\U000f024b", ["inode/directory"]),
    ("Images", "\U000f02e9", ["image/png", "image/jpeg", "image/webp", "image/gif"]),
    ("Video", "\U000f0381", ["video/mp4", "video/x-matroska", "video/webm"]),
]

PCI_IDS = "/usr/share/hwdata/pci.ids"
GPU_VENDORS = {"10de": "NVIDIA", "1002": "AMD", "8086": "Intel"}

ACCENT = "#1793d1"  # Arch blue

CSS = f"""
#panel {{ padding: 12px; min-width: 290px; }}

.logo  {{ font-size: 26px; color: {ACCENT}; min-width: 34px; }}
.title {{ font-size: 14px; }}
.sub   {{ font-size: 11px; font-weight: normal; color: #8a8f98; }}

/* Tabs: small caps text, active one in Arch blue with an underline */
button.tab {{ padding: 2px 6px; border-radius: 0; background-color: transparent;
              border-width: 0 0 2px 0; border-color: transparent; }}
button.tab label {{ font-size: 10px; color: #6f747d; }}
button.tab:hover label {{ color: #9a9fa8; }}
button.tab.active {{ border-color: {ACCENT}; }}
button.tab.active label {{ color: {ACCENT}; }}
.count {{ font-size: 10px; font-weight: normal; color: #6f747d; }}

/* Package lists */
.pkgs {{ background-color: #232323; border-radius: 5px; padding: 4px 0; }}
.pkg  {{ padding: 2px 10px; }}
.pkg-name {{ font-size: 12px; font-weight: normal; color: #e6e6e6; }}
.pkg-ver  {{ font-size: 11px; font-weight: normal; color: #6f747d; }}
scrollbar slider {{ min-width: 4px; border-radius: 2px; background-color: #444444; }}
scrollbar {{ background-color: transparent; border: none; }}

/* Hardware: one quiet line each, icon carries the meaning */
.hw-icon {{ font-size: 14px; color: {ACCENT}; min-width: 20px; }}
.hw-val  {{ font-size: 12px; font-weight: normal; color: #d6dde9; }}

separator {{ background-color: #333333; min-height: 1px; }}

button {{
    border-radius: 5px;
    border: 1px solid transparent;
    box-shadow: none;
    outline: none;
    background-image: none;
    transition: background-color 150ms ease-out, border-color 150ms ease-out;
}}

/* Default-app tiles: category on top, current app below */
button.tile {{ padding: 6px 8px; background-color: #262626; }}
button.tile:hover {{ background-color: #2e2e2e; }}
.tile .t-icon {{ font-size: 14px; color: #9a9fa8; }}
.tile .t-name {{ font-size: 10px; color: #8a8f98; }}
.tile .t-app  {{ font-size: 12px; font-weight: normal; color: #e6e6e6; }}
button.tile.open {{ background-color: rgba(23, 147, 209, 0.12); border-color: rgba(23, 147, 209, 0.5); }}
.tile.open .t-icon, .tile.open .t-name {{ color: {ACCENT}; }}

/* App list for the open tile */
.choices {{ background-color: #232323; border-radius: 5px; padding: 4px; }}
button.choice {{ padding: 4px 8px; background-color: transparent; }}
button.choice:hover {{ background-color: #2e2e2e; }}
.choice label {{ font-size: 12px; font-weight: normal; color: #cfcfcf; }}
.choice.current label {{ color: {ACCENT}; font-weight: bold; }}
.empty {{ font-size: 11px; font-weight: normal; color: #6f747d; padding: 4px 8px; }}
"""


# ---------------------------------------------------------------- system info

def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def user_line():
    pw = pwd.getpwuid(os.getuid())
    full = pw.pw_gecos.split(",")[0].strip()
    return full or pw.pw_name, pw.pw_name


def cpu_info():
    model = ""
    for line in read("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            model = line.split(":", 1)[1].strip()
            break
    model = model.replace("(R)", "").replace("(TM)", "")
    for junk in (" Processor", " with Radeon Graphics", " CPU"):
        model = model.replace(junk, "")
    model = " ".join(w for w in model.split() if not w.endswith("-Core"))
    return f"{model} \u00b7 {os.cpu_count()} threads" if model else f"{os.cpu_count()} threads"


def pci_names(wanted):
    """{(vendor, device): name} for the wanted ids, from pci.ids."""
    names, vendor = {}, None
    vendors = {v for v, _ in wanted}
    try:
        with open(PCI_IDS, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                if not line[0].isspace():
                    vendor = line[:4].lower() if line[:4].lower() in vendors else None
                elif vendor and line.startswith("\t") and not line.startswith("\t\t"):
                    dev = line[1:5].lower()
                    if (vendor, dev) in wanted:
                        names[(vendor, dev)] = line[5:].strip()
                        if len(names) == len(wanted):
                            break
    except OSError:
        pass
    return names


def gpu_info():
    ids = []
    for card in sorted(os.listdir("/sys/class/drm")):
        dev = f"/sys/class/drm/{card}/device"
        if not card.startswith("card") or "-" in card or not read(f"{dev}/class").startswith("0x03"):
            continue
        ids.append((read(f"{dev}/vendor")[2:].lower(), read(f"{dev}/device")[2:].lower()))
    names = pci_names(set(ids))
    out = []
    for vendor, device in dict.fromkeys(ids):
        name = names.get((vendor, device), f"device {device}")
        if "[" in name and name.endswith("]"):  # "GA104 [GeForce RTX 3060 Ti]" -> bracket part
            name = name[name.index("[") + 1:-1]
        brand = GPU_VENDORS.get(vendor, "")
        out.append(f"{brand} {name}".strip() if brand and brand not in name else name)
    return out or ["Unknown"]


def mem_info():
    for line in read("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            return f"{int(line.split()[1]) / 1024 / 1024:.1f} GB memory"
    return "Unknown"


def disk_info():
    """Used / free on / (plus /home if it's its own partition), like df -h."""
    out = []
    mounts = ["/"]
    try:
        if os.stat("/home").st_dev != os.stat("/").st_dev:
            mounts.append("/home")
    except OSError:
        pass
    for path in mounts:
        try:
            st = os.statvfs(path)
        except OSError:
            continue
        used = (st.f_blocks - st.f_bfree) * st.f_frsize / 2**30
        free = st.f_bavail * st.f_frsize / 2**30
        where = f" on {path}" if len(mounts) > 1 else ""
        out.append(f"{used:.0f} GB used \u00b7 {free:.0f} GB free{where}")
    return out


# ---------------------------------------------------------------- default apps

def candidates(mime):
    default = Gio.AppInfo.get_default_for_type(mime, False)
    apps = [a for a in Gio.AppInfo.get_all_for_type(mime) if a.should_show()]
    if default and not any(a.get_id() == default.get_id() for a in apps):
        apps.insert(0, default)
    return default, apps


class Tile(Gtk.Button):
    """One default-app category: icon + name on top, current app below."""

    def __init__(self, name, icon, mimes):
        super().__init__()
        self.name, self.mimes = name, mimes
        self.get_style_context().add_class("tile")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        top = Gtk.Box(spacing=6)
        top.pack_start(label(icon, "t-icon"), False, False, 0)
        top.pack_start(label(name.upper(), "t-name"), False, False, 0)
        box.pack_start(top, False, False, 0)
        self.app_lbl = label("", "t-app")
        self.app_lbl.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self.app_lbl.set_max_width_chars(14)
        box.pack_start(self.app_lbl, False, False, 0)
        self.add(box)
        self.refresh()

    def refresh(self):
        self.default, self.apps = candidates(self.mimes[0])
        name = self.default.get_name() if self.default else "Not set"
        self.app_lbl.set_text(name)
        self.set_tooltip_text(name)

    def choose(self, app):
        for mime in self.mimes:
            with contextlib.suppress(GLib.Error):  # keep going for the other types
                app.set_as_default_for_type(mime)
        self.refresh()


class PackageList(Gtk.Box):
    """Scrollable name/version list from one pacman query, loaded on first view."""

    def __init__(self, flags, helper, on_count):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.flags, self.helper, self.on_count = flags, helper, on_count
        self.loaded = False
        self.total = 0
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.rows.get_style_context().add_class("pkgs")
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                    propagate_natural_height=True, max_content_height=220)
        scroll.add(self.rows)
        self.pack_start(scroll, False, False, 0)

    def message(self, text):
        for child in self.rows.get_children():
            child.destroy()
        self.rows.pack_start(label(text, "empty"), False, False, 0)
        self.rows.show_all()

    def load(self):
        if self.loaded:
            return
        self.loaded = True
        if self.helper and not shutil.which(self.helper):
            self.message(f"{self.helper} is not installed")
            return
        self.message("Loading\u2026")
        try:
            proc = Gio.Subprocess.new(["pacman", self.flags], Gio.SubprocessFlags.STDOUT_PIPE
                                      | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            self.message("Couldn't run pacman")
            return
        proc.communicate_utf8_async(None, None, self.on_done)

    def on_done(self, proc, res):
        try:
            _ok, out, _err = proc.communicate_utf8_finish(res)
        except GLib.Error:
            out = ""
        pkgs = [line.split(" ", 1) for line in (out or "").splitlines() if " " in line]
        self.total = len(pkgs)
        if not pkgs:
            self.message("No packages")
        else:
            for child in self.rows.get_children():
                child.destroy()
            for name, ver in pkgs:
                row = Gtk.Box(spacing=8)
                row.get_style_context().add_class("pkg")
                n = label(name, "pkg-name")
                n.set_ellipsize(3)
                row.pack_start(n, True, True, 0)
                row.pack_end(label(ver, "pkg-ver"), False, False, 0)
                self.rows.pack_start(row, False, False, 0)
            self.rows.show_all()
        self.on_count(self)


# ---------------------------------------------------------------- popup

class SystemPopup(Popup):
    NAME = "system"

    def __init__(self):
        super().__init__(spacing=10, align=Gtk.Align.START)
        self.open = None

        # Header: logo, name, login@host · kernel
        name, login = user_line()
        head = Gtk.Box(spacing=10)
        head.pack_start(label(ICON_ARCH, "logo", xalign=0.5), False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_valign(Gtk.Align.CENTER)
        text.pack_start(label(name, "title"), False, False, 0)
        sub = f"{login}@{socket.gethostname()} \u00b7 Linux {platform.release().split('-')[0]}"
        text.pack_start(label(sub, "sub"), False, False, 0)
        head.pack_start(text, True, True, 0)
        self.panel.pack_start(head, False, False, 0)

        # Hardware
        hw = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        rows = [(ICON_CPU, cpu_info())] + [(ICON_GPU, g) for g in gpu_info()] + [(ICON_RAM, mem_info())]
        rows += [(ICON_DISK, d) for d in disk_info()]
        for icon, val in rows:
            row = Gtk.Box(spacing=6)
            row.pack_start(label(icon, "hw-icon"), False, False, 0)
            v = label(val, "hw-val")
            v.set_ellipsize(3)
            v.set_tooltip_text(val)
            row.pack_start(v, True, True, 0)
            hw.pack_start(row, False, False, 0)
        self.panel.pack_start(hw, False, False, 0)

        self.panel.pack_start(Gtk.Separator(), False, False, 0)

        # Tabs: Default apps | Pacman | AUR
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=120, vhomogeneous=False)
        self.tabs = {}
        tab_row = Gtk.Box(spacing=2)
        for name in ["Default apps"] + [t[0] for t in PACKAGE_TABS]:
            b = Gtk.Button(label=name.upper())
            b.get_style_context().add_class("tab")
            b.connect("clicked", lambda _b, n=name: self.show_tab(n))
            tab_row.pack_start(b, False, False, 0)
            self.tabs[name] = b
        self.count = label("", "count", xalign=1)
        tab_row.pack_end(self.count, False, False, 0)
        self.panel.pack_start(tab_row, False, False, 0)
        self.panel.pack_start(self.stack, False, False, 0)

        # Default apps: 2-column tiles, the open one's app list underneath
        apps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        grid.set_column_homogeneous(True)
        for i, cat in enumerate(CATEGORIES):
            tile = Tile(*cat)
            tile.connect("clicked", self.toggle)
            grid.attach(tile, i % 2, i // 2, 1, 1)
        apps.pack_start(grid, False, False, 0)

        self.choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.choices.get_style_context().add_class("choices")
        self.revealer = Gtk.Revealer(transition_duration=150)
        self.revealer.add(self.choices)
        apps.pack_start(self.revealer, False, False, 0)
        self.stack.add_named(apps, "Default apps")

        self.pkg_pages = {}
        for name, flags, helper in PACKAGE_TABS:
            page = PackageList(flags, helper, self.on_count)
            self.stack.add_named(page, name)
            self.pkg_pages[name] = page
        self.show_tab("Default apps")

    def show_tab(self, name):
        self.current = name
        for n, b in self.tabs.items():
            set_class(b, "active", n == name)
        self.stack.set_visible_child_name(name)
        page = self.pkg_pages.get(name)
        if page:
            page.load()
        self.on_count(page)

    def on_count(self, page):
        """Show the visible list's package count next to the tabs."""
        if page is self.pkg_pages.get(self.current):
            self.count.set_text(f"{page.total}" if page and page.total else "")

    def toggle(self, tile):
        if self.open:
            set_class(self.open, "open", False)
        self.open = None if self.open is tile else tile
        if self.open:
            set_class(tile, "open", True)
            self.fill_choices(tile)
        self.revealer.set_reveal_child(self.open is not None)

    def fill_choices(self, tile):
        for child in self.choices.get_children():
            child.destroy()
        if not tile.apps:
            self.choices.pack_start(label("No installed apps for this", "empty"), False, False, 0)
        for app in tile.apps:
            current = bool(tile.default) and app.get_id() == tile.default.get_id()
            box = Gtk.Box(spacing=8)
            icon = app.get_icon()
            if icon:
                box.pack_start(Gtk.Image.new_from_gicon(icon, Gtk.IconSize.MENU), False, False, 0)
            box.pack_start(label(app.get_name()), True, True, 0)
            if current:
                box.pack_start(label(ICON_CHECK), False, False, 0)
            b = Gtk.Button()
            b.add(box)
            b.get_style_context().add_class("choice")
            set_class(b, "current", current)
            b.connect("clicked", lambda _b, a=app: self.pick(tile, a))
            self.choices.pack_start(b, False, False, 0)
        self.choices.show_all()

    def pick(self, tile, app):
        tile.choose(app)
        self.toggle(tile)  # close the list; the tile now shows the new app


if __name__ == "__main__":
    run(SystemPopup, CSS)
