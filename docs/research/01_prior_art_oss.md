# External prior art: what already exists, and how `looks` is different

**Date: 2026-09-02**
**Scope:** PyPI ffmpeg wrappers, colour/LUT libraries, named-effect registry formats in any language, and anything that already does "declarative video effect spec, separable from execution".

## Verdict (stop here if you only read one paragraph)

**The positioning claim is confirmed, with one correction and one relocation.** Confirmed: of the twelve live Python ffmpeg/video wrappers surveyed, **zero** carry a registry of named effects, and **zero** carry any licence awareness whatsoever — not a field, not a check, not a warning. The correction is to the count: "~8 ffmpeg wrappers" undercounts the live field (twelve here, and the survey is not exhaustive), and three of them are themselves copyleft — `ffmpegio` is **GPL-2.0** and the `gmic` bindings are **CeCILL-2.1**, so a caller who reaches for a wrapper to stay clean can pick up copyleft *from the wrapper itself*. The relocation is the important finding: **the prior art that actually matters is not on PyPI at all — it is FFmpeg's own `configure`**, which already implements precisely `looks`' thesis. FFmpeg declares `LICENSE_LIST="gpl nonfree version3"`, tags each external library and each filter with the tier it requires, and **refuses to build — `die`, not warn** — when a component exceeds the declared ceiling [1]. That is `looks`' non-negotiable, already written, in shell, at build time. `looks`' genuine contribution is not inventing that idea but **moving it from build time to call time**, where the person choosing an effect actually is. Two secondary findings are directly actionable: `eq` — the most obvious grading filter in ffmpeg — is **GPL-gated**, while `colorlevels`/`curves`/`colorbalance`/`colorcorrect` are not, which is exactly the substitution a licence-aware facade exists to make; and **nothing surveyed generates a gradient-map 3D LUT**, so the Que Calor vehicle has no prior art to reuse, only `colour-science` (BSD-3-Clause) to write the `.cube` with.

---

## 1. Python ffmpeg / video wrappers

All versions and dates below are from the PyPI JSON API, fetched 2026-09-02; last-commit dates are from the GitHub API, same date. "Shape" is the API's mental model.

| Name | Version observed | Last release | Last commit | Licence (declared) | Shape | Named-effect registry? | Licence awareness? | Maintained? | Overlap with `looks` |
|---|---|---|---|---|---|---|---|---|---|
| [ffmpeg-python](https://pypi.org/project/ffmpeg-python/) | 0.2.0 | 2019-07-06 | 2022-07-11 | Apache-2.0 | **Graph** — Python object DAG of `InputNode`/`FilterNode`/`OutputNode`; `compile()`/`get_args()` emit argv without running [2] | No | **None** | **No** (no release in 7 yrs) | Closest on *spec/execution separation*; see §5 |
| [python-ffmpeg](https://pypi.org/project/python-ffmpeg/) | 2.0.12 | 2024-04-15 | 2024-04-15 | MIT | Imperative builder (`.input().output().execute()`), sync + async, event emitter | No | None | Marginal | Command construction only |
| [ffmpy](https://pypi.org/project/ffmpy/) | 1.0.0 | 2025-11-11 | 2025-11-11 | MIT | **String** — thin `subprocess` wrapper; you write the ffmpeg args | No | None | Yes | Execution only; no model at all |
| [imageio-ffmpeg](https://pypi.org/project/imageio-ffmpeg/) | 0.6.0 | 2025-01-16 | — | BSD-2-Clause *(metadata)* | Frame reader/writer generators | No | None | Yes | **Licence hazard — see §4** |
| [PyAV (`av`)](https://pypi.org/project/av/) | 18.1.0 (PyPI) / **16.0.1 installed** | 2026-08-12 | 2026-09-02 | BSD-3-Clause *(metadata)* | **Linked bindings** to libav*; frame-level | No | None | Yes, actively | **Licence hazard — see §4** |
| [moviepy](https://pypi.org/project/moviepy/) | 2.2.1 | 2025-05-21 | 2026-08-26 | MIT | **Object/compositional** — `VideoClip`, `.fx()`, in-memory numpy frames | `.fx()` is a convention, not a registry | None | Yes | Geometry tier `looks` inherits from `mixing` is built on this |
| [vidgear](https://pypi.org/project/vidgear/) | 0.3.5 | 2026-05-17 | 2026-05-17 | Apache-2.0 | Imperative streaming gears (`WriteGear`, `StreamGear`) | No | None | Yes | Streaming/IO, not stylization |
| [scikit-video](https://pypi.org/project/scikit-video/) | 1.1.11 | **2018-09-18** | 2026-07-04 | BSD | Array-in/array-out algorithms | No | None | **No** (repo commits, but no release in 8 yrs) | Quality metrics, not effects |
| [ffmpeg-progress-yield](https://pypi.org/project/ffmpeg-progress-yield/) | 1.1.3 | 2026-03-30 | 2026-07-10 | MIT | Generator wrapping one ffmpeg run for progress | No | None | Yes | Orthogonal — a progress concern |
| [static-ffmpeg](https://pypi.org/project/static-ffmpeg/) | 3.0 | 2026-01-16 | — | MIT | Binary fetcher; adds `ffmpeg` to PATH | No | None | Yes | **Licence hazard** (ships binaries; build flags **unverified**) |
| [ffmpegio](https://pypi.org/project/ffmpegio/) | 0.12.0 | 2026-07-03 | — | **GPL-2.0** | Media I/O, numpy-centric | No | None | Yes | **The wrapper itself is copyleft** |
| [movis](https://pypi.org/project/movis/) | 0.7.1 | 2023-11-25 | 2024-05-25 | MIT | Layer/composition model, `add_effect()` | Effects are classes, not a registry | None | No | Closest on *composition*, no registry, no licence |

Also checked and set aside: [vidpy](https://pypi.org/project/vidpy/) 0.2.1 (MIT, 2023, wraps MLT — and **MLT is LGPL-2.1 with GPL plugins**, an unlabelled hazard of the same family); [auto-editor](https://pypi.org/project/auto-editor/) 29.3.1 (Unlicense, 2025-11-04) which makes *cut* decisions and is therefore explicitly out of `looks`' scope per the kickoff; [videogrep](https://pypi.org/project/videogrep/) 2.3.0, whose licence is **"Anti-Capitalist"** — a non-OSI, non-commercial licence, and a perfect illustration of why an automated tier check beats reading fields by eye; [pyffmpeg](https://pypi.org/project/pyffmpeg/) 2.5.2.3.2; [videoflow](https://pypi.org/project/videoflow/) 0.2.10 (MIT, 2020, a general dataflow DAG for video — abandoned).

**The two columns that matter are unanimous.** Twelve libraries, twelve `No` for a named-effect registry, twelve `None` for licence awareness. The positioning claim survives contact with the evidence.

---

## 2. Colour grading and LUT libraries

| Name | Version observed | Last release | Licence | Reads `.cube`? | **Writes `.cube`?** | Generates a gradient-map LUT? |
|---|---|---|---|---|---|---|
| [colour-science](https://pypi.org/project/colour-science/) | 0.4.7 | 2025-12-06 | **BSD-3-Clause** | Yes | **Yes** — `colour.write_LUT` / `write_LUT_IridasCube`; also Cinespace `.csp`, Sony `.spi1d`/`.spi3d` [3] | No |
| [pillow-lut](https://pypi.org/project/pillow-lut/) | 1.1.0 | 2025-09-02 | MIT | Yes (`load_cube_file`) | **No** (read-only per its docs [4]) | No — `rgb_color_enhance` is parametric (exposure/contrast/vibrance/gamma), not a gradient map |
| [lut-maker](https://pypi.org/project/lut-maker/) | 0.1.1 | **2016-11-10** | MIT | — | Yes (Adobe Cube) | No. Dead: 10 years, pre-`python3` era |
| [OpenColorIO](https://pypi.org/project/opencolorio/) | 2.5.2 | 2026-05-13 | BSD-3-Clause | Yes | Yes | No — it is a *colour-management* config system, a much heavier commitment |
| [colorio](https://pypi.org/project/colorio/) | 0.12.18 | 2023-03-08 | **Other/Proprietary** (classifier) | — | — | No. Licence classifier alone disqualifies it without review |

**Three conclusions.** First, **`colour-science` is the LUT-authoring dependency** — BSD-3-Clause, actively maintained (last commit 2026-08-23), and the only surveyed library that can *write* an Iridas/Resolve `.cube`, which is what ffmpeg's `lut3d` consumes. Second, **`pillow-lut` cannot feed ffmpeg**: it produces a Pillow `Color3DLUT` object and does not serialise to `.cube`, so it is a dead end for the shell-out architecture. Third, and most useful: **nothing surveyed generates a gradient-map LUT** — a ramp from a dark anchor to a light anchor, sampled into a 3D lattice. That is exactly the Que Calor vehicle, and it has no prior art to copy. It is ~40 lines over `numpy` + `colour.write_LUT`, and it is a genuine, if small, contribution.

One licence note that matters for the Que Calor chain specifically: **OpenCV is Apache-2.0 and `pyrMeanShiftFiltering` is in the free core.** Verified locally on `opencv-contrib-python` 4.13.0.92 (`cv2.__version__ == '4.13.0'`), whose build reports `Non-free algorithms: NO`. The flattener is commercially safe; the constraint in this chain is entirely on the ffmpeg side.

---

## 3. Named-effect registries and plugin manifests — does *anything* carry a licence tier?

This was the question with the most expected upside, and the answer is a clean, useful negative in every plugin-manifest format, with one decisive exception that is not a plugin format at all.

| System | Manifest / descriptor | Licence field in the manifest? | Notes |
|---|---|---|---|
| **Frei0r** | `f0r_plugin_info_t`: `name`, `author`, `plugin_type`, `color_model`, `frei0r_version`, `major_version`, `minor_version`, `num_params`, `explanation` [5] | **No** | Expected to be the best candidate; it is not. It needs no field because the whole collection is GPL — and note FFmpeg puts `frei0r` in `EXTERNAL_LIBRARY_GPL_LIST`, so `--enable-frei0r` *requires* `--enable-gpl` [1] |
| **OpenFX (OFX)** | `kOfxPropLabel`, `kOfxPropVersion`, `kOfxPropPluginDescription`, `kOfxImageEffectPluginPropGrouping`, `kOfxImageEffectPluginPropObsolete` … [6] | **No** | The other expected candidate. No `kOfxPropLicense` exists. OFX is a commercial-plugin API where licensing is handled out-of-band, per-vendor |
| **ISF** (Interactive Shader Format) | `ISFVSN`, `VSN`, `DESCRIPTION`, `CATEGORIES`, `INPUTS`, `PASSES`, `IMPORTED` [7] | **No** | `CREDIT` is attribution, not a licence |
| **G'MIC** | `#@gui` filter definitions | **No** | Project-wide **CeCILL-2.1** (copyleft); the `gmic` PyPI binding 3.6.3.post1 carries that classifier |
| **OBS Studio** | `obs_source_info` struct | **No** | OBS is GPL-2.0 project-wide |
| **VapourSynth** | plugin namespace/registration | **No** | Core is **LGPL-2.1-or-later** (v79, 2026-08-07); plugins vary and are unlabelled |
| **DaVinci Resolve DCTL** | `.dctl` source with `DEFINE_UI_PARAMS` | **No** | Proprietary host; no metadata block for terms |
| **FFmpeg `configure`** | `LICENSE_LIST`, `EXTERNAL_LIBRARY_GPL_LIST`, `EXTERNAL_LIBRARY_NONFREE_LIST`, `EXTERNAL_LIBRARY_VERSION3_LIST`, per-filter `<name>_filter_deps="gpl"` [1] | **YES — and it refuses** | See below. This is the shape to steal |

### FFmpeg's `configure` is the prior art `looks` has been looking for

FFmpeg n8.1's `configure` declares three tiers and enforces them with a hard failure [1]:

```sh
LICENSE_LIST="
    gpl
    nonfree
    version3
"

die_license_disabled() {
    enabled $1 || { enabled $v && die "$v is $1 and --enable-$1 is not specified."; }
}

map "die_license_disabled gpl"      $EXTERNAL_LIBRARY_GPL_LIST $EXTERNAL_LIBRARY_GPLV3_LIST
map "die_license_disabled version3" $EXTERNAL_LIBRARY_VERSION3_LIST $EXTERNAL_LIBRARY_GPLV3_LIST
map "die_license_disabled nonfree"  $HWACCEL_LIBRARY_NONFREE_LIST
```

Every element of `looks`' design is present: a **per-component tier**, a **caller-declared ceiling** (`--enable-gpl`), a **refusal rather than a warning** (`die`), and a **third tier above copyleft** — `nonfree`, which sets `license="nonfree and unredistributable"` and means *you may not ship the artefact at all*. That last tier is worth adopting verbatim: it is not "copyleft", it is "no redistribution", and collapsing the two loses the distinction that matters most commercially.

### Measured: which ffmpeg filters actually require GPL

I measured this two ways and reconciled them, because the tier table is the load-bearing content of `looks` and an inherited list would be a future bug.

**Empirically**, by diffing the filter list of a GPL build against an LGPL build on this machine: homebrew ffmpeg 8.1 (`--enable-gpl --enable-version3`, libavfilter 11.14.100, 481 filters, self-reports "GNU General Public License … version 3") against PyAV 16.0.1's vendored libavfilter 11.4.100 (self-reports `LGPL version 3 or later`, 447 filters). The difference is 35 filters.

**Authoritatively**, by extracting `<name>_filter_deps="…gpl…"` from FFmpeg's own n8.1 `configure` [1]: 33 filters.

**The two reconcile exactly.** 32 appear in both. The 3 empirical-only entries are build-option and version artefacts, not licence ones — `libvmaf` (PyAV simply did not enable it; libvmaf is BSD-2-Clause-Patent), `scale_vt` (VideoToolbox, a macOS build option), and `premultiply_dynamic` (present in 11.14, absent in 11.4). The 1 configure-only entry is `boxblur_opencl`, not built here.

The 32 confirmed GPL-gated filters, as of **FFmpeg n8.1**:

`blackframe`, `boxblur`, `colormatrix`, `cover_rect`, `cropdetect`, `delogo`, **`eq`**, `find_rect`, `fspp`, `histeq`, `hqdn3d`, `interlace`, `kerndeint`, `mcdeint`, `mpdecimate`, `mptestsrc`, `nnedi`, `owdenoise`, `perspective`, `phase`, `pp7`, `pullup`, `repeatfields`, `sab`, `signature`, `smartblur`, `spp`, `stereo3d`, `super2xsai`, `tinterlace`, `uspp`, `vaguedenoiser`

**`eq` is the one that will bite.** It is ffmpeg's brightness/contrast/saturation/gamma filter — the single most obvious thing a stylization or normalisation facade offers — and it is GPL-only. Verified present in the GPL build and absent from the LGPL build. The permissive substitutions are all available in both builds: `colorlevels`, `curves`, `colorbalance`, `colorcorrect`, `colorchannelmixer`. **This is `looks`' first real tier entry, and its first real substitution rule.** Equally worth stating: the entire Que Calor chain is clean — `lut3d`, `lutrgb`, `format` and `scale` are all present in the LGPL-3 build, so the validated look carries no copyleft obligation on the filter side.

---

## 4. The licence hazards, re-verified first-hand — and one correction to the brief

The kickoff's two "never depend on this" rulings are **both correct in their conclusion**, but the `av` one is wrong about the mechanism, and the true mechanism is more troubling than the stated one.

**`imageio-ffmpeg` 0.6.0 — confirmed exactly as briefed.** Its wheel metadata says `BSD-2-Clause`. The binary it ships, run locally, is `ffmpeg-macos-aarch64-v7.1`, and `-version` reports it built with **`--enable-gpl`** (plus `--enable-libx264 --enable-libx265`). A permissively-labelled wheel that redistributes a GPL binary. And because `moviepy` 2.2.1 hard-depends on `imageio_ffmpeg>=0.2.0`, and `burns` hard-depends on `moviepy`, **`pip install burns` redistributes a GPL ffmpeg binary today** — verified by reading `burns/pyproject.toml` (`dependencies = ['numpy', 'moviepy', 'pillow']`). The brief's claim stands, first-hand.

**`av` — the conclusion holds, the stated reason does not.** The brief says the wheel "bundles libx264/libx265 GPL-2.0+ dylibs under BSD-3 metadata". Bundling and metadata are both confirmed on the installed `av` 16.0.1: `.dylibs/` contains `libx264.165.dylib` and `libx265.215.dylib`; `otool -L` shows `libavcodec.62.11.100.dylib` **hard-links both** via `@loader_path`; `av.codec.Codec('libx264', 'w')` opens successfully; and the dist-info declares `License-Expression: BSD-3-Clause` while shipping **no GPL licence text at all** — only PyAV's own `LICENSE.txt` and `AUTHORS`.

But the bundled ffmpeg is **not** a GPL build. Its configuration string contains `--enable-version3`, **not `--enable-gpl`** (zero occurrences of `--enable-gpl` across all seven bundled `libav*`/`libsw*` dylibs), and every library self-reports `license: 'LGPL version 3 or later'`. The control confirms the test is meaningful: homebrew's `--enable-gpl` ffmpeg 8.1 self-reports GPL-3 under `ffmpeg -L`.

**So the actual situation is an internally inconsistent build**: libraries claiming LGPL-3 that link x264 and x265, both **GPL-2.0-or-later**, in a wheel labelled BSD-3-Clause that carries no copyleft notice. FFmpeg's own `configure` would refuse this — `libx264` and `libx265` are in `EXTERNAL_LIBRARY_GPL_LIST` and `die_license_disabled` fires without `--enable-gpl` [1] — so the vendored build reached its state by some route that bypassed that guard. **Do not depend on `av`, for a stronger reason than the brief gives.** The route by which PyAV's build bypasses `configure`'s guard is **unverified**; I did not read PyAV's build scripts, and the question of whether this is deliberate, a packaging accident, or something I have misread deserves an upstream issue rather than an assertion here.

**One further hazard the brief does not mention.** `ultralytics` 8.4.75 is installed (AGPL-3.0, as briefed), but so is `opencv-contrib-python` — and `mixing`, whose geometry tier `looks` inherits, declares it. The contrib wheel is Apache-2.0 and reports `Non-free algorithms: NO`, so it is clean; but it is clean *because of a build flag*, not because of the package name, and that is precisely the class of fact a tier ledger should record rather than re-derive.

---

## 5. "Declarative video effect spec, separable from execution" — is it taken?

**Nearly, once, and the near-miss is instructive.** `ffmpeg-python` genuinely separates specification from execution: `ffmpeg.compile()` and `get_args()` build the full argv from a filter DAG **without running anything** [2]. That is real, and `looks` should not pretend otherwise.

Three things stop it from being what `looks` needs, and each one names a requirement:

1. **The spec is a Python object graph, not data.** `InputNode`/`FilterNode`/`OutputNode` instances wired by edges — there is no JSON serialisation and no way to round-trip a graph [2]. A `Look` that cannot be persisted cannot be diffed against last week's, stored as a `lacing` annotation, or attached to a provenance record. `falaw.Plan`'s discipline — the spec is *data*, and inspecting it costs nothing — is the differentiator.
2. **There is no vocabulary.** You name ffmpeg filters directly, so the abstraction leaks entirely: there is no `"posterise"`, only `lutrgb` with the right arguments. No registry means no substitution rule, which means no way to answer "give me this look, permissively".
3. **It is unmaintained.** Last release 2019-07-06; last commit 2022-07-11.

Beyond that: `movis` has a composition model but no registry and no serialisable plan; `videoflow` (MIT, 2020) is a general dataflow DAG for video and is abandoned; OFX and ISF are *plugin* interfaces, where the spec is compiled code rather than data. **Nothing found combines a serialisable pure-data effect spec with a named-effect registry, and nothing at all adds a licence tier.** The niche is genuinely open.

---

## 6. What `looks` should steal

- **FFmpeg's three-tier licence vocabulary and its refusal semantics** [1]. `LICENSE_LIST="gpl nonfree version3"` maps almost directly onto what `looks` needs, and the `nonfree` / "unredistributable" tier is the one most likely to be forgotten if the design starts from "permissive vs copyleft". Steal `die_license_disabled`'s shape too: the ceiling is declared once by the caller, and every component is checked against it, and exceeding it *fails*.
- **The measured GPL filter list in §3 as the seed of the tier table** — 32 names, version-anchored to FFmpeg n8.1, reconciled from two independent sources. Re-derive it per ffmpeg version rather than freezing it; the extraction is one `grep` over `configure`.
- **The substitution rule as first-class**, not a footnote. `eq` → `colorlevels`/`curves` is the motivating case: a facade that only *refuses* is much less useful than one that refuses *and names the permissive equivalent*.
- **`ffmpeg-python`'s `compile()`/`get_args()` split** [2] — the right seam, wrong data type. Keep the seam, make the spec serialisable.
- **`colour-science` for LUT authoring** [3] — BSD-3-Clause, maintained, writes Iridas `.cube`. Optional extra, never a hard dependency.
- **Frei0r's and ISF's parameter descriptors** [5,7] as the shape for `Effect` parameter metadata (name, type, explanation) — they are good at the part they solve, which is describing a knob.

## 7. What `looks` genuinely adds

- **A per-effect licence tier enforced at call time.** FFmpeg enforces at *build* time, which is the wrong moment for anyone who did not compile their own ffmpeg — and on this machine, homebrew's GPL build means every filter is silently available. No Python library does this at all.
- **A named-effect vocabulary with a licence-aware substitution rule.** `"posterise"` and `"flatten"` as names, resolving to different backends under different ceilings. Twelve wrappers, zero registries.
- **A serialisable pure-data `Look`.** Inspectable, diffable, persistable, costable before execution — the `falaw.Plan` discipline applied to stylization. `ffmpeg-python` gets the seam right and the data type wrong; everything else does not attempt it.
- **Per-clip parameter resolution.** The measured Que Calor finding — an effect's parameters must resolve against the clip they apply to, and the right auto-rule normalises the *output* across sources — has **no analogue anywhere surveyed**. Every system here treats an effect as a fixed configuration applied uniformly. This may be `looks`' most original idea, and it is the one with a measurement behind it.
- **A gradient-map 3D LUT generator.** Small, absent from PyPI, and the vehicle the first real look already needs.
- **Honest licence metadata about its own dependency tree**, in a field where `av` ships GPL-linked binaries under BSD-3, `imageio-ffmpeg` ships a GPL binary under BSD-2, `ffmpegio` is GPL-2.0, `gmic` is CeCILL-2.1, and `videogrep` is "Anti-Capitalist" — none of it visible without going and looking, which is the whole argument for the package.

---

## 8. Explicitly unverified

Marked so that none of these is mistaken for a measured fact.

- **How PyAV's vendored ffmpeg build links x264/x265 without `--enable-gpl`.** The *outcome* is verified (linked, openable, LGPL-3 self-report, BSD-3 metadata, no GPL text). The mechanism is not — I did not read PyAV's build scripts or CI.
- **`static-ffmpeg` 3.0's binary build flags.** Its metadata is MIT and it ships binaries; I did not download and run one. Treat as a hazard of the `imageio-ffmpeg` family until checked.
- **Whether `pillow-lut` can write `.cube`.** Its docs describe reading only [4]; I did not read its source. The negative is from documentation, not code.
- **The `pp` (libpostproc) filter's gating.** Absent from both builds here, so I could neither measure it nor extract a `pp_filter_deps` line. libpostproc is GPL, but I am not asserting the filter's gate.
- **`vidpy`/MLT's licence surface.** MLT is LGPL-2.1 with GPL plugins by reputation; not verified here.
- **Exhaustiveness.** PyPI has no usable search API; the candidate list came from the brief plus name probing. There may be wrappers I did not find — though twelve unanimous results make the conclusion robust to a few more.
- **Frei0r's own licence.** The header carries no SPDX declaration [5]; the project is described as GPL, which I did not verify at file level.

---

## REFERENCES

1. [FFmpeg `configure`, tag n8.1](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1/configure) — `LICENSE_LIST`, `EXTERNAL_LIBRARY_GPL_LIST`, `EXTERNAL_LIBRARY_NONFREE_LIST`, `EXTERNAL_LIBRARY_VERSION3_LIST`, `die_license_disabled`, per-filter `*_filter_deps`. Fetched 2026-09-02.
2. [ffmpeg-python `_run.py`](https://github.com/kkroening/ffmpeg-python/blob/master/ffmpeg/_run.py) — `get_args`, `compile`, `run`; node-graph model. Package version 0.2.0.
3. [colour-science LUT API reference](https://colour.readthedocs.io/en/develop/reference.html#luts) — `read_LUT`/`write_LUT`, `write_LUT_IridasCube`, `LUT3D`. Package version 0.4.7.
4. [pillow-lut-tools](https://github.com/homm/pillow-lut-tools) — `load_cube_file`, `rgb_color_enhance`, `transform_lut`. Package version 1.1.0.
5. [frei0r.h](https://raw.githubusercontent.com/dyne/frei0r/master/include/frei0r.h) — `f0r_plugin_info_t`, `f0r_param_info_t`.
6. [OpenFX `ofxImageEffect.h`](https://raw.githubusercontent.com/AcademySoftwareFoundation/openfx/main/include/ofxImageEffect.h) — plugin property constants.
7. [ISF specification](https://github.com/mrRay/ISF_Spec) — top-level JSON attributes.
8. [PyPI JSON API](https://pypi.org/pypi/) — all version, release-date and licence-classifier data in §1 and §2, fetched 2026-09-02.
9. [GitHub REST API `/repos/{owner}/{repo}/commits`](https://docs.github.com/en/rest/commits/commits) — all last-commit dates, fetched 2026-09-02.

### Local measurements (reproducible on this machine, 2026-09-02)

- `ffmpeg -version` / `ffmpeg -L` → homebrew ffmpeg **8.1**, `--enable-gpl --enable-version3`, self-reports GPL-3; libavfilter 11.14.100; 481 filters.
- `av._core.library_meta` on **PyAV 16.0.1** → libavfilter 11.4.100, `license: 'LGPL version 3 or later'`; 447 filters; configuration string contains `--enable-version3`, `--enable-libx264`, `--enable-libx265`, and **no** `--enable-gpl`.
- `otool -L .dylibs/libavcodec.62.11.100.dylib` → `@loader_path/libx264.165.dylib`, `@loader_path/libx265.215.dylib`.
- `imageio_ffmpeg.get_ffmpeg_exe()` → `ffmpeg-macos-aarch64-v7.1`, built `--enable-gpl`; package **0.6.0**, metadata BSD-2-Clause.
- `cv2.getBuildInformation()` → OpenCV **4.13.0**, `Non-free algorithms: NO`; `opencv-contrib-python` 4.13.0.92, Apache-2.0.

---

## Adversarial review (2026-09-02)

Every load-bearing claim was re-verified independently — commands re-run, URLs re-fetched, licence *texts* read rather than metadata fields. The note's central positioning claim survives. Five things are wrong, two of them in the dangerous direction (false permission), and one declared negative is refuted. No Python was proposed in the note, so there was nothing to execute.

### Refuted — false permission (fix before the tier table is written)

**R1. The "one grep over `configure`" recipe misses five GPL-gated filters.** §6 and §3 tell the reader to seed the tier table by grepping `<name>_filter_deps="…gpl…"`. Five filters are GPL-gated *indirectly*, through `EXTERNAL_LIBRARY_GPL_LIST`, and carry no literal `gpl` in their deps line:

```
frei0r_filter_deps="frei0r"              # frei0r      -> EXTERNAL_LIBRARY_GPL_LIST
frei0r_src_filter_deps="frei0r"
rubberband_filter_deps="librubberband"   # librubberband -> ditto
vidstabdetect_filter_deps="libvidstab"   # libvidstab    -> ditto
vidstabtransform_filter_deps="libvidstab"
```

`dyne/frei0r`'s `COPYING` is **GNU GPL version 2**, verified at file level (which also closes §8's "Frei0r's own licence — unverified"). `vidstabtransform` is stabilisation — a plausible *normalisation* effect for this package — and the proposed recipe would tier it permissive.

Worse, the two "independent" methods share this exact blind spot, so the "reconcile exactly" result is not the corroboration it reads as: homebrew's 8.1 enables none of frei0r/libvidstab/librubberband (`configuration:` line checked), so the empirical GPL-vs-LGPL diff **cannot** see them either. Both methods are grepping the same list.

**R2. `static-ffmpeg` 3.0 ships no binaries.** The table calls it a "**Licence hazard** (ships binaries; build flags **unverified**)". Its only distribution is `static_ffmpeg-3.0-py3-none-any.whl`, **7,927 bytes, 10 files, all pure Python** (`unzip -l`). `static_ffmpeg/run.py` downloads a zip at *runtime* from `https://github.com/zackees/ffmpeg_bins/raw/main/v8.0/{win32,darwin,darwin_arm64,linux,linux_arm64}.zip`. Fetch-at-runtime and redistribute-in-wheel are materially different redistribution postures — which is a distinction this package exists to make — so the row is wrong on its premise, not merely unverified. (Version-anchor while correcting it: those binaries are the `v8.0` set.)

### Refuted — a declared negative that is not a negative

**R3. OpenFX *does* carry call-time licence refusal semantics.** §3 says "No `kOfxPropLicense` exists. OFX is a commercial-plugin API where licensing is handled out-of-band, per-vendor." The spec disagrees, in `ofxImageEffect.h` (AcademySoftwareFoundation/openfx `main`) and `ofxCore.h`:

- `kOfxImageEffectPropBehaviourWhenUnlicensed` — set by the **host**, i.e. a caller-declared ceiling, delivered in the `inArgs` of `kOfxImageEffectActionRender`.
- `kOfxUnlicensedFail` → "plug-in should return `kOfxStatUnlicensed` and may do this **without any rendering**" — a refusal.
- `kOfxUnlicensedContinue` → render a watermark and return `kOfxStatUnlicensed` — a warning.
- Property **unset** → "plug-in should render an image … and return `kOfxStatOK`" — *unknown = permit*.
- `kOfxStatUnlicensed ((int) 15)` in `ofxCore.h`.

This is seat/commercial licensing rather than copyright tiering, so the note's headline (no per-effect *copyleft* tier in any plugin manifest) stands. But the mechanism the note claims as `looks`' novelty — "moving it from build time to **call** time" — already exists in OFX at render time, with the refuse/warn dichotomy explicit. The right framing is a *contrast*, and a strong one: OFX defaults unknown to permit; `looks` defaults unknown to refuse. Claiming the prior art is absent is weaker than naming it and inverting its default.

### Refuted — smaller

**R4. §8's "`pp` (libpostproc) filter gating — unverified" is a non-question.** FFmpeg n8.1's `configure` contains **zero** occurrences of the string `postproc`; the only `pp*` match is `pp7_filter_deps="gpl"`. libpostproc and the `pp` filter are gone from n8.1. `pp` is absent from both builds here because it no longer exists, not because of a build option.

**R5. The ISF `CREDIT` detail is not in the cited source.** The negative is confirmed (no licence key among the top-level attributes in `mrRay/ISF_Spec`'s README), but `grep -c CREDIT README.md` = **0**. The parenthetical "`CREDIT` is attribution, not a licence" came from somewhere else and should be re-sourced or dropped.

**R6. Recommendation 7 is already stale.** `.gitignore` now carries a hand-written comment explicitly rejecting the template's `docs/*`, and `git check-ignore docs/research/01_prior_art_oss.md` exits 1 — the notes are not ignored.

### Confirmed first-hand

- **FFmpeg n8.1 `configure`** (SHA-256 `28edfaee…b45f4`, 8840 lines): `LICENSE_LIST="gpl nonfree version3"` at line 2200; `die_license_disabled()` at 4759; the three `map` lines at 4767/4768/4771. Verbatim as quoted.
- **The 32/33/35/3/1 reconciliation reproduces exactly.** `configure` grep → 33 lines; homebrew 8.1 → 481 filters; PyAV 16.0.1 `libavfilter` 11.4.100 → 447; `comm` → **32 in both**, empirical-only = `libvmaf` / `premultiply_dynamic` / `scale_vt`, configure-only = `boxblur_opencl`. Every number in §3 is right (subject to R1).
- **`eq` is GPL-only; the substitutes are in both builds.** `eq` PRESENT in homebrew, **absent** from PyAV's LGPL libavfilter. `colorlevels`, `curves`, `colorbalance`, `colorcorrect`, `colorchannelmixer` present in both. So are `lut3d`, `lutrgb`, `scale`, `format` — the Que Calor chain is clean, as claimed.
- **PyAV `av` 16.0.1, all four legs.** `libavcodec` configuration string contains `--enable-version3 --enable-libx264 --enable-libx265` and **no** `--enable-gpl`; all seven libs self-report `LGPL version 3 or later`; `.dylibs/` holds `libx264.165.dylib` + `libx265.215.dylib` and `otool -L libavcodec.62.11.100.dylib` shows both via `@loader_path`; `av.codec.Codec('libx264','w')` and `('libx265','w')` both open; `License-Expression: BSD-3-Clause`, and `av-16.0.1.dist-info/licenses/` holds only `LICENSE.txt` + `AUTHORS.*` — no GPL text. The correction to the brief's mechanism is right, and the mechanism question is correctly left to an upstream issue.
- **`imageio-ffmpeg` 0.6.0 → `ffmpeg-macos-aarch64-v7.1`, `--enable-gpl` present, `--enable-version3` absent**; metadata `BSD-2-Clause`. `moviepy` 2.2.1 `Requires-Dist: imageio_ffmpeg>=0.2.0` (unconditional). `burns` 0.0.9 `Requires-Dist: moviepy` (unconditional). The chain holds.
- **All 23 PyPI rows in §1 and §2** re-fetched: versions, upload dates and licence fields match, including `ffmpegio` `GPL-2.0 License` + GPLv2 classifier, `gmic` CeCILL-2.1 classifier, `videogrep` `Anti-Capitalist` + `License :: Other/Proprietary License`, `colorio` `Other/Proprietary`.
- **Licence *texts*, not fields**: `colour-science` and `OpenColorIO` are genuine 3-clause BSD (all three clauses read); `ffmpeg-python` is genuine Apache-2.0.
- **`pillow-lut` cannot write — now verified at source, not from docs.** Its entire public API is `identity_table`, `rgb_color_enhance`, `load_cube_file`, `load_hald_image`, `amplify_lut`, `resize_lut`, `sample_lut_cubic`, `sample_lut_linear`, `transform_lut`. No writer. §8 can drop that item.
- **`colour-science` writes Iridas `.cube`** — `write_LUT_IridasCube` imported and re-exported in `colour/io/luts/__init__.py`, and dispatched from `write_LUT`'s format table.
- **`f0r_plugin_info_t` has nine fields and no licence field**, and `frei0r.h` carries no SPDX line. Exactly as described.
- **OpenCV**: `opencv-contrib-python` 4.13.0.92 / `opencv-python` 4.12.0.88 / `-headless` 4.13.0.92 all `Apache 2.0`; `ultralytics` 8.4.75 `AGPL-3.0`.

### Design objections

**D1 — the note never says what obligation the refusal protects against.** FFmpeg's `gpl` flag governs *linking*, and the licence of the resulting libraries/binary. `looks` **shells out** — it never links, and invoking a GPL program encumbers neither the caller's code nor the program's output. So a per-effect `gpl` tier under a shell-out architecture is a statement about *the ffmpeg build the user must have (and, if they redistribute, must ship)* — and simultaneously an **availability** fact: an `eq` look simply fails on any LGPL build, which is not hypothetical (PyAV's vendored one is exactly that). §7's headline "a per-effect licence tier enforced at call time" needs that sentence, or the person who gets refused cannot act on it.

**D2 — `nonfree` is the wrong tier to adopt "verbatim", and `version3` is missing.** In n8.1, `nonfree` has **zero filter members**: it is `HWACCEL_LIBRARY_NONFREE_LIST` (`cuda_nvcc`, `cuda_sdk`, `libnpp`) plus `EXTERNAL_LIBRARY_NONFREE_LIST` (`decklink`, `libfdk_aac`, `libmpeghdec`) — no video effect anywhere. And FFmpeg's `nonfree` means *unredistributable*, whereas the restricted cases that motivate `looks` (AnimeGANv2, White-box Cartoonization) are **non-commercial-use-only** — freely redistributable, just not sellable. Adopting the vocabulary verbatim mis-tiers precisely the cases the kickoff cites. Meanwhile `version3` *does* have a filter member the note never enumerates — `lensfun_filter_deps="liblensfun version3"` — so the "seed the table from the measurement" recipe yields a table with one tier populated out of three.

**D3 — the refusal model is a compatibility matrix, not a scalar ceiling.** §3 quotes `die_license_disabled` but not line 4770: `enabled gpl && map "die_license_disabled_gpl nonfree" $EXTERNAL_LIBRARY_NONFREE_LIST`, whose message is "*is incompatible with the gpl*". GPL and nonfree are mutually exclusive, not ordered. A single `Look.max_tier` scalar cannot express that.

**D4 — the substitution rule is not parameter-preserving, and the note does not say so.** `eq` exposes `contrast`, `brightness`, `saturation`, `gamma` (+ `gamma_r/g/b`, `gamma_weight`). Measured against the proposed substitutes on this machine: `colorlevels` = per-channel input/output black+white points only (no saturation, no gamma); `colorcorrect` = r/b shadow+highlight spots and `saturation` only; `curves` = curves. **No single permissive filter is a drop-in**, and the closest brightness+saturation filter — `hue` (`b`, `s`), present in *both* builds — is missing from the note's list entirely. A silent substitution therefore produces a *different grade*, which collides head-on with the measured non-negotiable "normalise the OUTPUT across sources": you cannot land clips in family if the commercial-safe path applies a different transfer function than the one that was measured. Substitution must be declared lossy, named in the plan, and ideally opt-in.

**D5 — Recommendation 2's mechanism is incompatible with the non-negotiables, and a cheaper one already exists in the extraction source.** "Re-derive per ffmpeg version by grepping `configure`" requires the FFmpeg *source* — a network fetch or a vendored copy — in a package that declares zero dependencies and shells out to whatever binary is on `PATH`. Combined with "unknown = refusal", a frozen table guarantees a false-refusal treadmill on every ffmpeg release. **Ask the binary instead.** `muvid/visualize/ffmpeg.py` already ships `has_filter` / `require_filter`; `ffmpeg -filters` answers availability, and the binary's own `configuration:` line answers the ceiling. Verified both ways here: homebrew prints `--enable-gpl --enable-version3` and `ffmpeg -L` prints GPLv3; PyAV's config string has `--enable-version3` and no `--enable-gpl`, self-reporting LGPLv3. Two subprocess calls, offline, zero dependencies, self-updating. The static 32-name table should be the *cross-check and the offline fallback*, not the mechanism.

**D6 — the note documents a hazard and an inheritance path and never joins them.** §4 proves `pip install burns` redistributes a `--enable-gpl` ffmpeg 7.1 binary via `moviepy → imageio-ffmpeg`. §1's table separately observes that the geometry tier `looks` inherits from `mixing` "is built on" moviepy. Both are true: `mixing/video/video_util.py:8` and `mixing/video/video_concat.py:35` import moviepy at module top, and `moviepy` is an unconditional dependency in `mixing`'s `pyproject.toml`. So the refactor the kickoff orders **first** would import into a zero-dependency package the exact hazard §4 documents. Neither the tension nor the resolution is stated — the geometry tier has to be rewritten against the ffmpeg CLI (or PIL), or moviepy becomes an extra whose own tier is "pulls a GPL binary".

**D7 — "GPL" is not one tier, and the note's own two measured builds differ.** homebrew 8.1 is `--enable-gpl --enable-version3` → **GPL-3.0-or-later** (`ffmpeg -L` confirms). imageio-ffmpeg's bundled 7.1 is `--enable-gpl` **without** `--enable-version3` → **GPL-2.0-or-later**. That is load-bearing: Apache-2.0 is incompatible with GPLv2-only and compatible with GPLv3. A tier table that collapses the two will give wrong advice to exactly the caller who asked.

