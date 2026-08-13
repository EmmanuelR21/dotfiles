#!/bin/bash

# Define options for Rofi
options="Enable (5000K)\nEnable (4000K)\nEnable (3000K)\nCustom Temperature\nDisable"

# Show rofi menu
chosen=$(echo -e "$options" | rofi -dunst -p "Hyprsunset" -dmenu)

case "$chosen" in
    "Enable (5000K)")
        hyprsunset -t 5000
        ;;
    "Enable (4000K)")
        hyprsunset -t 4000
        ;;
    "Enable (3000K)")
        hyprsunset -t 3000
        ;;
    "Custom Temperature")
        # Prompt user for a custom temperature using rofi's dmenu input
        temp=$(rofi -dunst -p "Enter Temperature (e.g., 4500):" -dmenu)
        if [[ "$temp" =~ ^[0-9]+$ ]]; then
            hyprsunset -t "$temp"
        fi
        ;;
    "Disable")
        pkill hyprsunset
        ;;
esac
