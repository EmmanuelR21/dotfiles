# Hyprland

```bash
sudo pacman -S hyprland
```

## NVIDIA steps (If Applicable)

Need to install the open source/proprietary drivers.

Choose one of the following commands, if one isnt working, try another.

**NOTE**: dkms driver package will require `linux-headers`

### Open Source Drivers

```bash
sudo pacman -S nvidia-open-dkms linux-headers
```

### Proprietary Drivers

```bash
sudo pacman -S nvidia-dkms linux-headers
```

### Extra

```bash
# Needed for both Open Source and Proprietary Drivers
sudo pacman -S nvidia-utils egl-wayland
```

```bash
# Needed for Multilib repo 32-bit applications
sudo pacman -S lib32-nvidia-utils
```

You will likely want gamescope for some of your games.

```bash
sudo pacman -S gamescope
```

## Post NVIDIA

Make sure to install `kitty`/`ghostty`. Kitty is within the default hyprland config, if you choose to use another, just make sure to update the hyprland.lua config in `~/.config/` to use whatever terminal you use.

You will also need these fonts for waybar's text, icons and symbols:

- `gnu-free-fonts` (FreeSans)
- `otf-font-awesome`
- `ttf-nerd-fonts-symbols`

```bash
# Login manager, brightness control and fonts
sudo pacman -S ly brightnessctl gnu-free-fonts otf-font-awesome ttf-nerd-fonts-symbols
```

Enable ly:

```bash
sudo systemctl enable ly@tty1.service
```

For screenshot abilities:

```bash
sudo pacman -S grim slurp swappy
```

The configuration for this to work is already within the hyprland.lua config file.

**You can now reboot.**

# Configs

## Prerequisites

You will need

- hyprlauncher (app launcher)
- browser (default: librewolf)
- git
- openssh (for seting up Github ssh keys)

You will also need:

- hyprpolkitagent (authentication agent)
- xdg-desktop-portal-hyprland (implements things such as opening file pickers, screen sharing etc.)
- qt5-wayland (QT Support)
- qt6-wayland (QT Support)
- dolphin (file manager)
- dunst (notification daemon)

```bash
sudo pacman -S hyprlauncher librewolf git openssh hyprpolkitagent xdg-desktop-portal-hyprland qt5-wayland qt6-wayland dolphin dunst
```

**OPTIONAL: Install Paru**

## Installation

You will also need:

1. waybar: Status bar
2. hyprpaper: Wallpaper utility
3. hypridle: Idle management
4. hyprlock: Lockscreen
5. wireplumber: Audio session manager
    - Pipewire will need a few more packages to work properly.

    1. pipewire-audio: Meta packages
    2. pipewire-alsa: ALSA support
    3. pipewire-pulse: PulseAudio support
6. hyprsunset: Color temperature control
7. hyprshutdown: Graceful shutdown utility

```bash
sudo pacman -S waybar hyprpaper hypridle hyprlock wireplumber hyprsunset hyprshutdown pipewire-audio pipewire-alsa pipewire-pulse
```

## Apply Configs

```bash
# Assuming you have this repository in your home directory
cd ~/dotfiles
git pull
cp -r ~/dotfiles/hyprland-configs/hypr ~/dotfiles/hyprland-configs/waybar ~/.config/
```

## Wallpapers

`hyprpaper.conf` and `hyprlock.conf` don't point at a specific image. They point at two fixed names:

- `~/Pictures/wallpapers/selected/background.png` (desktop)
- `~/Pictures/wallpapers/selected/lockscreen.png` (lock screen)

These are **symlinks** (shortcuts) to real images in `~/Pictures/wallpapers/`. Each machine sets its own links, so the configs stay identical on every device while the wallpapers can differ.

### First-time setup

```bash
mkdir -p ~/Pictures/wallpapers/selected
ln -sf ../dark_white_mountains.png ~/Pictures/wallpapers/selected/background.png
ln -sf ../night_gas_station.png ~/Pictures/wallpapers/selected/lockscreen.png
```

### Changing wallpapers

```bash
# Desktop (restart hyprpaper to apply)
ln -sf ../oil_painting.png ~/Pictures/wallpapers/selected/background.png
pkill hyprpaper; hyprpaper & disown

# Lock screen (applies next time you lock)
ln -sf ../night_gas_station.png ~/Pictures/wallpapers/selected/lockscreen.png
```

`../` means the image is one folder up, in `~/Pictures/wallpapers/`.

To see which images are currently selected:

```bash
ls -l ~/Pictures/wallpapers/selected/
```

## Per-Device Settings

The same configs work on every machine. Device differences are detected automatically from the hardware, so nothing needs changing per device.

`hypr/host.lua` detects:

| Value | Meaning | Detected from |
| --- | --- | --- |
| `host.profile` | `"desktop"` or `"laptop"` | `/sys/class/dmi/id/chassis_type` or a battery |
| `host.has_battery` | Has a battery | `/sys/class/power_supply/BAT0` (or `BAT1`) |
| `host.has_nvidia` | NVIDIA driver loaded | `/proc/driver/nvidia/version` |

What uses it:

- **`monitors.lua`**: desktop gets `DP-1` @ 180Hz, laptop gets `eDP-1` @ scale 1.07. Any other monitor falls back to `preferred` / `auto`.
- **`hyprland.lua`**: NVIDIA env vars only apply if `has_nvidia`. `batteryOpts.lua` (blur off) only loads if `has_battery`, at the end of the file so it overrides earlier settings.
- **Waybar**: the `battery` module is in the shared config. Waybar hides it automatically on machines without a battery.

To check what a machine is detected as:

```bash
cat /sys/class/dmi/id/chassis_type    # 3 = desktop, 9/10 = laptop
ls /sys/class/power_supply/           # BAT0 = has battery
```

To change a device's monitor, edit its block in `hypr/monitors.lua` (`hyprctl monitors all` lists monitor names and modes).

## New Device Checklist

1. Install packages (see above) and clone this repo to `~/dotfiles`.
2. Create the wallpaper links (see [Wallpapers](#wallpapers)).
3. Copy configs (see [Apply Configs](#apply-configs)).
4. Log out and back in, then verify:
    - `hyprctl monitors` shows the right monitor and scale
    - `hyprctl configerrors` prints nothing
    - `echo $LIBVA_DRIVER_NAME` prints `nvidia` on NVIDIA machines, nothing otherwise

## Syncing Changes Between Devices

Use the sync script:

```bash
~/dotfiles/scripts/sync-configs.sh
```

It asks which direction to copy:

1. **This device -> dotfiles**: after editing configs on a machine. Then commit and push.
2. **Dotfiles -> this device**: on the other machine. Offers to `git pull` first, and to reload Hyprland and waybar after.

How it works:

- Shows a preview (`+` added, `-` deleted, `~` changed) and asks before changing anything.
- Mirrors `hypr/` and `waybar/` exactly, so deleted or renamed files are removed on the other side too.
- Backs up whatever it replaces to `~/.local/state/dotfiles-sync/backups/` (keeps the last 10).
- Warns before you lose work:
    - **Option 1** when the repo has changes this device hasn't applied yet (e.g. you pulled from the other machine). Copying would undo them, so run option 2 first.
    - **Option 2** when this device has edits that were never copied to the repo.
- Don't run it with `sudo`.

Because it mirrors, any config file that should exist on both machines must exist on both (e.g. `batteryOpts.lua` stays on the PC even though only the laptop loads it). Check the `-` lines in the preview before confirming.

## Epilogue

If you are using gamescope, this is the command to include within the steam properties tab, wit the first values tweaked to the Desktop Monitor resolution & refresh rate:

`gamescope -W 1920 -H 1080 -r 180 --adaptive-sync --force-grab-cursor -f -- %command%`
