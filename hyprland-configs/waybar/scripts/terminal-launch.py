#!/usr/bin/env python3
"""Open a terminal as a floating, centered window on Hyprland.

    terminal-launch.py CLASSES SIZE -- TERMINAL-ARGV...

CLASSES is a comma-separated list of window classes the terminal may use,
SIZE is "W H". Started by popup_common.run_in_terminal, detached from the
popup so the popup can close right away.

Launch rules (float/size/center) only reach a window if it belongs to the
process Hyprland spawned. Terminals that hand new windows to an already
running instance (gnome-terminal, footclient, kitty --single-instance...)
escape them, so this also waits for the window's "openwindow" event on
Hyprland's event socket and floats it by address if it came up tiled. It
blocks on the socket (no polling) and gives up after TIMEOUT seconds.

Standard library only: no GTK import, so it starts fast.
"""

import json
import os
import shlex
import socket
import subprocess
import sys
import time

TIMEOUT = 5


def hyprctl(*args):
    try:
        return subprocess.run(
            ["hyprctl", *args], capture_output=True, text=True, timeout=2, check=False
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def event_socket():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        return None
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(os.path.join(runtime, "hypr", sig, ".socket2.sock"))
    except OSError:
        s.close()
        return None
    return s


def wait_for_window(sock, classes):
    """Address of the next opened window with one of these classes, or None."""
    deadline = time.monotonic() + TIMEOUT
    buf = b""
    while (left := deadline - time.monotonic()) > 0:
        sock.settimeout(left)
        try:
            data = sock.recv(4096)
        except OSError:  # timeout
            return None
        if not data:
            return None
        buf += data
        *lines, buf = buf.split(b"\n")
        for line in lines:
            if not line.startswith(b"openwindow>>"):
                continue
            # openwindow>>ADDRESS,WORKSPACE,CLASS,TITLE
            parts = line[12:].decode(errors="replace").split(",", 3)
            if len(parts) >= 3 and parts[2].lower() in classes:
                return "0x" + parts[0]
    return None


def is_floating(addr):
    try:
        for c in json.loads(hyprctl("clients", "-j") or "[]"):
            if c.get("address") == addr:
                return c.get("floating", False)
    except ValueError:
        pass
    return False


def main():
    if len(sys.argv) < 5 or sys.argv[3] != "--":
        sys.exit(__doc__)
    classes = {c.lower() for c in sys.argv[1].split(",") if c}
    w, h = sys.argv[2].split()
    argv = sys.argv[4:]

    # Listen before launching, so the event can't be missed
    sock = event_socket()
    # exec: the terminal must be the process Hyprland spawned (rules go by PID)
    cmd = "exec " + shlex.join(argv)
    lua = (
        f"hl.dsp.exec_cmd([==[{cmd}]==], "
        f'{{ float = true, size = "{w} {h}", center = true }})'
    )
    if not sock or hyprctl("dispatch", lua) != "ok":
        if sock:
            sock.close()
        os.execvp(argv[0], argv)  # not on Hyprland: just run it, tiled

    addr = wait_for_window(sock, classes)
    sock.close()
    if not addr or is_floating(addr):
        return
    win = f"address:{addr}"
    for d in (
        f'hl.dsp.window.float({{ window = "{win}", action = "enable" }})',
        f'hl.dsp.window.resize({{ window = "{win}", x = {w}, y = {h} }})',
        f'hl.dsp.window.center({{ window = "{win}" }})',
    ):
        hyprctl("dispatch", d)


if __name__ == "__main__":
    main()
