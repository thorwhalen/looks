"""The transition vocabulary, checked against the filter it names.

A curated vocabulary is only worth having if two things hold: every name in it
really works, and a name outside it is refused *here* rather than three stages
later. Both are measured against ffmpeg rather than asserted — the first by
rendering every one of the sixteen, the second by reproducing the error ffmpeg
gives instead.
"""

import shutil
import subprocess

import pytest

from looks.transition import (
    DFLT_CURVE,
    MIN_TRANSITION_S,
    TRANSITION_CURVES,
    Transition,
    TransitionError,
    blended_frames,
    max_blended_frames,
    check_visible,
    is_hard_cut,
    xfade_options,
)

SIZE = (64, 48)


def _ffmpeg_or_skip():
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    """Two solid, unmistakable colours — so a blend is visible as a mixture."""
    _ffmpeg_or_skip()
    directory = tmp_path_factory.mktemp("xfade")
    made = []
    for colour in ("red", "blue"):
        path = directory / f"{colour}.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", f"color=c={colour}:s=64x48:r=30:d=1",
             "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(path)],
            check=True, capture_output=True,
        )
        made.append(path)
    return made


def render(pair, options):
    """Run an xfade with these options and return its frames."""
    spec = ":".join(f"{k}={v}" for k, v in options.items())
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(pair[0]), "-i", str(pair[1]),
         "-filter_complex", f"xfade={spec}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    )
    width, height = SIZE
    per = width * height * 3
    frames = [
        tuple(proc.stdout[i * per : i * per + 3])
        for i in range(len(proc.stdout) // per)
    ]
    return proc, frames


def mixed(frames):
    """Frames that are neither source colour — i.e. actually blended."""
    return [i for i, p in enumerate(frames) if 20 < p[0] < 235 and 20 < p[2] < 235]


class TestEveryNameInTheVocabularyWorks:
    """Sixteen names, sixteen renders. A vocabulary with a dead entry in it is
    worse than no vocabulary, because the refusal it offers is a false one."""

    @pytest.mark.parametrize("curve", sorted(TRANSITION_CURVES))
    def test_it_renders(self, curve, pair):
        _ffmpeg_or_skip()
        proc, frames = render(
            pair, xfade_options(Transition(0.3, curve), offset=0.5)
        )
        assert proc.returncode == 0, proc.stderr[-300:]
        assert frames, "the render produced nothing"

    def test_the_vocabulary_is_a_strict_subset_of_what_ffmpeg_offers(self):
        """Curated, not exhaustive — that is the point of owning it."""
        _ffmpeg_or_skip()
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-h", "filter=xfade"],
            capture_output=True, text=True,
        ).stdout
        for curve in TRANSITION_CURVES:
            assert curve in out, f"{curve} is not in this build's xfade"
        assert len(TRANSITION_CURVES) == 16

    def test_the_default_curve_is_in_the_vocabulary(self):
        assert DFLT_CURVE in TRANSITION_CURVES


class TestAnUnknownNameIsRefusedHere:
    def test_the_type_refuses_it(self):
        with pytest.raises(TransitionError, match="not a transition"):
            Transition(0.5, "starwipe")

    def test_the_refusal_lists_what_is_available(self):
        with pytest.raises(TransitionError, match="circleopen"):
            Transition(0.5, "starwipe")

    def test_it_suggests_a_near_miss(self):
        with pytest.raises(TransitionError, match="Did you mean"):
            Transition(0.5, "fadegrey")

    def test_and_ffmpeg_would_have_been_no_help(self, pair):
        """The reason the vocabulary is owned. ffmpeg's own refusal names
        neither the caller's mistake nor the filter's real complaint."""
        _ffmpeg_or_skip()
        proc, _ = render(
            pair, {"transition": "starwipe", "duration": 0.3, "offset": 0.5}
        )
        assert proc.returncode != 0
        assert b"patches welcome" in proc.stderr or b"Invalid" in proc.stderr


class TestAShortTransitionIsAHardCut:
    """Measured: the floor depends on the frame rate, so a constant cannot
    express it."""

    #: EVERY row here is one where `floor(D)-1` and `ceil(D)-1` DISAGREE. The
    #: original parametrisation used five rows that all sat where the two
    #: formulas happen to agree, so it could not tell them apart and passed
    #: throughout the lifetime of a formula that was wrong in 14 of 27 measured
    #: combinations. Expected values are MEASURED, at offset=0.5.
    @pytest.mark.parametrize(
        "fps,duration,expected",
        [(30, 0.04, 1), (30, 0.08, 2), (30, 0.12, 3), (30, 0.15, 4),
         (25, 0.10, 2), (25, 0.15, 4), (10, 0.12, 1), (10, 0.25, 2)],
    )
    def test_the_exact_prediction_matches_ffmpeg_where_the_formulas_differ(
        self, fps, duration, expected, tmp_path
    ):
        """The rows the old parametrisation could not have contained."""
        _ffmpeg_or_skip()
        made = []
        for colour in ("red", "blue"):
            path = tmp_path / f"{colour}{fps}x.mp4"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                 "-i", f"color=c={colour}:s=64x48:r={fps}:d=1",
                 "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(path)],
                check=True, capture_output=True,
            )
            made.append(path)
        _, frames = render(
            made, {"transition": "fade", "duration": duration, "offset": 0.5}
        )
        # STRICT: any departure from either pure source. The 20/235 window of
        # `mixed()` misses frames that are nearly-but-not-quite pure, which is
        # what made the docstring table and the formula disagree unnoticed.
        observed = sum(1 for f in frames if f != frames[0] and f != frames[-1])
        assert observed == expected, f"{fps} fps, {duration}s -> {observed}"
        assert blended_frames(Transition(duration), fps, offset=0.5) == expected

    def test_the_count_depends_on_the_offset(self):
        """Which is why `blended_frames` takes one, and why the offset-free
        form is documented as a MINIMUM rather than a count. Measured: 0.10 s
        at 30 fps blends 2 frames at offset 0.5 and 3 at offset 0.42."""
        t = Transition(0.10)
        assert blended_frames(t, 30, offset=0.5) == 2
        assert blended_frames(t, 30, offset=0.42) == 3
        # The offset-free answer never exceeds the true count at any offset.
        floor_free = blended_frames(t, 30)
        assert floor_free <= min(
            blended_frames(t, 30, offset=o) for o in (0.0, 0.33, 0.42, 0.5)
        )

    def test_the_bounds_bracket_every_offset(self):
        """min <= exact <= max, for every offset — the property that makes the
        pair honest rather than two more numbers."""
        for fps in (10, 25, 30):
            for dur in (0.04, 0.1, 0.15, 0.3):
                t = Transition(dur)
                lo = blended_frames(t, fps)
                hi = max_blended_frames(t, fps)
                for off in (0.0, 0.17, 0.33, 0.5, 0.84):
                    exact = blended_frames(t, fps, offset=off)
                    assert lo <= exact <= hi, (fps, dur, off, lo, exact, hi)

    @pytest.mark.parametrize(
        "fps,duration,expected",
        [(30, 0.30, 8), (30, 0.10, 2), (30, 0.033, 0), (10, 0.30, 2), (10, 0.10, 0)],
    )
    def test_the_prediction_matches_ffmpeg(self, fps, duration, expected, tmp_path):
        _ffmpeg_or_skip()
        made = []
        for colour in ("red", "blue"):
            path = tmp_path / f"{colour}{fps}.mp4"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                 "-i", f"color=c={colour}:s=64x48:r={fps}:d=1",
                 "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(path)],
                check=True, capture_output=True,
            )
            made.append(path)
        _, frames = render(
            made,
            {"transition": "fade", "duration": duration, "offset": 0.5},
        )
        observed = len(mixed(frames))
        assert observed == expected, f"{fps} fps, {duration}s -> {observed}"
        assert blended_frames(Transition(duration), fps) == expected

    def test_the_same_duration_is_a_cut_at_one_rate_and_not_another(self):
        """Which is why the floor takes the rate. A fixed constant is right at
        exactly one frame rate and wrong everywhere else."""
        short = Transition(0.10)
        assert is_hard_cut(short, 10) is True
        assert is_hard_cut(short, 30) is False

    def test_the_inherited_constant_is_one_frame_at_25(self):
        """Where MIN_TRANSITION_S came from, and why it is too small below 25."""
        assert MIN_TRANSITION_S == pytest.approx(1 / 25)
        assert is_hard_cut(Transition(MIN_TRANSITION_S), 10) is True

    def test_check_visible_refuses_a_cut_that_calls_itself_a_fade(self):
        with pytest.raises(TransitionError, match="blends 0"):
            check_visible(Transition(0.05), 10)

    def test_and_says_how_long_it_would_need_to_be(self):
        with pytest.raises(TransitionError, match="longer than"):
            check_visible(Transition(0.05), 10)

    def test_the_advice_is_one_frame_period_not_two(self):
        """It used to say 2/fps, which overstates by up to 2x and would have a
        caller lengthen a transition that was already fine. A transition is
        guaranteed visible once its span exceeds ONE frame period."""
        with pytest.raises(TransitionError, match=r"longer than 0\.1 s"):
            check_visible(Transition(0.05), 10)
        # And the stated threshold is honest: just above it passes.
        check_visible(Transition(0.101), 10)

    def test_a_visible_one_passes(self):
        assert check_visible(Transition(0.3), 30) is None


class TestTheRecordRefusesWhatFfmpegAccepts:
    def test_zero_duration(self):
        """ffmpeg takes duration=0 without complaint and cuts, so a zero here
        would be a fade in the record and a cut on screen."""
        with pytest.raises(TransitionError, match="positive duration"):
            Transition(0.0)

    def test_ffmpeg_really_does_accept_it(self, pair):
        _ffmpeg_or_skip()
        proc, frames = render(
            pair, {"transition": "fade", "duration": 0, "offset": 0.5}
        )
        assert proc.returncode == 0, "the premise: ffmpeg does not refuse this"
        assert mixed(frames) == [], "and it produces no blended frame"

    def test_a_negative_duration(self):
        with pytest.raises(TransitionError, match="positive duration"):
            Transition(-1.0)

    def test_a_negative_offset(self):
        with pytest.raises(TransitionError, match="before the output does"):
            xfade_options(Transition(0.3), offset=-1.0)

    def test_an_offset_past_the_end_of_the_clip(self):
        """ffmpeg accepts it and blends NOTHING at exit 0 — measured on two
        1.0 s clips, offset=1.5 gives 32 frames and zero of them mixed. That is
        a fade in the record and a cut on screen, the same failure a zero
        duration is refused for."""
        with pytest.raises(TransitionError, match="past the end"):
            xfade_options(Transition(0.3), offset=1.5, first_clip_s=1.0)

    def test_and_ffmpeg_really_does_accept_it(self, pair):
        """The premise, pinned — `pair` is two 1.0 s clips."""
        _ffmpeg_or_skip()
        proc, frames = render(
            pair, {"transition": "fade", "duration": 0.3, "offset": 1.5}
        )
        assert proc.returncode == 0, "the premise: ffmpeg does not refuse this"
        assert [f for f in frames if f != frames[0] and f != frames[-1]] == []

    def test_an_offset_that_fits_is_allowed(self):
        assert xfade_options(Transition(0.3), offset=0.5, first_clip_s=1.0)


class TestItEmitsOptionsNotAFilter:
    """`xfade` takes two inputs, and a compiled fragment here references no
    input index — rule 20. So the host wires the streams."""

    def test_the_options_are_data(self):
        got = xfade_options(Transition(0.5, "wipeleft"), offset=2.0)
        assert got == {
            "transition": "wipeleft",
            "duration": 0.5,
            "offset": 2.0,
        }

    def test_no_stream_label_appears_anywhere(self):
        got = xfade_options(Transition(0.5), offset=1.0)
        assert not any("[" in str(v) for v in got.values())

    def test_the_module_emits_no_filter_string_at_all(self):
        """Asserted on the module, because the temptation is to add one."""
        import ast
        import pathlib

        import looks.transition

        tree = ast.parse(pathlib.Path(looks.transition.__file__).read_text())
        docstrings = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
        }
        emitted = [
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and id(n) not in docstrings
        ]
        assert not [s for s in emitted if "xfade=" in s], (
            "this module names the filter's options, never the filter — a "
            "two-input filter cannot satisfy rule 20"
        )

    def test_the_options_really_drive_ffmpeg(self, pair):
        """The join, checked: what this returns is what xfade takes.

        Uses `fade` deliberately. `mixed()` samples one pixel per frame, which
        is the right instrument for a dissolve — where the WHOLE frame is a
        mixture — and the wrong one for a geometric wipe, where that pixel stays
        pure until the boundary sweeps over it. Measured: the same 0.3 s at
        30 fps gives 8 blended frames for `fade` and 1 for `circleopen`, and the
        difference is the detector, not the transition.
        """
        _ffmpeg_or_skip()
        proc, frames = render(
            pair, xfade_options(Transition(0.3, "fade"), offset=0.5, fps=30)
        )
        assert proc.returncode == 0, proc.stderr[-300:]
        assert len(mixed(frames)) == 8

    def test_a_geometric_wipe_moves_pixels_too_just_not_that_one(self, pair):
        """The other half of the lesson: `circleopen` does transition — count
        pixels across the frame rather than one corner."""
        _ffmpeg_or_skip()
        spec = xfade_options(Transition(0.3, "circleopen"), offset=0.5)
        text = ":".join(f"{k}={v}" for k, v in spec.items())
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(pair[0]), "-i", str(pair[1]),
             "-filter_complex", f"xfade={text}",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True,
        )
        per = SIZE[0] * SIZE[1] * 3
        changing = 0
        for i in range(len(proc.stdout) // per):
            frame = proc.stdout[i * per : (i + 1) * per]
            reds = sum(1 for j in range(0, per, 3) if frame[j] > 200)
            if 0 < reds < SIZE[0] * SIZE[1]:
                changing += 1
        # Measured, not guessed: 3 at 0.3 s / 30 fps. The red-pixel counts run
        # 3072 (all) ... 2851, 1599, 115 ... 0 (none), so the circle crosses the
        # frame in three steps even though `fade` blends eight — the two curves
        # transition by different mechanisms and neither count generalises to
        # the other. My first guess here was 5, and it was a guess.
        assert changing == 3, (
            f"a geometric wipe should have part-red frames; got {changing}"
        )


class TestItIsData:
    def test_it_round_trips(self):
        one = Transition(0.42, "smoothleft")
        assert Transition.from_dict(one.to_dict()) == one

    def test_the_curve_defaults_on_the_way_back(self):
        assert Transition.from_dict({"duration_s": 0.5}).curve == DFLT_CURVE

    def test_a_bad_curve_in_a_document_is_refused_on_the_way_back(self):
        """A record is a document, and documents arrive from places."""
        with pytest.raises(TransitionError, match="not a transition"):
            Transition.from_dict({"duration_s": 0.5, "curve": "starwipe"})

    def test_it_serialises(self):
        import json

        assert json.loads(json.dumps(Transition(0.5).to_dict()))["curve"] == "fade"
