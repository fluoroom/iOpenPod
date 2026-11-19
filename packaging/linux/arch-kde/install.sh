#!/usr/bin/env bash
# Install the fluoroom iOpenPod fork on Arch Linux with KDE Plasma.
set -euo pipefail

APP_ID="io.github.fluoroom.iOpenPod"
TOOL_NAME="iopenpod"
FORK_URL="https://github.com/fluoroom/iOpenPod.git"
DEFAULT_SOURCE="git+${FORK_URL}@main"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
DESKTOP_DIR="${DATA_HOME}/applications"
ICON_THEME_DIR="${DATA_HOME}/icons/hicolor"
ICON_DIR="${ICON_THEME_DIR}/256x256/apps"
DESKTOP_FILE="${DESKTOP_DIR}/${APP_ID}.desktop"
ICON_FILE="${ICON_DIR}/${APP_ID}.png"
ICON_SOURCE="${REPO_ROOT}/website/iopenpod-icon-256.png"

LEGACY_DESKTOP="${DESKTOP_DIR}/io.github.therealsavi.iOpenPod.desktop"
LEGACY_ICON="${ICON_DIR}/io.github.therealsavi.iOpenPod.png"
LEGACY_LINK="${HOME}/.local/bin/iOpenPod"

SOURCE="${DEFAULT_SOURCE}"
ASSUME_YES=0

usage() {
    cat <<'EOF'
Usage: install.sh [options]

Install the fluoroom iOpenPod fork for the current user on Arch Linux/KDE.

Options:
  --local       Install this checkout instead of the fork's main branch.
  --yes, -y     Do not prompt before installing system packages.
  --help, -h    Show this help.

The app is installed with `uv tool install`, so the `iopenpod` launcher is
placed in ~/.local/bin. A desktop entry and icon are installed for KDE Plasma.
User settings, Backups and logs are never moved or deleted.
EOF
}

while (($#)); do
    case "$1" in
        --local) SOURCE="${REPO_ROOT}" ;;
        --yes | -y) ASSUME_YES=1 ;;
        --help | -h)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

confirm() {
    if ((ASSUME_YES)); then
        return 0
    fi
    local answer
    read -r -p "$1 [y/N] " answer
    [[ "${answer}" == [yY] || "${answer}" == [yY][eE][sS] ]]
}

warn_platform() {
    [[ -r /etc/os-release ]] || return 0
    # shellcheck source=/dev/null
    . /etc/os-release
    if [[ "${ID:-}" != "arch" && "${ID_LIKE:-}" != *arch* ]]; then
        printf 'Warning: this installer targets Arch Linux (detected %s).\n' \
            "${PRETTY_NAME:-unknown}" >&2
    fi
    if [[ "${XDG_CURRENT_DESKTOP:-}" != *KDE* && "${KDE_FULL_SESSION:-}" != "true" ]]; then
        printf 'Warning: this installer targets KDE Plasma; the desktop entry is still installed.\n' >&2
    fi
}

install_system_dependencies() {
    local -a missing=()
    command -v ffmpeg >/dev/null 2>&1 || missing+=(ffmpeg)
    command -v ffprobe >/dev/null 2>&1 || missing+=(ffmpeg)
    command -v fpcalc >/dev/null 2>&1 || missing+=(chromaprint)

    if ((${#missing[@]})); then
        mapfile -t missing < <(printf '%s\n' "${missing[@]}" | sort -u)
        if confirm "Install missing media tools (${missing[*]}) with pacman?"; then
            local -a pacman_args=(--needed)
            ((ASSUME_YES)) && pacman_args+=(--noconfirm)
            sudo pacman -S "${pacman_args[@]}" "${missing[@]}"
        else
            printf 'Continuing without %s. Sync will report the missing tools.\n' \
                "${missing[*]}" >&2
        fi
    fi

    if ! command -v uv >/dev/null 2>&1; then
        if confirm "uv is required. Install it with pacman?"; then
            local -a pacman_args=(--needed)
            ((ASSUME_YES)) && pacman_args+=(--noconfirm)
            sudo pacman -S "${pacman_args[@]}" uv
        else
            printf 'uv is required: https://docs.astral.sh/uv/getting-started/installation/\n' >&2
            exit 1
        fi
    fi
}

remove_previous_install() {
    # Remove the manually installed portable launcher and desktop entry that
    # pointed at the old checkout-shaped application directory.
    rm -f -- "${LEGACY_LINK}" "${LEGACY_DESKTOP}" "${LEGACY_ICON}"

    # Replace any earlier tool install so the selected source is authoritative.
    uv tool uninstall "${TOOL_NAME}" >/dev/null 2>&1 ||
        uv tool uninstall "iOpenPod" >/dev/null 2>&1 ||
        true
}

install_desktop_entry() {
    install -d -- "${DESKTOP_DIR}" "${ICON_DIR}"

    if [[ -f "${ICON_SOURCE}" ]]; then
        install -m644 -- "${ICON_SOURCE}" "${ICON_FILE}"
    else
        printf 'Warning: icon not found at %s\n' "${ICON_SOURCE}" >&2
    fi

    cat >"${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Type=Application
Name=iOpenPod
Comment=Manage your iPod media library without iTunes (fluoroom fork)
Exec="${HOME}/.local/bin/${TOOL_NAME}"
TryExec="${HOME}/.local/bin/${TOOL_NAME}"
Icon=${APP_ID}
Categories=AudioVideo;Audio;Utility;
Keywords=iPod;Music;Sync;
Terminal=false
StartupNotify=true
StartupWMClass=iOpenPod
EOF

    if [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
        :
    fi
}

refresh_caches() {
    command -v update-desktop-database >/dev/null 2>&1 &&
        update-desktop-database "${DESKTOP_DIR}" >/dev/null 2>&1 || true

    if command -v kbuildsycoca6 >/dev/null 2>&1; then
        kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
    elif command -v kbuildsycoca5 >/dev/null 2>&1; then
        kbuildsycoca5 --noincremental >/dev/null 2>&1 || true
    fi

    if command -v gtk-update-icon-cache >/dev/null 2>&1 &&
        [[ -d "${ICON_THEME_DIR}" ]]; then
        gtk-update-icon-cache -f -t "${ICON_THEME_DIR}" >/dev/null 2>&1 || true
    fi
}

warn_platform
install_system_dependencies
remove_previous_install

printf 'Installing iOpenPod from %s\n' "${SOURCE}"
uv tool install --force "${SOURCE}"

install_desktop_entry
refresh_caches

if ! "${HOME}/.local/bin/${TOOL_NAME}" --version; then
    printf 'iOpenPod was installed, but the launcher did not report a version.\n' >&2
fi

cat <<EOF

iOpenPod is installed.
  Launcher: ${HOME}/.local/bin/${TOOL_NAME}
  Desktop:  ${DESKTOP_FILE}

If ~/.local/bin is not on your PATH, add it or launch iOpenPod from the
application menu.
EOF
