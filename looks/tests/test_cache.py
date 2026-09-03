"""The cube cache, and the race it has to survive.

This package is built to be fanned out — one process per cut, several at once,
all wanting the same LUT. So the test that matters is not "does it write a file"
but "what does a reader see while another process is writing one".

**A half-written `.cube` is not an error, it is a silently wrong picture.**
ffmpeg reads what is there and interpolates the rest of the lattice from
nothing, exits 0, and produces a plausible frame with the wrong colours. That is
why the atomicity test spawns real processes rather than asserting that
`os.replace` is documented as atomic.
"""

import os
import pathlib
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from looks import Ramp
from looks.cache import (
    CUBE_SUFFIX,
    DFLT_CACHE_ENV,
    cache_dir,
    entries,
    cube_file,
    materialize_many,
    sweep,
)
from looks.lut import cube_key, cube_text

STOPS = [(8.2, "#2E0C18"), (46.8, "#D5254A"), (100.0, "#FEF0DC")]
SIZE = 9  # small enough to be quick, large enough to be a real lattice


@pytest.fixture
def ramp():
    return Ramp.from_hex(STOPS)


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "cubes"


def _materialise_in(args):
    """Top-level so it is picklable — a ProcessPoolExecutor needs that."""
    directory, stops, size = args
    from looks import Ramp
    from looks.cache import cube_file

    got = cube_file(Ramp.from_hex(stops), size=size, into=directory)
    return str(got.path), got.hit


class TestItIsACache:
    def test_the_first_call_writes_and_the_second_does_not(self, ramp, cache):
        first = cube_file(ramp, size=SIZE, into=cache)
        second = cube_file(ramp, size=SIZE, into=cache)
        assert first.hit is False and second.hit is True
        assert first.path == second.path and first.path.exists()

    def test_the_file_is_the_text_the_generator_would_produce(self, ramp, cache):
        got = cube_file(ramp, size=SIZE, into=cache)
        assert got.path.read_text() == cube_text(ramp, size=SIZE)

    def test_the_name_is_the_address(self, ramp, cache):
        got = cube_file(ramp, size=SIZE, into=cache)
        assert got.path.stem == cube_key(ramp, size=SIZE) == got.key

    def test_it_is_path_like(self, ramp, cache):
        got = cube_file(ramp, size=SIZE, into=cache)
        assert os.fspath(got).endswith(CUBE_SUFFIX)
        assert Path(got).exists()

    def test_size_is_part_of_the_identity(self, ramp, cache):
        a = cube_file(ramp, size=9, into=cache)
        b = cube_file(ramp, size=17, into=cache)
        assert a.path != b.path
        assert len(list(entries(cache))) == 2

    def test_the_title_is_part_of_the_identity(self, ramp, cache):
        """The collision this closed: `title` reaches the file's first line, so
        two titles are two files. Before it was folded into the key they shared
        one address and the second silently served the first's bytes."""
        a = cube_file(ramp, size=SIZE, title="look_a", into=cache)
        b = cube_file(ramp, size=SIZE, title="look_b", into=cache)
        assert a.path != b.path
        assert 'TITLE "look_a"' in a.path.read_text()
        assert 'TITLE "look_b"' in b.path.read_text()

    def test_a_changed_ramp_cannot_reuse_a_stale_file(self, cache):
        a = cube_file(Ramp.from_hex(STOPS), size=SIZE, into=cache)
        other = list(STOPS)
        other[1] = (46.8, "#D5254B")  # one hex digit
        b = cube_file(Ramp.from_hex(other), size=SIZE, into=cache)
        assert a.path != b.path


class TestTheRace:
    """Real processes, because this is the claim that cannot be reasoned about."""

    def test_many_writers_produce_one_correct_file(self, cache):
        cache.mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(_materialise_in, [(str(cache), STOPS, SIZE)] * 16)
            )
        paths = {path for path, _ in results}
        assert len(paths) == 1, f"writers disagreed on the address: {paths}"
        written = Path(paths.pop())
        assert written.read_text() == cube_text(Ramp.from_hex(STOPS), size=SIZE)
        assert sum(1 for _, hit in results if not hit) >= 1, "nobody wrote it"

    def test_no_partial_file_is_left_behind(self, cache):
        cache.mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(max_workers=8) as pool:
            list(pool.map(_materialise_in, [(str(cache), STOPS, SIZE)] * 16))
        leftovers = [p.name for p in cache.iterdir() if ".partial" in p.name]
        assert leftovers == [], leftovers

    def test_exactly_one_cube_exists_afterwards(self, cache):
        cache.mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(max_workers=8) as pool:
            list(pool.map(_materialise_in, [(str(cache), STOPS, SIZE)] * 16))
        assert len(list(entries(cache))) == 1

    def test_each_writer_gets_its_own_temp_name(self, ramp, cache, monkeypatch):
        """A deterministic `<key>.tmp` would have two writers interleaving into
        one file — the race in a costume.

        Observed rather than grepped: a first draft scanned the module source
        for `.tmp"` and failed on this module's own COMMENT explaining the
        rule, which would have read as the guard being broken rather than
        satisfied. Recording what `os.replace` is actually handed is the
        question itself.
        """
        import looks.cache as module

        seen = []
        real = module.os.replace

        def record(src, dst):
            seen.append(Path(src).name)
            return real(src, dst)

        monkeypatch.setattr(module.os, "replace", record)
        first = cube_file(ramp, size=SIZE, into=cache)
        first.path.unlink()  # force a second write of the same address
        cube_file(ramp, size=SIZE, into=cache)

        assert len(seen) == 2
        assert seen[0] != seen[1], (
            f"both writers used the temp name {seen[0]!r}; two of them "
            "concurrently would interleave into one file"
        )
        assert all(name.startswith(first.key) for name in seen), seen


class TestAFailedWriteLeavesNothing:
    def test_a_generator_error_removes_the_partial(self, cache, monkeypatch):
        cache.mkdir(parents=True, exist_ok=True)
        import looks.cache as module

        def boom(*args, **kwargs):
            raise RuntimeError("generation failed")

        monkeypatch.setattr(module, "cube_text", boom)
        with pytest.raises(RuntimeError, match="generation failed"):
            cube_file(Ramp.from_hex(STOPS), size=SIZE, into=cache)
        assert list(cache.iterdir()) == []

    def test_a_write_error_removes_the_partial(self, cache, monkeypatch):
        cache.mkdir(parents=True, exist_ok=True)
        import looks.cache as module

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(module.os, "replace", boom)
        with pytest.raises(OSError, match="disk full"):
            cube_file(Ramp.from_hex(STOPS), size=SIZE, into=cache)
        assert [p.name for p in cache.iterdir()] == []


class TestWhereItLives:
    def test_an_explicit_directory_wins(self, cache, monkeypatch):
        monkeypatch.setenv(DFLT_CACHE_ENV, "/nonexistent/should-not-be-used")
        assert cache_dir(cache) == cache

    def test_the_environment_is_next(self, tmp_path, monkeypatch):
        monkeypatch.setenv(DFLT_CACHE_ENV, str(tmp_path / "from-env"))
        assert cache_dir() == tmp_path / "from-env"

    def test_the_directory_is_created(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "cubes"
        assert not target.exists()
        assert cache_dir(target).is_dir()


class TestSeveralAtOnce:
    def test_a_shared_ramp_is_generated_once(self, cache):
        one, other = Ramp.from_hex(STOPS), Ramp.from_hex(STOPS[:2])
        got = materialize_many([one, other, one, one], size=SIZE, into=cache)
        assert len(got) == 4
        assert len(list(entries(cache))) == 2
        assert got[0].path == got[2].path == got[3].path

    def test_only_the_first_of_a_repeat_reports_a_write(self, cache):
        one = Ramp.from_hex(STOPS)
        got = materialize_many([one, one, one], size=SIZE, into=cache)
        assert [g.hit for g in got] == [False, False, False], (
            "deduplication returns the same record, so the hit flag is the "
            "first call's — the file was written once"
        )


class TestSweepIsTheCallersDecision:
    def test_it_removes_everything_by_default(self, cache):
        cube_file(Ramp.from_hex(STOPS), size=9, into=cache)
        cube_file(Ramp.from_hex(STOPS), size=17, into=cache)
        removed = sweep(cache)
        assert len(removed) == 2 and list(entries(cache)) == []

    def test_it_can_keep_named_keys(self, cache):
        keep = cube_file(Ramp.from_hex(STOPS), size=9, into=cache)
        cube_file(Ramp.from_hex(STOPS), size=17, into=cache)
        removed = sweep(cache, keep={keep.key})
        assert len(removed) == 1
        assert keep.path.exists()

    def test_everything_it_removes_can_be_rebuilt(self, cache):
        """Which is why there is no eviction policy: deleting the whole
        directory is always safe, a stronger property than any policy."""
        before = cube_file(Ramp.from_hex(STOPS), size=SIZE, into=cache)
        text = before.path.read_text()
        sweep(cache)
        after = cube_file(Ramp.from_hex(STOPS), size=SIZE, into=cache)
        assert after.path == before.path and after.path.read_text() == text


class TestFfmpegAcceptsIt:
    def test_a_materialised_cube_loads(self, ramp, cache):
        import shutil

        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg not on PATH")
        cube = cube_file(ramp, size=17, into=cache)
        proc = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-f", "lavfi",
                "-i", "testsrc2=size=64x48:rate=5:duration=0.2",
                "-vf", f"lut3d=file={os.fspath(cube)}",
                "-f", "null", "-",
            ],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr[-500:]

    def test_a_truncated_cube_is_what_the_atomicity_prevents(self, ramp, cache):
        """The reason a partial write is worse than a failed one. Written as a
        test so the claim is checked rather than asserted in a docstring."""
        import shutil

        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg not on PATH")
        cube = cube_file(ramp, size=17, into=cache)
        half = cache / "half.cube"
        text = cube.path.read_text()
        half.write_text(text[: len(text) // 2])
        proc = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-f", "lavfi",
                "-i", "testsrc2=size=64x48:rate=5:duration=0.2",
                "-vf", f"lut3d=file={half}",
                "-f", "null", "-",
            ],
            capture_output=True, text=True,
        )
        # Whatever ffmpeg does with it, the point is that the cache never lets
        # a reader see this file at all.
        assert proc.returncode != 0 or proc.stderr == "", (
            "recorded outcome for a truncated cube: "
            f"rc={proc.returncode} stderr={proc.stderr[:200]!r}"
        )


class TestThePlanLevelVerb:
    """`materialize(plan)` — why acquiring artifacts is its own step.

    `compile_look` starts no process and writes no file, so a plan is pure data
    that can be hashed, stored and sent elsewhere. Artifacts are what it needs
    to actually run, and getting them has a directory, a disk and a race in it.
    """

    def _plan(self, size=9):
        from looks import ClipSpec, Effect, Look, compile_look, probe

        env = probe()
        if not env.available:
            pytest.skip("ffmpeg not usable")
        look = Look(
            steps=(
                Effect(
                    name="gradient_map",
                    params={"stops": [list(s) for s in STOPS], "size": size},
                ),
            ),
            name="que-calor",
        )
        return compile_look(
            look, clip=ClipSpec(width=480, height=850, fps=30), env=env
        )

    def test_compiling_writes_no_file(self, cache):
        from looks.cache import pending

        plan = self._plan()
        assert len(pending(plan)) == 1
        assert not cache.exists() or list(cache.iterdir()) == []

    def test_the_backend_refuses_an_unbuilt_plan(self):
        from looks.ffmpeg import FfmpegBackendError, vf

        with pytest.raises(FfmpegBackendError, match="has not been built"):
            vf(self._plan())

    def test_materialising_makes_it_runnable(self, cache):
        from looks.cache import materialize, pending
        from looks.ffmpeg import vf

        ready = materialize(self._plan(), into=cache)
        assert pending(ready) == ()
        assert "lut3d=file=" in vf(ready)

    def test_the_input_plan_is_left_alone(self, cache):
        """A caller may well want to keep the portable one."""
        from looks.cache import materialize, pending

        plan = self._plan()
        materialize(plan, into=cache)
        assert len(pending(plan)) == 1, "the original was mutated"

    def test_it_is_idempotent(self, cache):
        from looks.cache import materialize, pending

        once = materialize(self._plan(), into=cache)
        twice = materialize(once, into=cache)
        assert twice is once, "a plan with nothing pending should be returned as-is"
        assert pending(twice) == ()

    def test_a_plan_with_no_artifacts_is_returned_unchanged(self):
        from looks import ClipSpec, Effect, Look, compile_look, probe
        from looks.cache import materialize

        env = probe()
        if not env.available:
            pytest.skip("ffmpeg not usable")
        plan = compile_look(
            Look(steps=(Effect(name="blur", params={"sigma": 2}),)),
            clip=ClipSpec(width=64, height=48, fps=10), env=env,
        )
        assert materialize(plan) is plan

    def test_the_path_reaches_the_filter_ESCAPED(self, tmp_path):
        """The flagship effect takes a caller-supplied directory, and a comma
        in it would otherwise end the filter."""
        from looks.cache import materialize
        from looks.ffmpeg import vf

        awkward = tmp_path / "cache,with:punctuation"
        ready = materialize(self._plan(), into=awkward)
        fragment = vf(ready)
        assert "\\," in fragment and "\\\\:" in fragment

    def test_and_ffmpeg_accepts_that(self, tmp_path):
        import shutil

        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg not on PATH")
        from looks.cache import materialize
        from looks.ffmpeg import vf

        awkward = tmp_path / "cache,with:punctuation"
        fragment = vf(materialize(self._plan(), into=awkward))
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi",
             "-i", "testsrc2=size=64x48:rate=5:duration=0.2",
             "-vf", fragment, "-f", "null", "-"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr[-400:]

    def test_two_plans_sharing_a_ramp_share_one_file(self, cache):
        from looks.cache import entries, materialize

        materialize(self._plan(), into=cache)
        materialize(self._plan(), into=cache)
        assert len(list(entries(cache))) == 1

    def test_the_request_carries_no_live_object(self):
        """A plan must survive a process boundary, and a `GradientMap` in a
        payload is exactly what stops it."""
        import json

        from looks.cache import PENDING

        request = self._plan().steps[0].payload[PENDING]
        json.dumps(request)  # raises if anything in there is not plain data


class TestTheWindowsRenameRefusal:
    """`os.replace` is atomic on Windows and on POSIX, but not equally TOTAL:
    Windows refuses the rename while another process holds the destination
    open, where POSIX succeeds and leaves that reader on the old inode.

    This package exists to be fanned out, so concurrent read-while-write is
    the normal case rather than an edge one — and it showed up as a FLAKY
    Windows leg (`[WinError 5] Access is denied`, three `TestTheRace` tests,
    the same commit green on a re-run). A flake is worse than a failure
    because it gets re-run instead of read.

    Simulated rather than skipped off-Windows: the refusal is a raise from one
    call, so injecting it exercises the handling on every platform. A guard
    that only runs on the machine where the bug happens is a guard that is
    never run by the person who breaks it.

    The fake must publish the winner's file **from inside the failing
    replace** — that is what "another writer won while we were writing" means.
    A first draft wrote the file before calling `cube_file`, so the
    `path.exists()` fast return fired and `_publish` was never reached at all:
    two mutations survived, including reverting the whole fix.
    """

    @staticmethod
    def _loser(destination_bytes):
        """An `os.replace` that loses the race exactly as Windows loses it."""

        def refuses(src, dst):
            # The winner lands its file, then our rename is denied.
            pathlib.Path(dst).write_bytes(destination_bytes)
            raise PermissionError(5, "Access is denied")

        return refuses

    def test_a_lost_race_is_a_cache_hit_not_an_exception(self, tmp_path, monkeypatch):
        import looks.cache as cache_module

        ramp = Ramp.from_hex(STOPS)
        # What the winner will have written — byte-identical, because the name
        # is a hash of the content.
        winner = cube_file(ramp, size=9, into=tmp_path / "reference").path.read_bytes()

        monkeypatch.setattr(cache_module.os, "replace", self._loser(winner))
        got = cube_file(ramp, size=9, into=tmp_path)
        assert got.path.read_bytes() == winner, (
            "the loser must end up on the winner's file"
        )

    def test_and_leaves_no_partial_behind(self, tmp_path, monkeypatch):
        """A `.partial` surviving the race is how a later sweep mistakes
        debris for a cache entry."""
        import looks.cache as cache_module

        ramp = Ramp.from_hex(STOPS)
        winner = cube_file(ramp, size=9, into=tmp_path / "reference").path.read_bytes()
        monkeypatch.setattr(cache_module.os, "replace", self._loser(winner))
        cube_file(ramp, size=9, into=tmp_path)
        leftovers = [p for p in tmp_path.rglob("*.partial")]
        assert leftovers == [], leftovers

    def test_but_a_refusal_with_no_winner_still_raises(self, tmp_path, monkeypatch):
        """The other half. Tolerating the refusal only makes sense when the
        destination really is there; swallowing it unconditionally would turn
        a broken cache directory into a silent success returning a path that
        does not exist."""
        import looks.cache as cache_module

        def refuses(src, dst):
            raise PermissionError(5, "Access is denied")

        monkeypatch.setattr(cache_module.os, "replace", refuses)
        with pytest.raises(PermissionError):
            cube_file(Ramp.from_hex(STOPS), size=9, into=tmp_path)
