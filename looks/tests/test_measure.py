"""Tests for :mod:`looks.measure`.

The identity guard is the point of this module, so most of these tests are
about :func:`compare` refusing rather than about arithmetic. The measured
disagreements it prevents (0.6% versus 17.4% crushed-black for one threshold;
2.98x versus 2.19x for the same fix under two instruments) are larger than the
effects a resolver chooses between, so a silent comparison returns a confident
wrong answer — the worst kind.

The live tests synthesise their source with `lavfi` and read it back, so they
are offline, free, and need nothing committed.
"""

import shutil
import subprocess

import pytest

from looks.measure import (
    ClipStats,
    Incomparable,
    LumaSummary,
    MeasurementError,
    color_range,
    compare,
    dispersion,
    measure,
    probe_frames,
)

#: A measurement's identity fields, with values that agree. Tests vary one at a
#: time so a failure names the field that broke.
IDENTITY = dict(
    stage="post_effect",
    instrument="ffmpeg-8.1/signalstats,siti,blurdetect",
    luma_space="coded_y",
    sample_spec="fps=1.0:first=5",
    n_frames=5,
)


def _ffmpeg_or_skip() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not on PATH")


@pytest.fixture
def clip(tmp_path):
    """Four seconds of deterministic synthetic video."""
    _ffmpeg_or_skip()
    path = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:duration=4",
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


class TestTheIdentityGuard:
    """Two measurements are comparable only if they were taken the same way."""

    def test_matching_identity_compares(self):
        a = ClipStats(source_id="c01", sharpness=72.2, **IDENTITY)
        b = ClipStats(source_id="c02", sharpness=114.3, **IDENTITY)
        compare(a, b)

    @pytest.mark.parametrize(
        "field,other",
        [
            ("stage", "source"),
            ("instrument", "opencv-4.13/laplacian"),
            ("luma_space", "bgr2gray"),
            ("sample_spec", "widest_spans:3"),
        ],
    )
    def test_each_identity_field_is_load_bearing(self, field, other):
        a = ClipStats(source_id="c01", **IDENTITY)
        b = ClipStats(source_id="c02", **{**IDENTITY, field: other})
        with pytest.raises(Incomparable, match=field):
            compare(a, b)

    def test_the_refusal_says_what_disagreed(self):
        a = ClipStats(source_id="c01", **IDENTITY)
        b = ClipStats(source_id="c02", **{**IDENTITY, "luma_space": "bgr2gray"})
        with pytest.raises(Incomparable) as excinfo:
            compare(a, b)
        message = str(excinfo.value)
        assert "coded_y" in message and "bgr2gray" in message
        assert "17.4%" in message, "the message should carry the measured stakes"

    def test_dispersion_checks_every_pair(self):
        """Not just the first two — a third measurement taken with a different
        instrument must not slip through."""
        good = [ClipStats(source_id=f"c{i}", sharpness=10.0 * (i + 1), **IDENTITY) for i in range(2)]
        bad = ClipStats(
            source_id="c99", sharpness=50.0, **{**IDENTITY, "instrument": "other"}
        )
        with pytest.raises(Incomparable):
            dispersion(good + [bad])


class TestDispersion:
    """A ratio, not a variance — every figure the source material reports is one."""

    def test_it_reproduces_the_shipped_before_and_after(self):
        """V2b's spread was 2.98x; the per-clip flattening scale took it to 1.59x."""
        before = [
            ClipStats(source_id=n, sharpness=v, **IDENTITY)
            for n, v in [("c01", 72.2), ("c02", 114.3), ("c03", 38.4)]
        ]
        after = [
            ClipStats(source_id=n, sharpness=v, **IDENTITY)
            for n, v in [("c01", 72.2), ("c02", 114.3), ("c03", 71.8)]
        ]
        assert round(dispersion(before), 2) == 2.98
        assert round(dispersion(after), 2) == 1.59

    def test_identical_clips_have_dispersion_one(self):
        same = [ClipStats(source_id=f"c{i}", sharpness=100.0, **IDENTITY) for i in range(3)]
        assert dispersion(same) == 1.0

    def test_a_missing_statistic_is_refused_by_name(self):
        stats = [
            ClipStats(source_id="c01", sharpness=100.0, **IDENTITY),
            ClipStats(source_id="c02", **IDENTITY),
        ]
        with pytest.raises(MeasurementError, match="c02"):
            dispersion(stats)

    def test_one_measurement_is_not_a_dispersion(self):
        with pytest.raises(MeasurementError, match="at least two"):
            dispersion([ClipStats(source_id="c01", sharpness=1.0, **IDENTITY)])

    def test_a_nonpositive_value_is_refused(self):
        """A ratio needs positive values; returning inf or a sign flip silently
        would be worse than saying so."""
        stats = [
            ClipStats(source_id="c01", sharpness=0.0, **IDENTITY),
            ClipStats(source_id="c02", sharpness=5.0, **IDENTITY),
        ]
        with pytest.raises(MeasurementError, match="positive"):
            dispersion(stats)


class TestAgainstARealClip:
    """The zero-dependency measurement tier, exercised."""

    def test_measuring_a_source_yields_the_expected_shape(self, clip):
        s = measure(str(clip), source_id="probe", ffmpeg_version="8.1")
        assert s.stage == "source"
        assert s.n_frames >= 1
        assert s.sharpness and s.sharpness > 0
        assert s.blur and s.blur > 0
        assert s.luma is not None
        assert s.instrument.startswith("ffmpeg-8.1/")

    def test_supplying_a_chain_makes_it_post_effect(self, clip, tmp_path):
        """And the two are then not comparable — which is the whole point of
        recording the stage."""
        from looks.lut import Ramp, write_cube

        cube = write_cube(Ramp.neutral(), tmp_path / "id.cube", size=17)
        src = measure(str(clip), source_id="p", ffmpeg_version="8.1")
        post = measure(
            str(clip), source_id="p", vf=f"lut3d={cube}", ffmpeg_version="8.1"
        )
        assert src.stage == "source" and post.stage == "post_effect"
        with pytest.raises(Incomparable, match="stage"):
            compare(src, post)

    def test_ylow_and_yhigh_are_percentiles_not_extremes(self, clip):
        """`signalstats` YLOW/YHIGH are p10/p90 — the man page is explicit.
        Reading them as min/max overstates every real clip's range."""
        s = measure(str(clip), source_id="p", ffmpeg_version="8.1")
        assert s.luma is not None
        assert s.luma.minimum is not None and s.luma.maximum is not None
        assert s.luma.minimum <= s.luma.low
        assert s.luma.high <= s.luma.maximum

    def test_a_stateless_lut_does_not_invent_temporal_structure(self, clip, tmp_path):
        """The anti-flicker guarantee, in the form that is actually general.

        The shipped chain measured 0.89-1.12x its own source's frame-to-frame
        change — but that band is a property of *that footage*, and a
        contrast-raising LUT amplifies existing differences, so on a synthetic
        high-contrast pattern the ratio is legitimately higher. What holds for
        every source is the structural claim: a per-pixel stateless map cannot
        create temporal structure, so applying the SAME map twice is idempotent
        in the temporal statistic.
        """
        from looks.lut import Ramp, write_cube

        cube = write_cube(Ramp.neutral(), tmp_path / "id.cube", size=33)
        once = measure(str(clip), source_id="p", vf=f"lut3d={cube}", ffmpeg_version="8.1")
        twice = measure(
            str(clip), source_id="p", vf=f"lut3d={cube},lut3d={cube}", ffmpeg_version="8.1"
        )
        assert once.temporal_delta and twice.temporal_delta
        ratio = twice.temporal_delta / once.temporal_delta
        assert 0.9 <= ratio <= 1.1, (
            f"applying a stateless map twice changed the temporal statistic by "
            f"{ratio:.2f}x — it should be idempotent"
        )

    def test_the_first_frame_is_excluded_from_the_temporal_median(self, clip):
        """`siti` reports ti=0 for the first frame (nothing to difference
        against). Including it drags a short probe's median toward zero."""
        raw = probe_frames(str(clip), frames=5)
        assert float(raw[0]["lavfi.siti.ti"]) == 0.0
        s = measure(str(clip), source_id="p", ffmpeg_version="8.1")
        assert s.temporal_delta and s.temporal_delta > 0

    def test_an_ffmpeg_written_file_is_untagged(self, clip):
        """`untagged` is a third value, not a synonym for limited — and it is
        the NORMAL case, including for files ffmpeg itself just wrote."""
        assert color_range(str(clip)) == "untagged"

    def test_a_missing_source_is_a_typed_error(self):
        _ffmpeg_or_skip()
        with pytest.raises(MeasurementError, match="could not measure"):
            measure("/nonexistent/clip.mp4")


class TestTheProbeBudget:
    """The source material's k=3 was too small."""

    def test_the_default_is_five_not_three(self):
        """A 3-frame median carries p90 relative error of 12.7-34.0%, larger
        than most improvements a resolver chooses between."""
        from looks.measure import DFLT_PROBE_FRAMES

        assert DFLT_PROBE_FRAMES == 5

    def test_the_sample_spec_records_what_was_asked_for(self, clip):
        """Part of identity: the sampler moves the answer by up to 27%."""
        s = measure(str(clip), source_id="p", frames=3, fps=2.0, ffmpeg_version="8.1")
        assert s.sample_spec == "fps=2.0:first=3"
        other = measure(str(clip), source_id="p", frames=5, fps=1.0, ffmpeg_version="8.1")
        with pytest.raises(Incomparable, match="sample_spec"):
            compare(s, other)


class TestLumaSummary:
    def test_spread_is_p10_to_p90(self):
        assert LumaSummary(low=41.0, mean=106.0, high=170.0).spread == 129.0
