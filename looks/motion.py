"""A camera path, compiled to an ffmpeg fragment — the compile half of RULE G.

RULE G splits authored geometry from its compilation. ``burns`` owns the
**authored** side: a ``BurnsPath`` with keyframes and easing, which exists
because someone chose it as the shot. ``looks`` owns the **compiled** side,
because a moving window expressed as ``crop=x='iw*(...)'`` is ffmpeg vocabulary
and nothing else — the same reason ``looks`` owns every other filter string.

So this module takes keyframes and returns a string. It does not ease, does not
sample a path, does not decide where a camera should go, and **never imports
burns** — the dependency points ``burns -> looks``, which is legal because
``looks`` is stdlib-only, and the reverse stays forbidden because ``burns``
pulls ``moviepy``, which pulls a GPL ffmpeg binary. A window here is anything
with ``.x``/``.y``/``.w``/``.h`` in burns' normalised, top-left, window-fraction
convention. Adopting a third rect convention is the mistake ``muvid.CropWindow``'s
docstring already exists to prevent.

Easing lives on the far side of this boundary on purpose. An eased path is
sampled by its owner into as many keyframes as it needs, and what arrives here
is interpolated **linearly** between them. That is not a limitation being
tolerated; it is what makes the seam a seam: ``looks`` never has to know what
`ease_in_out_cubic` means, and ``burns`` never has to know what ``in_time`` is.

## Which filter, and why it is not a matter of taste

Measured on ffmpeg 8.1, 2026-09-02 — the full transcript is
``docs/research/00f_motion_filters_evidence.md``.

===================================  ==========  ==================================
motion                               filter      why
===================================  ==========  ==================================
static window                        ``crop``    no clock needed; any aspect
**pan** (position varies)            ``crop``    per-frame ``x``/``y``; any aspect
**zoom** (window size varies)        ``zoompan`` ``crop`` structurally cannot
===================================  ==========  ==================================

The third row is the one that decides the module. ``crop``'s ``w``/``h`` do not
merely evaluate once — ``t`` is not in scope for them and the filter **refuses
to configure**, which is structural: a filter link has one fixed frame size. So
a Ken Burns path, which is a zoom by definition, is not compilable to ``crop``
at all.

This **overturns a recorded fleet fact.** ``muvid._crop_filter``'s docstring —
propagated by two of this package's own research notes into a warning aimed at
the ``burns`` owner — says *"Not zoompan: its expression vocabulary has no t at
all, and it duplicates frames on video input."* Both premises are true and the
conclusion is wrong: ``t`` is undefined but ``in_time`` is not, and the
duplication is the default ``d`` rather than a property of the filter (``d=1``
gives exactly 1:1, measured 20 frames from 20). ``muvid``'s own code is correct
— it compiles a *pan*, which is the case where ``crop`` is right and simpler.

Three ``zoompan`` traps are compiled away here so that no caller has to
remember them:

- its ``x``/``y`` are in **original input pixels**, not zoomed ones (60.5 dB
  against the reference versus 6.3 dB for the other reading);
- its ``fps`` **silently retimes** — at ``fps=25`` on a 10 fps source the frame
  count is unchanged and the clip is 60% shorter, so it is required here, never
  defaulted;
- its ``zoom`` is one scalar, so the visible window is always geometrically
  similar to the source frame, and a window that is not is refused rather than
  distorted on one axis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence, runtime_checkable

from looks.geometry import GeometryError, Size

#: Two normalised fractions are the same window edge within this. Tighter than
#: any authoring tool's precision and looser than float noise from easing
#: arithmetic, which is where these numbers come from.
EPSILON = 1e-9

#: How many decimals of a normalised fraction reach the filter string. At 1e-6
#: of a 3840-pixel frame that is 0.004 px — far below the integer rounding both
#: filters do anyway, and it keeps the emitted string readable.
PRECISION = 6

#: ``zoompan`` clamps its ``zoom`` here, **silently**. Measured: against a
#: reference built with ``crop``+``scale``, z=10 scores 54.4 dB and z=12 scores
#: 13.2 dB — the second is not a worse rendering of the window asked for, it is
#: a correct rendering of a different one. So the smallest window ``zoompan``
#: can show is 1/10 of the frame, and asking for less is refused here rather
#: than honoured as something else.
MAX_ZOOM = 10.0

#: The consequence of :data:`MAX_ZOOM`, in the units this module speaks.
MIN_WINDOW_FRACTION = 1.0 / MAX_ZOOM

#: Prepended to a moving ``crop`` and never to a static one. ``t`` must start at
#: 0 for a ramp to mean anything; adding it unconditionally would change a path
#: that already works. Inherited verbatim, reason included, from
#: ``muvid.footage.assemble._crop_filter``.
TIMEBASE_RESET = "setpts=PTS-STARTPTS"


class MotionError(GeometryError):
    """A path that cannot be compiled, or that would compile to a lie."""


@runtime_checkable
class WindowLike(Protocol):
    """Burns' convention: normalised, top-left origin, window fractions.

    Structural on purpose — ``burns.Rect`` satisfies it without ``looks``
    importing ``burns``, and so does anything else a caller already has.
    """

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Window:
    """A concrete :class:`WindowLike`, for callers who do not already have one.

    >>> Window(0.25, 0.25, 0.5, 0.5)
    Window(x=0.25, y=0.25, w=0.5, h=0.5)

    The whole frame is the identity window:

    >>> Window.full()
    Window(x=0.0, y=0.0, w=1.0, h=1.0)
    """

    x: float
    y: float
    w: float
    h: float

    @classmethod
    def full(cls) -> "Window":
        return cls(0.0, 0.0, 1.0, 1.0)


@dataclass(frozen=True)
class Keyframe:
    """A window, at a time in seconds from the start of the clip.

    >>> Keyframe(0.0, Window.full())
    Keyframe(t=0.0, window=Window(x=0.0, y=0.0, w=1.0, h=1.0))
    """

    t: float
    window: WindowLike


def _num(value: float) -> str:
    """A float as the filter string sees it, without a trailing-zero tail.

    >>> _num(0.5), _num(1.0), _num(1 / 3)
    ('0.5', '1', '0.333333')
    """
    text = f"{value:.{PRECISION}f}".rstrip("0").rstrip(".")
    return text or "0"


def _check(keyframes: Sequence[Keyframe]) -> tuple[Keyframe, ...]:
    """Every refusal this module makes about a path, in one place."""
    frames = tuple(keyframes)
    if not frames:
        raise MotionError("a path needs at least one keyframe; got none")
    last: Optional[float] = None
    for i, k in enumerate(frames):
        for name in ("x", "y", "w", "h"):
            if not hasattr(k.window, name):
                raise MotionError(
                    f"keyframe {i}'s window has no .{name} — a window is "
                    "burns' convention: normalised x/y/w/h, top-left origin"
                )
            value = getattr(k.window, name)
            if not isinstance(value, (int, float)) or value != value:
                raise MotionError(
                    f"keyframe {i}'s .{name} is {value!r}, which is not a "
                    "number. An unreadable window is a refusal, not a default."
                )
        if k.window.w <= 0 or k.window.h <= 0:
            raise MotionError(
                f"keyframe {i} has a window of zero or negative extent "
                f"({_num(k.window.w)} x {_num(k.window.h)})"
            )
        if (
            k.window.x < -EPSILON
            or k.window.y < -EPSILON
            or k.window.x + k.window.w > 1 + EPSILON
            or k.window.y + k.window.h > 1 + EPSILON
        ):
            raise MotionError(
                f"keyframe {i}'s window leaves the frame: x+w="
                f"{_num(k.window.x + k.window.w)}, y+h="
                f"{_num(k.window.y + k.window.h)}. ffmpeg would clamp this to "
                "a different framing than the one authored, silently."
            )
        if last is not None and k.t <= last:
            raise MotionError(
                f"keyframe {i} is at t={_num(k.t)}, not after t={_num(last)}. "
                "Keyframes must be strictly increasing in time — a path that "
                "revisits a moment is not a path."
            )
        last = k.t
    if frames[0].t < -EPSILON:
        raise MotionError(f"the first keyframe is at t={_num(frames[0].t)}, before 0")
    return frames


def is_static(keyframes: Sequence[Keyframe]) -> bool:
    """Does the window never move? Then no clock is needed at all.

    >>> a, b = Window(0, 0, 0.5, 0.5), Window(0, 0, 0.5, 0.5)
    >>> is_static([Keyframe(0, a), Keyframe(2, b)])
    True
    >>> is_static([Keyframe(0, a), Keyframe(2, Window(0.5, 0, 0.5, 0.5))])
    False
    """
    frames = _check(keyframes)
    first = frames[0].window
    return all(
        abs(getattr(k.window, n) - getattr(first, n)) <= EPSILON
        for k in frames
        for n in ("x", "y", "w", "h")
    )


def zooms(keyframes: Sequence[Keyframe]) -> bool:
    """Does the window's SIZE change? That is the question that picks a filter.

    >>> full, half = Window.full(), Window(0.25, 0.25, 0.5, 0.5)
    >>> zooms([Keyframe(0, full), Keyframe(2, half)])
    True

    A pan is a move at constant size, and does not zoom:

    >>> zooms([Keyframe(0, Window(0, 0, 0.5, 1)), Keyframe(2, Window(0.5, 0, 0.5, 1))])
    False
    """
    frames = _check(keyframes)
    first = frames[0].window
    return any(
        abs(getattr(k.window, n) - getattr(first, n)) > EPSILON
        for k in frames
        for n in ("w", "h")
    )


def ramp(points: Sequence[tuple[float, float]], clock: str) -> str:
    """Piecewise-linear interpolation of ``points`` as one ffmpeg expression.

    A sum of clamped ramps rather than nested ``if()``: it is exact at every
    knot, linear between them, and — the property that matters — **flat outside
    the path on both sides**, because every term saturates. That is the clamping
    ``muvid._crop_filter`` does at two keyframes, generalised to N without
    growing a branch.

    >>> ramp([(0.0, 10.0)], "t")
    '10'
    >>> ramp([(0.0, 0.0), (2.0, 1.0)], "t")
    '(0+(1)*min(max((t-0)/2,0),1))'

    Held before the first keyframe and after the last, which is what stops a
    clip that outlives its path from drifting off the end:

    >>> ramp([(1.0, 5.0), (3.0, 9.0)], "in_time")
    '(5+(4)*min(max((in_time-1)/2,0),1))'

    A segment that does not move contributes ``0 * something``, so it is not
    emitted; an axis that never moves collapses to the constant it is. This is
    not cosmetic — it is the difference between ffmpeg evaluating an expression
    per frame and reading a number once:

    >>> ramp([(0.0, 0.4), (2.0, 0.4), (5.0, 0.9)], "t")
    '(0.4+(0.5)*min(max((t-2)/3,0),1))'
    >>> ramp([(0.0, 0.25), (2.0, 0.25)], "t")
    '0.25'
    """
    if not points:
        raise MotionError("a ramp needs at least one point")
    terms = []
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        span = t1 - t0
        if span <= 0:
            raise MotionError(f"a ramp segment has non-positive span {_num(span)}")
        if abs(v1 - v0) <= EPSILON:
            continue
        terms.append(
            f"({_num(v1 - v0)})*min(max(({clock}-{_num(t0)})/{_num(span)},0),1)"
        )
    start = _num(points[0][1])
    if not terms:
        return start
    return "(" + "+".join([start, *terms]) + ")"


def crop_fragment(keyframes: Sequence[Keyframe]) -> str:
    """A path of constant window size, compiled to ``crop``.

    Normalised fractions become pixels only once the source dimensions are
    known, and the only thing that knows them is ffmpeg — hence ``iw``/``ih``
    rather than arithmetic here. That is what makes the fragment
    resolution-independent and input-index-free, which is what lets a consumer
    splice it into a filter string it already owns.

    >>> crop_fragment([Keyframe(0, Window(0.25, 0.1, 0.5, 0.5))])
    "crop=w='iw*0.5':h='ih*0.5':x='iw*0.25':y='ih*0.1'"

    A moving window gets its clock reset, and only then:

    >>> print(crop_fragment([
    ...     Keyframe(0, Window(0, 0, 0.5, 1)),
    ...     Keyframe(2, Window(0.5, 0, 0.5, 1)),
    ... ]))
    setpts=PTS-STARTPTS,crop=w='iw*0.5':h='ih*1':x='iw*(0+(0.5)*min(max((t-0)/2,0),1))':y='ih*0'

    Raises:
        MotionError: If the window's size varies. ``crop``'s ``w``/``h`` do not
            accept ``t`` — the filter refuses to configure — so this is not a
            missing feature that could be added later.
    """
    frames = _check(keyframes)
    if zooms(frames):
        raise MotionError(
            "this path zooms, and `crop` cannot express a zoom: `t` is not in "
            "scope for its `w`/`h` and the filter refuses to configure. Use "
            "compile_motion(), which picks `zoompan` for this case."
        )
    first = frames[0].window
    w = f"iw*{_num(first.w)}"
    h = f"ih*{_num(first.h)}"
    if is_static(frames):
        body = f"crop=w='{w}':h='{h}':x='iw*{_num(first.x)}':y='ih*{_num(first.y)}'"
        return body
    x = "iw*" + ramp([(k.t, k.window.x) for k in frames], "t")
    y = "ih*" + ramp([(k.t, k.window.y) for k in frames], "t")
    return f"{TIMEBASE_RESET},crop=w='{w}':h='{h}':x='{x}':y='{y}'"


def zoompan_fragment(keyframes: Sequence[Keyframe], *, output: Size, fps: float) -> str:
    """A path whose window size varies, compiled to ``zoompan``.

    Args:
        output: The delivery size. ``zoompan`` must be told one — it resamples
            the window to a fixed output rather than emitting the window's own
            pixels.
        fps: **The source's frame rate**, required rather than defaulted.
            ``zoompan``'s own default is 25, and passing the wrong one preserves
            the frame *count* while restamping it: 20 frames at 10 fps became 20
            frames at 25 fps, i.e. a 2.0 s clip silently became 0.8 s. A frame
            count check — the obvious check — passes in both cases.

    >>> zoompan_fragment(
    ...     [Keyframe(0, Window.full()), Keyframe(2, Window(0.25, 0.25, 0.5, 0.5))],
    ...     output=Size(1920, 1080), fps=30,
    ... )
    "zoompan=d=1:s=1920x1080:fps=30:z='1/(1+(-0.5)*min(max((in_time-0)/2,0),1))':x='iw*(0+(0.25)*min(max((in_time-0)/2,0),1))':y='ih*(0+(0.25)*min(max((in_time-0)/2,0),1))'"

    Raises:
        MotionError: If any window is not geometrically similar to the source
            frame. ``zoom`` is a single scalar, so the visible region is always
            ``(iw/zoom, ih/zoom)`` — one axis cannot be zoomed differently from
            the other, and honouring one while distorting the other silently is
            the failure this refuses.
    """
    frames = _check(keyframes)
    if fps <= 0:
        raise MotionError(f"fps must be positive; got {_num(fps)}")
    for i, k in enumerate(frames):
        if k.window.w < MIN_WINDOW_FRACTION - EPSILON:
            raise MotionError(
                f"keyframe {i} asks for a window {_num(k.window.w)} of the "
                f"frame, i.e. {_num(1 / k.window.w)}x magnification. `zoompan` "
                f"clamps zoom at {_num(MAX_ZOOM)} and does so SILENTLY — it "
                "would render a different framing, not a worse one. The "
                f"smallest window it can show is {_num(MIN_WINDOW_FRACTION)}."
            )
        if abs(k.window.w - k.window.h) > EPSILON:
            raise MotionError(
                f"keyframe {i}'s window is {_num(k.window.w)} x "
                f"{_num(k.window.h)} of the frame, so it is not the source's "
                "shape. `zoompan`'s zoom is one scalar: it can only show a "
                "window similar to the whole frame. Reframe first with a "
                "static crop, then move within it."
            )
    # zoom = 1/nw, and nw is what ramps. Dividing the ramp is exact at every
    # keyframe; ramping 1/nw directly would be exact at the keyframes too but
    # would interpolate the RECIPROCAL between them, which is a different — and
    # visibly non-linear — move.
    size = ramp([(k.t, k.window.w) for k in frames], "in_time")
    x = "iw*" + ramp([(k.t, k.window.x) for k in frames], "in_time")
    y = "ih*" + ramp([(k.t, k.window.y) for k in frames], "in_time")
    rate = _num(fps)
    return (
        f"zoompan=d=1:s={output.width}x{output.height}:fps={rate}:"
        f"z='1/{size}':x='{x}':y='{y}'"
    )


def compile_motion(
    keyframes: Sequence[Keyframe],
    *,
    output: Optional[Size] = None,
    fps: Optional[float] = None,
) -> str:
    """A camera path to an ffmpeg fragment, filter chosen by what the path does.

    The one entry point. Which filter is not a caller's decision, because it is
    not a matter of taste — it follows from whether the window's size varies,
    and getting it wrong is a configure-time error or a silent retime.

    A static window needs no clock:

    >>> compile_motion([Keyframe(0, Window(0, 0, 0.5, 0.5))])
    "crop=w='iw*0.5':h='ih*0.5':x='iw*0':y='ih*0'"

    A pan compiles to ``crop`` and needs nothing else:

    >>> print(compile_motion([
    ...     Keyframe(0.0, Window(0.0, 0.0, 0.5, 1.0)),
    ...     Keyframe(2.0, Window(0.5, 0.0, 0.5, 1.0)),
    ... ]))
    setpts=PTS-STARTPTS,crop=w='iw*0.5':h='ih*1':x='iw*(0+(0.5)*min(max((t-0)/2,0),1))':y='ih*0'

    A zoom compiles to ``zoompan``, and must be told the delivery size and the
    source's rate:

    >>> fragment = compile_motion(
    ...     [Keyframe(0, Window.full()), Keyframe(3, Window(0.1, 0.1, 0.8, 0.8))],
    ...     output=Size(1280, 720), fps=25,
    ... )
    >>> fragment.startswith("zoompan=d=1:s=1280x720:fps=25:")
    True

    Raises:
        MotionError: If a zoom is asked for without ``output`` and ``fps``.
            They are not defaultable: ``zoompan``'s own ``fps`` default retimes
            the clip, and there is no honest guess for a delivery size.
    """
    frames = _check(keyframes)
    if not zooms(frames):
        return crop_fragment(frames)
    missing = [
        name for name, value in (("output", output), ("fps", fps)) if value is None
    ]
    if missing:
        raise MotionError(
            f"this path zooms, so it compiles to `zoompan`, which needs "
            f"{' and '.join(missing)}. Neither is defaultable: zoompan's own "
            "fps default silently retimes the clip, and a delivery size cannot "
            "be guessed."
        )
    assert output is not None and fps is not None  # narrowed by `missing`
    return zoompan_fragment(frames, output=output, fps=fps)
