#!/usr/bin/env bash
#
# Volume / mic / brightness keys: change the value, then show it in a dunst
# pop-up with a level bar. Called from binds.lua.
#
#   osd.sh volume up|down|mute
#   osd.sh mic mute
#   osd.sh brightness up|down
#
# Every pop-up uses the "osd" stack tag, so holding a key updates one pop-up in
# place instead of stacking new ones. The [osd] rule in dunstrc styles them and
# keeps them out of notification history.

STEP=5

notify() { # app icon summary [value]
    local args=(-a "$1" -u low -i "$2" -h string:x-dunst-stack-tag:osd)
    [[ -n $4 ]] && args+=(-h "int:value:$4")
    notify-send "${args[@]}" "$3"
}

volume() {
    local sink=@DEFAULT_AUDIO_SINK@ out pct icon
    case "$1" in
        up) wpctl set-volume -l 1 "$sink" "$STEP%+" ;;
        down) wpctl set-volume "$sink" "$STEP%-" ;;
        mute) wpctl set-mute "$sink" toggle ;;
        *) exit 1 ;;
    esac

    out=$(wpctl get-volume "$sink") || exit 0 # e.g. "Volume: 0.65 [MUTED]"
    pct=$(awk '{ printf "%d", $2 * 100 + 0.5 }' <<<"$out")

    if [[ $out == *MUTED* ]]; then
        notify Volume audio-volume-muted "Muted" "$pct"
        return
    fi
    if ((pct < 34)); then icon=audio-volume-low
    elif ((pct < 67)); then icon=audio-volume-medium
    else icon=audio-volume-high
    fi
    notify Volume "$icon" "$pct%" "$pct"
}

mic() {
    local source=@DEFAULT_AUDIO_SOURCE@
    [[ $1 == mute ]] || exit 1
    wpctl set-mute "$source" toggle

    if [[ "$(wpctl get-volume "$source")" == *MUTED* ]]; then
        notify Microphone microphone-sensitivity-muted "Muted"
    else
        notify Microphone microphone-sensitivity-high "On"
    fi
}

brightness() {
    local out class pct icon
    case "$1" in
        up) out=$(brightnessctl -m -e4 -n2 set "$STEP%+") ;;
        down) out=$(brightnessctl -m -e4 -n2 set "$STEP%-") ;;
        *) exit 1 ;;
    esac

    # e.g. "intel_backlight,backlight,1200,50%,2400". Only show it for real
    # screen backlights (desktops without one have nothing to show).
    IFS=, read -r _ class _ pct _ <<<"$out"
    [[ $class == backlight ]] || exit 0
    pct=${pct%\%}

    if ((pct < 50)); then icon=brightness-low; else icon=brightness-high; fi
    notify Brightness "$icon" "$pct%" "$pct"
}

case "$1" in
    volume | mic | brightness) "$1" "$2" ;;
    *)
        echo "usage: $0 volume up|down|mute | mic mute | brightness up|down" >&2
        exit 1
        ;;
esac
