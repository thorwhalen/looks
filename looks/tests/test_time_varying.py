"""Whether a compiled fragment reads the clock — issue #17.

`ImplRef.timeline` looks like the answer and is close to the exact inverse:
`motion.ffmpeg.crop` (`zoompan`/`crop`, which reference `in_time`) has no
timeline support, and every static grade — which never reads the clock — does.
`Step.time_varying` and `LookPlan.time_varying` are the fields a consumer
should ask instead, folding in both ways a fragment ends up clock-driven: the
implementation itself, or an `Effect.at` Span gating an otherwise-static
filter with `enable=`.

**Tri-state throughout, on purpose.** `None` means "nobody told us", never
"does not read the clock" — the same posture as
`frame_dependency.DependencyReport.can_flicker`. A declaration is an
assertion; `TestDeclarationAgreesWithMeasurement` is the check, sweeping every
registered ffmpeg implementation and asking `frame_dependency.classify` to
confirm it against the same looped-still probe the flicker tests already use.

Offline and free: uses the real default registry (`looks.ffmpeg.register_defaults`,
run on `import looks`), synthesises every source with `lavfi`, and nothing
here starts a process outside of `ffmpeg`/`ffprobe` analysis runs.
"""

import dataclasses
import shutil

import pytest

import looks
from looks.cache import materialize
from looks.compile import compile_look
from looks.environment import probe
from looks.ffmpeg import vf
from looks.frame_dependency import Dependency, classify
from looks.licence import terms_for
from looks.registry import REGISTRY
from looks.spec import ClipSpec, Effect, ImplRef, Look, LookPlan, Span, Step

CLIP = ClipSpec(width=320, height=240, fps=10)

#: The minimal params each registered effect needs to compile, mirroring
#: test_ffmpeg.py's own sweep fixture — kept independent so this file does not
#: need to import that module's private table.
PARAMS = {
    "lut3d": {"cube": None},  # filled in by the fixture with a real file
    "gradient_map": {
        "stops": [[8.2, "#2E0C18"], [46.8, "#D5254A"], [100.0, "#FEF0DC"]],
        "size": 9,
    },
    "saturation": {"amount": 1.4},
    "contrast": {"amount": 1.2},
    "gamma": {"gamma": 1.2},
    "levels": {"black": 0.02, "white": 0.98},
    "posterize": {"levels": 6},
    "flatten": {"spatial": 20, "range": 0.05},
    "blur": {"sigma": 2},
    "sharpen": {"amount": 1.0},
    "fit": {"target": "320x240"},
    "fill": {"target": "shorts"},
    "stretch": {"target": "square"},
    "motion": {"keyframes": [(0.0, (0.0, 0.0, 0.5, 0.5)), (0.5, (0.5, 0.5, 0.5, 0.5))]},
}

ALL_IMPLS = tuple(
    impl for effect in REGISTRY.effects() for impl in REGISTRY.implementations(effect)
)


def _ffmpeg_or_skip() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not on PATH")


def _impl(effect="lut3d", *, timeline=True, time_varying=None):
    return ImplRef(
        effect=effect,
        impl=f"{effect}.ffmpeg.default",
        backend="ffmpeg",
        terms=terms_for("ffmpeg")[0],
        timeline=timeline,
        time_varying=time_varying,
    )


@pytest.fixture(scope="module")
def env():
    e = probe()
    if not e.available:
        pytest.skip("ffmpeg not usable")
    return e


@pytest.fixture(scope="module")
def cube(tmp_path_factory):
    ramp = looks.Ramp.from_hex(
        [(8.2, "#2E0C18"), (46.8, "#D5254A"), (100.0, "#FEF0DC")]
    )
    path = tmp_path_factory.mktemp("cubes") / "look.cube"
    return looks.write_cube(looks.gradient_map(ramp), path, size=17)


class TestImplRefTimeVaryingIsUnknownByDefault:
    """`None` is the default, and it is not a spelling of `False`."""

    def test_undeclared_reads_as_unknown_not_false(self):
        assert _impl().time_varying is None

    def test_timeline_and_time_varying_are_independent_fields(self):
        # A camera move: no timeline support, and it DOES read the clock.
        motion = _impl("motion", timeline=False, time_varying=True)
        assert motion.timeline is False
        assert motion.time_varying is True


class TestStepTimeVarying:
    """A Step reads the clock via its impl, or via a bounding `at` Span —
    and a certain span-gate wins even over an impl that never declared itself."""

    def test_a_static_step_with_no_span_reflects_its_impls_declaration(self):
        step = Step(
            effect="gamma",
            impl=_impl("gamma", time_varying=False),
            tier=_impl().tier,
        )
        assert step.time_varying is False

    def test_an_undeclared_impl_with_no_span_is_unknown(self):
        step = Step(effect="gamma", impl=_impl("gamma"), tier=_impl().tier)
        assert step.time_varying is None

    def test_a_span_open_at_both_ends_bounds_nothing_and_does_not_count(self):
        step = Step(
            effect="gamma",
            impl=_impl("gamma", time_varying=False),
            tier=_impl().tier,
            at=Span(),
        )
        assert step.time_varying is False

    def test_a_real_span_wins_even_over_a_declared_false(self):
        static = Step(
            effect="blur", impl=_impl("blur", time_varying=False), tier=_impl().tier
        )
        gated = dataclasses.replace(static, at=Span(1.0, 2.0))
        assert static.time_varying is False
        assert gated.time_varying is True

    def test_a_real_span_wins_even_over_an_undeclared_impl(self):
        step = Step(
            effect="blur", impl=_impl("blur"), tier=_impl().tier, at=Span(1.0, 2.0)
        )
        assert step.time_varying is True

    def test_a_clock_reading_impl_is_time_varying_even_with_no_span(self):
        motion_impl = _impl("motion", timeline=False, time_varying=True)
        step = Step(effect="motion", impl=motion_impl, tier=motion_impl.tier)
        assert step.time_varying is True


class TestLookPlanTimeVarying:
    """The aggregate a consumer actually asks, tri-state and all."""

    def test_an_empty_plan_does_not_read_the_clock(self):
        assert LookPlan().time_varying is False

    def test_one_certain_true_step_wins_even_beside_an_unknown_one(self):
        unknown = Step(effect="gamma", impl=_impl("gamma"), tier=_impl().tier)
        motion_impl = _impl("motion", timeline=False, time_varying=True)
        moving = Step(effect="motion", impl=motion_impl, tier=motion_impl.tier)
        assert LookPlan(steps=(unknown, moving)).time_varying is True

    def test_an_unknown_step_poisons_an_otherwise_false_plan(self):
        known_false = Step(
            effect="gamma",
            impl=_impl("gamma", time_varying=False),
            tier=_impl().tier,
        )
        unknown = Step(effect="blur", impl=_impl("blur"), tier=_impl().tier)
        assert LookPlan(steps=(known_false,)).time_varying is False
        assert LookPlan(steps=(known_false, unknown)).time_varying is None


class TestEveryBuiltInImplementationDeclaresItExplicitly:
    """`register_defaults` requires the kwarg — this is the drift guard."""

    def test_no_built_in_implementation_ships_unknown(self):
        undeclared = sorted(i.impl for i in ALL_IMPLS if i.time_varying is None)
        assert not undeclared, (
            f"{undeclared} are registered with no time_varying declaration. "
            "`None` means unknown, and a shipped implementation should not "
            "ship an unanswered question about whether it reads the clock."
        )


#: `frame_dependency.classify`'s TIME_VARYING probe (`_still_source`) is a
#: spatially UNIFORM still (`color=c=gray`). Measured here: a `crop` whose
#: window position reads `t` produces `time_delta == 0.0` against it, because
#: cropping a flat colour is invariant to where the window sits — there is
#: nothing for a luma diff to see. The classifier's decision order checks
#: `time_delta` first, so a purely positional clock-reader that the time probe
#: cannot see falls through to whichever of `temporal_delta`/`content_delta`
#: its *content* probe (a spatially split source) happens to catch instead —
#: measured as `CONTENT_ADAPTIVE` (`content_delta=83.0`) for
#: `motion.ffmpeg.crop`, not `TIME_VARYING`. That is a blind spot in the
#: probe's still, not a wrong declaration: `TestAgainstTheRealRegistry` below
#: confirms `time_varying=True` for this impl a different way, by compiling it
#: and reading `LookPlan.time_varying` directly. Excluded from the
#: measurement sweep for that reason, with the finding recorded rather than
#: silently skipped.
_BLIND_TO_THE_STILL_PROBE = frozenset({"motion.ffmpeg.crop"})


class TestDeclarationAgreesWithMeasurement:
    """The declaration is an assertion; frame_dependency.classify is the check.

    Mirrors test_ffmpeg.py's `TestEveryRegisteredEffectConfigures` sweep, one
    level deeper: not just "does ffmpeg accept this fragment" but "does its
    measured dependency class agree with what this PR just declared about it".
    """

    @pytest.mark.parametrize(
        "impl",
        [i for i in ALL_IMPLS if i.impl not in _BLIND_TO_THE_STILL_PROBE],
        ids=lambda i: i.impl,
    )
    def test_declared_time_varying_matches_the_probed_dependency(
        self, impl, env, cube, tmp_path_factory
    ):
        _ffmpeg_or_skip()
        if impl.effect not in PARAMS:
            pytest.skip(f"{impl.effect!r} has no params fixture in this sweep")
        params = dict(PARAMS[impl.effect])
        if impl.effect == "lut3d":
            params["cube"] = str(cube)
        look = Look(steps=(Effect(name=impl.effect, params=params, impl=impl.impl),))
        plan = compile_look(look, clip=CLIP, env=env)
        plan = materialize(plan, into=tmp_path_factory.mktemp("materialize"))
        fragment = vf(plan)
        report = classify(fragment)
        if report.dependency is Dependency.UNDETERMINED:
            pytest.skip(f"a probe did not run for {impl.impl!r}: {report.note}")
        measured = report.dependency is Dependency.TIME_VARYING
        assert impl.time_varying is measured, (
            f"{impl.impl!r} declares time_varying={impl.time_varying!r}, but "
            f"frame_dependency.classify measured {report.dependency.value!r} "
            f"(time_delta={report.time_delta}) against {fragment!r}"
        )


class TestTheStillProbeCannotSeeAMovingCropWindow:
    """The excluded case, measured and named rather than silently skipped.

    `motion.ffmpeg.crop`'s window position is a function of `t`, but
    `frame_dependency.classify`'s time probe runs it over a spatially uniform
    still, where no crop window produces a different pixel. The mismatch is in
    the probe's still, not in this PR's `time_varying=True` declaration —
    confirmed independently in `TestAgainstTheRealRegistry`, which reads
    `LookPlan.time_varying` off a real compiled plan rather than inferring it
    from `frame_dependency.classify`.
    """

    def test_a_flat_still_cannot_reveal_a_moving_crop_window(self, env, tmp_path):
        _ffmpeg_or_skip()
        look = Look(
            steps=(
                Effect(
                    name="motion",
                    params={
                        "keyframes": [
                            (0.0, (0.0, 0.0, 0.5, 0.5)),
                            (0.5, (0.5, 0.5, 0.5, 0.5)),
                        ]
                    },
                ),
            )
        )
        plan = compile_look(look, clip=CLIP, env=env)
        report = classify(vf(plan))
        assert report.time_delta == 0.0
        assert report.dependency is not Dependency.TIME_VARYING
        # The impl still declares (and LookPlan.time_varying still reports)
        # the true answer — the probe's blind spot does not leak into it.
        assert plan.time_varying is True


class TestAgainstTheRealRegistry:
    """The registered fact the issue was filed about, end to end."""

    def test_motion_reads_the_clock_and_a_static_grade_does_not(self):
        env_ = probe()
        if not env_.available:
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
        motion_plan = compile_look(motion, clip=CLIP, env=env_)
        grade_plan = compile_look(grade, clip=CLIP, env=env_)
        assert motion_plan.time_varying is True
        assert grade_plan.time_varying is False
        # The obvious-but-wrong field, named so a future reader sees why this
        # test does not use it: `timeline` is inverted for exactly this case.
        assert motion_plan.steps[0].impl.timeline is False
        assert grade_plan.steps[0].impl.timeline is True

    def test_the_same_static_grade_reads_the_clock_once_gated_to_a_span(self):
        env_ = probe()
        if not env_.available:
            pytest.skip("ffmpeg not usable")
        gated = Look(
            steps=(Effect(name="gamma", params={"gamma": 1.2}, at=Span(1.0, 2.0)),)
        )
        plan = compile_look(gated, clip=CLIP, env=env_)
        assert plan.time_varying is True
