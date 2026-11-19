"""Desktop launches raise the open-file soft limit without lowering it."""

from types import SimpleNamespace
from typing import Any

import pytest

from iOpenPod.app.core import resource_limits

_INFINITY = -1


def fake_resource(
    soft: int, hard: int, *, refuse_above: int | None = None
) -> SimpleNamespace:
    state = {"limits": (soft, hard)}

    def setrlimit(_kind: int, limits: tuple[int, int]) -> None:
        if refuse_above is not None and limits[0] > refuse_above:
            raise ValueError("not allowed to raise maximum limit")
        state["limits"] = limits

    return SimpleNamespace(
        RLIMIT_NOFILE=7,
        RLIM_INFINITY=_INFINITY,
        getrlimit=lambda _kind: state["limits"],
        setrlimit=setrlimit,
        state=state,
    )


def install(monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
    def load() -> Any:
        if module is None:
            raise ImportError("resource")
        return module

    monkeypatch.setattr(resource_limits, "_load_resource", load)


@pytest.mark.parametrize(
    "soft, hard, expected",
    [
        (1024, 524288, 65536),
        (1024, 4096, 4096),
        (1024, _INFINITY, 65536),
        (100000, 524288, 100000),
        (4096, 4096, 4096),
    ],
)
def test_soft_limit_rises_toward_the_hard_limit_and_never_falls(
    monkeypatch: pytest.MonkeyPatch, soft: int, hard: int, expected: int
) -> None:
    module = fake_resource(soft, hard)
    install(monkeypatch, module)
    assert resource_limits.raise_open_file_limit() == expected
    assert module.state["limits"] == (expected, hard)


def test_macos_open_max_refusal_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    module = fake_resource(256, _INFINITY, refuse_above=10240)
    install(monkeypatch, module)
    assert resource_limits.raise_open_file_limit() == 10240
    assert module.state["limits"] == (10240, _INFINITY)


def test_refused_limits_leave_the_soft_limit_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = fake_resource(256, _INFINITY, refuse_above=256)
    install(monkeypatch, module)
    assert resource_limits.raise_open_file_limit() == 256
    assert module.state["limits"] == (256, _INFINITY)


def test_hosts_without_posix_limits_are_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install(monkeypatch, None)
    assert resource_limits.raise_open_file_limit() is None
