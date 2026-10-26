#!/bin/sh
# Fuzzy-search every open window (all workspaces/monitors) with hyprlauncher's
# dmenu mode and focus the selected one. Most recently used windows come first.
# Note: hyprlauncher 0.1.6 matching is case-sensitive against lowercased text,
# so type queries in lowercase.

list=$(hyprctl clients -j | jq -r '
    sort_by(.focusHistoryID)[]
    | select(.mapped and .focusHistoryID != 0)
    | "\(.address)\t\(.class) — \(.title | gsub("[\t\n]"; " ")) [\(.workspace.name)]"
') || exit 1
[ -n "$list" ] || exit 0

choice=$(printf '%s\n' "$list" | cut -f2- | hyprlauncher --quiet --dmenu | tail -n 1)
[ -n "$choice" ] && [ "$choice" != "Exited without selection" ] || exit 0

addr=$(printf '%s\n' "$list" | C="$choice" awk -F '\t' '{
    d = $0; sub(/^[^\t]*\t/, "", d)
    if (d == ENVIRON["C"]) { print $1; exit }
}')
[ -n "$addr" ] && hyprctl dispatch "hl.dsp.focus({ window = \"address:$addr\" })"
