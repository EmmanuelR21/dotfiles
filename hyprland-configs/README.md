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

## Post NVIDIA

Make sure to install `kitty`/`ghostty`. Kitty is within the default hyprland config, if you choose to use another, just make sure to update the hyprland.lua config in `~/.config/` to use whatever terminal you use.

```bash
# Login manager and brightness control
sudo pacman -S ly brightnessctl
```

Enable ly:

```bash
sudo systemctl enable ly@tty1.service
```

**You can now reboot.**

# Configs

## Prerequisites

You will need

- hyprlauncher (app launcher)
- browser
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
sudo pacman -S hyprlauncher firefox git openssh hyprpolkitagent xdg-desktop-portal-hyprland qt5-wayland qt6-wayland dolphin dunst
```

**OPTIONAL: Install Paru**

## Installation

The following command installs all necessary packages.

```bash
sudo pacman -S waybar hyprpaper hypridle hyprlock dunst wireplumber hyprsunset otf-font-awesome
```

1. waybar: Status bar
2. hyprpaper: Wallpaper utility
3. hypridle: Idle management
4. hyprlock: Lockscreen
5. dunst: Notification daemon
6. wireplumber: Audio session manager
7. hyprsunset: Color temperature control
8. otf-font-awesome: Icons and symbols

## Apply Configs

```bash
# Assuming you have this repository in your home directory
cp -r ~/dotfiles/hyprland-configs/* ~/.config/
```
