"""The cross-clip solver, proved against brute force rather than argued for.

An exact algorithm is a claim, and the only way to hold it is to compute the
answer a second way. So :class:`TestItIsExact` enumerates the whole product for
sizes where that is possible and compares objective values — including ties,
duplicates and values repeated across clips, which is where a two-pointer sweep
goes wrong if it is going to.

The sizes it cannot enumerate are the point: |G|^|S| is 8**30 at the documented
size, about 1.24e27 combinations, against 0.093 ms for the sweep.
"""

import itertools
import math
import random

import pytest

from looks.across import (
    AcrossError,
    Candidate,
    Choice,
    Spread,
    probes_for,
    solve_across,
)
from looks.measure import ClipStats

SEED = 20260903


def stats(source_id, sharpness, **overrides):
    base = dict(
        stage="post_effect",
        instrument="ffmpeg-8.1/siti",
        luma_space="coded_y",
        sample_spec="uniform:5",
        n_frames=5,
    )
    base.update(overrides)
    return ClipStats(source_id=source_id, sharpness=sharpness, **base)


def grid(values_by_clip):
    """`{clip: [measured sharpness, ...]}` -> the solver's input."""
    return {
        source_id: [Candidate(i, stats(source_id, v)) for i, v in enumerate(values)]
        for source_id, values in values_by_clip.items()
    }


def brute_ratio(values_by_clip):
    """The best achievable max/min, by enumerating every combination."""
    best = None
    for combo in itertools.product(*values_by_clip.values()):
        ratio = max(combo) / min(combo)
        if best is None or ratio < best:
            best = ratio
    return best


class TestItIsExact:
    """Against brute force, at sizes brute force can reach."""

    @pytest.mark.parametrize("trial", range(300))
    def test_it_matches_brute_force(self, trial):
        rng = random.Random(SEED + trial)
        n = rng.randint(2, 5)
        # A small pool of repeated values on purpose: ties across clips and
        # duplicates within one are where a sweep's pointer arithmetic fails.
        pool = [1.0, 2.0, 2.0, 3.0, 5.0, 5.0, 8.0, 13.0]
        values = {
            f"c{i:02d}": [rng.choice(pool) for _ in range(rng.randint(1, 4))]
            for i in range(n)
        }
        got = solve_across(grid(values))
        assert got.ratio == pytest.approx(brute_ratio(values), rel=1e-9), values

    def test_it_matches_brute_force_on_continuous_values(self):
        """Ties are one hazard; distinct floats are the other, because then the
        window's edges are unique and an off-by-one is visible."""
        rng = random.Random(SEED)
        for _ in range(200):
            n = rng.randint(2, 5)
            values = {
                f"c{i:02d}": [rng.uniform(1.0, 100.0) for _ in range(rng.randint(1, 4))]
                for i in range(n)
            }
            got = solve_across(grid(values))
            assert got.ratio == pytest.approx(brute_ratio(values), rel=1e-9)

    def test_a_single_clip_is_refused_not_answered(self):
        """`looks.measure.dispersion` already refuses this exact quantity, and
        two modules disagreeing about whether a one-element spread is a
        question is the drift this package's guards exist to catch.

        It is also the honest answer: with one clip every candidate scores
        1.0, so the value returned would come from the tie-break rule and from
        nothing about the set.
        """
        with pytest.raises(AcrossError, match="at least two clips"):
            solve_across(grid({"c01": [10.0, 20.0, 40.0]}))

    def test_and_measure_refuses_the_same_question(self):
        """The consistency this is about, asserted rather than described."""
        from looks.measure import MeasurementError, dispersion

        with pytest.raises(MeasurementError, match="at least two"):
            dispersion([stats("c01", 40.0)])

    def test_clips_whose_ranges_do_not_overlap(self):
        """No window can be narrow; the answer is still exact and still says
        which values it picked."""
        values = {"c01": [1.0, 2.0], "c02": [100.0, 200.0]}
        got = solve_across(grid(values))
        assert got.ratio == pytest.approx(brute_ratio(values), rel=1e-9)
        assert got.ratio == pytest.approx(50.0)

    def test_it_scales_past_where_brute_force_can_go(self):
        """The reason the closed form matters, stated as a number."""
        rng = random.Random(SEED)
        values = {
            f"c{i:02d}": [rng.uniform(1, 100) for _ in range(8)] for i in range(30)
        }
        got = solve_across(grid(values))
        assert len(got.choices) == 30
        assert 8**30 > 1e26, "the product this avoids"


class TestTheMeasuredRule:
    """The finding this mechanises: per-clip beats uniform beats sharpest."""

    #: Three sources whose sharpness responds differently to the same knob —
    #: the shape of the measured case, where one global scale made the softest
    #: source softer still and it became the softest thing on screen.
    RESPONSES = {
        "sharp": [117.0, 114.0, 95.0, 72.0],
        "middling": [72.0, 60.0, 46.0, 35.0],
        "soft": [46.0, 42.0, 40.0, 38.0],
    }

    def test_per_clip_beats_uniform(self):
        per_clip = solve_across(grid(self.RESPONSES)).ratio
        uniform = min(
            max(col) / min(col) for col in zip(*self.RESPONSES.values())
        )
        assert per_clip < uniform, (per_clip, uniform)

    def test_per_clip_beats_sharpest_everywhere(self):
        per_clip = solve_across(grid(self.RESPONSES)).ratio
        sharpest = [max(v) for v in self.RESPONSES.values()]
        assert per_clip < max(sharpest) / min(sharpest)

    def test_the_headline_number_is_the_ratio_a_reader_recognises(self):
        """`ratio` is quoted in the same units as the measured 2.004x, so a
        caller can compare directly rather than converting."""
        got = solve_across(grid(self.RESPONSES))
        assert got.ratio == pytest.approx(math.exp(got.log_spread), rel=1e-12)
        assert got.ratio >= 1.0


class TestLogsAndScale:
    def test_the_objective_is_scale_independent(self):
        """Minimising the spread of logs IS minimising max/min, so multiplying
        every measurement by a constant cannot move the answer."""
        rng = random.Random(SEED)
        values = {
            f"c{i:02d}": [rng.uniform(1, 50) for _ in range(4)] for i in range(5)
        }
        scaled = {k: [v * 1000 for v in vs] for k, vs in values.items()}
        one = solve_across(grid(values))
        other = solve_across(grid(scaled))
        assert one.ratio == pytest.approx(other.ratio, rel=1e-12)
        assert [c.value for c in one.choices] == [c.value for c in other.choices]

    def test_a_zero_measurement_is_refused_not_clamped(self):
        """A flat clip genuinely measures 0, and log(0) does not exist.
        Clamping it to an epsilon would invent a measurement."""
        with pytest.raises(AcrossError, match="does not exist"):
            solve_across(grid({"c01": [10.0], "c02": [0.0]}))

    def test_a_negative_measurement_too(self):
        with pytest.raises(AcrossError, match="non-positive"):
            solve_across(grid({"c01": [10.0], "c02": [-1.0]}))

    def test_a_missing_statistic_is_refused(self):
        candidates = {"c01": [Candidate(0, stats("c01", None))]}
        with pytest.raises(AcrossError, match="no 'sharpness' measurement"):
            solve_across(candidates)


class TestItIsDeterministic:
    """A solver that answered differently twice would move `plan_hash`."""

    def test_the_same_input_gives_the_same_answer(self):
        rng = random.Random(SEED)
        values = {
            f"c{i:02d}": [rng.choice([1.0, 2.0, 2.0, 5.0]) for _ in range(3)]
            for i in range(6)
        }
        first = solve_across(grid(values))
        for _ in range(20):
            again = solve_across(grid(values))
            assert [c.value for c in again.choices] == [
                c.value for c in first.choices
            ]
            assert again.ratio == first.ratio

    def test_ties_resolve_by_rule_not_by_iteration_order(self):
        """Every candidate inside the window gives the same objective, so the
        pick has to come from a rule or it comes from dict ordering."""
        values = {"c01": [10.0, 10.0, 10.0], "c02": [10.0, 10.0]}
        got = solve_across(grid(values))
        assert got.ratio == pytest.approx(1.0)
        assert [c.value for c in got.choices] == [0, 0]

    def test_the_pick_inside_a_WIDE_window_is_the_smallest(self):
        """The two weak-test lessons in one case.

        My first determinism tests asserted only that repeated runs agreed, so a
        SYSTEMATIC change escaped: mutating the in-window pick from `min` to
        `max` left all 334 tests green. Discriminating needs a window forced
        wide enough to hold more than one of a clip's candidates — here c02 and
        c03 pin the edges at 1.0 and 1.2, so all three of c01's fit inside and
        the rule becomes visible.
        """
        values = {"c01": [1.0, 1.1, 1.2], "c02": [1.0], "c03": [1.2]}
        got = solve_across(grid(values))
        picks = {c.source_id: c.value for c in got.choices}
        assert picks["c01"] == 0, "the smallest measurement inside the window"
        assert got.choices[0].statistic == pytest.approx(1.0)

    def test_the_EARLIEST_narrowest_window_wins_a_genuine_tie(self):
        """The other escape: mutating `width < best` to `<=` also left the suite
        green, because it only changes which of two equally narrow windows is
        kept.

        A genuine tie has to be constructed in RATIO, not in linear width — my
        first attempt used 10.0/10.5/11.0 and was not a tie at all, because
        11/10.5 is a narrower ratio than 10.5/10. Equal linear gaps are not
        equal ratios, which is the whole reason this objective lives in logs.
        Here 11/10 and 12.1/11 are both exactly 1.1x.
        """
        values = {"c01": [10.0, 12.1], "c02": [11.0]}
        got = solve_across(grid(values))
        assert got.ratio == pytest.approx(1.1, rel=1e-12)
        assert [c.value for c in got.choices] == [0, 0], (
            "the earliest of the equally narrow windows"
        )

    def test_equal_linear_widths_are_not_equal_ratios(self):
        """Recorded because it caught me out: the solver is right and the
        intuition is wrong."""
        values = {"c01": [10.0, 11.0], "c02": [10.5]}
        got = solve_across(grid(values))
        assert got.ratio == pytest.approx(11.0 / 10.5, rel=1e-12)
        assert got.ratio < 10.5 / 10.0


class TestComparabilityIsCheckedFirst:
    """A spread over measurements that are not comparable means nothing."""

    def test_a_different_stage_is_refused(self):
        candidates = {
            "c01": [Candidate(0, stats("c01", 40.0))],
            "c02": [Candidate(0, stats("c02", 42.0, stage="source"))],
        }
        with pytest.raises(AcrossError, match="cannot be compared"):
            solve_across(candidates)

    def test_a_different_luma_space_is_refused(self):
        """The 29x trap: two sharpness numbers in different spaces are not the
        same quantity, and their ratio is meaningless."""
        candidates = {
            "c01": [Candidate(0, stats("c01", 40.0))],
            "c02": [Candidate(0, stats("c02", 42.0, luma_space="bgr2gray"))],
        }
        with pytest.raises(AcrossError, match="cannot be compared"):
            solve_across(candidates)

    def test_a_different_instrument_is_refused(self):
        candidates = {
            "c01": [Candidate(0, stats("c01", 40.0))],
            "c02": [Candidate(0, stats("c02", 42.0, instrument="opencv/laplacian"))],
        }
        with pytest.raises(AcrossError, match="cannot be compared"):
            solve_across(candidates)

    def test_the_refusal_names_what_differed(self):
        candidates = {
            "c01": [Candidate(0, stats("c01", 40.0))],
            "c02": [Candidate(0, stats("c02", 42.0, stage="source"))],
        }
        with pytest.raises(AcrossError, match="stage"):
            solve_across(candidates)

    def test_incomparability_within_ONE_clips_grid_is_caught(self):
        """Not only across clips. A grid measured half one way is worse,
        because the inconsistency hides inside a single source."""
        candidates = {
            "c01": [
                Candidate(0, stats("c01", 40.0)),
                Candidate(1, stats("c01", 30.0, sample_spec="uniform:9")),
            ]
        }
        with pytest.raises(AcrossError, match="cannot be compared"):
            solve_across(candidates)


class TestTheDispersionFunctional:
    """`max/min` is defensible at N=3 and fragile at N=30."""

    def _thirty_with_an_outlier(self):
        rng = random.Random(4242)
        values = {
            f"c{i:02d}": [rng.uniform(18, 22) for _ in range(8)] for i in range(29)
        }
        values["outlier"] = [rng.uniform(180, 220) for _ in range(8)]
        return values

    def test_one_unfixable_clip_sets_the_whole_window(self):
        values = self._thirty_with_an_outlier()
        full = solve_across(grid(values))
        trimmed = solve_across(
            grid(values), dispersion="trimmed_range", drop=1
        )
        assert full.ratio > 8.0, full.ratio
        assert trimmed.ratio < 1.1, trimmed.ratio
        share = 1 - trimmed.log_spread / full.log_spread
        assert share > 0.9, f"the outlier accounts for {share:.1%} of the window"

    def test_the_trim_names_the_clip_it_left_out(self):
        """Which clip could not be fixed is the interesting half of the answer,
        so it is named rather than counted."""
        values = self._thirty_with_an_outlier()
        trimmed = solve_across(grid(values), dispersion="trimmed_range", drop=1)
        assert trimmed.outside == ("outlier",)
        assert len(trimmed.choices) == 29

    def test_the_trim_is_still_exact(self):
        """It is the same sweep with `>=` in place of `==`, so brute force
        still agrees."""
        rng = random.Random(SEED)
        for _ in range(120):
            n = rng.randint(2, 5)
            values = {
                f"c{i:02d}": [rng.choice([1.0, 2.0, 3.0, 5.0, 8.0])
                              for _ in range(rng.randint(1, 3))]
                for i in range(n)
            }
            drop = rng.randint(1, n - 1)
            got = solve_across(grid(values), dispersion="trimmed_range", drop=drop)
            best = None
            for keep in itertools.combinations(sorted(values), n - drop):
                ratio = brute_ratio({k: values[k] for k in keep})
                if best is None or ratio < best:
                    best = ratio
            assert got.ratio == pytest.approx(best, rel=1e-9), (values, drop)

    def test_a_drop_under_full_range_is_refused(self):
        """A drop that quietly did nothing would report a consistency the set
        does not have."""
        with pytest.raises(AcrossError, match="full_range"):
            solve_across(grid({"c01": [1.0], "c02": [2.0]}), drop=1)

    def test_a_trim_of_zero_is_refused(self):
        with pytest.raises(AcrossError, match="under another name"):
            solve_across(
                grid({"c01": [1.0], "c02": [2.0]}), dispersion="trimmed_range"
            )

    def test_dropping_everything_is_refused(self):
        with pytest.raises(AcrossError, match="not a set-relative question"):
            solve_across(
                grid({"c01": [1.0], "c02": [2.0]}),
                dispersion="trimmed_range", drop=2,
            )


class TestTheObjectiveHasOneMember:
    def test_asking_to_maximise_is_refused(self):
        """Typed as a one-member Literal so a type checker refuses it, and
        checked at run time so a dynamic caller is refused too. There is no
        honest reason to maximise the spread of a set's appearance."""
        with pytest.raises(AcrossError, match="only objective"):
            solve_across(grid({"c01": [1.0]}), objective="max_spread")

    def test_the_literal_really_has_one_member(self):
        import typing

        from looks.across import Objective

        assert typing.get_args(Objective) == ("min_spread",)


class TestRefusalsAboutTheInputs:
    def test_no_clips_at_all(self):
        with pytest.raises(AcrossError, match="at least one clip"):
            solve_across({})

    def test_a_clip_with_an_empty_grid(self):
        """Quietly leaving it out would answer a different question."""
        candidates = grid({"c01": [10.0]})
        candidates["c02"] = []
        with pytest.raises(AcrossError, match="no candidates at all"):
            solve_across(candidates)

    def test_the_refusal_names_the_empty_clips(self):
        candidates = grid({"c01": [10.0]})
        candidates["c02"] = []
        candidates["c03"] = []
        with pytest.raises(AcrossError, match=r"\['c02', 'c03'\]"):
            solve_across(candidates)


class TestItComposesWithResolveAcross:
    """The join between the two halves of RULE N."""

    def test_probes_feed_resolve_across(self):
        from looks.spec import Effect, Look, Ref, Target, resolve_across

        values = {"c01": [117.0, 72.0], "c02": [46.0, 38.0]}
        spread = solve_across(grid(values))
        probes = probes_for(spread, "scale")
        look = Look(
            target=Target.SET_RELATIVE,
            steps=(Effect(name="flatten", params={"scale": Ref("scale")}),),
        )
        resolved = resolve_across(look, probes)
        assert len(resolved) == 2
        assert [lk[0].params["scale"] for lk in resolved] == [
            c.value for c in spread.choices
        ]

    def test_each_resolved_look_is_external(self):
        """The set-relative question has been answered; re-resolving would ask
        it again against a different set."""
        from looks.spec import Effect, Look, Ref, Target, resolve_across

        spread = solve_across(grid({"c01": [10.0], "c02": [11.0]}))
        look = Look(
            target=Target.SET_RELATIVE,
            steps=(Effect(name="flatten", params={"scale": Ref("scale")}),),
        )
        for resolved in resolve_across(look, probes_for(spread, "scale")):
            assert resolved.target is Target.EXTERNAL

    def test_a_trimmed_answer_cannot_be_turned_into_probes(self):
        """Some clips have no value, so there is no probe for them — and
        inventing one would be inventing a look."""
        rng = random.Random(4242)
        values = {f"c{i:02d}": [rng.uniform(18, 22) for _ in range(4)] for i in range(4)}
        values["outlier"] = [rng.uniform(180, 220) for _ in range(4)]
        trimmed = solve_across(grid(values), dispersion="trimmed_range", drop=1)
        with pytest.raises(AcrossError, match="left outside the window"):
            probes_for(trimmed, "scale")


class TestTheAnswerIsData:
    def test_it_serialises(self):
        import json

        spread = solve_across(grid({"c01": [117.0, 72.0], "c02": [46.0, 38.0]}))
        document = json.loads(json.dumps(spread.to_dict()))
        assert document["schema"] == "looks.spread/v1"
        assert len(document["choices"]) == 2
        assert document["statistic"] == "sharpness"

    def test_it_reports_the_statistic_it_used(self):
        """Two spreads over different statistics are different answers, and a
        number without its statistic is not one."""
        spread = solve_across(
            grid({"c01": [117.0], "c02": [114.0]}), statistic="sharpness"
        )
        assert spread.statistic == "sharpness"


class TestTheReportedNumbersAreTheMeasuredOnes:
    """Found by an independent verification of the shipped module.

    `Choice.statistic` was `exp(log(measured))`. That is not the measurement:
    **147 of 200** realistic sharpness values fail bit-equality through the
    round trip, and 117.0 came back as 117.00000000000003. The value reaches
    the `looks.spread/v1` wire document, and a package this careful about
    measurement identity must not report a number it altered.
    """

    def test_the_statistic_is_the_input_float(self):
        values = {"c01": [117.0, 72.0], "c02": [46.0, 38.0]}
        got = solve_across(grid(values))
        for choice in got.choices:
            assert choice.statistic in values[choice.source_id], (
                f"{choice.statistic!r} is not one of the measurements given"
            )

    def test_over_many_values_none_is_altered(self):
        rng = random.Random(SEED)
        for _ in range(200):
            a, b = rng.uniform(1, 200), rng.uniform(1, 200)
            got = solve_across(grid({"c01": [a], "c02": [b]}))
            reported = {c.source_id: c.statistic for c in got.choices}
            assert reported == {"c01": a, "c02": b}

    def test_the_ratio_cannot_raise_a_bare_overflow(self):
        """Above a log spread of ~709 `math.exp` overflows. Absurd input, but
        it must not surface as an OverflowError in a module where every other
        failure is an AcrossError."""
        with pytest.raises(AcrossError, match="overflows a float"):
            solve_across(grid({"c01": [1e-300], "c02": [1e300]}))


class TestTheAnswerDoesNotDependOnInputORDER:
    """`to_dict` is a wire document, so it must not carry how a caller happened
    to build its mapping."""

    def test_the_same_clips_in_a_different_order_give_the_same_document(self):
        one = solve_across(grid({"c01": [10.0, 12.0], "c02": [11.0]}))
        other = solve_across(grid({"c02": [11.0], "c01": [10.0, 12.0]}))
        assert one.to_dict() == other.to_dict()

    def test_choices_are_ordered_by_source_id(self):
        got = solve_across(grid({"c03": [10.0], "c01": [10.0], "c02": [10.0]}))
        assert [c.source_id for c in got.choices] == ["c01", "c02", "c03"]

    def test_probes_follow_that_order_so_the_join_is_stable(self):
        """`probes_for` is positional against `resolve_across`, so the order
        has to come from a rule. `Spread.choices` carries the source ids for a
        caller that needs to check the correspondence."""
        got = solve_across(grid({"c02": [10.0], "c01": [11.0]}))
        probes = probes_for(got, "scale")
        assert len(probes) == 2
        assert [c.source_id for c in got.choices] == ["c01", "c02"]
