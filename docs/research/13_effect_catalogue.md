# The v1 built-in effect catalogue

**Date: 2026-09-02** · research note 13 for `looks` · status: proposal, evidence measured

Every ffmpeg claim below was produced by running the command shown, on **ffmpeg 8.1** (homebrew `8.1_1`, `--enable-gpl --enable-version3`, no `--enable-libzimg`), on macOS 15 / arm64, on 2026-09-02. Python measurements are **CPython 3.12.12**; the OpenCV comparison is **cv2 5.0.0 / numpy 2.5.0** in that interpreter (note that sibling note 05 measured a different environment — opencv-python 4.13.0 / numpy 2.2.6 — so the two sets of OpenCV numbers are not directly comparable and I say which is which). Anything I did not run is marked **unverified**.

## Verdict

**v1 ships 24 named effects in three families plus one separate `Transition` type, and the catalogue's spine is a `frame_dependency` column with five values that turns out to be mechanically testable rather than a matter of judgement.** Two probes settle it for any effect: apply it to a *looped still* and diff consecutive output frames (separates deterministic-but-time-varying grain from everything else — `noise` with the `t` flag changes 87.4% of pixels frame to frame; `deband`, `bilateral`, `gblur`, `lut3d` and untagged `noise` change 0%), then apply it to two frames that *share a region but differ elsewhere* and diff the shared region (separates content-adaptive filters, which flicker, from content-independent ones — `normalize` changes 67.4% of the shared region by up to 204/255, `elbg` 15.0%, while `lut3d`, `curves`, `deband` and `bilateral` change nothing). That is the whole Que Calor flicker argument reduced to two `ffmpeg` invocations and a byte diff, so `looks` can assert every catalogue entry's declared dependency class in its own test suite instead of documenting it. **The headline gradient-map LUT is in the zero-dependency tier and this is measured, not hoped**: a stdlib-only reimplementation of `mklut_b.py` (`colorsys` for hue/saturation, `bisect` for the ramp, `math` for the rest, no numpy) produces the `.cube` for the shipped Que Calor look **byte for byte identical** to the numpy original — all 970,374 of them — in **0.141 s** for 33³. That decides the artifact-management question too: **inline the ramp in the spec and generate the `.cube` into a content-addressed cache**, because the spec is 566 bytes of JSON against a 948 KiB file (**1714×** the same information, measured through the proposed API), generation is cheaper than a network read, and a `Look` that references a path is not a document. Three findings arrived unbidden and each changes a decision. (1) **A run of pixel effects can be fused into one lookup and it is a 3.9× win** — 8 stacked pixel filters cost 14.25 ms/frame directly, 6.69 ms/frame fused in-graph via `haldclutsrc`, and **3.65 ms/frame** via a hald CLUT materialised once to a PNG and re-read with `movie=` — but **only when the composite is smooth**: fusing a run that ends in `posterize` under the default tetrahedral interpolation is measurably wrong (6.12% of samples off by more than 2/255, max 21/255) because interpolating a quantised lookup un-quantises it, and `interp=nearest` repairs it (0.265%). (2) **`curves` with its default `interp=natural` is not monotone** — on the steep-kneed curve a histogram match produces it emitted 21 non-monotone steps out of 255, so `tone_match` must compile with **`interp=pchip`**, which emitted 0. (3) **`flatten` has no permissive implementation and the LGPL one is not an equivalent**: `cv2.pyrMeanShiftFiltering` sits at `COPYLEFT_SHIPPED` and is therefore *refused by the default ceiling*, so the first look `looks` ships cannot run at its own default — while ffmpeg's `bilateral` (LGPL, no GPL dependency, verified in `configure`) does reach the same flattening (`ncol90` 117–165 bracketing mean-shift's 132) but at roughly half the retained post-look sharpness (23–36 against 54.9), which is precisely the axis the V2c per-clip correction was about. On the inherited `mixing` code the verdict is deflationary and worth stating up front: **the six transitions are two transitions, three EDL decisions and one retime**, and the geometry tier moves as a *vocabulary* — all four resize modes compile to verified ffmpeg chains, so none of moviepy comes with it.

---

## 1. What a catalogue entry is

Note 03 fixes the types: an `Effect` is `(name, params, at)` and carries **no tier**; a `Look` carries only a ceiling; a tier appears for the first time in a compiled `Step`, copied off the `ImplRef` that was selected [10]. So a catalogue entry is not one row — it is **one capability name plus one or more `ImplRef`s**, and the tier column below belongs to the implementations, never to the name.

Every entry declares seven things.

| column | what it is | why it exists |
|---|---|---|
| `name` | the registry key a user types | this is the package's whole user-facing vocabulary; film-industry nouns where one exists |
| one-line | what it does | goes into `effect_catalog()`, the JSON-able surface an agent or MCP builder reads (nw's `transform_catalog()` shape [4]) |
| params | name, type, unit, default, range | ranges are the *filter's own* declared ranges wherever one exists, read out of `ffmpeg -h filter=X`, not invented |
| implementations | `(backend, tier, compile target)` | note 06's finding that the tier is **resolved from the environment**, not declared as a constant [13] |
| `frame_dependency` | PIXEL / FRAME / INDEXED / ADAPTIVE / TEMPORAL | §1.1 — this is the flicker contract, and §1.2 makes it testable |
| `clip_aware` | does any parameter default to a `Ref` | note 04's resolver; the V2b→V2c lesson is that at least one effect **must** be clip-aware [11] |
| ordering | what may not follow it | note 05's rule: `looks` validates and warns, never reorders [12] |

### 1.1 `frame_dependency` — five values, and the two that are refusals

The Que Calor design's central claim is "frame-independent by construction, so it cannot flicker" [9]. That is a real property but the phrase is too coarse: film grain *should* vary frame to frame, and a per-frame auto-levels *must not*. Five values separate what matters.

| value | definition | flickers? | can it be fused into a lookup? | example |
|---|---|---|---|---|
| `PIXEL` | output pixel is a function of that input pixel alone | no | **yes** | `lut3d`, `curves`, `posterize`, `colortemperature` |
| `FRAME` | output is a function of the whole input frame, deterministically | no | no | `gblur`, `vignette`, `crop`, `bilateral`, `halation` |
| `INDEXED` | output is a function of the frame *and its index or timestamp*, deterministically | no — it *animates*, which is the point | no | `grain` with temporal noise, `xfade` progress |
| `ADAPTIVE` | output depends on *statistics recomputed from each frame's content* | **yes** | no | `normalize`, `colorcorrect analyze≠manual`, `elbg` |
| `TEMPORAL` | output depends on *other frames* | n/a — a different problem | no | `tmix`, `atadenoise`, `hqdn3d`, `minterpolate` |

The last two are the v1 exclusions and they are excluded for different reasons. `ADAPTIVE` is excluded because it is the flicker mode `mklut.py` names explicitly — "the failure mode of every neural cartooniser and of per-frame palette quantisation" [5]. `TEMPORAL` is excluded because of the *federation's execution model*, not taste: muvid renders one bounded ffmpeg process per cut [9], so a temporal filter would see a hard discontinuity at every cut boundary and produce a visible artefact at exactly 50 places in the Que Calor edit. That is a structural incompatibility, not a preference, and it is the reason this exclusion should not be revisited casually.

### 1.2 The taxonomy is testable, and here is the test

Both distinctions reduce to a diff. **Probe A — temporal stability.** Apply the effect to a *looped still* and compare consecutive output frames.

```
$ ffmpeg -loglevel error -y -f lavfi -i "gradients=s=640x360:c0=#101018:c1=#404860:d=1:r=10" -frames:v 1 static.png
$ ffmpeg -loglevel error -y -loop 1 -i static.png -vf "<EFFECT>" -frames:v 4 -f rawvideo -pix_fmt rgb24 x.raw
```

| effect | frame0 vs frame1 | frame0 vs frame3 | class |
|---|---|---|---|
| `deband` | max 0/255, 0.00% changed | max 0/255, 0.00% | FRAME |
| `bilateral` | max 0/255, 0.00% | max 0/255, 0.00% | FRAME |
| `gblur=sigma=4` | max 0/255, 0.00% | max 0/255, 0.00% | FRAME |
| `noise=alls=8:allf=u` | max 0/255, 0.00% | max 0/255, 0.00% | FRAME (fixed-pattern) |
| `noise=alls=8:allf=t+u` | **max 7/255, 87.39% changed** | max 7/255, 87.50% | **INDEXED** |

That last row is also the answer to "should grain be frame-independent?" — no. Untagged `noise` is temporally *static*, which is fixed-pattern noise and reads as dirt on the lens rather than as grain. `grain` is correctly `INDEXED`, and the probe proves it rather than asserting it.

**Probe B — content independence.** Render two single frames that share a large region and differ elsewhere (here: the same still, one with a 40×40 white box in the top-left corner), then diff **only the shared region** (rows 100–359).

| effect | max diff in the shared region | share of shared region changed | class |
|---|---|---|---|
| `null` | 0/255 | 0.00% | — |
| `lut3d=file=que_calor_b.cube` | 0/255 | 0.00% | PIXEL |
| `curves=all='0/0 0.5/0.6 1/1':interp=pchip` | 0/255 | 0.00% | PIXEL |
| `deband` | 0/255 | 0.00% | FRAME |
| `bilateral` | 0/255 | 0.00% | FRAME |
| `colorcorrect=analyze=manual` | 0/255 | 0.00% | PIXEL |
| `normalize=smoothing=0` | **204/255** | **67.37%** | **ADAPTIVE** |
| `elbg=l=16:n=1:s=42` | **5/255** | **15.04%** | **ADAPTIVE** |
| `colorcorrect=analyze=average` | 0/255 | 0.00% | **inconclusive — see below** |

Two honesty notes on that table. `colorcorrect=analyze=average` came out clean **only because the perturbation was too small** — a 40×40 patch out of 640×360 is 0.7% of the frame and moves the mean by less than 1/255. The filter is content-adaptive by its own documented construction, so `looks` must classify it `ADAPTIVE` **by declaration** and treat Probe B as a lower bound, never as an acquittal. Likewise `normalize=smoothing=30` produced identical numbers to `smoothing=0` in my run, which is **not a fair test of smoothing** — smoothing needs a frame *sequence* and my probe renders one frame each; the smoothed variant is therefore **unverified** and I make no claim about it.

The value of these two probes is that they are cheap enough to run over the whole catalogue in CI. The rule to ship: *every effect declaring `PIXEL` or `FRAME` must pass both probes; every effect declaring `INDEXED` must fail probe A; a declared class that disagrees with the probes is a bug in the catalogue, not in the probe.*

### 1.3 The canonical stage order

The Que Calor pipeline settled this and note 04 explains why the order is load-bearing rather than aesthetic: c01 and c02's sharpness ordering **inverts** between their source files and the finished render, because c01 is upscaled 2.68× and c02 only 1.51× [11]. Measure after geometry or you correct the wrong clip.

```
geometry  →  grade  →  flatten  →  look (LUT · posterize)  →  optical (halation · vignette · aberration)  →  grain
```

`looks` **validates and warns, never reorders** (note 05's rule [12]). Five ordering constraints are worth encoding:

- Nothing that resamples or interpolates may follow `posterize` — measured in note 05 (posterise-then-LUT yields 96 distinct 5-bit colours against LUT-then-posterise's 51; downscale-after-posterise 359 against 77) and re-confirmed here by the fusion experiment in §8.
- `flatten` before the LUT: the LUT-and-posterise stage *adds* apparent sharpness by creating hard edges between flat regions, and that only works where the flattener left distinct regions [9].
- `grain` last: grain before a LUT gets colour-mapped, grain before `posterize` gets quantised away.
- Optical effects (`halation`, `vignette`, `chromatic_aberration`) after the look — they model the lens and the film base, which sit after the image.
- `deband` before, never after, `posterize` — `deband` exists to break banding and `posterize` exists to create it.

---

## 2. Family A — grade and normalisation (8 effects)

This family answers the kickoff's second open question, *does `looks` own normalisation as well as stylization?* **Yes, deliberately.** The Que Calor edit needed both, they compile to the same insertion point, and the per-clip grade and the extreme look are solved by the same resolver against the same measurements. Treating them as one vocabulary is right and this note is the place that says so.

| name | one line | `frame_dependency` | clip-aware |
|---|---|---|---|
| `gamma` | power-law luminance transfer — the *only* sanctioned brightness control | PIXEL | yes, by convention |
| `exposure` | multiplicative exposure in stops | PIXEL | no |
| `contrast` | S-curve about a pivot | PIXEL | no |
| `saturation` | luma-preserving chroma gain | PIXEL | no |
| `white_balance` | colour-temperature shift in Kelvin | PIXEL | no |
| `levels` | black-point / white-point remap, in and out | PIXEL | no |
| `tone_match` | carry the source's luma CDF onto a target histogram | PIXEL after resolution | **mandatory** |
| `match_clip` | solve a grade so N clips land in family | composite | **mandatory** |

### `gamma`

**Parameters.** `gamma: float = 1.0`, range 0.1–4.0 (the Que Calor grade used 1.78 for the indoor clip [9]) · `channels: {"luma", "rgb"} = "luma"`.

**Documentation this effect carries, verbatim, because it is the single most reusable lesson in the source material:** *gamma, never a brightness offset.* An additive offset lifts the black floor and reads as haze [9]. ffmpeg gives you two ways to make that mistake and `looks` closes both: the `exposure` filter's `black` option (range −1…1) is deliberately **not exposed** by `looks.exposure`, and `eq=brightness=` is reachable only through the GPL-tier `eq` implementation, where the docstring names it as the wrong knob. This is documentation with teeth — an omitted parameter, not a warning.

**Implementations.**

| backend | tier | compile target | verified |
|---|---|---|---|
| ffmpeg (LGPL-safe) `channels="luma"` | `WEAK_COPYLEFT` | `lutyuv=y='16+219*pow(clip(val-16,0,219)/219,1/G)'` | OK |
| ffmpeg (LGPL-safe) `channels="rgb"` | `WEAK_COPYLEFT` | `lutrgb=r='255*pow(val/255,1/G)':g=…:b=…` | OK |
| ffmpeg (GPL) | `COPYLEFT_TOOL` | `eq=gamma=G` | OK |

The limited-range form is not decoration. `lutyuv` expressions see **coded** values, so `y='255*pow(val/255,1/G)'` on a limited-range source treats 16 as 0.0627 and pushes results below the legal floor. Which form is correct depends on note 05's `ColorContract`, and an unknown contract is a refusal there [12]; `looks` must select the implementation *after* the contract is known, which is another reason selection happens at compile time rather than at authoring time.

### `exposure`

**Parameters.** `stops: float = 0.0`, range −3…3 (the filter's own declared range).

**Implementation.** ffmpeg `exposure=exposure=S` · `WEAK_COPYLEFT` · PIXEL · verified OK. The filter's `black` option is not exposed (see `gamma` above).

### `contrast`

**Parameters.** `amount: float = 0.0`, range −1…1 · `pivot: float = 0.5`, range 0…1.

**Implementations.** ffmpeg `curves=all='0/0 <p1> <p2> 1/1':interp=pchip` (LGPL, `WEAK_COPYLEFT`, verified OK) · ffmpeg `eq=contrast=C` (GPL, `COPYLEFT_TOOL`). `interp=pchip` for the same reason `tone_match` needs it — see §2's `tone_match` entry and the measurement there.

### `saturation`

**Parameters.** `amount: float = 1.0`, range 0…4 · `coefficients: {"bt709","bt601"} = "bt709"`.

**Implementations, and a measured range split.** The luma-preserving saturation matrix is nine `colorchannelmixer` terms derived from the luma coefficients. `colorchannelmixer` declares every gain in **−2…2**, and the largest term (`bb = l_b + s·(1 − l_b)` with `l_b = 0.0722`) crosses 2 at **s = 2.0779**. Measured: `s = 2.05` is accepted, `s = 2.1` is refused with `Value 2.020600 for parameter 'bb' out of range [-2 - 2]`, and `s = 2.5` is refused on `rr`. `hue=s=` accepted 2.5 and 4.0.

| backend | tier | compile target | valid range | verified |
|---|---|---|---|---|
| ffmpeg `colorchannelmixer` | `WEAK_COPYLEFT` | 9-term matrix | **s ≤ 2.077** | OK at 0.0/0.18/1.0/1.35/2.0/2.05; refused at 2.1/2.5 |
| ffmpeg `hue` | `WEAK_COPYLEFT` | `hue=s=S` | unbounded in practice | OK at 1.35/2.5/4.0 |
| ffmpeg `eq` | `COPYLEFT_TOOL` | `eq=saturation=S` | 0…3 (declared) | OK |

So `saturation` is the small, clean example of an effect with two same-tier implementations selected by *parameter value* rather than by licence, which the `ImplRef` shape already supports.

### `white_balance`

**Parameters.** `temperature_k: int = 6500`, range 1000…40000 · `mix: float = 1.0`, range 0…1 · `preserve_lightness: float = 0.0`, range 0…1.

**Implementation.** ffmpeg `colortemperature=temperature=K:mix=M:pl=P` · `WEAK_COPYLEFT` · PIXEL · verified OK. There is a second, more surgical implementation in `colorbalance` (shadows/midtones/highlights, `pl` to preserve lightness, verified OK) which `looks` exposes as its own effect only if a second consumer asks; for v1 it stays inside `match_clip`'s solved output.

### `levels`

**Parameters.** `black_in: float = 0.0` (−1…1) · `white_in: float = 1.0` (−1…1) · `black_out: float = 0.0` (0…1) · `white_out: float = 1.0` (0…1) · `per_channel: bool = False` · `preserve: {"none","lum","max","avg","sum","nrm","pwr"} = "none"`.

**Implementation.** ffmpeg `colorlevels=rimin=…:rimax=…:romin=…:romax=…` · `WEAK_COPYLEFT` · PIXEL · verified OK.

**This is where the V2a→V2b shadow-floor correction lives.** V2a crushed 16.2% of pixels to L\* 0–5 where the reference has 0.3%, and the fix was to set the dark end to the reference's own measured floor `#2E0C18` (L\* 8.22), taking histogram distance from 46.7 to 32.0 pp [9]. In the shipped look that floor is baked into the *ramp* rather than applied as a separate `levels` step, and both are legitimate; `levels` with `black_out ≈ 0.032` is the way to lift a floor on material that is not going through a gradient map.

### `tone_match`

**One line.** Build the monotone curve carrying the source's luma CDF onto a target histogram, and apply it. This is `tonematch.py` generalised [7].

**Parameters.** `target: list[float] | str | Ref` — 20 bin shares, or a registered named histogram, or (idiomatically) a `Ref` resolved from a measured reference · `space: {"lstar","luma"} = "lstar"` · `strength: float = 1.0`, range 0…1 · `points: int = 8`, range 4…32 (how many control points to sample the curve at).

**Implementation.** ffmpeg `curves=all='<points>':interp=pchip` · `WEAK_COPYLEFT` · PIXEL after resolution · **clip-aware by construction** (the curve is a function of the measured source).

**`interp=pchip` is mandatory, and this is measured.** `curves` defaults to `interp=natural` — a natural cubic spline, which overshoots at a knee. Applied to a 256-step grey ramp:

| tone curve | `interp=natural` | `interp=pchip` |
|---|---|---|
| `0/0 0.02/0.01 0.06/0.30 0.10/0.33 0.50/0.55 0.90/0.93 1/1` | **21 non-monotone steps**, worst drop −2 | 0 non-monotone steps |
| `0/0 0.40/0.05 0.45/0.55 0.50/0.60 1/1` | **20 non-monotone steps**, worst drop −2 | 0 non-monotone steps |
| the gentler `0/0 0.05/0.02 0.10/0.16 0.20/0.24 0.40/0.42 0.60/0.60 0.85/0.90 1/1` | 0 | 0 |

A histogram match produces exactly the steep-kneed shape in the first two rows — `tonematch.py` enforces monotonicity in numpy with `np.maximum.accumulate` [7] and then hands the curve to a spline that can undo it. The third row is the trap: on a gentle curve `natural` looks fine, so this defect would ship and then appear on one clip.

`space` matters for the same reason note 04 records: the same nominal threshold gives a crushed-black share of 0.6% in coded Y and 17.4% in `BGR2GRAY` — a 29× disagreement no error would ever surface [11]. `tone_match` must record which space its target histogram was measured in, and refuse a target whose space it does not know.

### `match_clip`

**One line.** Solve one grade per clip so that N clips land in family on a chosen post-effect statistic.

This is not a filter; it is a **resolver-backed composite** that emits `gamma` + `levels` + `saturation` with solved parameters. It is in v1 because it is the highest-value thing in the catalogue and because note 04 already establishes that the objective is not a search problem — minimising the max/min ratio of a statistic across N clips is *the smallest window containing one element from each of N sorted lists*, solvable exactly by a two-pointer sweep in `O(N log N)` [11].

**Parameters.** `metrics: tuple[str,...] = ("luma_p10","luma_mean","luma_p90")` · `tolerance: float = 1.25` (target max/min ratio) · `group: str | None = None` · `stage: {"post_geometry","post_effect"} = "post_effect"` · `k: int = 5` (probe frames per clip).

Three of those carry lessons that cost real time to establish and would otherwise be lost.

- **`group` is the location-aware target.** Pulling the indoor clip all the way to the outdoor median needed gamma 1.78 and would have greyed out footage that is 29% crushed [9]. So clips shot at the same location form a group and match *within* it; a global target is available and is not the default.
- **`stage` defaults to post-effect, not post-geometry**, because the right auto-rule normalises the *output* across sources, not the input [9]. Do not sharpen the soft one.
- **`k` defaults to 5, not 3.** Note 04 measured a 3-frame median at a p90 relative error of 12.7–34.0%, which is larger than most of the improvements a resolver is choosing between; the resolver must return `inside_noise` rather than a number it cannot support [11].

**Tier.** Its emitted effects are `WEAK_COPYLEFT`; the *measurement* is note 04's zero-dependency ffmpeg path (`signalstats` + `siti` + `blurdetect` through `ffprobe -f lavfi`), which is `COPYLEFT_TOOL` on this machine only because the ffmpeg on `PATH` is a GPL build.

---

## 3. Family B — look and stylize (11 effects)

| name | one line | `frame_dependency` | clip-aware |
|---|---|---|---|
| `gradient_map` | **headline** — map lightness to a colour ramp, with a hue-keyed accent channel | PIXEL | no (deliberately) |
| `lut3d` | apply an arbitrary `.cube` / `.3dl` / `.dat` / `.m3d` / `.csp` | PIXEL | no |
| `posterize` | quantise each channel to N levels | PIXEL | no |
| `flatten` | boundary-preserving region flattening | FRAME | **mandatory** |
| `monochrome` | desaturate through a photographic colour filter | PIXEL | no |
| `colorize` | wash the image toward one hue | PIXEL | no |
| `bleach_bypass` | the silver-retention process look | PIXEL | no |
| `cross_process` | the C-41-in-E-6 look | PIXEL | no |
| `halation` | highlight bloom scattering back off the film base | FRAME | no |
| `vignette` | corner falloff | FRAME | no |
| `chromatic_aberration` | lateral per-channel shift | FRAME | no |
| `grain` | film grain | **INDEXED** | no |
| `film_stock` | a *slot* for a named emulation LUT — **ships empty** | PIXEL | no |
| `deband` | break the banding a coarse LUT creates | FRAME | no |
| `blur` / `sharpen` | primitives the family above needs | FRAME | `sharpen`: yes |

That is 15 rows for 11 headline effects because `deband`, `blur` and `sharpen` are primitives rather than looks, and `film_stock` is a registry rather than an implementation. The table is honest about that rather than padding the count.

### `gradient_map` — the headline

**One line.** Map each pixel's lightness through an L\*-indexed colour ramp, optionally preserving a hue-keyed accent family, and compile the result to a 3D LUT.

**Why it is the headline, restated from the measurement so the catalogue does not lose it.** A gradient map is the right vehicle **when the target's hue tracks its lightness**, and that is a property you *measure*, not assume. The Que Calor reference had 92.0% of its chroma in a single hue band, 0.0000% true black, 0.07% true white, and no outlines anywhere — the least colourful line measured in the whole film still carried chroma 27.5 [8]. So the classic "cartoonify" recipe (bilateral filter plus adaptive-threshold black edges) would have been exactly wrong, and the reason is one number in a palette report. `gradient_map`'s docstring carries that as its worked example, because "measure the target before assuming a filter" is the transferable part.

**Parameters.**

| param | type | unit / range | default |
|---|---|---|---|
| `ramp` | `list[[float, str]]` | (L\* 0…100, `#RRGGBB`), ≥ 2 stops, sorted | required |
| `accent` | `dict \| None` | see below | `None` |
| `tone` | `dict` | `{"contrast": float, "lift": float}` or `{"curve": [[L*, L*], …]}` | `{"contrast": 1.0, "lift": 0.0}` |
| `size` | `int` | 17 \| 33 \| 65 (`lut3d` accepts others; these three are what `looks` offers) | `33` |
| `interp` | `str` | `nearest` \| `trilinear` \| `tetrahedral` \| `pyramid` \| `prism` | `tetrahedral` |
| `luma` | `str` | `lstar` \| `rec709_y` \| `rec601_y` | `lstar` |

`accent` is `{"ramp": […], "hue_deg": 52.0, "hue_width_deg": 14.0, "sat_floor": 0.42, "sat_span": 0.30, "strength": 0.70}` — a second ramp, blended in by a Gaussian weight on hue distance times a ramp on saturation. The shipped Que Calor values are the defaults because they were derived from a measurement (off-axis pixels are 9.35% of the reference frame and **every accent is warm**, hue 44°–92°, with no green, no blue and no cyan anywhere in the film [8]) and a caller who does not know what to put there is better served by a value with provenance than by zero.

**Implementation.** Generate a `.cube` (stdlib, §6) → ffmpeg `lut3d=file=<cache path>:interp=<interp>` · the generator is tier **`PURE`** (note 06's top rung — stdlib, no dependency at all [13]), the application is `WEAK_COPYLEFT` · PIXEL · verified OK, measured 4.04 ms/frame at 1280×720 (against 1.40 ms/frame for decode alone).

**Deliberately not clip-aware.** One fixed LUT for the whole edit is what makes the look flicker-proof; measured frame-to-frame change through the shipped chain was 0.89–1.12× the source's own [9], and note 04 independently reproduced that as 0.91–1.12× with an ffmpeg-only instrument [11]. A caller *may* pass `tone` as a `Ref` to fold a per-clip tone match into the map, and then gets one LUT per clip — which is correct, and the content-addressed cache makes it free of ceremony.

### `lut3d`

**Parameters.** `cube: str` (path) **or** `content: str` (the LUT text inline) · `interp: str = "tetrahedral"` · `content_sha256: str | None = None` · `licence: str | None = None`.

**Implementation.** ffmpeg `lut3d=file=…:interp=…` · `WEAK_COPYLEFT` · PIXEL · verified OK.

Two fields earn their place. `content_sha256` is what keeps a `Look` that references an external file **verifiable** — a path is not content, and note 03's whole argument for a persistable spec collapses if the most important parameter is a filesystem handle [10]. `licence` exists because *a LUT file carries its own terms*: a purchased film-emulation pack is plausibly `FIELD_RESTRICTED`, which note 06 puts off the ladder entirely where no `max_tier` can reach it [13]. An unset `licence` on a third-party file is therefore **unknown, and unknown is a refusal**, exactly as the kickoff requires.

### `posterize`

**Parameters.** `levels: int = 16`, range 2…64. Compiles `step = round(256 / levels)`; the Que Calor look used `step = 18`, i.e. ≈ 14 levels [6].

**Implementation.** ffmpeg `lutrgb=r='trunc(val/S)*S+S/2':g=…:b=…` · `WEAK_COPYLEFT` · PIXEL · verified OK. Measured with `lut3d` in front: 7.22 ms/frame at 1280×720 for the pair, against 4.04 for `lut3d` alone.

**Ordering: nothing that interpolates may follow it.** §8 gives this a second, independent measurement.

### `flatten` — and the finding that should change a plan

**One line.** Flatten the image into regions while preserving object boundaries.

**Parameters.** `scale: Ref("flatten_scale") = Ref` — **the knob that matters, and it is a `Ref` by default** · `spatial_radius: int = 12`, range 4…30 · `colour_radius: int = 60`, range 10…90 · `max_level: int = 2`.

**`scale` is the one mandatory clip-aware parameter in the whole catalogue, and it is the strongest argument for the design.** The measured facts: post-LUT retained sharpness is ~150 at full resolution, ~85 at 0.75 and ~44 at 0.5, and it barely responds to the colour radius at all — 30/45/55/60 all land 139–160 at full resolution. So it is the downscale/upscale round trip almost entirely. One global setting made the *softest* source softer still (38 against 72 and 114), and it became the mushiest thing on screen; per-clip settings took the spread from 2.98× to 1.59×. Full resolution was available and sharper and was **deliberately not used** — at ~150 it would have made the softest source the *sharpest* thing in the edit, a new mismatch rather than a fix [9].

**Implementations, measured today on `src_96.jpg` (1280×720, one frame; `ncol90` is `stylize.py`'s 5-bit colour count at 90% coverage; sharpness is Laplacian variance; "post-look" is after `lut3d` + `posterize`):**

| implementation | tier | `ncol90` | sharp | post-look sharp | wall time |
|---|---|---|---|---|---|
| *(source, no flatten)* | — | 348 | 29.3 | 105.3 | — |
| `cv2.pyrMeanShiftFiltering` 0.5 / 12 / 60 — **the shipped setting** | **`COPYLEFT_SHIPPED`** | 132 | 16.0 | **54.9** | 67 ms (in-process) |
| `cv2.pyrMeanShiftFiltering` 0.75 / 12 / 40 — the c03 fix | **`COPYLEFT_SHIPPED`** | 175 | 47.7 | 101.6 | 270 ms (in-process) |
| ffmpeg `bilateral=sigmaS=10:sigmaR=0.1:planes=7` | `WEAK_COPYLEFT` | 252 | 15.8 | 64.4 | 214 ms (whole process) |
| ffmpeg `bilateral=sigmaS=30:sigmaR=0.2:planes=7` | `WEAK_COPYLEFT` | 165 | 6.0 | 35.9 | 169 ms (whole process) |
| ffmpeg `bilateral=sigmaS=60:sigmaR=0.3:planes=7` | `WEAK_COPYLEFT` | 117 | 3.1 | 22.9 | 164 ms (whole process) |
| ffmpeg `bilateral=sigmaS=100:sigmaR=0.4:planes=7` | `WEAK_COPYLEFT` | 81 | 2.2 | 16.1 | 166 ms (whole process) |
| ffmpeg `smartblur=luma_radius=3:luma_strength=1.0` | `COPYLEFT_TOOL` | 292 | 2.2 | 58.7 | 483 ms (whole process) |
| ffmpeg `gblur=sigma=3:steps=3` — *not* edge-aware | `WEAK_COPYLEFT` | 275 | 2.0 | 55.8 | 590 ms (whole process) |

The ffmpeg wall times include roughly 60–90 ms of process startup and JPEG decode and are **not** comparable to the in-process OpenCV numbers; read them as a rough ordering only.

Three readings, and the first is the one that matters.

1. **The first look `looks` ships cannot run at `looks`' own default ceiling.** `cv2.pyrMeanShiftFiltering` comes from a wheel that bundles a GPL-3.0-or-later ffmpeg with `libx264` and `libx265` under `License: Apache 2.0` metadata [12][13], which puts it at `COPYLEFT_SHIPPED` — one rung above the `COPYLEFT_TOOL` default. That is not a bug in the tier system; it is the tier system working, on the very first customer, and it should be stated in the README rather than discovered.
2. **ffmpeg's `bilateral` is an LGPL-clean flattener and I verified it has no GPL dependency** — it has no `_filter_deps` line in `release/8.1`'s `configure` [2]. It brackets the shipped mean-shift's flattening (`ncol90` 117 and 165 against 132).
3. **But it is not an equivalent, and the difference is on exactly the axis the V2c correction was about.** At comparable flattening, `bilateral` retains roughly half the post-look sharpness (23–36 against 54.9). So `looks` offers it as *the reachable implementation at the default ceiling*, and records — in the catalogue, not in a comment — that it trades detail for flattening more steeply than mean-shift does. This is note 06's "when an effect is over the ceiling because of one component, `looks` can often name the clean alternative chain" [13], with the honest footnote that the alternative is not the same picture.

`smartblur` and `gblur` are in the table to close them off: neither flattens (292 and 275 against a source of 348) and both destroy detail. `gblur` is the measured form of the `edgePreservingFilter` failure mode — smoothing across boundaries [9].

### `monochrome`, `colorize`, `cross_process`, `bleach_bypass`

Four one-line looks that ffmpeg already implements, all `WEAK_COPYLEFT`, all PIXEL, all verified OK.

| name | compile target | params |
|---|---|---|
| `monochrome` | `monochrome=cb=…:cr=…:size=…:high=…` | `filter_cb: float = 0.0` (−1…1) · `filter_cr: float = 0.0` (−1…1) · `size: float = 1.0` (0.1…10) · `highlights: float = 0.0` (0…1) |
| `colorize` | `colorize=hue=…:saturation=…:lightness=…:mix=…` | `hue_deg: float = 0.0` (0…360) · `saturation: float = 0.5` (0…1) · `lightness: float = 0.5` (0…1) · `mix: float = 1.0` (0…1) |
| `cross_process` | `curves=preset=cross_process` | *(none in v1)* |
| `bleach_bypass` | `split=2[a][b];[a]format=gray,format=<pix>[g];[b][g]blend=all_mode=bleach:all_opacity=A` | `amount: float = 0.7` (0…1) |

`bleach_bypass` is worth a sentence: **ffmpeg 8.1's `blend` ships a `bleach` mode** (index 36 of 40, alongside `stain` at 37), which is the silver-retention process by name, so the effect is one branch and one blend rather than a hand-rolled desaturate-and-overlay. The branch lives inside a *simple* `-vf` graph, which note 05's Rule C1 explicitly permits [12] — verified OK.

`duotone` is **not** a separate effect: it is `gradient_map` with two stops, and adding a second name for a degenerate case of the headline is how a vocabulary starts to rot. It ships as a documented recipe.

### `halation`

**Parameters.** `threshold: float = 0.78` (0…1) · `sigma: float = 24.0` px (1…128) · `steps: int = 3` (1…6) · `amount: float = 0.5` (0…1).

**Implementation.** `split=2[a][b];[b]lutyuv=y='if(gt(val,T),val,0)',gblur=sigma=S:steps=N[bl];[a][bl]blend=all_mode=screen:all_opacity=A` · `WEAK_COPYLEFT` · FRAME · verified OK, **9.00 ms/frame** at 1280×720 (the `gblur` alone is 8.23, so the split-and-screen is nearly free).

On the name: the industry noun for the halo around a highlight on film is **halation** — light scattering off the film base and back through the emulsion. *Bloom* is the lens equivalent and is the games-industry word. `looks` is called `looks` because "a look" is the industry noun; the same discipline applies inside the catalogue.

### `vignette`, `chromatic_aberration`, `grain`, `deband`, `blur`, `sharpen`

| name | compile target | tier | dep | params | measured |
|---|---|---|---|---|---|
| `vignette` | `vignette=angle=A:x0=…:y0=…:mode=…:aspect=…` | `WEAK_COPYLEFT` | FRAME | `angle: float = π/5` rad · `center: (str,str) = ("w/2","h/2")` · `mode: {"forward","backward"} = "forward"` · `aspect: str = "1/1"` | 2.54 ms/frame |
| `chromatic_aberration` | `rgbashift=rh=…:rv=…:bh=…:bv=…:edge=…` | `WEAK_COPYLEFT` | FRAME | `red_px: int = 0` (−255…255) · `blue_px: int = 0` · `vertical: bool = False` · `edge: {"smear","wrap"} = "smear"` | 2.14 ms/frame |
| `grain` | `noise=alls=S:allf=<flags>:all_seed=K` | `WEAK_COPYLEFT` | **INDEXED** | `strength: int = 8` (0…100) · `temporal: bool = True` · `uniform: bool = True` · `seed: int = 0` | 1.55 ms/frame |
| `deband` | `deband=1thr=…:2thr=…:3thr=…:range=R:blur=…:coupling=…` | `WEAK_COPYLEFT` | FRAME | `threshold: float = 0.02` (3e-5…0.5) · `range_px: int = 16` · `blur: bool = True` · `coupling: bool = False` | 4.52 ms/frame |
| `blur` | `gblur=sigma=S:steps=N:planes=P` | `WEAK_COPYLEFT` | FRAME | `sigma: float = 8.0` (0…1024) · `steps: int = 1` (1…6) | 8.23 ms/frame at σ=24, steps=3 |
| `sharpen` | `unsharp=lx=…:ly=…:la=A:cx=…:cy=…:ca=…` | `WEAK_COPYLEFT` | FRAME | `amount: float = 0.8` (−2…5) · `size: int = 5` (3…23, odd) · `chroma_amount: float = 0.0` | 2.13 ms/frame |

`grain`'s `seed` defaults to `0` rather than to the filter's own `-1` (random), because a spec that produces a different picture on every run is not a spec. `temporal=True` is the default and makes the effect `INDEXED` — see §1.2 for the probe that proves it, and the reason that is correct rather than a defect.

`sharpen`'s docstring carries the counter-lesson: **do not sharpen the soft one.** It exists so that `match_clip` can normalise *downward* as well as upward, which is what the V2c fix actually did — the sharpest available setting was rejected [9].

`deband` was the one entry I expected to have to exclude and the probes acquitted it: 0/255 across four frames of a looped still, and 0/255 on the shared region under Probe B. It is FRAME, not ADAPTIVE, and it is in.

### `film_stock` — a slot that ships empty, on purpose

**One line.** Apply a named film-emulation LUT from a registered provider.

**Parameters.** `stock: str` · `interp: str = "tetrahedral"`.

**Implementation.** Resolves `stock` through a registry to a `lut3d` with a declared `licence`, then compiles as `lut3d`.

**`looks` ships this registry empty**, and that is the point rather than an omission. Every film-emulation LUT pack worth having is either commercial or of unknown provenance; shipping one would put a plausibly `FIELD_RESTRICTED` artifact inside a package whose thesis is that unknown terms are a refusal. So the slot exists so that `looks` can **refuse it correctly**: `film_stock="kodak_2383"` with nothing registered raises `UnknownEffect` naming how to register a provider, and a registered provider with `licence=None` raises the licence refusal at compile time. An empty registry that refuses well is a better v1 than a populated one that cannot say where its contents came from.

---

## 4. Family C — geometry (3 effects plus a preset table)

Inherited from `mixing/video/video_util.py` [4] as a **deprecation-free move**, per the kickoff. The kickoff also names the tension — `video_util.py` is moviepy through and through, and `looks` declares zero dependencies — and the resolution is that **the vocabulary moves and the implementation does not**. All four resize modes compile to ffmpeg chains I verified today, so nothing of moviepy comes with them.

| name | one line | `frame_dependency` |
|---|---|---|
| `fit` | resize to a target size by one of four modes | FRAME |
| `crop` | take a static rectangle | FRAME |
| `pad` | letterbox or pillarbox to a size, in a colour | FRAME |

### `fit`

**Parameters.** `size: tuple[int,int] | str` (a `TARGET_SIZES` key) · `mode: {"stretch","fit","fill","social"} = "fit"` · `background: str = "black"` · `blur_sigma: float = 30.0` (`social` only) · `dim: float = 0.7` (`social` only) · `divisible_by: int = 2`.

**Compile targets — all four verified OK today.**

| mode | compile target |
|---|---|
| `stretch` | `scale=W:H,setsar=1` |
| `fit` | `scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2:color=<bg>,setsar=1` |
| `fill` | `scale=W:H:force_original_aspect_ratio=increase,crop=W:H,setsar=1` |
| `social` | `split=2[bg][fg];[bg]scale=W:H:force_original_aspect_ratio=increase,crop=W:H,gblur=sigma=<σ>:steps=3,colorchannelmixer=<dim·saturation matrix>[b2];[fg]scale=W:H:force_original_aspect_ratio=decrease[f2];[b2][f2]overlay=(W-w)/2:(H-h)/2` |

**The `social` mode carries a live finding about the federation's own code.** muvid's `background_chain` builds exactly this blurred-background composite and dims it with **`eq=brightness=-<dim>:saturation=<sat>`** (`muvid/visualize/canvas.py:224`) [16]. Two problems in one filter call: `eq` is **GPL-only** — one of the 33 filters `release/8.1`'s `configure` guards behind `gpl` [2], and the single `eq=` in the whole muvid tree against nine uses of `colorchannelmixer` elsewhere in the same package — and `brightness` is an **additive offset**, precisely the knob the Que Calor grade refused because it lifts the black floor and reads as haze [9]. The LGPL-clean replacement for `dim=0.5, saturation=0.18` is a single `colorchannelmixer` with the luma-preserving saturation matrix scaled by the dim:

```
colorchannelmixer=rr=0.1772:rg=0.2932:rb=0.0296:gr=0.0872:gg=0.3832:gb=0.0296:br=0.0872:bg=0.2932:bb=0.1196
```

It is **not numerically identical**, and that is the improvement: it dims multiplicatively instead of adding an offset. This is the concrete case for `looks` existing — one filter call, in a package that already depends on ffmpeg, quietly raising the whole product's licence tier for a cosmetic dim, with a better replacement available.

### `crop` and `pad`, and the boundary with `burns`

**`crop`** — `w: int|str`, `h: int|str`, `x: int|str = "(in_w-out_w)/2"`, `y: int|str = "(in_h-out_h)/2"`, `exact: bool = False` → `crop=w:h:x:y`. **`pad`** — `w`, `h`, `x = "(ow-iw)/2"`, `y = "(oh-ih)/2"`, `color: str = "black"` → `pad=w:h:x:y:color=…`. Both verified OK.

**The kickoff's first open question — should `burns` become a `looks` backend? — gets a clean answer from this family: no, and the split is a static/dynamic split rather than a package-politics one.** A static rectangle is a `looks` effect. A rectangle that *varies with time* is `burns.BurnsPath.evaluate(t) -> Rect`, which is already render-agnostic and JSON-serialisable, and whose own `backends.py` names an ffmpeg fast-path as its intended second backend — and that fast-path emits `crop=…:x='<expression in t>'`, the same filter with an expression instead of a constant. So the two never collide and neither needs to know about the other. The rule to write down: **`looks` must never grow a second geometry-over-time type.** If a look needs to move, it needs `burns`.

### `TARGET_SIZES`

`SOCIAL_SIZES` moves verbatim in content: `youtube` (1920, 1080) · `shorts` (1080, 1920) · `square` (1080, 1080) · `story` (1080, 1920) · `tiktok` (1080, 1920) [4].

Two observations on the move, offered as a judgement call rather than a finding. Three keys alias one value, and that is **correct** — they name an intent, not a shape, and a caller writing `"tiktok"` is documenting the deliverable. But `youtube` at 1920×1080 is not a social format at all; it is 1080p landscape. Since the move is deprecation-free and `mixing` has no external users for this, I recommend renaming the table **`TARGET_SIZES`** on the way across, keeping all five keys. Renaming is free exactly once and this is that once.

---

## 5. Family D — transitions, and why they are not `Effect`s

**A transition is not an `Effect` and must not be one.** Three reasons, each structural.

1. **It is binary, not unary.** A `Look` is an ordered stack of video→video functions; a transition takes two videos.
2. **It sits at a cut, and the cut is the caller's.** The kickoff's second exclusion is exactly this: `Effect.at` says *where a look applies*, never *where a cut is*. If a transition were an `Effect`, its `at` would be a cut, and the boundary would be gone on day one.
3. **It needs two labelled pads.** Note 05's Rule C1 — a compiled filter string references no container input index — is what lets a `Look` splice into any host [12]. A transition cannot honour that as an `Effect`; as its own type it honours it differently, by taking its two pad *labels* from the caller.

So `looks` ships a separate small frozen type:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Transition:
    """One named two-input blend, to be spliced at a cut the CALLER decided."""
    name: str                      # an xfade transition name, or "custom"
    duration_s: float = 0.5
    offset_s: float | None = None  # REQUIRED at compile time; supplied by the caller
    expr: str | None = None        # name == "custom" only
```

`offset_s` being caller-supplied and required is the structural guarantee that `looks` does not decide where the cut is. A `Transition` with `offset_s=None` refuses to compile.

**Compile target.** `[<a>][<b>]xfade=transition=<name>:duration=<d>:offset=<o>[<out>]` — `WEAK_COPYLEFT` (`xfade` has no `_filter_deps` line in `configure` [2]) · **INDEXED** (its output is a deterministic function of the two frames and the progress through the transition).

**The catalogue is `xfade`'s own enumeration, exposed wholesale: 58 named transitions (indices 0–57) plus `custom` (−1).** Curating that list would be arbitrary — they are one enum in one filter — and `custom` with `expr=` is a one-field seam for anything else.

### The six `mixing` transitions, mapped

This is the deflationary part, and it is the useful part.

| `mixing/video/video_concat.py` function | what it actually is | verdict |
|---|---|---|
| `crossfade_transition(duration=0.5)` | a crossfade | **IN** → `xfade=transition=fade` |
| `fade_through_black(duration=0.3)` | a dip to black | **IN** → `xfade=transition=fadeblack` |
| `overlap_blend(overlap=0.5)` | a crossfade that eats more footage | **OUT** — the transition is `fade`; "how much footage" is an EDL parameter, and the caller already supplies `offset_s` |
| `trim_first_frame_from_subsequent_clips()` | drop one frame per clip | **OUT** — not a transition at all; EDL hygiene |
| `trim_and_crossfade(duration=0.4)` | the two above, composed | **OUT as a unit** — its transition half is `fade`, its trim half is an EDL decision |
| `slow_motion_blend(ramp_duration=0.5)` | slow the tail and the head, changing total duration | **OUT** — temporal retiming *and* it changes duration, so it is doubly outside the boundary |

**Six functions become two transitions, three EDL decisions and one retime.** The two survivors are two of `xfade`'s 58, so the entire transition tier of `mixing` is subsumed by a filter muvid already calls 31 times [15]. That is the strongest evidence that the transitions belong in a vocabulary package rather than in an execution package.

---

## 6. The gradient-map LUT generator: the API, and the zero-dependency answer

### 6.1 Is the maths stdlib-feasible without numpy? Yes — measured, and byte-exact

The question decides whether the headline feature is in the zero-dependency tier, so I answered it by rewriting `mklut_b.py` [5] against stdlib only and diffing the output.

What the generator needs, and where stdlib provides it: hex → RGB (`int(…, 16)`) · ramp interpolation (`bisect.bisect_right` plus a lerp, replacing `np.interp`) · sRGB → linear (`**`) · linear → Y (three multiplies) · Y → L\* (a cube root and an affine) · RGB → hue and saturation (**`colorsys.rgb_to_hsv`**, which returns exactly the `(max−min)/max` saturation and the same hue the original computed by hand) · the accent's Gaussian weight (`math.exp`) · 35,937 formatted lines (`str` and one `"".join`).

Result, CPython 3.12.12, macOS 15 / arm64, 2026-09-02:

```
$ python3 stdlib_lut.py
33^3 in 0.141s
17^3 in 0.019s
65^3 in 1.109s
$ cmp stdlib.cube que_calor_b.cube && echo "BYTE IDENTICAL"
BYTE IDENTICAL
```

**The stdlib generator reproduces the shipped Que Calor `.cube` byte for byte — all 970,374 of them.** No numpy, no OpenCV, no Pillow. `colorsys` is the piece that makes it clean; without it the hue/saturation branch would be twenty lines of `if` and a likely source of divergence.

**So the headline feature is `Tier.PURE`** — note 06's top rung, an in-process implementation with no copyleft reach and no dependency at all [13]. That matters more than it first appears: it means the one thing `looks` is *for* runs at any ceiling, including a ceiling that forbids shelling out to ffmpeg entirely. Only the *application* of the LUT needs a backend.

**One capability does need an extra.** Extracting a ramp *from a reference image* needs k-means in CIELAB (that is what produced the Que Calor ramp — k=16 over 400,000 sampled pixels, 3,036,960 analysed [8]). That is not stdlib. The seam is clean, though, because **the extractor's output is data**: `ramp_from_image()` returns a list of `[L*, "#RRGGBB"]` pairs that you paste into the spec once, at authoring time. So extraction lives behind `looks[measure]`, is never on the runtime path, and a `Look` authored with it has no dependency on it. That is the right shape — the same shape `an` uses for its StylePack, where art direction is a *document* rather than a live computation.

### 6.2 The API

```python
"""Gradient-map look generation: an L*-indexed colour ramp compiled to a 3D LUT.

A gradient map is the right vehicle when the target's HUE TRACKS ITS LIGHTNESS
-- dark = oxblood, mid = crimson, light = coral -- and that is a property you
MEASURE before choosing a filter, never one you assume. The reference this was
built for had 92.0% of its chroma in one hue band, 0.0000% true black, 0.07%
true white and no outlines anywhere, so the classic "cartoonify" recipe
(bilateral filter plus adaptive-threshold black edges) would have been exactly
wrong.

Everything here is stdlib-only and side-effect free. :func:`cube_text` is a pure
function of its spec; :func:`materialize` is the only thing that touches a
filesystem, and it is deliberately separate so that ``compile()`` stays pure.
"""

from __future__ import annotations

import bisect
import colorsys
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

#: sRGB -> CIE Y luminance coefficients (Rec. 709 primaries, D65 white).
REC709_LUMA = (0.2126, 0.7152, 0.0722)
#: CIE L* has a linear segment below this Y; above it the transfer is a cube root.
LSTAR_LINEAR_KNEE = 0.008856
#: LUT grid sizes ``looks`` offers. ``lut3d`` accepts others; these are the ones
#: whose size/quality trade-off is measured (see the note's section 7).
CUBE_SIZES = (17, 33, 65)
DFLT_CUBE_SIZE = 33
#: The ``TITLE`` line of a generated ``.cube``. It lives in the SPEC rather than
#: in a separate argument, so that it enters the cache key like everything else:
#: two artifacts differing only by title must not collide, and a second channel
#: into the file's bytes that bypasses the key is how a cache starts lying.
DFLT_LUT_TITLE = "looks_gradient_map"
#: Bumped whenever this module's arithmetic changes. It enters the cache key, so
#: a bump invalidates every generated artifact -- nw's "lock, not receipt" rule.
GENERATOR_VERSION = 1


@dataclass(frozen=True, slots=True)
class Stop:
    """One ramp control point: a lightness, and the colour the map sends it to."""

    lstar: float
    color: str  # "#RRGGBB"

    def rgb(self) -> tuple[float, float, float]:
        """Unit-interval sRGB.

        >>> Stop(0.0, "#2E0C18").rgb()  # doctest: +ELLIPSIS
        (0.180..., 0.047..., 0.094...)
        """
        h = self.color.lstrip("#")
        return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


@dataclass(frozen=True, slots=True)
class Ramp:
    """An L*-indexed colour ramp, sampled to a 256-entry table on construction."""

    stops: tuple[Stop, ...]

    def __post_init__(self) -> None:
        if len(self.stops) < 2:
            raise ValueError("a ramp needs at least two stops")
        if list(self.stops) != sorted(self.stops, key=lambda s: s.lstar):
            raise ValueError("ramp stops must be sorted by lstar")

    @classmethod
    def of(cls, *pairs: tuple[float, str]) -> "Ramp":
        """Build from ``(lstar, hex)`` pairs.

        >>> Ramp.of((0.0, "#2E0C18"), (100.0, "#FEF0DC")).sample(50.0)  # doctest: +ELLIPSIS
        (0.588..., 0.494..., 0.478...)
        """
        return cls(tuple(Stop(l, c) for l, c in pairs))

    def sample(self, lstar: float) -> tuple[float, float, float]:
        """Linear interpolation between the two stops bracketing ``lstar``."""
        ls = [s.lstar for s in self.stops]
        j = min(max(bisect.bisect_right(ls, lstar) - 1, 0), len(ls) - 2)
        span = ls[j + 1] - ls[j]
        t = 0.0 if span <= 0 else min(max((lstar - ls[j]) / span, 0.0), 1.0)
        a, b = self.stops[j].rgb(), self.stops[j + 1].rgb()
        return tuple(a[k] + t * (b[k] - a[k]) for k in range(3))

    def to_params(self) -> list[list[Any]]:
        """The JSON form that goes into ``Effect.params``."""
        return [[s.lstar, s.color] for s in self.stops]


@dataclass(frozen=True, slots=True)
class Accent:
    """A second ramp that survives the map, keyed on input hue and saturation.

    A pure gradient map erases every off-axis colour. When the target keeps some
    -- the Que Calor reference keeps 9.35% of its pixels as warm accents, hue
    44-92 deg, and no green, blue or cyan at all -- a second ramp blended in by
    hue distance is what preserves them.
    """

    ramp: Ramp
    hue_deg: float = 52.0
    hue_width_deg: float = 14.0
    sat_floor: float = 0.42
    sat_span: float = 0.30
    strength: float = 0.70

    def weight(self, hue_deg: float, saturation: float) -> float:
        """Blend weight in [0, 1] for an input pixel's hue and saturation."""
        dh = ((hue_deg - self.hue_deg + 180.0) % 360.0) - 180.0
        sat = min(max((saturation - self.sat_floor) / self.sat_span, 0.0), 1.0)
        return sat * math.exp(-0.5 * (dh / self.hue_width_deg) ** 2) * self.strength


@dataclass(frozen=True, slots=True)
class ToneShape:
    """The S-curve applied to L* BEFORE the map.

    Either a contrast/lift pair, or an explicit monotone ``curve`` of
    ``(lstar_in, lstar_out)`` points -- which is how a measured tone match
    (``tone_match``) folds into the LUT instead of costing a second filter.
    """

    contrast: float = 1.0
    lift: float = 0.0
    curve: tuple[tuple[float, float], ...] = ()

    def apply(self, lstar: float) -> float:
        if self.curve:
            xs = [p[0] for p in self.curve]
            j = min(max(bisect.bisect_right(xs, lstar) - 1, 0), len(xs) - 2)
            span = xs[j + 1] - xs[j]
            t = 0.0 if span <= 0 else (lstar - xs[j]) / span
            out = self.curve[j][1] + t * (self.curve[j + 1][1] - self.curve[j][1])
        else:
            out = (lstar - 50.0) * self.contrast + 50.0 + self.lift
        return min(max(out, 0.0), 100.0)


def lstar(r: float, g: float, b: float) -> float:
    """CIE L* of a unit-interval sRGB triple.

    >>> round(lstar(0.0, 0.0, 0.0), 4), round(lstar(1.0, 1.0, 1.0), 4)
    (0.0, 100.0)
    """

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    y = sum(k * lin(c) for k, c in zip(REC709_LUMA, (r, g, b)))
    f = y ** (1 / 3) if y > LSTAR_LINEAR_KNEE else 7.787 * y + 16 / 116
    return 116 * f - 16


def map_rgb(
    r: float,
    g: float,
    b: float,
    *,
    ramp: Ramp,
    accent: Accent | None = None,
    tone: ToneShape = ToneShape(),
) -> tuple[float, float, float]:
    """One pixel through the gradient map. Pure; the whole look is this function."""
    ln = tone.apply(min(max(lstar(r, g, b), 0.0), 100.0))
    q = min(max(int(ln / 100.0 * 255), 0), 255)
    base = ramp.sample(q / 255.0 * 100.0)
    if accent is None:
        return base
    h, s, _v = colorsys.rgb_to_hsv(r, g, b)
    w = accent.weight(h * 360.0, s)
    hot = accent.ramp.sample(q / 255.0 * 100.0)
    return tuple(min(max(base[k] * (1 - w) + hot[k] * w, 0.0), 1.0) for k in range(3))


def gradient_map(
    *,
    ramp: Ramp,
    accent: Accent | None = None,
    tone: ToneShape = ToneShape(),
    size: int = DFLT_CUBE_SIZE,
    interp: str = "tetrahedral",
    title: str = DFLT_LUT_TITLE,
) -> dict[str, Any]:
    """The JSON-able ``Effect.params`` for a gradient-map effect.

    The dataclasses above are an AUTHORING convenience. What reaches
    ``Effect.params`` is plain JSON, because note 03's canonical blob raises on
    anything it cannot represent faithfully -- and a Look that cannot be hashed
    cannot be cached, diffed or shipped.
    """
    if size not in CUBE_SIZES:
        raise ValueError(f"size must be one of {CUBE_SIZES}, got {size!r}")
    spec: dict[str, Any] = {
        "ramp": ramp.to_params(), "size": size, "interp": interp, "title": title,
    }
    if accent is not None:
        spec["accent"] = {
            "ramp": accent.ramp.to_params(),
            "hue_deg": accent.hue_deg,
            "hue_width_deg": accent.hue_width_deg,
            "sat_floor": accent.sat_floor,
            "sat_span": accent.sat_span,
            "strength": accent.strength,
        }
    if tone != ToneShape():
        spec["tone"] = (
            {"curve": [list(p) for p in tone.curve]}
            if tone.curve
            else {"contrast": tone.contrast, "lift": tone.lift}
        )
    return spec


def cube_text(spec: Mapping[str, Any]) -> str:
    """Render the ``.cube`` for a spec. Pure: no I/O, no clock, no randomness.

    A pure function of the spec ALONE -- there is no second argument that can
    change the bytes, which is what makes :func:`cube_key` a true content
    address rather than an approximation of one.
    """
    ramp = Ramp(tuple(Stop(l, c) for l, c in spec["ramp"]))
    acc_spec = spec.get("accent")
    accent = (
        Accent(
            ramp=Ramp(tuple(Stop(l, c) for l, c in acc_spec["ramp"])),
            **{k: v for k, v in acc_spec.items() if k != "ramp"},
        )
        if acc_spec
        else None
    )
    t = spec.get("tone", {})
    tone = ToneShape(
        contrast=t.get("contrast", 1.0),
        lift=t.get("lift", 0.0),
        curve=tuple(tuple(p) for p in t.get("curve", ())),
    )
    n = spec.get("size", DFLT_CUBE_SIZE)
    title = spec.get("title", DFLT_LUT_TITLE)
    step = 1.0 / (n - 1)
    out = [f'TITLE "{title}"\nLUT_3D_SIZE {n}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n']
    for bi in range(n):  # .cube order: red varies fastest, blue slowest
        for gi in range(n):
            for ri in range(n):
                out.append(
                    "%.6f %.6f %.6f\n"
                    % map_rgb(
                        ri * step, gi * step, bi * step,
                        ramp=ramp, accent=accent, tone=tone,
                    )
                )
    return "".join(out)


def cube_key(spec: Mapping[str, Any]) -> str:
    """Content address of the artifact a spec generates.

    Keyed on the generator's identity as well as the spec, so a change to this
    module's arithmetic invalidates every cached ``.cube`` rather than serving a
    stale one forever.

    >>> cube_key({"ramp": [[0.0, "#000000"], [100.0, "#FFFFFF"]], "size": 17})
    'f59aea5c65e94cb20949e6af0de9a739'
    """
    blob = json.dumps(
        {"generator": "looks.gradient_map", "version": GENERATOR_VERSION, "spec": spec},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def cache_dir() -> Path:
    """Where generated LUTs live. Regenerable, so a CACHE dir, never app data."""
    env = os.environ.get("LOOKS_CACHE_DIR")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CACHE_HOME")
    return (Path(xdg) if xdg else Path.home() / ".cache") / "looks" / "lut3d"


def materialize(spec: Mapping[str, Any], *, into: Path | None = None) -> Path:
    """Write the ``.cube`` for ``spec`` and return its path. The ONLY I/O here.

    Content-addressed, so a second call is a no-op, two Looks sharing a ramp
    share one file, and garbage collection is "delete anything no plan names".
    Written to a temp file and ``os.replace``d, so a concurrent reader never
    sees a half-written LUT.
    """
    d = into or cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{cube_key(spec)}.cube"
    if path.exists():
        return path
    tmp = path.with_suffix(".cube.tmp")
    tmp.write_text(cube_text(spec), encoding="ascii")
    os.replace(tmp, path)
    return path
```

Two shape decisions in that listing are load-bearing and easy to get wrong.

**The dataclasses are authoring sugar; `Effect.params` holds plain JSON.** Note 03's canonical blob *raises* on a value it cannot represent faithfully rather than falling back to `repr` [10], and a `Look` that cannot be hashed cannot be cached, diffed or shipped. So `gradient_map(...)` returns a dict of lists and floats, and `cube_text` reconstructs the dataclasses on the way in. Putting a `Ramp` instance into `params` would work right up until someone tried to serialise a `Look`.

**`compile()` stays pure and `materialize()` is separate.** This is `burns`'s "the spec never touches I/O" taken one step further [10], and it is what keeps note 05's rule intact — `looks` emits argv as data and someone else runs it [12]. A compiled `Step` for a gradient map carries `{"cube_key": …, "cube_source": {…spec…}}`; `materialize(plan)` walks the plan, writes what is missing, and returns a plan with `file=` filled. A caller who wants to inspect or cost a `Look` never writes a byte.

**And the `title` lives in the spec rather than in a `cube_text(spec, *, title=…)` argument**, which was the shape I wrote first. A second channel into the file's bytes that bypasses `cube_key` means two artifacts differing only by title collide in the cache — I found it by writing the LUT through `materialize` and getting a file one byte larger than `cube_text` had returned. `cube_text` is now a pure function of the spec *alone*, which is what makes `cube_key` a true content address rather than an approximation of one.

### 6.3 The listing above was executed

The federation's working rule 11 is that code in a design document which has never run is a hypothesis [12]. So this note's Python was extracted from the fence, written to a file, and run.

```
$ python3 -m doctest gradient_module.py && echo "ALL DOCTESTS PASS"
ALL DOCTESTS PASS
$ python3 rebuild_que_calor.py
spec JSON: 566 bytes
cube_text: 970374 bytes in 0.402s
BYTE IDENTICAL to the shipped que_calor_b.cube: True
materialize -> 8dd26bcfa92574a1062454ec32bdf677.cube  970374 bytes  idempotent=True  matches_cube_text=True
full Que Calor look through ffmpeg 8.1: OK
ramp JSON -> .cube expansion: 1714x
title enters the key: True
```

Every doctest passes under `ELLIPSIS` alone — no `NORMALIZE_WHITESPACE`, no `IGNORE_EXCEPTION_DETAIL` — matching note 03's standard [10]. The 306-line module rebuilds the shipped Que Calor LUT byte for byte, `materialize` is idempotent and its bytes equal `cube_text`'s, and ffmpeg 8.1 runs the full look (`lut3d` + `posterize`) off the generated file.

**One honest regression to record: the API costs 0.402 s where the flat script costs 0.141 s**, a 2.9× slowdown for the same 970,374 bytes. The cause is that `Ramp.sample` re-reads `self.stops` and calls `Stop.rgb()` — re-parsing hex — on all 35,937 samples, where `mklut_b.py` precomputed a 256-entry table once [5]. The fix is to hoist that table into `__post_init__` as a non-compare cached field, which is the shape `burns.BurnsPath` already uses for its cached easing [10]. I have left the listing in its readable form and am recording the number rather than quietly optimising it, because 0.4 s is still far below anything that matters here and the readable version is the better thing to review.

---

## 7. How a `.cube` is managed — the decision, with the sizes that force it

**Decision: inline the ramp in the spec; generate the `.cube` at materialize time into a content-addressed cache. Referencing an external file is a separate effect (`lut3d`) which records the file's `content_sha256` and its `licence`.**

Five reasons, four of them measured.

**1. The spec is 1714× smaller than the artifact it generates.** Measured exactly, through the API in §6.2 — the Que Calor `.cube` is 970,374 bytes, decomposing as a 75-byte header plus 35,937 entries × 27 bytes each (`"%.6f %.6f %.6f\n"` is 8+1+8+1+8+1). The spec that generates it — 14 ramp stops, 7 accent stops, six accent scalars, `tone`, `size`, `interp`, `title` — serialises to **566 bytes** of compact JSON.

| grid | entries | `.cube` bytes | as text |
|---|---|---|---|
| 17³ | 4,913 | 132,726 | 130 KiB |
| **33³** | **35,937** | **970,374** | **948 KiB** |
| 65³ | 274,625 | 7,414,950 | 7.07 MiB |

A 65³ LUT inlined into a `Look` document is 7 MiB of base64 in something meant to be diffed. A 33³ is 948 KiB of it. Neither is a document.

**2. Generation is cheaper than fetching.** 0.141 s for 33³ and 0.019 s for 17³ in the flat form, 0.402 s for 33³ through the API as written (§6.3) — a lower cost than reading 948 KiB from any store that is not local disk, and comparable to reading it from local disk once you count the parse. And it is paid **once per distinct spec**, because the cache is content-addressed.

**3. A path is not content, so a `Look` referencing one is not self-contained.** This is note 03's argument for a persistable spec [10]; the same logic that rejects a callable easing parameter rejects a filesystem handle in `params`.

**4. Content addressing makes the cache trivially correct.** Two `Look`s with the same ramp share one file. GC is "delete anything no live plan names". There is no invalidation problem because there is no mutable name. And `GENERATOR_VERSION` inside the key means a change to the arithmetic invalidates everything rather than serving a stale LUT forever — which is note 05's rule 5 and nw's `impl_version` discipline applied to a generated artifact [4][12].

**5. The clip-aware case falls out for free.** If `tone` resolves per clip, the resolved spec differs per clip, so the key differs, so you get one LUT per clip with no extra machinery and no name collisions.

**Cache key.** `sha256(json({"generator": "looks.gradient_map", "version": GENERATOR_VERSION, "spec": <resolved spec>}, sort_keys=True, separators=(",",":"), allow_nan=False))[:32]`. Three details: `sort_keys` because dict order must not enter the key; `allow_nan=False` because a NaN would produce a key for a LUT that cannot be written; the 32-hex truncation because 128 bits is beyond sufficient for a per-user cache and a 64-character filename is unpleasant.

**Cache location.** `$LOOKS_CACHE_DIR` → `$XDG_CACHE_HOME/looks/lut3d` → `~/.cache/looks/lut3d`. It is regenerable, so it is a *cache* and never app data, and it is never inside the package directory.

**Write atomically.** Temp file plus `os.replace`, the same discipline `nw.jobs` uses for its store writes [4]. A half-written `.cube` read by a concurrent ffmpeg is a silently wrong picture, not an error.

### 7.1 The alternative artifact format, and when it wins

There is a second way to carry a LUT that is worth recording because it is **26× smaller at the same grid density**: a **hald CLUT** — the lookup encoded as an ordinary image. ffmpeg both generates them (`haldclutsrc`) and applies them (`haldclut`), and level *L* yields an *L*³ × *L*³ image, i.e. *L*⁶ entries and a cube dimension of *L*².

| hald level | cube dimension | entries | PNG bytes (measured) | comparable `.cube` text |
|---|---|---|---|---|
| 4 | 16³ | 4,096 | 7,269 | 132,726 (17³) |
| 6 | 36³ | 46,656 | 59,012 | — |
| **8** | **64³** | **262,144** | **282,100** | **7,414,950 (65³)** |
| 10 | 100³ | 1,000,000 | 944,481 | — |

**A 64³ hald PNG is 282 KB where a 65³ `.cube` is 7.41 MB.** For v1 `looks` still generates `.cube`, for three reasons: it is text and therefore diffable and reviewable; writing a PNG from stdlib is possible but is real code (`zlib` plus a hand-rolled chunk writer) where writing text is a `join`; and 33³ at 948 KiB is not a problem worth solving yet. But the hald format is the right answer the day a caller wants 65³, and §8 shows it is also the right answer for a different problem.

---

## 8. Fusing a run of `PIXEL` effects — a measured 3.9×, with one trap

This arrived unbidden and it changes the cost model. **A maximal run of `PIXEL` effects is, by definition, one function from a colour to a colour — so it can be baked into a single lookup.**

ffmpeg can do this without any new machinery, and inside a *simple* `-vf` graph, because the second source is a filter rather than a container input — which is exactly what note 05's Rule C1 permits [12]:

```
haldclutsrc=8:r=1:d=1,<the pixel run>,null[c];null[m];[m][c]haldclut=clut=first:shortest=0
```

Measured at 1280×720, 60 frames, best of 3, `-f null -`, on an 8-filter pixel stack (`lutrgb` gamma → `curves` → `hue` → `colortemperature` → `colorbalance` → `colorlevels` → `selectivecolor` → `lut3d`):

| form | ms/frame | speedup |
|---|---|---|
| direct — all 8 filters per frame | **14.25** | 1.0× |
| fused in-graph, `haldclutsrc=8:r=1:d=1` + `haldclut=clut=first` | **6.69** | 2.1× |
| fused into a **materialised hald PNG**, applied with `movie=…` + `haldclut=clut=first` | **3.65** | **3.9×** |

**The `r=1:d=1` and `clut=first` are the whole difference between a win and a loss, and I measured the loss first.** Without them, `haldclutsrc` emits a fresh 512×512 CLUT frame at 25 fps and `haldclut` re-processes it for every one — the naive form came out at 16.30 ms/frame, *slower* than the direct chain. Anyone reproducing this needs those two options, and an unbounded `haldclutsrc` in a `-f null -` pipeline never terminates.

**Accuracy at level 8 (64³), against the direct chain, one frame:**

| fused run | max diff | mean diff | share > 2/255 |
|---|---|---|---|
| `curves=preset=vintage` (single smooth filter) | 2/255 | 0.576 | 0.000% |
| the 8-filter smooth stack, level 4 (16³) | 36/255 | 0.233 | 0.586% |
| the 8-filter smooth stack, level 6 (36³) | 20/255 | 0.150 | 0.298% |
| the 8-filter smooth stack, **level 8 (64³)** | 18/255 | **0.096** | **0.300%** |
| the 8-filter smooth stack, level 10 (100³) | 17/255 | 0.040 | 0.282% |

The max error stops improving past level 8 while the mean keeps falling, which says the residual max is at a few saturated corners where `hue` and `selectivecolor` are locally non-smooth, not at the grid resolution. Level 8 is the operating point.

**The trap, and it is the same rule as §1.3.** Fusing a run that *ends in a quantiser* is measurably wrong:

| fused run, level 8 | max diff | mean | share > 2/255 |
|---|---|---|---|
| `lut3d` + `posterize`, `interp=tetrahedral` (the default) | 21/255 | 0.390 | **6.123%** |
| `lut3d` + `posterize`, `interp=nearest` | 18/255 | 0.048 | 0.265% |

Tetrahedral interpolation of a quantised lookup **un-quantises it** — it manufactures the intermediate values `posterize` exists to remove, on 6% of samples. `interp=nearest` preserves the step function and repairs it. So the fusion rule for v1 has two clauses: *fuse a maximal run of `PIXEL` effects; if any effect in the run is a quantiser, the fused lookup must be applied with `interp=nearest`.* Both clauses are testable against the unfused chain, which is how this was found.

**What this means for the design, stated conservatively.** Fusion is a **compile-time optimisation over an existing plan**, not a new effect and not a new type: it rewrites a run of `FilterStage`s into one `FilterStage` plus one generated artifact, using the same content-addressed cache §7 already needs. It is a v1.1 candidate rather than a v1 feature — the 3.9× is real but the correctness rule needs a test suite behind it, and `looks` should not ship an optimisation whose failure mode is a subtly wrong picture. Recording it here is the point; the numbers are the argument for doing it, and the quantiser row is the argument for not doing it hastily.

---

## 9. Deliberately out of v1

| out | family it would have joined | why |
|---|---|---|
| `normalize` (auto-levels) | grade | **ADAPTIVE**, measured: 67.37% of a shared region changed by up to 204/255 when unrelated content changed (§1.2). This is the flicker mode the whole Que Calor design exists to avoid. Reachable later behind a mandatory `smoothing` and a documented flicker risk; the smoothed variant is **unverified**. |
| `colorcorrect` with `analyze` ∈ {average, minmax, median} | grade | ADAPTIVE by the filter's own construction — per-frame white balance. `analyze=manual` is what `white_balance` uses and is IN. My probe did not detect it (§1.2) and that is a limit of the probe, not an acquittal. |
| `elbg` (colour quantisation) | look | ADAPTIVE (15.04% of a shared region changed) **and** 64.85 ms/frame measured — 9× the entire Que Calor chain. "Per-frame palette quantisation" is named in `mklut.py` as a flicker failure mode [5]. `posterize` + `gradient_map` do the job statelessly. |
| motion blur, `tmix`, `tblend`, `atadenoise`, `hqdn3d`, `dctdnoiz`, `fftdnoiz`, `nlmeans` | any | **TEMPORAL.** Structurally incompatible with the federation's execution model: muvid renders one bounded ffmpeg process per cut, so a temporal filter would see a hard boundary at every cut and produce an artefact at exactly 50 places in the Que Calor edit. Not a preference. |
| `minterpolate`, optical-flow retime, speed ramps (`slow_motion_blend`) | transitions | Changes **duration**, therefore an EDL decision, therefore outside the boundary `Effect.at` draws. |
| AnimeGANv2, White-box Cartoonization, any neural restyler | look | **`FIELD_RESTRICTED`** — non-commercial, which note 06 puts off the ladder entirely where no `max_tier` can reach it [13]. Separately: per-frame neural restyling is the flicker mode `mklut.py` names first [5]. Two independent disqualifications. |
| `trim_first_frame_from_subsequent_clips`, `overlap_blend`, `trim_and_crossfade` | transitions | EDL decisions wearing a transition's clothes (§5). |
| `drawtext`, titles, `overlay`, watermarks | — | Compositing and canvas, not stylization. That is `mixing`'s and `muvid`'s job and both already do it. |
| `despill`, chroma key | — | A matte operation. Belongs with compositing; nothing in the federation asks for it. |
| `perspective`, `rotate`, `shear` | geometry | `perspective` is GPL-only [2]; none of the three has a consumer; and anything that varies over time is `burns` (§4). |
| `pseudocolor` | look | It is a false-colour *instrument* (its presets are `magma`, `viridis`, `turbo` — scientific colormaps), not a look. A caller who wants a two-tone map wants `gradient_map`. |
| `boxblur`, `smartblur`, `histeq`, `hqdn3d` | various | Not out — **available at `COPYLEFT_TOOL`**, and each with its LGPL-clean alternative named where one exists. Worth stating that **`smartblur` has none**: it is the only edge-aware blur ffmpeg ships outside `bilateral`, and it is GPL-only. |
| a convenience `looks.render(clip, look)` | — | The kickoff's first exclusion, and note 04 turns it into a *testable invariant* rather than a rule of thumb: **every ffmpeg process `looks` starts ends in `-f null -`** [11]. That makes auto-tuning in scope and a deliverable structurally impossible. |

---

## 10. What the federation's consumers actually need

Grounding, so the catalogue is not designed against an imagined caller. Counted by `rg` over `muvid` today:

| filter | uses in muvid | catalogue home |
|---|---|---|
| `xfade` | 31 | `Transition` (§5) |
| `crop` | 22 | `crop` |
| `scale` | 13 | `fit` |
| `pad` | 10 | `fit` |
| `colorchannelmixer` | 9 | `saturation`, and `fit(mode="social")`'s dim |
| `gblur` | 4 | `blur`, `halation`, `fit(mode="social")` |
| `eq` | **1** | the finding in §4 — GPL-only, and the wrong knob |

Every one of those is in family C or D. So **the geometry-and-transitions half of this catalogue has a real consumer with 90 call sites today**, and the grade-and-look half has exactly one consumer — the Que Calor look — which is the honest position for a v1 and the reason the look family is designed against a measurement rather than against a survey.

`mixing` contributes the vocabulary (`SOCIAL_SIZES`, the four resize modes, the six transitions) and none of the implementation. `reelee`'s panels want the grade family — a panel set that has to look like one film is `match_clip` with `group=` — and want it through `nw`, which means through the pure-data plan rather than through a render call; the layering `lacing → nw → falaw.Plan → backends` puts `looks` beside `falaw.Plan` as a *second* pure-data compiler, not below it. **Unverified**: I did not read reelee's panel code in this session and that last sentence is inference from the group's stated layering, not from its source.

---

## 11. Summary tables

### 11.1 The catalogue

| # | family | name | tier(s) | frame dep. | clip-aware | primary compile target | verified |
|---|---|---|---|---|---|---|---|
| 1 | grade | `gamma` | WEAK / COPYLEFT_TOOL | PIXEL | conventionally | `lutyuv` / `lutrgb` / `eq=gamma` | OK |
| 2 | grade | `exposure` | WEAK | PIXEL | no | `exposure=exposure=S` | OK |
| 3 | grade | `contrast` | WEAK / COPYLEFT_TOOL | PIXEL | no | `curves=…:interp=pchip` / `eq=contrast` | OK |
| 4 | grade | `saturation` | WEAK ×2 / COPYLEFT_TOOL | PIXEL | no | `colorchannelmixer` (s ≤ 2.077) / `hue=s` | OK |
| 5 | grade | `white_balance` | WEAK | PIXEL | no | `colortemperature` | OK |
| 6 | grade | `levels` | WEAK | PIXEL | no | `colorlevels` | OK |
| 7 | grade | `tone_match` | WEAK | PIXEL | **yes** | `curves=…:interp=pchip` | OK |
| 8 | grade | `match_clip` | WEAK (composite) | composite | **yes** | emits 1, 4, 6 | design only |
| 9 | look | **`gradient_map`** | **PURE** + WEAK | PIXEL | no | stdlib `.cube` → `lut3d` | OK |
| 10 | look | `lut3d` | WEAK (+ file's own terms) | PIXEL | no | `lut3d=file=…` | OK |
| 11 | look | `posterize` | WEAK | PIXEL | no | `lutrgb=…trunc…` | OK |
| 12 | look | `flatten` | **COPYLEFT_SHIPPED** / WEAK / COPYLEFT_TOOL | FRAME | **yes** | `cv2.pyrMeanShiftFiltering` / `bilateral` / `smartblur` | OK |
| 13 | look | `monochrome` | WEAK | PIXEL | no | `monochrome` | OK |
| 14 | look | `colorize` | WEAK | PIXEL | no | `colorize` | OK |
| 15 | look | `bleach_bypass` | WEAK | PIXEL | no | `blend=all_mode=bleach` | OK |
| 16 | look | `cross_process` | WEAK | PIXEL | no | `curves=preset=cross_process` | OK |
| 17 | look | `halation` | WEAK | FRAME | no | `split`+`lutyuv`+`gblur`+`blend=screen` | OK |
| 18 | look | `vignette` | WEAK | FRAME | no | `vignette` | OK |
| 19 | look | `chromatic_aberration` | WEAK | FRAME | no | `rgbashift` | OK |
| 20 | look | `grain` | WEAK | **INDEXED** | no | `noise=alls=…:allf=t+u` | OK |
| 21 | look | `deband` | WEAK | FRAME | no | `deband` | OK |
| 22 | look | `blur` / `sharpen` | WEAK | FRAME | `sharpen`: yes | `gblur` / `unsharp` | OK |
| 23 | look | `film_stock` | *(the file's own terms)* | PIXEL | no | registry → `lut3d`; **ships empty** | design only |
| 24 | geom | `fit` | WEAK | FRAME | no | `scale`/`pad`/`crop`/`split`+`overlay` | OK ×4 |
| 25 | geom | `crop` | WEAK | FRAME | no | `crop` | OK |
| 26 | geom | `pad` | WEAK | FRAME | no | `pad` | OK |
| — | trans | `Transition` (58 + custom) | WEAK | INDEXED | no | `xfade=transition=…` | OK |

Twenty-four names in three families plus the `Transition` type, of which twenty-two have a verified compile target today and two (`match_clip`, `film_stock`) are design-complete but unimplemented by construction.

### 11.2 Measured costs, 1280×720, ffmpeg 8.1, best of 3, `-f null -`

| chain | ms/frame |
|---|---|
| *decode only* (`null`) | 1.40 |
| `grain` (`noise=alls=8:allf=u`) | 1.55 |
| `contrast` (`curves=preset=vintage`) | 2.03 |
| `sharpen` (`unsharp`) | 2.13 |
| `chromatic_aberration` (`rgbashift`) | 2.14 |
| `vignette` | 2.54 |
| `gradient_map` (`lut3d`) | 4.04 |
| `deband` | 4.52 |
| **`gradient_map` + `posterize` — the Que Calor look, LUT half** | **7.22** |
| `blur` (`gblur=sigma=24:steps=3`) | 8.23 |
| `halation` | 9.00 |
| 8-filter pixel stack, direct | 12.91 – 14.25 |
| 8-filter pixel stack, fused via materialised hald | **3.65** |
| `elbg=l=16` (**out of v1**) | 64.85 |

For scale: `flatten` at the shipped mean-shift setting is ~67 ms/frame in-process (cv2 5.0.0, 1280×720, this machine), i.e. roughly 9× the entire LUT half of the look — which is why `flatten` is where the clip-aware resolver earns its cost, and why note 03's CPU-second cost unit needs to distinguish the two halves rather than quoting one number for the look [10].

---

## 12. What I could not verify

- **`normalize=smoothing=N`.** My Probe B renders one frame per source, so it cannot exercise temporal smoothing. The `smoothing=30` row in §1.2 is **not a fair test** and I make no claim about whether smoothing makes `normalize` usable.
- **`colorcorrect=analyze=average`'s adaptivity.** The probe found nothing at a 0.7%-of-frame perturbation. The filter is content-adaptive by construction, so the probe is a lower bound; treating this as an acquittal would be wrong.
- **`bleach_bypass` under fusion.** I verified it compiles and runs; I did not test whether its `split`/`format=gray`/`blend` form survives the §8 hald fusion, so its `PIXEL` classification is a *semantic* one and its fusability is **unverified**.
- **The GPL filter list beyond `configure`.** I fetched `release/8.1`'s `configure` (8,840 lines, branch tip on 2026-09-02) and extracted 33 `*_filter_deps` entries naming `gpl`, plus `lensfun` under `version3` and no filter under `nonfree`. I did **not** independently diff it against an LGPL build in this session — sibling note 06 did that against `av` 16.0.1's bundled libavfilter and found 32 of the 33 reachable, `boxblur_opencl` needing OpenCL [13], and I am relying on that.
- **Every OpenCV licence claim.** The `COPYLEFT_SHIPPED` tier on `cv2.pyrMeanShiftFiltering` is note 05's and note 06's finding [12][13], not re-measured here. I confirmed only that `cv2` imports at version 5.0.0 in this interpreter, which is a *different* version from the one those notes assessed (4.13.0) — so **the tier of the cv2 in this particular environment is unverified**, and the catalogue must resolve it at compile time rather than assume it, which is what note 06's design already requires.
- **reelee's panel requirements** (§10) are inferred from the group's stated layering, not read from source.
- **The Adobe Cube LUT specification** [14] is cited by name; I did not fetch it. What I verified is empirical: ffmpeg 8.1's `lut3d` reads the file this generator writes, and the generator reproduces the shipped one byte for byte.

---

## REFERENCES

[1] [FFmpeg 8.1 filters documentation](https://ffmpeg.org/ffmpeg-filters.html) — and, authoritatively for this note, the local `ffmpeg -hide_banner -h filter=<name>` output on ffmpeg 8.1 (homebrew `8.1_1`), from which every parameter name, type, default and range quoted above was read on 2026-09-02. `ffmpeg -filters` reports 489 lines, 268 of them video→video.

[2] [FFmpeg `release/8.1` `configure`](https://github.com/FFmpeg/FFmpeg/blob/release/8.1/configure) — fetched 2026-09-02, 8,840 lines. Source of the GPL-gated filter list (33 `*_filter_deps` entries naming `gpl`: `blackframe boxblur boxblur_opencl colormatrix cover_rect cropdetect delogo eq find_rect fspp histeq hqdn3d interlace kerndeint mcdeint mpdecimate mptestsrc nnedi owdenoise perspective phase pp7 pullup repeatfields sab signature smartblur spp stereo3d super2xsai tinterlace uspp vaguedenoiser`), of the fact that `bilateral`, `nlmeans`, `xfade`, `lut3d`, `haldclut`, `curves`, `colorlevels`, `noise`, `vignette`, `gblur`, `deband`, `colorize`, `monochrome`, `colortemperature`, `colorcorrect`, `colorcontrast`, `selectivecolor`, `exposure`, `pseudocolor`, `rgbashift`, `chromashift`, `blend`, `crop`, `pad` and `fade` carry **no** GPL dependency, and of `lensfun` being the only `version3` filter and none being `nonfree`.

[3] [`muvid/visualize/visuals.py`](file:///Users/thorwhalen/Dropbox/py/proj/t/muvid/muvid/visualize/visuals.py) — the `VisualPlan` / `register_visual` shape `looks` extracts and generalises from audio→video to video→video.

[4] [`nw` — `Transform`, `impl_version`, `transform_catalog()`, atomic store writes](file:///Users/thorwhalen/Dropbox/py/proj/t/nw/CLAUDE.md) — the registry and identity discipline the catalogue borrows, including "`impl_version` is a lock, not a receipt".

[5] [`~/Downloads/que_calor/work/style/mklut_b.py`](file:///Users/thorwhalen/Downloads/que_calor/work/style/mklut_b.py) — the shipped gradient-map generator, and the source of the ramp, the accent parameters, the flicker argument, and the "a LUT is per-pixel and stateless, so it cannot flicker" claim.

[6] [`~/Downloads/que_calor/work/style/render_v2c.py`](file:///Users/thorwhalen/Downloads/que_calor/work/style/render_v2c.py) — the per-clip mean-shift parameters (`c01`/`c02` at 0.5/12/60, `c03` at 0.75/12/40), the posterise step of 18, and the measured commentary on scale versus colour radius.

[7] [`~/Downloads/que_calor/work/style/tonematch.py`](file:///Users/thorwhalen/Downloads/que_calor/work/style/tonematch.py) — the histogram-matching technique `tone_match` generalises, including its `np.maximum.accumulate` monotonicity enforcement.

[8] [`~/Downloads/que_calor/work/palette/palette.md`](file:///Users/thorwhalen/Downloads/que_calor/work/palette/palette.md) — the measured reference palette: 92.0% of chroma in one hue band, 0.0000% true black, 0.07% true white, off-axis accents 9.35% of pixels at hue 44°–92°, no green/blue/cyan anywhere, and the k=8/12/16 tables the ramp defaults come from.

[9] [`~/Downloads/que_calor/how_the_video_got_made__technical.md`](file:///Users/thorwhalen/Downloads/que_calor/how_the_video_got_made__technical.md) — "gamma, never a brightness offset"; the V2a→V2b shadow-floor correction (16.2% at L\* 0–5 against the reference's 0.3%; histogram distance 46.7 → 32.0 pp); the V2b→V2c per-clip scale correction (spread 2.98× → 1.59×); the location-aware grade target; the flicker measurement at 0.89–1.12× the source's own.

[10] `looks` research note 03 — `docs/research/03_spec_type.md` — `Effect` / `Look` / `ImplRef` / `Step` / `LookPlan` / `Ref`, the rule that the tier is declared by the implementation and never by the request, and the CPU-second cost unit.

[11] `looks` research note 04 — `docs/research/04_clip_aware_resolution.md` — the zero-dependency measurement path, the k=5 probe budget, the two-pointer sweep, the luma-space trap, the `SourceMap` type, and the `-f null -` invariant that makes `looks.render()` structurally impossible.

[12] `looks` research note 05 — `docs/research/05_compilation_and_backends.md` — `FilterStage` / `FrameStage` / `RenderedStage`, the `Backend` Protocol, Rule C1 (no container input index), the colour-contract refusal, the ordering rule, and the OpenCV wheel finding.

[13] `looks` research note 06 — `docs/research/06_licence_tiers.md` — the `Tier` ladder (`PURE` · `PERMISSIVE` · `WEAK_COPYLEFT` · `COPYLEFT_TOOL` · `COPYLEFT_SHIPPED`), the off-ladder `FORBIDDEN` and `FIELD_RESTRICTED` verdicts, the `COPYLEFT_TOOL` default ceiling, the resolved-not-declared tier, and the `opencv-contrib-python` licence contradiction.

[14] [Adobe Cube LUT Specification 1.0](https://kono.phpage.fr/images/9/94/Adobe-cube-lut-specification-1.0.pdf) — the `.cube` format. **Cited by name; not fetched in this session.** What is verified is that ffmpeg 8.1's `lut3d` reads the file this generator writes and that the output matches the shipped LUT byte for byte.

[15] [`mixing/video/video_concat.py`](file:///Users/thorwhalen/Dropbox/py/proj/t/mixing/mixing/video/video_concat.py) and [`mixing/video/video_util.py`](file:///Users/thorwhalen/Dropbox/py/proj/t/mixing/mixing/video/video_util.py) — the six transitions, `SOCIAL_SIZES`, `resize_to_dimensions` and `normalize_video_dimensions` that families C and D inherit.

[16] [`muvid/visualize/canvas.py`](file:///Users/thorwhalen/Dropbox/py/proj/t/muvid/muvid/visualize/canvas.py) line 224 — the live `eq=brightness=…:saturation=…` in `background_chain`: the federation's only use of a GPL-only ffmpeg filter, for a cosmetic dim, using an additive brightness offset.

[17] `looks` — `KICKOFF.md` — the non-negotiables, the two exclusions, the refactor order, and the two open questions §4 and §2 answer.

---

## Adversarial review (2026-09-02)

*Appended by an independent reviewer who re-ran every command rather than accepting any. Environment: ffmpeg 8.1 (homebrew `8.1_1`), macOS 15 / arm64. Two Python interpreters were used deliberately — see R1.*

### Confirmed by independent re-execution

- **The GPL filter gate.** Re-fetched `release/8.1`'s `configure` (8,840 lines, `sha256 28edfaee…b45f4`): exactly **33** `*_filter_deps` lines name `gpl`, the list matches reference [2] name for name, and `eq_filter_deps="gpl"` is there. Of the 166 `*_filter_deps` lines, `lensfun` is the only `version3` and none is `nonfree`. Every filter in §11.1 has **no** deps line except `scale` (swscale) and `elbg` (avcodec). Spot-checked at source level too: `libavfilter/vf_bilateral.c` is **MIT**, `vf_noise.c` is **LGPL-2.1+**, while `vf_smartblur.c` and `vf_eq.c` carry the GPL header — the configure gate and the file headers agree. `libpostproc` no longer ships a `pp` filter in 8.1, so there is no second gating mechanism to miss.
- **The stdlib generator, end to end.** Extracted the §6.2 fence to a file: 306 lines, `python3 -m doctest` → **4 tests, 4 passed**. Driving it with the `mklut_b.py` ramp/accent/tone reproduces the shipped `que_calor_b.cube` **byte for byte** — spec **566 bytes**, output **970,374 bytes** in **0.402 s**, cache key `8dd26bcfa92574a1062454ec32bdf677`, expansion **1714×**, `materialize` idempotent and equal to `cube_text`, title enters the key. Every number in §6.3 reproduced exactly.
- **The flat form's timings and the size table.** An independently written stdlib generator (precomputed 256-entry tables, as `mklut_b.py` does) gives **0.134 s** for 33³, **0.018 s** for 17³, **1.018 s** for 65³ and byte sizes **132,726 / 970,374 / 7,414,950** — the §7 table exactly. The 75-byte header decomposes as claimed, and it is 75 rather than 76 only because the shipped title is `que_calor_palette` (17 chars).
- **`curves` monotonicity.** 21 and 20 non-monotone steps under `interp=natural` on the two steep curves, worst drop −2; **0** under `pchip`; 0 for both on the gentle curve. Exact reproduction.
- **The `colorchannelmixer` ceiling.** `s = 2.077` accepted, `s = 2.078` refused (`Value 2.000168 for parameter 'bb' out of range [-2 - 2]`), `s = 2.1` refused on `bb`, `s = 2.5` refused on `rr`; `hue=s=` accepts 2.5 and 4.0. The 2.0779 crossing is right to four digits.
- **Probe A.** `noise=alls=8:allf=t+u` → 87.39% / 87.50% changed, max 7; `deband`, `bilateral`, `gblur`, untagged `noise` and `lut3d` → 0.00%. Exact.
- **The flatten table.** Every row reproduces once the upscale uses `INTER_CUBIC` (which is what `render_v2c.py` actually does): source 348 / 29.3 / 105.3; mean-shift 0.5/12/60 → **132 / 16.0 / 54.9**; 0.75/12/40 → **175 / 47.7 / 101.6**; `bilateral` 165/35.9 and 117/22.9; `smartblur` 292; `gblur` 275.
- **`blend` and `xfade`.** `bleach` = index 36, `stain` = 37, of 40 modes (0–39). `xfade` enumerates `custom` = −1 plus 0–57 = **58 named**.
- **All 25 compile targets.** Every `-vf` string this note calls "verified OK" — including the `bleach_bypass` split/`format=gray`/blend, the `halation` split/lutyuv/gblur/screen, all four `fit` modes including `social`, and the limited-range `lutyuv` gamma — runs with returncode 0 on ffmpeg 8.1 here.
- **`mixing` has no external users.** `rg` across `$PP/{t,tt,i}` for `SOCIAL_SIZES`, the six transition names, `resize_to_dimensions` and `normalize_video_dimensions` finds hits only inside `mixing`, inside `looks` itself, and in documentation. `SOCIAL_SIZES`'s five keys and values are exactly as quoted. Recommendation 9's premise holds.
- **The neural-restyler licences (which the note left unverified).** Fetched: AnimeGANv2's README §License — *"made freely available to academic and non-academic entities for **non-commercial purposes**"*; White-box Cartoonization — *"Licensed under the **CC BY-NC-SA 4.0**… Commercial application is prohibited"*. Claim 15 stands, now verified.
- **`elbg` and `normalize` are ADAPTIVE.** Probe B reproduces the direction and the maxima (`normalize` max 204/255, `elbg` max ~6/255) though not the exact percentages (I measured 93.1% and 16.7% against the note's 67.37% and 15.04%, using my own white-box construction). The classification is unaffected.
- **The `eq=` call site.** Exactly one in the whole muvid tree, at `muvid/visualize/canvas.py:224`, spelled `eq=brightness=-{layout.dim}:saturation={layout.saturation}`. Recommendation 14's target is real and correctly located.
- **The quantiser trap, on synthetic content.** Fused `lut3d`+`posterize` at level 8: **6.432%** of samples off by >2/255 under `interp=tetrahedral`, **0.447%** under `nearest` — the note's 6.123% / 0.265%, reproduced.
- **Folding `posterize` into the generated `.cube` does not work**, and I checked because it is the obvious cheaper alternative to §8's whole fusion subsystem. Quantising the 33³ entries at generation time and applying with `interp=nearest` costs 2.48 ms/frame against 3.61 for the two-filter chain, but differs from it by **max 37/255, 15.5% of samples >2/255** — the same "interpolating a quantised lookup" failure §8 identifies, now at grid resolution. `posterize` legitimately stays a separate filter. Recorded so nobody else tries it.

### Refuted

**R1 — the cv2-5.0.0 caveat in §12 is an artifact of running from `/tmp`, and the tier it hedges is directly verifiable.** `cd /tmp && python3 -c "import cv2"` → **5.0.0** (`~/.pyenv/versions/3.12.12`); the same command from `$HOME` or from the `looks` repo → **4.13.0** (`~/.pyenv/versions/p12`) — exactly the version notes 05/06 assessed. `.python-version` only applies under `$HOME`, so the note measured a different, undefended environment. And the hedge is unnecessary: **both** wheels bundle the same thing. `cv2/.dylibs/` in each contains `libx264.164`, `libx265.215`, `libpostproc` and a `libavcodec` whose own strings read `--enable-gpl --enable-version3` and **`libavcodec license: GPL version 3 or later`**, while the dist metadata says `License: Apache 2.0`. So `COPYLEFT_SHIPPED` for `cv2.pyrMeanShiftFiltering` is confirmed by inspection, on this machine, for both versions — and the copyleft is **GPL-3.0-or-later**, not the GPL-2.0+ the kickoff assumes. (Also worth knowing: the `p12` environment has **three** overlapping opencv distributions installed — `opencv-python 4.12.0.88`, `opencv-python-headless 4.13.0.92`, `opencv-contrib-python 4.13.0.92` — sharing one `cv2/` directory. Tier resolution must inspect the binaries, not the metadata; no dist record answers "whose `.dylibs` are these".)

**R2 — §10's consumer counts are token counts, not call sites, and are inflated roughly 4×.** `rg -c` over muvid counts *lines containing the substring*: `eq` alone matches 269 lines ("request", "sequence", "frequency"). Counting actual filter emissions (`\b<name>=` in a filter string, tests excluded) gives **xfade 1, crop 6, scale 8, pad 2, colorchannelmixer 4, gblur 1, eq 1 — 23 sites, not 90**. In particular *"muvid already calls `xfade` 31 times"* is really **one** emission site, `muvid/footage/assemble.py:370`. The conclusions survive (muvid does use xfade; it does use colorchannelmixer more than eq), but "90 call sites today" should not be quoted as evidence of demand.

**R3 — claim 10 does not reproduce, and its sign flips.** On a 1280×720 ffv1 source, best of 3 over 60 frames, `-f null -`: direct 8-filter **10.78** ms/frame, naive in-graph fusion **8.96**, correct fusion (`r=1:d=1` + `clut=first`) **3.66**, materialised hald + `movie=` **2.96**. The naive form was **faster** than the direct chain here, not slower. The actionable advice is unharmed — `r=1:d=1`/`clut=first` is still a 2.4× improvement over the naive form and ~3.6× over direct — but *"the naive form is slower than the direct chain"* is not a robust finding and should not be stated as one.

**R4 — §8's accuracy figures are measured on synthetic content and do not survive real footage.** Reproduced on a `testsrc2` still (smooth 8-stack, level 8: mean 0.165, 1.38% >2/255 — close to the note's 0.096 / 0.300%). On the actual Que Calor frame `src_96.jpg`, with format forced to `rgb24` on both sides: **max 30/255, mean 1.531, 20.05% of samples >2/255** — sixty times the reported rate. And on that frame `interp=nearest` makes the *smooth* stack worse (24.86%), so the two clauses of the fusion rule are not just a refinement, they are a fork whose branch must be chosen correctly per run. The 3.9× is real; "max 18/255, mean 0.096, 0.300%" is a property of the test pattern, not of the optimisation.

**R5 — `grain`'s stated rationale for `seed=0` is wrong.** `libavfilter/vf_noise.c:297`: when no seed is given the filter uses the **constant 123457**, not a clock. Measured: three consecutive runs of `noise=alls=8:allf=t+u` with no seed produce byte-identical output. "A spec that produces a different picture on every run is not a spec" does not apply to this filter on ffmpeg 8.1. Pinning a seed is still right (explicitness, and portability across ffmpeg versions) — but note that `all_seed=0` is a *different picture* from the default, so adopting it silently changes the grain of anything already authored against plain `noise=`.

**R6 — reference [14] is a dead link.** `https://kono.phpage.fr/images/9/94/Adobe-cube-lut-specification-1.0.pdf` returns **HTTP 404**. Separately, ffmpeg's own parser comments the format as the **"Iridas format"** (`vf_lut3d.c:674`), which is its actual origin (Adobe acquired SpeedGrade and later published the 1.0 spec). The empirical claim — ffmpeg reads what this generator writes, byte-identically to the shipped LUT — is confirmed; the citation needs replacing.

### Design objections

**D1 (serious) — the tier column in §11.1 is a *floor*, not a resolved tier, and on this machine every ffmpeg row resolves one rung lower than it is labelled.** `ffmpeg -L` here prints *"GNU General Public License … version 3"*, and the build is `--enable-gpl --enable-version3`. Note 06's rule, which this note cites approvingly, is that the tier is **resolved from the environment**. Under that rule the 22 rows labelled `WEAK` are `COPYLEFT_TOOL` on this machine, and the §3 headline — *"`bilateral` is the LGPL-clean flattener, reachable at the default ceiling"* — is true only because the default ceiling happens to be `COPYLEFT_TOOL`, which the GPL binary also satisfies. Below that ceiling `bilateral` is unreachable too, for exactly the same reason `pyrMeanShiftFiltering` is. The catalogue needs two columns (the *filter's* copyleft gate, and the tier that a given binary resolves to), or the README's honest sentence is not "the shipped setting cannot run at the default ceiling" but "on a stock homebrew ffmpeg, *nothing* in this catalogue runs below `COPYLEFT_TOOL`".

**D2 (serious) — the two CI probes enforce three of the five `frame_dependency` values, and the two they miss are the two the design depends on.** Measured here:
- **TEMPORAL is undetectable.** `tmix=frames=3`, `tblend=all_mode=average` and `hqdn3d` all pass Probe A on a looped still (identical input frames → 0.00% / 0.00% / 12.5% at max 2) *and* pass Probe B (0.00% on the shared region). A filter misdeclared `FRAME` that is actually `TEMPORAL` ships green — and TEMPORAL is the class §9 excludes on structural grounds, i.e. the one whose misclassification produces an artefact at every cut.
- **PIXEL and FRAME are indistinguishable under Probe B as constructed.** With the perturbation in the far corner, `gblur=sigma=4`, `deband`, `bilateral` and `lut3d` all read 0.00%. §8's fusion optimisation keys on `PIXEL`, so a `FRAME` effect misdeclared `PIXEL` would be silently baked into a CLUT.
The fix for the second is one line and I verified it: move the perturbation *adjacent* to the shared region (rows 90–99, shared 100–359) and `gblur` reads **max 96/255, 0.41% changed** while `lut3d` and `deband` stay at 0. A third probe is needed for TEMPORAL: feed a *varying* two-frame sequence and check that output frame N is unchanged when frame N−1 is replaced.

**D3 (serious) — implementations the catalogue presents as interchangeable are not the same picture, and the note is scrupulous about this only for `flatten`.** Measured on a `testsrc2` frame, byte-diffed:
- `saturation` at s = 0.5: `colorchannelmixer` vs `hue=s` → **mean 9.90/255, 95.9% of samples >2/255, max 18**; vs `eq=saturation` → mean 9.78, 95.4%. At s = 2.0: max 33 against both.
- `contrast`: `curves` RGB S-curve vs `eq=contrast=1.3` → **mean 6.91, max 55, 46.0% >2/255** (and the RGB form is not luma-preserving: mean per-pixel `max−min` chroma 239.6 vs `eq`'s 223.0).
Under the note's own design, lowering `max_tier` swaps the implementation — so a caller who tightens the ceiling silently gets a *different look* rather than a refusal. That is the failure mode the package exists to prevent, arriving through the front door. Either the catalogue records a per-implementation "not equivalent, differs by X" note (as it correctly does for `bilateral` vs mean-shift), or same-name implementations must be certified equivalent within a stated tolerance and otherwise given different names.

**D4 (serious) — `flatten`'s parameter list omits the upscale interpolator, which moves the load-bearing number as much as `scale` does.** `render_v2c.py` upscales with `INTER_CUBIC`. Substituting `INTER_LINEAR` at the *same* scale/radii: post-look sharpness **54.9 → 41.7** at 0.5/12/60 and **101.6 → 77.4** at 0.75/12/40 — a 24–32% swing on the exact statistic `match_clip` is solving for, from a parameter the spec does not name. Two conforming implementations of `flatten` can therefore disagree by more than the clip-aware resolver's whole correction. Either pin the interpolator in the spec or declare it a fixed part of the implementation's identity (and put it in `impl_version`).

**D5 (serious) — `cube_key` is an address of the Python object, not of the bytes, and `cube_text` validates nothing.** Measured on the listing as published: `cube_key({… "size": 17})` ≠ `cube_key({… "size": 17.0})` (`f59aea5c…` vs `074051…`) while `cube_text` **raises `TypeError`** on the float form — so the "true content address" is defined for specs that generate no artifact, and two specs that would generate identical bytes get different keys. Separately `cube_text({… "size": 1})` raises `ZeroDivisionError` and `size: 2` silently emits an 8-entry LUT outside `CUBE_SIZES`, because the only validation lives in the authoring sugar `gradient_map()` while §7's whole argument is that the spec is plain JSON arriving from a store, a diff, or an agent. Canonicalise the spec before hashing (coerce `size` to `int`, normalise hex case, reject unknown keys) and move validation into `cube_text`.

**D6 (serious) — `materialize`'s temp file is not unique, so its stated atomicity does not hold for concurrent writers.** `tmp = path.with_suffix(".cube.tmp")` is a deterministic function of the cache key alone. Two processes materialising the same spec — which is exactly what a per-cut fan-out does, and muvid's execution model is one ffmpeg process per cut — both open that path with `write_text` (truncate) and interleave; either can then `os.replace` a corrupt file into place. The docstring's promise ("a concurrent reader never sees a half-written LUT") is true; the risk is a concurrent *writer*, and a half-written `.cube` read by ffmpeg is, as the note itself says, a silently wrong picture rather than an error. Use `tempfile.mkstemp(dir=d)` (plus `fsync` before `replace` if you want the promise to survive a crash).

**D7 (minor, but it undercuts a stated rule) — `compile()` cannot emit runnable argv, and the note does not say so.** §6 says `compile()` is pure and `materialize()` owns all I/O; note 05's rule is that "`looks` emits argv as data and someone else runs it". Both cannot be true of the same object: the `-vf` string for a gradient map needs `lut3d=file=<path>`, and the path does not exist until `materialize` runs. So the thing `compile()` returns is a *plan*, not a command, and the executing host must run `looks.materialize` — which means it must have `looks` installed and a writable cache. That is a fine contract; it just needs stating, because §7's own argument ("a path is not content, so a `Look` referencing one is not self-contained") applies verbatim to the generated path once it is baked into a persisted `LookPlan` that travels to another machine.

**D8 (minor) — the `Transition` boundary is drawn inconsistently.** `overlap_blend` is rejected because *"how much footage is an EDL parameter, and the caller already supplies `offset_s`"* — yet `Transition.duration_s` **defaults to 0.5** and is not caller-mandatory. `xfade`'s `duration` *is* "how much footage the transition eats"; it is the same quantity `overlap_blend`'s `overlap` names. Either `duration_s` is mandatory alongside `offset_s`, or `overlap_blend` was excluded on a distinction that does not survive contact with the compile target.

**D9 (minor) — §10's reelee claim is confirmed in mechanism and wrong in demand.** I read the source the note says it did not. `rg -n "\-vf|filter_complex" reelee/` finds **zero hits** — reelee emits no ffmpeg filter anywhere — so "through the pure-data plan rather than through a render call" is right. But reelee's styling vocabulary is `style_decision.lock` (`style-decision/v1`: flavor slug, model id, style anchor, negative prompt, seed discipline) and `extract_color_script` (`color-script/v1`) — **prompt-side** decisions handed to a generative model, not a post-process grade. So reelee is not a consumer of the grade family today; it is a consumer of a vocabulary `looks` does not have. Saying so is more useful than the inference the note made.

**D10 (minor) — the limited-range gamma hazard is stated in one direction only.** The note warns that the full-range `lutyuv` form on a limited-range source pushes below the legal floor. Measured, the symmetric mistake is worse: the *limited-range* form on a full-range source maps every input 0–15 to **16** and every input 240–255 to **235** (175 distinct output codes against the full-range form's 203). Same refusal covers it — but the docstring should name both directions, because the limited-range expression is the one presented as the safe default.

### Net

The measured core of this note is unusually solid: the licence gate, the byte-exact stdlib generator, the cache-key design's motivation, the `pchip` finding, the `colorchannelmixer` ceiling, the flatten table and all 25 compile targets reproduce exactly. Three quantitative claims do not (R2 the consumer counts, R3 the naive-fusion direction, R4 the fusion accuracy off synthetic material), one caveat is an environment artifact that makes the finding *stronger* than stated (R1), and the design needs six fixes before code: the tier column's two meanings (D1), a third probe plus an adjacent-perturbation Probe B (D2), an equivalence policy for same-name implementations (D3), the flatten interpolator in the spec (D4), a canonicalising and validating `cube_key`/`cube_text` (D5), and a unique temp file (D6).
