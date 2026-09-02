# `looks` — research notes

Thirteen investigations plus six first-hand evidence notes, all dated **2026-09-02**. The decisions taken from them are in [`../decisions_and_rationale.md`](../decisions_and_rationale.md) — **read that first**; these are the working, not the ruling.

**Every numbered note carries an appended `## Adversarial review` section**, written by a second reader who re-ran every command rather than taking it on trust. **Where a review refuted a claim, the correction wins over the note's body text.** Three of the refutations ran in the *permissive* direction, which is the direction that matters for a package built on refusal.

## First-hand evidence (`00*`) — by the orchestrating session, so the agents' briefs had something to check against

| note | one line |
|---|---|
| [`00_ffmpeg_licence_gates_evidence.md`](00_ffmpeg_licence_gates_evidence.md) | FFmpeg's own gates extracted from `configure` at `n8.1`: 38 GPL-gated filters, `eq` among them — plus the correction that five of the 38 are gated *indirectly*, which the first extraction missed in the permissive direction. |
| [`00b_colour_range_trap_evidence.md`](00b_colour_range_trap_evidence.md) | The colour trap is **range** (and, per the correction, the **matrix**), not pixel format: `format=rgb24` before `lut3d` is a byte-identical no-op; untagged range changes 99.6% of bytes. |
| [`00c_the_insertion_point_evidence.md`](00c_the_insertion_point_evidence.md) | Where a Look actually attaches, read off `muvid.footage.assemble`'s bounded-memory invariant: one `-vf` fragment per part — which dissolves the "which source is on screen at *t*" problem. |
| [`00d_forbidden_deps_evidence.md`](00d_forbidden_deps_evidence.md) | `av`, `imageio-ffmpeg` and `opencv-contrib-python` verified on disk. For `av`, three layers disagree and the two easy ones both look reassuring. |
| [`00e_the_flatten_tension.md`](00e_the_flatten_tension.md) | A cross-note synthesis: the flagship look's flattener has a **platform-dependent** tier, so no static declaration can tell the truth about it. |
| [`00f_motion_filters_evidence.md`](00f_motion_filters_evidence.md) | Which filter compiles a camera path — and a **recorded fleet fact corrected**: `zoompan`'s two recorded objections are both true and its conclusion is wrong, while the filter the notes recommended instead cannot express a zoom at all. Three further traps measured, each a silent wrong answer. |
| [`ffmpeg_n81_licence_gates.json`](ffmpeg_n81_licence_gates.json) | Machine-readable companion to `00`. Superseded in-package by `looks/data/ffmpeg_gates.json` (schema v2, direct and indirect stored separately). |

## The thirteen investigations

| note | verdict | one line |
|---|---|---|
| [`01_prior_art_oss.md`](01_prior_art_oss.md) | sound-with-corrections | Twelve live PyPI ffmpeg wrappers, **zero** with a named-effect registry or any licence awareness — but the prior art that matters is FFmpeg's own `configure`, which already implements this thesis at build time. |
| [`02_prior_art_fleet.md`](02_prior_art_fleet.md) | sound-with-corrections | The fleet calls ffmpeg from 116 files and reimplements the same five primitives 2-5x each. `muvid.visualize` is the shape to port; `burns` and `mixing.video_util` must **not** simply move — both have live consumers the kickoff misses. |
| [`03_spec_type.md`](03_spec_type.md) | **needs-rework** | The core types. Its central decision survives — the tier is declared by the implementation, **never** by the request — but its ladder and its frozen `tier=` field were both refuted. Read the review with the note. |
| [`04_clip_aware_resolution.md`](04_clip_aware_resolution.md) | sound-with-corrections | The zero-dependency tier can measure everything the resolver acts on. Minimising output spread is an **exact O(N log N) sweep**, not a search — but k=3 probes was too few. |
| [`05_compilation_and_backends.md`](05_compilation_and_backends.md) | sound-with-corrections | A Look never needs `-filter_complex`, and a filter run adjacent to a frame stage **folds** into that stage's own pipe. An unknown colour contract is a refusal. |
| [`06_licence_tiers.md`](06_licence_tiers.md) | sound-with-corrections | The taxonomy: four orthogonal axes, a five-rung ladder that is a replaceable **policy projection** of three of them, and two regions no ceiling can reach. |
| [`07_ffmpeg_licence_surface.md`](07_ffmpeg_licence_surface.md) | sound-with-corrections | FFmpeg's internal split, filter by filter, plus the probe rules. `geq` has not been GPL since 4.3. The real wall is in the **encoders**. |
| [`08_opencv_and_python_deps.md`](08_opencv_and_python_deps.md) | sound-with-corrections | The optional-extras surface. `opencv-python`'s macOS **arm64** wheels bundle a GPL-3 FFmpeg; the manylinux ones are clean and the macOS x86_64 one has no FFmpeg at all. |
| [`09_neural_restyling.md`](09_neural_restyling.md) | sound-with-corrections | **No neural backend and no neural seam** for v1: nothing clears both the licence bar and the flicker bar. Measured, not argued. |
| [`10_shader_backend.md`](10_shader_backend.md) | sound-with-corrections | **No shader backend, and never as a `backend`.** The machine with the GPU has no GPU filters; the machine with no GPU has all of them, and libplacebo there is 141x slower than CPU while exiting 0. |
| [`11_fleet_integration.md`](11_fleet_integration.md) | sound-with-corrections | How `looks` reaches the federation. The pattern already exists (`nw.transforms.cache_key`, braidio's local-render Transform); `muvid` hosts it first; **Rule G** and **Rule N**. |
| [`12_mixing_refactor.md`](12_mixing_refactor.md) | sound-with-corrections | The geometry tier and the transitions, moved without moviepy. Only `paces` consumes anything — and two of `mixing`'s six transitions render a **hard cut** today. |
| [`13_effect_catalogue.md`](13_effect_catalogue.md) | sound-with-corrections | The v1 catalogue: three effect families plus a `Transition` type, 22 entries with a verified compile target. The gradient-map LUT is **stdlib-only**. |
