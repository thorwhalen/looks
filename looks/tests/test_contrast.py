"""`contrast`, measured against the sibling implementation it must agree with.

`contrast` has two implementations chosen by **licence tier** — `colorlevels`
(LGPL-clean) and `eq` (GPL). The registry's promise is that they are the same
effect, so a caller who cannot use GPL gets the same picture, not a different
one. That promise is the thing under test here, and it is tested by rendering
both and comparing pixels rather than by reading either.

It is tested because it was broken. Every measurement below was taken against
the shipped 0.0.4-0.0.12 implementation first, and each one failed:

* the two implementations moved the picture in **opposite directions** for
  every amount except the identity;
* the emitted `curves` rang under ffmpeg's default `interp` (this package's own
  rule 26, stated and not honoured);
* and at `amount >= 2` the emitted curve was degenerate and ffmpeg **refused
  the render**.

The instrument is a 256-step grey ramp: `geq=lum='X'` over a 256x1 frame, so
one render gives the whole transfer function. Offline and free — `lavfi` in,
`rawvideo` out.
"""

import shutil
import subprocess

import pytest

from looks.compile import compile_look
from looks.environment import probe
from looks.ffmpeg import vf
from looks.registry import EffectRegistry, effects
from looks.ffmpeg import register_defaults
from looks.spec import ClipSpec, Effect, Look, SpecError

CLIP = ClipSpec(width=256, height=1, fps=10)

#: Amounts a caller would plausibly ask for. 2.0 and 3.0 are here because they
#: are exactly where the old implementation stopped rendering.
AMOUNTS = (0.0, 0.25, 0.5, 0.8, 1.0, 1.25, 1.5, 1.8, 2.0, 3.0, 5.0, 10.0)


def _ffmpeg_or_skip():
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")


def transfer(filter_fragment):
    """Push a 256-step ramp through a fragment; return the 256 output levels.

    `None` when ffmpeg refused — which is itself a measurement, and one the old
    implementation produced.
    """
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi",
         "-i", "color=c=black:s=256x1:d=1",
         "-vf", f"format=gray,geq=lum='X',format=rgb24,{filter_fragment}",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or len(proc.stdout) < 256 * 3:
        return None
    return [proc.stdout[i * 3] for i in range(256)]


def ours(amount, env):
    """What the package emits for this amount, as a bare -vf fragment."""
    return vf(compile_look(
        Look(steps=(Effect(name="contrast", params={"amount": amount}),)),
        clip=CLIP, env=env,
    ))


def slope(levels, base):
    """How much the middle of the ramp was stretched. >1 steepened, <1 flattened."""
    return (levels[159] - levels[95]) / (base[159] - base[95])


def drops(levels):
    """Steps where the transfer goes DOWN — a monotone transfer has none."""
    return [a - b for a, b in zip(levels, levels[1:]) if b < a]


@pytest.fixture(scope="module")
def env():
    _ffmpeg_or_skip()
    return probe()


@pytest.fixture(scope="module")
def base():
    _ffmpeg_or_skip()
    got = transfer("null")
    assert got is not None
    return got


class TestTheTwoImplementationsAreOneEffect:
    """The licence tier chooses the filter. It must not choose the picture."""

    @pytest.mark.parametrize("amount", AMOUNTS)
    def test_they_move_the_picture_the_same_way(self, amount, env, base):
        """The defect that mattered most: for every amount except the identity,
        the LGPL path did the OPPOSITE of the GPL one. Measured on the shipped
        implementation at amount=1.5 — LGPL slope 0.45, GPL slope 1.48."""
        _ffmpeg_or_skip()
        mine = transfer(ours(amount, env))
        gpl = transfer(f"eq=contrast={amount}")
        assert mine is not None, f"our contrast did not render at amount={amount}"
        assert gpl is not None
        ours_s, gpl_s = slope(mine, base), slope(gpl, base)
        assert (ours_s - 1.0) * (gpl_s - 1.0) >= 0, (
            f"amount={amount}: we steepen/flatten by {ours_s:.3f} and eq by "
            f"{gpl_s:.3f} — opposite directions for the same named effect"
        )

    @pytest.mark.parametrize("amount", (0.5, 0.8, 1.0, 1.25, 1.5, 1.8, 2.0))
    def test_they_agree_closely_enough_to_be_interchangeable(self, amount, env):
        """Direction is the floor; through the useful range they should also
        land in nearly the same place. Measured: within 5/255. The bound is
        loose enough for two different filters and tight enough to catch a
        wrong pivot or a wrong slope."""
        _ffmpeg_or_skip()
        mine = transfer(ours(amount, env))
        gpl = transfer(f"eq=contrast={amount}")
        worst = max(abs(a - b) for a, b in zip(mine, gpl))
        assert worst <= 8, f"amount={amount}: worst disagreement {worst}/255"

    def test_the_identity_really_is_the_identity(self, env, base):
        """amount=1 must be a no-op, or every neutral look drifts."""
        _ffmpeg_or_skip()
        mine = transfer(ours(1.0, env))
        assert max(abs(a - b) for a, b in zip(mine, base)) <= 1

    def test_and_so_is_the_default(self, env, base):
        """`Effect(name="contrast")` with no params. Found by mutation: every
        other test passes an explicit amount, so a wrong DEFAULT was invisible
        to all of them."""
        _ffmpeg_or_skip()
        fragment = vf(compile_look(
            Look(steps=(Effect(name="contrast"),)), clip=CLIP, env=env,
        ))
        mine = transfer(fragment)
        assert mine is not None
        assert max(abs(a - b) for a, b in zip(mine, base)) <= 1


class TestItRendersAtEveryAmount:
    """The old implementation clamped its interior points onto its endpoints,
    and ffmpeg refuses a curve with a repeated x. A contrast of 2 is not
    exotic, and the failure was a dead render rather than a bad picture."""

    @pytest.mark.parametrize("amount", AMOUNTS)
    def test_it_renders(self, amount, env):
        _ffmpeg_or_skip()
        assert transfer(ours(amount, env)) is not None, (
            f"amount={amount} produced a fragment ffmpeg would not run"
        )

    def test_the_old_form_really_did_refuse(self):
        """The premise, pinned. Without this the fix's justification is a
        claim about a version nobody can run any more."""
        _ffmpeg_or_skip()
        old = "curves=all='0/0 0.0000/0.25 1.0000/0.75 1/1'"
        assert transfer(old) is None, (
            "the degenerate curve the old implementation emitted at amount=2 "
            "is expected to be refused by ffmpeg"
        )

    def test_a_negative_amount_is_refused_here(self, env):
        """Not by ffmpeg three stages later — inverting the picture is a
        different effect than the one being asked for."""
        with pytest.raises(SpecError, match="must not be negative"):
            ours(-1.0, env)


class TestTheTransferIsMonotone:
    """A contrast curve that goes DOWN anywhere is posterisation, and it ships
    invisibly because a gentle amount does not trip it — which is rule 26's
    whole point."""

    @pytest.mark.parametrize("amount", AMOUNTS)
    def test_no_step_goes_backwards(self, amount, env):
        _ffmpeg_or_skip()
        got = transfer(ours(amount, env))
        assert drops(got) == [], (
            f"amount={amount}: {len(drops(got))} non-monotone steps, worst "
            f"{max(drops(got))} LSB"
        )

    def test_the_old_form_really_did_ring(self):
        """The premise for rule 26, measured rather than cited: the shipped
        curve at amount=1.8 under ffmpeg's DEFAULT interpolation."""
        _ffmpeg_or_skip()
        old = "curves=all='0/0 0.0500/0.25 0.9500/0.75 1/1'"
        got = transfer(old)
        assert got is not None
        assert len(drops(got)) > 50, (
            "expected the natural spline to ring on this knee; measured 89 "
            f"steps, got {len(drops(got))}"
        )

    def test_and_pchip_would_have_helped_but_not_enough(self):
        """Why the fix is not simply rule 26's `interp=pchip`. It removes the
        ringing, but a spline still eases through the clip corner — measured
        up to 45/255 away from `eq`, where `colorlevels` is within 5."""
        _ffmpeg_or_skip()
        knee = "0/0 0.0500/0.25 0.9500/0.75 1/1"
        rang = transfer(f"curves=all='{knee}'")
        fixed = transfer(f"curves=all='{knee}':interp=pchip")
        assert len(drops(rang)) > 50
        assert all(d <= 1 for d in drops(fixed)), (
            "pchip should leave at most 1-LSB rounding"
        )


class TestRule26HoldsForAnythingThatEmitsCurves:
    """`contrast` no longer emits `curves` at all, so this is a perimeter
    rather than a check on one effect: the day someone adds a curves-based
    effect, rule 26 applies to it and this fails if it is forgotten.

    A guard over an empty set proves nothing, so the detector is exercised
    against a positive control in the same test.
    """

    @staticmethod
    def offends(fragment):
        """Rule 26: a `curves` emission must name `interp=pchip`."""
        return "curves=" in fragment and "interp=pchip" not in fragment

    def test_the_detector_detects(self):
        """The positive control, without which the sweep below is vacuous."""
        assert self.offends("curves=all=0/0 1/1")
        assert not self.offends("curves=all=0/0 1/1:interp=pchip")
        assert not self.offends("colorlevels=rimin=0.25")

    def test_no_registered_effect_emits_a_bare_curves(self, env):
        _ffmpeg_or_skip()
        registry = register_defaults(EffectRegistry())
        offenders, examined = [], 0
        for name in registry.effects():
            for params in ({}, {"amount": 1.5}, {"amount": 0.5}):
                try:
                    fragment = vf(compile_look(
                        Look(steps=(Effect(name=name, params=params),)),
                        clip=CLIP, env=env, registry=registry,
                    ))
                except Exception:
                    continue
                examined += 1
                if self.offends(fragment):
                    offenders.append((name, params, fragment))
        assert not offenders, (
            "rule 26: `curves` must be emitted with interp=pchip, never the "
            f"default. Offending: {offenders}"
        )
        # A sweep that examined nothing is a guard that proves nothing. These
        # params reach 8 of the 14 registered effects; the geometry and LUT
        # ones need arguments this loop does not invent.
        assert examined >= 8, (
            f"the sweep only compiled {examined} fragments — it has gone "
            "vacuous, and would pass no matter what the registry emits"
        )
