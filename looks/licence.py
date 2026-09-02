"""What an implementation costs you in obligations, and when to refuse it.

This is the module the package exists for. Everything else in ``looks``
computes a filter string; this decides whether you are allowed to run it.

**looks reports observations, not legal conclusions.**

A tier is not a legal determination. It is a position on a policy ladder this
project chose, derived from things that were mechanically observed on a stated
date — a command that was run, a file that was read, a binary that was
interrogated — and every row records that observation so you can check the
derivation rather than trust the label.

looks refuses when it cannot observe. It does not adjudicate: where an
artifact's own statements about itself disagree, looks reports the
disagreement and refuses, and does not decide which statement is true.

Raising a ceiling is a decision about *your* obligations, not about this
software's. Whether the licences and terms recorded here permit what you
intend to do is a question for you and your counsel.

The shape
---------

**The facts are four orthogonal axes** — :class:`Coupling`, :class:`Reach`,
:class:`Conveyance`, :class:`FieldOfUse` — recorded on :class:`Terms`, which an
implementation declares about itself. *An implementation declares terms, never
a tier.* A frozen ``tier=`` field would be wrong twice over: it is a false
refusal for the LGPL-clean majority of ffmpeg's colour vocabulary, and it
cannot distinguish the one filter (``eq``) that genuinely is GPL-only. The
same effect is :attr:`Tier.WEAK_COPYLEFT` on an LGPL ffmpeg and
:attr:`Tier.COPYLEFT_TOOL` on a GPL one, so the tier is *resolved* at compile
time by :func:`classify`, from what the implementation declared joined with
what the environment turned out to be.

**The ladder is a replaceable policy projection of three of those axes**, not a
fact about licences — which is why the function that computes it is called
:func:`project_onto_ladder` and the shipped ordering is
:data:`DFLT_LADDER`, a default on :class:`Policy` rather than a constant of
the domain. Rungs 2 and 3 are *not* ordered by obligation-inclusion: in-process
LGPL and subprocess GPL impose different duties, not more and fewer, and plenty
of corporate policies rank them the other way. The shipped order is chosen for
what this federation ships — Python source that shells out and bundles nothing.
A caller with a different posture passes ``Policy(order=...)``.

**Three regions are off the ladder, where no ``max_tier`` reaches them.**
:attr:`Verdict.FORBIDDEN` (in-process strong copyleft, plus any recorded
prohibition), :attr:`Verdict.FIELD_RESTRICTED` (non-commercial, research-only)
and :attr:`Verdict.UNKNOWN`. Field of use is *not commensurable* with copyleft
strength — a non-commercial model is not "more copyleft than GPL", it is a
different kind of failure — so a ladder that admits it when you raise the
ceiling one notch is a trap, and so is a rung you can opt into for something
the design says to "always refuse".

**``max_tier`` is not the commercial-safe knob.** Every rung, including
:attr:`Tier.COPYLEFT_SHIPPED`, is commercially usable — a source offer is a
duty, not a prohibition. What is *not* commercially usable is
:attr:`FieldOfUse.NON_COMMERCIAL`, which is off the ladder. So
"commercial-safe only" is ``allow_field_restricted=frozenset()``, which is
already the default. Advertise it as ``max_tier`` and the promise and the
semantics drift apart on day one.

What this module does not restate
---------------------------------

Two questions belong to :mod:`looks.environment` and are consumed from it
rather than duplicated here: *which ffmpeg filters are GPL-gated*
(``needs_gpl``, over the committed ``ffmpeg_gates.json``) and *what licence
does this binary carry* (``probe`` -> ``FfmpegEnv.licence``, from ``ffmpeg
-L``). A second copy of either is how two detectors start disagreeing.
:func:`ffmpeg_terms` and :func:`assess_ffmpeg_chain` are the joins.

    >>> env = FfmpegEnv(path='/opt/homebrew/bin/ffmpeg', licence=Licence.GPL3,
    ...                 filters=frozenset({'lut3d', 'lutrgb', 'eq'}))
    >>> classify(ffmpeg_terms(env)).tier
    <Tier.COPYLEFT_TOOL: 'copyleft_tool'>
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from looks.environment import FfmpegEnv, Licence, needs_gpl

__all__ = [
    # The facts.
    "Coupling",
    "Reach",
    "Conveyance",
    "FieldOfUse",
    "RESTRICTED_FIELDS",
    "STRONG_COPYLEFT",
    "REACH_BY_SPDX",
    "EXCLUDED_SPDX",
    "reach_of",
    # The policy projection.
    "Tier",
    "Verdict",
    "DFLT_LADDER",
    "DFLT_MAX_TIER",
    "project_onto_ladder",
    # The records.
    "Patent",
    "Evidence",
    "Terms",
    "Assessment",
    "Policy",
    "DFLT_POLICY",
    # The decision.
    "classify",
    "assess",
    "check",
    # The refusals.
    "LooksLicenceError",
    "LicenceCeilingExceeded",
    "LicenceForbidden",
    "LicenceFieldRestricted",
    "LicenceUnknown",
    # The environment join.
    "SPDX_BY_FFMPEG_LICENCE",
    "NONFREE_PROHIBITION",
    "ffmpeg_terms",
    "assess_ffmpeg_chain",
    # The ledger.
    "ledger",
    "terms_for",
    "unverified_claims",
    "KNOWN_COMPONENTS",
    "KNOWN_REALISATION_PREFIXES",
    "LEDGER_PATH",
    "LEDGER_SCHEMA",
    # Honesty.
    "DISCLAIMER",
    "SEE_DISCLAIMER",
    "SPDX_LICENSE_LIST_VERSION",
    "STALE_AFTER_DAYS",
]

#: The SPDX License List release :data:`REACH_BY_SPDX` is written against.
#: Recorded because the mapping is only as current as the list it was read
#: from, and a widened row is a dated decision.
SPDX_LICENSE_LIST_VERSION = "3.28.0"  # released 2026-02-20

#: Days after which a ledger row's evidence is *reported* stale. Deliberately
#: never an automatic refusal: staleness is not a licence fact, refusing on it
#: would stop the package working offline for a non-licence reason, and a
#: refusal nobody can act on is the one people delete.
STALE_AFTER_DAYS = 365

#: The evidence ledger, one row per ``(provider, realisation, component)``.
LEDGER_PATH = Path(__file__).with_name("data") / "provider_terms.json"

#: Its schema tag. An unrecognised tag is refused loudly.
LEDGER_SCHEMA = "looks.provider_terms/v1"

DISCLAIMER = """\
looks reports observations, not legal conclusions.

A tier is not a legal determination. It is a position on a policy ladder this
project chose, derived from things that were mechanically observed on a stated
date, and every row records that observation so you can check the derivation
rather than trust the label.

looks refuses when it cannot observe. It does not adjudicate: where an
artifact's own statements about itself disagree, looks reports the
disagreement and refuses, and does not decide which statement is true.

Raising a ceiling is a decision about YOUR obligations, not about this
software's. Whether the licences and terms recorded here permit what you
intend to do is a question for you and your counsel.\
"""

#: The one-line pointer a refusal carries. The full :data:`DISCLAIMER` on every
#: raise becomes noise, and noise is how a disclaimer stops being read.
SEE_DISCLAIMER = (
    "looks reports observations, not legal conclusions — see looks.licence.DISCLAIMER."
)


# ===========================================================================
# THE FACTS. Four orthogonal axes, always recorded, always inspectable.
# Nothing below this point may collapse them into a scalar: the ladder is a
# projection OF these, and the projection is the part that is replaceable.
# ===========================================================================


class Coupling(enum.Enum):
    """How the implementation is reached — whether copyleft can touch us.

    This axis and :class:`Conveyance` are the two that separate the four cases
    people habitually conflate: executing a copyleft program you found
    (``SUBPROCESS`` + ``FINDS``), executing one you shipped (``+ CONVEYS``),
    linking one (``IN_PROCESS``), and calling a hosted one (``SERVICE``).
    """

    NONE = "none"  # no external implementation at all
    IN_PROCESS = "in_process"  # imported or linked into our address space
    SUBPROCESS = "subprocess"  # executed as a separate program
    SERVICE = "service"  # called over a network
    UNKNOWN = "unknown"


class Reach(enum.Enum):
    """How far the implementation's copyleft extends."""

    NONE = "none"  # permissive
    FILE = "file"  # MPL-2.0 and friends
    LIBRARY = "library"  # LGPL
    PROGRAM = "program"  # GPL
    NETWORK = "network"  # AGPL
    UNKNOWN = "unknown"


class Conveyance(enum.Enum):
    """Whether a *declared dependency closure* ships the implementation.

    Whose closure is the load-bearing word. A caller's pre-existing
    ``imageio-ffmpeg`` is :attr:`FINDS` — ``looks`` does not declare it and
    does not convey it. It becomes :attr:`CONVEYS` for whoever *does* declare
    it, which is why a ledger row is keyed on how you obtain the thing rather
    than on the thing: ``realisation="system"`` finds, ``realisation="pypi:x"``
    describes the position of a package that declares ``x``.
    """

    NONE = "none"
    FINDS = "finds"  # resolved from the machine it is run on
    CONVEYS = "conveys"  # a declared dependency closure ships it
    UNKNOWN = "unknown"


class FieldOfUse(enum.Enum):
    """Whether the *purpose* is permitted. Orthogonal to every axis above.

    No SPDX identifier carries this, so it is always a declared column and is
    never parsed out of a licence id: ``CC-BY-NC-SA-4.0`` is a listed
    identifier whose non-commercial character is not derivable from the string,
    and AnimeGANv2's terms have no identifier at all.
    """

    UNRESTRICTED = "unrestricted"
    NO_DERIVATIVES = "no_derivatives"
    NON_COMMERCIAL = "non_commercial"
    RESEARCH_ONLY = "research_only"
    UNKNOWN = "unknown"


#: The field-of-use values that are a restriction rather than an absence of
#: one. :attr:`FieldOfUse.UNKNOWN` is deliberately absent: "we do not know what
#: this restricts" is an unknown, and folding it in here would let a caller opt
#: into it, which is laundering unknown into permission.
RESTRICTED_FIELDS: frozenset[FieldOfUse] = frozenset(
    {
        FieldOfUse.NO_DERIVATIVES,
        FieldOfUse.NON_COMMERCIAL,
        FieldOfUse.RESEARCH_ONLY,
    }
)

#: The reaches that put an in-process implementation in the forbidden region.
STRONG_COPYLEFT: frozenset[Reach] = frozenset({Reach.PROGRAM, Reach.NETWORK})

#: SPDX identifier -> copyleft :class:`Reach`. SPDX is the vocabulary; the axes
#: are ours, because SPDX encodes none of them — it cannot say whether you
#: linked or executed, whether you shipped or found, or whether the field of
#: use is restricted. Anything unlisted is :attr:`Reach.UNKNOWN`, which
#: refuses, in both directions. Widening this table is a dated decision, never
#: a convenience.
REACH_BY_SPDX: Mapping[str, Reach] = {
    **{
        k: Reach.NONE
        for k in (
            "MIT",
            "MIT-0",
            "BSD-2-Clause",
            "BSD-3-Clause",
            "0BSD",
            "ISC",
            "Apache-2.0",
            "CC0-1.0",
            "Unlicense",
            "BlueOak-1.0.0",
            "Python-2.0",
        )
    },
    **{k: Reach.FILE for k in ("MPL-2.0", "EPL-2.0", "CDDL-1.0")},
    **{
        k: Reach.LIBRARY
        for k in (
            "LGPL-2.1-only",
            "LGPL-2.1-or-later",
            "LGPL-3.0-only",
            "LGPL-3.0-or-later",
        )
    },
    **{
        k: Reach.PROGRAM
        for k in (
            "GPL-2.0-only",
            "GPL-2.0-or-later",
            "GPL-3.0-only",
            "GPL-3.0-or-later",
            "SSPL-1.0",
        )
    },
    **{k: Reach.NETWORK for k in ("AGPL-3.0-only", "AGPL-3.0-or-later")},
}

#: Identifiers left out of :data:`REACH_BY_SPDX` on purpose, with the reason.
#: Recorded rather than merely omitted, because an absence looks identical to
#: an oversight and someone eventually "fixes" it.
EXCLUDED_SPDX: Mapping[str, str] = {
    "BSD-4-Clause": (
        "the advertising clause is a real obligation, and the text is "
        "word-for-word BSD-3-Clause plus one paragraph — so it must be "
        "excluded explicitly or it gets waved through as BSD"
    ),
}


def reach_of(spdx: str) -> Reach:
    """Map one SPDX identifier onto a :class:`Reach`.

    Compound expressions are **not** parsed. A component needing ``AND`` or
    ``OR`` is not one component: the conjunction that actually occurs — a
    permissive library inside a wheel that also conveys a GPL program — is two
    rows with two couplings, not one licence, and joining their axes
    manufactures "we link a GPL program in-process", a fact true of neither.

    Examples:
        >>> reach_of("Apache-2.0")
        <Reach.NONE: 'none'>
        >>> reach_of("LGPL-3.0-or-later")
        <Reach.LIBRARY: 'library'>
        >>> reach_of("AGPL-3.0-or-later")
        <Reach.NETWORK: 'network'>

        Unlisted is unknown, which refuses — including the one that is unlisted
        deliberately, and every ``LicenseRef-*``:

        >>> reach_of("BSD-4-Clause")
        <Reach.UNKNOWN: 'unknown'>
        >>> reach_of("Apache-2.0 AND GPL-3.0-or-later")
        <Reach.UNKNOWN: 'unknown'>
        >>> reach_of("LicenseRef-AnimeGANv2-NonCommercial")
        <Reach.UNKNOWN: 'unknown'>
    """
    return REACH_BY_SPDX.get(spdx, Reach.UNKNOWN)


# ===========================================================================
# THE POLICY PROJECTION. Five named rungs, and the function that computes them
# from three of the four axes. This half is a choice this project made; the
# half above is not. `Policy.order` is what makes the choice replaceable.
# ===========================================================================


class Tier(enum.Enum):
    """A rung on a ladder that is **policy, not fact**.

    Deliberately a plain :class:`enum.Enum` with no ordering of its own, so
    ``<`` cannot silently mean the shipped ladder when a caller supplied a
    different one. Ranking goes through :meth:`Policy.rank`.

    ==== ==================== ============================================
    rung tier                 obligation
    ==== ==================== ============================================
    0    ``PURE``             none — nothing external is reached
    1    ``PERMISSIVE``       notice retention on conveyance
    2    ``WEAK_COPYLEFT``    notice + relink; dynamic linkage only
    3    ``COPYLEFT_TOOL``    none on your code; a prohibition on a *future*
                              act, namely conveying the tool
    4    ``COPYLEFT_SHIPPED`` full source-offer duty, inherited downstream
    ==== ==================== ============================================

    Rungs 3 and 4 are ordered by obligation-inclusion, unambiguously. Rungs 2
    and 3 are **not**: in-process LGPL and subprocess GPL impose different
    duties, not more and fewer.
    """

    PURE = "pure"
    PERMISSIVE = "permissive"
    WEAK_COPYLEFT = "weak_copyleft"
    COPYLEFT_TOOL = "copyleft_tool"
    COPYLEFT_SHIPPED = "copyleft_shipped"


class Verdict(enum.Enum):
    """Which region of the axis space the terms landed in.

    :attr:`ON_LADDER` is **not** "admitted". :func:`classify` locates terms; it
    does not apply a ceiling, and reading ``ON_LADDER`` as permission is the
    false-permission direction. :func:`check` is what admits or refuses.

    The other three are the regions no ``max_tier`` reaches, kept apart because
    their remedies genuinely differ: raise the ceiling, no opt-in exists, a
    separate opt-in, supply evidence.
    """

    ON_LADDER = "on_ladder"
    FORBIDDEN = "forbidden"
    FIELD_RESTRICTED = "field_restricted"
    UNKNOWN = "unknown"


#: The shipped ladder, lowest rung first — a **default on** :class:`Policy`,
#: not a constant of the domain. Chosen for what this federation ships: Python
#: source that shells out and bundles nothing, where the question that matters
#: is "does copyleft touch our source" and rung 3 answers "no, unless you later
#: ship the tool". Pass your own to reorder it.
DFLT_LADDER: tuple[Tier, ...] = (
    Tier.PURE,
    Tier.PERMISSIVE,
    Tier.WEAK_COPYLEFT,
    Tier.COPYLEFT_TOOL,
    Tier.COPYLEFT_SHIPPED,
)

#: "Shelling out to a copyleft binary is fine", stated precisely.
DFLT_MAX_TIER = Tier.COPYLEFT_TOOL

#: How loudly each region must be reported. A provider made of several
#: components takes the **worst component verdict**, never a per-axis join.
_VERDICT_SEVERITY: tuple[Verdict, ...] = (
    Verdict.ON_LADDER,
    Verdict.FIELD_RESTRICTED,
    Verdict.UNKNOWN,
    Verdict.FORBIDDEN,
)


def _validate_ladder(order: Sequence[Tier]) -> tuple[Tier, ...]:
    """A ladder must rank every rung, or something lands where it cannot rank.

    Reordering is the point; dropping a rung is a hole, because
    :func:`project_onto_ladder` can return any of the five.
    """
    order = tuple(order)
    if set(order) != set(Tier) or len(order) != len(Tier):
        missing = sorted(t.name for t in set(Tier) - set(order))
        raise ValueError(
            f"a ladder must be a permutation of all {len(Tier)} tiers; "
            f"got {[t.name for t in order]}"
            + (f", missing {missing}" if missing else "")
        )
    return order


# ===========================================================================
# THE RECORDS. A row records an OBSERVATION; the tier is derived from it.
# ===========================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class Patent:
    """A patent encumbrance, which no copyright vocabulary can express.

    Forced into existence by one row: Ebsynth is *public-domain code*
    implementing Adobe's PatchMatch (US8861869B2, Active, anticipated expiry
    2030-08-16). Public domain is the most permissive value any copyright
    vocabulary has, and for that artifact it is the wrong answer.

    ``looks`` **records a patent and reports it; it never refuses on it.** A
    patent binds an act in a jurisdiction rather than a redistribution, and
    deciding whether it binds *your* act is the adjudication the honesty rule
    forbids. What it may not do is be invisible — see
    :attr:`Assessment.advisories`.
    """

    patent_id: str
    jurisdiction: str
    holder: str = ""
    status: str = "unknown"  # "active" | "expired" | "unknown"
    expiry: Optional[str] = None  # ISO-8601 date; None means unknown
    source_url: Optional[str] = None

    def is_live(self, *, today: Optional[date] = None) -> bool:
        """Whether it is still, or might still be, in force.

        Unknown expiry counts as live. Unknown is not permission here either.

        Examples:
            >>> ebsynth = Patent(patent_id="US8861869B2", jurisdiction="US",
            ...                  status="active", expiry="2030-08-16")
            >>> ebsynth.is_live(today=date(2026, 9, 2))
            True
            >>> ebsynth.is_live(today=date(2031, 1, 1))
            False
            >>> Patent(patent_id="?", jurisdiction="US").is_live()
            True
        """
        if self.status == "expired":
            return False
        if self.expiry is None:
            return True
        return date.fromisoformat(self.expiry) >= (today or date.today())


@dataclass(frozen=True, slots=True, kw_only=True)
class Evidence:
    """One observation, with enough context to be re-checked or disbelieved."""

    method: str  # "probe" | "inspect" | "read" | "resolve"
    observed: str
    observed_on: str  # ISO-8601 date
    command: Optional[str] = None
    source_url: Optional[str] = None

    def is_stale(self, *, today: Optional[date] = None) -> bool:
        """Older than :data:`STALE_AFTER_DAYS`. Reported, never auto-refused.

        Examples:
            >>> old = Evidence(method="read", observed="x",
            ...                observed_on="2020-01-01")
            >>> old.is_stale(today=date(2026, 9, 2))
            True
            >>> Evidence(method="read", observed="x", observed_on="2026-09-02"
            ...          ).is_stale(today=date(2026, 9, 2))
            False
        """
        elapsed = (today or date.today()) - date.fromisoformat(self.observed_on)
        return elapsed.days > STALE_AFTER_DAYS


@dataclass(frozen=True, slots=True, kw_only=True)
class Terms:
    """What one component declares about itself. **Terms, never a tier.**

    Keyed on ``(provider, realisation, component)``. ``realisation`` is *how
    you obtain it* — ``"system"`` found on PATH, ``"pypi:<dist>"`` conveyed by
    a distribution, ``"weights:<repo>"``, ``"hosted:<name>"`` — because that is
    what makes :attr:`Conveyance.CONVEYS` expressible at all: one row per way
    of getting a thing, not one row per thing. ``component`` is what separates
    a package's own code from the binary in its wheel, and a model's code from
    its weights: ``animegan2-pytorch`` is MIT code over weights with no licence
    at all, and a metadata scan gets that exactly backwards.

    Every default that could be a guess refuses instead: an undeclared
    :attr:`conveyance` or :attr:`field_of_use` is ``UNKNOWN``.
    """

    provider: str
    realisation: str
    spdx: str
    coupling: Coupling
    component: str = "code"
    conveyance: Conveyance = Conveyance.UNKNOWN
    field_of_use: FieldOfUse = FieldOfUse.UNKNOWN
    #: Override the :class:`Reach` derived from :attr:`spdx`. Requires a
    #: :attr:`note`, because an unexplained override silently makes a row the
    #: most permissive of its available readings — which is how a compound
    #: ``"Apache-2.0 AND GPL-3.0-or-later"`` row once classified PERMISSIVE.
    reach: Optional[Reach] = None
    patents: tuple[Patent, ...] = ()
    #: Conditions carried as data rather than adjudicated — a revenue
    #: threshold, a share-alike duty, a hardware floor.
    conditions: tuple[str, ...] = ()
    #: A recorded, unliftable prohibition: the terms grant this use to nobody
    #: (FFmpeg's "nonfree and unredistributable"), or to nobody here (a
    #: territorial exclusion). Not a rung and not a field-of-use opt-in.
    prohibition: Optional[str] = None
    #: The artifact's own statements disagree. Refuses as UNKNOWN — looks
    #: reports the disagreement and does not decide which statement is true.
    contradiction: Optional[str] = None
    #: ``False`` refuses as UNKNOWN. A row that is recorded but not established
    #: is not a fact, and "do not cite as fact" has to be executable to hold.
    verified: bool = True
    evidence: tuple[Evidence, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        for name in ("patents", "conditions", "evidence"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not (self.provider and self.realisation and self.component):
            raise ValueError(
                "Terms needs a provider, a realisation and a component: the "
                f"key is the triple, and got {self.key!r}"
            )
        if self.reach is not None and not self.note:
            raise ValueError(
                f"{self.key!r} overrides reach={self.reach.value!r} instead of "
                f"deriving it from spdx={self.spdx!r}, but records no note "
                "saying why. An unexplained override is the false-permission "
                "direction: state the reason or drop the override."
            )

    @property
    def key(self) -> tuple[str, str, str]:
        """``(provider, realisation, component)``."""
        return (self.provider, self.realisation, self.component)

    @property
    def resolved_reach(self) -> Reach:
        """The declared reach, or the one :func:`reach_of` derives.

        Examples:
            >>> t = Terms(provider="p", realisation="system",
            ...           spdx="GPL-2.0-or-later", coupling=Coupling.SUBPROCESS)
            >>> t.resolved_reach
            <Reach.PROGRAM: 'program'>
        """
        return self.reach if self.reach is not None else reach_of(self.spdx)


@dataclass(frozen=True, slots=True, kw_only=True)
class Assessment:
    """Where :func:`classify` located some terms. Not a permission.

    ``tier is None`` means *no rung* — either an axis is unknown or the terms
    are in the forbidden region. A :attr:`Verdict.FIELD_RESTRICTED` assessment
    **still carries its rung**, and that is the fix for a real defect: with the
    rung dropped, honouring a field-of-use opt-in left nothing for the ceiling
    test to compare, so opting into a research model silently waived the
    copyleft ceiling as well.
    """

    terms: Terms
    tier: Optional[Tier]
    verdict: Verdict
    reasons: tuple[str, ...] = ()
    #: Things a caller must be told but which are not refusals: live patents,
    #: recorded conditions, stale evidence, an explicit reach override.
    advisories: tuple[str, ...] = ()
    #: The per-component assessments when this came from :func:`assess`.
    #: :func:`check` applies the ceiling to **every** part, so a composite
    #: cannot admit something one of its components would not.
    parts: tuple["Assessment", ...] = ()

    @property
    def severity(self) -> int:
        """Rank in :data:`_VERDICT_SEVERITY`; higher is louder."""
        return _VERDICT_SEVERITY.index(self.verdict)


@dataclass(frozen=True, slots=True, kw_only=True)
class Policy:
    """A ceiling, plus the thing a ceiling deliberately cannot reach.

    **``max_tier`` is not the commercial-safe knob**, and saying so once here
    is cheaper than the drift: every rung is commercially usable, so what
    "commercial-safe only" means is ``allow_field_restricted=frozenset()`` —
    already the default.

    Examples:
        >>> Policy().max_tier
        <Tier.COPYLEFT_TOOL: 'copyleft_tool'>
        >>> Policy().admits(Tier.COPYLEFT_TOOL)
        True
        >>> Policy(max_tier=Tier.WEAK_COPYLEFT).admits(Tier.COPYLEFT_TOOL)
        False

        Off the ladder is off the ladder — no ceiling admits it:

        >>> Policy(max_tier=Tier.COPYLEFT_SHIPPED).admits(None)
        False
    """

    max_tier: Tier = DFLT_MAX_TIER
    #: Which field-of-use restrictions the caller has deliberately accepted.
    #: Empty by default, and **never** widened by ``max_tier``.
    allow_field_restricted: frozenset[FieldOfUse] = frozenset()
    order: tuple[Tier, ...] = DFLT_LADDER

    def __post_init__(self) -> None:
        object.__setattr__(self, "order", _validate_ladder(self.order))
        object.__setattr__(
            self, "allow_field_restricted", frozenset(self.allow_field_restricted)
        )
        bad = self.allow_field_restricted - RESTRICTED_FIELDS
        if bad:
            raise ValueError(
                "allow_field_restricted takes the restrictions you have "
                f"accepted, and {sorted(f.value for f in bad)} is not one: "
                f"{FieldOfUse.UNRESTRICTED.value} is the absence of a "
                f"restriction, and {FieldOfUse.UNKNOWN.value} is an unknown — "
                "opting into an unknown is laundering it into a permission."
            )

    def rank(self, tier: Tier) -> int:
        """Position on *this* policy's ladder."""
        try:
            return self.order.index(tier)
        except ValueError:
            raise ValueError(
                f"{tier!r} is not a rung on this policy's ladder "
                f"({[t.name for t in self.order]})"
            ) from None

    def admits(self, tier: Optional[Tier]) -> bool:
        """Whether the ceiling reaches ``tier``. ``None`` is never admitted."""
        return tier is not None and self.rank(tier) <= self.rank(self.max_tier)


#: The shipped ceiling: shell out to a copyleft binary freely, convey nothing,
#: and accept no field-of-use restriction.
DFLT_POLICY = Policy()


# ===========================================================================
# THE REFUSALS. Four types, because the REMEDIES differ — and a refusal that
# does not say what it is protecting against is one nobody can act on.
# ===========================================================================


class LooksLicenceError(Exception):
    """Base for every licence refusal."""


class LicenceCeilingExceeded(LooksLicenceError):
    """On the ladder, above the ceiling. Raise it, or pick a lower provider."""


class LicenceForbidden(LooksLicenceError):
    """Off the ladder, permanently. There is no opt-in and no ceiling."""


class LicenceFieldRestricted(LooksLicenceError):
    """Non-commercial / research-only / no-derivatives. Its OWN opt-in."""


class LicenceUnknown(LooksLicenceError):
    """Undeterminable, unprobeable, or self-contradictory. Unknown refuses."""


# ===========================================================================
# THE DECISION.
# ===========================================================================


def project_onto_ladder(terms: Terms) -> Optional[Tier]:
    """Project three axes onto a rung. **This is the policy half.**

    Coupling, reach and conveyance go in; a rung or ``None`` comes out.
    :class:`FieldOfUse` is deliberately not consulted — it is not commensurable
    with copyleft strength and belongs off the ladder entirely.

    ``None`` means *no rung*: an axis is unknown, or the terms are in the
    forbidden region. Which of the two it is, is :func:`classify`'s answer.

    Note what conveyance does and does not do. It lifts rung 3 to rung 4 —
    conveying a GPL *program* is a source-offer duty you inherit — and it does
    nothing anywhere else, because that is the ladder as decided. (Section 5.7
    of the decisions document contains one row on the other side of this, the
    vendored LGPL shaders; its own manylinux-wheel row contradicts it, and both
    cannot hold under one projection.)

    Examples:
        >>> found = Terms(provider="ffmpeg", realisation="system",
        ...               spdx="GPL-3.0-or-later", component="binary",
        ...               coupling=Coupling.SUBPROCESS,
        ...               conveyance=Conveyance.FINDS,
        ...               field_of_use=FieldOfUse.UNRESTRICTED)
        >>> project_onto_ladder(found)
        <Tier.COPYLEFT_TOOL: 'copyleft_tool'>

        The same binary, shipped inside a wheel you declare:

        >>> project_onto_ladder(
        ...     Terms(provider="ffmpeg", realisation="pypi:imageio-ffmpeg",
        ...           spdx="GPL-2.0-or-later", component="binary",
        ...           coupling=Coupling.SUBPROCESS,
        ...           conveyance=Conveyance.CONVEYS,
        ...           field_of_use=FieldOfUse.UNRESTRICTED))
        <Tier.COPYLEFT_SHIPPED: 'copyleft_shipped'>

        And linked instead of executed, which is off the ladder:

        >>> project_onto_ladder(
        ...     Terms(provider="ultralytics", realisation="pypi:ultralytics",
        ...           spdx="AGPL-3.0-or-later", coupling=Coupling.IN_PROCESS,
        ...           conveyance=Conveyance.CONVEYS,
        ...           field_of_use=FieldOfUse.UNRESTRICTED)) is None
        True
    """
    reach = terms.resolved_reach
    if (
        terms.coupling is Coupling.UNKNOWN
        or reach is Reach.UNKNOWN
        or terms.conveyance is Conveyance.UNKNOWN
    ):
        return None
    if terms.coupling is Coupling.IN_PROCESS and reach in STRONG_COPYLEFT:
        return None  # the forbidden region is not a rung
    if terms.coupling is Coupling.NONE:
        return Tier.PURE
    if reach is Reach.NONE:
        return Tier.PERMISSIVE
    if reach in (Reach.FILE, Reach.LIBRARY):
        return Tier.WEAK_COPYLEFT
    return (
        Tier.COPYLEFT_SHIPPED
        if terms.conveyance is Conveyance.CONVEYS
        else Tier.COPYLEFT_TOOL
    )


def _unknown_axes(terms: Terms) -> tuple[str, ...]:
    """Which axes are unknown, named for a refusal message."""
    named = (
        ("coupling", terms.coupling is Coupling.UNKNOWN),
        ("reach", terms.resolved_reach is Reach.UNKNOWN),
        ("conveyance", terms.conveyance is Conveyance.UNKNOWN),
        ("field_of_use", terms.field_of_use is FieldOfUse.UNKNOWN),
    )
    return tuple(name for name, is_unknown in named if is_unknown)


def _advisories(terms: Terms, *, today: Optional[date] = None) -> tuple[str, ...]:
    """Everything a caller must be told that is not itself a refusal."""
    out: list[str] = []
    for patent in terms.patents:
        if patent.is_live(today=today):
            expiry = patent.expiry or "unknown expiry"
            holder = f" held by {patent.holder}" if patent.holder else ""
            out.append(
                f"patent {patent.patent_id} ({patent.jurisdiction}{holder}, "
                f"status {patent.status}, {expiry}) reads on this "
                "implementation. looks records it and does not refuse on it: a "
                "patent binds an act in a jurisdiction, and whether it binds "
                "yours is not a question looks may answer."
            )
    out.extend(f"condition: {c}" for c in terms.conditions)
    if terms.reach is not None:
        out.append(
            f"reach is recorded explicitly as {terms.reach.value!r} rather than "
            f"derived from spdx {terms.spdx!r} — see the note on this row"
        )
    for ev in terms.evidence:
        if ev.is_stale(today=today):
            out.append(
                f"evidence dated {ev.observed_on} is older than "
                f"{STALE_AFTER_DAYS} days. Reported, never auto-refused: "
                "staleness is not a licence fact."
            )
    return tuple(out)


def classify(terms: Terms, *, today: Optional[date] = None) -> Assessment:
    """Locate ``terms`` in the axis space. Applies **no** ceiling.

    The branch order is the design, and two things about it are load-bearing.

    **A field-restricted assessment still carries its ladder rung.** Dropping
    it is how the first version of this design let ``Policy(max_tier=PURE,
    allow_field_restricted={NON_COMMERCIAL})`` admit a subprocess GPL-3
    conveying provider: the opt-in was honoured, there was no tier left, and
    the ceiling test never ran.

    **Record-level unknowns come before the region checks; axis-level unknowns
    come after the field check.** If the record cannot be trusted at all — it
    is unverified, or the artifact contradicts itself — nothing may be
    concluded from its axes. But a row whose reach is unreadable while its
    field of use is plainly non-commercial is more usefully refused as
    field-restricted, and nothing leaks: opting into that field leaves
    ``tier is None``, and the ceiling test refuses it as unknown.

    Examples:
        >>> ffmpeg = Terms(provider="ffmpeg", realisation="system",
        ...                component="binary", spdx="GPL-3.0-or-later",
        ...                coupling=Coupling.SUBPROCESS,
        ...                conveyance=Conveyance.FINDS,
        ...                field_of_use=FieldOfUse.UNRESTRICTED)
        >>> a = classify(ffmpeg)
        >>> a.verdict, a.tier
        (<Verdict.ON_LADDER: 'on_ladder'>, <Tier.COPYLEFT_TOOL: 'copyleft_tool'>)

        A field-restricted row keeps its rung, which is what the ceiling test
        needs after an opt-in is honoured:

        >>> nc = Terms(provider="m", realisation="weights:m", component="weights",
        ...            spdx="GPL-3.0-or-later", coupling=Coupling.SUBPROCESS,
        ...            conveyance=Conveyance.CONVEYS,
        ...            field_of_use=FieldOfUse.NON_COMMERCIAL)
        >>> classify(nc).verdict, classify(nc).tier
        (<Verdict.FIELD_RESTRICTED: 'field_restricted'>, <Tier.COPYLEFT_SHIPPED: 'copyleft_shipped'>)

        Unknown is a refusal, and it is a *different* refusal:

        >>> classify(Terms(provider="x", realisation="pypi:x",
        ...                spdx="LicenseRef-nobody-wrote-one",
        ...                coupling=Coupling.IN_PROCESS,
        ...                conveyance=Conveyance.CONVEYS)).verdict
        <Verdict.UNKNOWN: 'unknown'>
    """
    advisories = _advisories(terms, today=today)
    reach = terms.resolved_reach

    def verdict(v: Verdict, tier: Optional[Tier], *reasons: str) -> Assessment:
        return Assessment(
            terms=terms,
            tier=tier,
            verdict=v,
            reasons=reasons,
            advisories=advisories,
        )

    if terms.prohibition:
        return verdict(
            Verdict.FORBIDDEN,
            None,
            f"a recorded prohibition, which no ceiling and no opt-in lifts: "
            f"{terms.prohibition}",
        )

    if not terms.verified:
        return verdict(
            Verdict.UNKNOWN,
            None,
            "this row is recorded but UNVERIFIED, so its axes are not facts "
            "and nothing may be derived from them",
        )

    if terms.contradiction:
        return verdict(
            Verdict.UNKNOWN,
            None,
            f"the artifact's own statements disagree, and looks does not "
            f"adjudicate which is true: {terms.contradiction}",
        )

    if terms.coupling is Coupling.IN_PROCESS and reach in STRONG_COPYLEFT:
        return verdict(
            Verdict.FORBIDDEN,
            None,
            f"{reach.value}-reach copyleft linked in-process. This is not a "
            "rung: a rung is something a ceiling can be raised to reach, and "
            "the rule here is always refuse.",
        )

    tier = project_onto_ladder(terms)

    if terms.field_of_use in RESTRICTED_FIELDS:
        return verdict(
            Verdict.FIELD_RESTRICTED,
            tier,
            f"the field of use is {terms.field_of_use.value}. This is not a "
            "rung and max_tier cannot grant it — agreeing to run a copyleft "
            "binary is not agreeing to non-commercial terms.",
        )

    unknown = _unknown_axes(terms)
    if unknown:
        return verdict(
            Verdict.UNKNOWN,
            None,
            f"{', '.join(unknown)} {'is' if len(unknown) == 1 else 'are'} "
            f"UNKNOWN, and unknown is a refusal — not a default, not a guess, "
            f"not 'probably permissive'",
        )

    return verdict(Verdict.ON_LADDER, tier)


def assess(
    terms: Iterable[Terms],
    *,
    order: Sequence[Tier] = DFLT_LADDER,
    today: Optional[date] = None,
) -> Assessment:
    """Assess a provider made of several components: **the worst one wins.**

    Deliberately *not* a per-axis join. Join OpenCV's Apache-2.0 in-process C++
    with the GPL ffmpeg conveyed in the same wheel and you get "we link a GPL
    program in-process" — a chimera true of neither component, which then
    classifies FORBIDDEN. Each component keeps its own row, the caller sees
    which half is the problem, and :func:`check` applies the ceiling to **every
    part**, so ``order`` only decides which component gets named first.

    Examples:
        >>> code = Terms(provider="moviepy", realisation="pypi:moviepy",
        ...              spdx="MIT", coupling=Coupling.IN_PROCESS,
        ...              conveyance=Conveyance.CONVEYS,
        ...              field_of_use=FieldOfUse.UNRESTRICTED)
        >>> shipped = Terms(provider="moviepy", realisation="pypi:moviepy",
        ...                 component="transitive", spdx="GPL-2.0-or-later",
        ...                 coupling=Coupling.SUBPROCESS,
        ...                 conveyance=Conveyance.CONVEYS,
        ...                 field_of_use=FieldOfUse.UNRESTRICTED)
        >>> classify(code).tier
        <Tier.PERMISSIVE: 'permissive'>
        >>> assess([code, shipped]).tier
        <Tier.COPYLEFT_SHIPPED: 'copyleft_shipped'>
        >>> len(assess([code, shipped]).parts)
        2
    """
    order = _validate_ladder(order)
    parts = tuple(classify(t, today=today) for t in terms)
    if not parts:
        raise ValueError(
            "assess() needs at least one Terms row; an empty component list is "
            "not a clean bill of health, it is nothing having been looked at"
        )

    def rank(part: Assessment) -> tuple[int, int]:
        return (part.severity, -1 if part.tier is None else order.index(part.tier))

    decisive = max(parts, key=rank)
    seen: list[str] = []
    for part in parts:
        for advisory in part.advisories:
            if advisory not in seen:
                seen.append(advisory)
    return Assessment(
        terms=decisive.terms,
        tier=decisive.tier,
        verdict=decisive.verdict,
        reasons=tuple(r for p in parts for r in p.reasons),
        advisories=tuple(seen),
        parts=parts,
    )


def _why(terms: Terms) -> str:
    """The dated observations behind a refusal, formatted for a message."""
    lines = []
    for ev in terms.evidence:
        how = ev.command or ev.method
        lines.append(f"       Observed {ev.observed_on} by `{how}`: {ev.observed}")
        if ev.source_url:
            lines.append(f"       See {ev.source_url}")
    if not lines:
        lines.append("       (no evidence recorded — that is itself a defect)")
    return "\n".join(lines)


def _alternatives(alternatives: Sequence[str]) -> str:
    if not alternatives:
        return ""
    return (
        "\n\n  A lower-tier implementation of this capability exists:\n"
        f"       {', '.join(alternatives)}"
    )


def _check_one(
    assessment: Assessment,
    policy: Policy,
    subject: str,
    *,
    alternatives: Sequence[str],
) -> None:
    """The whole rule, for one component. Falls through; never returns early."""
    terms = assessment.terms
    where = f"{terms.provider} [{terms.realisation}, {terms.component}]"
    why = _why(terms)
    tail = f"\n\n  {SEE_DISCLAIMER}"

    if assessment.verdict is Verdict.FORBIDDEN:
        raise LicenceForbidden(
            f"{subject}: {where} is refused outright.\n\n"
            f"  Why: {' '.join(assessment.reasons)}\n{why}\n\n"
            "  There is no opt-in and no ceiling: max_tier does not reach this "
            "region, by design. "
            + (
                f"Use one of: {', '.join(alternatives)}."
                if alternatives
                else "Use a different implementation."
            )
            + tail
        )

    if assessment.verdict is Verdict.UNKNOWN:
        raise LicenceUnknown(
            f"{subject}: cannot determine a licence position for {where}.\n\n"
            f"  Why: {' '.join(assessment.reasons)}\n{why}\n\n"
            "  looks refuses rather than guessing, and this refusal is not the "
            "ceiling's: raising max_tier will not lift it. Supply evidence for "
            "this provider, or choose one that can be observed."
            + _alternatives(alternatives)
            + tail
        )

    # Field of use is honoured here and then FALLS THROUGH to the ceiling test
    # below. Returning here is the defect this ordering exists to prevent: a
    # caller who opted into a research licence had thereby also opted out of
    # their own copyleft ceiling.
    if assessment.verdict is Verdict.FIELD_RESTRICTED:
        field_of_use = terms.field_of_use
        if field_of_use not in policy.allow_field_restricted:
            raise LicenceFieldRestricted(
                f"{subject}: {where} restricts the field of use "
                f"({field_of_use.value}).\n\n"
                f"  Why: {' '.join(assessment.reasons)}\n{why}\n\n"
                "  max_tier cannot grant this, at any setting. Opt in "
                "separately and deliberately:\n"
                f"       Policy(allow_field_restricted="
                f"{{FieldOfUse.{field_of_use.name}}})"
                + _alternatives(alternatives)
                + tail
            )

    if assessment.tier is None:
        raise LicenceUnknown(
            f"{subject}: {where} has no rung on the ladder, so no ceiling can "
            "admit it.\n\n"
            f"  Why: {' '.join(assessment.reasons) or 'an axis is unknown'}\n"
            f"{why}\n\n"
            "  Where a field-of-use opt-in was honoured, this is the ceiling "
            "test still running — and finding nothing to compare. Supply the "
            "missing axis." + tail
        )

    if not policy.admits(assessment.tier):
        raise LicenceCeilingExceeded(
            f"{subject} needs tier {assessment.tier.name}; the ceiling in "
            f"force is {policy.max_tier.name}.\n\n"
            f"  Why: resolved to {where}\n{why}"
            + _alternatives(alternatives)
            + "\n\n  Or raise the ceiling deliberately:\n"
            f"       Policy(max_tier=Tier.{assessment.tier.name})\n"
            "  Note that max_tier is about copyleft only. If what you want is "
            "commercial-safe-only, that is allow_field_restricted=frozenset(), "
            "which is already the default." + tail
        )


def check(
    assessment: Assessment,
    policy: Policy,
    subject: str,
    *,
    alternatives: Sequence[str] = (),
) -> None:
    """Raise unless ``policy`` admits ``assessment``. Returns ``None`` on pass.

    Every component is checked, loudest first, so a composite can never admit
    something one of its parts would not — and so the message names the
    component that is actually the problem.

    A refusal message names, in order: the subject, the tier it needs, the
    ceiling in force, *why* (the resolved provider and the dated observations
    that decided it), how to opt in, and any lower-tier alternative. A refusal
    that only says no is the one people remove.

    Args:
        assessment: From :func:`classify` or :func:`assess`.
        policy: The ceiling in force, plus any field-of-use opt-in.
        subject: What is being refused — an effect name, an implementation id.
        alternatives: Lower-tier implementations of the same capability, named
            in the message.

    Raises:
        LicenceForbidden: Off the ladder permanently; no opt-in exists.
        LicenceUnknown: Undeterminable, unverified, or self-contradictory.
        LicenceFieldRestricted: Restricted purpose, and no opt-in was given.
        LicenceCeilingExceeded: On the ladder, above the ceiling.

    Examples:
        >>> ffmpeg = classify(Terms(
        ...     provider="ffmpeg", realisation="system", component="binary",
        ...     spdx="GPL-3.0-or-later", coupling=Coupling.SUBPROCESS,
        ...     conveyance=Conveyance.FINDS,
        ...     field_of_use=FieldOfUse.UNRESTRICTED))
        >>> check(ffmpeg, DFLT_POLICY, "effect 'gamma'") is None
        True
        >>> check(ffmpeg, Policy(max_tier=Tier.WEAK_COPYLEFT), "effect 'gamma'")
        Traceback (most recent call last):
            ...
        looks.licence.LicenceCeilingExceeded: ...

        The refusal says what it is protecting against, and what to do:

        >>> try:
        ...     check(ffmpeg, Policy(max_tier=Tier.WEAK_COPYLEFT), "'gamma'",
        ...           alternatives=["gamma.ffmpeg.lutyuv"])
        ... except LicenceCeilingExceeded as e:
        ...     print(str(e).splitlines()[0])
        'gamma' needs tier COPYLEFT_TOOL; the ceiling in force is WEAK_COPYLEFT.
    """
    parts = assessment.parts or (assessment,)
    for part in sorted(parts, key=lambda p: p.severity, reverse=True):
        _check_one(part, policy, subject, alternatives=alternatives)


# ===========================================================================
# THE ENVIRONMENT JOIN. looks.environment owns "what licence is this binary"
# and "is this filter GPL-gated"; this half turns those answers into Terms.
# ===========================================================================

#: What ``ffmpeg -L`` reports, as an SPDX identifier. "or-later" throughout,
#: because FFmpeg's own cascade says "version N, or (at your option) any later
#: version". :attr:`Licence.NONFREE` and :attr:`Licence.UNKNOWN` are absent on
#: purpose: neither is a licence position, and each refuses differently.
SPDX_BY_FFMPEG_LICENCE: Mapping[Licence, str] = {
    Licence.LGPL21: "LGPL-2.1-or-later",
    Licence.LGPL3: "LGPL-3.0-or-later",
    Licence.GPL2: "GPL-2.0-or-later",
    Licence.GPL3: "GPL-3.0-or-later",
}

#: The nonfree refusal, recorded as a prohibition so it is checked **before**
#: any ceiling comparison and cannot be folded into UNKNOWN — whose remedy text
#: is "supply evidence", which is exactly wrong here. FFmpeg's own words for
#: such a build are "nonfree and unredistributable", which is the
#: best-characterised refusal available and one no evidence can lift.
NONFREE_PROHIBITION = (
    "FFmpeg calls this build nonfree and unredistributable. That is the "
    "project's own characterisation of it, not an inference, and no evidence "
    "lifts it. The incremental capability is nil for this package in any case: "
    "libfdk_aac and libmpeghdec are audio, decklink is capture hardware, and "
    "the libnpp filters have LGPL equivalents in unsharp and convolution."
)


def ffmpeg_terms(
    env: FfmpegEnv,
    *,
    realisation: str = "system",
    today: Optional[date] = None,
) -> Terms:
    """One probed ffmpeg binary, as :class:`Terms`.

    **The environment is an argument.** This takes an :class:`FfmpegEnv` a
    caller probed and never probes for itself, because there is not one ffmpeg
    on a machine: measured on the machine this package was written on, ``PATH``
    is 8.1 / GPL-3 / 481 filters while ``imageio-ffmpeg``'s bundled binary is
    7.1 / GPL-2 / 484, and the filter sets are non-nested. A component that
    probes on its own behalf silently binds to whichever binary was first on
    ``PATH``.

    Args:
        env: From :func:`looks.environment.probe`.
        realisation: How this binary was obtained — ``"system"`` for found on
            ``PATH``, ``"pypi:<dist>"`` for one a distribution ships. It is
            what decides :class:`Conveyance`, and therefore rung 3 versus 4.
        today: Stamped on the evidence; for tests.

    Examples:
        >>> gpl = FfmpegEnv(path='/opt/homebrew/bin/ffmpeg',
        ...                 version='ffmpeg version 8.1',
        ...                 licence=Licence.GPL3,
        ...                 filters=frozenset({'lut3d', 'eq'}))
        >>> classify(ffmpeg_terms(gpl)).tier
        <Tier.COPYLEFT_TOOL: 'copyleft_tool'>

        The same source, built without ``--enable-gpl``, is two rungs lower —
        which is the whole reason a tier cannot be a constant:

        >>> lgpl = FfmpegEnv(path='/usr/local/bin/ffmpeg-lgpl',
        ...                  licence=Licence.LGPL21,
        ...                  filters=frozenset({'lut3d'}))
        >>> classify(ffmpeg_terms(lgpl)).tier
        <Tier.WEAK_COPYLEFT: 'weak_copyleft'>

        A binary nobody probed is unknown, and unknown refuses:

        >>> classify(ffmpeg_terms(FfmpegEnv())).verdict
        <Verdict.UNKNOWN: 'unknown'>
    """
    stamp = (today or date.today()).isoformat()
    conveyance = Conveyance.FINDS if realisation == "system" else Conveyance.CONVEYS

    def build(**kwargs) -> Terms:
        return Terms(
            provider="ffmpeg",
            realisation=realisation,
            component="binary",
            coupling=Coupling.SUBPROCESS,
            conveyance=conveyance,
            **kwargs,
        )

    if not env.available:
        detail = "; ".join(env.notes) or "the environment was never probed"
        return build(
            spdx="LicenseRef-UNPROBED",
            field_of_use=FieldOfUse.UNKNOWN,
            evidence=(
                Evidence(
                    method="probe",
                    command="looks.environment.probe",
                    observed=f"no usable ffmpeg: {detail}",
                    observed_on=stamp,
                ),
            ),
            note="Not probed, or the probe did not answer. Unknown refuses.",
        )

    observed = (
        f"`ffmpeg -L` classified as {env.licence.value}; "
        f"{env.version or 'version unreported'}; {len(env.filters)} filters. "
        f"configuration (diagnostics only, never a licence): "
        f"{env.configuration or 'unreported'}"
    )
    evidence = (
        Evidence(
            method="probe",
            command=f"{env.path} -L; {env.path} -filters",
            observed=observed,
            source_url="https://ffmpeg.org/legal.html",
            observed_on=stamp,
        ),
    )

    if env.licence is Licence.NONFREE:
        return build(
            spdx="LicenseRef-FFmpeg-nonfree",
            field_of_use=FieldOfUse.UNKNOWN,
            prohibition=NONFREE_PROHIBITION,
            evidence=evidence,
            note="Refused before any ceiling comparison. Detection is free: "
            "the nonfree branch is first in `-L`'s cascade.",
        )

    if env.licence is Licence.UNKNOWN:
        return build(
            spdx="LicenseRef-UNCLASSIFIED",
            field_of_use=FieldOfUse.UNKNOWN,
            evidence=evidence,
            note="`ffmpeg -L` matched no known licence statement. No evidence "
            "of GPL is not evidence of LGPL.",
        )

    return build(
        spdx=SPDX_BY_FFMPEG_LICENCE[env.licence],
        field_of_use=FieldOfUse.UNRESTRICTED,
        evidence=evidence,
    )


def assess_ffmpeg_chain(
    filters: Sequence[str],
    *,
    env: FfmpegEnv,
    realisation: str = "system",
    today: Optional[date] = None,
) -> Assessment:
    """The licence position of a filter chain on one probed binary.

    Joins the two things :mod:`looks.environment` already answers — what the
    binary's ``-L`` says, and which filters FFmpeg gates behind
    ``--enable-gpl`` — without restating either.

    Three rules, in the order they bite:

    1. **A nonfree build is refused first**, before any ceiling comparison.
    2. **A GPL-gated filter does not raise the tier; the binary already has
       it.** Every filter in a GPL build is reached through a GPL program, so
       the chain's position is the *binary's* rung. What the gated filters
       change is the *reason*, which the refusal message needs: an ``eq`` look
       does not merely cost more obligations, it does not exist on an LGPL
       build at all.
    3. **A disagreement between the two authorities refuses.** A binary whose
       ``-L`` says LGPL while it carries filters FFmpeg gates behind
       ``--enable-gpl`` is contradicting itself, exactly as ``av`` does, and
       ``looks`` reports the disagreement rather than picking a side.

    Availability is reported, never refused here: a filter absent from the
    declared environment is a compile-time refusal (it is the *stronger* check,
    catching ``--disable-filter=eq`` on a GPL build, which no tier table can),
    and that refusal belongs to the compiler. It arrives as an advisory.

    Raises:
        looks.environment.UnknownFilter: A name that is not an ffmpeg filter.
            Deliberately not swallowed: this function reports a name carrying
            no gate as GPL-free, so an unrecognised one would be a *computed*
            false permission at the licence tier's entry point.

    Examples:
        >>> gpl = FfmpegEnv(path='/opt/homebrew/bin/ffmpeg',
        ...                 licence=Licence.GPL3,
        ...                 filters=frozenset({'lut3d', 'lutrgb', 'eq'}))
        >>> a = assess_ffmpeg_chain(['lut3d', 'lutrgb'], env=gpl)
        >>> a.tier
        <Tier.COPYLEFT_TOOL: 'copyleft_tool'>

        The Que Calor chain is LGPL-clean, so the same chain on an LGPL build
        is two rungs lower — and the grade filter everyone reaches for is not:

        >>> lgpl = FfmpegEnv(path='/usr/local/bin/ffmpeg-lgpl',
        ...                  licence=Licence.LGPL21,
        ...                  filters=frozenset({'lut3d', 'lutrgb'}))
        >>> assess_ffmpeg_chain(['lut3d', 'lutrgb'], env=lgpl).tier
        <Tier.WEAK_COPYLEFT: 'weak_copyleft'>
        >>> assess_ffmpeg_chain(['eq'], env=gpl).reasons[0]
        "it reaches filters FFmpeg gates behind --enable-gpl: ('eq',)"
    """
    terms = ffmpeg_terms(env, realisation=realisation, today=today)
    base = classify(terms, today=today)

    # Validated against the committed n8.1 universe, not against this build:
    # a real filter missing from one binary is an availability fact, while a
    # name that is not an ffmpeg filter at all is a typo, and they need
    # different answers.
    gated = needs_gpl(filters)
    present_gated = tuple(f for f in gated if env.has_filter(f))
    missing = env.missing(filters)

    extra: list[str] = []
    if missing:
        extra.append(
            f"not in the declared environment: {missing}. Rule 29 refuses this "
            f"at compile time — availability is the stronger check, and it is "
            f"the compiler's to make. Probed binary: {env.path}."
        )

    if present_gated and env.licence in (Licence.LGPL21, Licence.LGPL3):
        contradicted = replace(
            terms,
            contradiction=(
                f"`ffmpeg -L` classifies this build as {env.licence.value}, "
                f"yet it carries {list(present_gated)}, which FFmpeg's own "
                f"configure gates behind --enable-gpl. Unpatched configure "
                f"cannot produce that combination."
            ),
        )
        out = classify(contradicted, today=today)
        return Assessment(
            terms=out.terms,
            tier=out.tier,
            verdict=out.verdict,
            reasons=out.reasons,
            advisories=out.advisories + tuple(extra),
        )

    reasons = base.reasons
    if gated:
        reasons = reasons + (
            f"it reaches filters FFmpeg gates behind --enable-gpl: {gated}",
        )
    return Assessment(
        terms=base.terms,
        tier=base.tier,
        verdict=base.verdict,
        reasons=reasons,
        advisories=base.advisories + tuple(extra),
    )


# ===========================================================================
# THE LEDGER. One row per (provider, realisation, component), tiers DERIVED.
# ===========================================================================

#: The component vocabulary the ledger is validated against. Closed on purpose:
#: ``code`` and ``weights`` being separate rows is what keeps a permissively
#: licensed port of non-permissive weights from reading as permissive.
KNOWN_COMPONENTS: frozenset[str] = frozenset(
    {"code", "weights", "model", "binary", "assets", "transitive", "bundled-ffmpeg"}
)

#: How a row may say where the thing came from. ``@`` separates a platform,
#: because a wheel's tier is a property of the wheel: one distribution name
#: covers three different answers across macOS arm64, macOS x86_64 and
#: manylinux.
KNOWN_REALISATION_PREFIXES: tuple[str, ...] = (
    "system",
    "self",
    "any",
    "pypi:",
    "github:",
    "weights:",
    "hosted:",
    "commercial:",
)

_REQUIRED_ROW_KEYS = frozenset({"provider", "realisation", "component", "spdx"})
_OPTIONAL_ROW_KEYS = frozenset(
    {
        "coupling",
        "conveyance",
        "field_of_use",
        "reach",
        "patents",
        "conditions",
        "prohibition",
        "contradiction",
        "verified",
        "evidence",
        "note",
    }
)


def _enum_from(value: str, enum_cls, where: str):
    try:
        return enum_cls(value)
    except ValueError:
        raise ValueError(
            f"{where}: {value!r} is not a {enum_cls.__name__}; "
            f"expected one of {[m.value for m in enum_cls]}"
        ) from None


def _terms_from_row(row: Mapping[str, object]) -> Terms:
    """One ledger row, validated strictly. A malformed row is not a permission."""
    where = f"{row.get('provider')}/{row.get('realisation')}/{row.get('component')}"
    keys = set(row)
    if not _REQUIRED_ROW_KEYS <= keys:
        raise ValueError(f"{where}: missing {sorted(_REQUIRED_ROW_KEYS - keys)}")
    unexpected = keys - _REQUIRED_ROW_KEYS - _OPTIONAL_ROW_KEYS
    if unexpected:
        raise ValueError(
            f"{where}: unexpected key(s) {sorted(unexpected)}. A typo'd key "
            "would otherwise be silently dropped, and a dropped axis defaults "
            "to something."
        )

    component = str(row["component"])
    if component not in KNOWN_COMPONENTS:
        raise ValueError(
            f"{where}: component {component!r} is outside the vocabulary "
            f"{sorted(KNOWN_COMPONENTS)}"
        )
    realisation = str(row["realisation"])
    if not realisation.startswith(KNOWN_REALISATION_PREFIXES):
        raise ValueError(
            f"{where}: realisation {realisation!r} does not start with one of "
            f"{list(KNOWN_REALISATION_PREFIXES)}"
        )

    coupling = _enum_from(str(row.get("coupling", "unknown")), Coupling, where)
    conveyance = _enum_from(str(row.get("conveyance", "unknown")), Conveyance, where)
    field_of_use = _enum_from(
        str(row.get("field_of_use", "unknown")), FieldOfUse, where
    )
    if realisation == "system" and conveyance not in (
        Conveyance.FINDS,
        Conveyance.NONE,
    ):
        raise ValueError(
            f"{where}: realisation 'system' means it was found on the machine, "
            f"so conveyance cannot be {conveyance.value!r}"
        )

    reach = row.get("reach")
    evidence = tuple(
        Evidence(
            method=str(e["method"]),
            observed=str(e["observed"]),
            observed_on=str(e["observed_on"]),
            command=e.get("command"),
            source_url=e.get("source_url"),
        )
        for e in row.get("evidence", ())  # type: ignore[union-attr]
    )
    for ev in evidence:
        date.fromisoformat(ev.observed_on)  # raises on a malformed stamp
    verified = bool(row.get("verified", False))
    if verified and not evidence:
        raise ValueError(
            f"{where}: marked verified with no evidence. A verdict with no "
            "observation behind it is the thing this ledger exists to prevent."
        )

    return Terms(
        provider=str(row["provider"]),
        realisation=realisation,
        component=component,
        spdx=str(row["spdx"]),
        coupling=coupling,
        conveyance=conveyance,
        field_of_use=field_of_use,
        reach=None if reach is None else _enum_from(str(reach), Reach, where),
        patents=tuple(
            Patent(**p)  # type: ignore[arg-type]
            for p in row.get("patents", ())  # type: ignore[union-attr]
        ),
        conditions=tuple(row.get("conditions", ())),  # type: ignore[arg-type]
        prohibition=row.get("prohibition"),  # type: ignore[arg-type]
        contradiction=row.get("contradiction"),  # type: ignore[arg-type]
        verified=verified,
        evidence=evidence,
        note=str(row.get("note", "")),
    )


@lru_cache(maxsize=1)
def _raw_ledger() -> Mapping[str, object]:
    """The ledger file, parsed once. Lazy: ``import looks`` does no file I/O."""
    doc = json.loads(LEDGER_PATH.read_text())
    schema = doc.get("schema")
    if schema != LEDGER_SCHEMA:
        raise ValueError(
            f"{LEDGER_PATH.name} carries schema {schema!r}; this build reads "
            f"{LEDGER_SCHEMA!r}. An unrecognised tag is refused loudly rather "
            "than read optimistically."
        )
    return doc


@lru_cache(maxsize=1)
def ledger() -> tuple[Terms, ...]:
    """The evidence ledger: what was observed, about whom, and when.

    **No tier is stored.** Every row records axes and the dated observations
    behind them; the tier comes from :func:`classify`, so a reader can check
    the derivation rather than trust a label — and the test suite re-derives
    every row. Rows are keyed per component, because the compound cases
    (OpenCV, moviepy) cannot round-trip through a per-package key.

    It is a record of observations, **not a lookup table for a live machine**.
    In particular, do not read the ``ffmpeg``/``system`` row to decide what a
    caller's ffmpeg is: use :func:`ffmpeg_terms` on an
    :class:`~looks.environment.FfmpegEnv` they probed.

    Examples:
        >>> rows = ledger()
        >>> len(rows) > 25
        True
        >>> sorted({t.provider for t in rows})[:4]
        ['adobe-lut-packs', 'anime4k', 'animegan2-pytorch', 'animeganv2']

        The tier is derived, and the compound case is why:

        >>> opencv = terms_for('opencv')
        >>> classify(next(t for t in opencv if t.component == 'code')).tier
        <Tier.PERMISSIVE: 'permissive'>
        >>> assess(opencv).verdict
        <Verdict.UNKNOWN: 'unknown'>
    """
    rows = _raw_ledger()["rows"]
    terms = tuple(_terms_from_row(r) for r in rows)  # type: ignore[union-attr]
    keys = [t.key for t in terms]
    duplicates = {k for k in keys if keys.count(k) > 1}
    if duplicates:
        raise ValueError(
            f"{LEDGER_PATH.name} has duplicate keys {sorted(duplicates)}; "
            "the triple is the key, so a second row silently shadows a first"
        )
    return terms


def terms_for(
    provider: str,
    realisation: Optional[str] = None,
    component: Optional[str] = None,
) -> tuple[Terms, ...]:
    """Every ledger row matching a provider, optionally narrowed.

    Returns **all** matching components, because a provider is assessed by its
    worst one and handing back a single row would be the per-package key the
    ledger deliberately does not have.

    Examples:
        >>> [t.component for t in terms_for('moviepy')]
        ['code', 'transitive']
        >>> assess(terms_for('moviepy')).tier
        <Tier.COPYLEFT_SHIPPED: 'copyleft_shipped'>
        >>> terms_for('no-such-provider')
        ()
    """
    return tuple(
        t
        for t in ledger()
        if t.provider == provider
        and (realisation is None or t.realisation == realisation)
        and (component is None or t.component == component)
    )


def unverified_claims() -> tuple[str, ...]:
    """What the research explicitly did **not** establish.

    Recorded rather than omitted: an unverified claim asserted as fact defeats
    the point of the whole design, and the claims here are the ones somebody
    will otherwise assume were checked.

    Examples:
        >>> len(unverified_claims()) >= 4
        True
    """
    return tuple(_raw_ledger().get("unverified", ()))  # type: ignore[arg-type]
