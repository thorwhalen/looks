"""Tests for :mod:`looks.licence`.

Two of these matter more than the rest, and they are in the first class. The
design of this module survived contact with a reviewer twice, in the
false-permission direction both times:

1. a total-order ladder that admits an in-process GPL library the moment you
   raise the ceiling for a research model, and
2. an early return that lets a field-of-use opt-in silently waive the copyleft
   ceiling.

Each has a guard here, and each guard has a **mutation** next to it — a local
reimplementation of the broken behaviour, asserted to admit exactly what the
real code refuses. A refusal guard that has quietly stopped refusing is worse
than no guard, and the only way to know is to break it on purpose.
"""

import json
import shutil

import pytest

from looks.environment import FfmpegEnv, Licence, UnknownFilter, probe
from looks.licence import (
    DFLT_LADDER,
    DFLT_POLICY,
    DISCLAIMER,
    LEDGER_PATH,
    LEDGER_SCHEMA,
    RESTRICTED_FIELDS,
    SEE_DISCLAIMER,
    STRONG_COPYLEFT,
    Assessment,
    Conveyance,
    Coupling,
    Evidence,
    FieldOfUse,
    LicenceCeilingExceeded,
    LicenceFieldRestricted,
    LicenceForbidden,
    LicenceUnknown,
    LooksLicenceError,
    Patent,
    Policy,
    Reach,
    Terms,
    Tier,
    Verdict,
    assess,
    assess_ffmpeg_chain,
    check,
    classify,
    ffmpeg_terms,
    ledger,
    project_onto_ladder,
    reach_of,
    terms_for,
    unverified_claims,
)

#: The most permissive policy this module can express: the top rung, plus every
#: field-of-use restriction opted into. Anything still refused under THIS is
#: refused unconditionally, which is what "off the ladder" has to mean.
MOST_PERMISSIVE = Policy(
    max_tier=Tier.COPYLEFT_SHIPPED,
    allow_field_restricted=frozenset(RESTRICTED_FIELDS),
)


def _terms(**kwargs) -> Terms:
    """A well-formed Terms row, overridable field by field."""
    base = dict(
        provider="p",
        realisation="system",
        component="code",
        spdx="MIT",
        coupling=Coupling.SUBPROCESS,
        conveyance=Conveyance.FINDS,
        field_of_use=FieldOfUse.UNRESTRICTED,
        evidence=(
            Evidence(method="read", observed="a fixture", observed_on="2026-09-02"),
        ),
    )
    base.update(kwargs)
    return Terms(**base)


#: The exact provider the reviewer's counter-example used: a GPL-3 program,
#: executed rather than linked, shipped by the distribution that declares it,
#: and licensed for non-commercial use only.
NON_COMMERCIAL_SHIPPED_GPL = _terms(
    provider="nc-model",
    realisation="pypi:nc-model",
    component="weights",
    spdx="GPL-3.0-or-later",
    coupling=Coupling.SUBPROCESS,
    conveyance=Conveyance.CONVEYS,
    field_of_use=FieldOfUse.NON_COMMERCIAL,
)

#: In-process AGPL — the forbidden region, and a real row (ultralytics).
IN_PROCESS_STRONG = _terms(
    provider="ultralytics",
    realisation="pypi:ultralytics",
    spdx="AGPL-3.0-or-later",
    coupling=Coupling.IN_PROCESS,
    conveyance=Conveyance.CONVEYS,
)

#: A research-only model. The thing a caller might raise a ceiling "for".
RESEARCH_ONLY = _terms(
    provider="fast-neural-style",
    realisation="github:jcjohnson/fast-neural-style",
    component="model",
    spdx="BSD-3-Clause",
    coupling=Coupling.IN_PROCESS,
    conveyance=Conveyance.FINDS,
    field_of_use=FieldOfUse.RESEARCH_ONLY,
)


class TestTheTwoFatalObjections:
    """The two ways this module can be quietly wrong."""

    def test_no_ceiling_reaches_the_forbidden_region(self):
        """Objection 1. A rung you can opt into is not "always refuse"."""
        with pytest.raises(LicenceForbidden):
            check(classify(IN_PROCESS_STRONG), MOST_PERMISSIVE, "effect 'detect'")

    def test_raising_the_ceiling_for_a_research_model_admits_nothing_else(self):
        """Objection 1, in the shape it actually arrives in.

        A caller opts into research-only terms for one model. On a single total
        order that also raises the ceiling past the copyleft rungs — so an
        in-process GPL library, and a self-contradictory one, come with it.
        """
        for_research = Policy(allow_field_restricted={FieldOfUse.RESEARCH_ONLY})
        check(classify(RESEARCH_ONLY), for_research, "effect 'stylize'")

        with pytest.raises(LicenceForbidden):
            check(classify(IN_PROCESS_STRONG), for_research, "effect 'detect'")
        contradictory = _terms(
            provider="av",
            realisation="pypi:av",
            component="binary",
            spdx="LicenseRef-CONTRADICTORY",
            coupling=Coupling.IN_PROCESS,
            conveyance=Conveyance.CONVEYS,
            field_of_use=FieldOfUse.UNKNOWN,
            contradiction="metadata, self-report and otool -L disagree",
        )
        with pytest.raises(LicenceUnknown):
            check(classify(contradictory), for_research, "effect 'decode'")

    def test_mutation_a_single_total_order_admits_what_the_regions_refuse(self):
        """The guard above has teeth only if the rejected design fails it.

        The rejected design is one ladder with the off-ladder regions folded in
        as rungs. Under it, a ceiling raised to reach a research model reaches
        every rung beneath — including in-process strong copyleft.
        """
        total_order = (
            "pure",
            "permissive",
            "weak_copyleft",
            "copyleft_tool",
            "copyleft_shipped",
            "in_process_strong",
            "field_restricted",
        )

        def admits(position: str, ceiling: str) -> bool:
            return total_order.index(position) <= total_order.index(ceiling)

        assert admits("in_process_strong", "field_restricted")
        assert admits("copyleft_shipped", "field_restricted")

        # The shipped design refuses both, at its most permissive setting.
        with pytest.raises(LicenceForbidden):
            check(classify(IN_PROCESS_STRONG), MOST_PERMISSIVE, "x")

    def test_a_field_of_use_opt_in_does_not_waive_the_copyleft_ceiling(self):
        """Objection 2, verbatim from the decisions document.

        ``Policy(max_tier=PURE, allow_field_restricted={NON_COMMERCIAL})`` must
        NOT admit a subprocess + GPL-3 + conveys + non-commercial provider. The
        first version of this design did, because ``check`` returned as soon as
        the opt-in was honoured.
        """
        opted_in = Policy(
            max_tier=Tier.PURE,
            allow_field_restricted={FieldOfUse.NON_COMMERCIAL},
        )
        assessment = classify(NON_COMMERCIAL_SHIPPED_GPL)

        assert assessment.verdict is Verdict.FIELD_RESTRICTED
        # The rung survives the field verdict. Without it there is nothing for
        # the ceiling test to compare, which is how the leak happened.
        assert assessment.tier is Tier.COPYLEFT_SHIPPED

        with pytest.raises(LicenceCeilingExceeded):
            check(assessment, opted_in, "effect 'stylize'")

    def test_mutation_an_early_return_after_the_opt_in_admits_it(self):
        """The same guard, with the bug put back."""

        def buggy_check(assessment: Assessment, policy: Policy) -> None:
            """`check` as it was written first: `return` inside the branch."""
            if assessment.verdict is Verdict.FIELD_RESTRICTED:
                if assessment.terms.field_of_use in policy.allow_field_restricted:
                    return  # <-- the defect
                raise LicenceFieldRestricted("field restricted")
            if not policy.admits(assessment.tier):
                raise LicenceCeilingExceeded("over ceiling")

        opted_in = Policy(
            max_tier=Tier.PURE,
            allow_field_restricted={FieldOfUse.NON_COMMERCIAL},
        )
        buggy_check(classify(NON_COMMERCIAL_SHIPPED_GPL), opted_in)  # admits!

        with pytest.raises(LicenceCeilingExceeded):
            check(classify(NON_COMMERCIAL_SHIPPED_GPL), opted_in, "x")

    def test_the_opt_in_still_refuses_when_there_is_no_rung_to_compare(self):
        """The fall-through's other end.

        A field-restricted row whose reach is unreadable — CC BY-NC-SA, say —
        has no rung. Honouring the opt-in must then land on a refusal, not on
        an admission by absence.
        """
        no_rung = _terms(
            provider="whitebox",
            realisation="github:x/y",
            component="weights",
            spdx="CC-BY-NC-SA-4.0",
            coupling=Coupling.IN_PROCESS,
            conveyance=Conveyance.FINDS,
            field_of_use=FieldOfUse.NON_COMMERCIAL,
        )
        assert classify(no_rung).tier is None
        opted_in = Policy(allow_field_restricted={FieldOfUse.NON_COMMERCIAL})
        with pytest.raises(LicenceUnknown):
            check(classify(no_rung), opted_in, "effect 'cartoon'")


class TestTheAxesAreFactsAndTheLadderIsPolicy:
    """One half is observation, the other is a choice. Keep them apart."""

    def test_the_projection_ignores_field_of_use(self):
        """Three axes go in. The fourth is not commensurable with them."""
        unrestricted = _terms(
            spdx="GPL-2.0-or-later", conveyance=Conveyance.CONVEYS
        )
        restricted = _terms(
            spdx="GPL-2.0-or-later",
            conveyance=Conveyance.CONVEYS,
            field_of_use=FieldOfUse.NON_COMMERCIAL,
        )
        assert project_onto_ladder(unrestricted) is project_onto_ladder(restricted)

    def test_the_ladder_is_replaceable(self):
        """`Policy.order` is the escape hatch for a different corporate posture.

        Rungs 2 and 3 are not ordered by obligation-inclusion, so a caller who
        is comfortable with LGPL linking and nervous about GPL anything must be
        able to say so.
        """
        subprocess_gpl = classify(_terms(spdx="GPL-2.0-or-later"))
        assert subprocess_gpl.tier is Tier.COPYLEFT_TOOL
        assert DFLT_POLICY.admits(Tier.COPYLEFT_TOOL)

        swapped = Policy(
            max_tier=Tier.WEAK_COPYLEFT,
            order=(
                Tier.PURE,
                Tier.PERMISSIVE,
                Tier.COPYLEFT_TOOL,
                Tier.WEAK_COPYLEFT,
                Tier.COPYLEFT_SHIPPED,
            ),
        )
        assert swapped.admits(Tier.COPYLEFT_TOOL)
        check(subprocess_gpl, swapped, "effect 'gamma'")

    def test_a_ladder_missing_a_rung_is_refused_at_construction(self):
        """Something would land where it cannot be ranked."""
        with pytest.raises(ValueError, match="permutation"):
            Policy(order=(Tier.PURE, Tier.PERMISSIVE))

    def test_tier_has_no_ordering_of_its_own(self):
        """`<` must not silently mean the shipped ladder."""
        with pytest.raises(TypeError):
            Tier.PURE < Tier.PERMISSIVE  # noqa: B015

    def test_reach_of_excludes_bsd_4_clause_deliberately(self):
        """Its text is BSD-3-Clause plus one real obligation."""
        assert reach_of("BSD-3-Clause") is Reach.NONE
        assert reach_of("BSD-4-Clause") is Reach.UNKNOWN

    def test_reach_of_does_not_parse_compound_expressions(self):
        """The conjunction that occurs is two components, not one licence."""
        assert reach_of("Apache-2.0 AND GPL-3.0-or-later") is Reach.UNKNOWN
        assert reach_of("MIT OR GPL-2.0-only") is Reach.UNKNOWN

    def test_every_rung_is_reachable_from_some_axis_combination(self):
        """A rung nothing can produce is a rung a policy cannot express."""
        produced = set()
        for coupling in (Coupling.NONE, Coupling.IN_PROCESS, Coupling.SUBPROCESS):
            for spdx in ("MIT", "LGPL-2.1-only", "GPL-2.0-only"):
                for conveyance in (Conveyance.NONE, Conveyance.FINDS, Conveyance.CONVEYS):
                    tier = project_onto_ladder(
                        _terms(coupling=coupling, spdx=spdx, conveyance=conveyance)
                    )
                    if tier is not None:
                        produced.add(tier)
        assert produced == set(DFLT_LADDER)

    def test_the_ladder_table_matches_the_decided_one(self):
        """Section 5.3, row by row. The projection is the decision."""
        cases = {
            Tier.PURE: dict(coupling=Coupling.NONE, spdx="MIT",
                            conveyance=Conveyance.NONE),
            Tier.PERMISSIVE: dict(coupling=Coupling.IN_PROCESS, spdx="Apache-2.0",
                                  conveyance=Conveyance.CONVEYS),
            Tier.WEAK_COPYLEFT: dict(coupling=Coupling.IN_PROCESS,
                                     spdx="LGPL-2.1-or-later",
                                     conveyance=Conveyance.CONVEYS),
            Tier.COPYLEFT_TOOL: dict(coupling=Coupling.SUBPROCESS,
                                     spdx="GPL-3.0-or-later",
                                     conveyance=Conveyance.FINDS),
            Tier.COPYLEFT_SHIPPED: dict(coupling=Coupling.SUBPROCESS,
                                        spdx="GPL-2.0-or-later",
                                        conveyance=Conveyance.CONVEYS),
        }
        for expected, axes in cases.items():
            assert project_onto_ladder(_terms(**axes)) is expected

    def test_an_honest_lgpl_ffmpeg_is_rung_two(self):
        """Rung 2's own stated example, and looks reaches it by subprocess."""
        assert (
            project_onto_ladder(
                _terms(coupling=Coupling.SUBPROCESS, spdx="LGPL-2.1-or-later")
            )
            is Tier.WEAK_COPYLEFT
        )


class TestUnknownIsARefusal:
    """Not a warning, not a default, not "probably permissive"."""

    @pytest.mark.parametrize(
        "axes",
        [
            dict(coupling=Coupling.UNKNOWN),
            dict(spdx="LicenseRef-nobody-wrote-one"),
            dict(conveyance=Conveyance.UNKNOWN),
            dict(field_of_use=FieldOfUse.UNKNOWN),
        ],
    )
    def test_any_unknown_axis_refuses(self, axes):
        assessment = classify(_terms(**axes))
        assert assessment.verdict is Verdict.UNKNOWN
        assert assessment.tier is None
        with pytest.raises(LicenceUnknown):
            check(assessment, MOST_PERMISSIVE, "effect 'x'")

    def test_an_unverified_row_refuses(self):
        """"Do not cite as fact" has to be executable to hold."""
        assessment = classify(_terms(verified=False))
        assert assessment.verdict is Verdict.UNKNOWN
        assert "UNVERIFIED" in " ".join(assessment.reasons)

    def test_a_self_contradictory_artifact_refuses_without_adjudicating(self):
        """looks reports the disagreement; it does not pick a side."""
        assessment = classify(
            _terms(spdx="BSD-3-Clause", contradiction="otool -L shows libx264")
        )
        assert assessment.verdict is Verdict.UNKNOWN
        assert assessment.tier is None
        with pytest.raises(LicenceUnknown) as excinfo:
            check(assessment, MOST_PERMISSIVE, "effect 'decode'")
        assert "libx264" in str(excinfo.value)

    def test_opting_into_unknown_is_refused_at_construction(self):
        """The one escape hatch that would launder unknown into permission."""
        with pytest.raises(ValueError, match="unknown"):
            Policy(allow_field_restricted={FieldOfUse.UNKNOWN})
        with pytest.raises(ValueError, match="unrestricted"):
            Policy(allow_field_restricted={FieldOfUse.UNRESTRICTED})

    def test_a_recorded_prohibition_is_never_lifted(self):
        """Territorial exclusion, or FFmpeg's "nonfree and unredistributable"."""
        assessment = classify(_terms(prohibition="excluded by territory"))
        assert assessment.verdict is Verdict.FORBIDDEN
        with pytest.raises(LicenceForbidden):
            check(assessment, MOST_PERMISSIVE, "effect 'x'")

    def test_on_ladder_is_not_permission(self):
        """`classify` locates; it never admits."""
        assessment = classify(_terms(spdx="GPL-2.0-or-later"))
        assert assessment.verdict is Verdict.ON_LADDER
        with pytest.raises(LicenceCeilingExceeded):
            check(assessment, Policy(max_tier=Tier.PURE), "effect 'x'")


class TestCompositeProviders:
    """A provider made of several components takes the worst component."""

    def test_the_worst_component_wins_and_the_parts_survive(self):
        code = _terms(
            provider="moviepy",
            realisation="pypi:moviepy",
            spdx="MIT",
            coupling=Coupling.IN_PROCESS,
            conveyance=Conveyance.CONVEYS,
        )
        shipped = _terms(
            provider="moviepy",
            realisation="pypi:moviepy",
            component="transitive",
            spdx="GPL-2.0-or-later",
            conveyance=Conveyance.CONVEYS,
        )
        composite = assess([code, shipped])
        assert composite.tier is Tier.COPYLEFT_SHIPPED
        assert len(composite.parts) == 2
        assert {p.tier for p in composite.parts} == {
            Tier.PERMISSIVE,
            Tier.COPYLEFT_SHIPPED,
        }

    def test_it_is_not_a_per_axis_join(self):
        """The chimera the reviewer found by running the proposed module.

        Joining OpenCV's Apache-2.0 in-process code with the GPL ffmpeg its
        wheel conveys yields "we link a GPL program in-process" — FORBIDDEN,
        and true of neither component.
        """
        code = _terms(
            provider="opencv",
            spdx="Apache-2.0",
            coupling=Coupling.IN_PROCESS,
            conveyance=Conveyance.CONVEYS,
        )
        binary = _terms(
            provider="opencv",
            component="bundled-ffmpeg",
            spdx="GPL-3.0-or-later",
            coupling=Coupling.SUBPROCESS,
            conveyance=Conveyance.CONVEYS,
        )
        joined = classify(
            _terms(
                spdx="GPL-3.0-or-later",
                coupling=Coupling.IN_PROCESS,
                conveyance=Conveyance.CONVEYS,
            )
        )
        assert joined.verdict is Verdict.FORBIDDEN  # the chimera

        composite = assess([code, binary])
        assert composite.verdict is Verdict.ON_LADDER
        assert composite.tier is Tier.COPYLEFT_SHIPPED

    def test_check_applies_the_ceiling_to_every_part(self):
        """A composite may not admit what one of its components would not.

        The decisive part here is the field-restricted one, which an opt-in
        clears; the other part is over the ceiling and must still refuse.
        """
        over_ceiling = _terms(
            provider="pair", component="binary", spdx="GPL-2.0-or-later",
            conveyance=Conveyance.CONVEYS,
        )
        restricted = _terms(
            provider="pair", component="weights", spdx="MIT",
            coupling=Coupling.IN_PROCESS,
            conveyance=Conveyance.FINDS,
            field_of_use=FieldOfUse.NON_COMMERCIAL,
        )
        composite = assess([over_ceiling, restricted])
        assert composite.verdict is Verdict.FIELD_RESTRICTED
        policy = Policy(
            max_tier=Tier.PERMISSIVE,
            allow_field_restricted={FieldOfUse.NON_COMMERCIAL},
        )
        with pytest.raises(LicenceCeilingExceeded):
            check(composite, policy, "effect 'x'")

    def test_an_empty_component_list_is_not_a_clean_bill_of_health(self):
        with pytest.raises(ValueError, match="at least one"):
            assess([])


class TestRefusalMessages:
    """A refusal that does not say what it protects against is unactionable."""

    def test_a_ceiling_refusal_names_everything_a_caller_needs(self):
        assessment = classify(
            _terms(
                provider="ffmpeg",
                component="binary",
                spdx="GPL-3.0-or-later",
                evidence=(
                    Evidence(
                        method="probe",
                        command="ffmpeg -L",
                        observed="GNU General Public License version 3",
                        observed_on="2026-09-02",
                        source_url="https://ffmpeg.org/legal.html",
                    ),
                ),
            )
        )
        with pytest.raises(LicenceCeilingExceeded) as excinfo:
            check(
                assessment,
                Policy(max_tier=Tier.WEAK_COPYLEFT),
                "effect 'gamma'",
                alternatives=["gamma.ffmpeg.lutyuv"],
            )
        message = str(excinfo.value)
        assert "effect 'gamma'" in message  # the subject
        assert "COPYLEFT_TOOL" in message  # the tier it needs
        assert "WEAK_COPYLEFT" in message  # the ceiling in force
        assert "ffmpeg" in message  # the resolved provider
        assert "2026-09-02" in message  # the dated observation
        assert "ffmpeg.org/legal.html" in message  # and its source
        assert "gamma.ffmpeg.lutyuv" in message  # the lower-tier alternative
        assert "Policy(max_tier=Tier.COPYLEFT_TOOL)" in message  # how to opt in
        assert SEE_DISCLAIMER in message

    def test_a_ceiling_refusal_says_max_tier_is_not_the_commercial_knob(self):
        with pytest.raises(LicenceCeilingExceeded) as excinfo:
            check(
                classify(_terms(spdx="GPL-2.0-or-later")),
                Policy(max_tier=Tier.PERMISSIVE),
                "effect 'x'",
            )
        assert "allow_field_restricted=frozenset()" in str(excinfo.value)

    def test_a_field_refusal_names_the_separate_opt_in_and_not_the_ceiling(self):
        with pytest.raises(LicenceFieldRestricted) as excinfo:
            check(classify(RESEARCH_ONLY), DFLT_POLICY, "effect 'stylize'")
        message = str(excinfo.value)
        assert "Policy(allow_field_restricted={FieldOfUse.RESEARCH_ONLY})" in message
        assert "max_tier cannot grant this" in message

    def test_a_forbidden_refusal_says_there_is_no_opt_in(self):
        with pytest.raises(LicenceForbidden) as excinfo:
            check(classify(IN_PROCESS_STRONG), DFLT_POLICY, "effect 'detect'")
        assert "no opt-in" in str(excinfo.value)

    def test_every_refusal_points_at_the_disclaimer(self):
        rows = [
            IN_PROCESS_STRONG,
            RESEARCH_ONLY,
            _terms(coupling=Coupling.UNKNOWN),
            _terms(spdx="GPL-2.0-or-later"),
        ]
        for row in rows:
            with pytest.raises(LooksLicenceError) as excinfo:
                check(classify(row), Policy(max_tier=Tier.PURE), "effect 'x'")
            assert SEE_DISCLAIMER in str(excinfo.value)

    def test_the_disclaimer_reaches_every_belief_forming_surface(self):
        """The module docstring, the data file, and every refusal."""
        import looks.licence as module

        assert "reports observations, not legal conclusions" in module.__doc__
        assert "is a question for you and your counsel" in module.__doc__
        assert "not legal conclusions" in DISCLAIMER
        doc = json.loads(LEDGER_PATH.read_text())
        assert "not legal conclusions" in doc["disclaimer"]


class TestAdvisories:
    """What a caller must be told without being refused."""

    def test_a_live_patent_is_reported_and_does_not_refuse(self):
        """Public domain is the most permissive answer, and it is wrong here."""
        ebsynth = _terms(
            provider="ebsynth",
            realisation="github:jamriska/ebsynth",
            spdx="LicenseRef-ebsynth-public-domain",
            reach=Reach.NONE,
            coupling=Coupling.IN_PROCESS,
            note="public domain, no SPDX id asserted",
            patents=(
                Patent(
                    patent_id="US8861869B2",
                    jurisdiction="US",
                    holder="Adobe",
                    status="active",
                    expiry="2030-08-16",
                ),
            ),
        )
        assessment = classify(ebsynth)
        assert assessment.tier is Tier.PERMISSIVE
        check(assessment, DFLT_POLICY, "effect 'stylize'")
        assert any("US8861869B2" in a for a in assessment.advisories)

    def test_an_expired_patent_is_not_reported(self):
        assessment = classify(
            _terms(
                patents=(
                    Patent(
                        patent_id="US1",
                        jurisdiction="US",
                        status="expired",
                        expiry="1999-01-01",
                    ),
                )
            )
        )
        assert not any("US1" in a for a in assessment.advisories)

    def test_conditions_are_carried_as_data(self):
        assessment = classify(
            _terms(
                field_of_use=FieldOfUse.NON_COMMERCIAL,
                conditions=("terminates above USD 10,000,000 of revenue",),
            )
        )
        assert any("10,000,000" in a for a in assessment.advisories)

    def test_an_explicit_reach_override_needs_a_reason_and_is_announced(self):
        with pytest.raises(ValueError, match="records no note"):
            Terms(
                provider="p",
                realisation="system",
                spdx="Apache-2.0 AND GPL-3.0-or-later",
                coupling=Coupling.IN_PROCESS,
                reach=Reach.NONE,
            )
        announced = classify(
            _terms(spdx="LicenseRef-x", reach=Reach.NONE, note="why")
        )
        assert any("recorded explicitly" in a for a in announced.advisories)

    def test_stale_evidence_is_reported_never_auto_refused(self):
        assessment = classify(
            _terms(
                evidence=(
                    Evidence(
                        method="read", observed="x", observed_on="2001-01-01"
                    ),
                )
            )
        )
        assert assessment.verdict is Verdict.ON_LADDER
        assert any("older than" in a for a in assessment.advisories)


class TestTheEnvironmentJoin:
    """looks.environment owns the two authorities. This half consumes them."""

    def test_the_tier_follows_the_binary_and_not_the_effect(self):
        """The single most important consequence: a tier cannot be a constant."""
        gpl = FfmpegEnv(path="/gpl/ffmpeg", licence=Licence.GPL3,
                        filters=frozenset({"lut3d"}))
        lgpl = FfmpegEnv(path="/lgpl/ffmpeg", licence=Licence.LGPL21,
                         filters=frozenset({"lut3d"}))
        assert classify(ffmpeg_terms(gpl)).tier is Tier.COPYLEFT_TOOL
        assert classify(ffmpeg_terms(lgpl)).tier is Tier.WEAK_COPYLEFT

    def test_a_bundled_binary_conveys_where_a_found_one_finds(self):
        env = FfmpegEnv(path="/wheel/ffmpeg", licence=Licence.GPL2,
                        filters=frozenset({"lut3d"}))
        assert classify(ffmpeg_terms(env)).tier is Tier.COPYLEFT_TOOL
        shipped = ffmpeg_terms(env, realisation="pypi:imageio-ffmpeg")
        assert shipped.conveyance is Conveyance.CONVEYS
        assert classify(shipped).tier is Tier.COPYLEFT_SHIPPED

    def test_a_nonfree_build_is_refused_before_any_ceiling(self):
        """FFmpeg's own words, and no evidence lifts them."""
        env = FfmpegEnv(path="/nonfree/ffmpeg", licence=Licence.NONFREE,
                        filters=frozenset({"lut3d"}))
        assessment = classify(ffmpeg_terms(env))
        assert assessment.verdict is Verdict.FORBIDDEN
        with pytest.raises(LicenceForbidden) as excinfo:
            check(assessment, MOST_PERMISSIVE, "effect 'x'")
        assert "unredistributable" in str(excinfo.value)

    def test_a_nonfree_build_is_not_folded_into_unknown(self):
        """Their remedies are opposites: one says supply evidence."""
        env = FfmpegEnv(path="/nonfree/ffmpeg", licence=Licence.NONFREE,
                        filters=frozenset({"lut3d"}))
        with pytest.raises(LicenceForbidden):
            check(classify(ffmpeg_terms(env)), DFLT_POLICY, "effect 'x'")

    def test_an_unclassifiable_build_is_unknown_not_lgpl(self):
        """No evidence of GPL is not evidence of LGPL."""
        env = FfmpegEnv(path="/mystery/ffmpeg", licence=Licence.UNKNOWN,
                        filters=frozenset({"lut3d"}))
        assert classify(ffmpeg_terms(env)).verdict is Verdict.UNKNOWN

    def test_an_unprobed_environment_is_unknown(self):
        assert classify(ffmpeg_terms(FfmpegEnv())).verdict is Verdict.UNKNOWN

    def test_a_gated_filter_is_the_reason_not_a_higher_tier(self):
        """The binary is already GPL; the filters say why it has to be."""
        env = FfmpegEnv(path="/gpl/ffmpeg", licence=Licence.GPL3,
                        filters=frozenset({"lut3d", "lutrgb", "eq"}))
        clean = assess_ffmpeg_chain(["lut3d", "lutrgb"], env=env)
        gated = assess_ffmpeg_chain(["lut3d", "eq"], env=env)
        assert clean.tier is gated.tier is Tier.COPYLEFT_TOOL
        assert not any("--enable-gpl" in r for r in clean.reasons)
        assert any("'eq'" in r for r in gated.reasons)

    def test_a_gpl_gated_filter_on_an_lgpl_build_is_a_contradiction(self):
        """The two authorities disagree, so looks refuses rather than choosing."""
        env = FfmpegEnv(path="/lgpl/ffmpeg", licence=Licence.LGPL21,
                        filters=frozenset({"lut3d", "eq"}))
        assessment = assess_ffmpeg_chain(["eq"], env=env)
        assert assessment.verdict is Verdict.UNKNOWN
        with pytest.raises(LicenceUnknown) as excinfo:
            check(assessment, MOST_PERMISSIVE, "effect 'grade'")
        assert "--enable-gpl" in str(excinfo.value)

    def test_a_missing_filter_is_reported_as_an_availability_fact(self):
        """Availability is the stronger check, and it is the compiler's."""
        env = FfmpegEnv(path="/lgpl/ffmpeg", licence=Licence.LGPL21,
                        filters=frozenset({"lut3d"}))
        assessment = assess_ffmpeg_chain(["lut3d", "eq"], env=env)
        assert any("not in the declared environment" in a
                   for a in assessment.advisories)
        assert any("/lgpl/ffmpeg" in a for a in assessment.advisories)

    def test_an_unrecognised_filter_name_raises_rather_than_reporting_clean(self):
        """The fail-open that would sit exactly at the licence tier's door."""
        env = FfmpegEnv(path="/gpl/ffmpeg", licence=Licence.GPL3,
                        filters=frozenset({"lut3d"}))
        with pytest.raises(UnknownFilter):
            assess_ffmpeg_chain(["nosuchfilter"], env=env)
        with pytest.raises(UnknownFilter):
            assess_ffmpeg_chain(["EQ"], env=env)

    def test_geq_does_not_need_a_gpl_build(self):
        """Relicensed in FFmpeg 4.3. The belief outlives the fact."""
        env = FfmpegEnv(path="/gpl/ffmpeg", licence=Licence.GPL3,
                        filters=frozenset({"geq"}))
        assert not any(
            "--enable-gpl" in r for r in assess_ffmpeg_chain(["geq"], env=env).reasons
        )

    def test_against_the_real_binary(self):
        """A synthetic FfmpegEnv cannot tell you the join works."""
        if shutil.which("ffmpeg") is None:
            pytest.skip("no ffmpeg on PATH")
        env = probe()
        if not env.available:
            pytest.skip(f"ffmpeg probe failed: {env.notes}")
        assessment = classify(ffmpeg_terms(env))
        assert assessment.verdict in (Verdict.ON_LADDER, Verdict.FORBIDDEN)
        if assessment.verdict is Verdict.ON_LADDER:
            # The Que Calor chain, which is LGPL-clean by measurement.
            chain = assess_ffmpeg_chain(["lut3d", "lutrgb"], env=env)
            assert chain.tier is not None
            assert not any("--enable-gpl" in r for r in chain.reasons)


class TestTheLedger:
    """A record of observations. Every tier in it is derived, never stored."""

    def test_no_row_stores_a_tier_or_a_verdict(self):
        """The label is what the ledger deliberately does not have."""
        doc = json.loads(LEDGER_PATH.read_text())
        for row in doc["rows"]:
            assert "tier" not in row
            assert "verdict" not in row

    def test_every_row_derives_the_position_it_was_transcribed_with(self):
        """Section 5.7's table, re-derived rather than asserted.

        Three rows deviate from that table's Tier column, deliberately and with
        the reason recorded on the row: the opencv wheels that bundle a GPL
        ffmpeg are UNKNOWN because whether cv2's linkage counts as ours is the
        open question looks may not adjudicate, and the two vendored-LGPL
        shader rows follow section 5.3's ladder (which lifts a rung for
        conveyance only inside the strong-copyleft subprocess region) rather
        than 5.7's contrary annotation.
        """
        expected = {
            ("looks", "self", "code"): Tier.PURE,
            ("ffmpeg", "system", "binary"): Tier.COPYLEFT_TOOL,
            ("av", "pypi:av", "binary"): Verdict.UNKNOWN,
            ("imageio-ffmpeg", "pypi:imageio-ffmpeg", "binary"): (
                Tier.COPYLEFT_SHIPPED
            ),
            ("moviepy", "pypi:moviepy", "code"): Tier.PERMISSIVE,
            ("moviepy", "pypi:moviepy", "transitive"): Tier.COPYLEFT_SHIPPED,
            ("burns", "pypi:burns", "transitive"): Tier.COPYLEFT_SHIPPED,
            ("opencv", "any", "code"): Tier.PERMISSIVE,
            ("opencv", "pypi:opencv-python@macosx_arm64", "bundled-ffmpeg"): (
                Verdict.UNKNOWN
            ),
            (
                "opencv",
                "pypi:opencv-python-headless@macosx_arm64",
                "bundled-ffmpeg",
            ): Verdict.UNKNOWN,
            (
                "opencv",
                "pypi:opencv-contrib-python@macosx_arm64",
                "bundled-ffmpeg",
            ): Verdict.UNKNOWN,
            (
                "opencv",
                "pypi:opencv-python-headless@macosx_14_0_x86_64",
                "bundled-ffmpeg",
            ): Tier.PERMISSIVE,
            (
                "opencv",
                "pypi:opencv-python-headless@manylinux",
                "bundled-ffmpeg",
            ): Tier.WEAK_COPYLEFT,
            ("ultralytics", "pypi:ultralytics", "code"): Verdict.FORBIDDEN,
            ("argh", "pypi:argh", "code"): Tier.WEAK_COPYLEFT,
            ("colour-science", "pypi:colour-science", "code"): Tier.PERMISSIVE,
            ("moderngl", "pypi:moderngl", "code"): Tier.PERMISSIVE,
            ("glcontext", "pypi:glcontext", "code"): Tier.PERMISSIVE,
            (
                "animeganv2",
                "github:TachibanaYoshino/AnimeGANv2",
                "weights",
            ): Verdict.UNKNOWN,
            (
                "animegan2-pytorch",
                "github:bryandlee/animegan2-pytorch",
                "code",
            ): Tier.PERMISSIVE,
            (
                "whitebox-cartoonization",
                "github:SystemErrorWang/White-box-Cartoonization",
                "weights",
            ): Verdict.FIELD_RESTRICTED,
            (
                "fast-neural-style",
                "github:jcjohnson/fast-neural-style",
                "model",
            ): Verdict.FIELD_RESTRICTED,
            (
                "onnx-model-zoo",
                "github:onnx/models/fast_neural_style",
                "model",
            ): Tier.PERMISSIVE,
            ("ebsynth", "github:jamriska/ebsynth", "code"): Tier.PERMISSIVE,
            ("anime4k", "github:bloc97/Anime4K", "assets"): Tier.PERMISSIVE,
            ("ravu", "github:bjin/mpv-prescalers", "assets"): Tier.WEAK_COPYLEFT,
            ("fsrcnnx", "github:igv/FSRCNN-TensorFlow", "assets"): (
                Tier.WEAK_COPYLEFT
            ),
            ("minimax", "hosted:MiniMax-H3", "weights"): Verdict.FORBIDDEN,
            (
                "stability",
                "weights:stabilityai/stable-diffusion-3.5",
                "weights",
            ): Verdict.FIELD_RESTRICTED,
            (
                "stability",
                "weights:stabilityai/sdxl-turbo",
                "weights",
            ): Verdict.FIELD_RESTRICTED,
            (
                "ltx-video",
                "weights:Lightricks/LTX-Video",
                "weights",
            ): Verdict.FIELD_RESTRICTED,
            ("bytedance", "weights:ByteDance/Bernini-R", "weights"): (
                Tier.PERMISSIVE
            ),
            ("adobe-lut-packs", "commercial:various", "assets"): Verdict.UNKNOWN,
        }
        rows = {t.key: t for t in ledger()}
        assert set(rows) == set(expected), "the ledger and its pin disagree"
        for key, want in expected.items():
            got = classify(rows[key])
            if isinstance(want, Tier):
                assert got.verdict is Verdict.ON_LADDER, key
                assert got.tier is want, key
            else:
                assert got.verdict is want, key

    def test_the_deviating_rows_say_so(self):
        """A conflict with the decisions document is flagged, never silent."""
        for key in (
            ("opencv", "pypi:opencv-python@macosx_arm64", "bundled-ffmpeg"),
            ("ravu", "github:bjin/mpv-prescalers", "assets"),
        ):
            row = next(t for t in ledger() if t.key == key)
            assert "5.7" in row.note or "section 5.7" in row.note.lower()

    def test_every_off_ladder_row_is_unreachable_by_any_ceiling(self):
        for row in ledger():
            assessment = classify(row)
            if assessment.verdict is Verdict.ON_LADDER:
                continue
            with pytest.raises(LooksLicenceError):
                check(assessment, MOST_PERMISSIVE, f"row {row.key}")

    def test_every_row_carries_dated_evidence(self):
        from datetime import date

        for row in ledger():
            assert row.evidence, row.key
            for ev in row.evidence:
                assert ev.observed.strip(), row.key
                date.fromisoformat(ev.observed_on)

    def test_the_code_and_weights_split_is_expressible(self):
        """A metadata scan reads the port's LICENSE and gets it backwards."""
        code = terms_for("animegan2-pytorch")[0]
        weights = terms_for("animeganv2")[0]
        assert classify(code).tier is Tier.PERMISSIVE
        assert classify(weights).verdict is Verdict.UNKNOWN

    def test_missing_weights_terms_are_unknown_not_non_commercial(self):
        """No licence file is a stronger refusal, with a different remedy."""
        weights = terms_for("animeganv2")[0]
        assert weights.field_of_use is FieldOfUse.UNKNOWN
        with pytest.raises(LicenceUnknown):
            check(classify(weights), MOST_PERMISSIVE, "effect 'anime'")

    def test_one_distribution_name_covers_three_platform_answers(self):
        """The tier is a property of the wheel, not of the project name."""
        headless = terms_for("opencv", component="bundled-ffmpeg")
        by_platform = {
            t.realisation.split("@")[-1]: classify(t)
            for t in headless
            if "headless" in t.realisation
        }
        assert by_platform["macosx_arm64"].verdict is Verdict.UNKNOWN
        assert by_platform["macosx_14_0_x86_64"].tier is Tier.PERMISSIVE
        assert by_platform["manylinux"].tier is Tier.WEAK_COPYLEFT

    def test_a_bad_schema_tag_is_refused_loudly(self):
        import looks.licence as module

        module._raw_ledger.cache_clear()
        module.ledger.cache_clear()
        original = module.LEDGER_PATH
        try:
            bogus = original.with_name("provider_terms_bogus.json")
            doc = json.loads(original.read_text())
            doc["schema"] = "looks.provider_terms/v99"
            bogus.write_text(json.dumps(doc))
            module.LEDGER_PATH = bogus
            with pytest.raises(ValueError, match="schema"):
                module.ledger()
        finally:
            module.LEDGER_PATH = original
            bogus.unlink(missing_ok=True)
            module._raw_ledger.cache_clear()
            module.ledger.cache_clear()
        assert ledger()  # and the real one still loads
        assert LEDGER_SCHEMA == json.loads(original.read_text())["schema"]

    def test_unverified_claims_are_recorded_rather_than_omitted(self):
        claims = unverified_claims()
        assert len(claims) >= 4
        assert any("opencv" in c.lower() for c in claims)

    def test_every_runtime_extra_has_a_ledger_row(self):
        """The guard that turns the extras table into a tested artifact.

        Development extras are excluded, and the rule has to be stated or the
        ledger fills with build-tool rows: ``dev`` and ``docs`` are never in
        the install closure of ``pip install looks``, so nothing about them is
        conveyed to a user. Every *runtime* extra is, and each one is a
        conveyance decision.
        """
        try:
            import tomllib
        except ImportError:  # Python 3.10
            pytest.skip("tomllib needs Python 3.11+")
        root = LEDGER_PATH.parent.parent.parent / "pyproject.toml"
        config = tomllib.loads(root.read_text())
        extras = config["project"].get("optional-dependencies", {})
        runtime = {
            name: specs
            for name, specs in extras.items()
            if name not in ("dev", "docs", "test")
        }
        providers = {t.provider for t in ledger()}
        for name, specs in runtime.items():
            for spec in specs:
                dist = spec.split("[")[0].split(">")[0].split("=")[0].strip()
                assert dist in providers, (
                    f"extra {name!r} conveys {dist!r}, which has no ledger row. "
                    "An extra is a conveyance decision, not a convenience list."
                )
        assert config["project"]["dependencies"] == []


class TestLedgerRowValidation:
    """A malformed row is not a permission."""

    def _row(self, **overrides):
        row = {
            "provider": "p",
            "realisation": "pypi:p",
            "component": "code",
            "spdx": "MIT",
            "coupling": "in_process",
            "conveyance": "conveys",
            "field_of_use": "unrestricted",
            "verified": True,
            "evidence": [
                {"method": "read", "observed": "x", "observed_on": "2026-09-02"}
            ],
        }
        row.update(overrides)
        return row

    def test_a_typod_key_is_refused_rather_than_dropped(self):
        from looks.licence import _terms_from_row

        with pytest.raises(ValueError, match="unexpected key"):
            _terms_from_row(self._row(feild_of_use="non_commercial"))

    def test_an_unknown_component_is_refused(self):
        from looks.licence import _terms_from_row

        with pytest.raises(ValueError, match="vocabulary"):
            _terms_from_row(self._row(component="stuff"))

    def test_a_system_realisation_cannot_convey(self):
        from looks.licence import _terms_from_row

        with pytest.raises(ValueError, match="conveyance"):
            _terms_from_row(self._row(realisation="system", conveyance="conveys"))

    def test_a_verified_row_needs_evidence(self):
        from looks.licence import _terms_from_row

        with pytest.raises(ValueError, match="no evidence"):
            _terms_from_row(self._row(evidence=[]))

    def test_a_bad_enum_value_names_the_alternatives(self):
        from looks.licence import _terms_from_row

        with pytest.raises(ValueError, match="Conveyance"):
            _terms_from_row(self._row(conveyance="ships_it"))
