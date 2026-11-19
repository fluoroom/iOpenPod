#!/usr/bin/env bash
# Remove the fluoroom iOpenPod fork from an Arch Linux/KDE Plasma desktop.
set -euo pipefail

APP_ID="io.github.fluoroom.iOpenPod"
TOOL_NAME="iopenpod"

TOOL_BIN_DIR="${UV_TOOL_BIN_DIR:-${HOME}/.local/bin}"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
DESKTOP_DIR="${DATA_HOME}/applications"
ICON_THEME_DIR="${DATA_HOME}/icons/hicolor"
ICON_DIR="${ICON_THEME_DIR}/256x256/apps"
DESKTOP_FILE="${DESKTOP_DIR}/${APP_ID}.desktop"
ICON_FILE="${ICON_DIR}/${APP_ID}.png"

LEGACY_DESKTOP="${DESKTOP_DIR}/io.github.therealsavi.iOpenPod.desktop"
LEGACY_ICON="${ICON_DIR}/io.github.therealsavi.iOpenPod.png"
LEGACY_LINK="${HOME}/.local/bin/iOpenPod"

PURGE=0
ASSUME_YES=0

usage() {
    cat <<'EOF'
Usage: uninstall.sh [options]

Remove the fluoroom iOpenPod fork from the current user account.

Options:
  --purge       Also delete user settings, logs, caches and Backup Snapshots.
  --yes, -y     Do not prompt before deleting user data with --purge.
  --help, -h    Show this help.

Without --purge, only the application launcher, desktop entry and icon are
removed. User settings, Backups and logs are preserved.
EOF
}

while (($#)); do
    case "$1" in
        --purge) PURGE=1 ;;
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

printf 'Removing iOpenPod application files...\n'
uv tool uninstall "${TOOL_NAME}" >/dev/null 2>&1 ||
    uv tool uninstall "iOpenPod" >/dev/null 2>&1 ||
    true

rm -f -- "${TOOL_BIN_DIR}/${TOOL_NAME}" "${DESKTOP_FILE}" "${ICON_FILE}" "${LEGACY_DESKTOP}" "${LEGACY_ICON}" "${LEGACY_LINK}"
refresh_caches

if ((PURGE)); then
    cat <<EOF

--purge also deletes user data:
  ${HOME}/.config/iOpenPod
  ${HOME}/.config/iopenpod
  ${HOME}/.local/share/iOpenPod
  ${HOME}/.local/share/iopenpod
  ${HOME}/.local/state/iOpenPod
  ${HOME}/.local/state/iopenpod
  ${HOME}/.cache/iOpenPod
  ${HOME}/.cache/iopenpod

This includes Backup Snapshots stored under ~/.local/share/iOpenPod/backups.
Backups saved outside that directory are not touched.
EOF
    if confirm "Delete this user data permanently?"; then
        rm -rf -- \
            "${HOME}/.config/iOpenPod" \
            "${HOME}/.config/iopenpod" \
            "${HOME}/.local/share/iOpenPod" \
            "${HOME}/.local/share/iopenpod" \
            "${HOME}/.local/state/iOpenPod" \
            "${HOME}/.local/state/iopenpod" \
            "${HOME}/.cache/iOpenPod" \
            "${HOME}/.cache/iopenpod"
        printf 'User data deleted.\n'
    else
        printf 'User data preserved.\n'
    fi
else
    printf 'User settings, Backups and logs were preserved. Use --purge to delete them.\n'
fi

printf 'iOpenPod was removed.\n'
