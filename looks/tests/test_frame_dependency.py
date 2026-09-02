"""Tests for :mod:`looks.frame_dependency`.

The module's whole value is that it separates effects that can flicker from
effects that cannot, by measurement rather than assertion. So these tests run
real ffmpeg against real filters whose behaviour is known, and check the
verdict — a test of the classifier against a hand-made fixture would only test
the classifier against itself.
"""

import shutil

import pytest

from looks.frame_dependency import (
    Dependency,
    assert_flicker_free,
    classify,
)


def _ffmpeg_or_skip() -> None:
    if shutil.which("ffprobe") is None:
        pytest.skip("no ffprobe on PATH")


@pytest.fixture
def cube(tmp_path):
    from looks.lut import Ramp, write_cube

    return write_cube(Ramp.neutral(), tmp_path / "id.cube", size=17)


class TestTheVerdicts:
    """Against filters whose dependency class is known from their definition."""

    @pytest.mark.parametrize(
        "chain",
        ["curves=preset=lighter", "gblur=sigma=2", "noise=alls=30:allf=u", "hue=s=0"],
    )
    def test_content_independent_filters_read_independent(self, chain):
        _ffmpeg_or_skip()
        assert classify(chain).dependency is Dependency.INDEPENDENT

    def test_a_fixed_lut_is_independent(self, cube):
        """The flagship look's structural claim, corroborated."""
        _ffmpeg_or_skip()
        r = classify(f"lut3d={cube}")
        assert r.dependency is Dependency.INDEPENDENT
        assert r.can_flicker is False

    def test_auto_levels_is_caught_as_content_adaptive(self):
        """`normalize` rescales to the frame's own min/max, so an unchanged
        pixel moves when anything else in the frame does. Measured at 219/255."""
        _ffmpeg_or_skip()
        r = classify("normalize=blackpt=black:whitept=white")
        assert r.dependency is Dependency.CONTENT_ADAPTIVE
        assert r.content_delta and r.content_delta > 100

    def test_a_vector_quantiser_is_caught(self):
        """`elbg` builds a codebook from the frame — adaptive by definition, and
        the class the whole flicker argument is about."""
        _ffmpeg_or_skip()
        assert classify("elbg=l=4").dependency is Dependency.CONTENT_ADAPTIVE

    def test_time_varying_grain_is_separated_from_static_grain(self):
        """Same filter, one flag apart. Nothing but a probe tells them apart."""
        _ffmpeg_or_skip()
        assert classify("noise=alls=30:allf=t").dependency is Dependency.TIME_VARYING
        assert classify("noise=alls=30:allf=u").dependency is Dependency.INDEPENDENT


class TestBothProbesAreNeeded:
    """Neither content probe alone is sufficient — measured, not assumed."""

    def test_normalize_needs_the_fading_probe(self):
        """It adapts to the luma RANGE. A hue-cycling source does not move the
        range, and `normalize` reads 0 against it alone."""
        _ffmpeg_or_skip()
        assert classify("normalize").dependency is Dependency.CONTENT_ADAPTIVE

    def test_elbg_needs_the_hue_probe(self):
        """It adapts to the colour HISTOGRAM. A fade barely moves the histogram,
        and `elbg` reads 0 against it alone."""
        _ffmpeg_or_skip()
        assert classify("elbg=l=4").dependency is Dependency.CONTENT_ADAPTIVE

    def test_there_are_at_least_two_content_sources(self):
        """Adding one strictly increases sensitivity; removing one silently
        reintroduces a false negative, which is the dangerous direction."""
        from looks.frame_dependency import _split_sources

        assert len(_split_sources()) >= 2


class TestTheGuard:
    def test_a_flickering_effect_is_refused_with_its_numbers(self):
        _ffmpeg_or_skip()
        with pytest.raises(AssertionError, match="content_adaptive"):
            assert_flicker_free("normalize=blackpt=black:whitept=white")

    def test_a_stateless_effect_passes(self, cube):
        _ffmpeg_or_skip()
        assert assert_flicker_free(f"lut3d={cube}").can_flicker is False

    def test_undetermined_raises_rather_than_passing(self):
        """Unknown is not a guarantee — the same rule the licence tier follows,
        applied to the other promise this package makes."""
        _ffmpeg_or_skip()
        with pytest.raises(AssertionError, match="could not determine"):
            assert_flicker_free("this_is_not_a_filter")

    def test_undetermined_can_flicker_is_None_not_False(self):
        """`None` and `False` are different answers and only one is a promise."""
        from looks.frame_dependency import DependencyReport

        assert DependencyReport(dependency=Dependency.UNDETERMINED).can_flicker is None


class TestTheProbeMechanics:
    """The three silent traps, each pinned."""

    def test_a_blur_within_the_margin_reads_independent(self):
        """The seam margin exists so a spatial filter reading pixels near the
        boundary is not mistaken for one adapting to the whole frame."""
        _ffmpeg_or_skip()
        assert classify("gblur=sigma=2").dependency is Dependency.INDEPENDENT

    def test_a_blur_WIDER_than_the_margin_errs_conservatively(self):
        """A Gaussian's support runs to about 3 sigma, so a wide enough blur
        crosses any affordable margin and reads CONTENT_ADAPTIVE.

        That is the **safe** direction — "can flicker" about something that
        cannot. This test exists so the limitation is recorded rather than
        discovered, and so that anyone who "fixes" it by widening the noise
        floor sees what they are trading away: the unsafe error is calling an
        adaptive effect independent.
        """
        _ffmpeg_or_skip()
        r = classify("gblur=sigma=12")
        assert r.dependency is Dependency.CONTENT_ADAPTIVE
        assert r.content_delta and r.content_delta < 30, (
            "a spatial bleed should be small; a large delta here means "
            "something genuinely adaptive is being measured"
        )

    def test_an_rgb_only_filter_is_not_mistaken_for_time_varying(self, cube):
        """`tblend=difference` of identical frames is RGB black, which reads as
        Y=16 once signalstats converts it. Filters needing RGB (`lut3d`,
        `curves`) force that conversion, so the format is pinned on both sides —
        without it every such filter reads time-varying."""
        _ffmpeg_or_skip()
        r = classify(f"lut3d={cube}")
        assert r.time_delta == 0.0, (
            f"an identity LUT reported a time delta of {r.time_delta} — the "
            f"format pinning around the effect has been lost"
        )
