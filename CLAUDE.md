# looks — agent entry point

`looks` is a **facade over video stylization**: named effects that compile to a backend command, each carrying a **licence tier**, so a caller can demand commercial-safe-only and get a **refusal** rather than a surprise. Pure-data specs, separable from execution — the `falaw.Plan` shape, except the cost unit is **CPU-seconds, not dollars**.

## Read these before non-trivial work

1. **[`docs/decisions_and_rationale.md`](docs/decisions_and_rationale.md)** — the design of record. Read it before touching types, tiers, compilation or the federation seam.
2. **[`docs/research/`](docs/research/)** — thirteen investigations behind it, each with an appended **adversarial review** by a second reader who re-ran every command. Where a review refuted a claim, **the correction wins over the note's body text.** Start with `00*` (first-hand evidence from the orchestrating session), then the numbered notes.

Do not re-derive anything in those. They cost real time, and several of their findings are counter-intuitive enough that a fresh derivation is likely to land on the wrong answer.

## Non-negotiables

- **Zero declared dependencies.** `pyproject.toml` declares nothing but stdlib; every backend is an optional extra. **Never** depend on `av` or `imageio-ffmpeg` — both declare permissive licences while shipping GPL binaries, verified on disk (`av`'s build even patches FFmpeg's `configure` so its self-report is engineered, not merely absent). `opencv-python`'s **macOS arm64** wheels do the same; its **manylinux** wheels are clean and its **macOS x86_64** wheel bundles no FFmpeg at all — so any `[flatten]` extra's tier is **platform-dependent**, and a static declaration cannot tell the truth about it.
- **ffmpeg is shelled out to, never linked.**
- **The licence tier is a refusal, not a warning**, and **unknown is a refusal** — not a default, not a guess, not "probably LGPL".
- **Execution and muxing are out of scope**, enforced (see below). So are cut/EDL decisions: an `Effect.at` says *where a look applies*, never where a cut is.
- House style: functional over OOP; `dataclasses` for data; `Protocol` over ABC; keyword-only past the 3rd argument; no magic numbers; a module docstring on every module (ruff `D100` is on); doctests on public functions.

## The invariant, which is enforced rather than documented

> **Every ffmpeg process `looks` starts ends in `-f null -`.**

`looks/_run.py` is the **single process chokepoint**, and `looks/tests/test_invariant.py` has two guards: the chokepoint refuses a producing argv, and an AST scan refuses any module that imports `subprocess` directly. The second is the one that matters, because guard 1 protects only code that goes through it.

Why it is a mechanism and not a comment: a convenience `looks.render(clip, look)` *will* get used and *will* rebuild one whole-timeline `-filter_complex`, undoing the bounded-memory invariant `muvid.footage.assemble` won after 30-cut OOM kills. That is a measured 2.3 GB regression on a 3.7 GB box, not a style preference.

It earned itself immediately: the guard caught `environment.py`, written an hour earlier by the same session that wrote the guard.

Note the tail rule — ffmpeg takes the **last** output specification, so `-f null -` followed by a real output is a render. The sink must be the argv tail.

**The tail rule alone is NOT sufficient** — ffmpeg accepts *multiple* outputs, so `ffmpeg -i a.mp4 -c:v libx264 out.mp4 -map 0:v -f null -` passed the first version of `check_analysis_only` **and wrote a real 6170-byte H.264 file**. Closed (D-1): `output_specs()` now parses every output specification and requires exactly one, which must be the sink. Encoder options are **deliberately absent** from `VALUE_OPTIONS`, so their values read as outputs and any argv containing one is refused twice over. `ffprobe` stays exempt and must — `ffprobe -f null -` fails outright with "Unknown input format: null".

## Where `looks` sits in the federation

```
lacing  (annotation graph)
  -> nw.ProjectGraph + nw.Transform
       -> falaw.Plan      (consent-to-spend for an irreversible BILLED call)
       -> looks.LookPlan  (local CPU: not irreversible, not billed)
            -> backends
```

**`looks` is a peer of `burns`, not of `falaw`.** `nw.transforms.cache_key` (nw#54) already exists for "a Transform that spends money or CPU **without** going through fal", and `braidio.segment_extraction.ffmpeg` is its reference implementation — a local-render Transform whose `plan()` returns a zero-call `falaw.Plan` plus a skeleton carrying its own cache key. A `looks`-backed stylize step is that shape, so it needs **no new mechanism in `nw`**.

- **`looks` hosts no Transform, imports no federation package, and spawns no process.**
- The Transform is hosted by **`muvid` first**, graduating into `nw` on the rule of three.
- The seam is a **`-vf` fragment** the consumer splices into the per-part invocation it is already making. A compiled chain references **no input index**, which is what makes the splice work.
- Applying **per cut, before assembly** dissolves the "which source is on screen at time *t*" problem — at part-render time the caller already knows.

**`burns` stays separate** and gains a `looks`-backed ffmpeg backend. `looks -> burns` is **forbidden**: burns declares moviepy, which pulls imageio-ffmpeg's GPL binary. The dividing line is **authored versus derived geometry**, not "geometry versus pixels" — `burns` owns a path someone drew over time, `looks` owns geometry computed from a pair of sizes.

**`looks` owns normalisation as well as stylization** — one vocabulary, one tier system, one insertion point. The difference is two *resolvers*, not two Effect types: resolve against an external target, or against the set's own distribution.

## The measured facts. Do not re-derive; do not contradict.

From building the first real look (Que Calor V2), and independently reproduced here where noted.

- **The chain that works:** flatten (`cv2.pyrMeanShiftFiltering`) → 3D LUT (`lut3d`) → posterise (`lutrgb`). Frame-independent by construction, so it **cannot flicker**.
- **`pyrMeanShiftFiltering`, never `edgePreservingFilter`.** The latter smooths *across* object boundaries and dissolves figures into the background. Mean-shift clusters in colour *and* position, so boundaries survive.
- **Measure the target before assuming a filter.** The reference had **no black, no white and no outlines**, so the classic "cartoonify" (bilateral + adaptive-threshold black edges) would have been exactly wrong — it adds ink the reference never had.
- **Gamma, never a brightness offset.** An offset lifts the black floor and reads as haze.
- **Don't end a ramp at black.** A dark anchor at L\* 3.6 crushed 16.2% of pixels into the bottom bin where the reference had 0.3%; its own floor was an oxblood at L\* 8.22. `looks.lut.gradient_map` warns below L\* 5.
- **Parameters resolve against the clip.** One global flattening scale made the softest of three sources softer still (46 → 38, against 35 → 72 and 117 → 114), so it became the softest thing on screen.
- **Normalise the OUTPUT, not the input.** Don't sharpen the soft one; measure post-effect and land the clips in family. Full resolution was available and sharper and was **deliberately not used** — it would have made the softest source the *sharpest* thing in the edit, a new mismatch rather than a fix.
- **The probe budget is 5 frames, not 3.** A 3-frame median carries p90 relative error of 12.7–34.0%, larger than the improvements a resolver chooses between.

## Licence facts, all verified from source or from disk

- **38 of ~481 ffmpeg filters are GPL-gated**, and **every GPL-gated colour operation has an LGPL-or-better substitute in the same binary** — so no colour *capability* sits only behind the GPL wall. State it that way: the stronger form ("not one is a colour operation") is false, because `eq`, `histeq` and `colormatrix` are three. `eq` — the obvious brightness/contrast/gamma/saturation filter — is the one that matters. LGPL-clean substitutions: `curves`, `lutyuv`, `colorlevels`, `colorbalance`, `huesaturation`, `exposure`; `gblur` for `boxblur`; `atadenoise`/`removegrain` for `hqdn3d`. **The one gap:** `eq`'s `gamma_weight` has no exact LGPL equivalent. **The one exact substitution measured:** `eq=gamma` -> `lutyuv=y='clip(pow(val/255,1/g)*255,0,255)'`, within 0.55/255 mean luma.
- **A filter is gated two ways.** *Directly* (literal `gpl` in its `_filter_deps`, 33 filters) and *indirectly* (its deps name a library in `EXTERNAL_LIBRARY_GPL_LIST`, 5 filters: `frei0r`, `frei0r_src`, `rubberband`, `vidstabdetect`, `vidstabtransform`). **Missing the indirect set is a false permission** — the first version of the table did, and tiered stabilisation as permissive. `looks/data/ffmpeg_gates.json` stores the two classes separately so a re-extraction cannot drop one.
- **A directly-gated filter is in every GPL build; an indirectly-gated one is not** — the latter also needs its external library, a separate build flag.
- **`geq` is not GPL** and has not been since FFmpeg 4.3 (relicensed 2019-12-16). The belief outlives the fact; a test pins it.
- **The GPL wall is in the ENCODERS.** `libx264`/`libx265` are FFmpeg's only software H.264/HEVC encoders, both GPL, so an LGPL-tier *deliverable* is AV1 (SVT-AV1), VP9, ProRes/DNxHD/FFV1, or hardware.
- **Probe rules:** `ffmpeg -L` is the *only* authority on a binary's licence — a compile-time `#if` cascade, so it cannot be patched out the way the `configuration:` line can. `ffmpeg -filters` is the *only* authority on availability: **`ffmpeg -h filter=NAME` exits 0 for an unknown filter** (it prints "Unknown filter" then "Exiting with exit code 0").
- **There is not one ffmpeg on a machine.** Measured here: PATH is 8.1/GPL-3/481 filters; `imageio-ffmpeg`'s bundled binary is 7.1/GPL-2/484, with **non-nested** filter sets. So the environment is an **argument**; nothing downstream may call `probe()` for itself.
- **No neural backend, and no neural seam.** The one commercially-clean CPU-runnable stylizer fails the flicker bar by measurement (1.20–2.82× the source's own change, against the shipped chain's 0.70×), and FFmpeg's `gpl/nonfree/version3` vocabulary cannot express the four things that bind a model: the code/weights split, non-commercial (≠ `nonfree`, which means *unredistributable*), patent encumbrance, and whether the licence binds *us* or the host. The hosted route is `falaw`'s job.

## Tests

`pytest` from the repo root runs what CI runs.

- **Tests live in `looks/tests/`, never a repo-root `tests/`.** CI runs `pytest --doctest-modules looks`, so anything outside the package directory is **never collected** — a green tick over zero tests.
- `doctest_optionflags` is exactly `ELLIPSIS IGNORE_EXCEPTION_DETAIL`, matching what CI passes with `-o`. **No `NORMALIZE_WHITESPACE`** — it would pass locally and fail in CI.
- **Offline and free.** Synthesise sources with `ffmpeg -f lavfi`. But **not every lavfi source is deterministic**: `testsrc2` is bit-reproducible with no pinning; `gradients` defaults to `seed=-1` and `speed=0.01`, and two identical command lines differed by the full 255/255. Pin the geometry, pin `speed`, and check any new source for a `seed`.
- Compare **decoded pixels**, never encoded bytes — an mp4 is not byte-comparable across builds.
- Skip with `pytest.skip` **inside the test body**, never `importorskip` at module scope, which removes tests from collection entirely and makes their absence invisible in both the pass and skip counts.
- `docs/` is excluded from ruff: **ruff ≥ 0.16 formats Python inside Markdown fences**, and CI's publish job runs `ruff format .` and commits the result, so without the exclusion every release rewrites the research notes.

## What never to do

- Never write a `render` / `apply` / `encode` / `write_video` on `looks`. A test asserts their absence.
- Never call `subprocess` outside `looks/_run.py`.
- Never read a licence from a package's metadata field or from a library's own self-report. Read the shipped binary (`otool -L` / `ldd`). Three of the most obvious media dependencies lie in the permissive direction.
- Never write a doctest from what you expect the output to be. **Run it first.** Two bugs in this repo passed their doctests and failed against reality: a filter-row regex tested against a hand-invented sample returned zero filters from the real binary, and a "neutral" ramp that is not an identity.
- Never compare two `ClipStats` whose `stage`, `instrument`, `luma_space` or `sample_spec` differ. `compare()` raises; the measured disagreements are larger than the effects being chosen between.
- Never add a dependency without checking what its wheel *ships*, not what it *declares*.
