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
cp -r ~/dotfiles/hyprland-configs/* ~/.config/
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

## Epilogue

If you are using gamescope, this is the command to include within the steam properties tab, wit the first values tweaked to the Desktop Monitor resolution & refresh rate:

`gamescope -W 1920 -H 1080 -r 180 --adaptive-sync --force-grab-cursor -f -- %command%`
