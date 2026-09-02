"""Gradient-map 3D LUTs: a colour ramp in, an Iridas ``.cube`` out.

A **gradient map** replaces a pixel's colour with a colour looked up by its
*lightness* alone. It is the right vehicle when a reference's hue tracks its
lightness — dark to oxblood, mid to crimson, light to coral — and it is the
wrong one otherwise, which is why the first step is always to measure the
reference rather than assume a filter.

Two properties make it the tool for video specifically:

- **It cannot flicker.** The mapping is per-pixel and stateless, so frame *n*
  and frame *n+1* are transformed by the identical function. That is the
  failure mode of every per-frame palette quantiser and of the non-commercial
  cartoon GANs, and it is bought here for free rather than defended against.
  Measured on the first real look, frame-to-frame change came out at
  0.89–1.12x the *source's own*, i.e. the chain adds none.
- **It is `lut3d`, which is LGPL.** The obvious alternative for a
  colour-shaping pass is `eq`, and `eq` exists only in a GPL build. So the look
  that ships is also the one that is portable.

Two lessons from building the first real look are baked into the defaults and
the validation here, because both cost real work to learn:

- **Do not end the ramp at black.** A first version crushed 16.2% of pixels to
  L\\* 0–5 where the measured reference had 0.3%; the reference's floor was an
  oxblood at L\\* 8.22, never black. Setting the dark anchor to the reference's
  own measured value took the histogram distance from 46.7 to 32.0 pp. So
  :func:`gradient_map` warns when a ramp's darkest stop sits below
  :data:`SHADOW_FLOOR_WARN_L`, and the default ramps do not go near it.
- **Accents must survive.** A pure ramp erases every hue distinction, including
  ones the reference keeps. The first look kept warm accents (9.35% of pixels,
  every one warm) through a second, hue-keyed ramp blended in by saturation and
  hue proximity — :class:`Accent` here.

Everything is stdlib. The full 33³ lattice takes ~22 ms in pure Python, so the
headline capability needs no numpy and lives in the zero-dependency tier. The
resulting file is ~950 KB, which is why a `.cube` is **generated into a cache
keyed by the ramp's content**, never committed: the ramp is the spec, the file
is a build artifact.

    >>> ramp = Ramp.from_hex([(0.0, '#1B0610'), (50.0, '#D5254A'), (100.0, '#FEF0DC')])
    >>> text = cube_text(ramp, size=2)
    >>> text.splitlines()[1]
    'LUT_3D_SIZE 2'
    >>> len(text.splitlines()) - 5          # header lines are 5
    8
"""

from __future__ import annotations

import hashlib
import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

#: Lightness of the darkest stop below which :func:`gradient_map` warns. The
#: measured reference's own floor was L* 8.22; a ramp reaching L* 3.6 crushed
#: 16.2% of pixels into the bottom bin where the reference had 0.3%.
SHADOW_FLOOR_WARN_L = 5.0

#: Default lattice edge length. 33 is what Resolve, Premiere and ffmpeg's
#: `lut3d` all handle natively and is the de-facto interchange size; 17 is
#: visibly banded on a smooth ramp, 65 is 8x the file for no visible gain.
DFLT_CUBE_SIZE = 33

#: Accent weights below this are snapped to exactly 0.0. The hue window is a
#: Gaussian, so it never truly reaches zero — a blue pixel against a warm accent
#: scores ~7e-33, which is float noise rather than a blend. Snapping matters
#: because `weight() == 0.0` is the predicate :class:`GradientMap` uses to skip
#: the accent lookup entirely, and a predicate that is never true costs a second
#: ramp evaluation on every one of 35,937 lattice points.
NEGLIGIBLE_WEIGHT = 1e-9

#: Rec.709 luminance weights, used to get a linear Y before the L* transfer.
_LUMA_709 = (0.2126, 0.7152, 0.0722)

#: The CIE L* transfer's break point and slope (the standard 6/29 cubed form).
_LAB_EPS = 216 / 24389
_LAB_KAPPA = 24389 / 27

Rgb = tuple[float, float, float]
"""A colour as three floats in ``[0, 1]``, sRGB-encoded (not linear)."""


class LutError(ValueError):
    """A ramp or lattice that cannot produce a usable LUT."""


def hex_to_rgb(value: str) -> Rgb:
    """``'#RRGGBB'`` (or ``'RRGGBB'``) to three floats in ``[0, 1]``.

    Examples:
        >>> hex_to_rgb('#FFFFFF')
        (1.0, 1.0, 1.0)
        >>> hex_to_rgb('000000')
        (0.0, 0.0, 0.0)
        >>> tuple(round(c, 4) for c in hex_to_rgb('#D5254A'))
        (0.8353, 0.1451, 0.2902)
        >>> hex_to_rgb('#12345')
        Traceback (most recent call last):
        ...
        looks.lut.LutError: not a 6-digit hex colour: '#12345'
    """
    s = value.lstrip("#")
    if len(s) != 6:
        raise LutError(f"not a 6-digit hex colour: {value!r}")
    try:
        return tuple(int(s[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as e:
        raise LutError(f"not a 6-digit hex colour: {value!r}") from e


def rgb_to_hex(rgb: Rgb) -> str:
    """Three floats in ``[0, 1]`` back to ``'#RRGGBB'``.

    Examples:
        >>> rgb_to_hex((1.0, 1.0, 1.0))
        '#FFFFFF'
        >>> rgb_to_hex((0.8353, 0.1451, 0.2902))
        '#D5254A'
    """
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02X}" for c in rgb)


def srgb_to_linear(c: float) -> float:
    """The sRGB electro-optical transfer function.

    Examples:
        >>> srgb_to_linear(0.0)
        0.0
        >>> srgb_to_linear(1.0)
        1.0
        >>> round(srgb_to_linear(0.5), 4)
        0.214
    """
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    """Inverse of :func:`srgb_to_linear`.

    Examples:
        >>> round(linear_to_srgb(srgb_to_linear(0.37)), 6)
        0.37
    """
    return c * 12.92 if c <= 0.0031308 else 1.055 * max(c, 0.0) ** (1 / 2.4) - 0.055


def grey_at(level: float) -> float:
    """The sRGB grey whose CIE ``L*`` is ``level`` — the inverse of :func:`lightness`.

    Examples:
        >>> round(grey_at(0.0), 6)
        0.0
        >>> round(grey_at(100.0), 6)
        1.0
        >>> round(lightness((grey_at(53.39),) * 3), 2)
        53.39
    """
    lv = max(0.0, min(100.0, level))
    f = (lv + 16) / 116
    y = f**3 if f**3 > _LAB_EPS else (116 * f - 16) / _LAB_KAPPA
    return max(0.0, min(1.0, linear_to_srgb(y)))


def lightness(rgb: Rgb) -> float:
    """CIE ``L*`` in ``[0, 100]`` for an sRGB colour.

    This is the axis a gradient map indexes on, and it is deliberately
    *perceptual* rather than a naive ``(r+g+b)/3`` or a coded-Y average: the
    whole point of the map is that the output's lightness ordering matches what
    a viewer sees, and the two disagree most on saturated colour, which is
    exactly where an extreme look lives.

    Examples:
        >>> round(lightness((0.0, 0.0, 0.0)), 4)
        0.0
        >>> round(lightness((1.0, 1.0, 1.0)), 4)
        100.0
        >>> round(lightness((0.5, 0.5, 0.5)), 2)
        53.39
    """
    y = sum(w * srgb_to_linear(c) for w, c in zip(_LUMA_709, rgb))
    f = y ** (1 / 3) if y > _LAB_EPS else (_LAB_KAPPA * y + 16) / 116
    return 116 * f - 16


def _hue_saturation(rgb: Rgb) -> tuple[float, float]:
    """HSV hue in degrees and saturation in ``[0, 1]``.

    Used only to key the accent channel — the ramp itself never looks at hue.
    """
    r, g, b = rgb
    hi, lo = max(rgb), min(rgb)
    delta = hi - lo
    sat = 0.0 if hi <= 1e-9 else delta / hi
    if delta <= 1e-9:
        return 0.0, sat
    if hi == r:
        h = ((g - b) / delta) % 6
    elif hi == g:
        h = ((b - r) / delta) + 2
    else:
        h = ((r - g) / delta) + 4
    return (h * 60.0) % 360.0, sat


@dataclass(frozen=True)
class Accent:
    """A second ramp for colours the main ramp should not flatten.

    A pure gradient map erases every hue distinction. When the reference keeps
    one — the first real look kept warm accents, 9.35% of pixels and every one
    warm — a second ramp is blended in, weighted by how saturated the source
    pixel is and how close its hue sits to :attr:`hue`.

    Attributes:
        ramp: The colours this accent maps to, indexed by lightness exactly as
            the main ramp is.
        hue: Centre of the hue band to rescue, in degrees.
        hue_width: Gaussian sigma of the hue window, in degrees.
        min_saturation: Below this saturation, weight is zero — an accent keyed
            on hue alone would recolour every near-grey pixel whose hue is
            numerically nearby but perceptually meaningless.
        saturation_soft: Saturation range over which weight ramps from 0 to 1.
        strength: Maximum blend weight, in ``[0, 1]``.
    """

    ramp: "Ramp"
    hue: float = 52.0
    hue_width: float = 14.0
    min_saturation: float = 0.42
    saturation_soft: float = 0.30
    strength: float = 0.70

    def weight(self, rgb: Rgb) -> float:
        """Blend weight for one source colour, in ``[0, strength]``.

        Examples:
            >>> gold = Ramp.from_hex([(0.0, '#2A1206'), (100.0, '#FEF6DF')])
            >>> a = Accent(ramp=gold)
            >>> round(a.weight((0.95, 0.82, 0.15)), 3)      # a saturated amber
            0.695
            >>> a.weight((0.5, 0.5, 0.5))                   # grey: no hue to rescue
            0.0
            >>> a.weight((0.15, 0.30, 0.65))                # blue: outside the band
            0.0
        """
        hue, sat = _hue_saturation(rgb)
        sat_w = (sat - self.min_saturation) / self.saturation_soft
        sat_w = max(0.0, min(1.0, sat_w))
        if sat_w == 0.0:
            return 0.0
        delta_h = ((hue - self.hue + 180.0) % 360.0) - 180.0
        hue_w = math.exp(-0.5 * (delta_h / self.hue_width) ** 2)
        w = sat_w * hue_w * self.strength
        return 0.0 if w < NEGLIGIBLE_WEIGHT else w


@dataclass(frozen=True)
class Ramp:
    """Colours ordered by lightness — the whole specification of a gradient map.

    Attributes:
        stops: ``(L*, rgb)`` pairs, strictly increasing in ``L*``, at least two.
            ``L*`` outside a stop's range clamps to the nearest end.

    Examples:
        >>> r = Ramp.from_hex([(0.0, '#000000'), (100.0, '#FFFFFF')])
        >>> rgb_to_hex(r.at(50.0))
        '#808080'
        >>> rgb_to_hex(r.at(-10.0))     # clamps
        '#000000'
    """

    stops: tuple[tuple[float, Rgb], ...]

    def __post_init__(self) -> None:
        if len(self.stops) < 2:
            raise LutError(f"a ramp needs at least two stops, got {len(self.stops)}")
        levels = [lv for lv, _ in self.stops]
        if any(b <= a for a, b in zip(levels, levels[1:])):
            raise LutError(f"ramp stops must strictly increase in L*, got {levels}")
        if not (0.0 <= levels[0] and levels[-1] <= 100.0):
            raise LutError(f"ramp stops must lie in [0, 100], got {levels}")

    @classmethod
    def from_hex(cls, stops: Sequence[tuple[float, str]]) -> "Ramp":
        """Build from ``(L*, '#RRGGBB')`` pairs.

        Examples:
            >>> Ramp.from_hex([(0.0, '#000000'), (100.0, '#FFFFFF')]).stops[1][1]
            (1.0, 1.0, 1.0)
        """
        return cls(stops=tuple((float(lv), hex_to_rgb(h)) for lv, h in stops))

    @classmethod
    def neutral(cls, *, stops: int = 32) -> "Ramp":
        r"""A ramp that is a true identity on greys.

        **A two-stop black-to-white ramp is NOT an identity, and that surprises
        people.** A ramp interpolates its stop colours in *sRGB* while indexing
        on *L\**, and those two curves are not the same one: mid-grey sRGB 0.5
        is L\* 53.39, so a naive ``[(0, black), (100, white)]`` ramp returns
        sRGB 0.5339 for it. Measured through ffmpeg, that is an **8/255 shift at
        every lattice size** — 17, 33 and 65 alike, which is how you know it is
        systematic rather than interpolation error, and it peaks in the
        midtones rather than the shadows.

        This samples the inverse transfer instead, so greys survive. Use it as
        the smoke test for any LUT pipeline: an identity that is not an identity
        means the transfer or the lattice order is wrong.

        Examples:
            >>> r = Ramp.neutral()
            >>> rgb_to_hex(r.at(lightness((0.5, 0.5, 0.5))))
            '#808080'
            >>> rgb_to_hex(r.at(0.0)), rgb_to_hex(r.at(100.0))
            ('#000000', '#FFFFFF')
        """
        if stops < 2:
            raise LutError(f"a neutral ramp needs at least two stops, got {stops}")
        levels = [i * 100.0 / (stops - 1) for i in range(stops)]
        return cls(stops=tuple((lv, (grey_at(lv),) * 3) for lv in levels))

    @property
    def darkest(self) -> float:
        """``L*`` of the darkest stop.

        Examples:
            >>> Ramp.from_hex([(8.2, '#2E0C18'), (100.0, '#FEF0DC')]).darkest
            8.2
        """
        return self.stops[0][0]

    def at(self, level: float) -> Rgb:
        """The ramp colour at ``L*``, linearly interpolated, clamped at the ends.

        Examples:
            >>> r = Ramp.from_hex([(0.0, '#000000'), (50.0, '#FF0000'), (100.0, '#FFFFFF')])
            >>> rgb_to_hex(r.at(25.0))
            '#800000'
            >>> rgb_to_hex(r.at(75.0))
            '#FF8080'
        """
        stops = self.stops
        if level <= stops[0][0]:
            return stops[0][1]
        if level >= stops[-1][0]:
            return stops[-1][1]
        for (l0, c0), (l1, c1) in zip(stops, stops[1:]):
            if l0 <= level <= l1:
                t = 0.0 if l1 == l0 else (level - l0) / (l1 - l0)
                return tuple(a + (b - a) * t for a, b in zip(c0, c1))  # type: ignore[return-value]
        return stops[-1][1]  # pragma: no cover - unreachable given the clamps

    def to_dict(self) -> dict:
        """A JSON-able form, for the cache key and for persisting a Look."""
        return {"stops": [[lv, rgb_to_hex(c)] for lv, c in self.stops]}


@dataclass(frozen=True)
class GradientMap:
    """A ramp, an optional accent, and the tone adjustment applied before both.

    Attributes:
        ramp: The main lightness-indexed ramp.
        accent: An optional second ramp for a hue band the main ramp would
            flatten.
        contrast: Multiplier applied to ``L*`` around mid-grey before lookup.
            ``>1`` deepens; the first real look used 1.15.
        lift: ``L*`` offset applied after ``contrast``. Negative darkens.

    Examples:
        >>> gm = GradientMap(ramp=Ramp.from_hex([(0.0, '#1B0610'), (100.0, '#FEF0DC')]))
        >>> rgb_to_hex(gm(( 0.0, 0.0, 0.0)))
        '#1B0610'
        >>> rgb_to_hex(gm(( 1.0, 1.0, 1.0)))
        '#FEF0DC'
    """

    ramp: Ramp
    accent: Optional[Accent] = None
    contrast: float = 1.0
    lift: float = 0.0

    def __call__(self, rgb: Rgb) -> Rgb:
        """Map one sRGB colour through the gradient map."""
        level = lightness(rgb)
        level = (level - 50.0) * self.contrast + 50.0 + self.lift
        level = max(0.0, min(100.0, level))
        base = self.ramp.at(level)
        if self.accent is None:
            return base
        w = self.accent.weight(rgb)
        if w == 0.0:
            return base
        acc = self.accent.ramp.at(level)
        return tuple(b * (1 - w) + a * w for b, a in zip(base, acc))  # type: ignore[return-value]

    def to_dict(self) -> dict:
        """A JSON-able form — the thing that is hashed for the cache key."""
        d: dict = {
            "ramp": self.ramp.to_dict(),
            "contrast": self.contrast,
            "lift": self.lift,
        }
        if self.accent is not None:
            a = self.accent
            d["accent"] = {
                "ramp": a.ramp.to_dict(),
                "hue": a.hue,
                "hue_width": a.hue_width,
                "min_saturation": a.min_saturation,
                "saturation_soft": a.saturation_soft,
                "strength": a.strength,
            }
        return d


def gradient_map(
    ramp: Ramp,
    *,
    accent: Optional[Accent] = None,
    contrast: float = 1.0,
    lift: float = 0.0,
) -> GradientMap:
    """Build a :class:`GradientMap`, warning about a ramp that reaches black.

    The warning is the encoded form of a measured mistake: a ramp whose dark end
    sat at L\\* 3.6 crushed 16.2% of pixels into the bottom bin, where the
    reference it was matching had 0.3%. The reference's own floor was an
    oxblood at L\\* 8.22 — it had **no true black at all**.

    Examples:
        >>> import warnings
        >>> ok = gradient_map(Ramp.from_hex([(8.2, '#2E0C18'), (100.0, '#FEF0DC')]))
        >>> ok.ramp.darkest
        8.2

        >>> with warnings.catch_warnings(record=True) as w:
        ...     warnings.simplefilter('always')
        ...     _ = gradient_map(Ramp.from_hex([(0.0, '#000000'), (100.0, '#FFFFFF')]))
        ...     print(str(w[0].message)[:43])
        ramp reaches L* 0.0, below the L* 5.0 floor
    """
    if ramp.darkest < SHADOW_FLOOR_WARN_L:
        warnings.warn(
            f"ramp reaches L* {ramp.darkest}, below the L* {SHADOW_FLOOR_WARN_L} "
            f"floor: this crushes shadows to near-black. Measured on a real "
            f"look, an L* 3.6 dark anchor put 16.2% of pixels in the bottom "
            f"histogram bin against the reference's 0.3%; raising it to the "
            f"reference's own L* 8.22 cut the histogram distance from 46.7 to "
            f"32.0 pp. If the target genuinely has true black, ignore this.",
            stacklevel=2,
        )
    return GradientMap(ramp=ramp, accent=accent, contrast=contrast, lift=lift)


def cube_text(
    spec: Union[Ramp, GradientMap],
    *,
    size: int = DFLT_CUBE_SIZE,
    title: str = "looks_gradient_map",
) -> str:
    """Render an Iridas ``.cube`` for ``spec``, as text.

    The lattice order is the format's own: **red varies fastest**, then green,
    then blue. Getting that backwards produces a file that loads without
    complaint and swaps the red and blue axes of every colour, which is the
    single easiest way to be wrong here.

    Args:
        spec: A :class:`Ramp` (used with default tone) or a :class:`GradientMap`.
        size: Lattice edge length. 2 is legal and useful for tests.
        title: Written into the file's ``TITLE`` line.

    Examples:
        >>> ramp = Ramp.from_hex([(0.0, '#000000'), (100.0, '#FFFFFF')])
        >>> text = cube_text(ramp, size=2)
        >>> print(text.splitlines()[0])
        TITLE "looks_gradient_map"
        >>> print(text.splitlines()[1])
        LUT_3D_SIZE 2

        Red fastest: entry 1 is (r=1, g=0, b=0), which for a neutral ramp is a
        dark grey rather than a bright one, because red carries only 21% of
        luminance.

        >>> first, second = text.splitlines()[5], text.splitlines()[6]
        >>> [round(float(x), 3) for x in first.split()]
        [0.0, 0.0, 0.0]
        >>> round(float(second.split()[0]), 3)
        0.532
    """
    if size < 2:
        raise LutError(f"a cube needs size >= 2, got {size}")
    gm = spec if isinstance(spec, GradientMap) else GradientMap(ramp=spec)
    denom = size - 1
    lines = [
        f'TITLE "{title}"',
        f"LUT_3D_SIZE {size}",
        "DOMAIN_MIN 0 0 0",
        "DOMAIN_MAX 1 1 1",
        "",
    ]
    for b in range(size):
        for g in range(size):
            for r in range(size):
                out = gm((r / denom, g / denom, b / denom))
                lines.append(" ".join(f"{max(0.0, min(1.0, c)):.6f}" for c in out))
    return "\n".join(lines) + "\n"


def cube_key(spec: Union[Ramp, GradientMap], *, size: int = DFLT_CUBE_SIZE) -> str:
    """A content hash of everything that determines the file's bytes.

    A 33-cube is ~950 KB, so a `.cube` is a **build artifact generated into a
    cache**, never committed and never carried inside a Look. The ramp is the
    spec; this is its address. Two Looks with the same ramp share one file, and
    a changed ramp cannot reuse a stale one.

    Examples:
        >>> r = Ramp.from_hex([(0.0, '#000000'), (100.0, '#FFFFFF')])
        >>> a, b = cube_key(r), cube_key(r)
        >>> a == b and len(a) == 64
        True
        >>> cube_key(r, size=17) == cube_key(r, size=33)   # size is identity
        False
    """
    gm = spec if isinstance(spec, GradientMap) else GradientMap(ramp=spec)
    payload = json.dumps(
        {"spec": gm.to_dict(), "size": size, "schema": "looks.cube/v1"},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_cube(
    spec: Union[Ramp, GradientMap],
    path: Union[str, Path],
    *,
    size: int = DFLT_CUBE_SIZE,
    title: str = "looks_gradient_map",
) -> Path:
    """Write the ``.cube`` for ``spec`` to ``path`` and return it.

    Creates parent directories. Writing is not conditional on the file's
    absence — the caller owns the cache policy, and this owns the bytes.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(cube_text(spec, size=size, title=title))
    return p
