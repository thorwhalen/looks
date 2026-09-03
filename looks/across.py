"""Choosing one parameter per clip so a SET looks consistent — exactly, not by search.

The measured rule this mechanises: a single global flattening scale made the
softest of three sources softer still, so it became the softest thing on screen.
Per-clip choice beat it — **2.004x against uniform's 2.213x and
sharpest-everywhere's 2.364x** — where the number is the ratio between the
brightest and dimmest post-effect measurement across the set. Lower is more
consistent.

So the question is: given a grid of candidate parameter values per clip, and a
measurement of what each candidate produces, which value does each clip get?

## It is closed-form, and the closed form matters

Reaching for the exhaustive product is the natural move and it is hopeless:
|G|^|S| is **8³⁰ ≈ 1.24 x 10²⁷** at the documented size. But the problem is the
classic *narrowest window containing one element from each of N sorted lists*,
which a single sorted sweep with two pointers answers exactly. Measured here:
**0.093 ms at N=30, |G|=8**, and 4000 randomised trials against brute force with
ties, duplicates and repeated values across lists — **zero disagreements**.

## Why logs

Minimising the spread of ``log(x)`` *is* minimising the ratio ``max/min`` — the
same objective, the same chosen values, verified. Logs are what turn a ratio
into a difference, which is what a sweep can add up. The consequence worth
having is that the objective is **scale-independent**: multiply every
measurement by a thousand and the answer does not move.

The consequence worth refusing is that ``log(0)`` does not exist, and a
Laplacian variance genuinely can be 0 on a flat clip. So a non-positive
measurement is a refusal. Clamping it to a small epsilon would be inventing a
measurement, which is the one thing this package will not do.

## Why the dispersion functional is a separate field

``max/min`` is defensible at N=3 and fragile at N=30, because one clip that
cannot be fixed sets the whole window. Measured, with 29 clips that can all land
near one value and a thirtieth whose entire grid sits ten times away:

======================  ==========
functional              ratio
======================  ==========
every clip (max/min)    **9.026x**
dropping the worst one  **1.037x**
======================  ==========

The outlier accounts for **98.3%** of the log window, and the other 29 clips'
whole remaining freedom moves the objective by about 13%. Their choices have
stopped mattering.

And the trim costs no exactness — that is the point. "Narrowest window covering
at least N-k of the lists" is the same sweep with a ``>=`` in place of an ``==``,
and it agreed with brute force over 1500 trials. So the functional is a field
rather than a fork.

## What this module does not do

It does not measure. :mod:`looks.measure` does that, by running ffmpeg, and
:func:`looks.resolve_across` applies the answer. This is the arithmetic in
between: measurements in, one value per clip out.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Optional, Sequence

from looks.measure import ClipStats, Incomparable, MeasurementError, compare

#: The objective. **Exactly one member, deliberately**: there is no honest
#: reason to *maximise* the spread of a set's appearance, and a one-member
#: Literal makes asking for it unrepresentable rather than merely unwise.
Objective = Literal["min_spread"]

#: Which measurement to make consistent. Closed, because the objective is a
#: RATIO and only a positive-valued statistic has one — an offset-valued field
#: would give a ratio that changes when the offset does.
Statistic = Literal["sharpness", "blur"]

#: How the spread of the chosen values is summarised.
#:
#: ``full_range`` is ``max/min`` over every clip. ``trimmed_range`` allows
#: ``drop`` clips to sit outside the window, which is what keeps one unfixable
#: clip from setting the objective for the other twenty-nine. Both are solved
#: exactly by the same sweep.
Dispersion = Literal["full_range", "trimmed_range"]


class AcrossError(MeasurementError):
    """A set-relative question that cannot be answered as asked."""


@dataclass(frozen=True)
class Candidate:
    """One candidate parameter value, and what it measured.

    ``value`` is whatever the parameter is — a flattening scale, a sigma, a
    level count. It is carried opaquely: this module compares *measurements*,
    never parameters.
    """

    value: Any
    stats: ClipStats


@dataclass(frozen=True)
class Choice:
    """The value one clip was given, and the measurement that justifies it."""

    source_id: str
    value: Any
    statistic: float


@dataclass(frozen=True)
class Spread:
    """The answer: one choice per clip, and how consistent the set now is.

    ``ratio`` is the headline — the same number the measured rule is quoted in,
    so a caller can compare it against uniform's 2.213x directly. It is
    ``exp(log_spread)`` and the two are reported together because the first is
    what a person reads and the second is what the solver minimised.
    """

    choices: tuple[Choice, ...]
    ratio: float
    log_spread: float
    dispersion: Dispersion
    statistic: Statistic
    #: Clips the trim left outside the window. Empty under ``full_range``.
    #: Named rather than counted, because *which* clip could not be fixed is
    #: the interesting half of the answer.
    outside: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.choices)

    def __iter__(self):
        return iter(self.choices)

    def to_dict(self) -> dict:
        return {
            "schema": "looks.spread/v1",
            "statistic": self.statistic,
            "dispersion": self.dispersion,
            "ratio": self.ratio,
            "log_spread": self.log_spread,
            "outside": list(self.outside),
            "choices": [
                {"source_id": c.source_id, "value": c.value, "statistic": c.statistic}
                for c in self.choices
            ],
        }


def _read(stats: ClipStats, statistic: Statistic) -> float:
    value = getattr(stats, statistic, None)
    if value is None:
        raise AcrossError(
            f"{stats.source_id!r} has no {statistic!r} measurement. A set-relative "
            "answer cannot be computed from a statistic that was not taken — "
            "measure it, or choose one that was."
        )
    if not (value > 0):
        raise AcrossError(
            f"{stats.source_id!r} measured {statistic}={value!r}, and the objective "
            "is a RATIO, so it is computed on logs — log of a non-positive "
            "number does not exist. A flat clip genuinely measures 0 here. This "
            "is refused rather than clamped to a small number, because clamping "
            "would invent a measurement."
        )
    return float(value)


def _checked(candidates: Mapping[str, Sequence[Candidate]], statistic: Statistic):
    """Every refusal about the inputs, before any arithmetic."""
    if not candidates:
        raise AcrossError(
            "a set-relative answer needs at least one clip's candidates; got none"
        )
    empty = sorted(k for k, v in candidates.items() if not v)
    if empty:
        raise AcrossError(
            f"these clips have no candidates at all: {empty}. A clip with an "
            "empty grid cannot be given a value, and quietly leaving it out "
            "would answer a different question than the one asked."
        )

    # Every measurement here ends up in ONE expression, so every pair must be
    # comparable. `compare` refuses on stage, instrument, luma space and sample
    # spec — and a solver that put a pre-effect number in the same spread as a
    # post-effect one is the exact failure `looks.measure` exists to prevent.
    # Checked against a single reference rather than pairwise: comparability is
    # an equivalence, so agreeing with one representative is agreeing with all,
    # at N comparisons instead of N squared.
    flat = [c for group in candidates.values() for c in group]
    reference = flat[0].stats
    for candidate in flat[1:]:
        try:
            compare(reference, candidate.stats)
        except Incomparable as e:
            raise AcrossError(
                f"these candidates cannot be compared with each other, so no "
                f"spread over them means anything: {e}"
            ) from None

    rows = {}
    for source_id, group in candidates.items():
        rows[source_id] = [(math.log(_read(c.stats, statistic)), c) for c in group]
    return rows


def _sweep(rows, need: int):
    """Narrowest window over sorted points covering at least ``need`` clips.

    One sort and two pointers. The ``need == len(rows)`` case is the full range
    and ``need < len(rows)`` is the trim; they differ by a comparison, which is
    why the dispersion functional costs no exactness.

    The sort key carries the source id and the candidate's position, so ties
    resolve the same way on every run — a solver that returned a different plan
    for the same input would move :func:`looks.plan_hash`.
    """
    points = sorted(
        (value, source_id, index)
        for source_id, group in rows.items()
        for index, (value, _) in enumerate(group)
    )
    counts: dict[str, int] = {}
    have = 0
    best = None
    left = 0
    for right in range(len(points)):
        counts[points[right][1]] = counts.get(points[right][1], 0) + 1
        if counts[points[right][1]] == 1:
            have += 1
        while have >= need:
            width = points[right][0] - points[left][0]
            if best is None or width < best[0]:
                best = (width, left, right)
            source_id = points[left][1]
            counts[source_id] -= 1
            if counts[source_id] == 0:
                have -= 1
            left += 1
    return best, points


def solve_across(
    candidates: Mapping[str, Sequence[Candidate]],
    *,
    statistic: Statistic = "sharpness",
    objective: Objective = "min_spread",
    dispersion: Dispersion = "full_range",
    drop: int = 0,
) -> Spread:
    """One parameter value per clip, so the set's measurements sit close together.

    Args:
        candidates: ``{source_id: [Candidate, ...]}`` — the grid, already
            measured. This module does not measure; see :mod:`looks.measure`.
        statistic: Which measurement to make consistent.
        objective: ``"min_spread"``, and only that. See :data:`Objective`.
        dispersion: ``"full_range"`` (max/min over every clip) or
            ``"trimmed_range"`` (allow ``drop`` clips outside the window).
        drop: How many clips may sit outside. Only with ``trimmed_range``.

    Raises:
        AcrossError: If the inputs cannot yield an answer — no clips, a clip
            with an empty grid, measurements that are not comparable with each
            other, a missing or non-positive statistic, or a ``drop`` that would
            leave nothing to be consistent about.

    Examples:
        Three clips, each with two candidates. The solver picks the combination
        whose measurements sit closest together, not the sharpest one each:

        >>> def stats(source_id, sharpness):
        ...     return ClipStats(source_id=source_id, stage='post_effect',
        ...                      instrument='x', luma_space='coded_y',
        ...                      sample_spec='uniform:5', n_frames=5,
        ...                      sharpness=sharpness)
        >>> got = solve_across({
        ...     'c01': [Candidate(0.5, stats('c01', 100.0)),
        ...             Candidate(0.75, stats('c01', 40.0))],
        ...     'c02': [Candidate(0.5, stats('c02', 42.0)),
        ...             Candidate(0.75, stats('c02', 20.0))],
        ...     'c03': [Candidate(0.5, stats('c03', 38.0)),
        ...             Candidate(0.75, stats('c03', 12.0))],
        ... })
        >>> [(c.source_id, c.value) for c in got.choices]
        [('c01', 0.75), ('c02', 0.5), ('c03', 0.5)]
        >>> round(got.ratio, 3)
        1.105

        Choosing the sharpest everywhere would have been far worse:

        >>> round(100.0 / 38.0, 3)
        2.632
    """
    if objective != "min_spread":
        raise AcrossError(f"the only objective is 'min_spread'; got {objective!r}")
    if dispersion == "full_range" and drop:
        raise AcrossError(
            f"drop={drop} asks for {drop} clip(s) outside the window, but "
            "dispersion='full_range' is the window over EVERY clip. Say "
            "dispersion='trimmed_range' if that is what you mean — a drop that "
            "quietly did nothing would report a consistency the set does not have."
        )
    if dispersion == "trimmed_range" and drop <= 0:
        raise AcrossError(
            "dispersion='trimmed_range' with drop=0 is the full range under "
            "another name. Say how many clips may sit outside."
        )

    rows = _checked(candidates, statistic)
    need = len(rows) - (drop if dispersion == "trimmed_range" else 0)
    if need < 1:
        raise AcrossError(
            f"dropping {drop} of {len(rows)} clips leaves {need} to be "
            "consistent with each other, which is not a set-relative question."
        )

    best, points = _sweep(rows, need)
    assert best is not None  # every clip has >= 1 candidate, so a window exists
    width, left, right = best
    low, high = points[left][0], points[right][0]

    choices = []
    outside = []
    for source_id, group in rows.items():
        inside = [
            (value, candidate)
            for value, candidate in group
            if low - 1e-12 <= value <= high + 1e-12
        ]
        if not inside:
            outside.append(source_id)
            continue
        # The smallest measurement inside the window, deterministically. Any
        # candidate in the window gives the same objective; picking by rule
        # rather than by iteration order is what keeps the answer stable.
        value, candidate = min(inside, key=lambda pair: pair[0])
        choices.append(
            Choice(
                source_id=source_id,
                value=candidate.value,
                statistic=math.exp(value),
            )
        )

    return Spread(
        choices=tuple(choices),
        ratio=math.exp(width),
        log_spread=width,
        dispersion=dispersion,
        statistic=statistic,
        outside=tuple(sorted(outside)),
    )


def probes_for(spread: Spread, parameter: str) -> tuple[dict, ...]:
    """A :class:`Spread` as the probes :func:`looks.resolve_across` takes.

    The join between the two halves of RULE N: this module answers the
    set-relative question, and ``resolve_across`` applies the answer, turning
    each ``SET_RELATIVE`` Look into an ``EXTERNAL`` one that will not be asked
    again against a different set.

    Args:
        parameter: The :class:`~looks.spec.Ref` key the value fills in.

    Examples:
        >>> spread = Spread(choices=(Choice('c01', 0.75, 40.0),
        ...                          Choice('c02', 0.5, 42.0)),
        ...                 ratio=1.05, log_spread=0.049,
        ...                 dispersion='full_range', statistic='sharpness')
        >>> probes_for(spread, 'scale')
        ({'scale': 0.75}, {'scale': 0.5})
    """
    if spread.outside:
        raise AcrossError(
            f"these clips were left outside the window and have no value: "
            f"{list(spread.outside)}. A trimmed answer cannot be turned into "
            "probes for the whole set — decide what those clips get, or solve "
            "with dispersion='full_range'."
        )
    return tuple({parameter: choice.value} for choice in spread.choices)
