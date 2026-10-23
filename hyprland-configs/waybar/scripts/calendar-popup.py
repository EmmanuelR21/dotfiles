#!/usr/bin/env python3
"""Calendar popup for the Waybar clock.

Click to open, click again to close (see popup_common.py).

Arrows / scroll wheel change the month, clicking the title (or Home) jumps
back to today, Escape closes. Colors follow the clock widget and its old
tooltip calendar (amber today/weekdays, white days, peach month).

Power: nothing polls. The grid is 42 reused labels that only get new text on
month changes; one timer fires at midnight to move the "today" highlight.
"""

import datetime

from popup_common import Gdk, GLib, Gtk, Popup, label, run, set_class

FIRST_WEEKDAY = 6  # 0 = Monday ... 6 = Sunday (en_US, matches the clock locale)
WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
ICON_PREV, ICON_NEXT = "\U000f0141", "\U000f0142"  # chevron left / right

CSS = """
#panel { padding: 10px 12px 12px; }

button {
    padding: 2px 8px;
    border-radius: 4px;
    border: none;
    box-shadow: none;
    outline: none;
    background-image: none;
    background-color: transparent;
    transition: background-color 150ms ease-out;
}
button:hover { background-color: #2a2a2a; }
button.nav label { font-size: 16px; color: #d6dde9; }
.month { font-size: 15px; color: #ffead3; }
.year  { font-size: 15px; color: #8a8f98; font-weight: normal; }

separator { background-color: #333333; min-height: 1px; margin: 2px 0 4px; }

.wday { font-size: 11px; color: #ffcc66; min-width: 32px; }
.wday.weekend { color: #b38f47; }

.day {
    min-width: 32px;
    min-height: 28px;
    border-radius: 14px;
    color: #e6e6e6;
}
.day.weekend { color: #9a9fa8; }
.day.other { color: #4a4a4a; }

/* Today: amber ring + tint, like the clock's amber time */
.day.today {
    color: #ffcc66;
    background-color: rgba(255, 204, 102, 0.16);
    box-shadow: inset 0 0 0 1px rgba(255, 204, 102, 0.6);
}
"""


class CalendarPopup(Popup):
    NAME = "calendar"

    def __init__(self):
        super().__init__(spacing=6, align=Gtk.Align.CENTER)
        self.today = datetime.date.today()
        self.year, self.month = self.today.year, self.today.month

        # Header: < Month Year >   (title click = back to today)
        head = Gtk.Box(spacing=4)
        prev = self.nav_button(ICON_PREV, -1)
        nxt = self.nav_button(ICON_NEXT, 1)
        title = Gtk.Box(spacing=6)
        self.month_lbl = label("", "month")
        self.year_lbl = label("", "year")
        title.pack_start(self.month_lbl, False, False, 0)
        title.pack_start(self.year_lbl, False, False, 0)
        title_btn = Gtk.Button()
        title_btn.add(title)
        title_btn.set_tooltip_text("Back to today")
        title_btn.connect("clicked", lambda *_: self.go_today())
        head.pack_start(prev, False, False, 0)
        head.set_center_widget(title_btn)
        head.pack_end(nxt, False, False, 0)
        self.panel.pack_start(head, False, False, 0)
        self.panel.pack_start(Gtk.Separator(), False, False, 0)

        # Weekday row + 6x7 day grid (fixed 6 rows so the panel never resizes)
        grid = Gtk.Grid(row_spacing=2, column_spacing=2)
        grid.set_column_homogeneous(True)
        for col in range(7):
            wd = (FIRST_WEEKDAY + col) % 7
            wday = label(WEEKDAYS[wd], "wday", xalign=0.5)
            set_class(wday, "weekend", wd >= 5)
            grid.attach(wday, col, 0, 1, 1)
        self.cells = []
        for i in range(42):
            cell = label("", "day", xalign=0.5)
            grid.attach(cell, i % 7, 1 + i // 7, 1, 1)
            self.cells.append(cell)
        self.panel.pack_start(grid, False, False, 0)

        self.panel_box.add_events(
            Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK
        )
        self.panel_box.connect("scroll-event", self.on_scroll)

        self.render()
        self.schedule_midnight()

    def nav_button(self, icon, step):
        b = Gtk.Button(label=icon)
        b.get_style_context().add_class("nav")
        b.connect("clicked", lambda *_: self.shift(step))
        return b

    def render(self):
        first = datetime.date(self.year, self.month, 1)
        self.month_lbl.set_text(first.strftime("%B"))
        self.year_lbl.set_text(str(self.year))
        start = first - datetime.timedelta(days=(first.weekday() - FIRST_WEEKDAY) % 7)
        for i, cell in enumerate(self.cells):
            d = start + datetime.timedelta(days=i)
            cell.set_text(str(d.day))
            set_class(cell, "other", d.month != self.month)
            set_class(cell, "today", d == self.today)
            set_class(cell, "weekend", d.weekday() >= 5)

    def shift(self, step):
        m = self.month - 1 + step
        self.year, self.month = self.year + m // 12, m % 12 + 1
        self.render()

    def go_today(self):
        self.year, self.month = self.today.year, self.today.month
        self.render()

    def schedule_midnight(self):
        now = datetime.datetime.now()
        tomorrow = datetime.datetime.combine(
            now.date() + datetime.timedelta(days=1), datetime.time()
        )
        GLib.timeout_add_seconds(
            int((tomorrow - now).total_seconds()) + 1, self.on_midnight
        )

    def on_midnight(self):
        self.today = datetime.date.today()
        self.render()
        self.schedule_midnight()
        return False

    def on_scroll(self, _w, event):
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            dy = event.get_scroll_deltas()[2]
            if abs(dy) < 0.5:  # ignore tiny touchpad moves
                return True
            self.shift(1 if dy > 0 else -1)
        elif event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.LEFT):
            self.shift(-1)
        elif event.direction in (Gdk.ScrollDirection.DOWN, Gdk.ScrollDirection.RIGHT):
            self.shift(1)
        return True

    def on_key(self, _w, event):
        k = event.keyval
        if k == Gdk.KEY_Escape:
            Gtk.main_quit()
        elif k in (Gdk.KEY_Left, Gdk.KEY_Up, Gdk.KEY_Page_Up):
            self.shift(-1)
        elif k in (Gdk.KEY_Right, Gdk.KEY_Down, Gdk.KEY_Page_Down):
            self.shift(1)
        elif k == Gdk.KEY_Home:
            self.go_today()
        else:
            return False
        return True


if __name__ == "__main__":
    run(CalendarPopup, CSS)
