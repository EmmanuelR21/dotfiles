#!/usr/bin/env bash
#
# Battery notifications: low / critical warnings and charger plugged / unplugged.
# Started from autostart.lua, only on machines with a battery (host.has_battery).
#
# All notifications share one dunst stack tag, so a new one replaces the old one
# (e.g. plugging in the charger replaces the "Battery critical" warning).

LOW=20      # % -> normal warning
CRITICAL=10 # % -> critical warning, stays until dismissed or the charger is plugged in
INTERVAL=5  # seconds between checks (just reads a few tiny files)

# Only ever run one copy (e.g. if started by hand while autostart's copy is running)
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/battery-notify.lock"
flock -n 9 || exit 0

PS=/sys/class/power_supply

BAT=""
for d in "$PS"/BAT*; do
    [[ -r $d/capacity ]] && { BAT=$d; break; }
done
[[ -n $BAT ]] || exit 0

# Prefer the AC adapter's "online" flag; fall back to the battery's status
# on machines that don't expose one.
AC=""
for d in "$PS"/*; do
    [[ -r $d/type && -r $d/online && "$(<"$d/type")" == Mains ]] && { AC=$d; break; }
done

# Prints 1 if plugged in, 0 if not, nothing if unknown right now.
plugged() {
    if [[ -n $AC ]]; then
        cat "$AC/online"
        return
    fi
    case "$(<"$BAT/status")" in
        Discharging) echo 0 ;;
        Charging | Full | "Not charging") echo 1 ;;
    esac
}

# "About 1 h 25 min left", or nothing if the battery doesn't report it.
time_left() {
    local now rate mins
    if [[ -r $BAT/energy_now && -r $BAT/power_now ]]; then
        now=$(<"$BAT/energy_now") rate=$(<"$BAT/power_now")
    elif [[ -r $BAT/charge_now && -r $BAT/current_now ]]; then
        now=$(<"$BAT/charge_now") rate=$(<"$BAT/current_now")
    else
        return
    fi
    ((rate > 0)) || return
    mins=$((now * 60 / rate))
    if ((mins >= 60)); then
        echo "About $((mins / 60)) h $((mins % 60)) min left"
    else
        echo "About $mins min left"
    fi
}

# breeze-dark has battery-000 ... battery-100 (and -charging variants) in steps of 10
icon() {
    local name
    printf -v name 'battery-%03d' $(($1 / 10 * 10))
    [[ $2 == 1 ]] && name+="-charging"
    echo "$name"
}

notify() { # urgency icon summary body
    notify-send -a Battery -u "$1" -i "$2" -h string:x-dunst-stack-tag:battery "$3" "$4"
}

prev=""     # plugged state at the last check ("" = first check, don't announce)
warned=none # none | low | critical, so each warning fires once per discharge

while true; do
    cap=$(<"$BAT/capacity")
    now=$(plugged)

    if [[ -n $now ]]; then
        if [[ -n $prev && $now != "$prev" ]]; then
            if ((now)); then
                notify low "$(icon "$cap" 1)" "Charger connected" "$cap% and charging"
            else
                notify low "$(icon "$cap" 0)" "Charger disconnected" "$cap% remaining"
            fi
        fi
        prev=$now

        if ((now)); then
            warned=none
        elif ((cap <= CRITICAL)) && [[ $warned != critical ]]; then
            notify critical battery-caution "Battery critical: $cap%" \
                "Plug in your charger now. $(time_left)"
            warned=critical
        elif ((cap <= LOW)) && [[ $warned == none ]]; then
            notify normal battery-low "Battery low: $cap%" \
                "Consider plugging in your charger. $(time_left)"
            warned=low
        fi
    fi

    sleep "$INTERVAL"
done
