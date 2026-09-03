"""A compiled camera path, checked against ffmpeg rather than against itself.

String equality would pass for a fragment ffmpeg refuses to configure, and pass
just as well for one that configures and shows the wrong picture. Both have
happened here: `zoompan`'s x/y coordinate space was wrong on the first attempt
(6.3 dB against the reference), and `zoom` past 10 renders a different framing
in silence. So the tests that matter build the same window two ways — once
through :mod:`looks.motion`, once through a hand-written reference — and ask
ffmpeg's own `psnr` whether they are the same picture.

Offline and free: every clip is synthesised with `lavfi`, and every process ends
in `-f null -`.
"""

import re
import shutil
import subprocess

import pytest

from looks.geometry import Size
from looks.motion import (
    MAX_ZOOM,
    reframe,
    MIN_WINDOW_FRACTION,
    Keyframe,
    MotionError,
    Window,
    compile_motion,
    crop_fragment,
    is_static,
    ramp,
    zoompan_fragment,
    zooms,
)

#: Above this, two renderings differ only by scaler choice. The measured
#: separation is not marginal — a correct pairing scores 54-60 dB and the
#: nearest wrong one scores 6-13 — so the threshold is not a tuning knob.
SAME_PICTURE_DB = 45.0

SOURCE = "testsrc2=size=320x240:rate=10:duration=2"
SOURCE_FPS = 10
SOURCE_FRAMES = 20


def _ffmpeg_or_skip() -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def configure(fragment: str) -> subprocess.CompletedProcess:
    """Run a fragment over the standard source. Analysis only, as everywhere."""
    return _run(
        [
            "ffmpeg", "-v", "info", "-f", "lavfi", "-i", SOURCE,
            "-vf", fragment, "-f", "null", "-",
        ]
    )


def psnr(fragment: str, reference: str) -> float:
    """How alike are these two chains, over the same source? In dB."""
    lav = (
        f"[0:v]{fragment},format=gray[a];"
        f"[1:v]{reference},format=gray[b];[a][b]psnr"
    )
    proc = _run(
        [
            "ffmpeg", "-v", "info",
            "-f", "lavfi", "-i", SOURCE,
            "-f", "lavfi", "-i", SOURCE,
            "-lavfi", lav, "-f", "null", "-",
        ]
    )
    match = re.search(r"average:(inf|[0-9.]+)", proc.stderr)
    assert match, f"no PSNR in output:\n{proc.stderr[-1500:]}"
    return float("inf") if match.group(1) == "inf" else float(match.group(1))


def frames(fragment: str) -> int:
    proc = _run(
        [
            "ffprobe", "-v", "error", "-f", "lavfi",
            "-i", f"{SOURCE},{fragment}",
            "-count_frames", "-select_streams", "v",
            "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0",
        ]
    )
    return int(proc.stdout.strip().rstrip(","))


class TestTheFragmentsConfigure:
    """The floor. A fragment ffmpeg refuses is not a fragment."""

    @pytest.mark.parametrize(
        "keyframes,kwargs",
        [
            ([Keyframe(0, Window(0.25, 0.1, 0.5, 0.5))], {}),
            (
                [Keyframe(0, Window(0, 0, 0.5, 1)), Keyframe(2, Window(0.5, 0, 0.5, 1))],
                {},
            ),
            (
                [Keyframe(0, Window.full()), Keyframe(2, Window(0.25, 0.25, 0.5, 0.5))],
                {"output": Size(320, 240), "fps": SOURCE_FPS},
            ),
            (
                [
                    Keyframe(0.0, Window.full()),
                    Keyframe(0.7, Window(0.1, 0.1, 0.8, 0.8)),
                    Keyframe(2.0, Window(0.2, 0.15, 0.5, 0.5)),
                ],
                {"output": Size(640, 480), "fps": SOURCE_FPS},
            ),
        ],
        ids=["static", "pan", "zoom", "three-keyframes"],
    )
    def test_it_configures_and_produces_every_frame(self, keyframes, kwargs):
        _ffmpeg_or_skip()
        fragment = compile_motion(keyframes, **kwargs)
        proc = configure(fragment)
        assert "Undefined constant" not in proc.stderr, fragment
        assert "Failed to configure" not in proc.stderr, fragment
        assert proc.returncode == 0, proc.stderr[-1200:]
        assert frames(fragment) == SOURCE_FRAMES, (
            f"{fragment} changed the frame count — d=1 is what keeps it 1:1"
        )


class TestItShowsTheWindowItWasAsked:
    """Configuring proves nothing about which pixels come out."""

    def test_a_static_window_matches_a_hand_written_crop(self):
        _ffmpeg_or_skip()
        got = compile_motion([Keyframe(0, Window(0.25, 0.25, 0.5, 0.5))])
        assert psnr(got, "crop=w=160:h=120:x=80:y=60") == float("inf"), (
            "a static window should be bit-identical to the crop it names"
        )

    def test_a_zoom_matches_the_crop_and_scale_it_stands_for(self):
        """The test that caught the coordinate-space error.

        The first implementation put x/y in zoomed pixels, which configures
        cleanly and scores 6.3 dB. Only a picture comparison finds that.
        """
        _ffmpeg_or_skip()
        held = Window(0.25, 0.25, 0.5, 0.5)
        got = zoompan_fragment(
            [Keyframe(0, held), Keyframe(2, held)],
            output=Size(320, 240),
            fps=SOURCE_FPS,
        )
        assert psnr(got, "crop=w=160:h=120:x=80:y=60,scale=320:240") > SAME_PICTURE_DB

    def test_the_two_filters_agree_on_the_same_pan(self):
        """`crop`'s `t` and `zoompan`'s `in_time` are the same clock.

        This is what lets the compiler choose a filter by what the path does
        rather than by what the caller asked for.
        """
        _ffmpeg_or_skip()
        path = [
            Keyframe(0.0, Window(0.0, 0.25, 0.5, 0.5)),
            Keyframe(2.0, Window(0.5, 0.25, 0.5, 0.5)),
        ]
        by_crop = compile_motion(path)
        by_zoompan = zoompan_fragment(path, output=Size(320, 240), fps=SOURCE_FPS)
        assert "crop=" in by_crop and "zoompan=" in by_zoompan
        assert psnr(by_zoompan, f"{by_crop},scale=320:240") > SAME_PICTURE_DB

    def test_a_path_is_held_before_its_first_and_after_its_last_keyframe(self):
        """Every ramp term saturates, so a clip outliving its path does not
        drift off the end — it sits on the last window."""
        _ffmpeg_or_skip()
        # The path finishes at t=1.0; the clip runs to 2.0.
        moving = compile_motion(
            [
                Keyframe(0.0, Window(0.0, 0.0, 0.5, 0.5)),
                Keyframe(1.0, Window(0.5, 0.5, 0.5, 0.5)),
            ]
        )
        # From t=1.0 onward it must equal the static window it ended on. The
        # trim goes AFTER the fragment, never before: the fragment resets its
        # own timebase, so trimming first would restart the path rather than
        # sample its tail — which is what a first draft of this test did, and
        # it scored 7.5 dB on a compiler that was correct.
        parked = compile_motion([Keyframe(0, Window(0.5, 0.5, 0.5, 0.5))])
        tail = "trim=start=1.2,setpts=PTS-STARTPTS"
        lav = (
            f"[0:v]{moving},{tail},format=gray[a];"
            f"[1:v]{parked},{tail},format=gray[b];"
            "[a][b]psnr"
        )
        proc = _run(
            [
                "ffmpeg", "-v", "info",
                "-f", "lavfi", "-i", SOURCE, "-f", "lavfi", "-i", SOURCE,
                "-lavfi", lav, "-f", "null", "-",
            ]
        )
        match = re.search(r"average:(inf|[0-9.]+)", proc.stderr)
        assert match, proc.stderr[-1000:]
        value = float("inf") if match.group(1) == "inf" else float(match.group(1))
        assert value > SAME_PICTURE_DB


class TestTheMeasuredTrapsAreCompiledAway:
    """Each of these is a fact from `docs/research/00f_motion_filters_evidence.md`
    that a caller would otherwise have to remember."""

    def test_crop_refuses_a_zoom_rather_than_emitting_one_ffmpeg_rejects(self):
        with pytest.raises(MotionError, match="cannot express a zoom"):
            crop_fragment(
                [Keyframe(0, Window.full()), Keyframe(1, Window(0.1, 0.1, 0.8, 0.8))]
            )

    def test_ffmpeg_really_does_reject_the_thing_crop_refuses_to_emit(self):
        """The refusal above is only worth having if the alternative is real."""
        _ffmpeg_or_skip()
        proc = configure("crop=w='iw*(0.9-0.4*t)':h='ih*(0.9-0.4*t)':x=0:y=0")
        assert proc.returncode != 0
        assert "Error when evaluating" in proc.stderr

    def test_a_zoom_without_a_delivery_size_or_rate_is_refused(self):
        path = [Keyframe(0, Window.full()), Keyframe(1, Window(0.1, 0.1, 0.8, 0.8))]
        with pytest.raises(MotionError, match="output and fps"):
            compile_motion(path)
        with pytest.raises(MotionError, match="fps"):
            compile_motion(path, output=Size(320, 240))

    def test_the_wrong_fps_would_have_retimed_the_clip_silently(self):
        """Why `fps` is required rather than defaulted: the frame count — the
        obvious check — is identical, and the duration is not."""
        _ffmpeg_or_skip()
        path = [Keyframe(0, Window.full()), Keyframe(2, Window(0.25, 0.25, 0.5, 0.5))]
        right = zoompan_fragment(path, output=Size(320, 240), fps=SOURCE_FPS)
        wrong = zoompan_fragment(path, output=Size(320, 240), fps=25)
        assert frames(right) == frames(wrong) == SOURCE_FRAMES
        rates = [
            _run(
                [
                    "ffprobe", "-v", "error", "-f", "lavfi",
                    "-i", f"{SOURCE},{f}", "-select_streams", "v",
                    "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0",
                ]
            ).stdout.strip()
            for f in (right, wrong)
        ]
        assert rates == ["10/1", "25/1"], rates

    def test_a_window_smaller_than_the_zoom_ceiling_allows_is_refused(self):
        """Past 10x, `zoompan` renders a different framing and says nothing."""
        tiny = MIN_WINDOW_FRACTION / 2
        with pytest.raises(MotionError, match="clamps zoom"):
            zoompan_fragment(
                [Keyframe(0, Window.full()), Keyframe(1, Window(0, 0, tiny, tiny))],
                output=Size(320, 240),
                fps=SOURCE_FPS,
            )

    def test_the_ceiling_is_where_the_measurement_put_it(self):
        """The refusal's boundary, checked against ffmpeg rather than trusted.

        At the ceiling the filter is faithful; past it, it is not — and the gap
        is 40 dB, not a rounding difference.
        """
        _ffmpeg_or_skip()
        at = psnr(
            f"zoompan=z={MAX_ZOOM:g}:d=1:x=0:y=0:s=320x240:fps={SOURCE_FPS}",
            "crop=w=32:h=24:x=0:y=0,scale=320:240",
        )
        past = psnr(
            f"zoompan=z={MAX_ZOOM * 2:g}:d=1:x=0:y=0:s=320x240:fps={SOURCE_FPS}",
            "crop=w=16:h=12:x=0:y=0,scale=320:240",
        )
        assert at > SAME_PICTURE_DB, at
        assert past < 20, f"the clamp seems to be gone: {past} dB past the ceiling"

    def test_a_window_that_is_not_the_frames_shape_is_refused(self):
        with pytest.raises(MotionError, match="not the source's shape"):
            zoompan_fragment(
                [
                    Keyframe(0, Window.full()),
                    Keyframe(1, Window(0.1, 0.1, 0.8, 0.5)),
                ],
                output=Size(320, 240),
                fps=SOURCE_FPS,
            )

    def test_setpts_is_prepended_only_when_the_window_moves(self):
        static = compile_motion([Keyframe(0, Window(0, 0, 0.5, 0.5))])
        moving = compile_motion(
            [Keyframe(0, Window(0, 0, 0.5, 0.5)), Keyframe(1, Window(0.5, 0, 0.5, 0.5))]
        )
        assert not static.startswith("setpts")
        assert moving.startswith("setpts=PTS-STARTPTS,")


class TestTheRefusalsAboutThePathItself:
    def test_an_empty_path_is_refused(self):
        with pytest.raises(MotionError, match="at least one keyframe"):
            compile_motion([])

    def test_keyframes_must_advance_in_time(self):
        with pytest.raises(MotionError, match="not after"):
            compile_motion(
                [Keyframe(1.0, Window.full()), Keyframe(0.5, Window.full())]
            )

    def test_two_keyframes_at_one_moment_are_refused(self):
        """Not merely a division by zero — a path cannot be in two places at
        the same time, and picking one silently is the wrong repair."""
        with pytest.raises(MotionError, match="not after"):
            compile_motion(
                [Keyframe(1.0, Window.full()), Keyframe(1.0, Window(0, 0, 0.5, 0.5))]
            )

    def test_a_window_that_leaves_the_frame_is_refused(self):
        with pytest.raises(MotionError, match="leaves the frame"):
            compile_motion([Keyframe(0, Window(0.6, 0, 0.5, 0.5))])

    def test_a_window_of_no_extent_is_refused(self):
        with pytest.raises(MotionError, match="zero or negative extent"):
            compile_motion([Keyframe(0, Window(0, 0, 0.0, 0.5))])

    def test_a_window_missing_a_side_is_refused_by_name(self):
        class Partial:
            x = y = w = 0.5

        with pytest.raises(MotionError, match=r"no \.h"):
            compile_motion([Keyframe(0, Partial())])

    def test_a_nan_window_is_a_refusal_and_not_a_default(self):
        with pytest.raises(MotionError, match="not a\n?\\s*number|not a number"):
            compile_motion([Keyframe(0, Window(float("nan"), 0, 0.5, 0.5))])


class TestTheStructuralWindow:
    """`looks` must never import `burns`, so it accepts burns' shape instead."""

    def test_any_object_with_the_four_names_is_a_window(self):
        class Foreign:
            def __init__(self):
                self.x, self.y, self.w, self.h = 0.1, 0.2, 0.5, 0.5

        got = compile_motion([Keyframe(0, Foreign())])
        assert got == "crop=w='iw*0.5':h='ih*0.5':x='iw*0.1':y='ih*0.2'"

    def test_the_package_does_not_import_burns_to_do_it(self):
        import ast
        import pathlib

        import looks.motion

        tree = ast.parse(pathlib.Path(looks.motion.__file__).read_text())
        imported = {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        } | {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert "burns" not in imported
        assert "moviepy" not in imported


class TestTheRampIsTheRightShape:
    def test_it_is_exact_at_every_keyframe(self):
        """Checked by evaluating the emitted expression in Python, which shares
        `min`/`max` with ffmpeg's evaluator for these arguments."""
        points = [(0.0, 0.2), (1.5, 0.7), (4.0, 0.35)]
        expr = ramp(points, "T")
        for t, expected in points:
            got = eval(expr.replace("T", repr(float(t))), {"min": min, "max": max})
            assert abs(got - expected) < 1e-6, (t, got, expected)

    def test_it_holds_outside_the_path_at_both_ends(self):
        expr = ramp([(1.0, 0.2), (3.0, 0.8)], "T")
        ev = lambda t: eval(  # noqa: E731
            expr.replace("T", repr(float(t))), {"min": min, "max": max}
        )
        assert abs(ev(-100) - 0.2) < 1e-9
        assert abs(ev(0.0) - 0.2) < 1e-9
        assert abs(ev(1000) - 0.8) < 1e-9

    def test_it_is_linear_between_keyframes(self):
        expr = ramp([(0.0, 0.0), (2.0, 1.0)], "T")
        ev = lambda t: eval(  # noqa: E731
            expr.replace("T", repr(float(t))), {"min": min, "max": max}
        )
        assert abs(ev(0.5) - 0.25) < 1e-9
        assert abs(ev(1.0) - 0.5) < 1e-9

    def test_a_still_axis_emits_a_constant_rather_than_an_expression(self):
        assert ramp([(0.0, 0.25), (2.0, 0.25)], "t") == "0.25"

    def test_a_still_segment_within_a_moving_axis_emits_no_term(self):
        expr = ramp([(0.0, 0.4), (2.0, 0.4), (5.0, 0.9)], "t")
        assert expr.count("min(") == 1, expr


class TestThePredicatesThatPickTheFilter:
    def test_a_held_window_is_static_and_does_not_zoom(self):
        held = [Keyframe(0, Window(0.1, 0.1, 0.5, 0.5)), Keyframe(3, Window(0.1, 0.1, 0.5, 0.5))]
        assert is_static(held) and not zooms(held)

    def test_a_pan_is_not_static_and_does_not_zoom(self):
        path = [Keyframe(0, Window(0, 0, 0.5, 1)), Keyframe(3, Window(0.5, 0, 0.5, 1))]
        assert not is_static(path) and not zooms(path)

    def test_a_size_change_is_a_zoom_however_small(self):
        path = [Keyframe(0, Window(0, 0, 0.5, 0.5)), Keyframe(3, Window(0, 0, 0.6, 0.6))]
        assert zooms(path)
        assert "zoompan=" in compile_motion(
            path, output=Size(320, 240), fps=SOURCE_FPS
        )


class TestReframingTheHeadlineCase:
    """A Ken Burns path over a still whose shape is not the delivery's.

    `zoompan`'s zoom is one scalar, so it can only show a window similar to its
    input — which made the commonest real case (a 4:3 photo delivered at 16:9)
    the one thing this module refused. The fix is derived geometry, so it lives
    here: crop the source once to the windows' aspect, then move inside it.
    """

    #: 16:9 windows over a 4:3 source. w/h = (16/9)*(480/640).
    START = Window(0.1, 0.2, 0.8, 0.6)      # 512x288 px at (64, 96)
    END = Window(0.25, 0.3, 0.6, 0.45)      # 384x216 px at (160, 144)
    WIDE_SOURCE = "testsrc2=size=640x480:rate=10:duration=2"

    def _psnr_at(self, a, b, at):
        tail = f"trim=start={at}:end={at + 0.05},setpts=PTS-STARTPTS"
        lav = (
            f"[0:v]{a},{tail},format=gray[x];"
            f"[1:v]{b},{tail},format=gray[y];[x][y]psnr"
        )
        proc = _run(
            [
                "ffmpeg", "-v", "info",
                "-f", "lavfi", "-i", self.WIDE_SOURCE,
                "-f", "lavfi", "-i", self.WIDE_SOURCE,
                "-lavfi", lav, "-f", "null", "-",
            ]
        )
        match = re.search(r"average:(inf|[0-9.]+)", proc.stderr)
        assert match, proc.stderr[-900:]
        return float("inf") if match.group(1) == "inf" else float(match.group(1))

    def test_it_used_to_be_refused_and_now_compiles(self):
        path = [Keyframe(0.0, self.START), Keyframe(1.0, self.END)]
        with pytest.raises(MotionError, match="not the source's shape"):
            zoompan_fragment(path, output=Size(1280, 720), fps=10)
        assert compile_motion(path, output=Size(1280, 720), fps=10).startswith("crop=")

    def test_the_reframed_windows_are_square_which_is_what_zoompan_needs(self):
        crop, moved = reframe([Keyframe(0.0, self.START), Keyframe(1.0, self.END)])
        assert crop is not None
        for k in moved:
            assert abs(k.window.w - k.window.h) < 1e-9, k.window

    def test_it_renders_the_window_it_was_asked_for_at_BOTH_ends(self):
        """The test that matters. Geometry that type-checks and configures can
        still show the wrong pixels — only a comparison finds that."""
        _ffmpeg_or_skip()
        # The path finishes at t=1.0, so every later frame is parked on END.
        fragment = compile_motion(
            [Keyframe(0.0, self.START), Keyframe(1.0, self.END)],
            output=Size(1280, 720), fps=10,
        )
        at_start = "crop=w=512:h=288:x=64:y=96,scale=1280:720"
        at_end = "crop=w=384:h=216:x=160:y=144,scale=1280:720"
        assert self._psnr_at(fragment, at_start, 0.0) > SAME_PICTURE_DB
        assert self._psnr_at(fragment, at_end, 1.5) > SAME_PICTURE_DB
        # ...and is not merely close to everything:
        assert self._psnr_at(fragment, at_start, 1.5) < 20

    def test_a_path_already_shaped_like_its_source_is_left_exactly_alone(self):
        """No reframe, and byte-identical to what it compiled to before — a
        capability added must not move an answer that already worked."""
        path = [
            Keyframe(0.0, Window.full()),
            Keyframe(2.0, Window(0.25, 0.25, 0.5, 0.5)),
        ]
        crop, moved = reframe(path)
        assert crop is None and moved == tuple(path)
        assert compile_motion(path, output=Size(1920, 1080), fps=30).startswith(
            "zoompan="
        )

    def test_the_crop_is_the_bounding_box_not_a_centred_one(self):
        """A centred crop can exclude a window the path actually visits, which
        silently reframes the shot. Here the path hugs the top-left."""
        crop, moved = reframe(
            [
                Keyframe(0.0, Window(0.0, 0.0, 0.4, 0.3)),
                Keyframe(1.0, Window(0.05, 0.05, 0.4, 0.3)),
            ]
        )
        assert crop is not None
        for k in moved:
            w = k.window
            assert -1e-9 <= w.x and w.x + w.w <= 1 + 1e-9, w
            assert -1e-9 <= w.y and w.y + w.h <= 1 + 1e-9, w

    def test_an_anisotropic_zoom_is_still_refused(self):
        """No reframing makes it expressible — zoompan scales both axes by one
        scalar, so windows of two different shapes cannot both be shown."""
        with pytest.raises(MotionError, match="anisotropic"):
            reframe(
                [
                    Keyframe(0.0, Window(0.0, 0.0, 0.8, 0.4)),
                    Keyframe(1.0, Window(0.0, 0.0, 0.4, 0.4)),
                ]
            )

    def test_a_path_too_spread_out_to_reframe_is_refused(self):
        """The source cannot supply a frame of that shape containing the whole
        path, so there is nothing honest to emit."""
        with pytest.raises(MotionError, match="larger than the source"):
            reframe(
                [
                    Keyframe(0.0, Window(0.0, 0.0, 0.9, 0.15)),
                    Keyframe(1.0, Window(0.0, 0.85, 0.9, 0.15)),
                ]
            )

    def test_the_emitted_crop_carries_no_float_noise(self):
        """The rounded ratio is for the same-shape TEST only; the geometry uses
        the exact one. Rounding it put 0.6000000001 into the filter string."""
        crop, _ = reframe([Keyframe(0.0, self.START), Keyframe(1.0, self.END)])
        assert abs(crop.h - 0.6) < 1e-12, crop
        assert abs(crop.w - 0.8) < 1e-12, crop


class TestAPanIsScaledToItsDeliverySize:
    """`crop` emits the window's own pixel size, which is arbitrary."""

    def test_an_output_size_appends_a_scale(self):
        got = compile_motion(
            [
                Keyframe(0.0, Window(0.0, 0.0, 0.5, 1.0)),
                Keyframe(2.0, Window(0.5, 0.0, 0.5, 1.0)),
            ],
            output=Size(1280, 720),
        )
        assert got.endswith(",scale=1280:720")

    def test_without_one_the_fragment_is_unchanged(self):
        path = [
            Keyframe(0.0, Window(0.0, 0.0, 0.5, 1.0)),
            Keyframe(2.0, Window(0.5, 0.0, 0.5, 1.0)),
        ]
        assert "scale=" not in compile_motion(path)

    def test_the_odd_size_that_made_libx264_refuse_is_gone(self):
        """Measured on a 640x480 source: a drift emitted 575x431 and the
        encoder aborted with 'width not divisible by 2'."""
        _ffmpeg_or_skip()
        fragment = compile_motion(
            [
                Keyframe(0.0, Window(0.0, 0.0, 0.8987, 0.8987)),
                Keyframe(1.0, Window(0.1, 0.1, 0.8987, 0.8987)),
            ],
            output=Size(640, 480),
        )
        proc = _run(
            [
                "ffmpeg", "-v", "error", "-f", "lavfi",
                "-i", "testsrc2=size=640x480:rate=10:duration=0.5",
                "-vf", fragment, "-c:v", "libx264", "-f", "null", "-",
            ]
        )
        assert proc.returncode == 0, proc.stderr[-600:]


class TestTheAspectToleranceIsNarrowOnPurpose:
    """Windows read out of INTEGER pixel boxes do not share an exact aspect.

    That is the shape every real consumer hands over — `burns.sample_box`
    returns integer boxes for array slicing — and it is precisely the case this
    tolerance must NOT quietly absorb. Widening it here would accept a genuinely
    anisotropic path and render a shape nobody asked for; the caller's job is to
    normalise the aspect it meant. burns does exactly that.
    """

    def _quantised(self, img_w=640, img_h=480, out_w=1280, out_h=720, n=9):
        """Windows with the output's aspect, rounded to whole source pixels."""
        target = out_w / out_h
        frames = []
        for i in range(n):
            zoom = 1.0 + 0.35 * (i / (n - 1))
            box_w = round(img_w / zoom)
            box_h = round(box_w / target)
            frames.append(
                Keyframe(
                    float(i),
                    Window(
                        round((img_w - box_w) / 2) / img_w,
                        round((img_h - box_h) / 2) / img_h,
                        box_w / img_w,
                        box_h / img_h,
                    ),
                )
            )
        return frames

    def test_quantised_windows_do_not_share_an_exact_aspect(self):
        frames = self._quantised()
        ratios = {round(k.window.w / k.window.h, 9) for k in frames}
        assert len(ratios) > 1, "the premise of this whole class"

    def test_the_default_tolerance_refuses_them(self):
        with pytest.raises(MotionError, match="spread by"):
            reframe(self._quantised())

    def test_and_the_refusal_says_what_to_do_about_it(self):
        """Not merely that it failed — a caller hitting this needs to be told
        to normalise, not to loosen."""
        with pytest.raises(MotionError, match="normalise them to the aspect"):
            reframe(self._quantised())

    def test_a_caller_who_knows_better_can_widen_it(self):
        crop, moved = reframe(self._quantised(), aspect_tolerance=1e-2)
        assert crop is not None and len(moved) == 9

    def test_float_noise_alone_passes_the_default(self):
        """The tolerance exists for this and only this: two windows that are
        the same shape but not the same float."""
        frames = [
            Keyframe(0.0, Window(0.0, 0.1, 0.8, 0.6)),
            Keyframe(1.0, Window(0.1, 0.2, 0.8 * (1 + 1e-12), 0.6)),
        ]
        crop, moved = reframe(frames)
        assert crop is not None
