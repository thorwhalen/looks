"""Whether a compiled fragment reads the clock — issue #17.

`ImplRef.timeline` looks like the answer and is close to the exact inverse:
`motion.ffmpeg.crop` (`zoompan`/`crop`, which reference `in_time`) has no
timeline support, and every static grade — which never reads the clock — does.
`Step.time_varying` and `LookPlan.time_varying` are the fields a consumer
should ask instead, folding in both ways a fragment ends up clock-driven: the
implementation itself, or an `Effect.at` Span gating an otherwise-static
filter with `enable=`.

Offline and free: uses the real default registry (`looks.ffmpeg.register_defaults`,
run on `import looks`), and nothing here starts a process.
"""

import dataclasses

from looks.compile import compile_look
from looks.environment import probe
from looks.spec import ClipSpec, Effect, ImplRef, Look, Span, Step
from looks.licence import terms_for

CLIP = ClipSpec(width=1080, height=1920, fps=30)


def _impl(effect="lut3d", *, timeline=True, time_varying=False):
    return ImplRef(
        effect=effect,
        impl=f"{effect}.ffmpeg.default",
        backend="ffmpeg",
        terms=terms_for("ffmpeg")[0],
        timeline=timeline,
        time_varying=time_varying,
    )


class TestImplRefTimeVaryingIsNotTimeline:
    """The two fields answer different questions and default oppositely."""

    def test_default_implementation_does_not_read_the_clock(self):
        assert _impl().time_varying is False

    def test_timeline_and_time_varying_are_independent_fields(self):
        # A camera move: no timeline support, and it DOES read the clock.
        motion = _impl("motion", timeline=False, time_varying=True)
        assert motion.timeline is False
        assert motion.time_varying is True


class TestStepTimeVarying:
    """A Step reads the clock via its impl, or via a bounding `at` Span."""

    def test_a_static_step_with_no_span_does_not_read_the_clock(self):
        step = Step(effect="gamma", impl=_impl("gamma"), tier=_impl().tier)
        assert step.time_varying is False

    def test_a_span_open_at_both_ends_bounds_nothing_and_does_not_count(self):
        step = Step(effect="gamma", impl=_impl("gamma"), tier=_impl().tier, at=Span())
        assert step.time_varying is False

    def test_a_real_span_on_an_otherwise_static_impl_reads_the_clock(self):
        static = Step(effect="blur", impl=_impl("blur"), tier=_impl().tier)
        gated = dataclasses.replace(static, at=Span(1.0, 2.0))
        assert static.time_varying is False
        assert gated.time_varying is True

    def test_a_clock_reading_impl_is_time_varying_even_with_no_span(self):
        motion_impl = _impl("motion", timeline=False, time_varying=True)
        step = Step(effect="motion", impl=motion_impl, tier=motion_impl.tier)
        assert step.time_varying is True


class TestLookPlanTimeVarying:
    """The aggregate a consumer actually asks: does ANY step read the clock?"""

    def test_an_empty_plan_does_not_read_the_clock(self):
        from looks.spec import LookPlan

        assert LookPlan().time_varying is False

    def test_one_time_varying_step_among_static_ones_is_enough(self):
        from looks.spec import LookPlan

        static = Step(effect="gamma", impl=_impl("gamma"), tier=_impl().tier)
        motion_impl = _impl("motion", timeline=False, time_varying=True)
        moving = Step(effect="motion", impl=motion_impl, tier=motion_impl.tier)
        assert LookPlan(steps=(static, moving)).time_varying is True
        assert LookPlan(steps=(static,)).time_varying is False


class TestAgainstTheRealRegistry:
    """The registered fact the issue was filed about, end to end."""

    def test_motion_reads_the_clock_and_a_static_grade_does_not(self):
        env = probe()
        if not env.available:
            import pytest

            pytest.skip("ffmpeg not usable")
        motion = Look(
            steps=(
                Effect(
                    name="motion",
                    params={"keyframes": [(0.0, (0.0, 0.0, 1.0, 1.0))]},
                ),
            )
        )
        grade = Look(steps=(Effect(name="gamma", params={"gamma": 1.2}),))
        motion_plan = compile_look(motion, clip=CLIP, env=env)
        grade_plan = compile_look(grade, clip=CLIP, env=env)
        assert motion_plan.time_varying is True
        assert grade_plan.time_varying is False
        # The obvious-but-wrong field, named so a future reader sees why this
        # test does not use it: `timeline` is inverted for exactly this case.
        assert motion_plan.steps[0].impl.timeline is False
        assert grade_plan.steps[0].impl.timeline is True

    def test_the_same_static_grade_reads_the_clock_once_gated_to_a_span(self):
        env = probe()
        if not env.available:
            import pytest

            pytest.skip("ffmpeg not usable")
        gated = Look(
            steps=(Effect(name="gamma", params={"gamma": 1.2}, at=Span(1.0, 2.0)),)
        )
        plan = compile_look(gated, clip=CLIP, env=env)
        assert plan.time_varying is True
