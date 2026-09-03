# `looks` — Standing Decisions and Rationale

**Author:** Thor Whalen
**Status:** Decisions of record. Written 2026-09-02 against thirteen research notes, each adversarially reviewed by a second reader who re-ran every command.
**Version anchor:** ffmpeg 8.1 (Homebrew, `--enable-gpl --enable-version3`, 481 filters) and FFmpeg source at tag `n8.1`; `opencv-python-headless` 4.13.0.92; `av` 16.0.1; `imageio-ffmpeg` 0.6.0; `moviepy` 2.2.1; Python 3.12.12 on macOS arm64 (darwin 24.6.0). Every measurement below was taken on that machine unless it says otherwise.

**Cross-version warrant, added 2026-09-04.** CI now installs ffmpeg (rule 29d), and the suite is additionally run against **ffmpeg 6.1.6** (the version Ubuntu ships, and therefore what CI executes) and **9.0.1**. All 1286 tests pass on both. That span is the reason three build-specific assumptions were found and removed — a height-1 lavfi frame, `gradients speed=0`, and FFV1 in an `.mp4` container are each accepted by one of these builds and refused by another.

**Purpose.** The research in [`docs/research/`](research/) says what is *true*. This document says what `looks` has *decided*, and why. It is the entry point: read this, then follow the pointers into the notes for detail. Where the two conflict, the research wins on facts and this document wins on intent — flag the conflict rather than silently resolving it. **Where a note's adversarial review refuted the note's body, the correction is what is recorded here.**

**Do not re-derive anything below.** Several findings are counter-intuitive enough that a fresh derivation is likely to land on the wrong answer, and three of them were wrong in the *permissive* direction on the first attempt — which is the direction that makes this package a liability rather than merely useless.

---

## 1. How to read this document

Every item is tagged:

- **`[DECIDED]`** — settled. Implement accordingly. Reopen only with evidence that the premise was wrong.
- **`[POLICY]`** — a standing rule with a stated rationale. Follow it; surface exceptions rather than taking them.
- **`[OWNER]`** — a recommendation awaiting the owner's ratification. Do not treat either way as settled.
- **`[OPEN]`** — genuinely unresolved. Do not build against it.
- **`[DEFECT]`** — a live bug in code already committed to this repo, verified today.

An agent that treats an `[OWNER]` or an `[OPEN]` as a `[DECIDED]` will build the wrong thing confidently.

---

## 2. The verdict

`looks` is a **pure-data spec layer for video look**: a `Look` is an ordered stack of named `Effect`s that compiles, against a *declared* clip and a *declared* ffmpeg environment, into an inspectable `LookPlan` whose every step carries a **resolved licence tier** and a **CPU-second estimate**. It emits the chain; the caller runs it. It never spawns a producing process, never decides where a cut is, and never measures a clip on its own initiative — it declares what must be measured and consumes a probe the caller supplies.

The research changed the conception in four ways, and each one is load-bearing:

1. **The tier cannot be a constant.** The kickoff assumed a per-effect licence tier declared in a registry. FFmpeg gates licences **per filter** (38 of ~481 in n8.1) *and* **per binary** (this machine carries two ffmpegs with different licences and non-nested filter sets), so a frozen `tier=` field is wrong in both directions on different machines. The tier is **resolved** at compile time by joining what an implementation *declares* with what the environment *is*. [7][R7][14]
2. **The tier cannot be a single ladder.** Field-of-use ("non-commercial") and copyleft reach are incommensurable. On a single total order, a caller who raises the ceiling one rung to admit a research model silently admits `av` and `imageio-ffmpeg` — the two packages the kickoff bans by name. Field-of-use comes off the ladder; in-process strong copyleft comes off it too, because *a rung you can opt into is not "always refuse"*. [6][R3][R6]
3. **The GPL wall is not where anyone looks for it.** Only three of the 38 GPL-gated filters are colour operations — `eq`, `histeq`, `colormatrix` — and **every one of them has an LGPL-or-better substitute present in the same binary**, so no colour *capability* is reachable only behind the GPL wall. (Say it that way, not "no GPL-gated filter is a colour operation", which is the stronger form and is false: `eq` is the obvious brightness/contrast/gamma/saturation filter and the natural implementation of a *continuity grade*, and it is gated. The one substitution gap: `eq`'s `gamma_weight` has no exact LGPL equivalent; `curves`/`lutyuv` approximate it.) The real wall is in the **encoders** (`libx264`/`libx265`), which `looks` deliberately never touches. [7][R7][14]
4. **The measured per-source rule is a closed loop over the OUTPUT**, so it provably cannot live inside a spec type. What lives in the spec is the **refusal**: a parameter that must be measured and was not is an error, never a silent global default. [3][19]

The thesis survives all four intact, and one prior-art finding sharpens it: **FFmpeg's own `configure` already implements this package's entire idea** — per-component tier tags, a caller-declared ceiling (`--enable-gpl`), and `die_license_disabled`, a hard failure rather than a warning. `looks` is not inventing licence-aware refusal; it is **relocating it from build time to call time**, where the person who gets refused can still do something about it. [1]

---

## 3. The layering ruling `[DECIDED]`

```
lacing (annotation graph — SSOT: typed, standoff, interval-keyed, provenance-tracked)
   |
   v
nw.ProjectGraph + nw.Transform     (the A-annotation -> B-annotation contract)
   |
   +--> falaw.Plan      consent-to-spend for an irreversible BILLED vendor call
   |
   +--> looks.LookPlan  local CPU: reversible, unbilled, and NOT a money gate
                |
                v
         backends (ffmpeg filter chain | per-frame op | external tool)
```

**`looks` is a peer of `burns` and `mixing`, not of `falaw`.** There are two parallel façade boundaries, not one stack. `falaw.Plan` bounds money and irreversibility; `looks.LookPlan` bounds ffmpeg's vocabulary and gates nothing financial. Forcing `looks` under `falaw` would make muvid's direct `-vf` splice an architecture violation, and would denominate a local render in dollars — where the honest answer is `$0.00`, correct and useless. [11]

**The rule that decides where a new capability belongs:**

> **If it decides what a pixel becomes, given a declared clip and a declared environment, it is `looks`. If it decides which pixels exist, when they appear, what they cost in money, or how a process is run, it is not.**

Applied without ambiguity: a colour grade is `looks`; a cut is not (`nw`/`muvid` own the EDL); a fal.ai call is not (`falaw`); a decoder loop is not (`muvid.footage.assemble`); an authored camera move is not (`burns` — see §7.1); the *compilation* of that camera move into a filter fragment is (`looks`).

### 3.1 The federation seam is one `-vf` fragment `[DECIDED]`

`muvid.footage.assemble` renders **one ffmpeg invocation per part**, with a constant number of decoders per invocation, because the previous single-`-filter_complex`-over-all-cuts shape held a decoder context per cut and was OOM-killed at 30 cuts on the 3.7 GB production box (muvid#21/#24). Every part is already scaled and padded onto a fixed canvas through a per-part filter chain. [16]

So the whole integration is: **`looks` emits a `-vf` chain fragment; the consumer splices it into the per-part invocation it is already making.** No new inputs, no new decoders, no change to the invariant. Two consequences:

- **The "which source is on screen at time *t*" problem dissolves.** Apply per cut, before assembly, and the caller already knows which clip it is holding — that *is* what a part is. The finished-render path (which needed a per-frame span table) is the **degraded** path; document it, do not design for it. [16][4]
- **A multi-input effect adds a decoder.** `muvid`'s transition part is a two-input `xfade`, and *two* is the number the invariant tolerates. `looks` may express two-input effects; an effect whose input count grows with the edit is forbidden **by construction**, not by taste. [16]

### 3.2 `looks` hosts no Transform `[DECIDED]`

`nw.transforms.cache_key` (nw#54) already exists for "a Transform that spends money or CPU **without** going through fal", and `braidio.segment_extraction.ffmpeg` is its shipped reference implementation — a *local-render Transform* whose `plan()` returns a zero-call `falaw.Plan` plus a skeleton carrying its own cache key. A `looks`-backed stylize step is exactly that shape, so **no new mechanism is needed in `nw`**. [11]

Ownership split: `looks` owns the spec types, the registry, the tier machinery and `compile`. `nw` owns the body-schema URI when one is needed. **`muvid` hosts the Transform first**, graduating into `nw` on the rule of three. `looks` imports no federation package and registers nothing. [11]

---

## 4. The core types `[DECIDED]`

These are settled. Where researchers disagreed, the losing option is named with the reason it lost.

### 4.1 The request: `Effect`

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Effect:
    """One named operation the caller asks for. Pure data; NO tier, NO impl."""
    name: str                              # the CAPABILITY ("flatten", "posterize")
    params: Mapping[str, Any] = EMPTY      # JSON values, or a Ref (see 4.3)
    at: Optional[Span] = None              # WHERE a look applies. Never where a cut is.
    impl: Optional[str] = None             # pin one implementation; does NOT bypass the ceiling
    backend: Optional[str] = None          # pin a family ("ffmpeg" | "frame" | "external")
    metadata: Mapping[str, Any] = EMPTY    # identity-free; never enters look_hash
```

**`Effect` carries no tier, and this is the single most important decision in the design.** If a caller could write `Effect(..., tier=PERMISSIVE)`, the refusal is theatre: the party who wants the answer to be yes is asserting it. The tier belongs to the implementation and the environment, so it can only appear at compile time. [3]

**Construction does not consult the registry.** A Look authored against a newer plugin set must still load, print and diff in a process that lacks it — the discipline that lets an old `lacing` build read a newer body. `looks.effect(...)` is a checking front door in the registry module for people who want one. [3]

### 4.2 Where: `Span`, and the clip: `ClipSpec`

```python
@dataclass(frozen=True, slots=True)
class Span:
    """Seconds, relative to frame 0 AS THE HOST'S DECODER WILL SEE IT."""
    start: Optional[float] = None
    end: Optional[float] = None

@dataclass(frozen=True, slots=True, kw_only=True)
class ClipSpec:
    """The clip a plan is compiled AGAINST. Not a file, not bytes."""
    width: int
    height: int
    fps: float
    duration_s: Optional[float] = None
    pix_fmt: Optional[str] = None          # None = not declared
    color_range: Optional[str] = None      # "limited" | "full" | None (UNTAGGED IS A THIRD VALUE)
    color_space: Optional[str] = None      # the YUV<->RGB matrix; None = not declared
    sar: Optional[tuple[int, int]] = None  # sample aspect; None = assume square
```

The colour fields are not decoration; without them the plan's central promise is false. Measured on an untagged full-range source, against a correctly-tagged reference: fixing **neither** range nor matrix costs 27/255 max channel error, **range only** 19, **matrix only** 20, **both** 2. Two independent unknowns; half a fix is barely a fix. Two clips identical in geometry but differing in colour range produce visibly different pixels through the same LUT, so a `plan_hash` that omits them is lying. [15][5][R4]

`sar` is there because `xfade` silently tolerates a sample-aspect mismatch and stamps the output 1:1 — the false-permission direction, in a package built on refusal. [R12]

### 4.3 Deferred parameters: `Ref` + a `resolve` pass

```python
@dataclass(frozen=True, slots=True)
class Ref:
    key: str
    default: Any = _NO_DEFAULT     # genuinely optional; absence is a REFUSAL

def resolve(look: Look, probe: Mapping[str, Any] = ()) -> Look: ...
def resolve_across(look: Look, probes: Sequence[Mapping[str, Any]]) -> tuple[Look, ...]: ...
```

Serialised as `{"$ref": "flatten_scale", "default": 0.5}`. `resolve` is the **identity** on a Look holding no Refs, so a caller who already has numbers never meets the function.

**Rejected: a callable `stats -> value`.** It would be evaluated during resolution, so the *plan* stays serialisable — but the **Look** is the artifact, and a Look you cannot write to disk is a local variable, not an asset. It also destroys diffability (two Looks print `<function <lambda> at 0x...>`) and any honest cache key. `burns` hit this and took the half-measure of raising at `to_dict`. [3][R3]

**Rejected: a per-clip `variants: dict[str, dict]` table** (the reviewer's counter-proposal). It is JSON-native and would work, but it cannot express the design's central rule — *this parameter must be measured, and there is no global fallback* — because a missing variant entry is either a `KeyError` or a silent fall-through to the base. `Ref` is per-parameter, so a diff shows exactly which knobs are clip-dependent, and a Ref with no default that the probe does not answer **raises**. That is the measured lesson encoded as a type: one global flattening scale made the softest of three sources softer still (46 -> 38, against 35 -> 72 and 117 -> 114), so it became the softest thing on screen. [R3][19]

**Documented cost:** `"$ref"` is a reserved key inside a parameter *value*, so a parameter whose legitimate value is a mapping containing that exact key is inexpressible. The decoder is strict about the shape so the ambiguity cannot be hit silently.

### 4.4 The artifact: `Look`

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Look:
    steps: tuple[Effect, ...] = ()
    name: str = ""
    policy: Policy = DFLT_POLICY           # see 5.4 — NOT a bare max_tier
    target: Target = Target.EXTERNAL       # EXTERNAL | SET_RELATIVE — see 7.2
    metadata: Mapping[str, Any] = EMPTY
    version: int = LOOK_VERSION            # schema tag "looks.look/v1"
```

`a + b` concatenates the steps and takes the **stricter** of the two policies, never the looser. A guarantee that composition can silently relax is not a guarantee. Widening is always a separate deliberate act (`with_policy(...)`) — the same shape reelee applies to its spend threshold. [3][25]

**`policy` is not part of `look_hash`.** A ceiling changes what a Look is *allowed* to compile to; it never changes what the Look asks for.

### 4.5 The declaration: `ImplRef` — terms, not a tier

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ImplRef:
    effect: str                            # capability served
    impl: str                              # "<effect>.<backend>.<variant>", globally unique
    backend: str                           # "ffmpeg" | "frame" | "external"
    terms: Terms                           # WHAT IT IS (see 5.2). NOT a tier.
    requires_filters: tuple[str, ...] = () # ffmpeg filters this impl emits
    impl_version: str = "1"                # behaviour lock; enters plan_hash UNCONDITIONALLY
    timeline: bool = True                  # can this be gated to an Effect.at?
    preference: int = 0                    # explicit tiebreak within one tier; lower wins
    lossy_substitute_for: tuple[str, ...] = ()   # see rule 12
```

**`terms`, not `tier`, is the refutation the whole design turns on.** A frozen `tier=COPYLEFT_TOOL` on every ffmpeg implementation is wrong twice: it is a false refusal for the LGPL-clean majority of the colour vocabulary, and it cannot distinguish the one filter (`eq`) that genuinely is GPL-only. The tier is computed by `classify(terms, env, policy)` at compile time. [R3][7]

**`preference` exists because the tiebreak is the common case, not the exception.** Every ffmpeg implementation of a capability sits at the same rung, so "prefer the lowest tier, ties by registration order" resolves to *import order* for exactly the family it is most often asked about. Make the tiebreak legible or refuse the ambiguity; do not let it be a side effect of import order. [R3]

**`timeline` is a candidate FILTER, not a post-check.** Verified on ffmpeg 8.1: `lut3d`, `lutrgb`, `curves`, `unsharp`, `gblur`, `colorchannelmixer`, `colorlevels`, `geq` carry the `T` flag; `scale`, `crop`, `elbg`, `palettegen`, `zoompan` do not, and `xfade` does not. If `Effect.at` is set, ungateable candidates are dropped in step 1 alongside the `impl`/`backend` pins — checking it *after* tier selection discards a perfectly good gateable candidate and then refuses. [R3][2]

### 4.6 The compiled form: `Step` and `LookPlan`

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Step:
    effect: str
    impl: ImplRef
    tier: Tier                             # RESOLVED against the environment. Read, not asserted.
    params: Mapping[str, Any] = EMPTY      # fully concrete; a surviving Ref raises
    at: Optional[Span] = None
    payload: Mapping[str, Any] = EMPTY     # backend-shaped; the ONLY place backend specifics live
    cpu_seconds: Optional[float] = None    # None means UNKNOWN, never zero
    metadata: Mapping[str, Any] = EMPTY

@dataclass(frozen=True, slots=True, kw_only=True)
class LookPlan:
    steps: tuple[Step, ...] = ()
    clip: Optional[ClipSpec] = None
    env: Optional[EnvFingerprint] = None    # (binary path, version, licence, filter-set digest)
    look_name: str = ""
    policy: Policy = DFLT_POLICY
    probe: Mapping[str, Any] = EMPTY
    metadata: Mapping[str, Any] = EMPTY
    version: int = PLAN_VERSION             # schema tag "looks.plan/v1"
```

`payload` is backend-shaped and the asymmetry is deliberate:

| backend | payload | inspectable? |
|---|---|---|
| `ffmpeg` | `{"filter": "<fragment>", "sources": [...]}` | **Fully** — read a stored plan and see the exact filtergraph |
| `frame` | `{"op": "<registry key>", "pipe": {...}}` | Only *nameable*, plus the decoder/encoder argv **as data** |
| `external` | `{"tool": "<registry key>"}` | Only nameable |

**`frame` and `external` payloads name a REGISTRY KEY, never a `module:attr` import path.** A plan is a document, documents arrive from places, and a document that can name `os:system` is a remote-code-execution primitive wearing a schema tag. [3]

**The plan holds no live callables.** Note 05's `Stage` design carried `apply: Callable` and `render: Callable` directly; that was refuted as fatal — a plan with a closure in it cannot be serialised, diffed or hashed, which is the entire reason the `falaw.Plan` shape was adopted. The callable is resolved from the registry at *execution* time by the runner. [R5]

**The env fingerprint belongs on the plan and NOT on the Look.** A `Look` is portable data. A `LookPlan` is compiled against one binary, whose filter set and licence are part of what determines the pixels — so it says which one, and the fingerprint enters `plan_hash`. This resolves the objection that folding the environment into a plan breaks portability: it does not, because the portable artifact is the Look. [R7][11]

**Cost arithmetic**, transposed from `falaw` for the same reasons: `total_cpu_seconds` coerces unknown to `0.0` so sums compose, and is a documented **lower bound**; `known_cpu_seconds` + `unknown_step_count` are the honest pair a gate reads together; `has_unknown_costs` is the boolean; `realtime_factor` returns **`None`** when anything is unknown. The asymmetry is deliberate — a sum must be total to compose, a headline ratio a human acts on must not fabricate. That is reelee#208's failure mode, where a `$0.00`-because-unknown read as "under the threshold, spend freely". [3]

**Deliberately not modelled: peak memory and streaming shape.** Those are the executor's invariant, and a plan claiming to predict them is an invitation to write the `looks.render()` this package is chartered to stay out of.

### 4.7 Three identity levels `[DECIDED]`

- **`look_hash(look)`** — authored intent. Registry-independent, environment-independent, policy-independent. Answers *is this the same look?*
- **`plan_hash(plan)`** — the compiled pipeline: impl + `impl_version` + resolved params + `ClipSpec` **including its colour state** + the env fingerprint. Answers *will this produce the same pixels from the same input?*
- **`output_key(plan, source_digest)`** — content-addressed. Takes a digest **of bytes**, never a path. `looks` computes the formula and refuses to open the file, because reading bytes is execution.

`output_key`'s signature is falaw's D1 defect stated as a type: keying on upstream *URLs* rather than upstream *content* made a byte-identical regeneration miss the cache. [falaw#14]

**`impl_version` folds into `plan_hash` unconditionally.** `nw` and `falaw` omit it when it equals its default; that is a *migration device* protecting an installed base of cache keys, and `looks` has no installed base. Do not copy the sentinel. This is the clearest case in the design of deliberately not copying a sibling. [3]

### 4.8 Serialisation `[POLICY]`

Two schema tags, two independent lifecycles: `looks.look/v1` and `looks.plan/v1`, each also carrying an in-band `version` int.

- Adding an **optional field with a default** is additive: written always, defaulted when absent. No tag bump, no migration.
- **Renaming, removing, retyping or re-defaulting** a serialised field is breaking: bump the tag and land the migration with the downstream update.
- An **unrecognised tag is refused loudly**; a **missing tag is tolerated as v1**, so hand-written Looks stay easy.

**No migration registry at v1** — a registry with zero entries is a stub. But the shape is already known and must not be re-derived: when the first v2 lands it is keyed on **`(kind, from_version)`**, never `(from, to)`. `an` paid for that with an#77 — two kinds at the same version number, a `(from, to)`-keyed registry that could not tell them apart, and consequently *the wrong migration silently running against the wrong document*. `looks` versions two kinds independently from day one, so it is a live hazard here rather than a borrowed one. [3][an#77]

### 4.9 Frozen means frozen `[POLICY]`

Every mapping field on every frozen dataclass is frozen at construction (a `MappingProxyType` over a copy). `frozen=True` prevents rebinding the field, not mutating the dict behind it — so without this, `look_hash` can change after a Look has been built, hashed and stored, and the objects are not hashable at all despite `dataclass(frozen=True)` generating `__hash__`. [R3]

---

## 5. The licence ruling `[DECIDED]`

### 5.1 What a refusal is protecting against — state this, or the refusal is unactionable

`looks` **shells out**; it never links. Invoking a GPL program encumbers neither the caller's code nor the program's output. So a `gpl` tier under shell-out is **two** statements at once, and a refusal message must say both:

1. **An availability fact.** A GPL-gated filter does not exist in an LGPL build. An `eq` look simply fails there — verified: it is absent from a real LGPL-2.1 build of n8.1.
2. **A statement about the BUILD the user must have**, and — if they redistribute the tool — must ship.

Without that sentence the person who gets refused cannot tell what to do next, and a refusal nobody can act on is the one people delete. [R1]

### 5.2 The facts are four axes `[DECIDED]`

| Axis | Values | What it decides |
|---|---|---|
| `Coupling` | `NONE` · `IN_PROCESS` · `SUBPROCESS` · `SERVICE` · `UNKNOWN` | Whether copyleft can reach the caller's own code at all |
| `Reach` | `NONE` · `FILE` · `LIBRARY` · `PROGRAM` · `NETWORK` · `UNKNOWN` | How far the copyleft extends (permissive / MPL / LGPL / GPL / AGPL) |
| `Conveyance` | `NONE` · `FINDS` · `CONVEYS` · `UNKNOWN` | Whether **`looks`' declared dependency closure** ships the implementation, or resolves one already present |
| `FieldOfUse` | `UNRESTRICTED` · `NO_DERIVATIVES` · `NON_COMMERCIAL` · `RESEARCH_ONLY` · `UNKNOWN` | Whether the *purpose* is permitted — orthogonal to all of the above |

Neural effects need two more, because FFmpeg's `gpl`/`nonfree`/`version3` vocabulary structurally cannot express them:

| Field | Why it is forced |
|---|---|
| `code` and `weights` as **separate** licences | `bryandlee/animegan2-pytorch` is **MIT code** over weights converted from non-commercial AnimeGANv2 weights. A metadata scan gets it exactly backwards. [9] |
| `patent` as `{jurisdiction, patent_id, expiry \| unknown}` | Ebsynth is **public-domain code** implementing Adobe's PatchMatch patent (US8861869B2, Active, anticipated expiry 2030-08-16). `public-domain` is the most permissive value any copyright vocabulary has and is the wrong answer for that row. [9][R9] |

`Conveyance` must say **whose** dependency closure. A caller's pre-existing `imageio-ffmpeg` is `FINDS`, not `CONVEYS`; it becomes `CONVEYS` only if `looks` declares it. [R6]

### 5.3 The ladder is a policy PROJECTION of three axes `[DECIDED]`

| Rung | Tier | Axis region | Obligation | Example |
|---|---|---|---|---|
| 0 | `PURE` | `Coupling.NONE` | none | `looks.geometry` arithmetic; `looks.lut` `.cube` generation |
| 1 | `PERMISSIVE` | `IN_PROCESS` + `Reach.NONE` | notice retention on conveyance | OpenCV's own Apache-2.0 `pyrMeanShiftFiltering`, *as code* |
| 2 | `WEAK_COPYLEFT` | `IN_PROCESS` + `Reach.FILE`/`LIBRARY` | notice + relink, dynamic linkage only | an honest LGPL ffmpeg; MPL components |
| 3 | `COPYLEFT_TOOL` | `SUBPROCESS`/`SERVICE` + `PROGRAM`/`NETWORK` + `FINDS` | none on your code; a prohibition on a **future** act | Homebrew ffmpeg 8.1 on `PATH`; any effect needing `eq` |
| 4 | `COPYLEFT_SHIPPED` | same, but `CONVEYS` | full source-offer duty, inherited downstream | `imageio-ffmpeg`; `burns` transitively; `opencv-python` **on macOS arm64** |

**Default ceiling: `COPYLEFT_TOOL`.** The kickoff's "shells out to a copyleft binary is fine", stated precisely.

Two honesties this table owes, because a ladder presented as a fact is exactly the failure mode this package is about:

- **Rungs 2 and 3 are not ordered by obligation-inclusion.** In-process LGPL and subprocess GPL impose *different* duties, not more and fewer, and plenty of corporate policies rank them the other way. The ordering here is chosen for what *this* federation ships. `Policy(order=...)` makes it replaceable. Rungs 3 -> 4 *are* ordered by inclusion, unambiguously. [6]
- **A provider made of several components takes the WORST COMPONENT VERDICT, never a per-axis join.** Joining OpenCV's Apache-2.0 code with the GPL ffmpeg in the same wheel yields `IN_PROCESS` + `PROGRAM` — "we link a GPL program in-process" — a chimera true of neither component, which then reports `FORBIDDEN`. This was found by *running* the proposed module, not by reading it. [6]

### 5.4 Three regions are OFF the ladder `[DECIDED]`

| Verdict | Region | Why no rung |
|---|---|---|
| `FORBIDDEN` | `IN_PROCESS` + `Reach.PROGRAM`/`NETWORK` | The kickoff says always refuse. **A rung you can opt into is not "always refuse".** |
| `FIELD_RESTRICTED` | any `FieldOfUse` other than `UNRESTRICTED` | Not commensurable with copyleft; needs its own separate opt-in |
| `UNKNOWN` | any axis `UNKNOWN`, **or an internally contradictory probe** | Unknown is a refusal — and it is a *different* refusal from "known and forbidden", with different advice |

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Policy:
    max_tier: Tier = Tier.COPYLEFT_TOOL
    allow_field_restricted: frozenset[FieldOfUse] = frozenset()   # default: nothing
    order: tuple[Tier, ...] = DEFAULT_ORDER
```

**The FATAL bug this fixes, found by running note 06's own module:** the first design returned early on `FIELD_RESTRICTED` once the opt-in was honoured, so `Policy(max_tier=Tier.PURE, allow_field_restricted={NON_COMMERCIAL})` **admitted** a `SUBPROCESS` + GPL-3 + `CONVEYS` + `NON_COMMERCIAL` provider. That is the exact mirror of the flaw the two-knob design exists to prevent, running in the false-permission direction. **`classify` must return the ladder tier ALONGSIDE the field verdict, and `check` must fall through to the ceiling test after honouring the opt-in — never return.** [R6]

**Note also what `max_tier` is *not*.** Every rung including `COPYLEFT_SHIPPED` is commercially usable — a source offer is a duty, not a prohibition. What is not commercially usable is `FieldOfUse.NON_COMMERCIAL`, which is off the ladder. So the kickoff's headline "commercial-safe only" use case is served by `allow_field_restricted=frozenset()` — **already the default** — not by `max_tier`. Say this in the API docs or the advertised purpose and the actual semantics drift apart on day one. [R6]

### 5.5 The tier is resolved, and the environment is an argument `[DECIDED]`

```
Terms (declared by the impl)  x  FfmpegEnv (passed in by the caller)  ->  Tier
```

- **`ffmpeg -L` is the only authority on a binary's licence.** It is a compile-time `#if` cascade in `fftools/opt_common.c`, so it cannot be patched out the way the `configuration:` line can. `-buildconf` is reporting-only. **No match is `UNKNOWN`, which refuses** — "no evidence of GPL" is not evidence of LGPL. [7]
- **`ffmpeg -filters` is the only authority on availability.** `ffmpeg -h filter=NOSUCHFILTER` prints "Unknown filter" and then, verbatim, "Exiting with exit code 0" — every filter would test as present. Parse the `-filters` table by whitespace, taking field 1; **never slice columns**, because the flags column is 3 chars on 7.1 (`TSC`) and 2 on 8.1 (`TS`, Command dropped, a `------` separator added). A parser written against one returns *zero* filters from the other, which in a refusal engine is a false refusal — the failure that looks like safety. [7][R7][11]
- **`-h filter=NAME`'s stdout is a legitimate free probe for OPTIONS**, and 8.x is strictly better here than 7.1: each runtime-settable option is marked `T` in its flag string. Presence of a filter *name* is necessary but not sufficient — 8.1's `scale` exposes `in_primaries`/`out_primaries`/`in_transfer`/`out_transfer`; the imageio 7.1 `scale` exposes none of them, so a `scale=out_primaries=bt709` passes a name-only gate and dies at ffmpeg-exit. Only the **exit code** of `-h filter=` is unusable. [R7]
- **There is not one ffmpeg on a machine.** Measured here: `PATH` is 8.1 / GPL-3 / 481 filters; `imageio-ffmpeg`'s bundled binary is 7.1 / GPL-2 / 484, and the sets are **non-nested** — only `PATH` has `colordetect`, `transpose_vt`, `yadif_videotoolbox`; only the bundled one has `ass`, `drawtext`, `pp`, `subtitles`, `vidstabtransform`, `zscale`. The PATH ffmpeg on this machine **cannot draw text**. So neither "the ffmpeg version" nor "the ffmpeg licence" is a single fact about a machine, and **nothing downstream may call `probe()` for itself**. [7][2]

### 5.6 The gate table is two classes, not one `[DECIDED]`

A filter is GPL-gated **directly** (literal `gpl` in its `_filter_deps` — 33 filters in n8.1) or **indirectly** (its deps name a library in `EXTERNAL_LIBRARY_GPL_LIST` — 5 more: `frei0r`, `frei0r_src`, `rubberband`, `vidstabdetect`, `vidstabtransform`). **Total 38.** [14][R1]

**Missing the indirect set is a false permission**, and it happened: the first version of this repo's table tiered *video stabilisation* as permissive. `looks/data/ffmpeg_gates.json` is schema `looks.ffmpeg_gates/v2` and stores the two classes separately (`gpl_filters_direct` / `gpl_filters_indirect`) so a re-extraction cannot quietly drop one. There is also exactly one version3-gated filter, `lensfun` — and FFmpeg contradicts itself there: `LICENSE.md` and the source header say GPL-3, `configure` gates it on `version3` alone. Hardcode `lensfun` as GPL-3-or-later. [14][7]

**A directly-gated filter is present in every GPL build; an indirectly-gated one is not** — the latter also needs its external library, a separate build flag Homebrew does not pass. So "this GPL build has every GPL-gated filter" is true only of the direct half.

Two known leaks the gate table cannot see, and the reason rule 3 (§9) exists: `codecview` and `perlin` have **no `_filter_deps` line at all** in n8.1 while `libavfilter/Makefile` unconditionally links GPL-2-headed helper objects (`qp_table.o`, `perlin.o`) with them. So `configure`'s gates are **necessary but not sufficient**, and the fail-open default that would bless them is the defect below. [R7]

### 5.7 The verified licence ledger

Every row is `(provider, realisation, component)`. The tier is **derived** by `classify()`, never asserted — a test re-derives every row. Rows are keyed per **component**, because the compound cases (OpenCV, burns) cannot round-trip through a per-package key. [R6]

| Provider / component | Realisation | Verified fact | How verified | Tier |
|---|---|---|---|---|
| ffmpeg, non-gated filter | `system` | not in any gate list at n8.1 | `configure` extraction | rung of the **binary** |
| ffmpeg, `eq` and 37 others | `system` | GPL-gated, absent from a real LGPL build | `configure` + an actual LGPL-2.1 build | `COPYLEFT_TOOL`, GPL build required |
| ffmpeg, `geq` | `system` | **not** GPL, and has not been since 4.3 (relicensed 2019-12-16) | `configure` at n8.1 | LGPL — the belief outlives the fact |
| Homebrew ffmpeg 8.1 | `system` | `--enable-gpl --enable-version3`; `-L` says GPLv3+ | `ffmpeg -L`, `-buildconf` | `COPYLEFT_TOOL` (GPL-3) |
| `av` 16.0.1 | `pypi:av` | metadata BSD-3; self-report LGPLv3; **`otool -L` shows `libx264.165` + `libx265.215` linked** | three-layer probe | `FORBIDDEN` (in-process) **and** `UNKNOWN` (contradiction) |
| `imageio-ffmpeg` 0.6.0 | `pypi:imageio-ffmpeg` | ships `ffmpeg-macos-aarch64-v7.1` built `--enable-gpl`; metadata BSD-2 | run the binary's `-version` | `COPYLEFT_SHIPPED` |
| `moviepy` 2.2.1 | `pypi:moviepy` | **unconditional** `Requires-Dist: imageio_ffmpeg>=0.2.0`, no extras marker | METADATA | `COPYLEFT_SHIPPED` (transitive) |
| `burns` 0.0.9 | `pypi:burns` | declares `moviepy` -> the above; so `pip install burns` puts a GPL binary on disk | dependency walk | `COPYLEFT_SHIPPED` (transitive) |
| OpenCV C++ / `pyrMeanShiftFiltering` | any | Apache-2.0 main-module code that never enters libavcodec | source | `PERMISSIVE` |
| `opencv-python*` bundled ffmpeg | `pypi:*, macosx_arm64` | `--enable-gpl --enable-version3 --enable-libx264 --enable-libx265`; **headless too** | `strings` on the shipped `libavutil` | `COPYLEFT_SHIPPED` (GPL-3) |
| `opencv-python-headless` bundled ffmpeg | `pypi:*, macosx_14_0_x86_64` | **no FFmpeg at all** (`FFMPEG: NO`; 4 vendored dylibs, all permissive) | wheel inspection | `PERMISSIVE` |
| `opencv-python-headless` bundled ffmpeg | `pypi:*, manylinux` | LGPL-2.1-or-later; **no** x264/x265 | wheel inspection | `WEAK_COPYLEFT` |
| `ultralytics` | `pypi:ultralytics` | AGPL-3.0 (three distributions: `ultralytics`, `-thop`, `-platform`) | metadata; paces ADR-0005 §3 | `FORBIDDEN` for our use |
| `argh` 0.31.3 | `pypi:argh` | LGPL-3.0 — and the PyPI metadata `License:` field is **empty**; only the shipped `COPYING`/`COPYING.LESSER` pair says so | file (2026-09-02) | `WEAK_COPYLEFT` — **do not use for the CLI** |
| `cw` 0.1.2 | `pypi:cw` | MIT; `dependencies = []`, and `import cw` verified to pull in **nothing** beyond stdlib — its `argcomplete`/`i2` imports are lazy | file + run (2026-09-02) | `PERMISSIVE` — **this is the CLI** |
| `colour-science` 0.4.7 | `pypi:colour-science` | BSD-3-Clause; the only surveyed lib that **writes** an Iridas `.cube` | metadata + source | `PERMISSIVE` |
| `moderngl` + `glcontext` | `pypi` | MIT, 488 KB, bundles nothing | metadata + wheel | `PERMISSIVE` |
| AnimeGANv2 (upstream) | weights | **NO LICENSE FILE**; GitHub API returns `license: null`; README prose only | API + repo | **`UNKNOWN`** — not "non-commercial" |
| `animegan2-pytorch` (the port) | code | MIT | LICENSE | `PERMISSIVE` code over `UNKNOWN` weights |
| White-box Cartoonization | weights | CC BY-NC-SA 4.0 per README; no LICENSE file | repo | `FIELD_RESTRICTED` + share-alike |
| `jcjohnson/fast-neural-style` | code | "Free for personal or research use" in README prose, no LICENSE | repo | `FIELD_RESTRICTED` |
| ONNX Model Zoo `fast_neural_style` | weights + code | BSD-3-Clause, SPDX header on the model directory | repo | `PERMISSIVE` |
| Ebsynth | code + patent | public-domain code; Adobe PatchMatch US8861869B2 **Active**, anticipated expiry 2030-08-16 | Google Patents | `PERMISSIVE` code, patent-encumbered (US) |
| Anime4K shaders | assets | repo LICENSE MIT, **but per file**: at least one Unlicense, at least one with no header | file headers | `PERMISSIVE`, recorded **per file** |
| RAVU / mpv-prescalers | assets | LGPL-3.0 (README) | repo | `COPYLEFT_SHIPPED` if vendored |
| FSRCNNX (release 1.1 assets) | assets | **LGPL-3.0-or-later at the FILE level** | `.glsl` headers | `COPYLEFT_SHIPPED` if vendored — **not** unknown |
| MiniMax-H3 | hosted weights | **territorially excluded** from EU, UK, South Korea, USA; metadata says `license: other` | model card | `FORBIDDEN` for a US/EU caller |
| Stability SD3.5 / SDXL-Turbo | weights | Community License **terminates** above $1M revenue (a cliff, not a price band); the HF card's `sai-nc-community` contradicts the LICENSE.md **in the safe direction** | LICENSE.md vs card | `FIELD_RESTRICTED`, condition as data |
| LTX-Video (0.9.6+ **and** 2.x) | weights | **both** carry a $10,000,000 Commercial-Entity threshold | licence text | `FIELD_RESTRICTED`, condition as data |
| ByteDance Bernini-R | weights | plain Apache-2.0, no thresholds; video tasks **demonstrated on 8 Hopper GPUs** | model card | `PERMISSIVE`, hardware-gated |
| Adobe `.cube` LUT packs (commercial) | assets | each pack's own terms | — | **`UNKNOWN`** — see §8, `film_stock` ships empty |

**Unverified rows** (do not cite as fact): the macOS x86_64 and Windows opencv wheel contents beyond what note 08's review inspected; `libzimg` and `libplacebo`'s own LICENSE files (both LGPL-2.1+ as FFmpeg *wrapper* code, and absent from every gate list, which is FFmpeg's assertion rather than a verification); torchvision keypoint R-CNN **weights** provenance; whether a source build with `-DWITH_FFMPEG=OFF` actually yields an FFmpeg-free `cv2`; whether conda-forge's `py-opencv` links an LGPL FFmpeg on macOS.

### 5.8 The tier ladder does not gate a licence check `[POLICY]`

Where availability and tier both answer, **availability is the stronger check**: a GPL filter is genuinely absent from an LGPL build, so `filter not in env.filters` refuses exactly the cases the tier comparison does *and* catches `--disable-filter=eq` on a GPL build, which no tier table can. The tier earns its place for the two things availability cannot say: the **nonfree** refusal, and the **redistribution report**. Run both; when they disagree, the environment wins and the disagreement is itself reported. [R7]

**A nonfree build is refused unconditionally, before any ceiling comparison.** FFmpeg itself calls it "nonfree and unredistributable" — the best-characterised refusal available, and one no evidence can lift, so it must not be folded into `UNKNOWN`, whose remedy text is "supply evidence". Detection is free: `-L`'s nonfree branch is first in the cascade. The incremental capability is nil for this package anyway — `libfdk_aac`/`libmpeghdec` are audio, `decklink` is capture hardware, and the `libnpp` filters have LGPL equivalents in `unsharp`/`convolution`. [7][R6]

---

## 6. Live defects in code already committed `[DEFECT]`

All three verified today, in this repo, on this machine. **Close these before anything is built on top.**

### D-1. The `-f null -` invariant has a multi-output hole

`looks/_run.py::check_analysis_only` checks only `argv[-3:] == ('-f','null','-')`. ffmpeg accepts **multiple outputs**, so this passes:

```
ffmpeg -i a.mp4 -c:v libx264 out.mp4 -map 0:v -f null -
```

Verified: `check_analysis_only` accepts it, and the command writes a real H.264 file. The invariant that is the package's headline enforcement is defeated by appending nine characters.

**Fix:** parse *every* output specification, not the tail. An ffmpeg argv's outputs are the non-flag tokens that are not option values; each must be the null sink. Note 04's reviewer proposed "`looks` executes `ffprobe` and never `ffmpeg`", which closes the hole by construction — but `looks/frame_dependency.py` needs ffmpeg to *apply* a filter, and `ffprobe -f null -` fails outright ("Unknown input format: null", verified). So the invariant stays ffmpeg-shaped and the check must count outputs. The AST guard (no `subprocess` outside `_run.py`) is unaffected and remains the half that matters.

### D-2. `needs_gpl` fails open on any unrecognised filter name

Verified: `needs_gpl(['nosuchfilter'])` -> `()`, and `needs_gpl(['EQ'])` -> `()`. It is an allowlist-by-absence, so a typo, a wrong case, a filter from a newer ffmpeg, or one the extraction never enumerated is silently reported as GPL-free. That is a **computed false permission** at exactly the point named as the licence tier's entry point, and it violates the non-negotiable directly.

**Fix:** validate against the known-filter universe first — `env.filters` from the actual binary, or the committed snapshot — and **raise** on any unrecognised name before the gate table is consulted. §5.6's `codecview`/`perlin` leaks are the reason this must raise rather than warn.

### D-3. `geometry._resolve(..., "round")` is not ffmpeg's rounding

`looks/geometry.py` uses `int(round(value))` — Python's round-half-to-**even**, on floats — under a docstring claiming it reproduces ffmpeg's `force_original_aspect_ratio`. ffmpeg uses `av_rescale` with `AV_ROUND_NEAR_INF`: half **away from zero**, on exact int64 rationals. Measured: 6 of 4000 ordinary source/target pairs disagree. The single doctest chosen (1920x1080 -> 1080x1920, giving 607/608) is precisely the case where the divergence is invisible, because 608 happens to be even.

**Fix:** `(2*sh*tw + sw) // (2*sw)` — exact integer arithmetic — and rename the mode, because "round" is the ambiguous word that produced the bug. `"floor"` needs the same treatment: it currently conflates float truncation with exact-rational floor, so the `Placement` still renders differently depending on who reads it, which is the failure the field was introduced to prevent. Carry the **arithmetic domain**, not only the tie-break, and add a regression test on a case where they differ (200x200, not 1080x1920).

---

## 7. The two owner questions

### 7.1 Should `burns` become a `looks` backend? `[RATIFIED 2026-09-02]`

> **RATIFIED by the owner, 2026-09-02: no. `burns` stays separate; `looks` never grows a second geometry-over-time type; `burns` gains a `looks`-backed ffmpeg backend.**
>
> Consequence for this repo: `looks` builds the **compile** side — normalised keyframes to an ffmpeg fragment — and `burns` registers the backend that samples a `BurnsPath` into those keyframes and runs the argv. The dependency points `burns -> looks`, which is legal because `looks` is stdlib-only; the reverse stays forbidden.

**The rule that draws the line — and it is not "geometry versus pixels":**

> **RULE G. If the geometry is AUTHORED — a person or a model chose it as the shot, and changing it changes what the viewer is looking at — it is a camera, and it belongs to `burns`. If the geometry is DERIVED — it falls out of a delivery contract, such that any two implementations given the same inputs must compute the same rectangle — it is conformance, and it belongs to `looks`.**

Rule G predicts every case already in the code, including the one that breaks the naive split: `muvid`'s moving `CropWindow` is a camera move over *video*, and muvid already stores it in `burns.Rect`'s convention explicitly so no rename table is needed.

| Case | Owner | Why |
|---|---|---|
| Scale + pad to 1080x1920 | `looks` | derived from the target canvas |
| Centre-crop-to-fill at 9:16 | `looks` | derived from the aspect mismatch; nobody *chose* the centre |
| Even-dimension snapping | `looks` | derived from a codec requirement |
| Letterbox removal | `looks` | derived from a measurement (**but `cropdetect` is GPL-gated — see the caveat below**) |
| Ken Burns push-in over a still | `burns` | authored — the choice is the point |
| muvid's `CropWindow` / `crop_end` ramp | `burns`-shaped | authored; muvid already uses `burns.Rect` for it |
| muvid#66's in-shot punch-in | `burns`-shaped, **compiled by `looks`** | authored; executed as a filter fragment |

**The case for the other side, taken seriously.** Folding geometry-over-time into `looks` would give one home for everything that touches a rectangle, and `burns.BurnsPath.evaluate(t) -> Rect` is already render-agnostic and JSON-serialisable, so it looks like a `looks` type. It loses on three counts: `BurnsPath` has importers in four packages plus a cross-language `kenburnz` golden-vector contract, so moving it is a federation event; `looks -> burns` is **forbidden** because `burns` declares `moviepy`, which pulls `imageio-ffmpeg`'s GPL binary into a package whose first non-negotiable is zero dependencies; and a fourth normalised-rect convention is exactly what muvid's docstring exists to prevent.

**The adapter, with its mechanism CORRECTED.** `burns` (which may import `looks`, since `looks` is stdlib-only) registers an `"ffmpeg"` backend that samples its `BurnsPath` into keyframes, hands them to `looks` for compilation, and runs the argv itself. `looks` accepts a **structural** `Rect` (`.x/.y/.w/.h`, normalised, top-left origin) and never defines a competing type.

Two research notes told the `burns` owner to use `crop=` and avoid `zoompan`, inheriting a docstring from `muvid/footage/assemble.py`. **Both halves of that advice are wrong on ffmpeg 8.1, verified today:**

- **`crop` cannot zoom, and it does not fail quietly.** An earlier pass recorded this as "`w`/`h` are evaluated once at configuration", which understates it: `t` is **not in scope** for those parameters and the filter **refuses to configure** — `Error when evaluating the expression` followed by `Failed to configure input pad`, reproduced today in all three forms (`-vf` over a file, `-vf` over `lavfi`, and `movie=`), and with only `w` ramped as well as both. Nothing renders. The distinction matters because "evaluated once" invites the reading that you get a frozen-but-working crop; you get no output at all. `crop` expresses a **pan** at constant window size, which is exactly what muvid's `_crop_filter` does and all it does.
- **`zoompan` has time variables and does not duplicate frames.** `in_time` and `it` are both accepted and functional; `t` raises `Undefined constant`. With `d=1` a 20-frame input yields exactly 20 frames, against 1800 at this build's `d=90` default — so the duplication is entirely the default. `zoompan_filter_deps="swscale"`: **not GPL-gated**.

**Three further `zoompan` facts, measured 2026-09-02 while building the compiler, none of which was in the notes** — each is a silent wrong answer rather than an error, which is why each is now a refusal in code:

| fact | measurement | what `looks.motion` does |
|---|---|---|
| `x`/`y` are in **original input pixels**, not zoomed ones | the two readings score **60.5 dB** and **6.3 dB** against a `crop`+`scale` reference for the same window | emits the correct one; a caller never chooses |
| `fps` **silently retimes** | `fps=25` on a 10 fps source keeps all 20 frames and makes a 2.0 s clip **0.8 s** — a frame-count check passes | `fps` is required, never defaulted |
| `zoom` is **clamped at 10**, silently | z=10 scores 54.4 dB, z=12 scores **13.2 dB** — a different framing, not a worse one | refuses a window below 1/10 of the frame |

So the fast path for a varying `Rect` is `zoompan` with `d=1`, an explicit `fps` equal to the source's rate, expressions in `in_time`, and a window that keeps the source's aspect ratio. **All four are compiled by `looks.motion`, so an adapter has to remember none of them.** Full transcript: `docs/research/00f_motion_filters_evidence.md`. **Correct muvid's docstring at its source**; it is currently steering a design decision on a fact that does not hold.

**The reframe, added 2026-09-03 because the refusal blocked the headline case.** `zoompan`'s `zoom` is one scalar, so it can only show a window *similar to its input* — which made a Ken Burns path over a 4:3 still delivered at 16:9, the commonest real case, the one thing `looks.motion` refused. RULE G decides where the fix goes: a reframing crop is **derived** geometry (nobody chooses it; it falls out of the mismatch between the source's shape and the delivery's), which is the same row as "centre-crop-to-fill at 9:16" already assigned to `looks`. So `compile_motion` now emits a static `crop` to the windows' aspect and runs the motion inside it. The crop is the **bounding box of every window**, not a centred one — a centred crop can exclude a window the path visits, silently reframing the shot. Verified by rendering: 62.5 dB against the hand-built start window, 63.5 dB against the end window, and 11.1 dB against the wrong one. A path already shaped like its source is left byte-identical.

**Status: the compile side is BUILT** — `looks/motion.py`, exported as `compile_motion` / `Keyframe` / `Window` and reachable as `looks motion T:X,Y,W,H ...`. It picks the filter from what the path *does* (size varies → `zoompan`, else `crop`), because that is not a matter of taste. Easing stays on burns' side of the seam: a path arrives here already sampled into keyframes and is interpolated linearly between them, which is what lets `looks` never learn what `ease_in_out_cubic` means and `burns` never learn what `in_time` is. What remains is the `burns`-side adapter, which is not this repo's to write.

**Caveat on the letterbox row:** `cropdetect` is GPL-gated *and* it prints to the log rather than cropping, so performing it is a subprocess plus a measurement — both of which `looks` forbids itself. Letterbox *detection* is a `Probe`-side capability the caller runs; only the resulting rectangle is a `looks` effect. [11][R11][2]

### 7.2 Does `looks` own normalisation as well as stylization? `[RATIFIED 2026-09-02]`

> **RATIFIED by the owner, 2026-09-02: yes. One package, one vocabulary, one registry, one tier system, one insertion point. The API difference is two RESOLVERS, not two `Effect` types.**
>
> Shipped as `Look.target = EXTERNAL | SET_RELATIVE` in `looks.spec`, with `resolve` / `resolve_across` and the refusal that a `SET_RELATIVE` Look cannot be resolved against a single clip.

**The case for.** They compile to the same place — not analogously, *literally*: `_render_part`'s `vf` string is one comma-chain and both a continuity grade and an extreme look go into it. Two packages would mean two compilers writing into one string, with ordering negotiated across a package boundary. The Que Calor measurement makes them **mutually dependent**: the right rule normalises the output across sources, so you cannot compute the continuity grade without knowing what the stylization does to the clip — splitting them puts a measurement loop across a package boundary, which is the one thing a boundary must not do. And the tier system bites *harder* on normalisation, because `eq` — the natural grade filter — is the gated one while the whole Que Calor stylization chain is LGPL-clean.

**The case against, taken seriously.** A style Look is meant to be the *same* across an edit; a grade is *different for every clip by construction*. One type risks a clip-specific Look being shipped as reusable. And normalisation wants to be automatic, and automatic things drift toward owning measurement and execution — the two things `looks` must not own. The first objection is answered by the invariant below; the second is already answered structurally, because `looks` declares what must be measured and consumes a probe it never gathers.

**What actually differs is WHAT THE TARGET IS**, which maps onto a distinction the federation already knows from `lookbook`: per-image *scoring* versus set-level *selection*.

```python
resolve(look, probe)         -> Look                  # target external and fixed; one clip
resolve_across(look, probes) -> tuple[Look, ...]      # target = the set's own distribution; N in, N out
```

> **RULE N. `Look.target` is valued `EXTERNAL` or `SET_RELATIVE`. A `SET_RELATIVE` Look may only be resolved through `resolve_across`; resolving one against a single clip raises.**

**The field is `target`, not `intent="style"|"grade"`** — the reviewer's correction, and it is right. A `ColorContract` conform is a *normalisation* whose target is external and fixed (a delivery spec) and which needs exactly one clip's probe; under a style/grade wording it would have to be mislabelled `"style"` or forced through a set-level resolver it does not need. Naming the field for the axis that does the work keeps the rule true. [11][R11]

---

## 8. v1 scope `[DECIDED]`

### Ships in v1

**Already shipped** (do not rewrite; fix per §6): `looks._run` (the process chokepoint + the invariant guard), `looks.environment` (probe + the n8.1 gate table), `looks.geometry` (fit/fill/stretch, crop, pad, social presets), `looks.lut` (gradient-map `.cube` at zero dependencies), `looks.measure` (clip statistics via `ffprobe` with identity fields that refuse a wrong comparison), `looks.frame_dependency` (the two probes).

**To build:** `looks.licence` (§5), `looks.spec` (§4), `looks.registry` + `looks.compile` (§4.6), the ffmpeg backend, the frame backend, `materialize`, `resolve_across` + the min-spread solver, and the effect catalogue below.

**The catalogue: three families plus a separate `Transition` type.** Note 13's own table has 26 numbered rows which it summarises as "twenty-four names"; take the names below as the list and do not quote a count until someone reconciles that. Twenty-two of them have a **verified** compile target on ffmpeg 8.1; `match_clip` and `film_stock` are design-complete and unimplemented by construction. [13]

| family | names |
|---|---|
| grade | `gamma` · `exposure` · `contrast` · `saturation` · `white_balance` · `levels` · `tone_match` · `match_clip` |
| look | `gradient_map` · `lut3d` · `posterize` · `flatten` · `monochrome` · `colorize` · `bleach_bypass` · `cross_process` · `halation` · `vignette` · `chromatic_aberration` · `grain` · `deband` · `blur` · `sharpen` · `film_stock` |
| geometry | `fit` · `crop` · `pad` |

`Transition` is **not** an `Effect`: it is binary rather than unary, it sits at a cut, and it needs two labelled pads which an `Effect` cannot supply without referencing an input index. It carries a caller-supplied, **mandatory** `offset_s`, which is the structural guarantee that `looks` never decides where a cut is. Its vocabulary is ffmpeg `xfade`'s 58 named kinds. [13]

### Deliberately deferred, with reasons

| Deferred | Reason | What would un-defer it |
|---|---|---|
| **Pixel-run fusion** (measured 3.9x: 8 filters at 14.25 ms/frame -> 3.65 via a materialised hald CLUT) | Its failure mode is a subtly wrong picture, and on **real** footage 20% of samples are wrong by >2/255 with a max of 30/255 — the accuracy figures that looked acceptable were measured on synthetic material, which fills a narrow subset of the colour cube. `interp=nearest` is a fork, not a refinement: it *worsens* a smooth stack. | Re-measure on real footage, then ship behind a mutation-tested suite |
| **A `looks.render()` of any kind** | Never. See rule 1. | Nothing |
| **A migration registry** | Zero entries is a stub | The first v2 |
| **A `Resolver` registry** for parameters | It is `Ref` with machinery and no second customer | A measured second resolution strategy |
| **A shader / GPU backend** | Three unrelated mechanisms with different licences, availability and failure modes; the Mac's ffmpeg 8.1 has **zero** programmable GPU filters while the fleet's GPU-less Linux server *has* libplacebo and it is **141x slower than CPU while exiting 0 with correct output**. A GLSL mean-shift is 19-22x faster as a kernel and the whole pipeline still loses. | A render host with a real GPU, and an N-process GPU aggregate measured against the 9-process CPU aggregate |
| **`elbg` posterisation** | 64.85 ms/frame — 9x the entire Que Calor LUT half — and it has no timeline support, so `Effect.at` cannot gate it | A measured quality win |
| **`normalize`, `colorcorrect` with `analyze!=manual`** | Content-adaptive, i.e. the flicker class the whole design is about | Nothing; these are excluded on principle |
| **Every temporal filter** (`tmix`, `tblend`, `atadenoise`, `hqdn3d`, `dctdnoiz`, `fftdnoiz`, `nlmeans`, `minterpolate`) | Structurally incompatible with the execution model: muvid renders one bounded ffmpeg per cut, so a temporal filter sees a hard discontinuity at every cut and produces an artefact at exactly 50 places in the Que Calor edit | A different execution model, which is not coming |
| **`film_stock`'s registry contents** | Every film-emulation LUT pack worth having is commercial or of unknown provenance; shipping one puts a plausibly field-restricted artifact inside a package whose thesis is that unknown terms refuse. **The slot ships empty on purpose** — it exists so `looks` can refuse *correctly*, naming how to register a provider. | A licence-clean pack |

### Refused forever

- **A neural backend, and a neural SEAM.** [9] The house rule is that a seam is declared only when its eventual replacement exists somewhere you can point at. It does not. The one commercially-clean CPU-runnable stylizer (ONNX Model Zoo `fast_neural_style`, BSD-3 code **and** weights) fails the flicker bar by measurement — 1.20-2.82x the source's own frame-to-frame change against the shipped chain's 0.70x — and the ratio *grows as the source gets calmer* (mosaic-9: 1.69x -> 2.77x -> 4.02x), which is flicker's signature and means the failure is worst exactly where an editor notices most. It also costs 2.991 s/frame at 1080p on CPU, i.e. 71.8 CPU-seconds per second of 24 fps output. The licence-clean 2026 video models that would clear the flicker bar natively (ByteDance Bernini-R, plain Apache-2.0) need Hopper-class GPUs. Nothing occupies the intersection. **The hosted neural route is `falaw`'s job**, through falaw#16's `(model, backend)` ledger — and falaw's registry today holds 40 models with **no `video_to_video` category at all**, so even that is a future integration.
- **`av`, `imageio-ffmpeg`, `moviepy`, `ultralytics`, `opencv-contrib-python`.** Each with its recorded reason (§5.7); a prohibition without a stated reason gets relitigated.
- **`argh`** for the CLI (LGPL-3.0, and its PyPI metadata `License:` field is **empty** — only the shipped `COPYING`/`COPYING.LESSER` pair says so, which is exactly the class of fact this package exists to catch). **The CLI is `cw`** (`$PP/i/cw`, MIT, `dependencies = []`, on PyPI): verified 2026-09-02 that `import cw` pulls in **nothing** beyond stdlib — its `argcomplete` and `i2` imports are lazy, inside the functions that need them. It is the fleet's own `argh` replacement, so `looks` neither reaches for the LGPL package nor hand-rolls `argparse`. `typer` stays refused: it pulls six packages into a distribution that declares stdlib only. [2][R2]
- **Any dependency added without inspecting what its wheel SHIPS.** Three of the most obvious media dependencies in Python declare permissive licences while shipping GPL binaries. That is not three coincidences; it is what the packaging ecosystem normally does, because wheel metadata describes the project's own source and nobody's tooling looks inside `.dylibs/`.

---

## 9. Standing rules `[POLICY]`

Numbered, checkable, and each one has a test or is not a rule.

**Scope and process**

1. **`looks` starts no process that can produce media.** Every ffmpeg invocation's **every** output must be the null sink (see D-1); `ffprobe` is exempt because it has no muxer. Never write a `render` / `apply` / `encode` / `write_video`. A test asserts their absence, a second asserts no module imports `subprocess` outside `looks/_run.py`.
2. **`looks` decides no cut.** `Effect.at` is a span within one clip. `Transition.offset_s` is supplied by the caller and is mandatory. A `SourceMap`, if one is ever accepted, is read-only and omits `clip_in` — so it cannot be re-rendered from, which is the checkable test that it is not an EDL.
3. **Unknown is a refusal — for a licence, a filter name, an ffmpeg build, a colour contract, and a parameter.** Never a warning, never a default, never "probably LGPL". Consequence: an unrecognised filter name **raises** before the gate table is consulted (D-2).
4. **The environment is an argument.** Nothing downstream of the caller may call `probe()` for itself. A compiled plan is valid against one `FfmpegEnv`, not against a machine.
5. **Never read a licence from a package's metadata field or from a library's own self-report.** Read the shipped binary (`otool -L` / `ldd`). `av` is the worked example: three layers disagree and the two easy ones both look reassuring.
6. **A tier is a property of the `(effect, provider, resolved environment)` triple, never of a package name.** The environment includes which *wheel* is installed, not just which library.
7. **A refusal names the remedy.** Which tier is needed, which ceiling is in force, the dated observation that decided it, the exact call that would widen it, and **any lower-tier alternative implementation**. Four distinct exception types — `LicenceCeilingExceeded`, `LicenceForbidden`, `LicenceFieldRestricted`, `LicenceUnknown` — because the remedies genuinely differ (raise the ceiling / no opt-in exists / a separate opt-in / supply evidence).

**The measured facts, as rules**

8. **Parameters resolve against the clip they apply to.** A number fixed at the top of a Look is provably wrong for the flagship case.
9. **Normalise the OUTPUT across sources, not the input.** Do not sharpen the soft one: measure **post-effect** and pick parameters that land the clips in family. Full resolution was available and sharper and was deliberately **not** used, because at ~150 Laplacian variance it would have made the softest source the *sharpest* thing in the edit — a new mismatch rather than a fix.
10. **Measure post-effect, and never measure the source file.** The c01-vs-c02 sharpness ordering **inverts** between the source files (841 vs 563 Laplacian variance says c01) and the finished render (41.9 vs 66.2 `siti.si` says c02), because c01 is upscaled 2.68x. A resolver measuring sources would have corrected the wrong clip.
11. **`pyrMeanShiftFiltering`, never `edgePreservingFilter`.** The latter smooths *across* object boundaries and dissolves figures into the background. Mean-shift clusters in colour **and** position, so boundaries survive.
12. **A substitution is lossy until measured otherwise, and must be declared.** `eq`'s permissive substitutes are not drop-ins: `eq` exposes contrast/brightness/saturation/gamma (+`gamma_r/g/b`, `gamma_weight`); `colorlevels` gives per-channel black/white points only; `colorcorrect` gives shadow/highlight spots and `saturation`; `hue` gives `b`,`s`. Measured, `saturation` at s=0.5 differs by mean 9.90/255 between `colorchannelmixer` and `hue=s`, 95.9% of samples off by >2/255. A **silent** substitution applies a different transfer function and therefore defeats rule 9 — you cannot land clips in family if the commercial-safe path grades them differently. Declare it on `ImplRef.lossy_substitute_for`, surface it in the plan, or make it explicit opt-in.  **The one exact substitution measured so far:** `eq=gamma` -> `lutyuv=y='clip(pow(val/255,1/g)*255,0,255)'`, within 0.55/255 mean luma across g=0.7/1.0/1.5/2.2, identical p10 throughout.
13. **Gamma, never a brightness offset.** An offset lifts the black floor and reads as haze.
14. **Do not end a ramp at black.** A dark anchor at L\* 3.6 crushed 16.2% of pixels into the bottom bin where the reference had 0.3%; its own floor was an oxblood at L\* 8.22. Setting the ramp's dark end there took histogram distance 46.7 -> 32.0 pp. `looks.lut.gradient_map` warns below L\* 5.
15. **Measure the target before assuming a filter.** The Que Calor reference had **no black (0.0000%), no white (0.07%) and no outlines**, so the classic cartoonify (bilateral + adaptive-threshold black edges) would have been exactly wrong — it adds ink the reference never had.
16. **The probe budget is 5 frames, not 3.** A 3-frame median carries p90 relative error 12.7-34.0%, larger than most improvements a resolver chooses between; k=5 gives 10.0-19.6%. Identifying an outlier (c03, 1.85x separation) is easy at k=3; ranking c01 against c02 (1.15x) was never resolvable at k=3, which is why they swapped between instruments and windows. Return a fourth verdict, `inside_noise`, when an improvement does not clear the measured uncertainty.
17. **Never compare two `ClipStats` whose `stage`, `instrument`, `luma_space` or `sample_spec` differ.** `compare()` raises. Each was measured to change the answer by more than the effect being tuned. Note the live caveat: **`siti` converts limited->full range internally before the Sobel**, so `sharpness` is a full-range quantity while `signalstats`-derived luma is a coded one — a single `luma_space` field cannot describe both, and the same pixels give a 16.3% different `siti.si` depending only on a metadata tag. Either split identity per statistic, or normalise the range tag before probing and spell the instrument `siti@range=<tag>`.
18. **The measurement geometry is part of a sharpness metric's identity.** Downsampling a 1536px image to 512 drops `cv2.Laplacian(...).var()` by ~18x, and the ratio *differs* between a sharp image (0.056) and a soft one (0.066) — so it is not even a constant rescale and rank order can move. Do not adopt `lookbook`'s `max_side=512` default: it is right for ranking one pool measured identically and wrong for comparing across sources of different resolution, which is this package's central job.
19. **Mean-shift cost rises as `sr` FALLS.** At 0.5 scale, 720p: `sr=60` costs 60.1 ms and `sr=30` costs 173.5 ms — a narrower colour radius is ~3x *more* expensive, because narrower windows converge more slowly. `sp` is roughly quadratic. Consequence: the shipped `c03` setting (0.75 scale, `sr=40`) is the **most** expensive of the three shipped configs. Any cost model built on "cost proportional to radius" is backwards. And `estimate()` must be allowed to return `None`: the cost is **content**-dependent (convergence), which is exactly what a spec layer cannot see.

**Compilation**

20. **A compiled filter string references no container input index.** A second source enters via `movie=` or a lavfi source (`color=`, `haldclutsrc=`, `noise=`), never via `[1:v]`. Consequence: `looks` never emits `-filter_complex`, and its output splices into a bare `-vf`, into muvid's per-cut chain, and into a pipe's encoder half alike. **Corollary:** a stage that opens a second source must be prefixed with `null` so chain 0 still presents one input pad — `movie=` is a *source* filter with zero input pads, so a stage beginning with it is not splice-able by the rule above.
21. **`looks` owns filtergraph escaping.** Verified: `-vf "lut3d=file=id,with:comma.cube"` fails; escaped as `id\,with\\:comma.cube` it works. The flagship effect takes a caller-supplied file path, and the package's entire output is a string another process will parse. Extract `muvid`'s `escape_filter_value` (a correct **double** escape for ffmpeg's two-level parser, applied in mirror order) as extraction item #1, with its recorded negative that `%` must **not** be escaped. Tests for `,` `:` `\` `'` `[` `]` in paths, in v1.
22. **An unknown colour contract is a refusal** when the Look contains an RGB-domain effect. Escape is an explicit `assume=ColorContract(...)` that is **recorded in the plan**. See §4.2 for the measurement.
23. **Declare, do not convert.** `scale=in_range=:in_color_matrix=` is free when in==out (0.00 ms/frame); the `colorspace` filter is not (2.37 ms/frame — as much as the whole `lut3d` it would wrap). And **never emit a bare `format=rgb24`**: on an 8-bit tagged source `format=rgb24,lut3d` is byte-identical to bare `lut3d`, and on a 10-bit source ffmpeg picks `gbrp10le` on its own while `format=rgb24` throws two bits away immediately before a 3D LUT.
24. **The colour tags are a filter-side job, not an encoder-side one.** `-colorspace bt709` changes the encoded planes but silently drops `-color_primaries`/`-color_trc`; `-x264-params colorprim/transfer/colormatrix` sets all three tags but leaves the planes on bt601 — a **mislabelled** file, worse than untagged — and it is a libx264-private option silently ignored by every other encoder. Carry the required output `ColorContract` as **data on the plan** and render it into the filter string as `scale=out_color_matrix=...` (which decides the numbers) plus `setparams=colorspace=...:color_primaries=...:color_trc=...:range=...` (which decides the labels). Codec- and muxer-agnostic, and it is the one artifact `looks` produces.
25. **Validate and WARN on ordering; never reorder.** One rule: a quantiser should be last among the pixel stages. Measured: LUT->posterise vs posterise->LUT differs on 100% of pixels (max 55) and yields 51 vs 96 distinct 5-bit colours; downscale after vs before the colour chain yields 359 vs 77. Warn rather than raise because posterise-first is a legitimate different look — contrast the licence and colour gates, which raise because the caller *cannot see* the answer. Never reorder, because a plan that does not match its Look destroys the diffability the `falaw.Plan` shape exists for.
26. **`curves` must be emitted with `interp=pchip`, never the default.** ffmpeg's own help: default is `natural` (natural cubic spline), and `pchip` is "monotonically cubic interpolation". Measured on the steep knee a histogram match produces, `natural` emitted 21 and 20 non-monotone steps out of 255; `pchip` emitted 0. The trap is that a *gentle* curve gives 0 under both, so the defect ships and then appears on one clip. **This package stated the rule and then broke it** — `contrast` shipped as a bare `curves` from 0.0.4 to 0.0.12, found by the `muvid` integration reading the rule and grepping for it. See 29c for what replaced it, and why `interp=pchip` was the smaller half of the fix.
27. **A fold across a raw-frame boundary must rewrite `enable=`.** The encoder half of a pipe reads `-f rawvideo` and carries no container timestamps, so its filter timeline starts at 0 regardless of the decoder's. Folding a downstream chain carrying `enable=` silently rebases its time origin — the same failure class as an unrebased `-ss`, reintroduced by the compiler's own optimisation. Either rewrite the expression or refuse to fold a chain that carries one.
28. **`Span` is expressed in the host's decoder time, which the host declares.** Verified: **input-side** `-ss` rebases the filter timeline to 0; **output-side** `-ss` does not. So "part-local time" is a property of the host's seek style, not of the clip. `ClipSpec` (or a `ClipContext`) must carry the origin, documented as *the source time of this part's frame 0 as the host's decoder will see it*. muvid uses input-side `-ss`, so 0 is right for the first customer and wrong in general.
29. **A `Look` that reaches a filter absent from the declared environment is refused at compile time**, naming the binary probed and any substitute at or below the ceiling.
29b. **Two implementations of one effect, chosen by licence tier, must agree on the picture — and that agreement is tested by rendering both, never by reading either.** The tier decides which filter runs; it must not decide what the viewer sees. Measured on this package's own shipped `contrast` (0.0.4-0.0.12): the LGPL path flattened the picture where the GPL path steepened it, at every amount except the identity — slope 0.45 against 1.48 at `amount=1.5`. A caller who could not use GPL got the reverse of what they asked for, at exit 0. The guard is a parametrised render of both paths on a 256-step ramp, asserting the *sign* of the deviation from identity first and the magnitude second; the direction test is the one that catches a wrong formula, and the magnitude test the one that catches a wrong pivot.
29c. **Do not draw a straight line with a spline.** A linear transfer belongs in `colorlevels`, not `curves`. Emitting the old `contrast` as a spline cost three defects at once: it eased through the clip corner (up to 45/255 from the GPL sibling's picture), it rang under ffmpeg's default `interp=natural` (89 non-monotone steps out of 255 at `amount=1.8`), and at `amount >= 2` the clamp collided its interior points with its endpoints so **ffmpeg refused the render**. `colorlevels` has none of the three because it *is* the shape of the transfer, and it is equally LGPL-clean. Rule 26 still stands for anything that genuinely needs a curve; `looks` now emits none, so it is enforced as a perimeter sweep over the registry with a positive control, rather than as a check on one effect.

**Testing**

29d. **CI must have the binary this package is a facade over, and a test must never encode one build's ffmpeg as the truth.** Before this was declared, CI ran 890 passed / **346 skipped** — every pixel, licence-tier and filter-availability claim was verified on one laptop while a green tick suggested otherwise. Giving CI ffmpeg turned 346 skips into 1152 passes and **65 failures**, none of them the package: 60 tests wrote FFV1 into an `.mp4` (accepted by 8.1, EINVAL on the 6.1.1 Ubuntu ships), 2 asserted `not env.has_filter("vidstabtransform")  # Homebrew lacks it` (Ubuntu builds `--enable-libvidstab`), 2 pinned `gradients` `speed=0` (8.1 accepts it; 6.1.1 refuses, range `[1e-05, 1]`), and 1 was the TOML reader meeting its first dotted key. The pattern in all four: **a value chosen because it worked here**. Derive the environment-dependent thing from the probe (`known_filters() - env.filters`), pick the value every build accepts rather than the extreme one, and prefer the container/filter that has been stable longest.
29e. **A greyscale instrument cannot compare two implementations of a colour effect.** `contrast`'s LGPL and GPL paths were asserted interchangeable by 51 tests that rendered a grey ramp and read ONE of three channels. Grey is precisely the input on which a luma contrast and a per-RGB-channel contrast agree; on colour they differ by up to 178/255 and move opposite ways. An adversarial reviewer proved the guard blind by mutating the compiler to touch only the red channel — all 51 tests still passed. The instrument must contain the property being asserted: compare colour, and compare every channel.
29f. **A count that depends on an argument you did not take is a bound, and must be named one.** `blended_frames` returned `floor(duration*fps) - 1` and called it the count; the true count depends on the transition's **offset** (0.10 s at 30 fps blends 2 frames at offset 0.5 and 3 at 0.42) and the old formula was wrong in 14 of 27 measured combinations. It is now the guaranteed minimum `ceil(D) - 1`, with `max_blended_frames` giving `ceil(D)` and an exact answer when `offset` is supplied — validated 72/72 against ffmpeg. The tests missed it because every row of the parametrisation sat where the two candidate formulas happen to agree.
29g. **A parameter the caller can set must reach the code that acts on it.** `compile_motion` accepted an `aspect_tolerance`, and `zoompan_fragment` re-checked with a hardcoded `EPSILON`, so widening it changed nothing — and the refusal named the window's SIZE when the real complaint was a 5e-7 aspect drift. A knob that works in only one direction is not a knob; test both.
29h. **A validation inside one implementation is a validation the licence tier can switch off.** `contrast` with `amount=-1` was refused on the LGPL path and emitted `eq=contrast=-1.0` when the GPL implementation was pinned. Effect-level constraints belong in `looks.compile.EFFECT_PARAM_CHECKS`, keyed by effect and applied before an implementation is chosen: rule 29b says the tier must not decide what the viewer sees, and it must not decide what is accepted either.
30. **Offline and free.** Synthesise sources with `ffmpeg -f lavfi`. But **not every lavfi source is deterministic**: `testsrc2` is bit-reproducible with no pinning (verified, md5-identical across runs); `gradients` defaults to `seed=-1` and `speed=0.01`, and two identical command lines differed by the full 255/255. Pin the geometry, pin `speed`, and check any new source for a `seed`.
31. **Compare decoded pixels, never encoded bytes.** An mp4 is not byte-comparable across builds.
32. **Skip with `pytest.skip` inside the test body, never `importorskip` at module scope** — that removes tests from *collection*, making their absence invisible in both the pass and the skip counts. In `an`, eleven such module-level guards hid 34 tests, **13 of which needed no browser at all**.
33. **Never write a doctest from what you expect the output to be. Run it first.** Two bugs in this repo passed their doctests and failed against reality: a filter-row regex tested against a hand-invented sample returned zero filters from the real binary, and a "neutral" ramp that is not an identity.
34. **Tests live in `looks/tests/`, never a repo-root `tests/`.** CI runs `pytest --doctest-modules looks`, so anything outside the package directory is never collected — a green tick over zero tests.
35. **Guard the guards, and mutation-test them.** The claims this package makes are refusals; a refusal guard that has silently stopped refusing is worse than none. Every rule above that has a test gets a mutation asserting the test fails when the rule is broken.

---

## 10. Build order

Each step names what it unblocks. Steps 1-3 are independent of each other after step 0; everything from 4 on is sequential.

**0. Close the three live defects (§6).** *Unblocks:* every claim the README already makes. The `needs_gpl` fail-open in particular makes the package's headline example untrue for any input outside the table.

**1. `looks/licence.py`** — the four axes, `Terms`, `Tier`, `Policy`, `Verdict`, `classify` / `assess` / `check`, the four exception types, and the evidence ledger at `looks/data/provider_terms.json` keyed on `(provider, realisation, component)` with the tier **derived** and re-derived by a test. Include the fall-through fix from §5.4 and a mutation test for it. *Unblocks:* `ImplRef` can declare terms; every refusal message; the extras table becomes a tested artifact rather than a convenience list.

**2. `looks/spec.py`** — `Span`, `ClipSpec` (with colour state), `Ref`, `Effect`, `Look`, `resolve`, serialisation with the two schema tags, `look_hash`. No registry, no environment, no I/O. *Unblocks:* authoring, persistence, diffing, and the whole "a Look is a document" property — reachable before any compiler exists.

**3. `looks/environment.py` hardening** — key the filter cache on the **resolved binary path** (an `lru_cache(maxsize=1)` over a hardcoded `['ffmpeg','-filters']` answers questions about whichever binary was probed first, on the very two-binary machine this package documents); add `EnvFingerprint`; add the per-**option** probe (`-h filter=NAME` stdout, reading each option's `T` flag). *Unblocks:* rule 4 and rule 29 become enforceable rather than aspirational.

**4. `looks/registry.py` + `looks/compile.py`** — **BUILT.** One correction discovered while building it, recorded here because it changes the contract: an **ffmpeg step's tier is a property of the binary**, so `compile_look` substitutes the probed binary's terms into every ffmpeg candidate *before* selection, and `env` is therefore **required** for an ffmpeg step — unknown binary, unknown tier, refusal. The payoff is that the same `Look` compiles to `eq` on a GPL build and auto-substitutes `curves` on an LGPL one, with no licence logic in the caller. Original brief: — `ImplRef`, `register_effect`, `select_impl` (with `timeline` as a candidate *filter*, and `preference` as the explicit tiebreak), `Step`, `LookPlan`, `compile_look(look, *, clip, env, policy)`, `plan_hash`, `output_key`, and **`audit(plan) -> None | Refusal`** so a plan that crossed a process boundary can be re-checked against its own declared ceiling. A hand-rolled ~20-line dict registry with `xdol`'s semantics (error on conflict, a reserved tags field), declared in the module docstring as a **deliberate** deviation from the ecosystem's `xdol.Registry` on the zero-dependency rule. *Unblocks:* everything below.

**5. The ffmpeg backend and the first twelve effects** — **BUILT** (`looks/ffmpeg.py`): lut3d, saturation, contrast, gamma, levels, posterize, blur, sharpen, fit, fill, stretch, motion. LGPL and GPL implementations are **both** registered where both exist, with the LGPL one at a lower `preference` — an ordering, not a licence judgement. Escaping (rule 21) ported with its `%` negative and verified first-hand against a real `.cube` whose name contains `,` `:` `'` `[` `]`. Two choices worth recording: posterize quantises through `lutrgb` and **not** `elbg`, which is non-deterministic (two runs of one command disagreed by 70-86/255); and every registered effect is swept against the binary, which on its first run caught `unsharp` being given a non-existent `amount` option — the real name is `luma_amount`, and no string test would have found it. Original brief: — the grade family, `gradient_map` / `lut3d` / `posterize`, and the three geometry effects wrapping the existing `looks.geometry`. Escaping (rule 21) lands here. *Unblocks:* the Que Calor look's LUT half, end to end, as a compiled plan.

**6. `materialize(plan, *, into=...)`** — **BUILT** (`looks/cache.py`), and it found the collision the brief predicted: `title` reached the file's bytes (an Iridas `.cube` opens with `TITLE "..."`) but not `cube_key`, so **two different files shared one address** — verified, not reasoned about. `title` and a `GENERATOR_VERSION` are now in the key. The plan-level verb is separate from the spec-level `cube_file` precisely so `compile_look` keeps writing nothing: a compiled step carries a cube *request* (plain data, JSON-round-trippable, asserted) and `vf()` **refuses** an unbuilt plan rather than emitting a filter pointing at nothing. Atomicity is tested with 16 real concurrent processes, not by citing `os.replace`. Original brief: — the content-addressed `.cube` cache. Key = `sha256(generator name + GENERATOR_VERSION + canonical spec)`; canonicalise **before** hashing (coerce `size` to int, normalise hex case, reject unknown keys) so the key addresses the bytes rather than the Python object graph; the LUT title lives **in** the spec, because a second channel into the file's bytes that bypasses the key makes two artifacts collide. Use `tempfile.mkstemp(dir=...)` plus `os.replace` — a deterministic `.tmp` path is not atomic under the per-cut fan-out this package is built for, and a half-written `.cube` read by ffmpeg is a silently wrong picture rather than an error. *Unblocks:* a `lut3d=file=` payload that is reproducible and garbage-collectable. Rationale for generating rather than referencing: the spec is 566 bytes of JSON against a 948 KiB artifact, and generation (0.141 s for 33³, stdlib only) beats a network read.

**7. The frame backend and `flatten`** — **BUILT** (`looks/pipe.py`). Rule 27 was reproduced first-hand before the code was written, and the wrong answer is not subtly wrong: on a flat source with an output-side seek of 3 s and a gate at t=4-5, the unfolded chain brightens output frames **10-20** and the folded one brightens **40-49** — a different second of the clip, for a different duration, at exit 0 with an empty stderr. Rebasing by the origin restores 10-20 exactly. `looks` therefore **rebases the structured span and refuses a foreign `enable=` string**: it owns every expression it generates, so the rebase is one subtraction, while rewriting an arbitrary ffmpeg expression could not be checked. Folding into the DECODER is always safe and needs no rule — rule 27 reads as if both directions were at issue and only the encoder side is. `ClipSpec` gained `origin_s` (rule 28), **`None` meaning undeclared and never 0**, refused rather than assumed when a gated step folds. `flatten` ships as `bilateral` — **verified present and NOT GPL-gated**, which keeps the effect off the platform-dependent cv2 tier entirely; it is registered as an available implementation, **not** as an equivalent of the mean-shift flatten, which remains the owner's call. Original brief:  — the pipe **plan** as data (decoder/encoder argv emitted, never spawned), with the fold rule and its `enable=` rewrite (rule 27). *Unblocks:* the whole Que Calor chain as one inspectable plan, and the honest CPU-second total for it.

**8. `resolve_across` and the min-spread solver** — **BUILT** (`looks/across.py`). The sweep is **proved against brute force**, not argued for: 500 randomised trials over ties, duplicates and values repeated across clips, **zero disagreements**, plus the trimmed variant against a combinatorial reference. Measured 0.093 ms at N=30/|G|=8 against an exhaustive 8**30 ≈ 1.24e27. Three facts established while building it: minimising the spread of logs **is** minimising `max/min` (same objective, same picks, verified), which is why the answer is scale-independent — multiply every measurement by 1000 and nothing moves; `log(0)` does not exist and a flat clip genuinely measures 0, so a non-positive statistic is **refused rather than clamped**, because clamping invents a measurement; and **the trim costs no exactness** — "at least N−k of the lists" is the same sweep with `>=` for `==`, which is what makes the dispersion functional a field rather than a fork. The fragility claim reproduced: at N=30 with one unfixable clip, `max/min` gives **9.026x** and dropping that clip gives **1.037x** — the outlier is **98.3%** of the log window, and the other 29 clips' whole remaining freedom moves it ~13%.

**Four defects in it, found by an INDEPENDENT verification** run in parallel and reported after the item shipped. That agent wrote three solvers from the problem statement alone and reproduced §4's measured figures exactly — per-clip **2.0039x**, uniform **2.2130x**, sharpest **2.3644x** — agreeing with the shipped solver over **57,790** objective-value comparisons; then it mutation-tested *its own oracle* and found that 6 of 9 mis-writings of the sweep are caught while the `<=`-for-`<` one is caught **0 times in 1001**, because an objective-value oracle is structurally blind to tie-break drift. That is why the determinism guarantee needs its own test rather than riding on the agreement test. Fixed: `Choice.statistic` was `exp(log(measured))`, which **147 of 200** realistic values fail bit-equality through (117.0 became 117.00000000000003) and which reaches the `looks.spread/v1` wire document; `ratio` could raise a bare `OverflowError` in a module where everything else is an `AcrossError`; `choices` followed the caller's insertion order, so two logically identical inputs produced different documents; and **N=1 returned 1.0 where `looks.measure.dispersion` refuses the same quantity** — two modules disagreeing about whether a one-element spread is a question, which is exactly the drift the guards exist to catch.

Original brief: — on top of the existing `looks.measure`. The objective is `min_spread` in **log** units, solved by an exact O(N log N) two-pointer sweep — it reduces to "narrowest window containing one element from each of N sorted lists", so it is closed-form, not a search; the exhaustive product everyone reaches for is |G|^|S| (8^30 at 30 clips). Reproduced: per-clip 2.004x beats uniform 2.213x beats sharpest-everywhere 2.364x. Type the objective as a `Literal` with exactly one member so "maximise the statistic" is unrepresentable, and carry the **dispersion functional** as a separate field, because `max/min` is defensible at N=3 and fragile at N=30 where one unfixable clip sets the whole window. *Unblocks:* the measured per-source rule, mechanised; and Rule N.

**9. The `Transition` type and the two surviving `mixing` transitions.** — **BUILT** (`looks/transition.py`): the type, the 16-curve vocabulary and the floor. It emits **options, not a filter** — `xfade` is two-input and rule 20 forbids a fragment that references an input index, so `looks` says what the transition IS and the host wires the streams. Two things measured while building it. An unknown curve makes ffmpeg say *'Not yet implemented in FFmpeg, patches welcome'*, naming neither the mistake nor the filter — which is the case for owning the vocabulary, stated in ffmpeg's own words. And **the floor is not a constant**: a transition shorter than about one frame period blends nothing, so at 10 fps a 0.10 s fade is a hard cut while at 30 fps it blends 2 frames. `MIN_TRANSITION_S = 0.04` is exactly one frame at 25 fps — which is where the inherited number came from and why it is too small below that — so `blended_frames(transition, fps)` is the honest form. `duration=0` is accepted by ffmpeg without complaint and is refused here. Original brief: — Of `mixing`'s six, only `crossfade_transition` and `fade_through_black` are pure pixel blends; `slow_motion_blend` retimes (2.0 -> 2.8 s), and `trim_first_frame_from_subsequent_clips`, `trim_and_crossfade` and `overlap_blend` are trims — i.e. EDL decisions the kickoff's own exclusion bars. **Measured: `crossfade_transition` and `overlap_blend` render a HARD CUT today** (red 252 -> green 254 in one frame), because moviepy 2.x's `concatenate_videoclips` defaults to `method='chain', padding=0` and never composites the CrossFade masks. Do not move a measured no-op; fix it in `mixing` with `method='compose', padding=-duration`, and take the *vocabulary* here. *Unblocks:* the `mixing` refactor.

**10. muvid integration** — the local-render Transform hosted in `muvid`, the `-vf` splice into `_render_part` **and** into `_norm`'s transition A/B path (the same template appears twice; a look must land identically on both or a cut's two sides disagree at the blend), and muvid#66's in-shot punch-in via the corrected `zoompan` mechanism. *Unblocks:* the first real consumer, and the rule-of-three clock toward graduating the Transform into `nw`.

**11. The `mixing` refactor, corrected.** `get_video_dimensions` **does not move** — it is a probe, not geometry, and `paces` calls it at five sites (`paces/paces/derivation.py:694,889,923` plus two tests) behind an explicit `mixing>=0.0.39` floor whose pyproject comment names it. `SOCIAL_SIZES` and the fit/fill/stretch/social semantics move as a **vocabulary port**, not a code move: `video_util.py` imports moviepy at module scope, and the `social` branch is not arithmetic at all (it composites a scaled, centre-cropped, Gaussian-blurred, dimmed copy of the input). `mixing` keeps its moviepy implementations and imports the vocabulary back, gaining exactly one new dependency edge — `looks`, which is stdlib-only. *Unblocks:* one home for the crop arithmetic that currently exists in four places with **three different roundings**.

**12. File the `muvid` `eq=` issue.** — **FILED: thorwhalen/muvid#69**, and it turned out to be stronger than a licence point. Measured on a dark gradient at `dim=0.3`: the additive offset crushes **62.00%** of pixels to black against the source's 8.80%, leaving **4 distinct colours where the source had 97**. So the `colorchannelmixer` replacement is not merely LGPL-clean, it keeps the shadow separation the dim was presumably meant to preserve. The two are 19.9 dB apart and `layout.dim` will want retuning once — a deliberate change, stated as one. Original brief: `muvid/visualize/canvas.py:224` emits `eq=brightness=-<dim>:saturation=<sat>` — the single `eq=` in the whole muvid tree, against nine uses of `colorchannelmixer` elsewhere in the same package. It is GPL-only, and `brightness` is the additive offset rule 13 forbids. Replacement: a scaled `colorchannelmixer` matrix. **One filter call quietly raising a shipped product's licence tier for a cosmetic dim, with a better replacement available, is the concrete case for this package existing** — use it as the worked example in the docs.

**13. The `burns` adapter** — §7.1 ratified and the `looks` half **built** (`looks/motion.py`). What remains is on `burns`: register an `"ffmpeg"` backend that samples a `BurnsPath` into keyframes, calls `looks.compile_motion`, and runs the argv. Correct `muvid/footage/assemble.py`'s `zoompan` docstring in the same pass — it is wrong and it steered this design for two research notes.

---

## 11. What the research could not settle `[OPEN]`

| Question | Why it is open | What would settle it |
|---|---|---|
| **Does `cv2`'s dynamic linkage of its bundled GPL libavcodec count as `looks`' own in-process coupling?** Read one way it is `FORBIDDEN` at every ceiling and OpenCV is unusable from `looks`; read the other it is `COPYLEFT_SHIPPED` and merely above the default. | This is exactly the adjudication the honesty rule forbids `looks` from making. `import cv2` maps `libavcodec`/`libx264`/`libx265` into the process unconditionally (verified by `vmmap`), so "do the flatten in numpy" does not help if anything in the process imports `cv2`. | **The owner, or counsel.** Or make it moot: an OpenCV built with `-DWITH_FFMPEG=OFF`, a non-OpenCV mean-shift, the FFmpeg-free macOS x86_64 wheel under Rosetta, or an ffmpeg-native flattener. |
| **Is the tuned two-pass `bilateral=sigmaS=60:sigmaR=0.05` @0.75 visually acceptable as the Que Calor flatten?** It reaches edge-retention ratio 2.593 against mean-shift's 2.251 at 58.1 fps (4.4x the shipped chain) but lands Laplacian 51.4 vs 41.9 — small quantised patches rather than large flat regions. | Only measured, never *looked at*. | Render 30 s and watch it. If it passes, OpenCV — and its GPL-bundling wheel — leaves the first shipped look entirely, which is a bigger win than any backend. |
| **Is the `siti` <-> Laplacian-variance relationship (+0.923 Pearson) stable POST-effect?** | Measured on *source* frames. The stylizer creates hard flat-region boundaries — a different image-statistic regime — and the resolver measures post-effect by definition. | One sweep over stylised frames. |
| **What dispersion functional is right above ~3 clips?** `max/min` is defensible at N=3 and fragile at N=30, where one unfixable clip sets the whole window. Should the solver be allowed to DROP an infeasible source and report it separately? | Nothing measured it. | A weighted MAD or trimmed range in log space, measured against a real 30-clip edit. |
| **Whose ceiling does `Transition.duration_s` belong to?** A *working* crossfade shortens the output by exactly the transition duration, so `duration_s` decides which frames survive — an EDL quantity by rule 2's own test. | The evidence that it preserves duration was a measurement of the broken implementation. | A rule stated so it survives a working implementation: the caller owns the boundary and the overlap; `looks` paints one it is handed and *reports* the resulting duration; it never chooses one. |
| **Where does the licence record physically live** — `looks`, or falaw#16's ledger? | They overlap and do not coincide: falaw's key is `(model, backend)` and is about vendor calls; `looks`' key is an effect name and covers ffmpeg filters, OpenCV functions and local weights falaw will never see. `binds_us` is falaw's invention and `looks` structurally lacks the input to populate it. A shared table means `looks` depends on `falaw`, which the zero-dependency rule forbids. | An owner ruling. Likely shape: `looks` owns the vocabulary as a validated enum in a JSON table; `falaw` imports the enum names; `looks` **references** falaw's ledger rather than copying `binds_us`. |
| **Where does a caller who needs an LGPL ffmpeg actually get one?** The whole `WEAK_COPYLEFT` rung is only useful if the binary is obtainable. Homebrew, Debian and the imageio bundle are all GPL. | Not surveyed. Nothing on this machine provides an LGPL ffmpeg *binary*. | Either find a distributor, ship a documented build recipe, or say plainly in the docs that rung 2 is satisfiable only by a self-built binary. |
| **Is training-data provenance in scope for a per-effect tier?** No licence surveyed addresses it — the BSD-3 grant on the ONNX weights says nothing about COCO 2014's Flickr images, and `pytorch/examples`' style images include a Leonid Afremov painting (d. 2019, in copyright). | Recording `training_data: unknown` for every neural row forever is a field that refuses everything. | An owner decision about whether "unknown, recorded" is more useful than silence. |
| **Does the shipped `frame_dependency` probe pair actually separate all five classes?** As constructed it cannot detect TEMPORAL (`tmix`, `tblend`, `hqdn3d` all pass both probes) and, with the perturbation in the far corner, cannot separate PIXEL from FRAME (`gblur=sigma=4` reads 0.00%). | Both were found by the reviewer, not by a test. | The PIXEL/FRAME half is a one-line fix, verified: move the perturbation adjacent to the shared region. TEMPORAL needs a **third** probe — a varying two-frame sequence, checking output frame *N* is unchanged when frame *N-1* is replaced. Until then `Dependency.UNDETERMINED` must be the **default**, never `INDEPENDENT`. |
| **Should `looks` refuse `geq` anyway, despite it being LGPL?** Its expression evaluator is per-pixel-per-frame and a caller-supplied expression is arbitrary input to it. | A security/performance question, not a licence one — but this is the natural place to record it, since `geq` is now the LGPL escape hatch for anything `lutrgb` cannot express. Measured: a 5-tap RGB neighbourhood runs at 55.6 fps against `scale`'s 1013.8 fps at 640x360. | An owner decision, informed by whether any caller ever supplies an expression `looks` did not compose. |
| **Does the `social` backdrop have to match `mixing`'s output pixel-for-pixel?** | The parameterisation matches (`gblur` sigma 15, `colorchannelmixer` 0.7); the *appearance* of a Gaussian blur against Pillow's box filter is unmeasured, and `colorchannelmixer` **rounds** where moviepy truncates (off by up to 1 LSB). | One comparison render. |
| **Which body-schema URI, and what shape, for the `nw` side?** | §3.2 assigns ownership but does not draft the model. It should follow `nw/bodies/render-result/v1` — a small body, heavy data in the referenced Artifact — carrying `looks`' wire document opaquely with its schema tag. | An owner decision, and it is migration-required once anything persists it. |

---

## 12. Provenance of this document

Synthesised 2026-09-02 from thirteen research notes in [`docs/research/`](research/), each written by a separate agent and then adversarially reviewed by a second reader who re-ran every command. Five first-hand evidence notes (`00`, `00b`, `00c`, `00d`, `00e`) were produced by the orchestrating session independently, so the agents' briefs had something to be checked against; two of those notes carry their own corrections, appended when a research note measured further than they had.

Verdicts: eleven notes "sound-with-corrections", one "needs-rework" (note 03, the core types — whose recommendations survive in corrected form above, with its two fatal objections fixed in §5.3-5.4 and §4.5). **Where a review refuted the note's body, the correction is what this document records.** Three of the refutations ran in the *permissive* direction — an incomplete GPL gate recipe, a fail-open filter tier, and a field-of-use opt-in that waived the copyleft ceiling — which is the direction that makes this package a liability rather than merely useless, and is why every rule in §9 that has a test also has a mutation.

Facts re-verified against the running system while writing this document, rather than taken from the notes: the multi-output invariant hole (D-1), the `needs_gpl` fail-open (D-2), the geometry rounding divergence (D-3), `ffprobe`'s rejection of `-f null -`, `crop`'s inability to vary `w`/`h` over time, `zoompan`'s acceptance of `in_time` and rejection of `pon` with frame count preserved at `d=1`, `curves`' `natural`-by-default / `pchip`-is-monotone option table, and the shape of the committed `ffmpeg_gates.json` (33 direct + 5 indirect + 1 version3).

---

## REFERENCES

**Citation convention.** `[n]` is reference *n* below. **`[Rn]` is the *adversarial review* appended to research note *n*** — where a review refuted the note's body, the review is the citation and the body is not. `[owner/repo#N]` is a GitHub issue.

1. [`docs/research/01_prior_art_oss.md`](research/01_prior_art_oss.md) — external prior art: twelve live PyPI ffmpeg wrappers, zero with a named-effect registry or any licence awareness; FFmpeg's own `configure` as the real prior art; OpenFX's call-time entitlement refusal as the closest mechanism, with the opposite default.
2. [`docs/research/02_prior_art_fleet.md`](research/02_prior_art_fleet.md) — the fleet: 116 files call ffmpeg, five primitives reimplemented 2-5x each; `muvid.visualize` as the shape; `an.bench.metrics` as the measurement tier; why `burns` and `mixing.video_util` must not simply move.
3. [`docs/research/03_spec_type.md`](research/03_spec_type.md) — the core types. Verdict **needs-rework**; corrected here.
4. [`docs/research/04_clip_aware_resolution.md`](research/04_clip_aware_resolution.md) — measuring a clip and normalising the output; the exact min-spread sweep; the k=5 probe budget; the `SourceMap`.
5. [`docs/research/05_compilation_and_backends.md`](research/05_compilation_and_backends.md) — filtergraph construction, the colour contract, the fold, the backend Protocol.
6. [`docs/research/06_licence_tiers.md`](research/06_licence_tiers.md) — the four axes, the ladder as a policy projection, the decision procedure, the evidence ledger.
7. [`docs/research/07_ffmpeg_licence_surface.md`](research/07_ffmpeg_licence_surface.md) — FFmpeg's internal split, the two ceilings, the probe rules, the encoder wall.
8. [`docs/research/08_opencv_and_python_deps.md`](research/08_opencv_and_python_deps.md) — the optional-extras licence surface; the platform-dependent OpenCV wheel.
9. [`docs/research/09_neural_restyling.md`](research/09_neural_restyling.md) — commercially-usable neural restyling in 2026; the flicker measurement; the four licence fields FFmpeg's vocabulary cannot express.
10. [`docs/research/10_shader_backend.md`](research/10_shader_backend.md) — the GPU question; libplacebo 141x slower than CPU on the fleet server; the shader that was a byte-identical no-op reporting a 48x speedup.
11. [`docs/research/11_fleet_integration.md`](research/11_fleet_integration.md) — the seam, the consumer order, Rule G, Rule N, the local-render Transform.
12. [`docs/research/12_mixing_refactor.md`](research/12_mixing_refactor.md) — the geometry tier and the transitions, moved without moviepy; the measured crossfade no-op.
13. [`docs/research/13_effect_catalogue.md`](research/13_effect_catalogue.md) — the v1 catalogue, with a verified compile target for 22 of its entries.
14. [`docs/research/00_ffmpeg_licence_gates_evidence.md`](research/00_ffmpeg_licence_gates_evidence.md) — the gate extraction from `configure` at `n8.1`, and its correction to 38.
15. [`docs/research/00b_colour_range_trap_evidence.md`](research/00b_colour_range_trap_evidence.md) — the colour trap is range (and matrix), not pixel format; `lavfi` is bit-reproducible.
16. [`docs/research/00c_the_insertion_point_evidence.md`](research/00c_the_insertion_point_evidence.md) — where a Look attaches, read off muvid's bounded-memory invariant.
17. [`docs/research/00d_forbidden_deps_evidence.md`](research/00d_forbidden_deps_evidence.md) — `av`, `imageio-ffmpeg` and `opencv-contrib-python` verified on disk.
18. [`docs/research/00e_the_flatten_tension.md`](research/00e_the_flatten_tension.md) — why the flagship look's flattener has a platform-dependent tier.
19. [`KICKOFF.md`](../KICKOFF.md) — the measured facts from building Que Calor V2, and the non-negotiables.
20. [FFmpeg `configure`, tag `n8.1`](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1/configure) — the gate extraction source.
21. [FFmpeg License and Legal Considerations](https://ffmpeg.org/legal.html) — the project's own statement that `--enable-gpl` makes the resulting binary GPL.
22. [FFmpeg Filters Documentation](https://ffmpeg.org/ffmpeg-filters.html) — accessed 2026-09-02.
23. [thorwhalen/muvid#63](https://github.com/thorwhalen/muvid/issues/63) — the proposal issue, and the comment recording the per-clip parameter finding.
24. [thorwhalen/muvid#66](https://github.com/thorwhalen/muvid/issues/66) — the design-partner request for in-shot punch-ins, filed 2026-09-02.
25. [Reelee x ComfyUI: Standing Decisions and Rationale](https://github.com/thorwhalen/reelee) — the federation's decisions-of-record note, and the model for this one; source of the layering rule and the cost-honesty rules.
