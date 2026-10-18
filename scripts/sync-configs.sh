#!/usr/bin/env bash
#
# Sync Hyprland configs (hypr/ and waybar/) between this device and the
# dotfiles repo, in either direction.
#
# Folders are mirrored exactly: files deleted or renamed on one side are
# removed on the other. Changes are previewed before anything is touched,
# and whatever gets replaced is backed up first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
DOTFILES="$(dirname "$SCRIPT_DIR")"
REPO_DIR="$DOTFILES/hyprland-configs"
DEVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles-sync"
BACKUP_ROOT="$STATE_DIR/backups"
LAST_SYNC="$STATE_DIR/last-sync" # fingerprint of the configs at the last sync on this device
KEEP_BACKUPS=10
FOLDERS=(hypr waybar)

if [[ -t 1 ]]; then
    bold=$'\e[1m' green=$'\e[32m' red=$'\e[31m' yellow=$'\e[33m' reset=$'\e[0m'
else
    bold='' green='' red='' yellow='' reset=''
fi

die() {
    echo "${red}Error:${reset} $*" >&2
    exit 1
}

warn() {
    echo "${yellow}Warning:${reset} $*"
}

# confirm "Question?" [y|n]  -> returns 0 for yes. Second arg is the default.
confirm() {
    local prompt="$1" default="${2:-n}" reply
    if [[ $default == y ]]; then prompt+=" [Y/n] "; else prompt+=" [y/N] "; fi
    read -rp "$prompt" reply
    reply="${reply:-$default}"
    [[ $reply =~ ^[Yy]$ ]]
}

exists() { [[ -e $1 || -L $1 ]]; }

kind() {
    if [[ -L $1 ]]; then echo link; elif [[ -d $1 ]]; then echo dir; else echo file; fi
}

# A single hash of every file's path + contents under root/{hypr,waybar}.
fingerprint() {
    local root="$1" f
    for f in "${FOLDERS[@]}"; do
        [[ -d $root/$f ]] || continue
        (cd "$root" && find "$f" -type f -print0 | sort -z | xargs -0 -r sha256sum)
    done | sha256sum | cut -d' ' -f1
}

save_fingerprint() {
    mkdir -p "$STATE_DIR"
    fingerprint "$1" >"$LAST_SYNC"
}

# Refuse to run if the source is missing/empty (would wipe the destination),
# or if both sides are the same folder (e.g. ~/.config/hypr symlinked to the repo).
check_folder() {
    local src="$1" dest="$2"
    [[ -d $src ]] || die "$src does not exist."
    [[ -n "$(ls -A "$src")" ]] || die "$src is empty, refusing to mirror it."
    if [[ -e $dest && "$(readlink -f "$src")" == "$(readlink -f "$dest")" ]]; then
        die "$src and $dest are the same folder (symlinked?). Nothing to sync."
    fi
}

# Print what would change in dest to make it match src.
# Sets CHANGES=1 if anything differs.
preview() {
    local src="$1" dest="$2" name="$3" line full rel
    if [[ ! -d $dest ]]; then
        echo "  ${green}+ $name/${reset} (whole folder is new)"
        CHANGES=1
        return
    fi
    while IFS= read -r line; do
        CHANGES=1
        if [[ $line =~ ^Only\ in\ (.+):\ (.+)$ ]]; then
            full="${BASH_REMATCH[1]%/}/${BASH_REMATCH[2]}"
            if [[ $full == "$src/"* ]]; then
                echo "  ${green}+ $name/${full#"$src/"}${reset}"
            else
                echo "  ${red}- $name/${full#"$dest/"}${reset}"
            fi
        elif [[ $line =~ ^Files\ (.+)\ and\ .+\ differ$ ]]; then
            rel="${BASH_REMATCH[1]#"$src/"}"
            echo "  ${yellow}~ $name/$rel${reset}"
        elif [[ $line =~ ^File\ (.+)\ is\ a\ .+\ while\ file\ .+$ ]]; then
            rel="${BASH_REMATCH[1]#"$src/"}"
            echo "  ${yellow}~ $name/$rel${reset} (file <-> folder)"
        else
            echo "  ${yellow}~ $line${reset}"
        fi
    done < <(diff -rq "$src" "$dest" || true)
}

# Make dest an exact copy of src. Files are updated in place (not by swapping
# folders) so programs watching the config, like Hyprland, keep working.
mirror() {
    local src="$1" dest="$2" rel
    mkdir -p "$dest"

    # Remove anything in dest that isn't in src, or whose type changed
    # (file / folder / symlink). -depth lists children before their parent folder.
    while IFS= read -r -d '' rel; do
        exists "$dest/$rel" || continue
        if ! exists "$src/$rel" || [[ "$(kind "$src/$rel")" != "$(kind "$dest/$rel")" ]]; then
            rm -rf -- "${dest:?}/$rel"
        fi
    done < <(find "$dest" -mindepth 1 -depth -printf '%P\0')

    cp -a -- "$src/." "$dest/"
}

prune_backups() {
    local old=()
    mapfile -t old < <(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d | sort | head -n -"$KEEP_BACKUPS")
    if ((${#old[@]})); then rm -rf -- "${old[@]}"; fi
}

main() {
    ((EUID != 0)) || die "Don't run this with sudo, it would sync root's configs instead of yours."
    local cmd
    for cmd in diff find cp sha256sum; do
        command -v "$cmd" >/dev/null || die "'$cmd' is not installed (diff is in the 'diffutils' package)."
    done
    [[ -d $REPO_DIR ]] || die "Can't find $REPO_DIR"

    echo "${bold}Hyprland config sync${reset}"
    echo "  Device:   $DEVICE_DIR/{hypr,waybar}"
    echo "  Dotfiles: $REPO_DIR/{hypr,waybar}"
    echo
    echo "  1) This device -> dotfiles   (save this machine's configs to the repo)"
    echo "  2) Dotfiles -> this device   (apply the repo's configs to this machine)"
    echo "  q) Quit"
    echo

    local choice src_root dest_root label
    read -rp "Choose [1/2/q]: " choice
    case "$choice" in
        1) src_root="$DEVICE_DIR" dest_root="$REPO_DIR" label="to-dotfiles" ;;
        2) src_root="$REPO_DIR" dest_root="$DEVICE_DIR" label="to-device" ;;
        *) echo "Nothing done."; exit 0 ;;
    esac
    echo

    if [[ $label == to-device ]] && confirm "Pull the latest changes from git first?" y; then
        git -C "$DOTFILES" pull --ff-only || die "git pull failed. Fix that first, then re-run."
        echo
    fi

    local f
    for f in "${FOLDERS[@]}"; do
        check_folder "$src_root/$f" "$dest_root/$f"
    done

    # Catch the two ways this workflow loses work. Skipped on the first run,
    # before this device has synced once.
    if [[ -f $LAST_SYNC ]]; then
        local last
        last="$(<"$LAST_SYNC")"
        if [[ $label == to-dotfiles && "$(fingerprint "$REPO_DIR")" != "$last" ]]; then
            warn "The dotfiles repo has changed since this device last synced"
            echo "  (e.g. you pulled changes from your other machine). This device doesn't"
            echo "  have those changes, so continuing would undo them in the repo."
            echo "  Usually you want to run option 2 first."
            confirm "Continue anyway?" n || { echo "Nothing done."; exit 0; }
            echo
        elif [[ $label == to-device && "$(fingerprint "$DEVICE_DIR")" != "$last" ]]; then
            warn "This device has config edits that were never copied to dotfiles."
            echo "  Continuing will overwrite them (a backup is kept)."
            echo "  To keep them, quit and run option 1 first."
            confirm "Continue anyway?" n || { echo "Nothing done."; exit 0; }
            echo
        fi
    fi

    CHANGES=0
    echo "${bold}Changes to $dest_root:${reset}"
    for f in "${FOLDERS[@]}"; do
        preview "$src_root/$f" "$dest_root/$f" "$f"
    done

    if ((CHANGES == 0)); then
        echo "  None, already in sync."
        save_fingerprint "$dest_root"
        exit 0
    fi
    echo
    echo "  ${green}+ added${reset}  ${red}- deleted${reset}  ${yellow}~ changed${reset}"
    echo

    confirm "Apply these changes?" n || { echo "Nothing done."; exit 0; }

    local backup_dir
    mkdir -p "$BACKUP_ROOT"
    backup_dir="$(mktemp -d "$BACKUP_ROOT/$(date +%Y-%m-%d_%H-%M-%S)_$label.XXXX")"
    for f in "${FOLDERS[@]}"; do
        if [[ -d $dest_root/$f ]]; then cp -a -- "$dest_root/$f" "$backup_dir/"; fi
        mirror "$src_root/$f" "$dest_root/$f"
    done
    prune_backups
    save_fingerprint "$dest_root"

    echo
    echo "${green}Done.${reset} Previous versions backed up to:"
    echo "  $backup_dir"
    echo

    if [[ $label == to-dotfiles ]]; then
        git -C "$DOTFILES" status --short -- hyprland-configs 2>/dev/null || true
        echo
        echo "Commit with:"
        echo "  cd $DOTFILES && git add -A && git commit -m \"...\" && git push"
    elif [[ -n ${HYPRLAND_INSTANCE_SIGNATURE:-} ]] && confirm "Reload Hyprland and waybar now?" y; then
        hyprctl reload >/dev/null && echo "Hyprland reloaded."
        pkill -SIGUSR2 waybar && echo "Waybar reloaded." || true
    fi
}

main "$@"
