"""The registry and the compiler: what gets picked, and what a stored plan may do.

The headline test is :meth:`TestTheSameLookOnTwoBinaries.test_the_binary_picks_the_chain`
— one Look, two binaries, two different chains, no caller involvement. That is
the package's thesis in one assertion: a licence position is a property of the
machine, and the compiler is where the two meet.

The second theme is :func:`~looks.compile.audit`. A plan is a document; documents
arrive from places. Every test in :class:`TestAStoredPlanIsNotTrusted` tampers
with one the way a document from elsewhere might be tampered with, and asserts a
refusal rather than a repaired field.

Offline and free: nothing here starts a process except one `probe()`, and the
second binary is a dataclass replacement of the first.
"""

import dataclasses

import pytest

from looks.compile import (
    CompileError,
    PlanRefused,
    audit,
    compile_all,
    compile_look,
    describe,
    payloads,
    unmet_filters,
)
from looks.environment import FfmpegEnv, Licence, probe
from looks.licence import LooksLicenceError, Policy, Tier, terms_for
from looks.registry import (
    EffectRegistry,
    ImplConflict,
    RegistryError,
    UnknownImpl,
)
from looks.spec import ClipSpec, Effect, ImplRef, Look

FFMPEG_TERMS = terms_for("ffmpeg")[0]
CLIP = ClipSpec(width=1080, height=1920, fps=30)


def impl_ref(key, *, filters=(), preference=0, version="1", backend="ffmpeg"):
    return ImplRef(
        effect=key.split(".")[0],
        impl=key,
        backend=backend,
        terms=FFMPEG_TERMS,
        requires_filters=filters,
        preference=preference,
        impl_version=version,
    )


def a_filter(name):
    def compiler(params, **_kw):
        return {"filter": f"{name}={params.get('arg', '')}"}

    return compiler


@pytest.fixture
def registry():
    """Two ways to grade — one GPL-gated, one not — and one LUT."""
    reg = EffectRegistry()
    reg.register(
        impl_ref("lut3d.ffmpeg.default", filters=("lut3d",)),
        a_filter("lut3d"),
        cost=lambda params, **kw: 0.25,
    )
    reg.register(impl_ref("grade.ffmpeg.eq", filters=("eq",)), a_filter("eq"))
    reg.register(
        impl_ref("grade.ffmpeg.curves", filters=("curves",), preference=1),
        a_filter("curves"),
    )
    return reg


@pytest.fixture
def env():
    e = probe()
    if not e.available:
        pytest.skip("ffmpeg not usable")
    return e


@pytest.fixture
def look():
    return Look(
        steps=(Effect(name="lut3d", params={"arg": "a.cube"}), Effect(name="grade")),
        name="que-calor",
    )


def lgpl_build(env):
    """The same binary, minus its GPL half. `eq` is gated behind --enable-gpl,
    so on an LGPL build it is not compiled in and never appears in -filters."""
    return dataclasses.replace(
        env, licence=Licence.LGPL3, filters=frozenset(env.filters) - {"eq"}
    )


class TestTheSameLookOnTwoBinaries:
    """The thesis. One document, two machines, two answers."""

    def test_the_binary_picks_the_chain(self, registry, env, look):
        gpl = compile_look(look, clip=CLIP, env=env, registry=registry)
        lgpl = compile_look(
            look,
            clip=CLIP,
            env=lgpl_build(env),
            registry=registry,
            policy=Policy(max_tier=Tier.WEAK_COPYLEFT),
        )
        assert [s.impl.impl for s in gpl.steps] == [
            "lut3d.ffmpeg.default",
            "grade.ffmpeg.eq",
        ]
        assert [s.impl.impl for s in lgpl.steps] == [
            "lut3d.ffmpeg.default",
            "grade.ffmpeg.curves",
        ]
        assert {s.tier for s in gpl.steps} == {Tier.COPYLEFT_TOOL}
        assert {s.tier for s in lgpl.steps} == {Tier.WEAK_COPYLEFT}

    def test_the_caller_wrote_no_licence_logic_to_get_that(self, registry, env, look):
        """No branch, no flag, no name in the Look. The Look says `grade`."""
        assert [e.name for e in look.steps] == ["lut3d", "grade"]
        assert all(e.impl is None and e.backend is None for e in look.steps)

    def test_the_plan_records_which_binary_it_was_compiled_against(
        self, registry, env, look
    ):
        gpl = compile_look(look, clip=CLIP, env=env, registry=registry)
        lgpl = compile_look(
            look, clip=CLIP, env=lgpl_build(env), registry=registry,
            policy=Policy(max_tier=Tier.WEAK_COPYLEFT),
        )
        assert gpl.env is not None and gpl.env != lgpl.env, (
            "two binaries must not fingerprint alike, or a plan hash lies"
        )


class TestTheBinaryIsRequiredForAnFfmpegStep:
    """Unknown is a refusal, applied to 'which ffmpeg'."""

    def test_no_env_is_refused_rather_than_assumed(self, registry, look):
        with pytest.raises(CompileError, match="property of the binary"):
            compile_look(look, clip=CLIP, registry=registry)

    def test_an_unusable_binary_is_refused_and_says_so(self, registry, look):
        broken = FfmpegEnv(
            path=None, version=None, licence=Licence.UNKNOWN,
            filters=frozenset(), configuration=None,
            notes=("not on PATH",),
        )
        with pytest.raises(CompileError, match="not usable"):
            compile_look(look, clip=CLIP, env=broken, registry=registry)

    def test_a_non_ffmpeg_backend_needs_no_binary(self):
        """The requirement is about ffmpeg, not about compiling."""
        reg = EffectRegistry()
        reg.register(
            impl_ref("blur.frame.numpy", backend="frame"),
            lambda params, **kw: {"callable": "blur.frame.numpy"},
        )
        plan = compile_look(
            Look(steps=(Effect(name="blur"),)), clip=CLIP, registry=reg
        )
        assert plan.steps[0].impl.backend == "frame"


class TestTheRegistryRefusesEarly:
    """Each of these would otherwise surface as a confusing absence."""

    def test_a_duplicate_key_is_refused(self, registry):
        with pytest.raises(ImplConflict, match="already registered"):
            registry.register(
                impl_ref("grade.ffmpeg.eq", filters=("eq",)), a_filter("eq")
            )

    def test_a_key_that_disagrees_with_its_declaration_is_refused(self):
        reg = EffectRegistry()
        bad = ImplRef(
            effect="grade", impl="colour.ffmpeg.eq", backend="ffmpeg",
            terms=FFMPEG_TERMS,
        )
        with pytest.raises(RegistryError, match="disagrees with what it declares"):
            reg.register(bad, a_filter("eq"))

    def test_a_key_of_the_wrong_shape_is_refused(self):
        reg = EffectRegistry()
        bad = ImplRef(
            effect="grade", impl="grade_eq", backend="ffmpeg", terms=FFMPEG_TERMS
        )
        with pytest.raises(RegistryError, match="segments"):
            reg.register(bad, a_filter("eq"))

    def test_a_misspelled_filter_is_refused_at_registration(self):
        """D-2's lesson one layer up. Left in, the typo makes selection drop
        the candidate on a set test and report 'no implementation available'."""
        reg = EffectRegistry()
        with pytest.raises(RegistryError, match="not ffmpeg"):
            reg.register(
                impl_ref("grade.ffmpeg.typo", filters=("curvez",)), a_filter("x")
            )

    def test_case_matters_because_it_matters_to_ffmpeg(self):
        reg = EffectRegistry()
        with pytest.raises(RegistryError, match="Case matters"):
            reg.register(
                impl_ref("grade.ffmpeg.shouty", filters=("CURVES",)), a_filter("x")
            )

    def test_a_gpl_implementation_may_be_registered(self):
        """The registry records what exists; a Policy refuses at selection.
        Refusing here would stop a caller WITH a GPL ceiling from using one."""
        reg = EffectRegistry()
        assert reg.register(
            impl_ref("grade.ffmpeg.eq", filters=("eq",)), a_filter("eq")
        )

    def test_an_unregistered_effect_is_an_empty_tuple_not_an_error(self, registry):
        assert registry.implementations("nonesuch") == ()

    def test_but_compiling_one_is_a_refusal(self, registry, env):
        with pytest.raises(CompileError, match="nobody implements"):
            compile_look(
                Look(steps=(Effect(name="nonesuch"),)),
                clip=CLIP, env=env, registry=registry,
            )


class TestAStoredPlanIsNotTrusted:
    """A plan is a document, and documents arrive from places."""

    @pytest.fixture
    def plan(self, registry, env, look):
        return compile_look(look, clip=CLIP, env=env, registry=registry)

    def test_an_untampered_plan_passes(self, plan, registry):
        assert audit(plan, registry=registry) is None

    def test_a_plan_claiming_a_tier_its_terms_do_not_support_is_refused(
        self, plan, registry
    ):
        """The one that matters. A plan able to assert its own position could
        assert itself acceptable."""
        forged = dataclasses.replace(
            plan,
            steps=(dataclasses.replace(plan.steps[0], tier=Tier.PURE),)
            + plan.steps[1:],
        )
        with pytest.raises(PlanRefused, match="claims tier"):
            audit(forged, registry=registry)

    def test_the_forged_plan_would_otherwise_have_passed_a_stricter_ceiling(
        self, plan, registry
    ):
        """Why re-deriving is not paranoia: the forgery is not decorative, it
        buys the plan a ceiling it is not entitled to."""
        strict = Policy(max_tier=Tier.PERMISSIVE)
        forged = dataclasses.replace(
            plan,
            steps=(dataclasses.replace(plan.steps[0], tier=Tier.PURE),)
            + plan.steps[1:],
        )
        # Reading the stored tier, step 0 sits under the ceiling.
        assert forged.steps[0].tier == Tier.PURE
        with pytest.raises((PlanRefused, LooksLicenceError)):
            audit(forged, policy=strict, registry=registry)

    def test_a_plan_naming_an_absent_implementation_is_refused(self, plan):
        with pytest.raises(PlanRefused, match="nothing is registered"):
            audit(plan, registry=EffectRegistry())

    def test_a_moved_impl_version_is_refused_rather_than_run(self, plan):
        """Same interface, changed behaviour. Running it would produce
        different pixels under the same plan hash."""
        moved = EffectRegistry()
        moved.register(
            impl_ref("lut3d.ffmpeg.default", filters=("lut3d",), version="2"),
            a_filter("lut3d"),
        )
        moved.register(impl_ref("grade.ffmpeg.eq", filters=("eq",)), a_filter("eq"))
        with pytest.raises(PlanRefused, match="impl_version"):
            audit(plan, registry=moved)

    def test_a_stricter_ceiling_than_the_plan_was_compiled_under_refuses(
        self, plan, registry
    ):
        with pytest.raises(LooksLicenceError):
            audit(plan, policy=Policy(max_tier=Tier.PERMISSIVE), registry=registry)

    def test_the_plans_own_policy_is_the_default_and_the_weaker_check(
        self, plan, registry
    ):
        """Stated so nobody reads a bare audit() as a strong guarantee: a plan
        carrying a permissive policy vouches for itself."""
        assert audit(plan, registry=registry) is None
        assert plan.policy is not None


class TestCostIsUnknownRatherThanZero:
    def test_a_declared_estimator_is_used(self, registry, env, look):
        plan = compile_look(look, clip=CLIP, env=env, registry=registry)
        assert plan.steps[0].cpu_seconds == 0.25

    def test_an_absent_estimator_is_none_and_poisons_the_total(
        self, registry, env, look
    ):
        plan = compile_look(look, clip=CLIP, env=env, registry=registry)
        assert plan.steps[1].cpu_seconds is None
        assert plan.has_unknown_costs
        assert "unknown" in describe(plan)


class TestReadingAPlan:
    def test_an_ffmpeg_payload_is_fully_inspectable(self, registry, env, look):
        plan = compile_look(look, clip=CLIP, env=env, registry=registry)
        assert payloads(plan, "ffmpeg") == (
            {"filter": "lut3d=a.cube"},
            {"filter": "eq="},
        )

    def test_a_payload_that_is_not_data_is_refused(self, env):
        reg = EffectRegistry()
        reg.register(
            impl_ref("bad.ffmpeg.default", filters=("null",)),
            lambda params, **kw: "eq=contrast=1",
        )
        with pytest.raises(CompileError, match="not a mapping"):
            compile_look(
                Look(steps=(Effect(name="bad"),)), clip=CLIP, env=env, registry=reg
            )

    def test_missing_filters_are_a_separate_question_from_licence(
        self, registry, env, look
    ):
        """A ceiling is about what a caller may do; a missing filter is about
        what a machine can do. Different refusals, different fixes."""
        plan = compile_look(look, clip=CLIP, env=env, registry=registry)
        assert unmet_filters(plan, env) == ()
        stripped = dataclasses.replace(
            env, filters=frozenset(env.filters) - {"lut3d"}
        )
        assert unmet_filters(plan, stripped) == ("lut3d",)

    def test_describe_says_unknown_where_it_is_unknown(self, registry, env, look):
        text = describe(compile_look(look, clip=CLIP, env=env, registry=registry))
        assert "lut3d.ffmpeg.default" in text and "cpu=unknown" in text

    def test_an_empty_plan_describes_as_empty(self):
        from looks.spec import LookPlan

        assert describe(LookPlan()) == "(empty plan)"


class TestCompilingSeveral:
    def test_all_or_none(self, registry, env, look):
        good = compile_all([look, look], clip=CLIP, env=env, registry=registry)
        assert len(good) == 2
        with pytest.raises(CompileError):
            compile_all(
                [look, Look(steps=(Effect(name="nonesuch"),))],
                clip=CLIP, env=env, registry=registry,
            )


class TestTheRegistryIsAPlainDictOnPurpose:
    def test_it_imports_nothing_third_party(self):
        """The declared deviation from xdol.Registry: xdol needs dol, and this
        package declares stdlib only."""
        import ast
        import pathlib
        import sys

        import looks.registry

        tree = ast.parse(pathlib.Path(looks.registry.__file__).read_text())
        names = {
            (n.module or "").split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom)
        } | {
            a.name.split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, ast.Import)
            for a in n.names
        }
        outside = {
            n for n in names
            if n and n not in ("looks", "__future__")
            and n not in sys.stdlib_module_names
        }
        assert outside == set(), outside

    def test_tags_are_reserved_and_never_read_by_selection(self, registry, env, look):
        """A tag that changed a refusal would be a tier a caller can assert."""
        reg = EffectRegistry()
        reg.register(
            impl_ref("grade.ffmpeg.eq", filters=("eq",)),
            a_filter("eq"),
            tags=("safe", "commercial", "approved"),
        )
        reg.register(
            impl_ref("grade.ffmpeg.curves", filters=("curves",), preference=1),
            a_filter("curves"),
        )
        plan = compile_look(
            Look(steps=(Effect(name="grade"),)), clip=CLIP, env=env, registry=reg
        )
        assert plan.steps[0].impl.impl == "grade.ffmpeg.eq"
        assert reg.tags("grade.ffmpeg.eq") == frozenset(
            {"safe", "commercial", "approved"}
        )
        assert plan.steps[0].tier == Tier.COPYLEFT_TOOL, (
            "tags must not move a tier"
        )

    def test_registration_order_is_preserved(self, registry):
        assert [i.impl for i in registry.implementations("grade")] == [
            "grade.ffmpeg.eq",
            "grade.ffmpeg.curves",
        ]

    def test_an_unknown_key_names_what_is_available(self, registry):
        with pytest.raises(UnknownImpl, match="3 implementations"):
            registry.impl("grade.ffmpeg.nonesuch")

    def test_the_compiler_behind_a_key_is_reachable(self, registry):
        """How a stored plan becomes runnable work again."""
        assert registry.compiler("lut3d.ffmpeg.default")({"arg": "x.cube"}) == {
            "filter": "lut3d=x.cube"
        }

    def test_a_plan_holds_no_live_callables(self, registry, env, look):
        plan = compile_look(look, clip=CLIP, env=env, registry=registry)
        for step in plan.steps:
            assert all(not callable(v) for v in step.payload.values())
            assert not callable(step.impl)
