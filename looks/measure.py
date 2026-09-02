"""What a clip *is*, measured — the input to resolving an effect's parameters.

This module exists because of one expensive lesson. Building the first real
look, the flattening stage ran at half resolution because that is ~10x faster
and, on two of three sources, measurably flatter. On the third — a dark indoor
clip, already the softest at source — it was visibly mushy. Measured through
the whole chain: clip A went 35 -> 72 (205% retained), B 117 -> 114 (98%), C
46 -> 38 (**83%**). One global setting made the softest source softer still, so
it became the softest thing on screen by a wide margin, and it was the one the
viewer complained about.

So an effect's parameters have to resolve against *the clip they apply to*.
That needs a measurement, and a measurement needs three things stated that are
usually left implicit — which is what the identity fields on :class:`ClipStats`
are for:

- **``stage``** — measuring the source file answers the wrong question. The
  number that mattered was *post-effect* sharpness, because the LUT-and-posterise
  stage normally *adds* apparent sharpness by creating hard edges between flat
  regions, and it only does that where the flattener left distinct regions.
- **``instrument``** — the fix is reproducible, the scale is not. Different
  instruments give different numbers for the same clip, and comparing across
  them silently compares nothing.
- **``luma_space``** — the 29x trap. The same nominal threshold gives a
  crushed-black share of **0.6% in coded Y** and **17.4% in `BGR2GRAY`** on the
  same frames. No error is raised, no warning appears, and the two numbers look
  equally plausible.

:func:`compare` **raises** when any of those disagree, because the measured
disagreements between instruments and between luma spaces are larger than the
effects a resolver is choosing between.

**Everything here works at the zero-dependency tier.** ``ffprobe -f lavfi``
over ``signalstats`` / ``siti`` / ``blurdetect`` yields per-frame JSON that
stdlib ``json`` parses. Independently checked against OpenCV: the sharpness
ordering agrees (Spearman +0.845), and a threshold share is bit-exact against
numpy. So the headline auto-tuning capability needs no extra.

Every process started here goes through :mod:`looks._run`, so the ``-f null -``
invariant covers it: this module measures and never produces.

    >>> stats = measure('clip.mp4')                    # doctest: +SKIP
    >>> stats.sharpness, stats.luma_space              # doctest: +SKIP
    (152.78, 'coded_y')
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from typing import Literal, Mapping, Optional, Sequence

from looks._run import run

Stage = Literal["source", "post_effect"]
"""Where in the pipeline a measurement was taken.

``source`` is the clip as it arrives; ``post_effect`` is after a Look has been
applied. They are *not* comparable, and conflating them is the mistake the
per-source flattening lesson came from — the number that governs the outcome is
the post-effect one.
"""

LumaSpace = Literal["coded_y", "bgr2gray", "linear_y", "lstar"]
"""Which luma a threshold or average was taken in.

Part of a measurement's identity, not a footnote: the same nominal threshold
gives a crushed-black share of 0.6% in ``coded_y`` and 17.4% in ``bgr2gray``.
"""

ColorRange = Literal["limited", "full", "untagged"]
"""``untagged`` is a **third value**, not a synonym for ``limited``.

ffmpeg assumes limited for an untagged yuv420p source — including for files
ffmpeg itself just wrote, which are untagged by default. If the source is
really full-range, every colour operation downstream is applied to wrongly
expanded values, with no warning: measured, the two assumptions differ on 99.6%
of bytes, by up to 15/255.
"""

#: Frames sampled per measurement by default.
#:
#: **Not 3.** The source material used a 3-frame median; measured on the
#: delivered render, that carries a p90 relative error of 12.7-34.0%, which is
#: larger than most of the improvements a resolver would be choosing between.
#: Five is the smallest that brings it under the effects being compared.
DFLT_PROBE_FRAMES = 5

#: The ffprobe/ffmpeg filter chain that produces every statistic below in one
#: decode. ``signalstats`` gives luma and saturation summaries, ``siti`` gives
#: spatial and temporal information (ITU-T P.910), ``blurdetect`` gives a
#: perceptual blur estimate (Marziliano).
INSTRUMENT_CHAIN = "signalstats,siti,blurdetect"

#: The instrument name recorded on a :class:`ClipStats` produced here. Carries
#: the ffmpeg major version because the filters' outputs are version-dependent.
INSTRUMENT_PREFIX = "ffmpeg"


class MeasurementError(RuntimeError):
    """A measurement that could not be taken, or one that must not be compared."""


class Incomparable(MeasurementError):
    """Two measurements whose identity fields disagree.

    Deliberately loud. The alternative — comparing them anyway — returns a
    confident number produced by two different instruments, which is worse than
    a refusal because nothing about it looks wrong.
    """


@dataclass(frozen=True)
class LumaSummary:
    """A frame's luma distribution, in whatever :class:`LumaSpace` was used.

    ``low`` and ``high`` are ``signalstats``' ``YLOW`` / ``YHIGH``, which are
    the **10th and 90th percentiles** — not the minimum and maximum. The
    man page is explicit ("the Y value at the 10% percentile"), and reading them
    as extremes overstates a clip's range on every real source.

    Examples:
        >>> LumaSummary(low=41.0, mean=106.0, high=170.0).spread
        129.0
    """

    low: float
    mean: float
    high: float
    minimum: Optional[float] = None
    maximum: Optional[float] = None

    @property
    def spread(self) -> float:
        """``high - low``, i.e. the p10-p90 spread."""
        return self.high - self.low


@dataclass(frozen=True)
class ClipStats:
    """What one source contributes to one stage of one pipeline, as measured.

    The first five fields are the value's **identity**, not decoration. Two
    ``ClipStats`` are comparable only if ``stage``, ``instrument``,
    ``luma_space`` and ``sample_spec`` all agree — :func:`compare` raises
    otherwise.

    Attributes:
        source_id: Whatever the caller calls this clip. Never a path, so a
            measurement survives the file moving.
        stage: ``source`` or ``post_effect``. See :data:`Stage`.
        instrument: What took the measurement, including its version.
        luma_space: See :data:`LumaSpace`.
        sample_spec: How the frames were chosen. Part of identity because the
            sampler moves the answer: taking the median over the 3 widest spans
            gave one clip a spatial-information figure of 30.7 where all 17
            spans gave 41.9 — a 27% move from the sampler alone.
        n_frames: How many frames were actually measured.
        sharpness: Higher is sharper, in the instrument's own units.
        sharpness_unit: What those units are.
        luma: The luma distribution.
        saturation_mean: Mean chroma magnitude.
        temporal_delta: Mean frame-to-frame change. The flicker check as one
            number — the shipped look sits at 0.89-1.12x its own source's.
        blur: ``blurdetect``'s estimate. Higher is blurrier, the opposite
            direction from :attr:`sharpness`, which is why they are separate
            fields rather than one "quality" number.
        color_range: See :data:`ColorRange`.
        extra: Instrument-specific values nothing above has a home for.

    Examples:
        >>> s = ClipStats(source_id='c03', stage='post_effect',
        ...               instrument='ffmpeg-8.1/siti', luma_space='coded_y',
        ...               sample_spec='uniform:5', n_frames=5, sharpness=38.4)
        >>> s.sharpness
        38.4
        >>> s.identity
        ('post_effect', 'ffmpeg-8.1/siti', 'coded_y', 'uniform:5')
    """

    source_id: str
    stage: Stage
    instrument: str
    luma_space: LumaSpace
    sample_spec: str
    n_frames: int

    sharpness: Optional[float] = None
    sharpness_unit: str = ""
    luma: Optional[LumaSummary] = None
    saturation_mean: Optional[float] = None
    temporal_delta: Optional[float] = None
    blur: Optional[float] = None
    color_range: ColorRange = "untagged"
    extra: Mapping[str, float] = field(default_factory=dict)

    @property
    def identity(self) -> tuple[str, str, str, str]:
        """The four fields two measurements must share to be comparable."""
        return (self.stage, self.instrument, self.luma_space, self.sample_spec)


def compare(a: ClipStats, b: ClipStats) -> None:
    """Raise :class:`Incomparable` unless ``a`` and ``b`` can be compared.

    Call this before any arithmetic that puts two measurements in the same
    expression. It is cheap, and the failure it prevents is silent.

    Examples:
        >>> base = dict(instrument='ffmpeg-8.1/siti', luma_space='coded_y',
        ...             sample_spec='uniform:5', n_frames=5)
        >>> a = ClipStats(source_id='c01', stage='post_effect', **base)
        >>> b = ClipStats(source_id='c02', stage='post_effect', **base)
        >>> compare(a, b)

        Different stages are the mistake the whole module exists to prevent:

        >>> c = ClipStats(source_id='c02', stage='source', **base)
        >>> compare(a, c)
        Traceback (most recent call last):
        ...
        looks.measure.Incomparable: 'c01' and 'c02' were measured differently
        and cannot be compared: stage 'post_effect' vs 'source'...

        So is a different luma space, and this one is the 29x trap:

        >>> d = ClipStats(source_id='c02', stage='post_effect',
        ...               instrument='ffmpeg-8.1/siti', luma_space='bgr2gray',
        ...               sample_spec='uniform:5', n_frames=5)
        >>> compare(a, d)
        Traceback (most recent call last):
        ...
        looks.measure.Incomparable: ...luma_space 'coded_y' vs 'bgr2gray'...
    """
    fields = ("stage", "instrument", "luma_space", "sample_spec")
    differences = [
        f"{name} {getattr(a, name)!r} vs {getattr(b, name)!r}"
        for name in fields
        if getattr(a, name) != getattr(b, name)
    ]
    if differences:
        raise Incomparable(
            f"{a.source_id!r} and {b.source_id!r} were measured differently and "
            f"cannot be compared: {'; '.join(differences)}. The measured "
            f"disagreements between instruments and between luma spaces (0.6% "
            f"vs 17.4% crushed-black for one threshold) are larger than the "
            f"effects a resolver chooses between, so this is a refusal rather "
            f"than a warning."
        )


def _tag(tags: Mapping[str, str], key: str) -> Optional[float]:
    raw = tags.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _median(values: Sequence[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return statistics.median(present) if present else None


def probe_frames(
    source: str,
    *,
    vf: str = "",
    frames: int = DFLT_PROBE_FRAMES,
    fps: float = 1.0,
    ffprobe: str = "ffprobe",
    timeout: float = 120.0,
) -> list[dict]:
    """Per-frame instrument readings for ``source``, optionally through ``vf``.

    Goes through ``ffprobe -f lavfi``, so the output is JSON that stdlib parses
    and the process cannot write media at all.

    ``vf`` is the compiled chain of the Look being measured. Supplying it is
    what makes the measurement ``post_effect`` — and that is the one that
    governs the outcome, so it is not an optional refinement.

    Args:
        source: Path to the clip.
        vf: A filter chain to apply before measuring. Empty measures the source.
        frames: How many frames to read.
        fps: Sampling rate. The default reads roughly one frame per second,
            which spreads the sample across the clip rather than clustering it
            at the head.
        ffprobe: Binary name or path.
        timeout: Seconds.

    Raises:
        MeasurementError: The probe could not run, or produced no frames.
    """
    chain = f"movie={source}"
    if vf:
        chain += f",{vf}"
    chain += f",fps={fps},{INSTRUMENT_CHAIN}"
    entries = ",".join(
        f"lavfi.{k}"
        for k in (
            "signalstats.YMIN",
            "signalstats.YLOW",
            "signalstats.YAVG",
            "signalstats.YHIGH",
            "signalstats.YMAX",
            "signalstats.SATAVG",
            "siti.si",
            "siti.ti",
            "blur",
        )
    )
    result = run(
        [
            ffprobe,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            chain,
            "-show_entries",
            f"frame_tags={entries}",
            "-of",
            "json",
            "-read_intervals",
            f"%+#{frames}",
        ],
        timeout=timeout,
    )
    if not result.ok:
        raise MeasurementError(
            f"could not measure {source!r}: "
            f"{result.error or result.stderr.strip() or f'exit {result.returncode}'}"
        )
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as e:
        raise MeasurementError(f"ffprobe did not return JSON for {source!r}") from e
    got = [f.get("tags", {}) for f in payload.get("frames", [])]
    if not got:
        raise MeasurementError(
            f"no frames measured for {source!r} — the chain produced nothing"
        )
    return got


def color_range(
    source: str, *, ffprobe: str = "ffprobe", timeout: float = 30.0
) -> ColorRange:
    """What range ``source`` **declares**, with ``untagged`` as a real answer.

    Not "probably limited". ffmpeg writes untagged files by default, so the
    untagged case is the normal one, and treating it as limited is an
    assumption the caller should get to see rather than inherit.
    """
    result = run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=color_range",
            "-of",
            "default=nw=1:nk=1",
            source,
        ],
        timeout=timeout,
    )
    if not result.ok:
        return "untagged"
    value = result.stdout.strip().lower()
    if value in ("tv", "mpeg", "limited"):
        return "limited"
    if value in ("pc", "jpeg", "full"):
        return "full"
    return "untagged"


def measure(
    source: str,
    *,
    source_id: str = "",
    vf: str = "",
    frames: int = DFLT_PROBE_FRAMES,
    fps: float = 1.0,
    ffmpeg_version: str = "unknown",
    ffprobe: str = "ffprobe",
    timeout: float = 120.0,
) -> ClipStats:
    """Measure one clip, at the source or through a Look's compiled chain.

    Supplying ``vf`` makes this a ``post_effect`` measurement, which is the one
    that governs a resolver's answer.

    ``ffmpeg_version`` enters :attr:`ClipStats.instrument`, so pass the version
    from a :class:`looks.environment.FfmpegEnv` rather than letting it default —
    the filters' outputs are version-dependent, and ``unknown`` is honest but
    makes every measurement incomparable with a properly-labelled one, which is
    the intended pressure.

    Raises:
        MeasurementError: The probe could not run.
    """
    tags = probe_frames(
        source, vf=vf, frames=frames, fps=fps, ffprobe=ffprobe, timeout=timeout
    )
    si = _median([_tag(t, "lavfi.siti.si") for t in tags])
    ti_values = [_tag(t, "lavfi.siti.ti") for t in tags]
    # siti reports ti = 0 for the first frame (nothing to difference against),
    # so including it drags the median toward zero on a short probe.
    ti = _median(ti_values[1:]) if len(ti_values) > 1 else None
    low = _median([_tag(t, "lavfi.signalstats.YLOW") for t in tags])
    mean = _median([_tag(t, "lavfi.signalstats.YAVG") for t in tags])
    high = _median([_tag(t, "lavfi.signalstats.YHIGH") for t in tags])
    luma = (
        LumaSummary(
            low=low,
            mean=mean,
            high=high,
            minimum=_median([_tag(t, "lavfi.signalstats.YMIN") for t in tags]),
            maximum=_median([_tag(t, "lavfi.signalstats.YMAX") for t in tags]),
        )
        if None not in (low, mean, high)
        else None
    )
    return ClipStats(
        source_id=source_id or source,
        stage="post_effect" if vf else "source",
        instrument=f"{INSTRUMENT_PREFIX}-{ffmpeg_version}/{INSTRUMENT_CHAIN}",
        luma_space="coded_y",
        sample_spec=f"fps={fps}:first={frames}",
        n_frames=len(tags),
        sharpness=si,
        sharpness_unit="siti.si",
        luma=luma,
        saturation_mean=_median([_tag(t, "lavfi.signalstats.SATAVG") for t in tags]),
        temporal_delta=ti,
        blur=_median([_tag(t, "lavfi.blur") for t in tags]),
        color_range=color_range(source, ffprobe=ffprobe),
    )


def dispersion(stats: Sequence[ClipStats], *, key: str = "sharpness") -> float:
    """The max/min ratio of ``key`` across ``stats`` — the quantity to minimise.

    A **ratio**, not a variance, for two reasons. Every figure the source
    material reports is one ("2.98x -> 1.59x", "205% retained", "0.89-1.12x"),
    and the statistic is positive and multiplicative, so a variance in raw units
    would let one bright clip dominate.

    Every pair is checked with :func:`compare` first.

    Examples:
        >>> base = dict(stage='post_effect', instrument='i', luma_space='coded_y',
        ...             sample_spec='s', n_frames=5)
        >>> before = [ClipStats(source_id=n, sharpness=v, **base)
        ...           for n, v in [('c01', 72.2), ('c02', 114.3), ('c03', 38.4)]]
        >>> round(dispersion(before), 2)          # the shipped V2b spread
        2.98
        >>> after = [ClipStats(source_id=n, sharpness=v, **base)
        ...          for n, v in [('c01', 72.2), ('c02', 114.3), ('c03', 71.8)]]
        >>> round(dispersion(after), 2)           # V2c, after the per-clip fix
        1.59
    """
    if len(stats) < 2:
        raise MeasurementError("dispersion needs at least two measurements")
    for other in stats[1:]:
        compare(stats[0], other)
    values = [getattr(s, key) for s in stats]
    if any(v is None for v in values):
        missing = [s.source_id for s, v in zip(stats, values) if v is None]
        raise MeasurementError(f"{key!r} was not measured for {missing}")
    if any(v <= 0 for v in values):
        raise MeasurementError(
            f"{key!r} must be positive for a ratio dispersion; got {values}"
        )
    return max(values) / min(values)
