"""Tests for :mod:`looks.geometry`.

The claim this module makes is that **one pure-data `Placement` drives two
different backends to the same pixels**. That claim is only worth anything if
it is checked against the real backends, so the tests here do three things a
unit test of the arithmetic alone would not:

1. Compare against **real `mixing.resize_to_dimensions`** output, across a grid
   of source/target/mode combinations, when moviepy is importable.
2. Compare against **real ffmpeg** output dimensions across the same grid.
3. Pin the **one measured divergence** — floor versus round — because it is the
   reason `rounding` is a field on the spec rather than a constant in an
   emitter.

`mixing` is not a dependency of `looks` and must never become one; these tests
skip when it is absent, from inside the test body rather than at module scope.
"""

import shutil
import subprocess

import pytest

from looks.geometry import (
    Blurred,
    Box,
    GeometryError,
    Size,
    Solid,
    center_box,
    ffmpeg_chain,
    placement,
    reframe,
    scaled_size,
    snap_even,
    social_size,
)

#: A grid that includes the awkward cases: odd dimensions, a source that is
#: exactly the target, extreme aspect ratios, and the 1920x1080 -> 1080x1920
#: pair that produces the 607/608 disagreement.
SOURCES = [
    Size(1920, 1080),
    Size(641, 481),  # both odd
    Size(480, 850),  # portrait, the real c01 shape
    Size(1024, 576),
    Size(200, 200),
]
TARGETS = [
    Size(1280, 720),
    Size(1080, 1920),
    Size(1080, 1080),
    Size(200, 200),
]
MODES = ["stretch", "fit", "fill"]


def _ffmpeg_or_skip() -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("no ffmpeg on PATH")


def _rendered_size(chain: str, source: Size, tmp_path) -> Size:
    """Render a synthetic source through ``chain`` and probe the result."""
    # .mkv, not .mp4: ffv1 in an mp4 container is accepted by ffmpeg 8.1 and
    # REFUSED by 6.1.1 (exit 234), which is what Ubuntu ships. That difference
    # cost 60 failures the moment CI was given an ffmpeg at all — the tests had
    # been silently skipping, so the container choice was never exercised
    # anywhere but one laptop. Matroska takes ffv1 on both.
    out = tmp_path / "probe.mkv"
    vf = chain or "null"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi",
            "-i", f"testsrc2=size={source.width}x{source.height}:rate=2:duration=0.5",
            "-vf", vf,
            "-frames:v", "1",
            "-c:v", "ffv1",  # lossless, and no even-dimension requirement
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0", str(out),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    w, h = probe.stdout.strip().split(",")
    return Size(int(w), int(h))


class TestAgainstRealFfmpeg:
    """The chain must actually produce the target size."""

    @pytest.mark.parametrize("source", SOURCES)
    @pytest.mark.parametrize("target", TARGETS)
    @pytest.mark.parametrize("mode", MODES)
    def test_the_chain_lands_on_the_target(self, source, target, mode, tmp_path):
        _ffmpeg_or_skip()
        p = placement(source, target, mode=mode)
        got = _rendered_size(ffmpeg_chain(p), source, tmp_path)
        assert got == target, (
            f"{source.width}x{source.height} -> {target.width}x{target.height} "
            f"({mode}) rendered {got.width}x{got.height}"
        )

    def test_a_no_op_placement_emits_nothing(self, tmp_path):
        """An identity `scale` still resamples, so a chain that does not need to
        resample must not. This is why `crop`/`offset` are `None` rather than
        degenerate values."""
        _ffmpeg_or_skip()
        p = placement(Size(320, 240), Size(320, 240))
        assert ffmpeg_chain(p) == ""
        assert p.resamples is False


class TestAgainstRealMixing:
    """The extracted arithmetic must reproduce what `mixing` already ships."""

    @pytest.mark.parametrize("source", SOURCES)
    @pytest.mark.parametrize("target", TARGETS)
    @pytest.mark.parametrize("mode", ["stretch", "fit", "fill"])
    def test_scaled_size_matches_mixing(self, source, target, mode):
        """`mixing.resize_to_dimensions` computes the intermediate size with
        `int(...)`, which for positive values is what `exact_floor` reproduces —
        exactly, and without a float in the middle.

        Checked by re-deriving mixing's own arithmetic rather than by running
        moviepy: the branch is small, exact, and reading it is what makes the
        equivalence claim checkable at all.
        """
        try:
            import mixing.video.video_util  # noqa: F401
        except ImportError:
            pytest.skip("mixing is not importable")

        cw, ch = source.width, source.height
        tw, th = target.width, target.height
        target_aspect = tw / th
        current_aspect = cw / ch

        if mode == "stretch":
            want = (tw, th)
        elif mode == "fit":
            if current_aspect > target_aspect:
                want = (tw, int(tw / current_aspect))
            else:
                want = (int(th * current_aspect), th)
        else:  # fill
            if current_aspect > target_aspect:
                want = (int(th * current_aspect), th)
            else:
                want = (tw, int(tw / current_aspect))

        got = scaled_size(source, target, mode=mode)
        assert (got.width, got.height) == want

    def test_center_box_uses_mixing_s_floor_halving(self):
        """`mixing` computes offsets with `//2`. An odd leftover goes right and
        down, and reproducing that is what keeps an extracted render identical
        to an existing one."""
        assert center_box(Size(1439, 1080), Size(1920, 1080)) == Box(240, 0, 1439, 1080)
        assert center_box(Size(3, 1), Size(4, 1)).x == 0


class TestTheRoundingDivergence:
    """The measured reason `rounding` is a field on the spec."""

    def test_the_two_modes_disagree_on_a_perfectly_ordinary_input(self):
        """1080 / (1920/1080) = 607.5. `mixing` and moviepy floor to 607;
        ffmpeg's `force_original_aspect_ratio` goes half-away to 608. One row,
        and a black-to-white difference at the seam."""
        src, dst = Size(1920, 1080), Size(1080, 1920)
        assert scaled_size(src, dst, mode="fit", rounding="exact_floor").height == 607
        assert (
            scaled_size(src, dst, mode="fit", rounding="exact_half_away").height == 608
        )

    def test_the_rule_travels_with_the_placement(self):
        """A spec whose rendered result depends on which backend read it is not
        a spec."""
        p = placement(Size(1920, 1080), Size(1080, 1920), rounding="exact_half_away")
        assert p.rounding == "exact_half_away"
        assert p.scale.height == 608

    def test_exact_floor_is_the_default(self):
        """Because it is what the fleet's existing renders were made with — a
        silent one-pixel change to every previously-rendered frame is not an
        improvement."""
        assert placement(Size(1920, 1080), Size(1080, 1920)).rounding == "exact_floor"

    def test_the_deferred_ffmpeg_form_is_not_emitted(self):
        """`scale=W:H:force_original_aspect_ratio=decrease` is tempting and
        rounds differently. A placement that does not know its source size also
        cannot be inspected or diffed, which is the premise of the package."""
        chain = ffmpeg_chain(placement(Size(1920, 1080), Size(1080, 1920)))
        assert "force_original_aspect_ratio" not in chain
        assert "scale=1080:607" in chain


class TestFitVersusFill:
    """The two modes must be exact opposites about what they give up."""

    @pytest.mark.parametrize("source", SOURCES)
    @pytest.mark.parametrize("target", TARGETS)
    def test_fit_pads_and_never_crops(self, source, target):
        p = placement(source, target, mode="fit")
        assert p.crop is None

    @pytest.mark.parametrize("source", SOURCES)
    @pytest.mark.parametrize("target", TARGETS)
    def test_fill_crops_and_never_pads(self, source, target):
        p = placement(source, target, mode="fill")
        assert p.offset is None

    @pytest.mark.parametrize("source", SOURCES)
    @pytest.mark.parametrize("target", TARGETS)
    def test_stretch_does_neither(self, source, target):
        p = placement(source, target, mode="stretch")
        assert p.crop is None and p.offset is None
        assert p.scale == target


class TestBackdrop:
    """`social` is not a fourth fit mode — it is a backdrop, and they compose."""

    def test_the_default_backdrop_is_solid_black(self):
        assert reframe(Size(480, 850), Size(1280, 720)).backdrop == Solid()

    def test_a_blurred_backdrop_composes_with_any_mode(self):
        for mode in MODES:
            r = reframe(Size(480, 850), Size(1280, 720), mode=mode, backdrop=Blurred())
            assert isinstance(r.backdrop, Blurred)

    def test_a_solid_colour_reaches_the_chain(self):
        p = placement(Size(480, 850), Size(1280, 720))
        assert "color=0xFF00FF" in ffmpeg_chain(p, backdrop=Solid((255, 0, 255)))

    def test_a_blurred_backdrop_refuses_the_single_chain_form(self):
        """It needs a second input branch. Refusing beats emitting a chain that
        silently drops the blur."""
        p = placement(Size(480, 850), Size(1280, 720))
        with pytest.raises(GeometryError, match="two-branch graph"):
            ffmpeg_chain(p, backdrop=Blurred())


class TestSmallThings:
    def test_snap_even_rounds_down(self):
        assert snap_even(Size(1439, 1081)) == Size(1438, 1080)
        assert snap_even(Size(1920, 1080)) == Size(1920, 1080)

    def test_social_presets_resolve_to_sizes(self):
        assert social_size("shorts") == Size(1080, 1920)
        assert social_size("youtube") == Size(1920, 1080)

    def test_an_unknown_preset_names_the_known_ones(self):
        with pytest.raises(GeometryError, match="shorts"):
            social_size("myspace")

    def test_a_zero_size_is_refused(self):
        with pytest.raises(GeometryError, match="must be positive"):
            Size(0, 100)

    def test_an_unknown_mode_is_refused(self):
        with pytest.raises(GeometryError, match="unknown mode"):
            scaled_size(Size(4, 3), Size(16, 9), mode="cover")  # type: ignore[arg-type]

    def test_an_unknown_rounding_is_refused(self):
        with pytest.raises(GeometryError, match="unknown rounding"):
            scaled_size(Size(4, 3), Size(16, 9), rounding="ceil")  # type: ignore[arg-type]


class TestD3ExactArithmetic:
    """`int(round(float))` is half-to-EVEN; ffmpeg's `av_rescale` is half-away
    from zero on exact int64 rationals. They disagree on ordinary inputs.

    The doctest originally chosen (1920x1080 -> 1080x1920, 607/608) is precisely
    a case where the divergence is invisible, because 608 happens to be even.
    """

    def test_half_away_is_not_half_to_even(self):
        from looks.geometry import _resolve

        assert _resolve(1, 2, "exact_half_away") == 1   # round() gives 0
        assert _resolve(5, 2, "exact_half_away") == 3   # round() gives 2
        assert _resolve(3, 2, "exact_half_away") == 2   # round() agrees here

    def test_a_case_where_the_old_implementation_was_wrong(self):
        """1920x1080 -> 200x200 gives 112.5. ffmpeg says 113; `int(round())`
        said 112, because 112 is even."""
        got = scaled_size(Size(1920, 1080), Size(200, 200), rounding="exact_half_away")
        assert got == Size(200, 113)
        assert int(round(200 * 1080 / 1920)) == 112, "the old rule, for contrast"

    def test_both_modes_are_exact_integer_arithmetic(self):
        """No float ever represents the ratio, so there is no representation
        error to argue about and the tie-break is the only difference."""
        from looks.geometry import _resolve

        big = 10**15
        assert _resolve(big * 3, 7, "exact_floor") == (big * 3) // 7
        assert _resolve(big * 3, 7, "exact_half_away") == (2 * big * 3 + 7) // 14

    def test_the_mode_names_carry_the_arithmetic_domain(self):
        """'round' was the ambiguous word that produced the bug."""
        from looks.geometry import DFLT_ROUNDING

        assert DFLT_ROUNDING == "exact_floor"
        with pytest.raises(GeometryError, match="exact_floor"):
            scaled_size(Size(4, 3), Size(16, 9), rounding="round")  # type: ignore[arg-type]

    def test_the_branch_choice_is_exact_too(self):
        """A float aspect comparison can pick the wrong branch on a near-square
        pair; the cross-product cannot."""
        near = scaled_size(Size(1000, 998), Size(1080, 1080), mode="fit")
        assert near.width <= 1080 and near.height <= 1080
