"""Where a source frame lands inside a target frame. Pure arithmetic.

No I/O, no media library, no ffmpeg, no numpy. Every function here is total:
give it two sizes and a mode and it answers, with no file open and nothing
decoded. That is what lets one answer drive an ffmpeg filter chain, a moviepy
composite, a CSS ``object-fit`` preview, or a cost estimate — and it is why the
geometry tier can be a *spec* rather than a call.

**The rounding rule is part of the answer, not an implementation detail.**
`mixing` and moviepy truncate; ffmpeg's ``force_original_aspect_ratio`` rounds.
On real inputs they disagree: 1920x1080 into 1080x1920 gives ``1080/(16/9) =
607.5``, which truncates to **607** and rounds to **608**. One pixel row, and a
total black-to-white difference at the seam. A spec whose rendered result
depends on which backend read it is not a spec, so the rule travels inside the
:class:`Placement`.

The three modes are the ones `mixing` already had, and they answer three
different questions:

- ``stretch`` — fill the target exactly, distorting. The only mode that changes
  the aspect ratio.
- ``fit`` — the whole source is visible; the target is padded. Nothing is lost.
- ``fill`` — the target is covered; the source is cropped. Nothing is padded.

`mixing`'s fourth, ``social``, is not a fourth mode: it is ``fit`` with a
blurred, dimmed copy of the source behind it instead of a solid colour. That is
a :class:`Backdrop`, and separating the two is what lets a caller put a blurred
backdrop behind a ``fill`` or a solid colour behind a ``social`` layout without
a fifth mode appearing.

    >>> placement(Size(1920, 1080), Size(1080, 1920), mode="fit").scale
    Size(width=1080, height=607)
    >>> placement(Size(1920, 1080), Size(1080, 1920), mode="fit",
    ...           rounding="round").scale
    Size(width=1080, height=608)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Union

FitMode = Literal["stretch", "fit", "fill"]
Rounding = Literal["floor", "round"]

#: ``"floor"`` reproduces ``mixing.resize_to_dimensions`` pixel-for-pixel;
#: ``"round"`` reproduces ffmpeg's ``force_original_aspect_ratio``. Floor is the
#: default because it is what the fleet's existing renders were made with, and a
#: silent one-pixel change to every previously-rendered frame is not an
#: improvement.
DFLT_ROUNDING: Rounding = "floor"

#: Backdrop defaults, transcribed from ``mixing.resize_to_dimensions``'s
#: ``method="social"`` branch so the extracted version reproduces it.
DFLT_BACKDROP_BLUR_SIGMA = 15.0
DFLT_BACKDROP_DIM = 0.7

#: Named target sizes. Kept because callers ask for "a YouTube Short", not for
#: 1080x1920 — but see :func:`social_size`: these are a *convenience over*
#: :class:`Size`, never a parallel vocabulary. Nothing in this module takes a
#: preset name; they resolve to a `Size` at the boundary.
SOCIAL_SIZES: dict[str, tuple[int, int]] = {
    "youtube": (1920, 1080),
    "shorts": (1080, 1920),
    "square": (1080, 1080),
    "story": (1080, 1920),
    "tiktok": (1080, 1920),
}


class GeometryError(ValueError):
    """A size or mode that cannot produce a placement."""


@dataclass(frozen=True)
class Size:
    """A pixel size. :attr:`aspect` is width/height, never the other way round.

    Examples:
        >>> Size(1920, 1080).aspect
        1.7777777777777777
        >>> Size(0, 10)
        Traceback (most recent call last):
        ...
        looks.geometry.GeometryError: a Size must be positive, got 0x10
    """

    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise GeometryError(
                f"a Size must be positive, got {self.width}x{self.height}"
            )

    @property
    def aspect(self) -> float:
        return self.width / self.height


@dataclass(frozen=True)
class Box:
    """An axis-aligned pixel box, top-left origin, y downwards.

    Deliberately **not** ``burns.Rect``: that one is normalised to ``[0, 1]``
    over a source image and interpolates over time. This one is integer pixels
    in one frame and does not move. The distinction is the same one that keeps
    the two packages apart — ``burns`` owns *authored* geometry over time,
    ``looks`` owns geometry *derived* from a pair of sizes.

    Examples:
        >>> Box(240, 0, 1439, 1080).size
        Size(width=1439, height=1080)
    """

    x: int
    y: int
    width: int
    height: int

    @property
    def size(self) -> Size:
        return Size(self.width, self.height)


@dataclass(frozen=True)
class Solid:
    """A flat colour behind the placed frame.

    Examples:
        >>> Solid().rgb
        (0, 0, 0)
    """

    rgb: tuple[int, int, int] = (0, 0, 0)


@dataclass(frozen=True)
class Blurred:
    """A blurred, dimmed copy of the source, scaled to cover — the "social" look.

    This is `mixing`'s ``method="social"``, separated from the fit mode so that
    the two compose. Its defaults reproduce that branch.

    Examples:
        >>> Blurred().sigma, Blurred().dim
        (15.0, 0.7)
    """

    sigma: float = DFLT_BACKDROP_BLUR_SIGMA
    dim: float = DFLT_BACKDROP_DIM


Backdrop = Union[Solid, Blurred]
"""What fills the part of the target the placed frame does not cover."""


def _resolve(value: float, rounding: Rounding) -> int:
    if rounding == "floor":
        return int(value)
    if rounding == "round":
        return int(round(value))
    raise GeometryError(f"unknown rounding {rounding!r}; use 'floor' or 'round'")


def scaled_size(
    source: Size,
    target: Size,
    *,
    mode: FitMode = "fit",
    rounding: Rounding = DFLT_ROUNDING,
) -> Size:
    """The size the source is scaled to, before any crop or pad.

    Examples:
        >>> scaled_size(Size(1920, 1080), Size(1080, 1920), mode="fit")
        Size(width=1080, height=607)

        The rounding rule is visible right here, on an ordinary input — this is
        the 607-versus-608 disagreement, not a contrived case:

        >>> scaled_size(Size(1920, 1080), Size(1080, 1920), mode="fit",
        ...             rounding="round")
        Size(width=1080, height=608)

        ``fill`` covers instead of fitting, so it goes the other way:

        >>> scaled_size(Size(1920, 1080), Size(1080, 1920), mode="fill")
        Size(width=3413, height=1920)

        ``stretch`` is the target, by definition:

        >>> scaled_size(Size(1920, 1080), Size(1080, 1920), mode="stretch")
        Size(width=1080, height=1920)
    """
    if mode == "stretch":
        return target
    if mode not in ("fit", "fill"):
        raise GeometryError(f"unknown mode {mode!r}; use 'stretch', 'fit' or 'fill'")
    wider = source.aspect > target.aspect
    # `fit` matches the constraining axis; `fill` matches the other one.
    match_width = wider if mode == "fit" else not wider
    if match_width:
        return Size(target.width, _resolve(target.width / source.aspect, rounding))
    return Size(_resolve(target.height * source.aspect, rounding), target.height)


def center_box(inner: Size, outer: Size) -> Box:
    """``inner`` centred in ``outer``, halving with the floor `mixing` used.

    Examples:
        >>> center_box(Size(1439, 1080), Size(1920, 1080))
        Box(x=240, y=0, width=1439, height=1080)

        An odd leftover goes to the right/bottom, because the offset floors:

        >>> center_box(Size(3, 1), Size(4, 1))
        Box(x=0, y=0, width=3, height=1)
    """
    return Box(
        x=(outer.width - inner.width) // 2,
        y=(outer.height - inner.height) // 2,
        width=inner.width,
        height=inner.height,
    )


@dataclass(frozen=True)
class Placement:
    """Scale the source to :attr:`scale`, take :attr:`crop` out, put it at :attr:`offset`.

    :attr:`crop` and :attr:`offset` are ``None`` when that pass is a no-op, so a
    backend emits nothing for it rather than an identity filter. That matters
    for more than tidiness: an identity ``scale`` still resamples, and a chain
    that resamples when it did not need to loses detail for free.

    :attr:`rounding` is carried, not assumed — see the module docstring.

    Examples:
        >>> p = placement(Size(641, 481), Size(1920, 1080), mode="fill")
        >>> p.scale
        Size(width=1920, height=1440)
        >>> p.crop
        Box(x=0, y=180, width=1920, height=1080)
        >>> p.offset is None
        True
    """

    source: Size
    target: Size
    scale: Size
    crop: Optional[Box] = None
    offset: Optional[tuple[int, int]] = None
    rounding: Rounding = DFLT_ROUNDING

    @property
    def resamples(self) -> bool:
        """Whether this placement actually changes the pixel grid.

        Examples:
            >>> placement(Size(64, 36), Size(64, 36)).resamples
            False
            >>> placement(Size(64, 36), Size(128, 72)).resamples
            True
        """
        return self.scale != self.source


def placement(
    source: Size,
    target: Size,
    *,
    mode: FitMode = "fit",
    rounding: Rounding = DFLT_ROUNDING,
) -> Placement:
    """The full geometric answer for one clip.

    ``fit`` pads and never crops; ``fill`` crops and never pads; ``stretch``
    does neither.

    Examples:
        A portrait source into a landscape frame, fitted — padded left/right:

        >>> p = placement(Size(480, 850), Size(1280, 720))
        >>> p.scale, p.crop, p.offset
        (Size(width=406, height=720), None, (437, 0))

        The same pair, filled — cropped top/bottom, nothing padded:

        >>> p = placement(Size(480, 850), Size(1280, 720), mode="fill")
        >>> p.scale, p.crop, p.offset
        (Size(width=1280, height=2266), Box(x=0, y=773, width=1280, height=720), None)

        Same size in and out: nothing happens at all.

        >>> p = placement(Size(1280, 720), Size(1280, 720))
        >>> p.scale, p.crop, p.offset, p.resamples
        (Size(width=1280, height=720), None, None, False)
    """
    scale = scaled_size(source, target, mode=mode, rounding=rounding)
    crop: Optional[Box] = None
    offset: Optional[tuple[int, int]] = None
    if scale.width > target.width or scale.height > target.height:
        box = center_box(target, scale)
        crop = box
    if scale.width < target.width or scale.height < target.height:
        box = center_box(scale, target)
        offset = (box.x, box.y)
    return Placement(
        source=source,
        target=target,
        scale=scale,
        crop=crop,
        offset=offset,
        rounding=rounding,
    )


@dataclass(frozen=True)
class Reframe:
    """A placement plus what fills the part of the target it does not cover.

    This is the shape a ``Look`` stores: geometry is a spec, and a spec has to
    say what the empty region contains, or two backends will disagree about it.

    Examples:
        >>> r = reframe(Size(480, 850), Size(1280, 720))
        >>> r.placement.offset, r.backdrop
        ((437, 0), Solid(rgb=(0, 0, 0)))
        >>> reframe(Size(480, 850), Size(1280, 720), backdrop=Blurred()).backdrop
        Blurred(sigma=15.0, dim=0.7)
    """

    placement: Placement
    backdrop: Backdrop = field(default_factory=Solid)


def reframe(
    source: Size,
    target: Size,
    *,
    mode: FitMode = "fit",
    backdrop: Optional[Backdrop] = None,
    rounding: Rounding = DFLT_ROUNDING,
) -> Reframe:
    """:func:`placement` plus a backdrop."""
    return Reframe(
        placement=placement(source, target, mode=mode, rounding=rounding),
        backdrop=Solid() if backdrop is None else backdrop,
    )


def social_size(name: str) -> Size:
    """Resolve a :data:`SOCIAL_SIZES` preset name.

    A convenience over :class:`Size`, never a parallel vocabulary — nothing else
    in this module accepts a preset name, so a preset cannot acquire behaviour
    of its own.

    Examples:
        >>> social_size('shorts')
        Size(width=1080, height=1920)
        >>> social_size('myspace')
        Traceback (most recent call last):
        ...
        looks.geometry.GeometryError: unknown size preset 'myspace'; known: ...
    """
    if name not in SOCIAL_SIZES:
        known = ", ".join(sorted(SOCIAL_SIZES))
        raise GeometryError(f"unknown size preset {name!r}; known: {known}")
    return Size(*SOCIAL_SIZES[name])


def snap_even(size: Size) -> Size:
    """Both axes rounded **down** to even — the yuv420p requirement.

    H.264 in yuv420p subsamples chroma 2x2, so an odd dimension is not
    encodable. Down rather than up, so the result never exceeds a target the
    caller asked for.

    Examples:
        >>> snap_even(Size(1439, 1081))
        Size(width=1438, height=1080)
        >>> snap_even(Size(1920, 1080))
        Size(width=1920, height=1080)
    """
    return Size(size.width - size.width % 2, size.height - size.height % 2)


def ffmpeg_chain(placement: Placement, *, backdrop: Backdrop = None) -> str:  # type: ignore[assignment]
    """The resolved ``scale,crop,pad`` chain for one placement.

    **Resolved, not deferred.** ffmpeg can express fit and fill without knowing
    the source size, via ``scale=W:H:force_original_aspect_ratio=decrease``, and
    that form is nearly identical — but *nearly* is the problem: it rounds where
    this floors, so 1920x1080 into 1080x1920 differs by one row and the seam
    goes black-to-white. More fundamentally, a placement that does not know its
    source size cannot be inspected or diffed, which is the premise of the whole
    package. Resolve against the clip, then emit.

    Only a solid backdrop is emitted here; a :class:`Blurred` backdrop needs a
    second copy of the input and therefore a two-branch graph, which is the
    compiler's business rather than this function's.

    Examples:
        >>> p = placement(Size(480, 850), Size(1280, 720))
        >>> ffmpeg_chain(p)
        'scale=406:720,pad=1280:720:437:0:color=0x000000'

        Filling crops instead of padding:

        >>> p = placement(Size(480, 850), Size(1280, 720), mode="fill")
        >>> ffmpeg_chain(p)
        'scale=1280:2266,crop=1280:720:0:773'

        A no-op placement emits a no-op chain, not an identity scale:

        >>> ffmpeg_chain(placement(Size(1280, 720), Size(1280, 720)))
        ''
    """
    parts: list[str] = []
    if placement.resamples:
        parts.append(f"scale={placement.scale.width}:{placement.scale.height}")
    if placement.crop is not None:
        c = placement.crop
        parts.append(f"crop={c.width}:{c.height}:{c.x}:{c.y}")
    if placement.offset is not None:
        x, y = placement.offset
        bd = Solid() if backdrop is None else backdrop
        if isinstance(bd, Blurred):
            raise GeometryError(
                "a Blurred backdrop needs a second input branch; compile it as a "
                "two-branch graph rather than a single -vf chain"
            )
        colour = "0x%02X%02X%02X" % bd.rgb
        parts.append(
            f"pad={placement.target.width}:{placement.target.height}:{x}:{y}:color={colour}"
        )
    return ",".join(parts)
