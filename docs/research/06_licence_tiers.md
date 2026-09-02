# The licence-tier taxonomy and its decision procedure

**Date: 2026-09-02** · research note for `looks` · status: proposal, not yet code

## Verdict

A single ordered ceiling is the right *API* and the wrong *model*. The facts are four independent axes — **coupling** (in-process / subprocess / service), **copyleft reach** (none / file / library / program / network), **conveyance** (does our declared dependency closure ship the implementation, or find one already on the machine), and **field of use** (unrestricted / no-derivatives / non-commercial / research-only) — and the last of those is not commensurable with the others: a non-commercial model is not "more copyleft than GPL", it is a different kind of failure, and a ladder that admits it when you raise the ceiling one notch is a trap. So `looks` keeps `max_tier` as one simple knob, defines the ladder as a **documented, replaceable policy projection** of the axes, and puts two things **off the ladder entirely** where no ceiling can reach them: in-process strong copyleft (always forbidden), and field-of-use restrictions (a separate opt-in that `max_tier` cannot grant). The tier is resolved from the environment rather than declared as a constant, because it genuinely varies — measured today, **32 of FFmpeg 8.1's video filters exist only in a GPL build, and `eq`, the ordinary brightness/contrast/saturation filter, is one of them**, so the same normalisation effect is tier `WEAK_COPYLEFT` written with `curves` and tier `COPYLEFT_TOOL` written with `eq`. And the honesty rule has teeth rather than prose: three of the packages in this very environment report licences that contradict their own contents, including — the finding that should change the plan — **`opencv-contrib-python` 4.13.0.92, whose wheel bundles a GPL-3.0-or-later ffmpeg with `libx264` and `libx265`, under `License: Apache 2.0` metadata and an MIT `LICENSE.txt`**. That is the wheel behind `cv2.pyrMeanShiftFiltering`, which is stage one of the first look `looks` will ship.

---

## 1. What the environment actually says, measured today

Everything in this section was run on this machine on 2026-09-02. It is here first because it is what forces the design; the taxonomy in §2 is derived from it, not the other way round.

### 1.1 The GPL/LGPL split is a *filter-availability* split, and it hits an everyday filter

Two builds, enumerated and diffed:

| Build | libavfilter | Self-reported licence | Video filters |
|---|---|---|---|
| Homebrew `ffmpeg` 8.1_1 on `PATH` | 11.14.100 | `GPL version 3 or later` (`ffmpeg -L`) | 481 |
| The LGPL build inside the `av` 16.0.1 wheel | 11.4.100 | `LGPL version 3 or later` (`avfilter_license()`) | 447 |

The diff is 34 filters. Two are explained by version/build drift rather than licence (`libvmaf` needs `--enable-libvmaf`; `premultiply_dynamic` is new in 8.1 and absent from `av`'s 8.0-era libavfilter). The remaining **32 are exactly the filters FFmpeg's own `configure` guards behind `gpl`** — cross-checked against `release/8.1`'s `*_filter_deps="…gpl…"` declarations, which name 33 (the 33rd, `boxblur_opencl`, needs OpenCL and is in neither build) [1]:

`blackframe boxblur colormatrix cover_rect cropdetect delogo eq find_rect fspp histeq hqdn3d interlace kerndeint mcdeint mpdecimate mptestsrc nnedi owdenoise perspective phase pp7 pullup repeatfields sab signature smartblur spp stereo3d super2xsai tinterlace uspp vaguedenoiser`

`eq` is the one that matters. It is *the* brightness/contrast/saturation/gamma filter, the natural implementation of the continuity-grade half of what `looks` does, and it is GPL-only. `boxblur`, `hqdn3d`, `smartblur`, `vaguedenoiser`, `cropdetect` and `perspective` are all in the same position. Meanwhile the Que Calor V2 chain's actual filters — `lut3d`, `lutrgb`, plus `curves`, `colorchannelmixer`, `scale`, `format` — are all present in the LGPL build (verified individually).

**This is the whole argument for a resolved rather than declared tier, and it is not hypothetical.** An effect named `grade` is tier `WEAK_COPYLEFT` if it compiles to `curves`/`colorlevels` and tier `COPYLEFT_TOOL` if it compiles to `eq`, and a second effect can be tier `WEAK_COPYLEFT` on one machine and `COPYLEFT_TOOL` on the next because that is what is installed. It also hands `looks` a genuinely useful job beyond refusing: **when an effect is over the ceiling because of one filter, `looks` can often name the LGPL-clean alternative chain.**

### 1.2 FFmpeg already implements the mechanism `looks` needs, one layer down

`configure` in `release/8.1` carries an ordered licence lattice, per-component licence declarations, and a build-time refusal [1]:

```
map "die_license_disabled gpl"      $EXTERNAL_LIBRARY_GPL_LIST $EXTERNAL_LIBRARY_GPLV3_LIST
map "die_license_disabled version3" $EXTERNAL_LIBRARY_VERSION3_LIST $EXTERNAL_LIBRARY_GPLV3_LIST

die_license_disabled() {
    enabled $1 || { enabled $v && die "$v is $1 and --enable-$1 is not specified."; }
}

if enabled nonfree;  then license="nonfree and unredistributable"
elif enabled gplv3;  then license="GPL version 3 or later"
elif enabled lgplv3; then license="LGPL version 3 or later"
elif enabled gpl;    then license="GPL version 2 or later"
else                      license="LGPL version 2.1 or later"
fi
```

with `EXTERNAL_LIBRARY_GPL_LIST = avisynth frei0r libcdio libdavs2 libdvdnav libdvdread librubberband libvidstab libx264 libx265 libxavs libxavs2 libxvid`, `EXTERNAL_LIBRARY_NONFREE_LIST = decklink libfdk_aac libmpeghdec`, and `EXTERNAL_LIBRARY_VERSION3_LIST = gmp libaribb24 liblensfun libopencore_amrnb libopencore_amrwb libvo_amrwbenc mbedtls rkmpp`.

This is the best precedent available and it is right next door. `looks` should **reimplement that exact resolution rule** rather than invent one — it is authoritative for the artifact being probed, it is five lines, and it makes the probe verifiable against the thing it probes.

It also gives `looks` a free contradiction detector, which §1.3 turns out to need.

### 1.3 Three packages in this environment report a licence their own contents contradict

**`av` 16.0.1 (PyPI wheel, macOS arm64) — four layers, four answers.**

| Layer | What it says | How observed |
|---|---|---|
| PyPI distribution metadata | `License-Expression: BSD-3-Clause` | `importlib.metadata` |
| Bundled `avcodec_license()` | `LGPL version 3 or later` | `ctypes.CDLL(...).avcodec_license()` |
| Bundled `avcodec_configuration()` | `--enable-version3 … --enable-libx264 --enable-libx265`, **no `--enable-gpl`** | same |
| Actual linkage | `@loader_path/libx264.165.dylib`, `@loader_path/libx265.215.dylib` | `otool -L` |
| Actual capability | `libx264` and `libx265` encoders constructible via `av.codec.Codec(name, "w")` | PyAV API |

The dylibs are real (1.69 MB and 6.40 MB) and the encoders work. But **FFmpeg's unpatched `configure` cannot produce that configuration** — `libx264` and `libx265` are in `EXTERNAL_LIBRARY_GPL_LIST`, so `die_license_disabled gpl` aborts the build with `libx264 is gpl and --enable-gpl is not specified` [1]. Something in the build path bypassed that gate, and the licence string the binary reports is computed from a `gpl` flag that was never set. I am **not** adjudicating what that means legally, and `looks` must not either — x264 and x265 are dual-licensed (GPL-2.0-or-later or commercial), so a lawful non-GPL build is conceivable and I have no evidence either way. What I *can* state as verified fact is the four-layer disagreement above, and the operational conclusion follows without any legal reading: **an artifact whose licence self-report contradicts its own linkage cannot be classified, and unknown is a refusal.** This upgrades the kickoff's ban on `av` from a second-hand claim to a first-hand, mechanically-detectable one.

**`imageio-ffmpeg` 0.6.0 — confirmed, no ambiguity.** Metadata says `BSD-2-Clause`. The wheel ships `binaries/ffmpeg-macos-aarch64-v7.1`, 49.4 MB, configured `--enable-gpl --enable-libx264 --enable-libx265 --enable-libvidstab --enable-postproc …`, and `ffmpeg -L` on it prints the GNU General Public License version 2 or later. The metadata field describes the Python wrapper; the payload is a GPL program.

**`opencv-contrib-python` 4.13.0.92 — the finding that changes the plan.** Metadata says `License: Apache 2.0`. The `LICENSE.txt` *inside* the package is **MIT, "Copyright (c) Olli-Pekka Heinisuo"** — the wheel-builder's licence for the packaging scripts, not OpenCV's own Apache-2.0 and not the payload's. And `cv2/.dylibs/` contains 93 shared libraries including:

- `libx264.164.dylib`, `libx265.215.dylib` — GPL-2.0-or-later, both in FFmpeg's `EXTERNAL_LIBRARY_GPL_LIST`
- `libvidstab.1.2.dylib`, `librubberband.3.dylib` — also in that list
- a complete FFmpeg 7.1.1 (`libavcodec.61.19.101`, `libavformat`, `libavfilter`, `libpostproc`)

and the decisive test, the one that leaves nothing to interpret:

```
avutil_license()      -> GPL version 3 or later
--enable-gpl      : True
--enable-version3 : True
configuration: --prefix=/opt/homebrew/Cellar/ffmpeg/7.1.1_3 … --enable-gpl … --enable-libx264 --enable-libx265 …
```

**`pip install opencv-contrib-python` redistributes a GPL-3.0-or-later ffmpeg.** So does `pip install opencv-python` — 4.12.0.88's `RECORD` lists `libx264.164.dylib`, `libx265.215.dylib`, `libavcodec`, `libavformat`, `libbluray`, `libaribb24`. There is no plain-vs-contrib escape.

This lands squarely on `looks`: `cv2.pyrMeanShiftFiltering` is the flattening stage of the Que Calor look, the first real customer. The kickoff's framing had `av` and `imageio-ffmpeg` as the forbidden ones and OpenCV as the safe in-process path. **That framing is wrong at the wheel level**, and the tier system is what should have said so.

**And there is a sharper question underneath, which §7 surfaced by being executed and which is for the owner rather than for `looks`.** `cv2`'s extension module dynamically links that GPL libavcodec *into the Python process*. Read one way — the linkage is ours — that is in-process strong copyleft, which §2.4 forbids at every ceiling, and OpenCV would be unusable from `looks` at all. Read the other way — the linkage is OpenCV's, and what `looks` couples to is OpenCV's Apache-2.0 code — it is `COPYLEFT_SHIPPED`, above the default ceiling but reachable by an explicit opt-in. **`looks` must not decide which reading is right**; that is precisely the adjudication §6 forbids it. What `looks` should do is record both components, report the conflict, and refuse until a human rules. The cheap way out of the question entirely is an OpenCV build with no ffmpeg in it, or doing the flatten in numpy. `opencv-python-headless` is the obvious candidate and is **unverified** — it is not installed here, and checking it is the first thing to do before declaring an `opencv` extra.

Two smaller notes from the same sweep, both first-hand: **`ultralytics` 8.4.75 ships the actual GNU Affero General Public License v3 text** at `ultralytics-8.4.75.dist-info/licenses/LICENSE` (not merely an `AGPL-3.0` metadata string), confirming the federation's standing ban. And `burns` 0.0.9 declares `dependencies = ["numpy", "moviepy", "pillow"]`; `moviepy` 2.2.1 hard-requires `imageio_ffmpeg>=0.2.0`; so `pip install burns` conveys a GPL ffmpeg binary in three verified hops. `burns`' own `pyproject.toml` writes `[project.license] text = "mit"` — lowercase, not an SPDX identifier, a fourth small instance of the same class of defect.

**The pattern across all of these: the licence *field* is not evidence, and — the refinement this environment adds to the existing federation rules — for a wheel that bundles a third-party library, neither is the top-level `LICENSE` file, because it belongs to the packaging layer rather than the payload.** `an`'s Rule 1 ("the chip is not evidence, in either direction") [2] and reelee-web's rule that the licence *text* is the authority [3] both stop one layer short of this. For a binary-bearing wheel the authority is the bundled binary, interrogated.

---

## 2. The tier ladder

### 2.1 Why not a single order — and why a single knob anyway

The kickoff assumes a linear ceiling. Taken literally that is inadequate, for one decisive reason: **field-of-use restrictions are not a rung.** If `NON_COMMERCIAL` sits above `COPYLEFT_SHIPPED` on one ladder, then a caller who raises the ceiling to accept a shipped GPL binary — a perfectly ordinary decision for an internal tool — silently also accepts AnimeGANv2 weights. Those are opposite decisions for this federation, which ships a commercialisable product and is entirely relaxed about executing GPL binaries. A ladder that couples them is worse than no ladder, because it converts an explicit decision into a side effect.

The same argument, more sharply, applies to in-process strong copyleft. The kickoff says it "must always refuse". **A rung you can opt into is not "always refuse."** So it cannot be a rung.

The resolution keeps the simple API and fixes the model:

- The **facts** are four axes, always recorded, always inspectable.
- The **ladder** is a *projection* of three of those axes onto five named, ordered tiers. It is a policy artifact this project chose, not a fact about licences, and `Policy.order` makes it replaceable by a caller with a different corporate posture.
- The **fourth axis** (field of use) and the **forbidden region** (in-process strong copyleft) are off the ladder. `max_tier` cannot reach either.

So the common case is one knob — `Look(..., max_tier=Tier.WEAK_COPYLEFT)` — and the full expression is there when needed. That is the progressive-disclosure rule applied to a policy object rather than to a function signature.

### 2.2 The axes

| Axis | Values (ordered where ordering is meaningful) | What it decides |
|---|---|---|
| `Coupling` | `NONE` · `IN_PROCESS` · `SUBPROCESS` · `SERVICE` · `UNKNOWN` | Whether copyleft can reach the caller's own code at all |
| `Reach` | `NONE` · `FILE` · `LIBRARY` · `PROGRAM` · `NETWORK` · `UNKNOWN` | How far the implementation's copyleft extends (permissive / MPL / LGPL / GPL / AGPL) |
| `Conveyance` | `NONE` · `FINDS` · `CONVEYS` · `UNKNOWN` | Whether `looks`' declared closure ships the implementation, or resolves one already present |
| `FieldOfUse` | `UNRESTRICTED` · `NO_DERIVATIVES` · `NON_COMMERCIAL` · `RESEARCH_ONLY` · `UNKNOWN` | Whether the *purpose* is permitted — orthogonal to all of the above |

`Coupling` and `Conveyance` are the two the existing federation rules keep implicitly and never name. They are exactly what separates the four cases the kickoff lists: executing a GPL binary you found (`SUBPROCESS` + `PROGRAM` + `FINDS`), executing one you shipped (`… + CONVEYS`), linking one (`IN_PROCESS` + `PROGRAM`), and calling a hosted one (`SERVICE`).

### 2.3 The ladder

| Rung | Tier | Axis region | Obligation shape | Worked example from §1 |
|---|---|---|---|---|
| 0 | `PURE` | `Coupling.NONE` | none | a `Look` that is only metadata; geometry arithmetic |
| 1 | `PERMISSIVE` | `IN_PROCESS` + `Reach.NONE` | notice retention on conveyance | OpenCV's own Apache-2.0 C++ (`pyrMeanShiftFiltering`) — *as code* |
| 2 | `WEAK_COPYLEFT` | `IN_PROCESS` + `Reach.FILE`/`LIBRARY` | notice + relink/source-of-the-library, dynamic linkage only | an honest LGPL ffmpeg build; MPL components |
| 3 | `COPYLEFT_TOOL` | `SUBPROCESS`/`SERVICE` + `Reach.PROGRAM`/`NETWORK` + `FINDS` | none on your code; a **prohibition on a future act** (conveying it) | Homebrew `ffmpeg` 8.1 on `PATH`; any effect needing `eq` |
| 4 | `COPYLEFT_SHIPPED` | same, but `CONVEYS` | full source-offer duty, inherited by every downstream redistributor | `imageio-ffmpeg`; `burns` transitively; **`opencv-*-python`** |

**Default ceiling: `COPYLEFT_TOOL`** — the kickoff's "shells out to a copyleft binary is fine", stated precisely.

Two things to be honest about in this table, because a ladder presented as a fact is the failure mode this whole note is about:

- **Rungs 2 and 3 are not ordered by obligation-inclusion.** In-process LGPL and subprocess GPL impose *different* duties, not more and fewer. Plenty of corporate policies rank them the other way (comfortable with LGPL dynamic linking, nervous about GPL anything). The ordering here is chosen for what *this* federation ships — Python source packages that shell out and bundle nothing — where "does copyleft touch our source" is the question that matters and rung 3's answer is "no, unless you later ship the tool". A caller with a different posture supplies `Policy(order=…)`. Rungs 3→4 *are* ordered by inclusion, unambiguously.
- **Rung 1 is about the code an effect calls, not about the wheel it arrives in — and a provider made of several components takes the *worst* verdict among them, never a blend of their axes.** OpenCV's mean-shift is genuinely Apache-2.0 in-process code; the GPL ffmpeg in the same wheel is a separate component. Each gets its own row. **Running the code in §7 is what established that this must not be a per-axis join**: joining the two rows produces `IN_PROCESS` + `Reach.PROGRAM` — "we link a GPL program in-process" — a chimera true of neither component, which `classify()` then correctly but uselessly reports as `FORBIDDEN`. `assess()` takes the worst *component* verdict instead, and every row survives into the record, so a caller can see which half is the problem. That distinction is the whole reason the axes exist rather than a scalar.

### 2.4 Off the ladder

| Verdict | Region | Why no rung |
|---|---|---|
| `FORBIDDEN` | `IN_PROCESS` + `Reach.PROGRAM`/`NETWORK` | The kickoff says always refuse; a rung is opt-in-able, so this cannot be one |
| `FIELD_RESTRICTED` | any `FieldOfUse` other than `UNRESTRICTED` | Not commensurable with copyleft (§2.1); needs its own explicit, separate opt-in |
| `UNKNOWN` | any axis `UNKNOWN`, **or an internally contradictory probe** | Unknown is a refusal; §1.3's `av` case is precisely the contradiction branch |

The contradiction branch is what makes the honesty rule executable instead of aspirational. `looks` does not need to decide what `av`'s licence *is*; it needs only to notice that the artifact's own statements disagree, and refuse.

---

## 3. The decision procedure

**Four gates, and the fourth is deliberately empty.**

| When | Checks | Against | Can it be skipped? |
|---|---|---|---|
| **Registration** (`@register_effect`) | the *declaration* is well-formed: a known `Tier`, a `provider_id` present in the ledger, an SPDX id in the vocabulary | nothing environmental | no — it is an import-time `ValueError` and catches the effect author, not the user |
| **`Look` construction** | every effect's **declared** tier | `Look.max_tier` | no |
| **`compile()`** | every effect's **resolved** tier, after probing | the same ceiling | no |
| **run** | — | — | `looks` does not run anything |

That the fourth row is empty is the architecture paying a licence dividend. Because `looks` never encodes — the kickoff keeps execution and muxing out for memory-invariant reasons — **`looks` never chooses `libx264` and therefore never has to answer for it.** The Que Calor chain is the demonstration: its filters (`lut3d`, `lutrgb`) are LGPL-available, its flattener is Apache-2.0 code, and the only GPL-only component in the whole pipeline is the `-c:v libx264` on the encode, which belongs to `muvid.assemble`. A boundary drawn for architectural reasons turns out to be the boundary that keeps the licence claim truthful. Worth stating in the README as a reason, not an accident.

### 3.1 The declared/resolved rule — how to refuse early without refusing wrongly

The rule that makes gate 2 sound:

> **An effect's declared tier is the minimum over every provider it could resolve to.**

Consequently gate 2 can only produce refusals gate 3 would also produce (no false refusals from checking early), and gate 3 catches everything else. Concretely: a `posterise` effect that can compile to either an LGPL or a GPL ffmpeg declares `WEAK_COPYLEFT`; a caller with `max_tier=WEAK_COPYLEFT` gets past gate 2, and gate 3 refuses only if the machine actually resolved to the GPL build — with a message saying an LGPL provider would satisfy them and how to get one. A caller with `max_tier=PERMISSIVE` is refused at gate 2, offline, in microseconds, before anything is measured or rendered.

This is the "earliest possible" requirement discharged without lying, and it is testable: `min over providers == declared` is a property every registered effect must satisfy, asserted in the suite.

### 3.2 The exceptions

Four types, because the **remedies are different** — the same reasoning that made reelee-web separate "copyleft" from "unknown" [3]:

| Exception | Meaning | Remedy the message must state |
|---|---|---|
| `LicenceCeilingExceeded` | on the ladder, above the ceiling | raise `max_tier`, **or** install/select a lower-tier provider (named, if one exists) |
| `LicenceForbidden` | in the forbidden region | none — use a different effect; there is no opt-in |
| `LicenceFieldRestricted` | non-commercial / research-only / no-derivatives | the separate `Policy(allow_field_restricted=…)` opt-in, never `max_tier` |
| `LicenceUnknown` | undeterminable, unprobeable, or self-contradictory | supply evidence, or use a provider that can be probed |

A refusal message names, in this order: **the effect**, **the tier it needs**, **the ceiling in force**, **why it needs that tier** (the resolved provider and the observation that decided it, with date and source), and **how to opt in**. Sketch of the real thing:

```
LicenceCeilingExceeded: effect 'grade' needs tier COPYLEFT_TOOL; the ceiling in force is WEAK_COPYLEFT.

  Why: it compiles to the ffmpeg filter 'eq', which exists only in a GPL build.
       Resolved provider: ffmpeg @ /opt/homebrew/bin/ffmpeg
       Observed 2026-09-02 by `ffmpeg -version`: configuration contains --enable-gpl
       and --enable-version3, so FFmpeg's own rule gives GPL-3.0-or-later.
       See https://ffmpeg.org/legal.html

  A provider under your ceiling would satisfy this effect:
       'grade' also compiles to 'curves', available in an LGPL build.
       Pass provider='ffmpeg-lgpl', or Look(..., prefer_lowest_tier=True).

  Or opt in deliberately:
       Look(..., max_tier=Tier.COPYLEFT_TOOL)

  looks reports observations, not legal conclusions — see looks.licensing.DISCLAIMER.
```

### 3.3 Where the tier comes from

**Both, joined — and the join is per-axis, not a max of two scalars.**

```
resolved_terms = declared_terms  ⊔  probe(provider)
resolved_tier  = tier_of(resolved_terms)          # the ladder projection
```

The effect author declares what the *effect* does (`Coupling`, the filters it needs, the SPDX of any code it calls in-process). The **probe** supplies what the *environment* is. Neither alone is sufficient, and the join is a least-upper-bound in the axis lattice rather than `max(a, b)` on a number — which is what preserves the OpenCV distinction in §2.3.

**The ffmpeg probe** (the one that matters, and it is stdlib-only):

1. Run `ffmpeg -version`; take the `configuration:` line.
2. Apply **FFmpeg's own resolution rule verbatim** (§1.2): `nonfree` → unredistributable; `version3 + gpl` → `GPL-3.0-or-later`; `version3` → `LGPL-3.0-or-later`; `gpl` → `GPL-2.0-or-later`; else `LGPL-2.1-or-later`.
3. **Contradiction check.** If any `--enable-<x>` appears for `x` in `EXTERNAL_LIBRARY_GPL_LIST` but `--enable-gpl` does not, the artifact's self-report is inconsistent with its own components → `UNKNOWN` → refuse. *(This is the branch that catches `av` 16.0.1 mechanically.)*
4. Enumerate `ffmpeg -filters` once and cache it, so gate 3 can answer "is this effect's chain available here, and does it need a GPL-only filter".

**When the environment cannot be probed** — no binary on `PATH`, a probe that times out, a build that reports no `configuration:` line — the result is `Coupling.UNKNOWN`/`Reach.UNKNOWN`, the verdict is `LicenceUnknown`, and the refusal message says which probe failed and what would fix it. There is no "assume LGPL", no "assume the common case", and no warning-instead-of-refusal. The probe result is cached **with its evidence** (command, output excerpt, date), never as a bare verdict, so a cached answer can always be re-read for what it was actually based on.

---

## 4. Precedent — and the gap `looks` fills

| System | Anchor | What it encodes | Does it refuse? |
|---|---|---|---|
| **SPDX License List** | **3.28.0, released 2026-02-20** [4] | a canonical *identifier* vocabulary + expressions (`AND`/`OR`/`WITH`) + `LicenseRef-*` for bespoke terms [5] | no — a vocabulary, not a policy |
| **REUSE** | **3.3, 2024-11-14** [6] | file-level `SPDX-License-Identifier` / `SPDX-FileCopyrightText`, a `LICENSES/` dir, `REUSE.toml` | conformance only; nothing about *use* |
| **Debian machine-readable copyright (DEP-5)** | format 1.0 [7] | per-`Files:`-glob licence paragraphs — a licence claim scoped to a path, not to a package | no |
| **`pip-licenses`, `licensecheck`** | [8], [9] | reads the distribution **metadata field** | some gate on it — and §1.3 shows that field wrong three times in one environment |
| **frei0r** | `f0r_plugin_info_t` [10] | `name`, `author`, `plugin_type`, `color_model`, `frei0r_version`, `major_version`, `minor_version`, `num_params`, `explanation` — **no licence field** (frei0r itself is GPL-2.0 [11]) | no |
| **OpenFX** | `ofxCore.h`, `SPDX-License-Identifier: BSD-3-Clause` [12] | version, description, labels, grouping — **no licence or copyright property** | no |
| **FFmpeg `configure`** | release/8.1 [1] | an ordered licence lattice + per-component licence deps | **yes — `die()` at build time.** The closest precedent by far |
| **`falaw`#16 (planned)** | internal | a `(model, backend)`-keyed terms ledger; `unknown` is a refusal at plan time [13] | yes, by design |

**The gap is real and this table is the evidence for the kickoff's claim.** The two mature video-plugin APIs — the ones every NLE and compositor speaks — carry *no licence field at all* in their plugin manifests. FFmpeg has the mechanism but stops at its own build boundary: it refuses to *build* a mislicensed binary and then tells you nothing about *using* one. The Python tooling reads the field this environment just falsified three times. Nobody sits where `looks` proposes to sit: at the point where a named effect is bound to a resolved implementation, before anything runs.

**Should `looks` use SPDX as the underlying vocabulary? Yes — as the vocabulary, and only as the vocabulary.** SPDX identifiers are the right keys: unambiguous, versioned, universally understood, and they already have `LicenseRef-*` for terms with no listed identifier, which is exactly what AnimeGANv2's bespoke non-commercial grant needs. But SPDX encodes **none** of the four axes: it cannot say whether you linked or executed, whether you shipped or found, or — a real gap, not a quibble — whether the field of use is restricted, since bespoke non-commercial terms have no listed id by construction. So the mapping is one small, testable table, `SPDX id → Reach`, and everything else is `looks`' own:

| SPDX identifier(s) | `Reach` |
|---|---|
| `MIT`, `MIT-0`, `BSD-2-Clause`, `BSD-3-Clause`, `0BSD`, `ISC`, `Apache-2.0`, `CC0-1.0`, `Unlicense`, `BlueOak-1.0.0`, `Python-2.0` | `NONE` |
| `MPL-2.0`, `EPL-2.0`, `CDDL-1.0` | `FILE` |
| `LGPL-2.1-only`, `LGPL-2.1-or-later`, `LGPL-3.0-only`, `LGPL-3.0-or-later` | `LIBRARY` |
| `GPL-2.0-only`, `GPL-2.0-or-later`, `GPL-3.0-only`, `GPL-3.0-or-later`, `SSPL-1.0` | `PROGRAM` |
| `AGPL-3.0-only`, `AGPL-3.0-or-later` | `NETWORK` |
| anything not listed, incl. every `LicenseRef-*` | `UNKNOWN` |

Two rules on that table, both learned from reelee-web's version of it [3]: **`BSD-4-Clause` is deliberately absent** — its advertising clause is a real obligation and its text is word-for-word BSD-3-Clause plus one paragraph, so it must be *listed as excluded* rather than left to fall through; and an id that is not in the table is `UNKNOWN`, which is a refusal, in both directions. Widening this table is a recorded decision with a date and a reason, never a convenience.

`FieldOfUse` is a **separate declared column**, because no SPDX id carries it. `CC-BY-NC-SA-4.0` happens to be a listed id whose non-commercial character is not derivable from the id string; AnimeGANv2's terms have no id at all. Both must produce `NON_COMMERCIAL` and both do so from the ledger, not from parsing.

---

## 5. The seeded table — shape and home

**Home:** `looks/data/provider_terms.json`, loaded by `looks/licensing.py`, pinned by `looks/tests/test_provider_terms.py`.

A separate data file rather than literals in code, for the reason `falaw`#16 gives for the same choice [13]: it is refreshed on its own cadence and reviewed as a legal artifact, not as code. Keyed on **`(provider_id, realisation)`** — the direct analogue of falaw's `(model, backend)`, and load-bearing for the same reason: `realisation` is *how you obtain it* (`system` = found on `PATH`; `pypi:<dist>` = conveyed by that distribution), and it is what makes `CONVEYS` expressible at all. One row per way of getting a thing, not one row per thing.

Every row carries **evidence, not a conclusion**: the method, the exact command, what was observed, a source URL, and the date. A row is a record of an observation; the tier is *derived* from it by `classify()`, so a reader can always check the derivation rather than trusting the label. This is the REUSE/DEP-5 shape (provenance attached to the claim) applied to providers instead of files.

```json
{
  "schema": "looks/provider-terms/v1",
  "spdx_license_list_version": "3.28.0",
  "disclaimer": "looks reports observations, not legal conclusions. See looks.licensing.DISCLAIMER.",
  "rows": [
    {
      "provider_id": "ffmpeg", "realisation": "system",
      "spdx": "GPL-3.0-or-later",
      "coupling": "subprocess", "reach": "program",
      "conveyance": "finds", "field_of_use": "unrestricted",
      "tier": "copyleft_tool",
      "evidence": [{
        "method": "probe", "command": "ffmpeg -version",
        "observed": "configuration: --enable-gpl --enable-version3 ... (Homebrew 8.1_1)",
        "source_url": "https://ffmpeg.org/legal.html", "observed_on": "2026-09-02"}],
      "note": "Tier is PROBED, never assumed: an LGPL build of the same binary is tier weak_copyleft. 32 video filters (incl. 'eq') exist only in the GPL build."
    },
    {
      "provider_id": "ffmpeg", "realisation": "pypi:imageio-ffmpeg",
      "spdx": "GPL-2.0-or-later",
      "coupling": "subprocess", "reach": "program",
      "conveyance": "conveys", "field_of_use": "unrestricted",
      "tier": "copyleft_shipped",
      "evidence": [{
        "method": "inspect+probe",
        "command": "imageio_ffmpeg.get_ffmpeg_exe(); $exe -L",
        "observed": "imageio-ffmpeg 0.6.0 ships binaries/ffmpeg-macos-aarch64-v7.1 (49.4 MB), --enable-gpl; -L prints GPL v2 or later. Distribution metadata says BSD-2-Clause.",
        "source_url": "https://pypi.org/project/imageio-ffmpeg/", "observed_on": "2026-09-02"}],
      "note": "FORBIDDEN AS A LOOKS DEPENDENCY (kickoff non-negotiable). Row exists to explain the refusal and to classify a caller's pre-existing install."
    },
    {
      "provider_id": "ffmpeg", "realisation": "pypi:av",
      "spdx": "LicenseRef-CONTRADICTORY",
      "coupling": "in_process", "reach": "unknown",
      "conveyance": "conveys", "field_of_use": "unknown",
      "tier": null, "verdict": "unknown",
      "evidence": [{
        "method": "inspect+ctypes+otool",
        "command": "avcodec_license(); avcodec_configuration(); otool -L libavcodec*.dylib",
        "observed": "av 16.0.1: metadata License-Expression=BSD-3-Clause; avcodec_license()='LGPL version 3 or later'; configuration has --enable-libx264 --enable-libx265 but NO --enable-gpl; libavcodec links @loader_path/libx264.165.dylib and libx265.215.dylib; both encoders constructible. FFmpeg configure cannot produce this combination (die_license_disabled gpl).",
        "source_url": "https://raw.githubusercontent.com/FFmpeg/FFmpeg/release/8.1/configure", "observed_on": "2026-09-02"}],
      "note": "REFUSED as UNKNOWN, not as GPL. looks does not adjudicate; it observes that the artifact contradicts itself. Also FORBIDDEN as a looks dependency: in-process coupling."
    },
    {
      "provider_id": "opencv", "realisation": "pypi:opencv-contrib-python",
      "spdx": "Apache-2.0 AND GPL-3.0-or-later",
      "coupling": "in_process", "reach": "none",
      "conveyance": "conveys", "field_of_use": "unrestricted",
      "tier": "copyleft_shipped",
      "evidence": [{
        "method": "inspect+ctypes",
        "command": "ls cv2/.dylibs; ctypes avutil_license()",
        "observed": "opencv-contrib-python 4.13.0.92: metadata License='Apache 2.0'; in-wheel LICENSE.txt is MIT (packaging author); cv2/.dylibs bundles libx264.164, libx265.215, libvidstab, librubberband and ffmpeg 7.1.1_3 whose avutil_license() = 'GPL version 3 or later'. opencv-python 4.12.0.88 bundles x264/x265 too.",
        "source_url": "https://pypi.org/project/opencv-python/", "observed_on": "2026-09-02"}],
      "note": "TWO components, two rows, worst verdict wins (see assess()). Row A: pyrMeanShiftFiltering is Apache-2.0 in-process => permissive. Row B: the bundled ffmpeg is a GPL program the wheel conveys. How row B is COUPLED is the open question and it is consequential: cv2's extension module dynamically links libavcodec into the Python process, which read as in_process+program is FORBIDDEN at every ceiling, while read as 'OpenCV's own linkage, not ours' it is copyleft_shipped and merely above the default. looks must NOT adjudicate that. Escalate to the owner; the cheap way out is an ffmpeg-free OpenCV build. A looks 'opencv' extra is a conveyance decision either way, not a convenience. opencv-python-headless UNVERIFIED - check first."
    },
    {
      "provider_id": "animeganv2", "realisation": "weights:TachibanaYoshino/AnimeGANv2",
      "spdx": "LicenseRef-AnimeGANv2-NonCommercial",
      "coupling": "in_process", "reach": "unknown",
      "conveyance": "finds", "field_of_use": "non_commercial",
      "tier": null, "verdict": "field_restricted",
      "evidence": [{
        "method": "read",
        "observed": "README: 'made freely available to academic and non-academic entities for non-commercial purposes'; commercial use requires a written authorization letter. No SPDX id exists for these terms.",
        "source_url": "https://github.com/TachibanaYoshino/AnimeGANv2", "observed_on": "2026-09-02"}],
      "note": "NOT reachable by raising max_tier. Needs Policy(allow_field_restricted={FieldOfUse.NON_COMMERCIAL})."
    },
    {
      "provider_id": "whitebox-cartoonization", "realisation": "weights:SystemErrorWang/White-box-Cartoonization",
      "spdx": "CC-BY-NC-SA-4.0",
      "coupling": "in_process", "reach": "unknown",
      "conveyance": "finds", "field_of_use": "non_commercial",
      "tier": null, "verdict": "field_restricted",
      "evidence": [{
        "method": "read",
        "observed": "'Licensed under the CC BY-NC-SA 4.0 license'; 'Commercial application is prohibited'.",
        "source_url": "https://github.com/SystemErrorWang/White-box-Cartoonization", "observed_on": "2026-09-02"}],
      "note": "A LISTED SPDX id whose non-commercial character is not derivable from the id string - field_of_use must be a declared column, not parsed."
    },
    {
      "provider_id": "ultralytics", "realisation": "pypi:ultralytics",
      "spdx": "AGPL-3.0-or-later",
      "coupling": "in_process", "reach": "network",
      "conveyance": "conveys", "field_of_use": "unrestricted",
      "tier": null, "verdict": "forbidden",
      "evidence": [{
        "method": "read",
        "observed": "ultralytics 8.4.75 ships the full GNU AFFERO GENERAL PUBLIC LICENSE Version 3 text at ultralytics-8.4.75.dist-info/licenses/LICENSE (not merely the metadata string).",
        "source_url": "https://pypi.org/project/ultralytics/", "observed_on": "2026-09-02"}],
      "note": "FORBIDDEN: in_process + network reach. No ceiling admits it. Person detection uses torchvision keypoint R-CNN (BSD-3) or OpenCV's shipped detectors."
    },
    {
      "provider_id": "moviepy", "realisation": "pypi:burns",
      "spdx": "MIT AND GPL-2.0-or-later",
      "coupling": "in_process", "reach": "none",
      "conveyance": "conveys", "field_of_use": "unrestricted",
      "tier": "copyleft_shipped",
      "evidence": [{
        "method": "resolve",
        "command": "importlib.metadata requires",
        "observed": "burns 0.0.9 requires moviepy; moviepy 2.2.1 requires imageio_ffmpeg>=0.2.0; imageio-ffmpeg 0.6.0 ships a --enable-gpl ffmpeg. Three hops, all verified. burns' pyproject writes [project.license] text='mit' (not an SPDX id).",
        "source_url": "https://pypi.org/project/moviepy/", "observed_on": "2026-09-02"}],
      "note": "The recorded decision the kickoff asks for. Consequence for looks: moving mixing/video/video_util.py in unchanged imports moviepy at module top and would give a zero-dependency package a transitive GPL conveyance. The geometry tier must be ported off moviepy, or gated behind an extra whose tier is declared honestly."
    }
  ]
}
```

That last row is not decoration. **Refactor step 1 in the kickoff is a licence event, and the tier system is what says so before it happens.** `mixing/video/video_util.py` opens with `from moviepy import VideoFileClip, VideoClip, ImageClip, CompositeVideoClip` at module scope; moving it in unchanged would make a package whose first non-negotiable is "zero hard dependencies" convey a GPL binary on `pip install looks`. The geometry tier is arithmetic over `(width, height)` — porting it off moviepy is small work and now has a stated reason.

**Test shape**, following the pattern that has already survived contact in this federation [3][14]: every row's `tier`/`verdict` must equal `classify(row)` recomputed from its axes (the label is derived, never asserted); every `spdx` must be in the `SPDX id → Reach` table or explicitly `LicenseRef-*`; every row needs at least one `Evidence` with a non-empty `observed` and a parseable `observed_on`; every `FORBIDDEN`/`FIELD_RESTRICTED` row must be unreachable by any `max_tier`; and — the guard that matters most — **every distribution named in `looks`' own `[project.optional-dependencies]` must have a row, and its declared tier must not exceed a stated `EXTRA_TIER_CEILING`.** That makes the extras table a tested licence artifact rather than a convenience list, which is exactly the mistake the OpenCV finding would otherwise let `looks` walk into.

One deliberate non-rule: a row whose `observed_on` is older than `STALE_AFTER_DAYS` is **reported, never auto-refused**. Auto-refusing on staleness would make the package stop working offline for a reason that is not a licence fact, and a refusal nobody can act on trains people to disable refusals.

---

## 6. The honesty rule

Three commitments, each with a mechanism rather than a promise.

**One — `looks` never states a conclusion it cannot support.** A ledger row records what was *observed*; the tier is *derived* by `classify()` and re-derived by the test suite. Nothing in the data file is a bare verdict, so there is no place for a claim to sit unbacked. `av`'s row is the proof of concept: `looks` refuses it without ever asserting what its licence is.

**Two — undeterminable is a refusal, and it is a *distinct* refusal.** `LicenceUnknown` is not folded into `LicenceCeilingExceeded`, because the remedies differ and because folding them would let "we could not check" read as "we checked and it is fine" — the same reasoning behind `priv upkeep` keeping `unavailable` as a separate list from `findings`. Three routes reach it: an absent probe, a failed probe, and a **self-contradictory** probe.

**Three — it is not legal advice, said in the places where a human forms a belief.** The exact text:

> **`looks` reports observations, not legal conclusions.**
>
> A tier is not a legal determination. It is a position on a policy ladder this project chose, derived from things that were mechanically observed on a stated date — a command that was run, a file that was read, a binary that was interrogated — and every row records that observation so you can check the derivation rather than trust the label.
>
> `looks` refuses when it cannot observe. It does not adjudicate: where an artifact's own statements about itself disagree, `looks` reports the disagreement and refuses, and does not decide which statement is true.
>
> Raising a ceiling is a decision about *your* obligations, not about this software's. Whether the licences and terms recorded here permit what you intend to do is a question for you and your counsel.

**Four places**, one per belief-forming surface: the module docstring of `looks/licensing.py`; the `disclaimer` field in the header of `provider_terms.json`; the output of `looks licence` (the CLI report); and the licensing section of the README. Refusal exceptions carry a **one-line pointer**, not the full text — `looks reports observations, not legal conclusions — see looks.licensing.DISCLAIMER` — because a paragraph on every raise becomes noise, and noise is how a disclaimer stops being read.

**Scope boundary, stated so two ledgers do not grow.** `looks` owns **engine** copyleft: which implementation runs a pixel operation, how it is coupled, and whether we ship it. `falaw`#16 owns **model and vendor terms**: which hosted model may be called and under whose terms [13]. The seam is `falaw.Plan`, which is already the federation's façade boundary. Where an effect resolves to a hosted service, `looks` should record `Coupling.SERVICE` and **defer** the field-of-use question to falaw's ledger rather than keeping a second copy — falaw#16 explicitly says the validated SPDX vocabulary must be defined once. Until that ledger lands, a `SERVICE`-coupled effect is `UNKNOWN`, therefore refused, which is the correct interim state.

---

## 7. `looks/licensing.py` — proposed implementation

Stdlib only. Dataclasses for data, `Protocol` for the seam, keyword-only past the third argument, no magic numbers, doctests on the public functions.

```python
"""Licence tiers: what an effect costs you in obligations, and when to refuse.

`looks` binds a named effect to a *resolved* implementation, and the licence
position of that pairing is not a constant: the same effect is
:attr:`Tier.WEAK_COPYLEFT` on an LGPL ffmpeg and :attr:`Tier.COPYLEFT_TOOL` on
a GPL one, because 32 of FFmpeg 8.1's video filters — ``eq`` among them —
exist only in a GPL build. So the tier is *probed*, joined with what the effect
author declared, and compared against a ceiling **before anything runs**.

Four axes carry the facts (:class:`Coupling`, :class:`Reach`,
:class:`Conveyance`, :class:`FieldOfUse`); :data:`DEFAULT_ORDER` projects three
of them onto an ordered ladder of five :class:`Tier` rungs, and
:class:`Policy` is that projection made replaceable. Two regions are
deliberately **off** the ladder, where no ceiling reaches them: in-process
strong copyleft is :attr:`Verdict.FORBIDDEN`, and a field-of-use restriction
needs its own opt-in — because a caller raising a ceiling to accept a shipped
GPL binary has not thereby agreed to non-commercial model weights.

``UNKNOWN`` is a refusal. So is a probe that contradicts itself: a binary whose
configuration claims LGPL while linking GPL-only components is not classified
as GPL, it is classified as unclassifiable.

**looks reports observations, not legal conclusions.** See :data:`DISCLAIMER`.

>>> reach_of("Apache-2.0"), reach_of("LGPL-3.0-or-later"), reach_of("GPL-2.0-only")
(<Reach.NONE: 'none'>, <Reach.LIBRARY: 'library'>, <Reach.PROGRAM: 'program'>)
>>> reach_of("BSD-4-Clause")           # excluded on purpose, not overlooked
<Reach.UNKNOWN: 'unknown'>
"""

from __future__ import annotations

import enum
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Mapping, Protocol, Sequence

__all__ = [
    "Coupling", "Reach", "Conveyance", "FieldOfUse", "Tier", "Verdict",
    "Evidence", "Terms", "Assessment", "Policy",
    "LooksLicenceError", "LicenceCeilingExceeded", "LicenceForbidden",
    "LicenceFieldRestricted", "LicenceUnknown",
    "reach_of", "classify", "assess", "check", "probe_ffmpeg",
    "DEFAULT_ORDER", "DFLT_MAX_TIER", "SPDX_LICENSE_LIST_VERSION", "DISCLAIMER",
]

#: The SPDX License List release :data:`REACH_BY_SPDX` is written against.
SPDX_LICENSE_LIST_VERSION = "3.28.0"  # released 2026-02-20

#: Days after which a ledger row's evidence is *reported* stale. Never an
#: automatic refusal: staleness is not a licence fact, and a refusal nobody can
#: act on teaches people to disable refusals.
STALE_AFTER_DAYS = 365

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

_SEE_DISCLAIMER = (
    "looks reports observations, not legal conclusions "
    "— see looks.licensing.DISCLAIMER."
)


# --------------------------------------------------------------------------
# The four axes. These are the facts; the ladder below is a projection of them.
# --------------------------------------------------------------------------

class Coupling(enum.Enum):
    """How an effect reaches its implementation."""

    NONE = "none"              # no external implementation at all
    IN_PROCESS = "in_process"  # imported / linked into our address space
    SUBPROCESS = "subprocess"  # executed as a separate program
    SERVICE = "service"        # called over a network
    UNKNOWN = "unknown"


class Reach(enum.Enum):
    """How far the implementation's copyleft extends."""

    NONE = "none"        # permissive
    FILE = "file"        # MPL-2.0 and friends
    LIBRARY = "library"  # LGPL
    PROGRAM = "program"  # GPL
    NETWORK = "network"  # AGPL
    UNKNOWN = "unknown"


class Conveyance(enum.Enum):
    """Whether *we* redistribute the implementation, or find one in place."""

    NONE = "none"
    FINDS = "finds"      # resolved from the caller's machine
    CONVEYS = "conveys"  # our declared dependency closure ships it
    UNKNOWN = "unknown"


class FieldOfUse(enum.Enum):
    """Whether the *purpose* is permitted. Orthogonal to every axis above."""

    UNRESTRICTED = "unrestricted"
    NO_DERIVATIVES = "no_derivatives"
    NON_COMMERCIAL = "non_commercial"
    RESEARCH_ONLY = "research_only"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------
# The ladder: a POLICY PROJECTION of three axes. Not a fact about licences.
# --------------------------------------------------------------------------

class Tier(enum.Enum):
    """A rung. Deliberately a plain ``Enum``: the ordering belongs to
    :class:`Policy`, so that ``<`` cannot silently mean the default ladder
    when a caller supplied a different one."""

    PURE = "pure"
    PERMISSIVE = "permissive"
    WEAK_COPYLEFT = "weak_copyleft"
    COPYLEFT_TOOL = "copyleft_tool"
    COPYLEFT_SHIPPED = "copyleft_shipped"


class Verdict(enum.Enum):
    """What :func:`check` concluded. ``ADMITTED`` plus four ways to refuse,
    kept apart because their remedies differ."""

    ADMITTED = "admitted"
    OVER_CEILING = "over_ceiling"
    FORBIDDEN = "forbidden"
    FIELD_RESTRICTED = "field_restricted"
    UNKNOWN = "unknown"


#: The shipped ladder, lowest first. Chosen for what this federation ships —
#: Python source that shells out and bundles nothing — where the question that
#: matters is "does copyleft touch our source". Rungs 2 and 3 are NOT ordered
#: by obligation-inclusion (in-process LGPL and subprocess GPL impose different
#: duties, not more and fewer); a caller with another posture passes their own.
DEFAULT_ORDER: tuple[Tier, ...] = (
    Tier.PURE,
    Tier.PERMISSIVE,
    Tier.WEAK_COPYLEFT,
    Tier.COPYLEFT_TOOL,
    Tier.COPYLEFT_SHIPPED,
)

#: "Shelling out to a copyleft binary is fine" — stated precisely.
DFLT_MAX_TIER = Tier.COPYLEFT_TOOL

#: SPDX identifier -> copyleft reach. SPDX is the vocabulary; the axes are ours.
#: ``BSD-4-Clause`` is absent DELIBERATELY: its advertising clause is a real
#: obligation and its text is BSD-3-Clause plus one paragraph, so it must be
#: excluded explicitly rather than by oversight. Anything unlisted is UNKNOWN,
#: which refuses — in both directions.
REACH_BY_SPDX: Mapping[str, Reach] = {
    **{k: Reach.NONE for k in (
        "MIT", "MIT-0", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "ISC",
        "Apache-2.0", "CC0-1.0", "Unlicense", "BlueOak-1.0.0", "Python-2.0",
    )},
    **{k: Reach.FILE for k in ("MPL-2.0", "EPL-2.0", "CDDL-1.0")},
    **{k: Reach.LIBRARY for k in (
        "LGPL-2.1-only", "LGPL-2.1-or-later",
        "LGPL-3.0-only", "LGPL-3.0-or-later",
    )},
    **{k: Reach.PROGRAM for k in (
        "GPL-2.0-only", "GPL-2.0-or-later",
        "GPL-3.0-only", "GPL-3.0-or-later", "SSPL-1.0",
    )},
    **{k: Reach.NETWORK for k in ("AGPL-3.0-only", "AGPL-3.0-or-later")},
}


def reach_of(spdx: str) -> Reach:
    """Map one SPDX identifier onto a :class:`Reach`.

    An unlisted identifier is :attr:`Reach.UNKNOWN`, which refuses. Compound
    expressions are *not* parsed here — a row needing ``AND``/``OR`` states its
    axes explicitly, because the conjunction that matters (permissive code in a
    wheel that conveys a GPL program) is a two-axis fact, not one licence.

    >>> reach_of("MIT")
    <Reach.NONE: 'none'>
    >>> reach_of("AGPL-3.0-or-later")
    <Reach.NETWORK: 'network'>
    >>> reach_of("LicenseRef-AnimeGANv2-NonCommercial")
    <Reach.UNKNOWN: 'unknown'>
    """
    return REACH_BY_SPDX.get(spdx, Reach.UNKNOWN)


# --------------------------------------------------------------------------
# Evidence and terms: a row records an OBSERVATION; the tier is derived.
# --------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class Evidence:
    """One observation, with enough context to be re-checked or disbelieved."""

    method: str            # "probe" | "inspect" | "read" | "resolve"
    observed: str
    observed_on: str       # ISO-8601 date
    command: str | None = None
    source_url: str | None = None

    def is_stale(self, *, today: date | None = None) -> bool:
        """Older than :data:`STALE_AFTER_DAYS`. Reported, never auto-refused.

        >>> Evidence(method="read", observed="x", observed_on="2020-01-01"
        ...          ).is_stale(today=date(2026, 9, 2))
        True
        """
        today = today or date.today()
        return (today - date.fromisoformat(self.observed_on)).days > STALE_AFTER_DAYS


@dataclass(frozen=True, kw_only=True, slots=True)
class Terms:
    """What is known about one ``(provider_id, realisation)`` pairing.

    ``realisation`` is *how you obtain it* — ``"system"`` for found on PATH,
    ``"pypi:<dist>"`` for conveyed by a distribution. It is the analogue of
    falaw's ``backend`` key, and it is what makes :attr:`Conveyance.CONVEYS`
    expressible at all: one row per way of getting a thing, not per thing.
    """

    provider_id: str
    realisation: str
    spdx: str
    coupling: Coupling
    conveyance: Conveyance
    field_of_use: FieldOfUse = FieldOfUse.UNKNOWN
    reach: Reach | None = None  # None -> derive from spdx
    evidence: tuple[Evidence, ...] = ()
    note: str = ""

    @property
    def resolved_reach(self) -> Reach:
        return self.reach if self.reach is not None else reach_of(self.spdx)


@dataclass(frozen=True, kw_only=True, slots=True)
class Assessment:
    """The derived position. ``tier is None`` means *off the ladder*."""

    terms: Terms
    tier: Tier | None
    verdict: Verdict
    reasons: tuple[str, ...] = ()


def classify(terms: Terms) -> Assessment:
    """Project :class:`Terms` onto the ladder, or off it.

    Order of the branches is the design: UNKNOWN before everything (a fact we
    do not have cannot be reasoned from), then the forbidden region, then the
    field-of-use axis, then the rungs.

    >>> t = Terms(provider_id="ffmpeg", realisation="system",
    ...           spdx="GPL-3.0-or-later", coupling=Coupling.SUBPROCESS,
    ...           conveyance=Conveyance.FINDS,
    ...           field_of_use=FieldOfUse.UNRESTRICTED)
    >>> classify(t).tier
    <Tier.COPYLEFT_TOOL: 'copyleft_tool'>
    >>> linked = Terms(provider_id="x", realisation="pypi:x",
    ...                spdx="AGPL-3.0-or-later", coupling=Coupling.IN_PROCESS,
    ...                conveyance=Conveyance.CONVEYS,
    ...                field_of_use=FieldOfUse.UNRESTRICTED)
    >>> classify(linked).verdict, classify(linked).tier
    (<Verdict.FORBIDDEN: 'forbidden'>, None)
    """
    reach = terms.resolved_reach
    strong = (Reach.PROGRAM, Reach.NETWORK)

    if (Coupling.UNKNOWN in (terms.coupling,) or reach is Reach.UNKNOWN
            or terms.conveyance is Conveyance.UNKNOWN
            or terms.field_of_use is FieldOfUse.UNKNOWN):
        return Assessment(terms=terms, tier=None, verdict=Verdict.UNKNOWN,
                          reasons=("an axis is UNKNOWN; unknown is a refusal",))

    if terms.coupling is Coupling.IN_PROCESS and reach in strong:
        return Assessment(
            terms=terms, tier=None, verdict=Verdict.FORBIDDEN,
            reasons=("strong copyleft linked in-process: no ceiling admits it",))

    if terms.field_of_use is not FieldOfUse.UNRESTRICTED:
        return Assessment(
            terms=terms, tier=None, verdict=Verdict.FIELD_RESTRICTED,
            reasons=(f"field of use is {terms.field_of_use.value}; "
                     "this is not a rung and max_tier cannot grant it",))

    if terms.coupling is Coupling.NONE:
        tier = Tier.PURE
    elif reach in strong:                       # subprocess/service by now
        tier = (Tier.COPYLEFT_SHIPPED
                if terms.conveyance is Conveyance.CONVEYS
                else Tier.COPYLEFT_TOOL)
    elif reach in (Reach.FILE, Reach.LIBRARY):
        tier = (Tier.COPYLEFT_SHIPPED
                if terms.conveyance is Conveyance.CONVEYS
                else Tier.WEAK_COPYLEFT)
    else:
        tier = Tier.PERMISSIVE
    return Assessment(terms=terms, tier=tier, verdict=Verdict.ADMITTED)


#: Refusals ordered by how loudly they must be reported. A provider bundling
#: several components takes the WORST verdict among them.
_VERDICT_SEVERITY = (Verdict.ADMITTED, Verdict.OVER_CEILING,
                     Verdict.FIELD_RESTRICTED, Verdict.UNKNOWN,
                     Verdict.FORBIDDEN)


def assess(terms: Iterable[Terms]) -> Assessment:
    """The verdict for a provider made of several components: **the worst one**.

    Deliberately *not* a per-axis join across components. Joining axes that
    belong to different components manufactures a fact true of neither — join
    ``IN_PROCESS`` + ``Reach.NONE`` (OpenCV's own Apache-2.0 C++) with
    ``SUBPROCESS`` + ``Reach.PROGRAM`` (the GPL ffmpeg in the same wheel) and
    you get "we link a GPL program in-process", which nobody observed. Each
    component keeps its own row; the caller sees which one is the problem.

    >>> code = Terms(provider_id="opencv-code", realisation="pypi:opencv",
    ...              spdx="Apache-2.0", coupling=Coupling.IN_PROCESS,
    ...              conveyance=Conveyance.CONVEYS,
    ...              field_of_use=FieldOfUse.UNRESTRICTED)
    >>> assess([code]).tier
    <Tier.PERMISSIVE: 'permissive'>
    """
    terms = tuple(terms)
    if not terms:
        raise ValueError("assess() needs at least one Terms row")
    parts = [classify(t) for t in terms]
    worst = max(parts, key=lambda a: _VERDICT_SEVERITY.index(a.verdict))
    if worst.verdict is Verdict.ADMITTED:
        worst = max(parts, key=lambda a: DEFAULT_ORDER.index(a.tier))
    return Assessment(
        terms=worst.terms, tier=worst.tier, verdict=worst.verdict,
        reasons=tuple(r for p in parts for r in p.reasons),
    )


# --------------------------------------------------------------------------
# Policy: the one simple knob, and the escape hatch under it.
# --------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True, slots=True)
class Policy:
    """A ceiling, plus the two things a ceiling deliberately cannot reach.

    >>> Policy().admits(Tier.COPYLEFT_TOOL)
    True
    >>> Policy(max_tier=Tier.WEAK_COPYLEFT).admits(Tier.COPYLEFT_TOOL)
    False
    """

    max_tier: Tier = DFLT_MAX_TIER
    order: tuple[Tier, ...] = DEFAULT_ORDER
    allow_field_restricted: frozenset[FieldOfUse] = frozenset()

    def rank(self, tier: Tier) -> int:
        if tier not in self.order:
            raise LicenceUnknown(
                f"tier {tier!r} has no rung in this policy's ladder "
                f"({[t.name for t in self.order]}). An off-ladder verdict must "
                "be handled by check(), never compared against a ceiling.")
        return self.order.index(tier)

    def admits(self, tier: Tier | None) -> bool:
        """``None`` is off the ladder, so no ceiling admits it."""
        return tier is not None and self.rank(tier) <= self.rank(self.max_tier)


# --------------------------------------------------------------------------
# Refusals. Four types, because the REMEDIES differ.
# --------------------------------------------------------------------------

class LooksLicenceError(Exception):
    """Base for every licence refusal."""


class LicenceCeilingExceeded(LooksLicenceError):
    """On the ladder, above the ceiling. Remedy: raise it, or pick a provider."""


class LicenceForbidden(LooksLicenceError):
    """Off the ladder, permanently. There is no opt-in."""


class LicenceFieldRestricted(LooksLicenceError):
    """Non-commercial / research-only / no-derivatives. Needs its OWN opt-in."""


class LicenceUnknown(LooksLicenceError):
    """Undeterminable, unprobeable, or self-contradictory. Unknown refuses."""


def check(
    assessment: Assessment,
    policy: Policy,
    effect_name: str,
    *,
    alternatives: Sequence[str] = (),
) -> None:
    """Raise unless ``policy`` admits ``assessment``. Returns ``None`` on pass.

    A message names, in order: the effect, the tier it needs, the ceiling in
    force, WHY (the resolved provider and the observation that decided it,
    dated), and how to opt in — plus any lower-tier alternative, because a
    refusal that only says "no" makes the ceiling the thing people remove.
    """
    a, t = assessment, assessment.terms
    where = f"{t.provider_id} ({t.realisation})"
    why = "\n".join(
        f"       Observed {e.observed_on} by `{e.command or e.method}`: {e.observed}"
        + (f"\n       See {e.source_url}" if e.source_url else "")
        for e in t.evidence
    ) or "       (no evidence recorded — this itself is a defect)"
    tail = f"\n\n  {_SEE_DISCLAIMER}"

    if a.verdict is Verdict.UNKNOWN:
        raise LicenceUnknown(
            f"effect {effect_name!r}: cannot determine a licence tier for {where}.\n\n"
            f"  Why: {'; '.join(a.reasons)}\n{why}\n\n"
            "  looks refuses rather than guessing. Supply evidence for this "
            "provider, or select one that can be probed." + tail)

    if a.verdict is Verdict.FORBIDDEN:
        raise LicenceForbidden(
            f"effect {effect_name!r}: {where} is forbidden outright "
            f"({'; '.join(a.reasons)}).\n\n{why}\n\n"
            "  There is no opt-in: max_tier does not reach this region. "
            + (f"Alternatives: {', '.join(alternatives)}." if alternatives
               else "Use a different effect.") + tail)

    if a.verdict is Verdict.FIELD_RESTRICTED:
        fou = t.field_of_use
        if fou not in policy.allow_field_restricted:
            raise LicenceFieldRestricted(
                f"effect {effect_name!r}: {where} restricts the field of use "
                f"({fou.value}).\n\n{why}\n\n"
                "  max_tier cannot grant this — a ceiling is about copyleft, and "
                "agreeing to run a GPL binary is not agreeing to non-commercial "
                "terms. Opt in separately and deliberately:\n"
                f"       Policy(allow_field_restricted={{FieldOfUse.{fou.name}}})"
                + tail)
        return

    assert a.tier is not None
    if not policy.admits(a.tier):
        alt = (f"\n\n  A provider under your ceiling would satisfy this effect:\n"
               f"       {', '.join(alternatives)}" if alternatives else "")
        raise LicenceCeilingExceeded(
            f"effect {effect_name!r} needs tier {a.tier.name}; "
            f"the ceiling in force is {policy.max_tier.name}.\n\n"
            f"  Why: resolved provider {where}\n{why}{alt}\n\n"
            "  Or opt in deliberately:\n"
            f"       Look(..., max_tier=Tier.{a.tier.name})" + tail)


# --------------------------------------------------------------------------
# The ffmpeg probe. Reimplements FFmpeg's OWN resolution rule, so the probe is
# verifiable against the thing it probes.
# --------------------------------------------------------------------------

#: FFmpeg's ``EXTERNAL_LIBRARY_GPL_LIST`` (release/8.1). A build enabling any of
#: these MUST also carry ``--enable-gpl``; FFmpeg's own configure dies otherwise.
#: A build that claims not to is contradicting itself.
FFMPEG_GPL_COMPONENTS = frozenset({
    "avisynth", "frei0r", "libcdio", "libdavs2", "libdvdnav", "libdvdread",
    "librubberband", "libvidstab", "libx264", "libx265", "libxavs",
    "libxavs2", "libxvid",
})

#: Video filters FFmpeg release/8.1 guards behind ``gpl``. 32 of the 33 were
#: measured absent from an LGPL build on 2026-09-02; the 33rd, ``boxblur_opencl``,
#: needs OpenCL. ``eq`` being here is why the tier cannot be a constant.
FFMPEG_GPL_ONLY_FILTERS = frozenset("""
blackframe boxblur boxblur_opencl colormatrix cover_rect cropdetect delogo eq
find_rect fspp histeq hqdn3d interlace kerndeint mcdeint mpdecimate mptestsrc
nnedi owdenoise perspective phase pp7 pullup repeatfields sab signature
smartblur spp stereo3d super2xsai tinterlace uspp vaguedenoiser
""".split())

_CONFIG_RE = re.compile(r"^\s*configuration:\s*(.*)$", re.M)


def ffmpeg_spdx_from_configuration(configuration: str) -> str | None:
    """FFmpeg's own licence rule, verbatim from ``configure`` release/8.1.

    Returns ``None`` when the configuration contradicts itself — a GPL-only
    component enabled without ``--enable-gpl``, which FFmpeg's own build cannot
    produce. That is not a GPL verdict; it is an unclassifiable artifact.

    >>> ffmpeg_spdx_from_configuration("--enable-gpl --enable-version3")
    'GPL-3.0-or-later'
    >>> ffmpeg_spdx_from_configuration("--enable-gpl")
    'GPL-2.0-or-later'
    >>> ffmpeg_spdx_from_configuration("--enable-version3")
    'LGPL-3.0-or-later'
    >>> ffmpeg_spdx_from_configuration("--enable-shared")
    'LGPL-2.1-or-later'

    The `av` 16.0.1 case, which is why this returns Optional:

    >>> ffmpeg_spdx_from_configuration(
    ...     "--enable-version3 --enable-libx264 --enable-libx265") is None
    True
    """
    flags = set(re.findall(r"--enable-([A-Za-z0-9_]+)", configuration))
    gpl, version3 = "gpl" in flags, "version3" in flags
    if not gpl and (flags & FFMPEG_GPL_COMPONENTS):
        return None
    if "nonfree" in flags:
        return None  # unredistributable: not a licence we can place
    if version3 and gpl:
        return "GPL-3.0-or-later"
    if version3:
        return "LGPL-3.0-or-later"
    if gpl:
        return "GPL-2.0-or-later"
    return "LGPL-2.1-or-later"


class Runner(Protocol):
    """The subprocess seam — so the suite probes fixtures, never the machine."""

    def __call__(self, args: Sequence[str]) -> str: ...


def _run(args: Sequence[str]) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=False).stdout


def probe_ffmpeg(
    exe: str = "ffmpeg",
    *,
    realisation: str = "system",
    run: Runner = _run,
    today: date | None = None,
) -> Terms:
    """Resolve one ffmpeg's terms from the binary itself.

    An absent or unreadable binary yields ``UNKNOWN`` axes — which refuse.
    There is no "assume LGPL" and no warning-instead-of-refusal.
    """
    stamp = (today or date.today()).isoformat()
    unknown = Terms(
        provider_id="ffmpeg", realisation=realisation, spdx="LicenseRef-UNPROBED",
        coupling=Coupling.UNKNOWN, conveyance=Conveyance.UNKNOWN,
        field_of_use=FieldOfUse.UNKNOWN, reach=Reach.UNKNOWN,
        evidence=(Evidence(method="probe", command=f"{exe} -version",
                           observed="probe failed or binary absent",
                           observed_on=stamp),),
    )
    if shutil.which(exe) is None and realisation == "system":
        return unknown
    out = run([exe, "-version"])
    m = _CONFIG_RE.search(out)
    if not m:
        return unknown
    configuration = m.group(1)
    spdx = ffmpeg_spdx_from_configuration(configuration)
    ev = Evidence(method="probe", command=f"{exe} -version",
                  observed=f"configuration: {configuration}",
                  source_url="https://ffmpeg.org/legal.html", observed_on=stamp)
    if spdx is None:
        return Terms(provider_id="ffmpeg", realisation=realisation,
                     spdx="LicenseRef-CONTRADICTORY", coupling=Coupling.SUBPROCESS,
                     conveyance=Conveyance.UNKNOWN, field_of_use=FieldOfUse.UNKNOWN,
                     reach=Reach.UNKNOWN, evidence=(ev,),
                     note="self-contradictory build; looks does not adjudicate")
    return Terms(
        provider_id="ffmpeg", realisation=realisation, spdx=spdx,
        coupling=Coupling.SUBPROCESS,
        conveyance=(Conveyance.FINDS if realisation == "system"
                    else Conveyance.CONVEYS),
        field_of_use=FieldOfUse.UNRESTRICTED, evidence=(ev,),
    )
```

---

## 8. What is unverified

Named explicitly, because an unverified claim asserted as fact would defeat the point of the whole design.

- **`opencv-python-headless`** — not installed here; whether it also bundles a GPL ffmpeg is **unverified**, and it is the first thing to check before `looks` declares any `opencv` extra.
- **`av` 16.0.1's legal position** — deliberately **not** adjudicated. The four-layer disagreement is verified; whether the build is lawful (x264/x265 are dual-licensed, so a commercially-licensed build is conceivable) is not, and `looks` refuses on the contradiction rather than on a conclusion. Whether this is known upstream is unchecked.
- **Whether the observations here hold on Linux and Windows wheels** — every measurement is macOS arm64. The `av`, `opencv` and `imageio-ffmpeg` wheels are built per platform, and per-platform variation is exactly the kind of thing that makes a probe necessary rather than a constant.
- **`libpostproc`'s GPL guard** — `postproc` does not appear in FFmpeg release/8.1's `configure` at all (it was removed), so the claim that it is GPL-only in the ffmpeg 7.1.1 bundled by the OpenCV wheel is **unverified for that version**. It is not load-bearing: `libx264`, `libx265`, `libvidstab` and `librubberband` in that wheel are verified GPL-list members, and the bundled `avutil_license()` says GPL-3.0-or-later outright.
- **`libopenh264` as a permissive H.264 encoder** — plausible substitute for `libx264` (BSD-2-Clause code; Cisco's binary distribution carries its own patent-licence arrangement), **unverified** here, and encoding is out of `looks`' scope anyway.
- **Replicate's `weights_licenses.md`** — reported second-hand via falaw#16 [13]; not read directly.
- **The 32-filter figure across other FFmpeg versions** — anchored to release/8.1 `configure` and to the two builds on this machine. It will drift.
- **`looks` has no code yet**, so nothing here has been run *as* `looks`. §7 itself **has** been run, though: the module was extracted from this document and executed on 2026-09-02, its 19 doctests pass, and the six behaviours the design turns on were demonstrated end-to-end against this machine — the real `ffmpeg` on `PATH` probing to `GPL-3.0-or-later`/`COPYLEFT_TOOL`; `av` 16.0.1's own configuration string returning `None` (contradiction → `LicenceUnknown`, not a GPL verdict); `LicenceCeilingExceeded` at a `WEAK_COPYLEFT` ceiling; `LicenceFieldRestricted` still raising with `max_tier` at the **top** rung and yielding only to the explicit opt-in; OpenCV assessed as two components to `COPYLEFT_SHIPPED` (refused by the default ceiling) with no chimera; and `admits(None)` returning `False` rather than raising. Executing it is also what **found the per-axis-join defect** described in §2.3 — which is the argument for §11 of the federation's working rules ("code in a design document that has never run is a hypothesis") landing on this note too.

---

## REFERENCES

1. [FFmpeg, `configure`, release/8.1](https://raw.githubusercontent.com/FFmpeg/FFmpeg/release/8.1/configure) — fetched 2026-09-02 (307,358 bytes). Licence resolution block, `die_license_disabled`, `EXTERNAL_LIBRARY_GPL_LIST`, and the 33 `*_filter_deps="…gpl…"` declarations. See also [FFmpeg Legal](https://ffmpeg.org/legal.html).
2. [`an-dev-licensing` skill](https://github.com/thorwhalen/an) — `an` repo, `.claude/skills/an-dev-licensing/SKILL.md`. Rule 1 ("the chip is not evidence, in either direction"), Rule 2 (code / weights / editor are three separate licences), Rule 5 (enforce in code, not in prose).
3. [reelee-web licence guard](https://github.com/thorwhalen/reelee-web) — `scripts/licenses/spdx.mjs`, `collect.mjs`, `collect.test.ts`. The permissive allowlist, the ordered text probes, the deliberate `BSD-4-Clause` exclusion, and the copyleft-vs-unknown split.
4. [SPDX License List](https://spdx.org/licenses/) — **version 3.28.0, released 2026-02-20** (read 2026-09-02).
5. [SPDX Specification](https://spdx.github.io/spdx-spec/) — licence expressions (`AND` / `OR` / `WITH`) and the `LicenseRef-*` mechanism for terms with no listed identifier.
6. [REUSE Specification 3.3](https://reuse.software/spec-3.3/) — released 2024-11-14. `SPDX-License-Identifier` / `SPDX-FileCopyrightText`, `LICENSES/`, `REUSE.toml`, and the [REUSE tool](https://codeberg.org/fsfe/reuse-tool).
7. [Debian machine-readable copyright format 1.0 (DEP-5)](https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/) — per-`Files:`-glob licence paragraphs.
8. [`pip-licenses`](https://pypi.org/project/pip-licenses/) — reads distribution metadata.
9. [`licensecheck`](https://pypi.org/project/licensecheck/) — same class of tool, same limitation.
10. [frei0r, `include/frei0r.h`](https://raw.githubusercontent.com/dyne/frei0r/master/include/frei0r.h) — `f0r_plugin_info_t`; no licence field (read 2026-09-02).
11. [frei0r, `COPYING`](https://raw.githubusercontent.com/dyne/frei0r/master/COPYING) — GNU GPL version 2, June 1991.
12. [OpenFX, `include/ofxCore.h`](https://raw.githubusercontent.com/AcademySoftwareFoundation/openfx/main/include/ofxCore.h) — `SPDX-License-Identifier: BSD-3-Clause`; no licence or copyright property in the property set (read 2026-09-02).
13. [thorwhalen/falaw#16](https://github.com/thorwhalen/falaw/issues/16) — the `(model, backend)` terms ledger; `unknown` is a refusal at plan time; `terms_context` passed by the caller, never read from a global; the Replicate `weights_licenses.md` precedent; and the ruling that the validated SPDX vocabulary is defined once.
14. [`illustration/licensing.py`](https://github.com/thorwhalen/illustration) — `normalize_license`, and the invariant that normalisation may never drop a restriction token; `RIGHTS_FIELDS` and its three literal-pinned guard hops.
15. [AnimeGANv2](https://github.com/TachibanaYoshino/AnimeGANv2) — "made freely available to academic and non-academic entities for non-commercial purposes"; commercial use requires a written authorisation letter (read 2026-09-02).
16. [White-box Cartoonization](https://github.com/SystemErrorWang/White-box-Cartoonization) — [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode); "Commercial application is prohibited" (read 2026-09-02).
17. [`av` (PyAV)](https://pypi.org/project/av/) — 16.0.1 measured locally 2026-09-02: `License-Expression: BSD-3-Clause`; bundled `avcodec_license()` = "LGPL version 3 or later"; configuration enables `libx264`/`libx265` without `--enable-gpl`; `libavcodec` links both dylibs; both encoders constructible.
18. [`imageio-ffmpeg`](https://pypi.org/project/imageio-ffmpeg/) — 0.6.0 measured locally 2026-09-02: `BSD-2-Clause` metadata; ships a 49.4 MB `--enable-gpl` ffmpeg 7.1 whose `-L` prints GPL v2 or later.
19. [`opencv-python`](https://pypi.org/project/opencv-python/) / [`opencv-contrib-python`](https://pypi.org/project/opencv-contrib-python/) — 4.12.0.88 and 4.13.0.92 measured locally 2026-09-02: `License: Apache 2.0` metadata, MIT in-wheel `LICENSE.txt`, and bundled `libx264`/`libx265` plus an ffmpeg 7.1.1_3 reporting `GPL version 3 or later`.
20. [`ultralytics`](https://pypi.org/project/ultralytics/) — 8.4.75 measured locally 2026-09-02: ships the full GNU Affero General Public License v3 text.
21. [x264](https://www.videolan.org/developers/x264.html) and [x265](https://www.x265.org/) — both GPL-2.0-or-later with a commercial alternative; the dual licensing is why §1.3 refuses to adjudicate `av`.
22. `looks/KICKOFF.md` and thorwhalen/muvid#63 — the non-negotiables this note implements, and the measured Que Calor V2 design constraints.
