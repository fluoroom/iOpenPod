"""Raise process resource limits that desktop sessions set conservatively."""

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Desktop sessions commonly start applications with a 1024 (Linux) or 256 (macOS)
# soft descriptor limit while permitting far more. Media tools, Qt buffers, and
# staged Sync files share that budget.
_TARGET_OPEN_FILES = 65536
# macOS rejects values above OPEN_MAX even when the hard limit reports unlimited.
_FALLBACK_OPEN_FILES = 10240


def _load_resource() -> Any:
    # Imported dynamically: the module is POSIX-only and absent on Windows.
    return importlib.import_module("resource")


def raise_open_file_limit() -> int | None:
    """Raise the soft open-file limit toward the hard limit; never lower it.

    Returns the resulting soft limit, or ``None`` where the Host has no POSIX
    resource limits (Windows).
    """
    try:
        resource = _load_resource()
    except ImportError:
        return None
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    for target in (_TARGET_OPEN_FILES, _FALLBACK_OPEN_FILES):
        if hard != resource.RLIM_INFINITY:
            target = min(target, hard)
        if soft != resource.RLIM_INFINITY and soft >= target:
            break
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
        except (OSError, ValueError) as error:
            logger.debug("Open-file limit %d was refused: %s", target, error)
            continue
        logger.info("Open-file soft limit raised from %d to %d", soft, target)
        return int(target)
    return int(soft)
