"""Large staging uses the selected Host volume and safely reaps crashed owners."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path

import pytest

from storage.content_workspace import StagedContent, content_workspace
from storage.host_staging import RetainedStagingDirectory, cleanup_stale_staging
from storage.media_processing import media_workspace


@pytest.mark.parametrize("name", ("TMPDIR", "TEMP", "TMP"))
def test_explicit_temporary_volume_is_used_for_media_and_spilled_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    for variable in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(name, str(tmp_path))
    with (
        media_workspace(checkpoint=lambda: None) as media,
        content_workspace(memory_budget=0, checkpoint=lambda: None) as content,
    ):
        output = Path(media.output_path(".mp3"))
        output.write_bytes(b"media")
        spilled = content.store(b"overflow")
        assert isinstance(spilled, StagedContent)
        assert output.is_relative_to(tmp_path)
        assert Path(spilled.path).is_relative_to(tmp_path)
        assert cleanup_stale_staging() == 0
        assert output.read_bytes() == b"media"
        assert spilled.read_at(0, len(spilled)) == b"overflow"
    assert not output.exists()
    assert not Path(spilled.path).exists()


def test_tmpdir_takes_precedence_and_invalid_override_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    monkeypatch.setenv("TMPDIR", str(chosen))
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    with media_workspace(checkpoint=lambda: None) as workspace:
        assert Path(workspace.output_path(".mp3")).is_relative_to(chosen)
    monkeypatch.setenv("TMPDIR", str(tmp_path / "missing"))
    with pytest.raises(OSError), media_workspace(checkpoint=lambda: None):
        pytest.fail("An unavailable staging override silently fell back")
    assert cleanup_stale_staging() == 0


@pytest.mark.parametrize("kind", ("media", "content", "chaptered"))
def test_abrupt_process_exit_leaves_only_owned_files_for_startup_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    script = """
import os, sys
from pathlib import Path
from storage.media_processing import media_workspace
from storage.content_workspace import content_workspace
from storage.host_staging import RetainedStagingDirectory
if sys.argv[1] == 'media':
    with media_workspace(checkpoint=lambda: None) as workspace:
        path = Path(workspace.output_path('.mp3'))
        path.write_bytes(bytes(256 * 1024))
        print(path, flush=True)
        os._exit(17)
elif sys.argv[1] == 'content':
    with content_workspace(memory_budget=0, checkpoint=lambda: None) as workspace:
        content = workspace.store(bytes(256 * 1024))
        print(content.path, flush=True)
        os._exit(17)
else:
    directory = RetainedStagingDirectory('iopenpod-chaptered-')
    path = Path(directory.name) / 'chaptered.m4a'
    path.write_bytes(bytes(256 * 1024))
    print(path, flush=True)
    os._exit(17)
"""
    crashed = subprocess.run(
        [sys.executable, "-c", script, kind],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert crashed.returncode == 17, crashed.stderr
    path = Path(crashed.stdout.strip())
    assert path.is_relative_to(tmp_path)
    assert path.stat().st_size == 256 * 1024
    assert cleanup_stale_staging() == 1
    assert not path.parent.exists()
    assert not list(path.parent.parent.glob(".owner-*"))
    assert cleanup_stale_staging() == 0


def test_draft_owned_staging_lives_until_explicit_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    directory = RetainedStagingDirectory("iopenpod-chaptered-")
    try:
        path = Path(directory.name) / "chaptered.m4a"
        path.write_bytes(b"prepared album")
        assert cleanup_stale_staging() == 0
        assert path.read_bytes() == b"prepared album"
    finally:
        directory.cleanup()
    directory.cleanup()
    assert not Path(directory.name).exists()


def test_cleanup_in_another_process_cannot_remove_a_live_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with media_workspace(checkpoint=lambda: None) as workspace:
        path = Path(workspace.output_path(".mp3"))
        path.write_bytes(b"prepared media")
        checked = subprocess.run(
            [
                sys.executable,
                "-c",
                "from storage.host_staging import cleanup_stale_staging; "
                "print(cleanup_stale_staging())",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        assert checked.stdout.strip() == "0"
        assert path.read_bytes() == b"prepared media"


def test_concurrent_startup_cleanup_does_not_race_workspace_creation_or_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    cleaner = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from storage.host_staging import cleanup_stale_staging; "
            "[cleanup_stale_staging() for _ in range(5000)]",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(600):
            with media_workspace(checkpoint=lambda: None) as workspace:
                output = Path(workspace.output_path(".mp3"))
                output.write_bytes(b"prepared data")
            assert not output.parent.exists()
        _, errors = cleaner.communicate(timeout=20)
        assert cleaner.returncode == 0, errors
    finally:
        if cleaner.poll() is None:
            cleaner.kill()
        cleaner.communicate(timeout=10)


def test_cleanup_ignores_unmarked_and_unexpected_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with media_workspace(checkpoint=lambda: None) as workspace:
        root = Path(workspace.output_path(".mp3")).parent.parent
    unrelated = root / "iopenpod-media-unmarked"
    unrelated.mkdir(mode=0o700)
    original = unrelated / "source"
    original.write_bytes(b"unowned data")
    marker = unrelated / ".iopenpod-owner"
    assert cleanup_stale_staging() == 0
    assert not marker.exists()
    assert original.read_bytes() == b"unowned data"
    marker.write_bytes(b"not a staging marker")
    assert cleanup_stale_staging() == 0
    assert original.read_bytes() == b"unowned data"
    # A valid marker alone must not authorize recursive deletion.
    marker.write_bytes(b"iopenpod-host-staging-v1\n")
    (unrelated / "unexpected").mkdir()
    assert cleanup_stale_staging() == 0
    assert original.read_bytes() == b"unowned data"


def test_cleanup_does_not_follow_linked_workspaces_or_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with media_workspace(checkpoint=lambda: None) as workspace:
        root = Path(workspace.output_path(".mp3")).parent.parent
    outside = tmp_path / "outside"
    outside.mkdir()
    original = outside / "source"
    original.write_bytes(b"unowned data")
    linked = root / "iopenpod-media-linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit symbolic links")
    assert cleanup_stale_staging() == 0
    assert original.read_bytes() == b"unowned data"
    linked.unlink()
    linked.mkdir(mode=0o700)
    (linked / ".iopenpod-owner").write_bytes(b"iopenpod-host-staging-v1\n")
    (linked / "source").symlink_to(original)
    assert cleanup_stale_staging() == 0
    assert original.read_bytes() == b"unowned data"


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
def test_cleanup_rejects_a_shared_staging_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with media_workspace(checkpoint=lambda: None) as workspace:
        root = Path(workspace.output_path(".mp3")).parent.parent
    root.chmod(0o777)
    try:
        assert cleanup_stale_staging() == 0
        with (
            pytest.raises(ValueError, match="private"),
            media_workspace(checkpoint=lambda: None),
        ):
            pytest.fail("Shared staging root was accepted")
    finally:
        root.chmod(0o700)


def _open_descriptors() -> int:
    return len(os.listdir("/proc/self/fd" if sys.platform == "linux" else "/dev/fd"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor table")
def test_live_workspaces_share_one_descriptor_per_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    before = _open_descriptors()
    with ExitStack() as workspaces:
        outputs = []
        for _ in range(300):
            workspace = workspaces.enter_context(
                media_workspace(checkpoint=lambda: None)
            )
            output = Path(workspace.output_path(".mp3"))
            output.write_bytes(b"prepared")
            outputs.append(output)
        # A Sync retains every prepared Track until publication.
        assert _open_descriptors() - before <= 1
        root = outputs[0].parent.parent
        assert len(list(root.glob(".owner-*.lease"))) == 1
        assert cleanup_stale_staging() == 0
        assert all(output.read_bytes() == b"prepared" for output in outputs)
    assert _open_descriptors() == before
    assert not list(root.glob(".owner-*"))
    assert not any(root.glob("iopenpod-media-*"))


def _staging_root(tmp_path: Path) -> Path:
    with media_workspace(checkpoint=lambda: None) as workspace:
        return Path(workspace.output_path(".mp3")).parent.parent


def test_abandoned_legacy_workspace_is_still_reclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    legacy = _staging_root(tmp_path) / "iopenpod-media-legacy"
    legacy.mkdir(mode=0o700)
    (legacy / ".iopenpod-owner").write_bytes(b"iopenpod-host-staging-v1\n")
    (legacy / "output.mp3").write_bytes(b"prepared")
    assert cleanup_stale_staging() == 1
    assert not legacy.exists()


_VALID_OWNER = b".owner-" + b"0" * 32 + b".lease"


@pytest.mark.parametrize(
    "owner",
    (
        b"../outside.lease\n",
        b".owner-short.lease\n",
        _VALID_OWNER + b"/extra\n",
        _VALID_OWNER,  # Incomplete: no final newline.
    ),
)
def test_malformed_owner_markers_are_not_cleanup_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: bytes
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    workspace = _staging_root(tmp_path) / "iopenpod-media-malformed"
    workspace.mkdir(mode=0o700)
    (workspace / ".iopenpod-owner").write_bytes(
        b"iopenpod-host-staging-v2\nowner=" + owner
    )
    original = workspace / "output.mp3"
    original.write_bytes(b"unowned data")
    assert cleanup_stale_staging() == 0
    assert original.read_bytes() == b"unowned data"


def test_workspace_whose_owner_lease_is_gone_is_reclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    workspace = _staging_root(tmp_path) / "iopenpod-media-orphan"
    workspace.mkdir(mode=0o700)
    (workspace / ".iopenpod-owner").write_bytes(
        b"iopenpod-host-staging-v2\nowner=.owner-" + b"a" * 32 + b".lease\n"
    )
    (workspace / "output.mp3").write_bytes(b"prepared")
    assert cleanup_stale_staging() == 1
    assert not workspace.exists()


def test_cleanup_in_another_process_keeps_workspaces_of_a_live_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with (
        media_workspace(checkpoint=lambda: None) as first,
        media_workspace(checkpoint=lambda: None) as second,
    ):
        outputs = [Path(w.output_path(".mp3")) for w in (first, second)]
        for output in outputs:
            output.write_bytes(b"prepared media")
        root = outputs[0].parent.parent
        lease = next(root.glob(".owner-*.lease"))
        checked = subprocess.run(
            [
                sys.executable,
                "-c",
                "from storage.host_staging import cleanup_stale_staging; "
                "print(cleanup_stale_staging())",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        assert checked.stdout.strip() == "0"
        assert lease.exists()
        assert all(o.read_bytes() == b"prepared media" for o in outputs)


def test_parallel_workspaces_share_and_release_one_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    root = _staging_root(tmp_path)

    def prepare(_: int) -> None:
        for _ in range(40):
            with media_workspace(checkpoint=lambda: None) as workspace:
                Path(workspace.output_path(".mp3")).write_bytes(b"prepared")
                assert len(list(root.glob(".owner-*.lease"))) == 1

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(prepare, range(8)))
    assert not list(root.glob(".owner-*"))
    assert not any(root.glob("iopenpod-media-*"))
