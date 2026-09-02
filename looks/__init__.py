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
:mod:`looks.environment`, :mod:`looks.geometry`, :mod:`looks.lut`,
:mod:`looks.measure`, :mod:`looks.frame_dependency`.

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
    classify,
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
    "classify",
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


__version__ = _installed_version()
