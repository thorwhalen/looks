"""A facade over video stylization: named effects carrying a licence tier.

Named effects that compile to a backend command, each carrying a licence tier,
so a caller can demand commercial-safe-only and get a **refusal** rather than a
surprise. Pure-data specs, separable from execution — the ``falaw.Plan`` shape,
except the cost unit is CPU-seconds rather than dollars.

The one call that shows what this is for::

    >>> from looks import needs_gpl
    >>> needs_gpl(['scale', 'eq', 'lut3d'])
    ('eq',)

``eq`` is the obvious brightness/contrast/gamma filter, and it exists **only in
a GPL build of ffmpeg**. Nothing in the ffmpeg CLI will tell you, because the
binary on your machine runs it fine — and ``curves`` / ``colorlevels`` /
``exposure`` do the same job in an LGPL one.

**Zero dependencies.** ffmpeg is shelled out to, never linked.

This namespace is **curated**: it carries the surface a caller uses, not
everything the package defines. Reach into a submodule for the rest —
:mod:`looks.spec`, :mod:`looks.environment`, :mod:`looks.licence`,
:mod:`looks.geometry`, :mod:`looks.lut`, :mod:`looks.measure`,
:mod:`looks.frame_dependency`.

One rename happens at this boundary and nowhere else: ``frame_dependency``'s
``classify`` is exported as :func:`classify_dependency`, because
``licence.classify`` has the better claim to the bare name here — a caller
reaching for ``looks.classify`` wants the licence question. Inside the
submodule it keeps its own short name.

Two names are deliberately absent, and a test asserts it: there is no
``render`` and no ``apply``. Every ffmpeg process this package starts ends in
``-f null -`` — it emits the chain, and the caller runs it. See
:mod:`looks._run`.
"""

from looks.environment import (
    FfmpegEnv,
    Licence,
    UnknownFilter,
    gpl_only_filters,
    known_filters,
    needs_gpl,
    probe,
)
from looks.frame_dependency import (
    Dependency,
    DependencyReport,
    assert_flicker_free,
)
from looks.frame_dependency import classify as classify_dependency
from looks.licence import (
    DFLT_POLICY,
    DISCLAIMER,
    Assessment,
    Conveyance,
    Coupling,
    FieldOfUse,
    LicenceCeilingExceeded,
    LicenceFieldRestricted,
    LicenceForbidden,
    LicenceUnknown,
    LooksLicenceError,
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
    terms_for,
    unverified_claims,
)
from looks.geometry import (
    Blurred,
    Box,
    GeometryError,
    Placement,
    Reframe,
    Size,
    Solid,
    ffmpeg_chain,
    placement,
    reframe,
    scaled_size,
    snap_even,
    social_size,
)
from looks.motion import (
    Keyframe,
    MotionError,
    Window,
    WindowLike,
    compile_motion,
    crop_fragment,
    zoompan_fragment,
)
from looks.lut import (
    Accent,
    GradientMap,
    LutError,
    Ramp,
    cube_key,
    cube_text,
    gradient_map,
    write_cube,
)
from looks.spec import (
    ClipSpec,
    Effect,
    ImplRef,
    Look,
    LookPlan,
    Ref,
    SchemaError,
    Span,
    SpanUnsupported,
    SpecError,
    Step,
    Target,
    UnresolvedParameter,
    look_from_dict,
    look_hash,
    look_to_dict,
    output_key,
    plan_from_dict,
    plan_hash,
    plan_to_dict,
    resolve,
    resolve_across,
    select_impl,
)
from looks.measure import (
    ClipStats,
    Incomparable,
    MeasurementError,
    color_range,
    compare,
    dispersion,
    measure,
)

__all__ = [
    # the environment: what this machine's ffmpeg is and what it may do
    "FfmpegEnv",
    "Licence",
    "UnknownFilter",
    "probe",
    "needs_gpl",
    "known_filters",
    "gpl_only_filters",
    # the licence tier: the facts, the policy projection, and the refusals
    "Terms",
    "Coupling",
    "Reach",
    "Conveyance",
    "FieldOfUse",
    "Tier",
    "Verdict",
    "Assessment",
    "Policy",
    "DFLT_POLICY",
    "DISCLAIMER",
    "terms_for",
    "ffmpeg_terms",
    "classify",
    "assess",
    "assess_ffmpeg_chain",
    "check",
    "unverified_claims",
    "LooksLicenceError",
    "LicenceForbidden",
    "LicenceFieldRestricted",
    "LicenceCeilingExceeded",
    "LicenceUnknown",
    # the spec: what a stylization IS, before anything runs
    "Effect",
    "Look",
    "Ref",
    "Span",
    "ClipSpec",
    "Target",
    "ImplRef",
    "Step",
    "LookPlan",
    "resolve",
    "resolve_across",
    "select_impl",
    "look_to_dict",
    "look_from_dict",
    "plan_to_dict",
    "plan_from_dict",
    "look_hash",
    "plan_hash",
    "output_key",
    "SpecError",
    "SchemaError",
    "SpanUnsupported",
    "UnresolvedParameter",
    # geometry: where a source frame lands inside a target frame
    "Size",
    "Box",
    "Placement",
    "Reframe",
    "Solid",
    "Blurred",
    "GeometryError",
    "placement",
    "reframe",
    "scaled_size",
    "ffmpeg_chain",
    "snap_even",
    "social_size",
    # motion: an authored camera path, compiled (RULE G's compile half)
    "Window",
    "WindowLike",
    "Keyframe",
    "MotionError",
    "compile_motion",
    "crop_fragment",
    "zoompan_fragment",
    # looks: a colour ramp in, an Iridas .cube out
    "Ramp",
    "Accent",
    "GradientMap",
    "LutError",
    "gradient_map",
    "cube_text",
    "cube_key",
    "write_cube",
    # measurement: what a clip is, with identity fields that refuse a wrong
    # comparison
    "ClipStats",
    "MeasurementError",
    "Incomparable",
    "measure",
    "compare",
    "dispersion",
    "color_range",
    # can this effect flicker?
    "Dependency",
    "DependencyReport",
    "classify_dependency",
    "assert_flicker_free",
]


def _installed_version() -> str:
    """The version of the installed distribution.

    Read from metadata rather than hardcoded, because CI bumps the version in
    ``pyproject.toml`` on every release and a literal here would silently
    disagree with it. Falls back to ``"0.0.0+unknown"`` when the package is on
    ``sys.path`` without being installed — honest, and distinguishable from a
    real version.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("looks")
    except PackageNotFoundError:  # pragma: no cover - depends on the environment
        return "0.0.0+unknown"


def __getattr__(name: str):
    """Resolve :data:`__version__` on first access (PEP 562).

    Reading it eagerly cost **50 ms of import time** — ``importlib.metadata``
    pulls in ``email.parser`` — for a value most callers never look at. Lazy
    keeps both halves: the version stays honest (a literal would silently
    disagree with the one CI bumps) and ``import looks`` stays cheap.

    Measured: 54.5 ms eager, 4.2 ms lazy.
    """
    if name == "__version__":
        value = _installed_version()
        globals()["__version__"] = value  # compute once
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
