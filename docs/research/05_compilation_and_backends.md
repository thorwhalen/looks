# Compilation semantics: filtergraph construction, colour correctness, and the backend seam

**Date: 2026-09-02** · research note for `looks` · every ffmpeg claim below was produced by running the command shown, on **ffmpeg 8.1 (homebrew, `--enable-gpl --enable-version3`, no `--enable-libzimg`)**, **opencv-python 4.13.0**, **numpy 2.2.6**, macOS 15 / arm64. Nothing here is quoted from documentation I did not execute.

## Verdict

Compile a `Look` to an ordered tuple of **`Stage`s**, where a stage is one of three pure-data shapes — `FilterStage` (an ffmpeg chain fragment), `FrameStage` (a per-frame callable plus the raw pixel format it wants), `RenderedStage` (the muvid escape hatch: a callable from path to path) — and let a **`Backend` Protocol** with two methods (`claims`, `compile`) turn a maximal run of same-backend effects into one stage. `looks` never spawns a process: the tension the brief names ("a per-frame backend inherently implies a pipe, which IS execution") dissolves once you notice that a filter run **adjacent to** a frame stage folds into that stage's own decoder or encoder `-vf` for free, so the que Calor chain (cv2-flatten → `lut3d` → `lutrgb`) compiles to *one* decode/encode pair, which is exactly what `render_v2c.py` does by hand — `looks` emits that pair's argv as data and someone else runs it. Three findings carry the design and each is measured below: (1) **a `Look` never needs `-filter_complex`**, because a simple `-vf` graph accepts labels, `;` and branching, and a second *source* enters through `movie=` or a lavfi source rather than a container input — so the compiled string may reference **no input index**, which is what makes it splice-able into muvid's per-cut `-vf` unchanged; (2) **colour correctness is two independent tags, not one** — on an untagged full-range source, fixing range alone leaves a max channel error of 19/255 and fixing matrix alone leaves 20/255, against 27/255 for fixing neither and 2/255 for fixing both, so `looks` must treat an unknown `ColorContract` the same way it treats an unknown licence tier: a **refusal**, escapable only by an explicit recorded `assume=`; (3) **the raw-frame pipe boundary costs ~4.4 ms/frame at 720p30**, which is ~1.8× the entire `lut3d`+posterise chain it would displace (2.4 ms/frame) and ~7% of a `pyrMeanShiftFiltering` stage (64 ms/frame) — so the cost model is "count the non-filter stages after folding", and a pure-filter `Look` costs zero boundaries. On ordering: `looks` should **validate and warn, never reorder**, on one measured rule — *nothing that resamples or interpolates may follow something that quantises* (posterise-then-LUT yields 96 distinct 5-bit colours against LUT-then-posterise's 51; downscale-after-posterise yields 359 against 77). One finding arrived unbidden and outranks most of the above in consequence: **the cv2 backend is not permissive.** `opencv-python` (every variant, headless included) ships `libx264`, `libx265`, `libpostproc` and `libvidstab` inside `cv2/.dylibs/` under an "Apache 2.0" PyPI metadata field — a GPL redistribution of exactly the class the KICKOFF bans `av` and `imageio-ffmpeg` for. Measured in §3.6 and §A.11; it sets the cv2 backend's tier to `copyleft-binary` and makes the zero-dependency rule load-bearing rather than tidy.

---

## 1. The ffmpeg filtergraph — how effects compose

### 1.1 What muvid already established, and what changes

muvid's `VisualPlan` [4] is the shape to extract:

```python
@dataclass
class VisualPlan:
    inputs: list[list[str]]  # extra ffmpeg input argument groups, numbered from 1
    filters: list[str]  # filter_complex chains, joined with ';' by the renderer
    video: str = "vbg"  # label of the video stream the chains emit
    still: Path | None = None  # escape hatch: the video IS this image
```

Three of those four fields survive the generalisation from audio→video to video→video, and one must not.

`filters: list[str]` survives verbatim — a list of chains joined with `;` is the right representation, and §1.2 shows why the list (rather than one string) is load-bearing. `video: str` survives as an output label. The escape hatch survives, generalised (§3.4).

**`inputs` must not survive.** muvid's plans legitimately add container inputs because muvid *owns the whole invocation* — input 0 is the audio, and a strategy numbering its own inputs from 1 is a contract between two halves of the same package. `looks` owns no invocation at all: a compiled `Look` has to splice into muvid's per-cut `_render_part` [4], into a bare `ffmpeg -i clip.mp4 -vf …`, into the encoder half of a raw-frame pipe, and into whatever reelee does next. Every one of those hosts numbers its own inputs. A `looks`-emitted string containing `[1:v]` is a string that only works in one host, and silently produces the *wrong stream* in another. So:

> **Rule C1 — a compiled filter string references no container input index.** Not `[0:v]`, not `[1:v]`, not `[in]` unless explicitly requested. The graph's single input is the pad it is spliced onto, and any additional source is a filter (`movie=`, `color=`, `haldclutsrc=`, `nullsrc=`), never an input file.

That rule is what makes §1.3's answer to "when is `-filter_complex` required?" come out as *never*.

### 1.2 Simple `-vf` versus `-filter_complex`

The folk rule is "`-vf` is a linear comma chain; anything branching needs `-filter_complex`". **That is wrong**, and the correction matters because it removes the only apparent reason `looks` would need to own the invocation.

A *simple* filtergraph (`-vf` / `-filter:v`) is one with exactly **one input pad and one output pad**. Within that constraint it accepts `;`, labels, and arbitrary branching:

```
$ ffmpeg -hide_banner -loglevel error -y -i src.mp4 \
    -vf "split=2[a][b];[a]hue=s=0[g];[b][g]blend=all_mode=screen" -frames:v 1 -f null -
OK: -vf accepts a branching graph
```

What it refuses is a second *input pad*:

```
$ ffmpeg -hide_banner -loglevel error -y -i src.mp4 -i src.mp4 \
    -vf "[0:v][1:v]blend=all_mode=screen" -frames:v 1 -f null -
[vf#0:0] Simple filtergraph '(null)' was expected to have exactly 1 input and 1 output.
However, it had 2 input(s) and 1 output(s). Please adjust, or use a complex filtergraph
(-filter_complex) instead.
```

So `-filter_complex` is required for exactly three things, and a video→video `Look` needs none of them:

| `-filter_complex` is required when | in scope for `looks`? |
|---|---|
| the graph consumes more than one **container input** (`[1:v]`) | **no** — see §1.4, second sources come from `movie=` |
| the graph emits more than one output stream | **no** — a `Look` is one video in, one video out, by definition |
| the graph crosses stream types (audio → video, e.g. muvid's `showcqt`) | **no** — that is muvid's business, not `looks`' |

> **Rule C2 — `looks` emits simple-filtergraph-compatible output and never `-filter_complex`.** A host that already runs a complex graph (muvid's `xfade` parts, which have two decoders [4]) can still splice a `looks` chain into one of its branches, because a chain with one in and one out is valid in *both* graph kinds. The reverse is not true, which is why the constraint points this way.

The one real consequence: **`;` and `,` do not splice the same way.** `a,b;c` is not a valid chain. So a `FilterStage` must expose its chains as a *list*, and the host joins them with `;` — precisely muvid's `VisualPlan.filters` convention [5]. A single-chain stage with no explicit labels is additionally comma-splice-able into a host's existing `-vf`, which is the common case and the one worth optimising for.

### 1.3 Label allocation

Labels only appear when the graph branches. The allocation rules:

1. **The first filter of the stage takes the implicit input; the last emits implicitly.** Verified that explicit `[in]`/`[out]` also work in a simple graph (`-vf "[in]hue=s=0[out]"` → OK), but they are not needed and naming them costs splice-ability.
2. **Every internal label is namespaced per compile**, e.g. `lk<stage>_<n>`. A host may already own `[a]`, `[bg]`, `[vbg]` — muvid's `_reactive_plan` uses `_bgsrc`, `_fgsrc`, `_viz`, `_bg`, `_bgviz`, `_fg` [5]. A collision is not an error ffmpeg reports usefully; it silently rewires the graph.
3. **Labels never cross a stage boundary.** A `FilterStage` is closed: it consumes one pad, emits one pad, and no label it allocates is visible outside. This is what lets two stages be reordered, dropped by a licence-tier filter, or split across a pipe without rewriting strings.

### 1.4 When an effect needs a second *input*

Three distinct cases, and only one of them is a real second input:

- **A LUT file is an argument, not an input.** `lut3d=file=x.cube` opens the file itself. Confirmed: the filter declares one input pad (`Inputs: #0: default (video)`).
- **A CLUT *image* is a real second pad.** `haldclut` is `VV->V`. So is `blend`, `overlay`, `xpsnr`.
- **A synthetic plate is a source filter**, not an input: `color=`, `noise=`, `perlin=`, `haldclutsrc=`, `nullsrc=`.

Cases two and three both stay inside a simple `-vf` graph, because `movie=` is a *source filter* that opens a file from inside the graph:

```
$ ffmpeg -hide_banner -loglevel error -y -i src.mp4 \
    -vf "movie=hald.png[h];[in][h]haldclut" -frames:v 1 -f null -
OK: haldclut via movie= in -vf

$ ffmpeg -hide_banner -loglevel error -y -i src.mp4 \
    -vf "movie=grain.mkv:loop=0,format=gbrp[g];[in]format=gbrp[b];[b][g]blend=all_mode=softlight:shortest=1,format=yuv420p" \
    -frames:v 5 -f null -
OK

$ ffmpeg -hide_banner -loglevel error -y -i src.mp4 \
    -vf "color=c=red:s=320x180:r=5[c];[in][c]blend=all_mode=multiply:shortest=1" -frames:v 3 -f null -
OK
```

`movie` carries the options a second source needs: `seek_point`, `loop`, `stream_index`, `dec_threads` (from `ffmpeg -h filter=movie`, 8.1).

**Is there a real case in scope for v1?** Yes — two, and both are file-backed second sources rather than second inputs: a **grain / texture / light-leak plate** blended over the clip, and a **Hald CLUT image** as an alternative to a `.cube` file. Both work through `movie=`. So:

> **Recommendation — v1 is single-container-input, and this forecloses less than it looks like.** `looks` never adds an input; it adds sources. What it genuinely forecloses is an effect whose second stream is *computed from the same clip by a different backend* — the foreseeable case being a person/background **matte** produced per-frame in Python and then used by an ffmpeg `maskedmerge` or `blend`. The escape exists and should be written down now so nobody invents a second mechanism later: the matte is a `FrameStage` that writes a sidecar file, and the consuming `FilterStage` picks it up with `movie=<sidecar>`. That costs one intermediate file and keeps rule C1 intact. Note the licence trap that comes with this specific example — person segmentation must **not** reach for `ultralytics` (AGPL-3.0), per the group's standing finding.

### 1.5 `Effect.at` — the timeline, and where it does not exist

`Effect.at` says *where a look applies*, never where a cut is (KICKOFF). For colour effects it compiles directly to ffmpeg's timeline `enable=`:

```
$ ffmpeg -i big.mp4 -vf "lut3d=file=que_calor_b.cube:enable='between(t,2,4)'" -frames:v 300 -f rawvideo -pix_fmt rgb24 -
  t= 0.5s  frame mean = 126.79      <- LUT off
  t= 1.5s  frame mean = 126.89
  t= 2.5s  frame mean = 178.11      <- LUT on
  t= 3.5s  frame mean = 169.63
  t= 4.5s  frame mean = 126.75      <- LUT off
  t= 5.5s  frame mean = 126.87
```

Two constraints follow, both easy to get wrong:

**(a) Not every filter has a timeline.** From `ffmpeg -filters`, the `T` flag: `lut3d`, `lutrgb`, `colorchannelmixer`, `huesaturation`, `eq`, `hue`, `unsharp`, `noise`, `blend`, `overlay`, `haldclut` all carry it — but **`scale` and `crop` do not** (`.. crop V->V`, `.. scale V->V`). So a *geometry* effect cannot be interval-scoped with `enable`; it needs the expression-ramp approach muvid's `_crop_filter` already uses (a clamped linear ramp in the filter's own `t`) [4]. This is direct evidence for the KICKOFF's open question — **geometry-over-time is a different mechanism from colour-over-time, and it already has a home in `burns`.** Do not build a second one here.

**(b) The filter timeline is part-local, not timeline-local.** Input-side `-ss` rebases it to zero:

```
  -ss 0, enable='between(t,0,1)' : frame means at 0.2s,0.8s,1.2s,1.8s = ['178.8','178.8','126.7','126.7']
  -ss 4, enable='between(t,0,1)' : frame means at 0.2s,0.8s,1.2s,1.8s = ['178.8','178.8','126.7','126.7']
```

Identical. So in muvid's per-cut render, where every part is `-ss clip_in -i clip` [4], an `at` expressed in song time or source time is silently wrong by `clip_in` seconds. `looks` must therefore compile `at` against a declared **origin** carried on the `ClipContext`, and the failure mode of getting it wrong is a look that applies to the wrong part of the shot with no error anywhere.

---

## 2. Colour correctness

### 2.1 What `lut3d` actually negotiates

`lut3d` is **RGB-only** as of 8.1. From `-loglevel debug` on a `yuv420p` source:

```
Filter 'Parsed_lut3d_0' formats:
    Pixel formats: rgb24 bgr24 rgba bgra argb abgr 0rgb 0bgr rgb0 bgr0 rgb48le bgr48le
                   rgba64le bgra64le gbrp gbrap gbrp9le gbrp10le gbrap10le gbrp12le
                   gbrap12le gbrp14le gbrp16le gbrap16le gbrpf32le gbrapf32le
[Parsed_lut3d_0] auto-inserting filter 'auto_scale_0' between the filter
                 'graph -1 input from stream 0:0' and the filter 'Parsed_lut3d_0'
[auto_scale_0] picking rgb24 out of 26 ref:yuv420p alpha:0
[auto_scale_0] w:320 h:180 fmt:yuv420p csp:unknown range:unknown sar:1/1
            -> w:320 h:180 fmt:rgb24  csp:gbr     range:pc      sar:1/1
```

`lutrgb` is likewise RGB-only (`picking rgb24 out of 18`). And **adjacent RGB-only filters share one conversion** — the whole `lut3d,lutrgb` chain inserts exactly **one** `auto_scale` (`rg -c "auto-inserting filter 'auto_scale"` → `1`), not one per filter. So a chain of *n* colour effects costs two conversions total, not 2*n*.

### 2.2 The measured trap — and it is two tags, not one

Eight known RGB swatches were encoded losslessly (ffv1) to `yuv420p` and read back through various chains. **On a correctly-tagged source, `lut3d`'s auto-inserted conversion is byte-identical to no filter at all and to an explicit `format=rgb24`** — the "always insert `format=rgb24` before a LUT" folklore buys nothing:

| swatch in | no filter | `lut3d` (auto) | `format=rgb24,lut3d` | `scale=in_range=full,…,lut3d` (WRONG) |
|---|---|---|---|---|
| (0, 0, 0) | (0, 0, 0) | (0, 0, 0) | (0, 0, 0) | **(16, 16, 16)** |
| (16, 16, 16) | (16, 16, 16) | (16, 16, 16) | (16, 16, 16) | **(30, 30, 30)** |
| (64, 32, 16) | (64, 31, 16) | (64, 31, 16) | (64, 31, 16) | **(72, 42, 29)** |
| (128, 128, 128) | (128, 128, 128) | (128, 128, 128) | (128, 128, 128) | (126, 126, 126) |
| (200, 60, 90) | (199, 60, 89) | (199, 60, 89) | (199, 60, 89) | **(189, 67, 93)** |
| (0, 255, 0) | (0, 255, 1) | (0, 255, 1) | (0, 255, 1) | **(12, 237, 13)** |
| (235, 235, 235) | (235, 235, 235) | (235, 235, 235) | (235, 235, 235) | **(218, 218, 218)** |
| (255, 255, 255) | (255, 255, 255) | (255, 255, 255) | (255, 255, 255) | **(235, 235, 235)** |

The damage comes from *asserting the wrong thing*, not from omitting an assertion — which is the opposite of the usual advice, and the reason a blanket "always add `scale=in_range=full`" wrapper is a bug generator.

The dangerous real-world case is a source that carries **no colour tags at all** and is **not** limited-range. Our synthesised `testsrc2` mp4 probes as `color_range=None, color_space=None, color_primaries=None, color_transfer=None` — untagged is normal, not exotic. Taking genuinely full-range bt709 planes, stripping every tag, and reading them back four ways:

| original RGB | default (no tags) | range fixed only | matrix fixed only | **both fixed** |
|---|---|---|---|---|
| (0, 0, 0) | (0, 0, 0) | (0, 0, 0) | (0, 0, 0) | (0, 0, 0) |
| (16, 16, 16) | (0, 0, 0) | (16, 16, 16) | (0, 0, 0) | (16, 16, 16) |
| (64, 32, 16) | (51, 17, 1) | (60, 31, 17) | (54, 19, 0) | (63, 33, 16) |
| (128, 128, 128) | (130, 130, 130) | (128, 128, 128) | (130, 130, 130) | (128, 128, 128) |
| (200, 60, 90) | (197, 33, 84) | (187, 44, 88) | (210, 52, 84) | (199, 60, 88) |
| (0, 255, 0) | (8, 255, 0) | (19, 255, 7) | (0, 255, 0) | (0, 255, 0) |
| (235, 235, 235) | (255, 255, 255) | (235, 235, 235) | (255, 255, 255) | (235, 235, 235) |
| (255, 255, 255) | (255, 255, 255) | (255, 255, 255) | (255, 255, 255) | (255, 255, 255) |

```
max abs channel error,  default (no tags):  27
max abs channel error,        range fixed:  19
max abs channel error,       matrix fixed:  20
max abs channel error,         both fixed:   2      <- residual is 4:2:0 chroma subsampling
```

**Half a fix is barely a fix.** Range and matrix are independent errors that partially mask each other; correcting one moves the error by 7–8 levels out of 27. This is the executable rule the brief asked for, and it is why "unknown colour" has to be a refusal rather than a default.

Through a *linear* chain a 27/255 error is a visible but recoverable grade shift. Through the que Calor **gradient-map LUT** it is not recoverable at all: the LUT keys the output hue on `L*` (`mklut_b.py`: `Ln = clip((L-50)*1.08 + 50 + 2)`, then a lookup into a 256-entry oxblood→cream ramp), so a shadow error of 16 levels selects a *different ramp entry* — a different colour, not a darker one. The V2a→V2b correction was exactly this kind of measurement: the shadow floor was crushing to black at 16.2% of pixels against the reference's 0.3%, and moving the ramp's dark end to `#2E0C18` (L\* 8.22) took the histogram distance from 46.7 to 32.0 pp. A silent 27-level shadow error is the same magnitude of mistake, arriving for free.

### 2.3 Do not emit a bare `format=rgb24`

On an 8-bit source `format=rgb24` before `lut3d` is a harmless no-op (§2.2). On a **10-bit** source it is destructive:

```
# without it — ffmpeg's own negotiation:
[auto_scale_0] picking gbrp10le out of 26 ref:yuv420p10le alpha:0

# with format=rgb24:
[auto_scale_0] w:320 h:180 fmt:yuv420p10le csp:unknown range:tv -> fmt:rgb24 csp:gbr range:pc
```

ffmpeg's negotiation preserves the source's bit depth; hard-coding `rgb24` throws away two bits before a 3D LUT, which is precisely where banding is introduced. So:

> **Rule C3 — emit `format=` only for a reason you can name.** Two legitimate reasons exist, both from muvid's own hard-won comments [5]: `colorchannelmixer` is "a silent no-op on YUV" so a tint needs `format=rgba` before it; and `blend`'s screen mode "must run in *alpha-free* RGB — both YUV and alpha-carrying `rgba` corrupt its colours", so it needs `format=gbrp`. "Because a LUT wants RGB" is **not** a reason: ffmpeg already does it, and better.

### 2.4 What `colorspace` / `zscale` cost — and one of them is not there

```
== zscale / colorspace availability in this build ==
 TS colorspace V->V Convert between colorspaces.
 (no zscale)
== libzimg in configuration? ==
(no libzimg => no zscale)
```

**This machine's ffmpeg 8.1 has no `zscale`.** Homebrew's formula does not `--enable-libzimg`. So every piece of internet advice of the form "use `zscale` for correct colour management" fails silently-ish here (as a graph-parse error, which at least is loud) — and `looks` must gate any `zscale` emission behind a `has_filter` check, exactly as muvid gates `showcqt`/`drawtext` via `require_filter` [3].

Cost, 10 s of 1280×720 (300 frames), best of three, wall clock, `-f null` output:

| chain | time | marginal, per frame |
|---|---|---|
| decode only | 0.14 s | — (baseline) |
| `scale=in_range=tv:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709` | 0.14 s | **0.00 ms** (in == out, swscale takes the copy path) |
| `scale=in_range=full:out_range=tv` (a real conversion) | 0.18 s | 0.13 ms |
| `format=rgb24,format=yuv420p` (RGB round trip) | 0.23 s | 0.30 ms |
| `lut3d=que_calor_b.cube` | 0.75 s | 2.03 ms |
| `lut3d` + `lutrgb` posterise | 0.88 s | 2.47 ms |
| `colorspace=all=bt709:iall=bt601-6-625` | 0.85 s | **2.37 ms** |

> **Rule C4 — declare, don't convert.** Stating the truth with `scale=in_range=…:in_color_matrix=…` is **free** when nothing actually changes, and it is the cheapest place to put the assumption. The `colorspace` filter costs as much as a whole 3D LUT (2.37 vs 2.03 ms/frame) because it does a gamma-correct float conversion — it is a deliberate stage a `Look` may contain, never a hygiene wrapper `looks` inserts on its own.

### 2.5 The encode side: `-colorspace` and `-x264-params` are not interchangeable, and neither alone is right

The house memory records that `-colorspace bt709` *changes encoded planes* and that primaries/trc need `-x264-params`. Both halves verified, and the combination is sharper than either:

```
# same rgb24 swatches -> yuv420p, ffv1 (lossless), 3 tagging variants
p_plain  tags(range,space,prim,trc)=tv,unknown,unknown,unknown   Y of (200,60,90) = 106
p_709    tags=tv,bt709,unknown,unknown                           Y of (200,60,90) =  95
p_601    tags=tv,bt470bg,unknown,unknown                         Y of (200,60,90) = 106
# p_plain and p_601 are byte-identical (same md5) -> the default matrix here is bt601
```

and on the libx264/mp4 path that a delivery actually uses:

```
x_plain     (nothing)                                        range,space,prim,trc = unknown,unknown,unknown,unknown   Y=106
x_cs        -colorspace bt709                                 = tv,bt709,unknown,unknown                              Y= 95
x_full      -colorspace + -color_primaries + -color_trc       = tv,bt709,unknown,unknown   <- prim/trc SILENTLY DROPPED
x_x264only  -x264-params colorprim/transfer/colormatrix=bt709 = tv,bt709,bt709,bt709       Y=106   <- PLANES UNCHANGED
```

So:

- `-colorspace bt709` **changes the pixels** (Y 106 → 95 for one swatch, an 11-level shift) and sets `color_space`. It does **not** set primaries or transfer — and `-color_primaries` / `-color_trc` alongside it are **silently dropped** by the mp4 muxer path.
- `-x264-params colorprim=bt709:transfer=bt709:colormatrix=bt709` sets **all three tags** and **changes no pixels**. Used alone it produces a **mislabelled file**: bt601-encoded planes tagged bt709. A conforming player will apply the wrong matrix. That is worse than untagged, because untagged at least leaves the player's heuristic (which would guess bt601 for SD) correct.
- The correct incantation is **both**, and they are doing two different jobs: `-colorspace` (or an explicit `scale=out_color_matrix=`) decides the *numbers*, `-x264-params` decides the *label*.

`looks` does not own the encode — execution is out of scope (KICKOFF) — so its obligation is to make the requirement **data**: a compiled `Look` carries `output_color: ColorContract`, and the runner is responsible for honouring it in both halves. A `looks`-side helper that renders a `ColorContract` into the two argument groups is fine and useful; a `looks.render()` that runs them is the convenience function the KICKOFF forbids.

### 2.6 The rule, stated as code would state it

> **Rule C5 — unknown colour is a refusal, not a default.** If a `Look` contains any RGB-domain effect and the clip's probe yields `color_range=None` or `color_space=None`, `compile_look` **raises**, naming the two ffprobe fields and the two ways out: measure the source, or pass `assume=ColorContract(matrix="bt709", range="tv")`, which is **recorded in the compiled plan** so a later reader can see that a human asserted it rather than a default having been picked silently. This is the same shape as the licence tier — unknown is a refusal — and the justification is the 27 / 19 / 20 / 2 table in §2.2.

An important nuance: this refusal is **only** owed when an RGB-domain effect is present. A pure-geometry `Look` (`scale`, `crop`, `pad`) touches no matrix and should not be gated on colour tags it does not care about. The gate belongs on the *effect kind*, not on the `Look`.

---

## 3. The backend Protocol

### 3.1 The tension, and how it resolves

The brief states it exactly: a per-frame Python backend implies a decode/encode pipe, which is execution, which `looks` must not own. The resolution is in two moves.

**Move 1 — `looks` emits the pipe *plan*, not the pipe.** A `FrameStage` carries the per-frame callable *and* the exact decoder/encoder argv as data. Nothing spawns. This is the `falaw.Plan` shape applied one level down: falaw's `CallPlan` holds "the *exact* tuple `cached_call_fal(application, arguments)` would take" [7] so a plan can be cache-checked, costed, serialised or executed without ambiguity; a `FrameStage` holds the exact argv a runner would spawn, for the same reasons.

**Move 2 — the pipe is bounded by construction, and that is checkable before it runs.** muvid's invariant is O(1) memory *in cut count*, won after 30-cut OOM kills, and the mechanism is "a constant number of decoders per invocation" — muvid's `xfade` part is the only two-decoder shape and its docstring says TWO is the number that matters [4]. A `FrameStage` declares **exactly one input**, so it cannot violate that invariant; and rule C1 (no container input indices) means a `FilterStage` cannot either. Reproducing the failure muvid fixed, to make the invariant concrete rather than folkloric — peak RSS of one `ffmpeg -filter_complex` with *N* 720p inputs, each run measured in isolation, descending order so a cumulative reading would be exposed:

```
  N=40  peak RSS =     694 MB
  N=24  peak RSS =     482 MB
  N=12  peak RSS =     328 MB
  N=4   peak RSS =     208 MB
  N=1   peak RSS =     143 MB
```

Linear: ≈143 MB + 14 MB per additional 720p input, and ~2.25× that per input at 1080p. Against that, a `FrameStage` pipe running `pyrMeanShiftFiltering` over the same material peaked at **364 MB** and a plain ffmpeg `lut3d` at **377 MB**, both flat in clip length. The pipe is not the memory risk; a graph with an input per cut is.

### 3.2 The types

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
    Literal,
    Mapping,
    Protocol,
    Sequence,
    runtime_checkable,
)

# ---------------------------------------------------------------- vocabulary

Tier = Literal["permissive", "copyleft-binary", "restricted", "unknown"]
"""Licence ceiling. ``unknown`` is a REFUSAL, never a warning (KICKOFF)."""

Kind = Literal["geometry", "tone", "palette", "quantise", "texture", "composite"]
"""What an effect does to pixels. Drives the ONE ordering rule (Sec. 5) and the
colour gate (Rule C5): ``geometry`` alone needs no ColorContract."""


@dataclass(frozen=True)
class ColorContract:
    """The four things that decide what a YUV plane MEANS. ``None`` is UNKNOWN.

    Unknown is never silently defaulted: see Rule C5. Measured justification for
    treating ``matrix`` and ``range`` as independent obligations is Sec. 2.2 —
    fixing one and not the other leaves 19-20/255 of the 27/255 error in place.
    """

    matrix: str | None = None  # "bt709", "bt470bg", ...  (ffprobe color_space)
    range: str | None = None  # "tv" | "pc"              (ffprobe color_range)
    transfer: str | None = None  # ffprobe color_transfer
    primaries: str | None = None  # ffprobe color_primaries
    assumed: bool = False  # True when a human asserted it via assume=

    @property
    def known_for_rgb(self) -> bool:
        """Enough is known to convert to RGB correctly."""
        return self.matrix is not None and self.range is not None


@dataclass(frozen=True)
class ClipContext:
    """What an effect's parameters RESOLVE AGAINST.

    This is the KICKOFF's strongest measured design argument: the Que Calor
    flattening scale had to be per-source (c03 at 0.75/sr40 against 0.5/sr60),
    because a single global setting made the softest source softer still. So a
    parameter is a function of the clip, not a constant at the top of a Look.

    ``measurements`` carries whatever the caller measured (``"laplacian_var"``,
    ``"median_L"``, ...). ``looks`` never measures on its own behalf: measuring
    means decoding, and decoding is execution.
    """

    path: Path | None
    size: tuple[int, int]
    fps: float
    duration: float
    pix_fmt: str
    color: ColorContract
    origin: float = 0.0  # source time of this part's frame 0; see Sec. 1.5
    measurements: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Effect:
    """One named effect, as authored. Pure data, JSON-able, diffable."""

    name: str
    params: Mapping[str, Any] = field(default_factory=dict)
    at: tuple[float, float] | None = None  # WHERE the look applies. Never a CUT.


@dataclass(frozen=True)
class ResolvedEffect:
    """An Effect whose params have been resolved against a specific ClipContext."""

    effect: Effect
    params: Mapping[str, Any]
    kind: Kind
    tier: Tier
    backend: str
```

### 3.3 The three stage shapes

```python
@dataclass(frozen=True)
class FilterStage:
    """A fragment of an ffmpeg filtergraph. Costs no process of its own.

    ``chains`` mirrors ``muvid.visualize.visuals.VisualPlan.filters`` — a LIST,
    joined with ';' by whoever hosts it, because ';' and ',' do not splice the
    same way (Sec. 1.2). A single-chain stage with no labels is additionally
    comma-splice-able into a host's existing ``-vf``, which is the common case.

    Rule C1: no chain here references a container input index.
    """

    chains: tuple[str, ...]
    requires_filters: tuple[
        str, ...
    ] = ()  # gate with has_filter(); zscale may be absent
    input_color: ColorContract | None = None
    output_color: ColorContract | None = None

    @property
    def is_linear(self) -> bool:
        """Can be spliced with a comma into a host chain."""
        return len(self.chains) == 1

    def as_vf(self) -> str:
        return ";".join(self.chains)


@dataclass(frozen=True)
class FrameStage:
    """A per-frame callable over raw pixels, plus the pipe it needs — as DATA.

    ``apply`` is a pure function of one decoded frame. ``looks`` does not call
    it, does not decode, does not encode; it describes the pipe and hands the
    description over. Composing this with its neighbours is Sec. 4's folding.

    ``per_frame_ms`` is ``None`` when unknown, NEVER 0.0 — the group's standing
    cost rule: unknown must be distinguishable from free.
    """

    apply: Callable[["FrameBuffer", "FrameContext"], "FrameBuffer"]
    pix_fmt: str = "bgr24"  # what ``apply`` wants; drives the pipe argv
    size: tuple[int, int] | None = None  # None = the clip's own size
    per_frame_ms: float | None = None
    requires: tuple[str, ...] = ()  # import names, e.g. ("cv2",)


@dataclass(frozen=True)
class RenderedStage:
    """The escape hatch muvid already has, generalised from source to transform.

    muvid's ``resolve_visual`` accepts a strategy that returns "the path of a
    silent video it rendered itself" — the seam for projectM, a headless-browser
    capture, a matplotlib animation. Video->video makes it a FUNCTION of a path
    rather than a producer of one.

    Opaque to ``looks``: it cannot be folded, cannot be reordered, and always
    materialises an intermediate file. That is its price and it is stated here
    rather than discovered.
    """

    render: Callable[[Path, Path], Path]  # (input, output) -> output
    tier: Tier = "unknown"
    realtime_factor: float | None = None  # None = unknown, never 1.0-by-default


Stage = FilterStage | FrameStage | RenderedStage
```

`FrameBuffer` is deliberately left as a protocol-shaped alias rather than `np.ndarray`: `looks` declares **zero hard dependencies** (KICKOFF), so numpy may not appear in a signature that gets imported at module load. In practice it is `numpy.ndarray` of shape `(H, W, C)`, and the type alias is `Any` with a docstring, or a `TYPE_CHECKING`-guarded import.

### 3.4 The Protocol

```python
@runtime_checkable
class Backend(Protocol):
    """Turn a run of same-backend effects into ONE stage.

    Two methods, and the split is what keeps the compiler open-closed: ``claims``
    is the registry's dispatch question, ``compile`` is the work. A backend that
    needs a third method to be expressible is a sign the stage vocabulary is
    wrong, not that the Protocol is too small.
    """

    name: str
    """Registry key — the open-closed seam, muvid's ``register_visual`` shape."""

    tier: Tier
    """The licence ceiling of everything this backend can emit. A backend whose
    tier exceeds ``Look.max_tier`` is not consulted at all, so a restricted
    effect fails at RESOLUTION with a name, not at execution with a stack."""

    def claims(self, effect: ResolvedEffect) -> bool:
        """Can this backend implement ``effect``? Pure, cheap, no I/O."""
        ...

    def compile(self, run: Sequence[ResolvedEffect], clip: ClipContext) -> Stage:
        """Compile a maximal run of claimed effects into one stage.

        Given a RUN rather than one effect on purpose: an ffmpeg backend must
        emit ``lut3d=...,lutrgb=...`` as one chain (one auto_scale conversion,
        Sec. 2.1), and a cv2 backend must fuse several per-frame operations into
        one callable rather than one pipe each.
        """
        ...
```

Three backends satisfy this and they are the three the brief names:

| backend | `tier` | `compile` returns | notes |
|---|---|---|---|
| `"ffmpeg"` | `copyleft-binary` — shells out to a GPL binary, does not link or ship it | `FilterStage` | `lut3d`, `lutrgb`, `eq`, `unsharp`, `colorchannelmixer`, `blend`+`movie=` … |
| `"cv2"` | `copyleft-binary` — **the wheel ships GPL binaries**, see §3.6 | `FrameStage` | `pyrMeanShiftFiltering`, bilateral, any per-frame numpy |
| `"external"` | declared per instance, default `unknown` → refused | `RenderedStage` | projectM, a shader pass, a model that renders a whole file |

The registry is `xdol.Registry`-shaped, per the group's standing pattern, and the `tier` field is what makes the licence ceiling **structural**: a `Look` that names a restricted effect fails when the registry declines to hand out a backend, before any parameter is resolved and long before anything runs.

### 3.5 The compile function

```python
def compile_look(
    look: "Look",
    clip: ClipContext,
    *,
    backends: Mapping[str, Backend] | None = None,
    max_tier: Tier = "copyleft-binary",
    assume: ColorContract | None = None,
    order_check: Literal["warn", "raise", "off"] = "warn",
) -> "CompiledLook":
    """Compile an ordered Look against ONE clip. Pure: opens no process, no file.

    Five steps, in this order, and the order is the point — each one can refuse,
    and refusing early means refusing with a name rather than a stack trace:

    1. RESOLVE   each Effect's params against ``clip`` (the per-source rule).
    2. GATE      on ``max_tier``; an unknown or over-ceiling tier RAISES.
    3. GATE      on colour: any RGB-domain effect with an unknown ColorContract
                 RAISES unless ``assume`` supplies one (Rule C5). The assumption
                 is recorded on the result, not silently applied.
    4. VALIDATE  ordering (Sec. 5). Warns or raises; NEVER reorders.
    5. SEGMENT   into maximal same-backend runs, compile each to a Stage, then
                 FOLD adjacent FilterStages into their neighbouring FrameStage's
                 own pipe (Sec. 4). Folding is what makes the Que Calor chain one
                 process pair instead of three.
    """
    resolved = tuple(_resolve(e, clip) for e in look.effects)

    for r in resolved:
        if r.tier == "unknown" or _rank(r.tier) > _rank(max_tier):
            raise LicenceRefused(
                f"effect {r.effect.name!r} is tier {r.tier!r}; this Look's "
                f"ceiling is {max_tier!r}. Raise the ceiling deliberately with "
                f"Look(max_tier=...), or choose another effect."
            )

    color = _reconcile_color(clip.color, assume)
    if any(_needs_rgb(r) for r in resolved) and not color.known_for_rgb:
        raise ColorUnknown(
            "this Look converts to RGB, but the clip declares "
            f"color_space={clip.color.matrix!r} color_range={clip.color.range!r}. "
            "Measured: getting both wrong costs up to 27/255 per channel and "
            "getting ONE right still costs 19-20. Either measure the source, or "
            'pass assume=ColorContract(matrix="bt709", range="tv") — which is '
            "recorded in the compiled plan so the assumption stays visible."
        )

    _check_order(resolved, policy=order_check)

    stages = tuple(
        backends[run[0].backend].compile(run, clip)
        for run in _runs(resolved, key=lambda r: r.backend)
    )
    return CompiledLook(
        stages=_fold(stages),
        input_color=color,
        output_color=_output_color(stages, color),
        resolved=resolved,
        assumed_color=color.assumed,
    )
```

Note what is *not* in the signature. There is no `output` path, no `run=True`, no `executor`. `CompiledLook` is inert data plus pure callables; the runner walks it. That is the whole discipline, and it is the same one falaw draws between `plan_X(...)` and `execute(plan, ...)` [7].

---

### 3.6 The cv2 backend's tier is NOT permissive — measured

This started as an "unverified, check it" footnote and turned into a first-order finding. The reflex answer — "opencv-python is Apache-2.0, so the cv2 backend is permissive" — is wrong three ways, and the group's standing rule (the licence **text** is the authority, the package metadata field is not) is what catches it.

**Metadata vs. text vs. payload, on the wheels actually installed here** (`opencv-python 4.12.0.88`, `opencv-python-headless 4.13.0.92`, `opencv-contrib-python 4.13.0.92`; macOS arm64; inspected 2026-09-02):

- The **PyPI metadata field** says `License: Apache 2.0`, classifier `License :: OSI Approved :: Apache Software License`, on all three.
- The **`cv2/LICENSE.txt` shipped inside the package** is **MIT** — Olli-Pekka Heinisuo's packaging work, not OpenCV. The field and the file already disagree, and neither is the payload.
- **`cv2/LICENSE-3RD-PARTY.txt`** (177,810 chars) opens with the Apache-2.0 text for the OpenCV binary, then says, verbatim:

  > `FFmpeg is redistributed within all opencv-python packages.`
  > `Libbluray, libgnutls, libnettle, libhogweed, libintl, libmp3lame, libp11,`
  > `librtmp, libsoxr and libtasn1 are redistributed within all opencv-python macOS packages.`
  > `This license applies to the above library binaries in the directory cv2/.`

  followed by the full **LGPL-2.1** text, and later LGPL-3 and MPL-2.0.

And the payload is worse than that paragraph admits. `cv2/.dylibs/` holds **93** shared libraries, among them:

```
libx264.164.dylib          <- GPL-2.0-or-later
libx265.215.dylib          <- GPL-2.0-or-later
libpostproc.58.3.100.dylib <- FFmpeg's postproc: GPL-ONLY
libvidstab.1.2.dylib       <- GPL-2.0+
libass.9.dylib  libbluray.2.dylib  libgnutls.30.dylib  libnettle.8.10.dylib
libhogweed.6.10.dylib  libmp3lame.0.dylib  libsoxr.0.1.2.dylib  libtasn1.6.dylib
libp11-kit.0.dylib         <- LGPL family
libavcodec.61.19.101.dylib libavformat.61.7.100.dylib libavutil.59.39.100.dylib
libswscale.8.3.100.dylib   libswresample.5.3.100.dylib
```

and `otool -L` confirms the bundled `libavcodec` **links them**:

```
$ otool -L cv2/.dylibs/libavcodec.61.19.101.dylib | rg -i "x264|x265|lame"
    @loader_path/libmp3lame.0.dylib
    @loader_path/libx264.164.dylib
    @loader_path/libx265.215.dylib
```

An `libavcodec` linked against x264 is a `--enable-gpl` build, and `libpostproc` is GPL-only in FFmpeg regardless. So **`pip install opencv-python` redistributes GPL-2.0-or-later binaries under an "Apache 2.0" metadata field** — the same class of finding the group already records for `av` (GPL dylibs under BSD-3 metadata) and `imageio-ffmpeg` (an `--enable-gpl` binary), and worse in degree because the header paragraph names only LGPL components.

Three consequences for `looks`, none of them "refuse":

1. **`cv2`'s backend tier is `copyleft-binary`, not `permissive`.** The exposure is *redistribution*, not derivation — `looks` would call Apache-2.0 `imgproc` entry points (`pyrMeanShiftFiltering`, `resize`) through a Python API, and the GPL components are unused codecs sitting in the same directory. That is exactly the framing the group already applies to `pip install burns` pulling a GPL ffmpeg through moviepy → imageio-ffmpeg: **execution and co-location, not infection.** But it is still a redistribution the user did not ask for, and the tier must say so rather than a docstring mentioning it.
2. **"Use headless" does not fix it.** The usual reflex is wrong: `opencv-python-headless`'s own `LICENSE-3RD-PARTY.txt` carries the identical "FFmpeg is redistributed within **all** opencv-python packages" line and the identical LGPL-2.1 text. Headless drops the GUI toolkits, not the codecs. Genuinely avoiding it means building OpenCV with `-DWITH_FFMPEG=OFF` or using a distro package — neither of which is a `pip install` anybody will do.
3. **`looks` core must import `cv2` nowhere at module load**, so that `pip install looks` pulls none of this. That is already the zero-dependency rule; this finding is the reason it is load-bearing rather than tidy, and it is the reason a `looks[cv2]` extra owes a plain sentence in the README about what the extra puts on the user's disk.

A cheerful footnote with no consequence: `cv2/.dylibs/` contains **`libzimg.2.dylib`** — the library this machine's homebrew ffmpeg lacks, which is why `zscale` is unavailable at the CLI (§2.4). It is not reachable from the ffmpeg binary; it is only linked into the wheel's own `libswscale`.

## 4. A plan that mixes backends

### 4.1 The real chain

Que Calor V2c, from `render_v2c.py` [6]: `cv2.pyrMeanShiftFiltering` (at a per-clip scale) → `lut3d=que_calor_b.cube` → `lutrgb` posterise at step 18. One Python stage followed by two ffmpeg stages.

```
Look:      [ flatten(cv2) ]  [ palette(ffmpeg) ]  [ posterise(ffmpeg) ]
             kind=texture      kind=palette         kind=quantise

segment:   run 0 = {cv2}: [flatten]
           run 1 = {ffmpeg}: [palette, posterise]        <- ONE chain, one auto_scale

compile:   FrameStage(apply=_flatten, pix_fmt="bgr24", per_frame_ms=64.0)
           FilterStage(chains=("lut3d=file=que_calor_b.cube,lutrgb=r='trunc(val/18)*18+9':...",))

fold:      the FilterStage is DOWNSTREAM-ADJACENT to the FrameStage, so it becomes
           the FrameStage's own ENCODER -vf. Result: one (decoder, encoder) pair.
```

That folded plan is, argument for argument, what `render_v2c.py` already runs by hand — a decoder emitting `rawvideo bgr24`, a Python loop, an encoder whose `-vf` is `lut3d=…,lutrgb=…`. Which is the point: the compiler is not inventing a shape, it is naming the one that a human arrived at under real pressure.

### 4.2 Folding, stated as a rule

> **Rule C6 — segmenting into same-backend runs is necessary but not sufficient; you must also fold.** A `FilterStage` immediately *before* a `FrameStage` becomes that stage's **decoder** `-vf`. A `FilterStage` immediately *after* one becomes its **encoder** `-vf`. Consecutive `FrameStage`s with the same `pix_fmt` and size fuse into one callable and one pipe. Therefore **the number of raw-frame boundaries is not `len(runs) - 1`** — a naive reading that would have costed the Que Calor chain at two boundaries when it has one.

After folding, the plan is a chain of processes connected by raw pipes, one process per surviving stage. Reordering the same three effects to `[palette, flatten, posterise]` still folds to **one** process pair (the upstream filter run into the decoder, the downstream into the encoder). Only a *second* `FrameStage` separated from the first by a filter run adds a process — and even then the frames flow through a pipe, not a file, so memory stays flat.

`RenderedStage` is the exception and its cost is categorical: it takes a path and returns a path, so it **always** forces a full encode of everything before it and a full decode of everything after. It cannot fold and it cannot be piped.

### 4.3 The cost model

```
boundaries      = (number of stages surviving the fold) - 1
intermediates   = number of RenderedStages          (each = one full encode + one full decode)
pure filter Look -> 1 stage, 0 boundaries, 0 intermediates
```

Measured, 62 frames of 1280×720, `libx264 -crf 16 -preset medium`, best of three:

| pipeline | wall | per frame |
|---|---|---|
| decode → encode, **no filter** (baseline) | 0.28 s | 4.5 ms |
| decode → `lut3d` + `lutrgb` → encode, **all in ffmpeg** | 0.43 s | 6.9 ms |
| decode → **raw pipe → Python no-op → raw pipe** → encode | 0.55 s | 8.9 ms |
| the same pipe running `pyrMeanShiftFiltering` at scale 0.5 | 4.42 s | 71.2 ms (of which 63.9 ms is cv2) |

So:

- **one raw-frame boundary costs ≈ 4.4 ms/frame at 720p30** (0.55 − 0.28, over 62 frames), and it moves **82.9 MB/s** at 720p30 / **186.6 MB/s** at 1080p30 of `bgr24` through a pipe.
- That is **≈1.8× the entire `lut3d`+posterise chain** it would displace (2.4 ms/frame). Which is the quotable form of the rule: *do not cross a backend boundary to do something ffmpeg can already do.*
- But it is only **6.9%** of the mean-shift stage. So when a stage genuinely has no ffmpeg equivalent, the boundary is noise and the argument for a Python backend is unaffected.
- Peak RSS is flat in clip length for both shapes (364 MB for the cv2 pipe, 377 MB for plain ffmpeg), against 143 + 14·N MB for a graph with N inputs (§3.1). **The pipe is bounded; the multi-input graph is not.**

`CompiledLook.cost()` should therefore return a structure, not a number — `(boundaries, intermediates, per_frame_ms_known, per_frame_ms_unknown_stages)` — and per the group's standing rule an unknown per-stage cost is `None`, never `0.0`, and its presence must be visible to whatever gates the render.

---

## 5. Ordering and commutativity

### 5.1 Measured

`lut3d` (the Que Calor gradient map) and an 18-step posterise, on one 320×180 frame, both orders:

```
LUT->posterise vs posterise->LUT      : mean|d|=  4.24  max|d|= 55  differing px=100.0%
  distinct 5-bit colours: LUT->post=  51   post->LUT=  96
```

Downscale to 160×90 before versus after the same colour chain:

```
downscale->colour vs colour->downscale: mean|d|=  2.60  max|d|=122  differing px= 26.8%
  distinct 5-bit colours: geo-first=  77   geo-last= 359
```

Neither pair commutes, and the *shape* of the disagreement is the same in both cases: **a resampling or interpolating operation placed after a quantiser undoes the quantisation.** Posterise-first yields 96 colours because `lut3d`'s tetrahedral interpolation re-spreads them; downscale-last yields 359 because area-averaging neighbouring flat regions manufactures intermediate values. In both cases the *look* — a flat, few-colour cartoon — is the thing being destroyed, which is exactly what the Que Calor reference was chosen for.

This also explains a subtlety already recorded in the KICKOFF: the LUT+posterise stage "normally *adds* apparent sharpness by creating hard edges between flat regions", measured at 205% retained sharpness for c01. That only works if the quantiser is downstream of everything that would smear it, and the per-clip scale fix was in effect a fight over the same principle one stage earlier.

### 5.2 What effects do commute, and why it does not earn a mechanism

Tone effects that are monotone per channel commute with each other only in exact arithmetic; in 8-bit they do not (each rounds). Two `colorchannelmixer`s compose as matrix multiplication and *do* commute up to rounding. A `blend` against a fixed plate commutes with nothing. The honest summary is that **almost nothing commutes in 8-bit**, so a `commutes_with` relation would be a large table whose entries are nearly all `False` — a mechanism that carries no information.

### 5.3 Recommendation

> **`looks` validates, warns, and never reorders.** One rule, with three instances, two of them measured above:
>
> **R1 — a `quantise` effect should be last among the pixel stages.** Warn when any `geometry`, `palette`, or `texture` effect follows a `quantise` one, and put the measured numbers in the message ("posterise before a palette map yields 96 distinct colours where the reverse yields 51; a downscale after a quantiser yields 359 where the reverse yields 77").
>
> Warn, not raise, because posterise-then-LUT is a legitimate *different* look, and 96 colours is not an error — it is a choice someone may have made. Contrast this deliberately with the licence tier and the colour contract, which **raise**: those are questions with a correct answer that the caller cannot see, and this one is a question of taste that the caller can. `Look(order_check="raise")` is available for a caller who wants the stricter reading; `"off"` for one who has measured and disagrees.
>
> **Never reorder.** Order is authorship. A compiler that silently moved a posterise to the end would have produced a *different picture* from the one the author asked for, with nothing in the output saying so — and since the compiled plan is meant to be diffable and persistable (the `falaw.Plan` property this whole design is built on), a plan that does not match its `Look` destroys the one guarantee that makes the plan worth keeping.

One structural exception worth stating so it is not mistaken for a reorder: **a colour-space conversion `looks` inserts to satisfy Rule C3** (muvid's `format=rgba` before `colorchannelmixer`, `format=gbrp` before a screen `blend`) is not a reordering of the author's effects and needs no warning — it is part of compiling one effect, and it belongs inside that effect's chain rather than as a stage of its own.

---

## 6. What this note does not settle

- **Whether `burns` becomes a `looks` backend** (KICKOFF open question). §1.5's finding — that `scale`/`crop` carry no timeline flag, so interval-scoped geometry needs a different mechanism from interval-scoped colour — is evidence *for* keeping geometry-over-time in `burns` and pixel effects here. But `looks` still inherits `mixing/video/video_util.py`'s static geometry tier (`SOCIAL_SIZES`, `resize_to_dimensions`), which is a different thing from a pan. The line I would draw: **static geometry is a `looks` effect (`kind="geometry"`, compiles to `scale`/`crop`/`pad`); geometry that is a function of `t` is a `BurnsPath`.** Not verified against `burns`' actual API surface beyond its `backends.py` docstring [8].
- **The moviepy tension in the inherited geometry tier.** `mixing/video/video_util.py` imports `VideoFileClip, VideoClip, ImageClip, CompositeVideoClip` at module top and `resize_to_dimensions` is written against moviepy clips [13]. `looks` declares zero dependencies. Extracting it therefore means *rewriting* it against `(w, h)` tuples and emitting `scale`/`crop`/`pad` strings, not moving it. That is a bigger job than "a deprecation-free move" implies, and it is worth saying so before someone schedules it as one.
- **Whether the cv2 finding (§3.6) holds on Linux/x86-64 and Windows wheels.** Verified only on the macOS arm64 wheels installed here. The `LICENSE-3RD-PARTY.txt` sentence says "all opencv-python packages" for FFmpeg and "all opencv-python **macOS** packages" for the LGPL list, which implies the platform wheels differ in payload — **unverified** which, and it matters, because CI runs on Linux. Someone should run the same `ls .dylibs` / `otool -L` check (there, `ls *.so*` / `ldd`) on the manylinux wheel before the tier is written into code.
- **Whether the `colorspace` filter's 2.37 ms/frame holds on Linux/x86-64.** Measured on macOS/arm64 only; swscale's SIMD paths differ. All timing numbers here are single-machine.
- **10-bit end-to-end.** §2.3 establishes that ffmpeg's negotiation preserves depth and `format=rgb24` destroys it, but no full 10-bit `Look` was compiled or measured, and the `FrameStage` pixel-format vocabulary above assumes 8-bit `bgr24` (which is what `render_v2c.py` uses). A 10-bit `FrameStage` would need `bgr48le` and a `uint16` frame buffer; **unverified** whether the pipe throughput doubles cleanly.
- **Cache identity.** Nothing here says how a `CompiledLook` hashes. The group's standing rule (nw's invariant 3, falaw's D1 fix) is that a behaviour change must reach the cache key — which for `looks` means the key must cover the LUT file's *content* digest and not its path, the resolved parameters and not the authored ones, and an `impl_version` per backend. Out of scope for this note; must not be out of scope for the first implementation.

---

## Appendix — every command run, with its output

Environment: `ffmpeg version 8.1`, `libavutil 60.26.100`, `libavcodec 62.28.100`, `libavformat 62.12.100`, built `--enable-gpl --enable-version3 --enable-libx264 --enable-libx265 …` and **without** `--enable-libzimg`. `python3` = `~/.pyenv/versions/p12/bin/python3`, `cv2 4.13.0`, `numpy 2.2.6`. macOS 15 (Darwin 24.6.0), arm64.

### A.1 Test material

```bash
ffmpeg -hide_banner -loglevel error -y -f lavfi -i "testsrc2=size=320x180:rate=5" -t 1 \
  -c:v libx264 -crf 12 -pix_fmt yuv420p src.mp4
ffprobe -v error -show_streams -of json src.mp4
# {'pix_fmt': 'yuv420p', 'color_range': None, 'color_space': None,
#  'color_primaries': None, 'color_transfer': None, 'width': 320, 'height': 180, 'nb_frames': '5'}

ffmpeg -hide_banner -loglevel error -y -f lavfi -i "testsrc2=size=1280x720:rate=30" -t 10 \
  -c:v libx264 -crf 16 -preset veryfast -pix_fmt yuv420p big.mp4     # 6,352,944 bytes
ffmpeg -hide_banner -loglevel error -y -i big.mp4 -t 2 -c copy short.mp4   # 62 frames
```

Eight-swatch RGB source (`swatch.rgb24`, 256×32, 3 frames), swatches `(0,0,0) (16,16,16) (64,32,16) (128,128,128) (200,60,90) (0,255,0) (235,235,235) (255,255,255)`; an identity 2×2×2 `.cube`; a swap-R/B 2×2×2 `.cube`; and the real `que_calor_b.cube` (33³) copied from `~/Downloads/que_calor/work/style/`.

### A.2 `lut3d` format negotiation

```bash
ffmpeg -hide_banner -loglevel debug -y -i src.mp4 -vf "lut3d=file=swap_rb.cube" -frames:v 1 -f null -
```
```
Filter 'Parsed_lut3d_0' formats:
    Pixel formats: rgb24 bgr24 rgba bgra argb abgr 0rgb 0bgr rgb0 bgr0 rgb48le bgr48le
    rgba64le bgra64le gbrp gbrap gbrp9le gbrp10le gbrap10le gbrp12le gbrap12le gbrp14le
    gbrp16le gbrap16le gbrpf32le gbrapf32le
[auto_scale_0] w:iw h:ih flags:'' interl:0
[Parsed_lut3d_0] auto-inserting filter 'auto_scale_0' between the filter
                 'graph -1 input from stream 0:0' and the filter 'Parsed_lut3d_0'
[auto_scale_0] picking rgb24 out of 26 ref:yuv420p alpha:0
[auto_scale_0] w:320 h:180 fmt:yuv420p csp:unknown range:unknown sar:1/1
            -> w:320 h:180 fmt:rgb24 csp:gbr range:pc sar:1/1 flags:0x00000004
```

`lutrgb` likewise (`picking rgb24 out of 18`). Adjacent RGB filters share one conversion:

```bash
ffmpeg -hide_banner -loglevel debug -y -i src.mp4 \
  -vf "lut3d=file=identity.cube,lutrgb=r=val:g=val:b=val" -frames:v 1 -f null - \
  | rg -c "auto-inserting filter 'auto_scale"
# 1
```

10-bit source:

```bash
ffmpeg ... -c:v libx265 -pix_fmt yuv420p10le -crf 16 src10.mp4
ffmpeg -hide_banner -loglevel debug -y -i src10.mp4 -vf "lut3d=file=identity.cube" -frames:v 1 -f null -
# [auto_scale_0] picking gbrp10le out of 26 ref:yuv420p10le alpha:0

ffmpeg -hide_banner -loglevel debug -y -i src10.mp4 -vf "format=rgb24,lut3d=file=identity.cube" -frames:v 1 -f null -
# [auto_scale_0] w:320 h:180 fmt:yuv420p10le csp:unknown range:tv -> fmt:rgb24 csp:gbr range:pc
```

### A.3 The colour tables (§2.2)

```bash
# encode the swatches to yuv420p, lossless, three tagging variants
ffmpeg ... -vf "scale=out_color_matrix=bt709"              -c:v ffv1 -pix_fmt yuv420p -colorspace bt709            yuv_untagged.mkv
ffmpeg ... -vf "scale=out_color_matrix=bt709:out_range=tv" -c:v ffv1 -pix_fmt yuv420p -colorspace bt709 -color_range tv yuv_tv.mkv
ffmpeg ... -vf "scale=out_color_matrix=bt709:out_range=pc" -c:v ffv1 -pix_fmt yuv420p -colorspace bt709 -color_range pc yuv_pc.mkv
# untagged -> yuv420p,tv,bt709   tv -> yuv420p,tv,bt709   pc -> yuv420p,pc,bt709
```

Read back four ways (first table in §2.2 — `tv_none` / `tv_auto` / `tv_fmt` are identical; `tv_wrongrange` is the damaged column):

```bash
ffmpeg -i yuv_tv.mkv                                                      -frames:v 1 -f rawvideo -pix_fmt rgb24 out_tv_none.rgb24
ffmpeg -i yuv_tv.mkv -vf "lut3d=identity.cube"                            -frames:v 1 -f rawvideo -pix_fmt rgb24 out_tv_auto.rgb24
ffmpeg -i yuv_tv.mkv -vf "format=rgb24,lut3d=identity.cube"               -frames:v 1 -f rawvideo -pix_fmt rgb24 out_tv_fmt.rgb24
ffmpeg -i yuv_tv.mkv -vf "scale=in_range=full:out_range=full,format=rgb24,lut3d=identity.cube" \
                                                                          -frames:v 1 -f rawvideo -pix_fmt rgb24 out_tv_wrongrange.rgb24
```

Untagged full-range planes (extraction verified to insert **no** scaler — `-loglevel debug` shows `range:pc` on the input pad and no `auto_scale`):

```bash
ffmpeg -i yuv_pc.mkv -frames:v 1 -f rawvideo -pix_fmt yuv420p full.yuv
B="ffmpeg -f rawvideo -pix_fmt yuv420p -s 256x32 -i full.yuv"
$B                                                                                  ... a_default.rgb24
$B -vf "scale=in_range=full:out_range=full"                                         ... b_range.rgb24
$B -vf "scale=in_color_matrix=bt709:out_color_matrix=bt709"                         ... c_matrix.rgb24
$B -vf "scale=in_range=full:out_range=full:in_color_matrix=bt709:out_color_matrix=bt709" ... d_both.rgb24
```
```
max abs channel error,  default (no tags):  27
max abs channel error,        range fixed:  19
max abs channel error,       matrix fixed:  20
max abs channel error,         both fixed:   2
```

### A.4 Encode-side tagging (§2.5)

```bash
enc() { ffmpeg -f rawvideo -pix_fmt rgb24 -s 256x32 -r 5 -i swatch.rgb24 -frames:v 3 \
        -c:v libx264 -crf 18 -pix_fmt yuv420p "$@"; }
enc x_plain.mp4
enc -colorspace bt709 x_cs.mp4
enc -colorspace bt709 -color_primaries bt709 -color_trc bt709 x_full.mp4
enc -x264-params "colorprim=bt709:transfer=bt709:colormatrix=bt709" x_x264only.mp4
```
```
                                     range  space  primaries  transfer     Y of (200,60,90)
x_plain      (nothing)               unknown,unknown,unknown,unknown              106
x_cs         -colorspace bt709       tv,bt709,unknown,unknown                      95
x_full       + -color_primaries/-trc tv,bt709,unknown,unknown   <- silently dropped
x_x264only   -x264-params only       tv,bt709,bt709,bt709                         106  <- planes unchanged
```

Lossless ffv1 control, isolating the plane change from the codec: `p_plain` (Y=106) is **byte-identical** (md5 `c7e381…`) to `p_601` (`-colorspace bt470bg`, Y=106), and both differ from `p_709` (md5 `2ae2b1…`, Y=95).

### A.5 Simple vs complex graph, and second sources (§1.2, §1.4)

```bash
ffmpeg -i src.mp4 -vf "split=2[a][b];[a]hue=s=0[g];[b][g]blend=all_mode=screen" -frames:v 1 -f null -
# OK: -vf accepts a branching graph
ffmpeg -i src.mp4 -i src.mp4 -vf "[0:v][1:v]blend=all_mode=screen" -frames:v 1 -f null -
# Simple filtergraph '(null)' was expected to have exactly 1 input and 1 output.
# However, it had 2 input(s) and 1 output(s). ... use a complex filtergraph (-filter_complex) instead.
ffmpeg -i src.mp4 -vf "movie=src.mp4,hue=s=0[m];[in][m]blend=all_mode=screen" -frames:v 1 -f null -   # OK
ffmpeg -f lavfi -i "haldclutsrc=8" -frames:v 1 -pix_fmt rgb24 hald.png
ffmpeg -i src.mp4 -vf "movie=hald.png[h];[in][h]haldclut" -frames:v 1 -f null -                        # OK
ffmpeg -i src.mp4 -vf "[in]hue=s=0[out]" -frames:v 1 -f null -                                        # OK
ffmpeg -i src.mp4 -vf "color=c=red:s=320x180:r=5[c];[in][c]blend=all_mode=multiply:shortest=1" -frames:v 3 -f null -  # OK
ffmpeg -f lavfi -i "nullsrc=s=320x180:r=5,noise=alls=40:allf=t+u" -t 1 -c:v ffv1 -pix_fmt yuv420p grain.mkv
ffmpeg -i src.mp4 -vf "movie=grain.mkv:loop=0,format=gbrp[g];[in]format=gbrp[b];[b][g]blend=all_mode=softlight:shortest=1,format=yuv420p" -frames:v 5 -f null -  # OK
```

### A.6 Timeline `enable` (§1.5)

```bash
ffmpeg -i big.mp4 -vf "lut3d=file=que_calor_b.cube:enable='between(t,2,4)'" -frames:v 300 -f rawvideo -pix_fmt rgb24 -
#   t= 0.5s  frame mean = 126.79     t= 2.5s  frame mean = 178.11     t= 4.5s  frame mean = 126.75
#   t= 1.5s  frame mean = 126.89     t= 3.5s  frame mean = 169.63     t= 5.5s  frame mean = 126.87

for ss in 0 4; do ffmpeg -ss $ss -i big.mp4 -t 2 -vf "lut3d=file=que_calor_b.cube:enable='between(t,0,1)'" ... ; done
#   -ss 0 : means at 0.2/0.8/1.2/1.8 s = 178.8, 178.8, 126.7, 126.7
#   -ss 4 : means at 0.2/0.8/1.2/1.8 s = 178.8, 178.8, 126.7, 126.7   (identical: -ss rebases t to 0)
```

Timeline (`T`) support, from `ffmpeg -filters`: `TS lut3d`, `TS lutrgb`, `TS colorchannelmixer`, `TS huesaturation`, `T. eq`, `T. hue`, `TS unsharp`, `TS noise`, `TS blend`, `TS overlay`, `TS haldclut` — and **`.. crop`**, **`.. scale`** (no timeline).

### A.7 Filter availability (§2.4)

```bash
ffmpeg -hide_banner -filters | rg -w "zscale|colorspace|scale |format |lut3d|haldclut|lutrgb|colorchannelmixer"
#  TS colorchannelmixer V->V     .. format V->V       TS haldclut VV->V
#  TS colorspace V->V            TS lut3d V->V        TS lutrgb V->V        .. scale V->V
#  (no zscale)
ffmpeg -hide_banner -version | rg -o "enable-libzimg" || echo "(no libzimg => no zscale)"
# (no libzimg => no zscale)
```

### A.8 Timings (§2.4, §4.3) — best of three, `/usr/bin/time -p`

10 s @ 1280×720 (300 frames), output `-f null -`:

```
decode only (null out)                                       0.14s
scale (range+matrix declared, in == out)                     0.14s
scale in_range=full -> out_range=tv (real convert)           0.18s
format=rgb24 then back to yuv420p                            0.23s
lut3d (auto conversion)                                      0.75s
lut3d + lutrgb posterise                                     0.88s
colorspace=all=bt709:iall=bt601-6-625                        0.85s
```

62 frames @ 1280×720, with a real `libx264 -crf 16 -preset medium` encode:

```
decode -> encode, no filter                                  0.28s   (4.5 ms/frame)
decode -> lut3d + lutrgb -> encode  (all ffmpeg)             0.43s   (6.9 ms/frame)
decode -> raw pipe -> python no-op -> raw pipe -> encode      0.55s   (8.9 ms/frame)
   ... the same pipe running numpy identity                   0.58s   (9.4 ms/frame, 0.11 s in python)
   ... the same pipe running pyrMeanShiftFiltering @ 0.5      4.42s   (71.2 ms/frame, 3.96 s in python)
```

Peak RSS (`/usr/bin/time -l`): cv2 pipe **364 MB**, plain ffmpeg `lut3d` **377 MB**, both flat in clip length.

### A.9 Multi-input memory scaling (§3.1)

Each run isolated, **descending** order so a cumulative `ru_maxrss` reading would be exposed:

```
  N=40  peak RSS =     694 MB
  N=24  peak RSS =     482 MB
  N=12  peak RSS =     328 MB
  N=4   peak RSS =     208 MB
  N=1   peak RSS =     143 MB
```
(one `ffmpeg -filter_complex "[0:v]…[N-1:v]concat=n=N:v=1:a=0[v]"` per row, N copies of the 2 s 720p clip.)

### A.10 Ordering (§5.1)

```bash
P="lutrgb=r='trunc(val/18)*18+9':g='trunc(val/18)*18+9':b='trunc(val/18)*18+9'"
L="lut3d=file=que_calor_b.cube"
ffmpeg -i src.mp4 -vf "$L,$P"            -frames:v 1 -f rawvideo -pix_fmt rgb24 o_LP.rgb24
ffmpeg -i src.mp4 -vf "$P,$L"            -frames:v 1 -f rawvideo -pix_fmt rgb24 o_PL.rgb24
ffmpeg -i src.mp4 -vf "scale=160:90,$L,$P" -frames:v 1 -f rawvideo -pix_fmt rgb24 o_geoFirst.rgb24
ffmpeg -i src.mp4 -vf "$L,$P,scale=160:90" -frames:v 1 -f rawvideo -pix_fmt rgb24 o_geoLast.rgb24
```
```
LUT->posterise vs posterise->LUT      : mean|d|=  4.24  max|d|= 55  differing px=100.0%
downscale->colour vs colour->downscale: mean|d|=  2.60  max|d|=122  differing px= 26.8%
  distinct 5-bit colours: LUT->post=  51   post->LUT=  96
  distinct 5-bit colours: geo-first=  77   geo-last= 359
```

### A.11 The cv2 wheel licence audit (§3.6)

```bash
python3 -c "
import importlib.metadata as m
for n in ('opencv-python','opencv-python-headless','opencv-contrib-python'):
    d=m.distribution(n); print(n, d.version, '|', d.metadata.get('License'))"
# opencv-python 4.12.0.88            | Apache 2.0
# opencv-python-headless 4.13.0.92   | Apache 2.0
# opencv-contrib-python 4.13.0.92    | Apache 2.0

head -1 site-packages/cv2/LICENSE.txt
# MIT License          <- the wheel builder's, NOT OpenCV's

sed -n '240,252p' site-packages/cv2/LICENSE-3RD-PARTY.txt
# FFmpeg is redistributed within all opencv-python packages.
# Libbluray, libgnutls, libnettle, libhogweed, libintl, libmp3lame, libp11,
# librtmp, libsoxr and libtasn1 are redistributed within all opencv-python macOS packages.
# This license applies to the above library binaries in the directory cv2/.
#                   GNU LESSER GENERAL PUBLIC LICENSE
#                        Version 2.1, February 1999

ls site-packages/cv2/.dylibs | wc -l          # 93
ls site-packages/cv2/.dylibs | rg -i "x264|x265|postproc|vidstab|bluray|lame|gnutls|nettle|tasn1|zimg"
# libx264.164.dylib   libx265.215.dylib   libpostproc.58.3.100.dylib   libvidstab.1.2.dylib
# libbluray.2.dylib   libmp3lame.0.dylib  libgnutls.30.dylib  libnettle.8.10.dylib
# libhogweed.6.10.dylib  libtasn1.6.dylib  libzimg.2.dylib

otool -L site-packages/cv2/.dylibs/libavcodec.61.19.101.dylib | rg -i "x264|x265|lame"
#     @loader_path/libmp3lame.0.dylib
#     @loader_path/libx264.164.dylib
#     @loader_path/libx265.215.dylib
```

The headless variant's own `LICENSE-3RD-PARTY.txt` carries the identical FFmpeg-redistribution line and the identical LGPL-2.1 text — checked for all three installed distributions.

Build info of the imported `cv2 4.13.0`: `Video I/O: FFMPEG: YES`, `GStreamer: NO`, `Non-free algorithms: NO`, `hasattr(cv2, "xfeatures2d") == True` (the imported module is the **contrib** build).

---

## REFERENCES

Local sources were read directly in this session. Web references are cited as pointers; **none of them was fetched in this session**, and no claim in this note rests on one — every ffmpeg behaviour above was established by running the command shown in the appendix.

[1] [FFmpeg Filters Documentation — filtergraph description, simple vs complex graphs, the timeline `enable` option](https://ffmpeg.org/ffmpeg-filters.html). Pointer only; the behaviours asserted here were measured against the ffmpeg 8.1 binary (§A.5, §A.6).

[2] [FFmpeg `libavfilter/vf_lut3d.c`](https://github.com/FFmpeg/FFmpeg/blob/master/libavfilter/vf_lut3d.c) — the source of `lut3d`'s pixel-format list. Pointer only; the list in §2.1 was read out of the running binary's `-loglevel debug` output.

[3] `muvid/visualize/ffmpeg.py` — `/Users/thorwhalen/Dropbox/py/proj/t/muvid/muvid/visualize/ffmpeg.py`. The dependency-free binary wrappers: `run_ffmpeg`, `probe`, `has_filter` / `require_filter` (the pattern §2.4 says `looks` needs for `zscale`), and `$MUVID_FFMPEG_TIMEOUT_S`.

[4] `muvid/footage/assemble.py` — `/Users/thorwhalen/Dropbox/py/proj/t/muvid/muvid/footage/assemble.py`. The bounded-memory invariant (module docstring), the one-decoder-per-part `_render_part` whose `-vf` a `looks` `FilterStage` must splice into, the two-decoder `xfade` exception, and `_crop_filter`'s expression-ramp approach to time-varying geometry.

[5] `muvid/visualize/visuals.py` — `/Users/thorwhalen/Dropbox/py/proj/t/muvid/muvid/visualize/visuals.py`. `VisualPlan`, `register_visual`, `resolve_visual`'s path-returning escape hatch, and the `format=rgba` / `format=gbrp` comments that Rule C3 codifies.

[6] `render_v2c.py` — `~/Downloads/que_calor/work/style/render_v2c.py`. The real mixed-backend chain: per-clip `MS_PARAMS`, the `bgr24` decode/encode pipe, and the encoder `-vf` carrying `lut3d` + `lutrgb`. Companion sources `stylize.py`, `mklut_b.py`, `tonematch.py` in the same directory, and the write-up `~/Downloads/que_calor/how_the_video_got_made__technical.md`.

[7] `falaw/plan.py` — `/Users/thorwhalen/Dropbox/py/proj/t/falaw/falaw/plan.py`. `CallPlan` / `Plan`: the pure-data-then-execute split, "the *exact* tuple … would take", and the `cache_status` / cost vocabulary this note's `CompiledLook` mirrors.

[8] `burns/backends.py` — `/Users/thorwhalen/Dropbox/py/proj/t/burns/burns/backends.py`. The `RenderBackend` Protocol + `RENDER_BACKENDS` registry, and the docstring naming an ffmpeg `zoompan` fast-path as the intended second backend.

[9] [Adobe Cube LUT Specification 1.0](https://web.archive.org/web/20220220033515/https://wwwimages2.adobe.com/content/dam/acom/en/products/speedgrade/cc/pdfs/cube-lut-specification-1.0.pdf) — the `.cube` format `mklut_b.py` writes and `lut3d` reads. Pointer only.

[10] [ITU-R BT.709](https://www.itu.int/rec/R-REC-BT.709) — the matrix/primaries/transfer triple §2.5 is about. Pointer only.

[11] `mixing/video/video_util.py` — `/Users/thorwhalen/Dropbox/py/proj/t/mixing/mixing/video/video_util.py`. `SOCIAL_SIZES`, `resize_to_dimensions`, `normalize_video_dimensions` — the geometry tier `looks` inherits, and the moviepy coupling §6 flags.

[12] `looks/KICKOFF.md` — `/Users/thorwhalen/Dropbox/py/proj/t/looks/KICKOFF.md`. The non-negotiables this note is constrained by, the measured Que Calor facts, and the two open questions §6 returns to.

[13] `opencv-python` wheel licence payload — read from the installed distributions on this machine, not from the web: `site-packages/cv2/LICENSE.txt` (MIT), `site-packages/cv2/LICENSE-3RD-PARTY.txt` (Apache-2.0 + LGPL-2.1 + LGPL-3 + MPL-2.0, and the FFmpeg-redistribution paragraph), and `site-packages/cv2/.dylibs/` (93 shared libraries incl. `libx264`, `libx265`, `libpostproc`, `libvidstab`). Versions inspected 2026-09-02: `opencv-python 4.12.0.88`, `opencv-python-headless 4.13.0.92`, `opencv-contrib-python 4.13.0.92`, macOS arm64. Upstream project page for context: [opencv-python on PyPI](https://pypi.org/project/opencv-python/) — **pointer only, not fetched**.

[14] [x264 licensing](https://www.videolan.org/developers/x264.html) and [FFmpeg legal / licensing](https://ffmpeg.org/legal.html) — the GPL-2.0-or-later status of `libx264` / `libx265` and the GPL-only status of `libpostproc` that §3.6 turns on. **Pointers only, not fetched in this session**; the *presence* of those binaries in the wheel was measured (§A.11), their licences are taken as common knowledge and should be re-confirmed against each project's own COPYING file before the tier is written into code.
