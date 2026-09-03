"""How one shot gives way to the next — the vocabulary, not the graph.

ffmpeg's ``xfade`` offers 58 transitions on this build. This package carries
**sixteen**, and the reason is the posture rather than the number: a name a
caller passes should be refused here, at the boundary, rather than discovered
three stages later as an ffmpeg error. Measured — an unrecognised curve produces

    [Parsed_xfade_0] const_values array too small for transition
    Error applying option 'transition' to filter 'xfade':
        Not yet implemented in FFmpeg, patches welcome

which names neither the caller's mistake nor the filter's actual complaint. A
vocabulary we own is a vocabulary we can keep working across ffmpeg builds, and
translating at the boundary is the same rule `muvid`'s EDL and `an`'s camera
table already follow.

## Why this module emits no filter

Every other compiler here returns a string. This one returns **options**, because
``xfade`` takes *two* video inputs and a compiled fragment in this package
references no input index at all — that is rule 20, and it is what lets a
fragment splice into a bare ``-vf``, into a per-cut chain, and into a pipe's
encoder half alike. A two-input filter cannot satisfy it.

So `looks` owns the curve names, the record, and the floor; the host owns the
filtergraph that wires two streams into an ``xfade``. That is the same split as
everywhere else: this package decides *what*, the caller decides *where*.

## A short transition is a hard cut wearing a label, and the floor is not a constant

Measured counting frames that are neither source colour. The numbers below
were taken on ffmpeg 8.1 and re-verified unchanged on **6.1.6 and 9.0.1**,
which is why they are stated as a property of the filter rather than of a
build — `speed=0` and a height-1 frame both looked like properties of ffmpeg
until CI ran a different one:

=========  ==========  ===============
fps        duration    blended frames
=========  ==========  ===============
30         0.30 s      8
30         0.10 s      2
30         0.04 s      1
30         0.033 s     **0**
10         0.30 s      2
10         0.10 s      **0**
=========  ==========  ===============

So a transition shorter than about one frame period produces **no blended frame
at all** — the picture cuts, and the record says it faded. ``duration=0`` is
accepted by ffmpeg without complaint.

:data:`MIN_TRANSITION_S` is inherited from `muvid` at 0.04 s, which is exactly
one frame at 25 fps — which is where the number came from, and why it is *too
small* at lower rates. :func:`blended_frames` is the honest form: it takes the
rate, because the question does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional

from looks.spec import SpecError

#: The transitions this package offers: a curated subset of ffmpeg's 58, chosen
#: because they read as deliberate edits rather than as effects. Adding one is a
#: decision — the point of an owned vocabulary is that it does not grow by
#: accident — and every name here is verified present in ffmpeg's ``xfade``.
TRANSITION_CURVES = frozenset(
    {
        "fade",
        "fadeblack",
        "fadewhite",
        "dissolve",
        "wipeleft",
        "wiperight",
        "wipeup",
        "wipedown",
        "slideleft",
        "slideright",
        "slideup",
        "slidedown",
        "smoothleft",
        "smoothright",
        "circleopen",
        "circleclose",
    }
)

#: The default curve. A plain cross-fade, because it is the one that reads as
#: no decision at all.
DFLT_CURVE = "fade"

#: The floor below which a transition is a hard cut wearing a label. Inherited
#: from `muvid`, where it is 0.04 s — **exactly one frame at 25 fps**, which is
#: where the number comes from. It is therefore too small at lower rates, and
#: :func:`blended_frames` is the form that knows it: prefer that when the rate
#: is available, and treat this as the rate-free fallback it is.
MIN_TRANSITION_S = 0.04


class TransitionError(SpecError):
    """A transition that cannot be honoured as asked."""


@dataclass(frozen=True)
class Transition:
    """How a shot blends in from its predecessor.

    A record rather than a bare float, so the curve — and anything after it — is
    an additive field rather than another shape change on something already
    serialised.

    The transition belongs to the shot it is *on*: it annotates that shot's
    **entrance**. `muvid`'s EDL keeps it that way so spans stay one per span, and
    the reasoning for that invariant stays there — this is the vocabulary, not
    the edit model.

    Examples:
        >>> Transition(0.5)
        Transition(duration_s=0.5, curve='fade')
        >>> Transition(0.5, 'circleopen').curve
        'circleopen'

        A name outside the vocabulary is refused here, not by ffmpeg later:

        >>> Transition(0.5, 'starwipe')
        Traceback (most recent call last):
        ...
        looks.transition.TransitionError: 'starwipe' is not a transition this
        package offers...

        And a duration that cannot be a transition:

        >>> Transition(0.0)
        Traceback (most recent call last):
        ...
        looks.transition.TransitionError: a transition needs a positive
        duration; got 0.0...
    """

    duration_s: float
    curve: str = DFLT_CURVE

    def __post_init__(self) -> None:
        if not (self.duration_s > 0):
            raise TransitionError(
                f"a transition needs a positive duration; got "
                f"{self.duration_s!r}. ffmpeg accepts duration=0 without "
                "complaint and cuts, so a zero here would be a fade in the "
                "record and a cut on screen."
            )
        if self.curve not in TRANSITION_CURVES:
            near = sorted(c for c in TRANSITION_CURVES if c[:4] == self.curve[:4])
            raise TransitionError(
                f"{self.curve!r} is not a transition this package offers. "
                f"Available: {sorted(TRANSITION_CURVES)}."
                + (f" Did you mean {near}?" if near else "")
                + " ffmpeg's own refusal for an unknown name is 'Not yet "
                "implemented in FFmpeg, patches welcome', which names neither "
                "the mistake nor the filter — which is why this is refused here."
            )

    def to_dict(self) -> dict:
        return {"duration_s": self.duration_s, "curve": self.curve}

    @classmethod
    def from_dict(cls, d: Mapping) -> "Transition":
        return cls(
            duration_s=float(d["duration_s"]),
            curve=str(d.get("curve", DFLT_CURVE)),
        )


def blended_frames(transition: Transition, fps: float) -> int:
    """How many frames will actually be a mixture of the two shots.

    The honest form of "is this long enough", because the answer depends on the
    rate and a constant cannot. Measured against ffmpeg: a 0.30 s fade blends 8
    frames at 30 fps and 2 at 10 fps, and 0.10 s blends 2 at 30 fps and **none**
    at 10.

    >>> blended_frames(Transition(0.30), 30)
    8
    >>> blended_frames(Transition(0.30), 10)
    2
    >>> blended_frames(Transition(0.10), 10)
    0
    """
    if fps <= 0:
        raise TransitionError(f"fps must be positive; got {fps!r}")
    return max(0, int(math.floor(transition.duration_s * fps)) - 1)


def is_hard_cut(transition: Transition, fps: float) -> bool:
    """Will this transition produce no blended frame at all?

    >>> is_hard_cut(Transition(0.30), 30)
    False
    >>> is_hard_cut(Transition(0.10), 10)
    True
    """
    return blended_frames(transition, fps) == 0


def check_visible(transition: Transition, fps: float) -> None:
    """Raise unless the transition will actually be seen.

    Call it when the rate is known. A transition that blends nothing is not a
    subtle transition — it is a cut, and a record saying otherwise is the kind
    of quiet disagreement between plan and picture this package exists to
    prevent.

    >>> check_visible(Transition(0.30), 30)
    >>> check_visible(Transition(0.05), 10)
    Traceback (most recent call last):
    ...
    looks.transition.TransitionError: a 0.05 s transition at 10 fps blends 0
    frames...
    """
    if is_hard_cut(transition, fps):
        needed = 2.0 / fps
        raise TransitionError(
            f"a {transition.duration_s:g} s transition at {fps:g} fps blends 0 "
            f"frames — it is a hard cut, and calling it {transition.curve!r} in "
            f"the record would be the only place the fade exists. It needs at "
            f"least {needed:.3g} s at this rate."
        )


def xfade_options(
    transition: Transition, *, offset: float, fps: Optional[float] = None
) -> dict:
    """The ``xfade`` options for this transition — options, not a filter.

    ``xfade`` takes two video inputs, and a compiled fragment in this package
    references no input index (rule 20). So the host wires the two streams and
    splices these options in; `looks` says what the transition IS.

    Args:
        offset: When the transition starts, in the output's timeline. The host's
            number, because it depends on how the host laid out its cuts.
        fps: When given, the transition is checked against it — a transition
            that blends nothing is refused rather than emitted.

    Examples:
        >>> xfade_options(Transition(0.5, 'circleopen'), offset=2.0)
        {'transition': 'circleopen', 'duration': 0.5, 'offset': 2.0}

        >>> xfade_options(Transition(0.02), offset=1.0, fps=25)
        Traceback (most recent call last):
        ...
        looks.transition.TransitionError: a 0.02 s transition at 25 fps blends 0
        frames...
    """
    if fps is not None:
        check_visible(transition, fps)
    if offset < 0:
        raise TransitionError(
            f"a transition cannot start before the output does; got offset={offset!r}"
        )
    return {
        "transition": transition.curve,
        "duration": transition.duration_s,
        "offset": offset,
    }
