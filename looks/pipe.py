"""A plan that mixes backends, as a pipe — emitted as data, never spawned.

Some effects are filters and some are Python over raw frames. A plan holding
both cannot be one ffmpeg process, so it becomes a **pipe**: ffmpeg decodes and
filters, hands raw frames to a Python operation, and a second ffmpeg reads those
frames back and filters again.

This module produces that arrangement **as data** — argv lists a caller can run.
`looks` does not run it, and structurally cannot: `looks._run` refuses any argv
whose outputs are not `-f null -`, and both halves emitted here are refused by
it. That is asserted rather than assumed, because "we simply do not call it" is
a convention and a refusal is a mechanism.

## What is deliberately not emitted

**The codec, the container, the output path.** The encoder half stops at its
input contract and its filter chain. Encode settings are a delivery decision the
host owns — `muvid` pins `-video_track_timescale` for concat compatibility, and
a package that grew opinions about `-c:v` would be the second muvid. It also
means no module here contains an encoder spelling, which the package's own AST
perimeter scan enforces on every run.

## The fold, and the one place it is dangerous

Adjacent same-backend steps merge into one filter chain, and a filter run
*next to* a frame operation does not get its own process — it rides in the
`-vf` of the ffmpeg that already exists to feed or drain the pipe. That is what
makes a chain like Que Calor's one (decoder, encoder) pair rather than three
processes.

Folding into the **decoder** half is always safe: it reads a container and
inherits the host's filter timeline. Folding into the **encoder** half is not,
and this is rule 27:

    The encoder half reads `-f rawvideo`, which carries no timestamps at all.
    Its filter timeline restarts at 0.

So a step gated to "4 s to 5 s" fires on source frames 40-50 unfolded and on
**nothing at all** folded — exit 0, empty stderr, and a look that silently never
appears. Reproduced, and reproduced again with the rebase applied, which
restores a frame-for-frame identical result.

`looks` therefore **rebases what it can and refuses what it cannot**:

- A span carried structurally on :attr:`~looks.spec.Step.at` is one subtraction,
  and `looks` owns every expression it generates, so the rebase is exact.
- An `enable=` baked into a filter string by someone else is an arbitrary ffmpeg
  expression. Rewriting it would mean surgery on a grammar with no way to check
  the result, so it is refused by name.

And an undeclared origin is refused rather than assumed to be 0 — see
:attr:`~looks.spec.ClipSpec.origin_s`, which is where that fact lives.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from looks.spec import ClipSpec, LookPlan, Span, SpecError, Step

#: The raw pixel format the pipe carries. Packed 8-bit BGR: it is what the
#: frame kernels in this ecosystem already speak, and packing means a frame is
#: one contiguous ``width * height * 3`` read with no plane arithmetic.
DFLT_PIPE_PIX_FMT = "bgr24"

#: Bytes per pixel, by raw pixel format. A consumer sizes its reads from the
#: plan rather than from a constant it happens to agree on — rawvideo has no
#: header, so a wrong stride is a silently sheared picture rather than an error.
#: Only packed 8-bit formats are listed: a planar or higher-depth format has no
#: single bytes-per-pixel, so it is refused rather than approximated.
PIPE_BYTES_PER_PIXEL = {
    "bgr24": 3,
    "rgb24": 3,
    "gray": 1,
    "bgra": 4,
    "rgba": 4,
    "argb": 4,
    "abgr": 4,
}


class PipeError(SpecError):
    """A plan that cannot be arranged as a pipe, or not safely."""


@dataclass(frozen=True)
class FrameSegment:
    """One ffmpeg → Python → ffmpeg segment.

    Both argv are input-and-filter only. The caller appends its own encode
    settings and destination to :attr:`encode`.
    """

    op: str
    decode: tuple[str, ...]
    encode: tuple[str, ...]
    pix_fmt: str
    width: int
    height: int
    rate: float
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Frozen means frozen. Every other mapping-carrying dataclass in this
        # package copies and freezes; without it this one aliases the caller's
        # dict and `to_dict()` changes after the segment is built.
        from types import MappingProxyType

        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))

    @property
    def frame_bytes(self) -> int:
        """How many bytes one frame occupies on the pipe.

        rawvideo has no header, so a consumer that guesses this reads a sheared
        picture rather than an error.
        """
        return self.width * self.height * PIPE_BYTES_PER_PIXEL[self.pix_fmt]

    def to_dict(self) -> dict:
        return {
            "kind": "frame",
            "op": self.op,
            "decode": list(self.decode),
            "encode": list(self.encode),
            "pix_fmt": self.pix_fmt,
            "size": [self.width, self.height],
            "rate": self.rate,
            "frame_bytes": self.frame_bytes,
            "params": dict(self.params),
        }


@dataclass(frozen=True)
class FilterSegment:
    """A run of ffmpeg steps with no frame operation in it: one `-vf`."""

    vf: str

    def to_dict(self) -> dict:
        return {"kind": "filter", "vf": self.vf}


@dataclass(frozen=True)
class PipePlan:
    """The whole arrangement, as data.

    ``boundaries`` is the number of raw-frame crossings, which is the number
    that costs — each one is a full decode and re-encode. It is reported after
    folding, because counting runs before folding overstates it.
    """

    segments: tuple[Any, ...]
    boundaries: int
    source: Optional[str] = None

    def __len__(self) -> int:
        return len(self.segments)

    def __iter__(self):
        return iter(self.segments)

    def to_dict(self) -> dict:
        return {
            "schema": "looks.pipe/v1",
            "source": self.source,
            "boundaries": self.boundaries,
            "segments": [s.to_dict() for s in self.segments],
        }


def runs(plan: LookPlan) -> tuple[tuple[str, tuple[Step, ...]], ...]:
    """Maximal runs of consecutive steps sharing a backend.

    The first thing the fold needs, and worth its own name because "how many
    processes does this plan cost" is answered from it.

    >>> from looks.spec import LookPlan
    >>> runs(LookPlan())
    ()
    """
    out: list[tuple[str, list[Step]]] = []
    for step in plan.steps:
        backend = step.impl.backend
        if out and out[-1][0] == backend:
            out[-1][1].append(step)
        else:
            out.append((backend, [step]))
    return tuple((backend, tuple(steps)) for backend, steps in out)


def _rebased(step: Step, origin: float) -> Step:
    """A step's span moved from host-decoder time into pipe time.

    Only the structured span is touched. `looks` generates every ``enable=`` it
    emits from :attr:`Step.at` at read time, so moving the span moves the
    expression exactly — there is no string to parse and nothing to get wrong.
    """
    if step.at is None or origin == 0:
        return step
    start = None if step.at.start is None else step.at.start - origin
    end = None if step.at.end is None else step.at.end - origin
    return dataclasses.replace(step, at=Span(start, end))


def _refuse_foreign_gate(steps: Sequence[Step], where: str) -> None:
    """A gate baked into someone else's filter string cannot be rebased.

    Rewriting it would mean editing an arbitrary ffmpeg expression with no way
    to verify the result. Refusing costs a caller one static crop; guessing
    costs them a look that silently applies to the wrong frames.
    """
    for index, step in enumerate(steps):
        fragment = step.payload.get("filter") or ""
        if "enable=" in fragment:
            raise PipeError(
                f"step {index} ({step.effect!r}) carries an `enable=` inside its "
                f"own filter string, and {where} would rebase its time origin. "
                "`looks` rebases a span it generated and refuses one it did "
                "not: rewriting an arbitrary ffmpeg expression cannot be "
                "checked. Express the span as Effect.at instead."
            )


def _vf_of(steps: Sequence[Step]) -> str:
    from looks.ffmpeg import vf

    return vf(LookPlan(steps=tuple(steps)))


def piped_size(clip: ClipSpec, folded: Sequence[Step]) -> tuple[int, int]:
    """The frame size the decoder actually emits, after the folded chain.

    An effect that changes the frame's geometry declares ``out_size`` in its
    payload. That is a **contract**, not decoration: rawvideo has no header, so
    the size a consumer reads has to come from the plan, and an implementation
    that resizes without saying so makes the declared stride a lie.

    >>> from looks.spec import ClipSpec
    >>> piped_size(ClipSpec(width=640, height=480, fps=10), [])
    (640, 480)
    """
    width, height = clip.width, clip.height
    for step in folded:
        declared = step.payload.get("out_size")
        if declared:
            width, height = int(declared[0]), int(declared[1])
    return width, height


def _decoder(source: str, clip: ClipSpec, chain: str, pix_fmt: str) -> tuple[str, ...]:
    """ffmpeg reading the source and writing raw frames to stdout."""
    argv = ["ffmpeg", "-v", "error", "-i", source, "-an"]
    if chain:
        argv += ["-vf", chain]
    # NO `-s` here. After `-vf` it is an OUTPUT option, so it does not describe
    # the frames — it forces a rescale to that size, undoing any geometry folded
    # into the decode chain. Measured: `fit` to 320x240 folded in, then
    # `-s 640x480` scaled it straight back to the source size, silently. The
    # frame size out of a decoder is whatever its chain produces, and a consumer
    # reads it from the segment's declared width/height instead.
    argv += ["-f", "rawvideo", "-pix_fmt", pix_fmt, "-r", _rate(clip.fps), "-"]
    return tuple(argv)


def _encoder(clip: ClipSpec, chain: str, pix_fmt: str) -> tuple[str, ...]:
    """ffmpeg reading raw frames from stdin — input contract and filters only.

    The rate is declared explicitly and derived from the clip, never omitted:
    the rawvideo demuxer defaults to 25, which would rescale every time-based
    expression in the folded chain without saying so.
    """
    argv = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        pix_fmt,
        "-s",
        f"{clip.width}x{clip.height}",
        "-r",
        _rate(clip.fps),
        "-i",
        "-",
    ]
    if chain:
        argv += ["-vf", chain]
    return tuple(argv)


def _rate(fps: float) -> str:
    text = f"{fps:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def pipe_plan(
    plan: LookPlan,
    *,
    source: str,
    clip: Optional[ClipSpec] = None,
    pix_fmt: str = DFLT_PIPE_PIX_FMT,
) -> PipePlan:
    """Arrange a compiled plan as processes — emitted as data, never started.

    Args:
        source: What the first decoder reads. Passed through verbatim; `looks`
            does not open it.
        clip: The clip the plan was compiled against. Defaults to the plan's own.

    Raises:
        PipeError: If the plan needs a raw-frame boundary and cannot be arranged
            safely across it — an undeclared time origin under a gated step, or
            a gate baked into a filter string.

    Examples:
        A plan of pure ffmpeg steps is one segment and costs no boundary. The
        plan is built here by hand rather than compiled, so the example needs no
        ffmpeg — a doctest that needs a binary is a doctest CI does not run.

        >>> from looks.licence import Tier, terms_for
        >>> from looks.spec import ImplRef, LookPlan, Step
        >>> impl = ImplRef(effect='blur', impl='blur.ffmpeg.gblur',
        ...                backend='ffmpeg', terms=terms_for('ffmpeg')[0])
        >>> plan = LookPlan(steps=(Step(effect='blur', impl=impl,
        ...     tier=Tier.COPYLEFT_TOOL, payload={'filter': 'gblur=sigma=2'}),))
        >>> arranged = pipe_plan(plan, source='in.mp4')
        >>> len(arranged), arranged.boundaries
        (1, 0)
    """
    if pix_fmt not in PIPE_BYTES_PER_PIXEL:
        raise PipeError(
            f"{pix_fmt!r} has no single bytes-per-pixel this module can declare "
            f"(known: {sorted(PIPE_BYTES_PER_PIXEL)}). rawvideo carries no "
            "header, so a consumer reads the stride from the plan — and a "
            "planar or higher-depth format would make that number a guess."
        )
    clip = plan.clip if clip is None else clip
    grouped = runs(plan)
    if not grouped:
        return PipePlan(segments=(), boundaries=0, source=source)

    frame_runs = [i for i, (backend, _) in enumerate(grouped) if backend == "frame"]
    if not frame_runs:
        return PipePlan(
            segments=(FilterSegment(vf=_vf_of(plan.steps)),),
            boundaries=0,
            source=source,
        )
    if clip is None:
        raise PipeError(
            "a pipe needs a ClipSpec: the raw frames on it have no header, so "
            "their size and rate have to be declared or the reader guesses."
        )

    segments: list[Any] = []
    index = 0
    for position, run_index in enumerate(frame_runs):
        backend, frame_steps = grouped[run_index]
        if len(frame_steps) > 1:
            raise PipeError(
                f"{len(frame_steps)} frame operations run back to back "
                f"({[s.effect for s in frame_steps]}). Each is a separate "
                "process on this pipe; compose them into one registered "
                "operation instead, or the frames cross Python twice for "
                "nothing."
            )
        before = [s for _, steps in grouped[index:run_index] for s in steps]
        after_index = (
            frame_runs[position + 1] if position + 1 < len(frame_runs) else len(grouped)
        )
        after = [s for _, steps in grouped[run_index + 1 : after_index] for s in steps]

        # Folding into the DECODER is always safe — it reads a container and
        # keeps the host's timeline. Nothing to rebase, nothing to refuse.
        decode_chain = _vf_of(before) if before else ""

        # Folding into the ENCODER crosses the raw-frame boundary, where the
        # timeline restarts at 0. This is rule 27.
        if after:
            # UNCONDITIONAL. An author who bakes a gate into a filter string is
            # by construction NOT using `Effect.at`, so `at is None` is the
            # NORMAL case for exactly the population this refuses. Running it
            # only when some unrelated sibling happened to carry a span made the
            # guard fire on a coincidence rather than on the hazard — measured:
            # the foreign gate folded through un-rebased and moved a look by 20
            # frames at exit 0.
            _refuse_foreign_gate(after, "folding into the encoder half")
            # A Span open at BOTH ends bounds nothing — `gated()` emits no
            # `enable=` for it and `_rebased` cannot move it — so it must not
            # demand an origin it provably cannot use.
            gated = [
                s
                for s in after
                if s.at is not None and not (s.at.start is None and s.at.end is None)
            ]
            if gated:
                if clip.origin_s is None:
                    raise PipeError(
                        f"{len(gated)} step(s) after the frame operation carry a "
                        "span, and folding them into the encoder half rebases "
                        "their time origin — the encoder reads rawvideo, which "
                        "has no timestamps, so its timeline restarts at 0. "
                        "Declare ClipSpec.origin_s (the source time of this "
                        "part's frame 0 as the host's decoder sees it). It is "
                        "not assumed to be 0: that is right for an input-side "
                        "seek and wrong for an output-side one, and the "
                        "difference is a look on the wrong frames with no error."
                    )
            after = [_rebased(s, clip.origin_s or 0.0) for s in after]
        encode_chain = _vf_of(after) if after else ""

        width, height = piped_size(clip, before)
        piped = dataclasses.replace(clip, width=width, height=height)
        segments.append(
            FrameSegment(
                op=frame_steps[0].payload.get("op", frame_steps[0].impl.impl),
                decode=_decoder(
                    source if position == 0 else "-", clip, decode_chain, pix_fmt
                ),
                encode=_encoder(piped, encode_chain, pix_fmt),
                pix_fmt=pix_fmt,
                width=width,
                height=height,
                rate=clip.fps,
                params=dict(frame_steps[0].params),
            )
        )
        index = after_index
    return PipePlan(segments=tuple(segments), boundaries=len(segments), source=source)


def describe(arranged: PipePlan) -> str:
    """The arrangement as a few lines — what will run, and what it costs."""
    if not arranged.segments:
        return "(empty pipe)"
    lines = []
    for i, segment in enumerate(arranged.segments):
        if isinstance(segment, FilterSegment):
            lines.append(f"{i}. one ffmpeg process: -vf {segment.vf[:70]}")
        else:
            lines.append(
                f"{i}. decode -> {segment.op} -> encode "
                f"({segment.width}x{segment.height} {segment.pix_fmt} "
                f"@{_rate(segment.rate)}, {segment.frame_bytes} B/frame)"
            )
    lines.append(
        f"raw-frame boundaries: {arranged.boundaries}"
        + (" (none: one process)" if arranged.boundaries == 0 else "")
    )
    return "\n".join(lines)
