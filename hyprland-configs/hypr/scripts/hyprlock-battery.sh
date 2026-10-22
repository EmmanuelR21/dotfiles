#!/usr/bin/env bash
#
# Battery label for hyprlock: Nerd Font icon + percentage (+ status when on AC).
# Prints Pango markup; called from hyprlock.conf every few seconds.
# Prints nothing on machines without a battery, so the label just stays empty.

LOW=20      # % -> amber (same thresholds as battery-notify.sh)
CRITICAL=10 # % -> red

# Needed for bash to expand \U escapes into UTF-8
export LC_ALL=C.UTF-8

ICON_FONT="Symbols Nerd Font"
LOW_COLOR="#c8a064"      # matches capslock_color in hyprlock.conf
CRITICAL_COLOR="#c86464" # matches fail_color in hyprlock.conf

BAT=""
for d in /sys/class/power_supply/BAT*; do
    [[ -r $d/capacity ]] && { BAT=$d; break; }
done
[[ -n $BAT ]] || exit 0

cap=$(<"$BAT/capacity")
status=$(<"$BAT/status")
level=$((cap / 10)) # 0..10

# nf-md-battery_outline, battery_10 ... battery_90, battery
discharging=(
    $'\U000F008E' $'\U000F007A' $'\U000F007B' $'\U000F007C' $'\U000F007D' $'\U000F007E'
    $'\U000F007F' $'\U000F0080' $'\U000F0081' $'\U000F0082' $'\U000F0079'
)
# nf-md-battery_charging_outline, battery_charging_10 ... battery_charging_100
charging=(
    $'\U000F089F' $'\U000F089C' $'\U000F0086' $'\U000F0087' $'\U000F0088' $'\U000F089D'
    $'\U000F0089' $'\U000F089E' $'\U000F008A' $'\U000F008B' $'\U000F0085'
)
plug=$'\U000F06A5' # nf-md-power_plug

# Some batteries keep reporting "Charging" at 100%; treat that as full too.
[[ $status == Charging ]] && ((cap >= 100)) && status=Full

case "$status" in
    Charging) icon=${charging[level]} label="Charging" ;;
    Full) icon=${charging[10]} label="Full" ;;
    "Not charging") icon=$plug label="Plugged in" ;; # e.g. held at a charge limit
    *) icon=${discharging[level]} label="" ;;
esac

color=""
if [[ $status == Discharging ]]; then
    if ((cap <= CRITICAL)); then
        color=$CRITICAL_COLOR
    elif ((cap <= LOW)); then
        color=$LOW_COLOR
    fi
fi

out="<span font_family='$ICON_FONT'>$icon</span>  $cap%"
[[ -n $label ]] && out+="  ·  $label"
[[ -n $color ]] && out="<span foreground='$color'>$out</span>"

echo "$out"
