"""The ffmpeg backend: filter strings, escaping, and the first effects.

This is where a `Step`'s payload becomes text another process will parse, which
is the whole reason the escaping in here is not a detail. Everything else in the
package produces data; this module produces a *string handed to a parser*, and
the flagship effect takes a caller-supplied file path.

## Escaping, and why once is not enough

ffmpeg unescapes a filter option **twice**. The filtergraph parser reads the
whole graph first, splitting on ``,`` ``;`` ``[`` ``]`` and consuming one layer
of quoting; only then is each surviving per-filter argument split into options
on ``:``, consuming a second. So escaping runs in the **mirror order** — option
level first, graph level over that result — and each ffmpeg pass peels off
exactly one layer.

Ported from ``muvid.visualize.canvas.escape_filter_value``, with its recorded
negative kept: **``%`` is deliberately not escaped.** Neither parser treats it
as special, so ``\\%`` was simply unescaped back to ``%`` and escaping it never
did anything. ``drawtext``'s ``%{...}`` expansion is a third level belonging to
one filter's ``text`` option, and is out of scope for a general escaper.

Verified here rather than inherited: ``-vf "lut3d=file=id,with:comma.cube"``
fails, and the escaped form works.

## LGPL first, and the alternate says why

Where an effect has both a GPL-gated and an LGPL implementation, **both are
registered** and the LGPL one carries the lower ``preference``. That is not a
licence judgement made here — the registry records what exists and a
:class:`~looks.licence.Policy` refuses at selection — it is an ordering, so that
a caller who never thinks about licences gets the portable answer by default and
a caller who needs the GPL one can still pin it.

``eq`` is the case worth naming: the obvious grade filter is GPL-only, three of
its jobs have LGPL substitutes in the same binary, and `muvid` ships a single
``eq=`` for a cosmetic dim. That one filter call is the concrete argument for
this package existing.

## What is deliberately absent

No encoder arguments, no output file, no process. A payload here is a filter
fragment and nothing more — the moment this module grows an opinion about
``-c:v`` it has become the second muvid, and the ``-f null -`` invariant that
keeps the package honest would have nothing left to protect.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from looks.geometry import Size, ffmpeg_chain, placement, social_size
from looks.licence import Terms, terms_for
from looks.registry import REGISTRY, EffectRegistry
from looks.spec import ImplRef, LookPlan, Span, SpecError

#: Characters the **option** parser gives meaning to, within one filter's
#: arguments. Must lead with ``\\``: the backslashes introduced for the later
#: characters must not themselves be escaped by the ``\\`` pass.
OPTION_LEVEL_SPECIALS = ("\\", "'", ":")

#: Characters the **filtergraph** parser gives meaning to across the graph:
#: ``,`` chains, ``;`` separates, ``[]`` delimit pad labels, ``\\`` and ``'``
#: do that parser's quoting.
GRAPH_LEVEL_SPECIALS = ("\\", "'", ",", ";", "[", "]")


class FfmpegBackendError(SpecError):
    """A step that cannot be expressed as a filter fragment."""


def _backslash_escape(value: str, specials: Sequence[str]) -> str:
    for char in specials:
        value = value.replace(char, "\\" + char)
    return value


def escape_filter_value(value: str) -> str:
    r"""Escape a value for use as a filter option inside a filtergraph.

    >>> escape_filter_value("plain.cube")
    'plain.cube'

    A comma would end the filter and a colon would end the option, so both are
    escaped twice — once for each parser that will read them:

    >>> escape_filter_value("id,with:comma.cube")
    'id\\,with\\\\:comma.cube'

    ``%`` is left alone, on purpose — neither parser treats it as special, so
    escaping it only produced a backslash that was unescaped away again:

    >>> escape_filter_value("100%.cube")
    '100%.cube'
    """
    return _backslash_escape(
        _backslash_escape(value, OPTION_LEVEL_SPECIALS), GRAPH_LEVEL_SPECIALS
    )


def filter_string(name: str, options: Optional[Mapping[str, Any]] = None) -> str:
    r"""One filter, with its options escaped.

    >>> filter_string("gblur", {"sigma": 2})
    'gblur=sigma=2'
    >>> filter_string("null")
    'null'

    A path with a comma in it survives, which is the whole point:

    >>> filter_string("lut3d", {"file": "a,b.cube"})
    'lut3d=file=a\\,b.cube'
    """
    if not options:
        return name
    parts = [
        f"{key}={escape_filter_value(str(value))}"
        for key, value in options.items()
        if value is not None
    ]
    return f"{name}={':'.join(parts)}" if parts else name


def gated(fragment: str, at: Optional[Span]) -> str:
    """Restrict a fragment to a span, using ffmpeg's own timeline support.

    >>> gated("gblur=sigma=2", None)
    'gblur=sigma=2'
    >>> gated("gblur=sigma=2", Span(1.0, 3.5))
    "gblur=sigma=2:enable='between(t,1,3.5)'"

    A fragment of several filters is gated **per filter**, because ``enable`` is
    an option on a filter and not on a chain — writing it once at the end would
    gate only the last one, silently:

    >>> gated("scale=2:2,crop=1:1", Span(0.0, 1.0))
    "scale=2:2:enable='between(t,0,1)',crop=1:1:enable='between(t,0,1)'"
    """
    if at is None:
        return fragment
    window = f"enable='between(t,{_num(at.start)},{_num(at.end)})'"
    return ",".join(
        f"{part}{':' if '=' in part else '='}{window}" for part in fragment.split(",")
    )


def _num(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def vf(plan: LookPlan, *, gate: bool = True) -> str:
    """A whole plan as one ``-vf`` fragment: input-index-free, splice-ready.

    The seam every consumer asked for is one string — ``muvid`` splices it into
    the filter chain ``_render_part`` already builds, and that only works if
    nothing here names a stream.

    Raises:
        FfmpegBackendError: If a step is not ffmpeg-backed, or is gated to a
            span its filter cannot honour. The second is why
            :attr:`~looks.spec.ImplRef.timeline` exists: ``zoompan`` and
            ``elbg`` carry no timeline support, so an ``at`` on them would be
            accepted by the string and ignored by the binary.
    """
    fragments = []
    for index, step in enumerate(plan.steps):
        if step.impl.backend != "ffmpeg":
            raise FfmpegBackendError(
                f"step {index} ({step.effect!r}) runs on "
                f"{step.impl.backend!r}, which has no filter form. A plan "
                "mixing backends is compiled per backend, never flattened."
            )
        fragment = step.payload.get("filter")
        if not fragment:
            from looks.cache import PENDING

            if PENDING in step.payload:
                raise FfmpegBackendError(
                    f"step {index} ({step.effect!r}) needs an artifact that has "
                    f"not been built: cube {step.payload[PENDING]['key'][:12]}…. "
                    "Call looks.materialize(plan) first — compiling writes no "
                    "files on purpose, so acquiring artifacts is its own step."
                )
            raise FfmpegBackendError(
                f"step {index} ({step.effect!r}) has no 'filter' in its payload"
            )
        if step.at is not None and gate:
            if not step.impl.timeline:
                raise FfmpegBackendError(
                    f"step {index} ({step.effect!r}) is gated to {step.at}, but "
                    f"{step.impl.impl!r} has no timeline support — ffmpeg would "
                    "accept the option and ignore it, which is a look that "
                    "silently applies everywhere."
                )
            fragment = gated(fragment, step.at)
        fragments.append(fragment)
    return ",".join(fragments)


# ---------------------------------------------------------------- the effects


def _ffmpeg_terms() -> Terms:
    """The static declaration. :func:`looks.compile.compile_look` replaces it
    with the probed binary's, which is the one that decides a tier."""
    return terms_for("ffmpeg")[0]


def _target_size(params: Mapping[str, Any]) -> Size:
    target = params.get("target")
    if target is None:
        raise FfmpegBackendError(
            "a geometry effect needs a 'target' — a size like '1920x1080' or a "
            "preset name like 'shorts'"
        )
    if isinstance(target, Size):
        return target
    text = str(target)
    if "x" in text.lower():
        width, height = text.lower().split("x", 1)
        return Size(int(width), int(height))
    return social_size(text)


def _geometry(mode: str):
    def compiler(params, *, clip=None, env=None, **_kw):
        if clip is None:
            raise FfmpegBackendError(
                f"the {mode!r} effect is derived from the source's size, so it "
                "needs a ClipSpec. Pass clip= to compile_look()."
            )
        place = placement(
            Size(clip.width, clip.height), _target_size(params), mode=mode
        )
        return {"filter": ffmpeg_chain(place) or "null"}

    return compiler


def _simple(name: str, build):
    def compiler(params, **_kw):
        return {"filter": filter_string(name, build(params))}

    return compiler


def _gamma_expression(params) -> Mapping[str, Any]:
    """Gamma through `lutrgb`, because rule 13 forbids the offset alternative.

    An additive brightness offset lifts the black floor and reads as haze; a
    gamma curve keeps the endpoints. ``eq=gamma=`` would say this in one option
    and is GPL-only, so the LGPL form composes the same curve as a lookup.
    """
    gamma = float(params.get("gamma", 1.0))
    if gamma <= 0:
        raise FfmpegBackendError(f"gamma must be positive, got {gamma}")
    curve = f"maxval*pow(val/maxval,{1 / gamma:.6f})"
    return {"r": curve, "g": curve, "b": curve}


def _posterize_expression(params) -> Mapping[str, Any]:
    """Quantise through `lutrgb`, not `elbg`.

    ``elbg`` is ffmpeg's own posterizer and is **non-deterministic**: measured
    while building the flicker classifier, two runs of one command disagreed by
    70-86/255. A look that differs from itself between renders is not a look.
    """
    levels = int(params.get("levels", 8))
    if levels < 2:
        raise FfmpegBackendError(f"posterize needs at least 2 levels, got {levels}")
    step = f"round(val*{levels - 1}/maxval)*maxval/{levels - 1}"
    return {"r": step, "g": step, "b": step}


def _gradient_map_compiler(params, **_kw):
    """A ramp in, a cube REQUEST out — never a file.

    `compile_look` writes nothing, so this emits the artifact's address and the
    spec that reproduces it, and :func:`looks.cache.materialize` supplies the
    file. That is what keeps a compiled plan portable: it can be hashed, stored
    and sent to another machine, which then builds the same cube from the same
    spec and gets the same bytes.
    """
    from looks.cache import PENDING
    from looks.lut import DFLT_CUBE_SIZE, DFLT_CUBE_TITLE, Ramp, cube_key, gradient_map

    stops = params.get("stops")
    if not stops:
        raise FfmpegBackendError(
            "the 'gradient_map' effect needs 'stops': [(L*, '#rrggbb'), ...] — "
            "the ramp the look maps luminance onto"
        )
    size = int(params.get("size", DFLT_CUBE_SIZE))
    title = str(params.get("title", DFLT_CUBE_TITLE))
    spec = gradient_map(
        Ramp.from_hex([tuple(s) for s in stops]),
        contrast=float(params.get("contrast", 1.0)),
        lift=float(params.get("lift", 0.0)),
    )
    request = {
        "stops": [list(s) for s in stops],
        "size": size,
        "title": title,
        "contrast": float(params.get("contrast", 1.0)),
        "lift": float(params.get("lift", 0.0)),
        "key": cube_key(spec, size=size, title=title),
        # The template rather than the filter, because the path is not known
        # until the artifact exists. `{file}` is filled in by materialize with
        # an ESCAPED path — the flagship effect takes a caller-supplied
        # directory, and a comma in it would otherwise end the filter.
        "filter_template": "lut3d=file={file}:interp="
        + str(params.get("interp", "tetrahedral")),
    }
    return {PENDING: request}


def register_defaults(registry: Optional[EffectRegistry] = None) -> EffectRegistry:
    """Register the built-in ffmpeg effects. Idempotent per registry.

    Called once on ``import looks``. Pass your own registry to get an
    independent set — the module-level default is the one
    :func:`looks.compile.compile_look` uses.

    Examples:
        >>> reg = register_defaults(EffectRegistry())
        >>> "saturation" in reg.effects() and "lut3d" in reg.effects()
        True

        Both ways to saturate are registered, and the LGPL one sorts first:

        >>> [i.impl for i in reg.implementations("saturation")]
        ['saturation.ffmpeg.colorchannelmixer', 'saturation.ffmpeg.eq']
    """
    reg = REGISTRY if registry is None else registry
    if "lut3d.ffmpeg.default" in reg:
        return reg
    terms = _ffmpeg_terms()

    def add(key, filters, compiler, *, preference=0, timeline=True, tags=()):
        effect, backend, _variant = key.split(".")
        reg.register(
            ImplRef(
                effect=effect,
                impl=key,
                backend=backend,
                terms=terms,
                requires_filters=filters,
                preference=preference,
                timeline=timeline,
            ),
            compiler,
            tags=tags,
        )

    # --- colour, LGPL first -------------------------------------------------
    add(
        "gradient_map.ffmpeg.lut3d",
        ("lut3d",),
        _gradient_map_compiler,
    )
    add(
        "lut3d.ffmpeg.default",
        ("lut3d",),
        _simple(
            "lut3d",
            lambda p: {"file": p["cube"], "interp": p.get("interp", "tetrahedral")},
        ),
    )
    add(
        "saturation.ffmpeg.colorchannelmixer",
        ("colorchannelmixer",),
        _simple("colorchannelmixer", _saturation_matrix),
    )
    add(
        "saturation.ffmpeg.eq",
        ("eq",),
        _simple("eq", lambda p: {"saturation": p.get("amount", 1.0)}),
        preference=1,
        tags=("gpl-gated",),
    )
    add(
        "contrast.ffmpeg.curves",
        ("curves",),
        _simple("curves", lambda p: {"all": _contrast_curve(p)}),
    )
    add(
        "contrast.ffmpeg.eq",
        ("eq",),
        _simple("eq", lambda p: {"contrast": p.get("amount", 1.0)}),
        preference=1,
        tags=("gpl-gated",),
    )
    add("gamma.ffmpeg.lutrgb", ("lutrgb",), _simple("lutrgb", _gamma_expression))
    add(
        "levels.ffmpeg.colorlevels",
        ("colorlevels",),
        _simple(
            "colorlevels",
            lambda p: {
                "rimin": p.get("black", 0),
                "gimin": p.get("black", 0),
                "bimin": p.get("black", 0),
                "rimax": p.get("white", 1),
                "gimax": p.get("white", 1),
                "bimax": p.get("white", 1),
            },
        ),
    )
    add(
        "posterize.ffmpeg.lutrgb", ("lutrgb",), _simple("lutrgb", _posterize_expression)
    )

    # --- spatial ------------------------------------------------------------
    add(
        "blur.ffmpeg.gblur",
        ("gblur",),
        _simple("gblur", lambda p: {"sigma": p.get("sigma", 2)}),
    )
    add(
        "blur.ffmpeg.boxblur",
        ("boxblur",),
        _simple("boxblur", lambda p: {"luma_radius": p.get("radius", 2)}),
        preference=1,
        tags=("gpl-gated",),
    )
    add(
        "sharpen.ffmpeg.unsharp",
        ("unsharp",),
        _simple(
            "unsharp",
            # `luma_amount`, not `amount`: unsharp has no such option and
            # ffmpeg answers "Option not found" at configure time. Caught by
            # the registry sweep, which is what that sweep is for.
            lambda p: {"luma_amount": p.get("amount", 1.0)},
        ),
    )

    # --- geometry, wrapping looks.geometry ----------------------------------
    for mode in ("fit", "fill", "stretch"):
        add(f"{mode}.ffmpeg.scale", ("scale",), _geometry(mode))

    # --- motion, wrapping looks.motion --------------------------------------
    add(
        "motion.ffmpeg.crop",
        ("crop", "setpts"),
        _motion_compiler,
        timeline=False,
    )
    return reg


def _saturation_matrix(params) -> Mapping[str, Any]:
    """Saturation as a scaled luma-preserving matrix.

    The LGPL answer to ``eq=saturation=``. Rec.709 luma coefficients, so a
    fully desaturated result is the same grey the encoder would compute.

    Note the recorded trap from `muvid`: ``colorchannelmixer`` is a silent
    no-op on YUV, so a caller wanting it on YUV input must convert first.
    """
    amount = float(params.get("amount", 1.0))
    lr, lg, lb = 0.2126, 0.7152, 0.0722
    cell = lambda base, weight: f"{weight + amount * (base - weight):.6f}"  # noqa: E731
    return {
        "rr": cell(1, lr),
        "rg": cell(0, lg),
        "rb": cell(0, lb),
        "gr": cell(0, lr),
        "gg": cell(1, lg),
        "gb": cell(0, lb),
        "br": cell(0, lr),
        "bg": cell(0, lg),
        "bb": cell(1, lb),
    }


def _contrast_curve(params) -> str:
    """Contrast as a three-point curve pinned at both ends.

    The LGPL answer to ``eq=contrast=``. Pivoting about mid-grey keeps black
    black and white white, which is rule 13's point in a different filter.
    """
    amount = float(params.get("amount", 1.0))
    mid = 0.5
    low = max(0.0, mid - 0.25 * amount)
    high = min(1.0, mid + 0.25 * amount)
    return f"0/0 {low:.4f}/0.25 {high:.4f}/0.75 1/1"


def _motion_compiler(params, *, clip=None, env=None, **_kw):
    """A camera path, via :mod:`looks.motion`.

    The registry entry that makes RULE G's compile half reachable from a
    ``Look``, so a camera move is a step in a plan like any other rather than a
    separate call a caller has to remember to make.
    """
    from looks.geometry import Size as _Size
    from looks.motion import Keyframe, Window, compile_motion

    frames = params.get("keyframes")
    if not frames:
        raise FfmpegBackendError(
            "the 'motion' effect needs 'keyframes': [(t, (x, y, w, h)), ...] in "
            "burns' normalised convention"
        )
    path = [
        Keyframe(float(t), Window(*(float(v) for v in window))) for t, window in frames
    ]
    output = None
    if params.get("output") is not None:
        output = _target_size({"target": params["output"]})
    elif clip is not None:
        output = _Size(clip.width, clip.height)
    fps = params.get("fps", clip.fps if clip is not None else None)
    return {"filter": compile_motion(path, output=output, fps=fps)}
