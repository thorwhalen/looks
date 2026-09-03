"""Tests for :mod:`looks.spec`.

Most of these are about things the types **refuse**, because the refusals are
where the design lives. An `Effect` that could carry a tier, a `Ref` that could
fall back to a global default, a `SET_RELATIVE` Look that could be resolved
against one clip, a plan that could rehydrate into a licence verdict nobody
observed — each of those would compile, run, and be wrong in a way that does not
announce itself.
"""

import dataclasses

import pytest

from looks.licence import DFLT_POLICY, FieldOfUse, Policy, Tier, terms_for
from looks.spec import (
    EMPTY,
    ClipSpec,
    Effect,
    ImplRef,
    Look,
    LookPlan,
    Ref,
    SchemaError,
    Span,
    SpanUnsupported,
    SpecError,
    Step,
    Target,
    UnresolvedParameter,
    look_from_dict,
    look_hash,
    look_to_dict,
    output_key,
    plan_from_dict,
    plan_hash,
    plan_to_dict,
    resolve,
    resolve_across,
    select_impl,
)

FFMPEG_TERMS = terms_for("ffmpeg")[0]


def an_impl(**kw) -> ImplRef:
    base = dict(
        effect="flatten", impl="flatten.ffmpeg.bilateral", backend="ffmpeg",
        terms=FFMPEG_TERMS,
    )
    base.update(kw)
    return ImplRef(**base)


class TestEffectCarriesNoTier:
    """The single most important decision in the design."""

    def test_effect_has_no_tier_field(self):
        """If a caller could write `Effect(..., tier=PERMISSIVE)` the refusal is
        theatre: the party who wants the answer to be yes asserts it."""
        names = {f.name for f in dataclasses.fields(Effect)}
        assert "tier" not in names
        assert "terms" not in names
        assert "licence" not in names

    def test_constructing_an_effect_consults_no_registry(self):
        """A Look authored against a newer plugin set must still load, print and
        diff in a process that lacks it."""
        e = Effect(name="a-capability-nothing-implements", params={"x": 1})
        assert e.name == "a-capability-nothing-implements"

    def test_a_pin_narrows_and_never_permits(self):
        """`impl`/`backend` say WHICH answer you want, never that you may have
        it — otherwise a pin is a way to assert a tier."""
        # imageio-ffmpeg's binary row is COPYLEFT_SHIPPED — genuinely above a
        # PERMISSIVE ceiling, unlike opencv's `code` row which really is
        # Apache-2.0. Picking the wrong row is how this test first passed for
        # the wrong reason.
        restricted = an_impl(impl="flatten.frame.meanshift", backend="frame",
                             terms=terms_for("imageio-ffmpeg")[0])
        effect = Effect(name="flatten", impl="flatten.frame.meanshift")
        strict = Policy(max_tier=Tier.PERMISSIVE)
        with pytest.raises(SpecError, match="ceiling"):
            select_impl(effect, [restricted], policy=strict)


class TestRefRefusesRatherThanFallsBack:
    """The measured lesson, encoded as a type."""

    def test_a_ref_with_no_default_raises(self):
        with pytest.raises(UnresolvedParameter, match="flatten_scale"):
            resolve(Look(steps=(Effect(name="flatten",
                                       params={"scale": Ref("flatten_scale")}),)), {})

    def test_the_refusal_carries_why_it_is_a_refusal(self):
        """Because the next person's instinct is to add a default."""
        with pytest.raises(UnresolvedParameter) as e:
            Ref("s").resolve({}, where="flatten.scale")
        assert "softest" in str(e.value)

    def test_a_ref_with_a_default_is_tolerable(self):
        look = Look(steps=(Effect(name="flatten", params={"scale": Ref("s", 0.5)}),))
        assert resolve(look, {})[0].params["scale"] == 0.5

    def test_the_probe_beats_the_default(self):
        look = Look(steps=(Effect(name="flatten", params={"scale": Ref("s", 0.5)}),))
        assert resolve(look, {"s": 0.75})[0].params["scale"] == 0.75

    def test_refs_nested_in_containers_are_found_and_resolved(self):
        e = Effect(name="x", params={"a": [Ref("p"), 2], "b": {"c": Ref("q")}})
        assert {r.key for r in e.refs} == {"p", "q"}
        got = e.resolved({"p": 1, "q": 3})
        # A frozen sequence is a TUPLE. `params` is part of what `look_hash`
        # addresses, so freezing it has to reach the containers too — a list
        # left inside stayed aliased to the caller's object and moved the hash
        # after the Look was built. It still serialises as a JSON array.
        assert tuple(got.params["a"]) == (1, 2)
        assert got.params["b"]["c"] == 3

    def test_a_frozen_param_container_is_a_tuple_and_still_serialises(self):
        import json

        from looks.spec import look_to_dict

        look = Look(steps=(Effect(name="x", params={"a": [1, 2], "b": {"c": 3}}),))
        assert isinstance(look.steps[0].params["a"], tuple)
        assert json.loads(json.dumps(look_to_dict(look)))["steps"][0]["params"]["a"] == [
            1,
            2,
        ]

    def test_frozen_really_means_frozen_all_the_way_down(self):
        """§4.9's guarantee, which a one-level freeze did not keep: the caller's
        nested object stayed aliased, so mutating it moved the hash."""
        from looks.spec import look_hash

        nested = {"stops": [[8.2, "#2E0C18"]]}
        look = Look(steps=(Effect(name="gradient_map", params=nested),))
        before = look_hash(look)
        nested["stops"][0][0] = 99.9
        assert look_hash(look) == before

    def test_and_the_values_are_hashable_despite_carrying_mappings(self):
        """`frozen=True` generates a `__hash__`, and a proxy over a dict made
        every one of them raise — including for values carrying no mapping at
        all, because the DEFAULT was one."""
        assert isinstance(hash(Effect(name="x")), int)
        assert isinstance(hash(Look(steps=(Effect(name="x"),))), int)
        assert len({Effect(name="x"), Effect(name="x")}) == 1

    def test_a_frozen_mapping_refuses_mutation_by_name(self):
        look = Look(steps=(Effect(name="x", params={"a": 1}),))
        with pytest.raises(TypeError, match="frozen"):
            look.steps[0].params["a"] = 2

    def test_resolve_is_the_identity_on_a_concrete_look(self):
        """A caller who already has numbers never meets this function."""
        look = Look(steps=(Effect(name="lut3d", params={"cube": "x.cube"}),))
        assert resolve(look) is look


class TestRuleN:
    """A SET_RELATIVE Look may only be resolved across the set."""

    def test_resolve_refuses_a_set_relative_look(self):
        with pytest.raises(SpecError, match="SET_RELATIVE"):
            resolve(Look(target=Target.SET_RELATIVE), {})

    def test_the_refusal_names_the_right_function(self):
        with pytest.raises(SpecError) as e:
            resolve(Look(target=Target.SET_RELATIVE), {})
        assert "resolve_across" in str(e.value)

    def test_resolve_across_returns_one_look_per_probe(self):
        look = Look(target=Target.SET_RELATIVE,
                    steps=(Effect(name="flatten", params={"scale": Ref("s")}),))
        got = resolve_across(look, [{"s": 0.5}, {"s": 0.5}, {"s": 0.75}])
        assert [lk[0].params["scale"] for lk in got] == [0.5, 0.5, 0.75]

    def test_each_result_is_external(self):
        """The set-relative question has been answered; re-resolving would ask
        it again against a different set."""
        look = Look(target=Target.SET_RELATIVE)
        assert resolve_across(look, [{}])[0].target is Target.EXTERNAL

    def test_an_empty_set_has_no_distribution(self):
        with pytest.raises(SpecError, match="at least one probe"):
            resolve_across(Look(target=Target.SET_RELATIVE), [])

    def test_the_field_is_target_not_intent(self):
        """A colour conform is a NORMALISATION with an EXTERNAL target; under a
        style/grade wording it would have to be mislabelled."""
        names = {f.name for f in dataclasses.fields(Look)}
        assert "target" in names
        assert "intent" not in names


class TestCompositionNeverRelaxes:
    """A guarantee composition can silently widen is not a guarantee."""

    def test_the_stricter_ceiling_survives(self):
        strict = Look(policy=Policy(max_tier=Tier.PERMISSIVE))
        loose = Look(policy=Policy(max_tier=Tier.COPYLEFT_SHIPPED))
        assert (strict + loose).policy.max_tier is Tier.PERMISSIVE
        assert (loose + strict).policy.max_tier is Tier.PERMISSIVE

    def test_only_field_restrictions_BOTH_sides_accepted_survive(self):
        """The half of the policy a max_tier comparison would miss."""
        a = Look(policy=Policy(allow_field_restricted=frozenset({FieldOfUse.NON_COMMERCIAL})))
        b = Look(policy=Policy(allow_field_restricted=frozenset()))
        assert (a + b).policy.allow_field_restricted == frozenset()

    def test_set_relative_is_infectious(self):
        """It demands the more capable resolver, so composing with it must not
        quietly produce a Look that `resolve` will accept."""
        assert (Look() + Look(target=Target.SET_RELATIVE)).target is Target.SET_RELATIVE

    def test_widening_is_a_separate_deliberate_act(self):
        narrowed = Look(policy=Policy(max_tier=Tier.PERMISSIVE))
        assert narrowed.with_policy(DFLT_POLICY).policy.max_tier is Tier.COPYLEFT_TOOL


class TestFrozenMeansFrozen:
    """`frozen=True` prevents rebinding a field, not mutating the dict behind it."""

    def test_a_mapping_field_is_frozen_against_the_callers_dict(self):
        d = {"levels": 18}
        e = Effect(name="posterize", params=d)
        d["levels"] = 4
        assert e.params["levels"] == 18

    def test_a_mapping_field_cannot_be_mutated_in_place(self):
        e = Effect(name="posterize", params={"levels": 18})
        with pytest.raises(TypeError):
            e.params["levels"] = 4

    def test_a_hash_cannot_change_after_storage(self):
        """Which is the actual harm: a Look built, hashed and stored, whose hash
        then moves."""
        d = {"levels": 18}
        look = Look(steps=(Effect(name="posterize", params=d),))
        before = look_hash(look)
        d["levels"] = 4
        assert look_hash(look) == before


class TestThreeIdentityLevels:
    def test_look_hash_ignores_metadata_and_policy(self):
        a = Look(name="x", steps=(Effect(name="gamma", params={"g": 1.1}),))
        assert look_hash(a) == look_hash(dataclasses.replace(a, metadata={"who": "t"}))
        assert look_hash(a) == look_hash(a.with_policy(Policy(max_tier=Tier.PURE)))

    def test_look_hash_is_identity_in_the_name_and_the_steps(self):
        a = Look(name="x", steps=(Effect(name="gamma"),))
        assert look_hash(a) != look_hash(dataclasses.replace(a, name="y"))
        assert look_hash(a) != look_hash(Look(name="x", steps=(Effect(name="eq"),)))

    def test_look_hash_is_target_sensitive(self):
        """EXTERNAL and SET_RELATIVE ask different questions of the same steps."""
        a = Look(steps=(Effect(name="gamma"),))
        assert look_hash(a) != look_hash(dataclasses.replace(a, target=Target.SET_RELATIVE))

    def test_plan_hash_includes_the_clips_COLOUR_state(self):
        """Two clips identical in geometry but differing in colour produce
        visibly different pixels through the same LUT — measured at up to
        27/255 — so a hash that omits them is lying."""
        geom = dict(width=1920, height=1080, fps=30.0)
        a = LookPlan(clip=ClipSpec(**geom))
        b = LookPlan(clip=ClipSpec(**geom, color_range="full"))
        c = LookPlan(clip=ClipSpec(**geom, color_space="bt601"))
        assert len({plan_hash(a), plan_hash(b), plan_hash(c)}) == 3

    def test_plan_hash_folds_impl_version_unconditionally(self):
        """nw and falaw omit theirs at the default; that is a migration device
        protecting an installed base, and `looks` has none. Do not copy it."""
        impl = an_impl()
        bumped = dataclasses.replace(impl, impl_version="2")
        step = dict(effect="flatten", tier=Tier.WEAK_COPYLEFT)
        a = LookPlan(steps=(Step(impl=impl, **step),))
        b = LookPlan(steps=(Step(impl=bumped, **step),))
        assert plan_hash(a) != plan_hash(b)

    def test_output_key_takes_a_digest_not_a_path(self):
        """falaw's D1 defect stated as a type: keying on upstream URLs made a
        byte-identical regeneration miss its own cache."""
        with pytest.raises(SpecError, match="content digest"):
            output_key(LookPlan(), "/path/to/clip.mp4")
        assert len(output_key(LookPlan(), "a" * 64)) == 64

    def test_output_key_moves_with_both_halves(self):
        impl = an_impl()
        other = LookPlan(steps=(Step(effect="flatten", impl=impl, tier=Tier.WEAK_COPYLEFT),))
        assert output_key(LookPlan(), "a" * 64) != output_key(LookPlan(), "b" * 64)
        assert output_key(LookPlan(), "a" * 64) != output_key(other, "a" * 64)


class TestCostArithmetic:
    """Unknown is never zero — falaw's rule, transposed to CPU-seconds."""

    def test_a_sum_is_total_so_it_composes(self):
        plan = LookPlan(steps=(
            Step(effect="a", impl=an_impl(), tier=Tier.WEAK_COPYLEFT, cpu_seconds=2.0),
            Step(effect="b", impl=an_impl(), tier=Tier.WEAK_COPYLEFT),
        ))
        assert plan.total_cpu_seconds == 2.0
        assert plan.known_cpu_seconds == 2.0
        assert plan.unknown_step_count == 1
        assert plan.has_unknown_costs

    def test_a_headline_ratio_refuses_to_fabricate(self):
        """The asymmetry is deliberate. Returning 0.0 for 'we did not know' is
        reelee#208, where a $0.00-because-unknown read as 'spend freely'."""
        clip = ClipSpec(width=2, height=2, fps=1.0, duration_s=10.0)
        unknown = LookPlan(clip=clip, steps=(
            Step(effect="a", impl=an_impl(), tier=Tier.WEAK_COPYLEFT),
        ))
        assert unknown.realtime_factor is None
        known = LookPlan(clip=clip, steps=(
            Step(effect="a", impl=an_impl(), tier=Tier.WEAK_COPYLEFT, cpu_seconds=5.0),
        ))
        assert known.realtime_factor == 0.5

    def test_a_negative_cost_is_refused(self):
        with pytest.raises(SpecError, match="non-negative"):
            Step(effect="a", impl=an_impl(), tier=Tier.WEAK_COPYLEFT, cpu_seconds=-1.0)


class TestStepIsConcrete:
    def test_a_surviving_ref_raises(self):
        """A compiled Step is concrete by definition."""
        with pytest.raises(UnresolvedParameter, match="scale"):
            Step(effect="flatten", impl=an_impl(), tier=Tier.WEAK_COPYLEFT,
                 params={"scale": Ref("scale")})


class TestSelectImpl:
    def test_it_picks_the_lowest_tier(self):
        cheap = an_impl(impl="flatten.a", terms=terms_for("looks")[0])
        dear = an_impl(impl="flatten.b")
        assert select_impl(Effect(name="flatten"), [dear, cheap]).impl == "flatten.a"

    def test_preference_breaks_a_tie_within_one_tier(self):
        a = an_impl(impl="flatten.a", preference=1)
        b = an_impl(impl="flatten.b", preference=0)
        assert select_impl(Effect(name="flatten"), [a, b]).impl == "flatten.b"

    def test_a_missing_filter_removes_a_candidate(self):
        impl = an_impl(requires_filters=("bilateral",))
        with pytest.raises(SpecError, match="survived"):
            select_impl(Effect(name="flatten"), [impl],
                        available_filters=frozenset({"scale"}))

    def test_a_span_needs_a_gateable_implementation(self):
        impl = an_impl(timeline=False)
        with pytest.raises(SpanUnsupported, match="span"):
            select_impl(Effect(name="flatten", at=Span(1.0, 2.0)), [impl])

    def test_an_unregistered_capability_says_what_was_offered(self):
        with pytest.raises(SpecError, match="flatten"):
            select_impl(Effect(name="nosuch"), [an_impl()])

    def test_the_ceiling_check_is_delegated_never_re_derived(self):
        """The one place a tier meets a ceiling is licence.check. A second
        comparison here could drift, and drift in a refusal engine is either a
        false refusal or a false permission."""
        import inspect

        from looks import spec

        source = inspect.getsource(spec._admits)
        assert "check(" in source
        assert "<=" not in source and ">=" not in source


class TestSerialisation:
    def test_a_look_round_trips(self):
        look = Look(
            name="que_calor",
            target=Target.SET_RELATIVE,
            policy=Policy(max_tier=Tier.PERMISSIVE),
            steps=(
                Effect(name="flatten", params={"scale": Ref("s", 0.5)}, at=Span(0.0, 2.0)),
                Effect(name="lut3d", params={"cube": "x.cube"}, backend="ffmpeg"),
            ),
            metadata={"author": "t"},
        )
        back = look_from_dict(look_to_dict(look))
        assert look_hash(back) == look_hash(look)
        assert back.target is Target.SET_RELATIVE
        assert back.policy.max_tier is Tier.PERMISSIVE
        assert back.steps[0].params["s" if False else "scale"].default == 0.5

    def test_an_unrecognised_tag_is_refused_loudly(self):
        with pytest.raises(SchemaError, match="looks.look/v1"):
            look_from_dict({"schema": "looks.look/v9"})

    def test_a_missing_tag_is_tolerated_as_v1(self):
        """So hand-written Looks stay easy."""
        assert look_from_dict({"name": "x", "steps": []}).name == "x"

    def test_a_param_value_containing_the_ref_marker_is_refused(self):
        """Documented cost of the `$ref` encoding — and it raises rather than
        being hit silently."""
        with pytest.raises(SchemaError, match=r"\$ref"):
            look_to_dict(Look(steps=(Effect(name="x", params={"a": {"$ref": "no"}}),)))

    def test_a_plan_round_trips_given_its_implementations(self):
        impl = an_impl()
        plan = LookPlan(
            look_name="que_calor",
            clip=ClipSpec(width=1920, height=1080, fps=30.0, color_range="limited"),
            steps=(Step(effect="flatten", impl=impl, tier=Tier.WEAK_COPYLEFT,
                        params={"scale": 0.75}, payload={"filter": "bilateral"}),),
        )
        back = plan_from_dict(plan_to_dict(plan), impls={impl.impl: impl})
        assert plan_hash(back) == plan_hash(plan)

    def test_a_plan_naming_an_absent_implementation_refuses(self):
        """Rebuilding an ImplRef from a key alone would invent its Terms, and
        inventing Terms is inventing a licence verdict. It is also what makes a
        stored plan safe to receive: it cannot name its way into a capability
        the receiving process did not install."""
        impl = an_impl()
        plan = LookPlan(steps=(Step(effect="flatten", impl=impl, tier=Tier.WEAK_COPYLEFT),))
        with pytest.raises(SchemaError, match="does not have"):
            plan_from_dict(plan_to_dict(plan), impls={})


class TestSpanAndClipSpec:
    def test_a_backwards_span_is_refused(self):
        with pytest.raises(SpecError, match="end before it starts"):
            Span(3.0, 1.0)

    def test_untagged_colour_is_a_third_value(self):
        c = ClipSpec(width=2, height=2, fps=1.0)
        assert c.color_range is None and not c.colour_is_declared

    def test_sar_reaches_the_display_aspect(self):
        """`xfade` silently tolerates a sample-aspect mismatch and stamps its
        output 1:1 — the false-permission direction."""
        square = ClipSpec(width=720, height=576, fps=25.0)
        anamorphic = ClipSpec(width=720, height=576, fps=25.0, sar=(16, 15))
        assert anamorphic.aspect > square.aspect

    def test_a_degenerate_clip_is_refused(self):
        with pytest.raises(SpecError, match="positive dimensions"):
            ClipSpec(width=0, height=2, fps=1.0)
        with pytest.raises(SpecError, match="positive fps"):
            ClipSpec(width=2, height=2, fps=0.0)


class TestImplRefDeclaresTermsNotATier:
    def test_it_has_terms_and_no_tier_field(self):
        names = {f.name for f in dataclasses.fields(ImplRef)}
        assert "terms" in names
        assert "tier" not in names

    def test_the_tier_is_derived_on_read(self):
        """So it cannot drift from the terms it came from."""
        impl = an_impl()
        assert impl.tier is not None
        assert impl.tier == an_impl().tier
