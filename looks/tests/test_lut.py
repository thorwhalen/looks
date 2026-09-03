"""Tests for :mod:`looks.lut`.

Three things are worth pinning here, and only one of them is arithmetic:

1. **The file ffmpeg actually reads.** A `.cube` that parses in Python and is
   rejected — or silently misread — by `lut3d` is worthless. The end-to-end
   test generates a LUT, applies it with ffmpeg, and inspects decoded pixels.
2. **The look's defining property**, which is a *measurement of the reference*
   rather than a preference: the target had 0.0000% true black and 0.07% true
   white, so a chain that produces either has stopped matching it.
3. **The lattice order.** Red varies fastest in a `.cube`. Getting it backwards
   yields a file that loads without complaint and swaps every colour's red and
   blue axes — the easiest way to be wrong in this module, and invisible
   without a directional test.

Offline and free: sources are synthesised with `lavfi`, which is bit-reproducible
across runs, so nothing is committed and nothing is downloaded.
"""

import shutil
import subprocess
import warnings

import pytest

from looks.lut import (
    DFLT_CUBE_SIZE,
    Accent,
    GradientMap,
    LutError,
    Ramp,
    cube_key,
    cube_text,
    gradient_map,
    hex_to_rgb,
    lightness,
    rgb_to_hex,
    write_cube,
)

#: The Que Calor V2b ramp — the measured k=16 palette of the reference, sorted
#: by lightness, with the corrected shadow floor. `#2E0C18` is L* 8.22, the
#: reference's own darkest cluster; the version that ended at L* 3.6 crushed
#: 16.2% of pixels into the bottom histogram bin where the reference had 0.3%.
QUE_CALOR_STOPS = [
    (8.2, "#2E0C18"),
    (15.4, "#530319"),
    (23.9, "#77041F"),
    (29.4, "#8A0D4F"),
    (35.0, "#A31043"),
    (46.8, "#D5254A"),
    (48.8, "#D7208C"),
    (57.9, "#DF6088"),
    (67.5, "#EA8B77"),
    (71.2, "#E897B4"),
    (83.5, "#FBC78D"),
    (87.5, "#F6D4C5"),
    (100.0, "#FEF0DC"),
]

#: The warm-accent ramp that keeps the reference's gold family alive. A pure
#: gradient map would erase it, and the reference keeps it: 9.35% of pixels,
#: every one warm.
GOLD_STOPS = [
    (0.0, "#2A1206"),
    (35.0, "#8A4A10"),
    (55.0, "#C97A22"),
    (67.2, "#E88E3F"),
    (77.5, "#F6B358"),
    (88.3, "#FED992"),
    (100.0, "#FEF6DF"),
]


#: A black-to-white ramp, with **every non-deterministic knob pinned**.
#:
#: "Synthesise the source with lavfi" is not by itself enough for a golden, and
#: this source is the counterexample: `gradients` defaults to `seed=-1` (random)
#: and `speed=0.01` (rotating), so two identical command lines produce different
#: pixels — measured, two runs differed by the full 255/255. `testsrc2` happens
#: to be bit-reproducible with no pinning; `gradients` is not. Pin the geometry
#: (`x0/y0/x1/y1`), pin `speed=0`, and check any new source for a `seed` before
#: comparing its output to anything.
GREY_RAMP_SOURCE = (
    "gradients=size=64x36:c0=0x000000:c1=0xFFFFFF:type=linear:nb_colors=2:"
    "x0=0:y0=0:x1=63:y1=35:speed=0:seed=1:d=1:r=5"
)


def que_calor_map() -> GradientMap:
    """The first real look, rebuilt from its measured ramp."""
    return gradient_map(
        Ramp.from_hex(QUE_CALOR_STOPS),
        accent=Accent(ramp=Ramp.from_hex(GOLD_STOPS)),
        contrast=1.15,
        lift=-3.0,
    )


def _ffmpeg_or_skip() -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("no ffmpeg on PATH")



def _run(argv):
    """Run ffmpeg and, on failure, say what it SAID.

    `subprocess.run(check=True, capture_output=True)` raises a
    `CalledProcessError` whose message is the command and an exit code, and
    throws the stderr away — so a failure on a machine you cannot log into
    tells you nothing. These tests are the ones most likely to fail on a
    different ffmpeg build, which makes that the wrong trade here.
    """
    proc = subprocess.run(argv, capture_output=True)
    if proc.returncode != 0:
        raise AssertionError(
            f"ffmpeg exited {proc.returncode}\n"
            f"  argv: {' '.join(str(a) for a in argv)}\n"
            f"  stderr: {proc.stderr.decode('utf-8', 'replace').strip()[-800:]}"
        )
    return proc

def _decode(dest, source, *, vf=None):
    """Decode one lavfi source (optionally through ``vf``) to RGB pixel tuples."""
    argv = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source]
    if vf:
        argv += ["-vf", vf]
    argv += ["-f", "rawvideo", "-pix_fmt", "rgb24", str(dest)]
    _run(argv)
    data = dest.read_bytes()
    return [tuple(data[i : i + 3]) for i in range(0, len(data), 3)]


def _apply_lut(cube_path, tmp_path, *, size=(64, 36), frames=5):
    """Run a synthesised clip through ``lut3d`` and return its decoded pixels."""
    w, h = size
    raw = tmp_path / "out.rgb"
    _run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi",
            "-i", f"testsrc2=size={w}x{h}:rate={frames}:duration=1",
            "-vf", f"lut3d={cube_path}",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            str(raw),
        ],
    )
    data = raw.read_bytes()
    return [tuple(data[i : i + 3]) for i in range(0, len(data), 3)]


class TestFfmpegActuallyReadsIt:
    """The only test that proves the file is a `.cube` rather than a text file."""

    def test_ffmpeg_applies_a_generated_lut(self, tmp_path):
        _ffmpeg_or_skip()
        cube = write_cube(que_calor_map(), tmp_path / "look.cube")
        px = _apply_lut(cube, tmp_path)
        assert px, "no pixels came back"

    def test_the_look_has_no_true_black_and_no_true_white(self, tmp_path):
        """The reference's defining measurement, as an assertion.

        Measured on the target: 0.0000% true black, 0.07% true white. A chain
        that produces either has stopped matching it — and this is exactly what
        the classic 'cartoonify' (bilateral + adaptive-threshold black edges)
        gets wrong, since it *adds* ink the reference never had.
        """
        _ffmpeg_or_skip()
        cube = write_cube(que_calor_map(), tmp_path / "look.cube")
        px = _apply_lut(cube, tmp_path)
        black = sum(1 for p in px if max(p) < 8)
        white = sum(1 for p in px if min(p) > 247)
        assert black == 0, f"{black}/{len(px)} pixels are true black"
        assert white == 0, f"{white}/{len(px)} pixels are true white"

    def test_an_identity_lut_is_an_identity(self, tmp_path):
        """`Ramp.neutral()` must leave a grey ramp alone, end to end.

        This is the smoke test for the whole pipeline: if the L* transfer, its
        inverse, or the lattice ordering is wrong, an identity stops being one.
        Every other test here checks the *character* of the output and would
        pass regardless.
        """
        _ffmpeg_or_skip()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # a neutral ramp does reach black
            ident = Ramp.neutral()
        cube = write_cube(ident, tmp_path / "ident.cube", size=DFLT_CUBE_SIZE)

        # A GREY RAMP, not `testsrc2`. A gradient map is a *lightness* map, so
        # a neutral ramp reproduces luminance and pulls saturated colour toward
        # its own grey — on a colour test pattern "identity" is simply the wrong
        # expectation, and `testsrc2` has no near-grey pixels at all to check
        # against. Greys are where identity is meaningful, and where a wrong
        # transfer or a swapped lattice axis shows up.
        got = _decode(tmp_path / "got.rgb", GREY_RAMP_SOURCE, vf=f"lut3d={cube}")
        want = _decode(tmp_path / "want.rgb", GREY_RAMP_SOURCE)

        assert len(got) == len(want)
        spread = max(max(p) for p in want) - min(min(p) for p in want)
        assert spread > 200, f"the ramp only spans {spread}/255 — not a real ramp"

        worst = max(abs(a - b) for g, w in zip(got, want) for a, b in zip(g, w))
        assert worst <= 4, f"neutral ramp shifted grey by {worst}/255"


    def test_a_two_stop_black_to_white_ramp_is_NOT_an_identity(self, tmp_path):
        """The surprise, pinned so nobody re-derives it.

        A ramp interpolates its stop colours in sRGB while indexing on L*, and
        those curves differ: mid-grey sRGB 0.5 is L* 53.39, so the naive ramp
        returns 0.5339 for it. Measured through ffmpeg the shift is ~8/255 —
        **at lattice size 17, 33 AND 65 alike**, which is how you know it is
        systematic rather than interpolation error, and it peaks in the
        midtones rather than the shadows where interpolation error would.
        """
        _ffmpeg_or_skip()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            naive = Ramp.from_hex([(0.0, "#000000"), (100.0, "#FFFFFF")])
        cube = write_cube(naive, tmp_path / "naive.cube", size=DFLT_CUBE_SIZE)
        got = _decode(tmp_path / "got.rgb", GREY_RAMP_SOURCE, vf=f"lut3d={cube}")
        want = _decode(tmp_path / "want.rgb", GREY_RAMP_SOURCE)
        worst = max(abs(a - b) for g, w in zip(got, want) for a, b in zip(g, w))
        assert worst >= 6, (
            f"the naive ramp shifted grey by only {worst}/255 — if this has "
            f"become an identity, `Ramp.at` has changed its interpolation space "
            f"and `Ramp.neutral` may now be redundant"
        )


class TestLatticeOrder:
    """Red varies fastest. A directional test, because a swapped axis loads fine."""

    def test_red_varies_fastest(self):
        """With a neutral ramp, entry 1 of a size-2 cube is (r=1,g=0,b=0).

        Red carries only 21% of luminance and green 72%, so if the order were
        green-fastest the second entry would be much brighter. That asymmetry
        is what makes the direction observable at all.
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ramp = Ramp.from_hex([(0.0, "#000000"), (100.0, "#FFFFFF")])
        rows = [ln for ln in cube_text(ramp, size=2).splitlines() if ln and ln[0].isdigit()]
        assert len(rows) == 8
        second = float(rows[1].split()[0])
        third = float(rows[2].split()[0])
        # index 1 = red, index 2 = green. Green must be the brighter of the two.
        assert second < third, "green is not brighter than red — axes are swapped"

    def test_entry_count_is_size_cubed(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ramp = Ramp.from_hex([(0.0, "#000000"), (100.0, "#FFFFFF")])
        for size in (2, 5, 9):
            rows = [
                ln for ln in cube_text(ramp, size=size).splitlines()
                if ln and ln[0].isdigit()
            ]
            assert len(rows) == size**3


class TestTheShadowFloorLesson:
    """A measured mistake, encoded so it cannot be made silently again."""

    def test_a_ramp_reaching_black_warns(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            gradient_map(Ramp.from_hex([(0.0, "#000000"), (100.0, "#FFFFFF")]))
        assert len(caught) == 1
        assert "crushes shadows" in str(caught[0].message)

    def test_the_que_calor_ramp_does_not_warn(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            que_calor_map()
        assert caught == []

    def test_black_maps_to_the_ramps_floor_not_to_black(self):
        gm = que_calor_map()
        assert rgb_to_hex(gm((0.0, 0.0, 0.0))) == "#2E0C18"


class TestAccent:
    """The hue band a pure ramp would erase."""

    def test_a_warm_pixel_is_pulled_toward_gold(self):
        gm = que_calor_map()
        plain = GradientMap(
            ramp=Ramp.from_hex(QUE_CALOR_STOPS), contrast=1.15, lift=-3.0
        )
        amber = (0.95, 0.82, 0.15)
        with_accent = gm(amber)
        without = plain(amber)
        assert with_accent != without
        # gold is warmer: more red-minus-blue than the bare ramp gives
        assert (with_accent[0] - with_accent[2]) > (without[0] - without[2])

    def test_a_cold_pixel_is_untouched_by_the_accent(self):
        gm = que_calor_map()
        plain = GradientMap(
            ramp=Ramp.from_hex(QUE_CALOR_STOPS), contrast=1.15, lift=-3.0
        )
        blue = (0.15, 0.30, 0.65)
        assert gm(blue) == plain(blue)

    def test_a_grey_pixel_gets_exactly_zero_weight(self):
        """Exactly zero, not nearly zero: `weight() == 0.0` is the predicate
        that skips the second ramp evaluation on all 35,937 lattice points."""
        a = Accent(ramp=Ramp.from_hex(GOLD_STOPS))
        assert a.weight((0.5, 0.5, 0.5)) == 0.0
        assert a.weight((0.15, 0.30, 0.65)) == 0.0


class TestCacheKey:
    """A `.cube` is a build artifact addressed by its ramp's content."""

    def test_same_spec_same_key(self):
        assert cube_key(que_calor_map()) == cube_key(que_calor_map())

    def test_a_changed_stop_changes_the_key(self):
        stops = list(QUE_CALOR_STOPS)
        stops[0] = (8.2, "#2E0C19")  # one unit of blue
        other = gradient_map(
            Ramp.from_hex(stops),
            accent=Accent(ramp=Ramp.from_hex(GOLD_STOPS)),
            contrast=1.15,
            lift=-3.0,
        )
        assert cube_key(other) != cube_key(que_calor_map())

    def test_tone_knobs_are_part_of_identity(self):
        base = Ramp.from_hex(QUE_CALOR_STOPS)
        a = GradientMap(ramp=base, contrast=1.15)
        b = GradientMap(ramp=base, contrast=1.20)
        assert cube_key(a) != cube_key(b)

    def test_lattice_size_is_part_of_identity(self):
        gm = que_calor_map()
        assert cube_key(gm, size=17) != cube_key(gm, size=33)


class TestValidation:
    def test_a_one_stop_ramp_is_refused(self):
        with pytest.raises(LutError, match="at least two stops"):
            Ramp.from_hex([(50.0, "#FFFFFF")])

    def test_unsorted_stops_are_refused(self):
        with pytest.raises(LutError, match="strictly increase"):
            Ramp.from_hex([(50.0, "#FFFFFF"), (10.0, "#000000")])

    def test_out_of_range_lightness_is_refused(self):
        with pytest.raises(LutError, match=r"\[0, 100\]"):
            Ramp.from_hex([(0.0, "#000000"), (140.0, "#FFFFFF")])

    def test_a_size_one_cube_is_refused(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ramp = Ramp.from_hex([(0.0, "#000000"), (100.0, "#FFFFFF")])
        with pytest.raises(LutError, match="size >= 2"):
            cube_text(ramp, size=1)

    def test_bad_hex_is_refused(self):
        with pytest.raises(LutError, match="6-digit hex"):
            hex_to_rgb("#GGGGGG")


class TestLightness:
    def test_endpoints(self):
        assert round(lightness((0.0, 0.0, 0.0)), 6) == 0.0
        assert round(lightness((1.0, 1.0, 1.0)), 6) == 100.0

    def test_green_is_lighter_than_red_at_equal_code_value(self):
        """The reason L* is used rather than a channel mean: at the same code
        value green carries 72% of luminance and red 21%, and an extreme look
        lives exactly where those disagree."""
        assert lightness((0.0, 1.0, 0.0)) > lightness((1.0, 0.0, 0.0))
