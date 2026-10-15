"""Large private Host workspaces kept off the system's default temporary volume."""

from __future__ import annotations

import errno
import logging
import os
import re
import secrets
import stat
import sys
import tempfile
import threading
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from storage._filesystem import is_link_or_reparse
from storage._writer_lock import (
    _lock_file,  # pyright: ignore[reportPrivateUsage]
    _open_lock_file,  # pyright: ignore[reportPrivateUsage]
    _unlock_file,  # pyright: ignore[reportPrivateUsage]
)
from storage.errors import DeviceBusyError, StorageError
from storage.host_directory import pin_host_directory
from storage.host_files import application_cache_file
from storage.session import _open_host_source  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)

_PREFIXES = ("iopenpod-media-", "iopenpod-content-", "iopenpod-chaptered-")
_OWNER = ".iopenpod-owner"
# v1 workspaces each held a lock on their own marker, which costs one open
# descriptor per live workspace. v2 markers name their process's shared lease.
_LEGACY_MARKER = b"iopenpod-host-staging-v1\n"
_MARKER = b"iopenpod-host-staging-v2\nowner="
_LEASE_NAME = re.compile(r"\.owner-[0-9a-f]{32}\.lease")
_MARKER_LIMIT = len(_MARKER) + 64


@dataclass(slots=True)
class _ProcessLease:
    name: str
    file: BinaryIO
    workspaces: int = 0


# One locked lease per staging root keeps descriptor use constant however many
# workspaces a Sync retains. Guarded by the root cleanup lock, then this lock.
_LEASES: dict[Path, _ProcessLease] = {}
_LEASES_GUARD = threading.Lock()


def _staging_root() -> Path:
    # Respect deliberate temporary-volume choices, but never silently spill a
    # complete Sync into Linux's commonly RAM-backed default /tmp.
    for name in ("TMPDIR", "TEMP", "TMP"):
        if value := os.environ.get(name):
            base = Path(value).resolve(strict=True)
            suffix = ""
            if sys.platform != "win32":
                suffix = f"-{os.getuid()}"
            return base / f"iopenpod-staging{suffix}"
    platform_name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    return application_cache_file("iOpenPod", "staging", platform_name=platform_name)


def _require_owned_directory(path: Path) -> None:
    metadata = path.lstat()
    if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Host staging must be a plain private directory")
    if sys.platform != "win32" and (
        metadata.st_uid != os.getuid() or metadata.st_mode & 0o077
    ):
        raise ValueError("Host staging must be private to the current user")


@contextmanager
def _cleanup_guard(root: Path, *, wait: bool = True) -> Generator[None]:
    # Serialize creation and normal removal with reaping. In particular, a
    # Windows cleaner must not pin a directory between its owner's unlock and
    # removal. The guard is never held while preparing or publishing content.
    with _open_lock_file(root / ".cleanup-lock") as lease:
        deadline = time.monotonic() + 30
        while True:
            try:
                _lock_file(lease, "Host staging cleanup")
            except DeviceBusyError as error:
                cause = error.__cause__
                if (
                    not wait
                    or not isinstance(cause, OSError)
                    or cause.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK)
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(0.01)
            else:
                break
        try:
            yield
        finally:
            _unlock_file(lease)


def _retain_lease(root: Path) -> str:
    """Return this process's lease name; the caller holds the cleanup guard."""
    with _LEASES_GUARD:
        lease = _LEASES.get(root)
        if lease is None:
            name = f".owner-{secrets.token_hex(16)}.lease"
            file = _open_lock_file(root / name)
            try:
                _lock_file(file, "Host staging owner")
            except BaseException:
                file.close()
                (root / name).unlink(missing_ok=True)
                raise
            lease = _LEASES[root] = _ProcessLease(name, file)
        lease.workspaces += 1
        return lease.name


def _release_lease(root: Path) -> None:
    """Drop one workspace's claim; the caller holds the cleanup guard."""
    with _LEASES_GUARD:
        lease = _LEASES[root]
        lease.workspaces -= 1
        if lease.workspaces:
            return
        del _LEASES[root]
    try:
        _unlock_file(lease.file)
    finally:
        lease.file.close()
    # Windows cannot remove an open file. The guard keeps cleanup from
    # observing the closed lease before it is removed.
    (root / lease.name).unlink(missing_ok=True)


def _write_marker(directory: Path, lease_name: str) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    with os.fdopen(os.open(directory / _OWNER, flags, 0o600), "wb") as marker:
        marker.write(_MARKER + lease_name.encode("ascii") + b"\n")


@contextmanager
def staging_directory(prefix: str) -> Generator[Path]:
    """Retain complete outputs on the selected Host volume until their owner exits.

    Each workspace marker names its process's locked lease, which distinguishes
    abandoned workspaces from another live process's preparations. Only these
    marked, flat workspaces can be reaped.
    """
    if prefix not in _PREFIXES:
        raise ValueError("Unsupported Host staging workspace")
    root = _staging_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require_owned_directory(root)
    # Resolve conventional Host aliases (for example macOS /var) before later
    # identity-checked reads. The owned staging root itself cannot be a link.
    root = root.resolve(strict=True)
    with _cleanup_guard(root):
        lifetime = ExitStack()
        try:
            lease_name = _retain_lease(root)
            lifetime.callback(_release_lease, root)
            directory = Path(
                lifetime.enter_context(
                    tempfile.TemporaryDirectory(prefix=prefix, dir=root)
                )
            )
            # A directory without a complete marker is never cleanup authority.
            _write_marker(directory, lease_name)
        except BaseException:
            lifetime.close()
            raise
    try:
        yield directory
    finally:
        with _cleanup_guard(root):
            lifetime.close()


class RetainedStagingDirectory:
    """Transfer a marked workspace to a draft that explicitly owns its cleanup."""

    def __init__(self, prefix: str) -> None:
        self._lifetime = ExitStack()
        self.name = str(self._lifetime.enter_context(staging_directory(prefix)))

    def cleanup(self) -> None:
        self._lifetime.close()


def cleanup_stale_staging() -> int:
    """Remove only marked workspaces whose owner no longer holds its lease.

    Old unmarked system-temp directories and unexpected entries are untouched.
    Cleanup is best effort; a busy or unreadable workspace cannot block startup.
    """
    removed = 0
    try:
        root = _staging_root()
        if not root.exists():
            return 0
        _require_owned_directory(root)
        root = root.resolve(strict=True)
        with _cleanup_guard(root, wait=False), pin_host_directory(root):
            entries = tuple(root.iterdir())
            referenced: set[str] = set()
            for directory in entries:
                if not directory.name.startswith(_PREFIXES):
                    continue
                try:
                    owner = _remove_abandoned(root, directory)
                except (OSError, ValueError, StorageError):
                    # Includes active leases, files being closed by their owner,
                    # and another process completing the same cleanup.
                    continue
                if owner is None:
                    removed += 1
                elif owner:
                    referenced.add(owner)
            for lease in entries:
                if _LEASE_NAME.fullmatch(lease.name) and lease.name not in referenced:
                    _remove_abandoned_lease(lease)
    except (OSError, ValueError, StorageError) as error:
        logger.debug("Host staging cleanup was unavailable: %s", error)
    return removed


@contextmanager
def _owner_released(lease: Path) -> Generator[None]:
    """Hold a crashed owner's lease while reaping; a live owner raises busy."""
    # Live leases exist whenever the cleanup guard is free.
    if not (lease.exists() or lease.is_symlink()):
        yield
        return
    with _open_host_source(lease, writable=True) as handle:
        _lock_file(handle, "Host staging owner")
        try:
            yield
        finally:
            _unlock_file(handle)


def _remove_abandoned(root: Path, directory: Path) -> str | None:
    """Return ``None`` once removed, else the retained owner's lease name.

    An empty name means the workspace is retained without a v2 owner.
    """
    _require_owned_directory(directory)
    identity = directory.stat()
    marker = directory / _OWNER
    with (
        pin_host_directory(directory),
        _open_host_source(marker, writable=True) as handle,
        ExitStack() as ownership,
    ):
        metadata = os.fstat(handle.fileno())
        if metadata.st_nlink != 1 or (
            sys.platform != "win32" and metadata.st_uid != os.getuid()
        ):
            return ""
        content = handle.read(_MARKER_LIMIT + 1)
        owner = ""
        if content == _LEGACY_MARKER:
            # Earlier versions locked the marker itself for a workspace's life.
            _lock_file(handle, "Host staging workspace")
            ownership.callback(_unlock_file, handle)
        elif content.startswith(_MARKER) and content.endswith(b"\n"):
            owner = content[len(_MARKER) : -1].decode("ascii", "replace")
            if not _LEASE_NAME.fullmatch(owner):
                return ""
            ownership.enter_context(_owner_released(root / owner))
        else:
            return ""
        children = tuple(directory.iterdir())
        # These workspaces contain regular files only. Do not recurse into
        # unexpected directories or follow links left by external changes.
        for child in children:
            info = child.lstat()
            if is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
                return owner
        for child in children:
            if child.name != _OWNER:
                child.unlink()
    # Windows cannot remove the open marker or pinned directory. Close handles
    # first, then recheck identity before removing the now-empty workspace.
    current = directory.lstat()
    if is_link_or_reparse(current) or (current.st_dev, current.st_ino) != (
        identity.st_dev,
        identity.st_ino,
    ):
        return owner
    marker.unlink()
    directory.rmdir()
    return None


def _remove_abandoned_lease(lease: Path) -> None:
    """Remove a crashed owner's unreferenced lease; live leases stay locked."""
    try:
        with _owner_released(lease):
            pass
        info = lease.lstat()
        if stat.S_ISREG(info.st_mode) and not is_link_or_reparse(info):
            lease.unlink()
    except (OSError, StorageError):
        return
