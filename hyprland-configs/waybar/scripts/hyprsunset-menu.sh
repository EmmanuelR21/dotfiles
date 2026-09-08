#!/usr/bin/env bash

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"

set_temp() {
    pkill hyprsunset
    if [ "$1" != "off" ]; then
        hyprsunset -t "$1" &
    fi
}

case "$1" in
    status)
        if pgrep -x "hyprsunset" > /dev/null; then
            echo "󰌵"
        else
            echo "󰌶"
        fi
        ;;
    menu)
        options="5000K (Warm)\n4000K (Warmer)\n3000K (Night)\nCustom Temperature\nTurn Off"
        chosen=$(echo -e "$options" | rofi -dmenu -p "Hyprsunset")

        case "$chosen" in
            *5000K*) set_temp 5000 ;;
            *4000K*) set_temp 4000 ;;
            *3000K*) set_temp 3000 ;;
            *Custom*)
                custom_temp=$(rofi -dmenu -p "Enter Kelvin (e.g., 4500):")
                if [[ "$custom_temp" =~ ^[0-9]+$ ]]; then
                    set_temp "$custom_temp"
                fi
                ;;
            *Turn\ Off*) set_temp "off" ;;
        esac
        ;;
esac
