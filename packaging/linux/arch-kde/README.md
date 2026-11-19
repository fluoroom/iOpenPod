# Arch Linux + KDE Plasma install scripts

These scripts install and remove the `fluoroom/iOpenPod` fork for the current
user. They do not use `sudo` for the application itself: iOpenPod is installed
with `uv tool install` under `~/.local/share/uv/tools`, and the launcher,
desktop entry and icon live under the user's XDG directories.

## Requirements

- Arch Linux with KDE Plasma
- `uv` (the script offers to install it with pacman)
- FFmpeg and FFprobe for media inspection and conversion
- Chromaprint's `fpcalc` for acoustic fingerprinting

The install script offers to install missing packages with `pacman`.

## Install

```shell
./packaging/linux/arch-kde/install.sh
```

The default source is `git+https://github.com/fluoroom/iOpenPod.git@main`.
Re-run this script to update from the fork; it forces a rebuild from the
selected source. `uv tool upgrade iopenpod` only upgrades when the project
version changes. Pass `--local` to install the current checkout instead, or
`--yes` to skip package prompts.

The script replaces the old manual `~/.local/bin/iOpenPod` launcher and
`io.github.therealsavi.iOpenPod.desktop` entry with the fork's launcher and
desktop entry. It installs:

- `~/.local/bin/iopenpod`
- `~/.local/share/applications/io.github.fluoroom.iOpenPod.desktop`
- `~/.local/share/icons/hicolor/256x256/apps/io.github.fluoroom.iOpenPod.png`

If `~/.local/bin` is not on `PATH`, add it or launch iOpenPod from the
application menu.

## Uninstall

```shell
./packaging/linux/arch-kde/uninstall.sh
```

This removes the launcher, desktop entry and icon, and leaves user settings,
logs, caches and Backup Snapshots in place.

To delete user data as well:

```shell
./packaging/linux/arch-kde/uninstall.sh --purge
```

`--purge` also removes `~/.local/share/iOpenPod`, which contains Backup
Snapshots by default. Add `--yes` to skip the confirmation prompt.
