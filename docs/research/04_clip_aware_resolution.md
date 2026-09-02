# Clip-aware parameter resolution: measuring a clip, and normalising the OUTPUT

**Date: 2026-09-02.** Every ffmpeg and OpenCV number below was produced by running the command shown, on this machine, on this date. Software versions are stated at each measurement. Anything not measured is marked **unverified**.

## Verdict — stop here if you read one paragraph

**The zero-dependency tier can measure everything this layer needs, and that is a measured fact rather than a hope.** ffmpeg 8.1's `signalstats` + `siti` + `blurdetect`, read as structured JSON through `ffprobe -f lavfi`, reproduce the three statistics the Que Calor work actually acted on: a sharpness ordering that agrees with OpenCV's Laplacian variance (Spearman +0.845, Pearson +0.923 against its square root, n=24 frames), a threshold share that is **bit-exact** against numpy (max absolute difference 0.000000 over 24 frames, via a `lutyuv`/`geq` trick that costs one decode), and a flicker ratio that independently reproduces the source's reported "0.89–1.12× the source's own" as **0.91×–1.12×**. The one thing the zero-dep tier cannot do is a CIELAB L\* histogram, and the one thing it must declare is which luma space a threshold was taken in — measured, the same nominal threshold gives a crushed-black share of **0.6% in coded Y and 17.4% in `BGR2GRAY`** on the same frames, a 29× disagreement that no error would ever surface. On the resolver itself: minimising the max/min ratio of a post-effect statistic across N clips is not a search problem at all — it is the *smallest window containing one element from each of N sorted lists*, solvable **exactly** by a two-pointer sweep in `O(N log N)`, so `looks` needs no heuristic, no gradient, and no learned model. The probe budget, however, is the binding constraint and the source's k=3 was too small: measured on the delivered render, a 3-frame median carries a **p90 relative error of 12.7–34.0%**, which is larger than most of the improvements a resolver would be choosing between — so the default is **k=5** and the resolver must return `inside_noise` rather than a number it cannot support. Finally, the boundary: **`looks` owns the measurer, the objective and the solver, and it never produces a deliverable** — enforced structurally by the rule that *every ffmpeg process `looks` starts ends in `-f null -`*, a testable invariant rather than a convention, which keeps auto-tuning in scope and `looks.render()` permanently impossible. The type it accepts is a `SourceMap` — an ordered, frozen sequence of `(interval, source_id)` in **output** time — which is provably not an EDL because *you cannot re-render from it*: it deliberately omits `clip_in`, and three of the nine fields of the real Que Calor EDL are all a stylizer ever read.

---

## 0. What the source material actually measured, and in what vocabulary

Four separate measurement scripts exist in `~/Downloads/que_calor/work/`, and they do **not** share a vocabulary. Cataloguing that is the first job, because `looks` must not become a fifth.

| script | what it measures | how | units |
|---|---|---|---|
| `survey/quality.py` | `sharp_lap_var_{med,p10,p90}`, `frac_soft`, `blown_highlight_frac_{med,p95}`, `crushed_black_frac_{med,p95}`, `luma_mean`, `luma_sd_over_time`, `lab_{a,b}_{mean,sd}`, `noise_sd_{med,p90}` | ffmpeg → rawvideo `bgr24` pipe → OpenCV per frame at 2 fps | Laplacian variance; fractions; 0–255 gray; Lab a\*/b\* offset from 128 |
| `analysis/quality.py` | `sharp`, `bright`, `contrast`, `sat`, `blown`, `crushed`, on **song time** | `cv2.VideoCapture` at 4 fps, frames resized to 320 px wide | Laplacian variance; gray mean; gray std; HSV S mean; fractions at `>245` / `<10` |
| `analysis/autograde.py` | `L_p05`, `L_med`, `L_p95`, `S_med` **over the spans the EDL uses** | `cv2.VideoCapture` seeking to 4 points per cut, 240×135 | CIELAB L\* scaled to 0–100; HSV S in 0–1 |
| `style/tonematch.py` | a 20-bin L\* histogram of the finished V1 render, matched to the reference's published one | `cv2.VideoCapture`, ~160 frames, 160×90, `COLOR_BGR2LAB` | L\* in 0–100, 5-point bins |
| `style/sweep_c03.py` | **post-effect** Laplacian variance, 3 frames, 8 parameter settings | OpenCV mean-shift → ffmpeg `lut3d`+`lutrgb` → OpenCV Laplacian | Laplacian variance |
| `style/flicker.py` | mean and p99 of `\|frame(t) − frame(t−1)\|`, as a **ratio to the source's own** | OpenCV, 3 s at native fps | 0–255 mean absolute difference |

Five scripts, five spellings of "how sharp", three spellings of "how dark", two colour spaces, and two different percentile pairs (p05/p95 in `autograde`, p10/p90 nowhere but implicitly wanted). The lesson is not that the work was sloppy — each script was fit for its moment — but that a package must pick **one** vocabulary and say what instrument produced each number.

`muvid` already has a vocabulary, and it is the one to defer to. `muvid.footage.scoring` names its metrics `sharpness`, `exposure`, `stability_shake`, `face_framing`, `motion_beat_bas`, `motion_onset_xcorr` [8], carries them as `ScoreTrack(clip_id, metric, t0, hop_s, raw_values, mask, direction)` on a shared song-time grid, keeps **raw as the SSOT** and normalises per-metric-globally across clips at tensor-assembly time [9], and its per-frame kernels are explicitly flagged as *"promotion candidates for `mixing.video` the moment a second consumer appears"* [10].

**One trap in reusing it, and it is a real one.** `muvid`'s `exposure` is **not** a luma measurement. It is `clip_ok * contrast` — a composite health score in [0,1] where `clip_ok = 1 − (share below 16 + share above 239)` and `contrast = min(1, std/64)` [10]. A well-exposed dark frame and a flat mid-grey frame get very different `exposure` values, and neither is "how bright is it". `looks` needs raw luma (a grade solves for gamma against a *median*, not against a health score), so it must **not** reuse the name `exposure` for anything raw. It should reuse `sharpness` verbatim — same meaning, same direction — and spell its exposure quantities `luma_p10 / luma_mean / luma_p90`, which are unambiguous and are exactly what the zero-dep tier produces.

---

## 1. `ClipStats` — what a clip needs to carry

Three fields carry more design weight than all the numbers: `stage`, `instrument`, and `luma_space`. Each of them exists because a measurement was found to be meaningless without it.

### 1a. Why `stage` — the source file is the wrong thing to measure

Measured, on the Que Calor material:

| | c01 | c02 | c03 | who is sharpest |
|---|---|---|---|---|
| OpenCV Laplacian variance, **source files**, whole clip (`survey/quality.json`) | 841.4 | 563.3 | 27.2 | **c01** |
| ffmpeg `siti.si`, the **finished V1 render**, median over all 50 EDL spans (measured today) | 41.9 | 66.2 | 35.0 | **c02** |

The ordering of c01 and c02 **inverts** between the source file and the render. The reason is in the geometry tier, not the measurement: c01 is 478 px wide and is upscaled 2.68× to 720p and cropped (it is the vertical clip), while c02 is 848 px and upscaled 1.51× [11]. c01's high native sharpness does not survive its upscale. A resolver that measured source files and normalised on that would have corrected the wrong clip.

So a `ClipStats` is meaningless without the pipeline stage it was taken at, and the stage that matters is **the frame the effect will actually see**.

### 1b. Why `instrument` — the fix is reproducible, the scale is not

Measured today, ffmpeg 8.1 `siti.si` on the delivered `que_calor_v2b.mp4` and `que_calor_v2c.mp4`, grouped by which source is on screen (from the EDL, in output time), against the OpenCV numbers the source material reports:

| | c01 | c02 | c03 | max/min spread |
|---|---|---|---|---|
| **OpenCV Laplacian variance** (source's own figure, 3 c03 frames post-LUT) — V2b | 72.2 | 114.3 | 38.4 | **2.98×** |
| **OpenCV Laplacian variance** — V2c | 72.2 | 114.3 | 71.8 | **1.59×** |
| **ffmpeg `siti.si`** (measured today, all spans of the delivered file) — V2b | 53.33 | 65.23 | 29.75 | **2.19×** |
| **ffmpeg `siti.si`** — V2c | 53.33 | 65.23 | 37.93 | **1.72×** |
| **ffmpeg `siti.si`** — the ungraded input, `v1e` | 41.89 | 66.25 | 34.98 | 1.89× |

The two instruments agree on everything that is a *decision*: c03 is the outlier, c02 is the sharpest, the fix moved only c03, it moved it up, and the spread came down. They disagree on every *magnitude*: 2.98→1.59 versus 2.19→1.72. They are measuring different functionals of the same pictures over different frame populations, and neither is wrong.

**Therefore a spread target is expressed in the instrument's own units and is not portable.** `ClipStats.instrument` is not metadata, it is part of the value's identity, and comparing two `ClipStats` with different instruments must raise.

The `v1e` row also confirms the source's causal story with an independent instrument: the stylizer raised c01 from 41.9 to 53.3 (+27%) while barely moving c02 (66.2 → 65.2) — the "LUT and posterize stage normally *adds* apparent sharpness by creating hard edges between flat regions", visible here as a per-clip gain that varies by clip.

### 1c. Why `luma_space` — the 29× silent disagreement

Measured today (ffmpeg 8.1; OpenCV 4.13.0 under `~/.pyenv/versions/p12`), on 8 frames per clip at 2 fps from t=20 s, the *crushed-black share* under the identical nominal rule "luma < 20":

| clip | ffmpeg `lutyuv`+`signalstats` | numpy on the **coded Y plane** | numpy on `cv2.COLOR_BGR2GRAY` |
|---|---|---|---|
| c01 | 0.00449 | 0.00449 | 0.04690 |
| c02 | 0.02335 | 0.02335 | 0.11083 |
| c03 | 0.00595 | 0.00595 | **0.17419** |

`max |ffmpeg − numpy(coded Y)| = 0.000000` and `max |ffmpeg − numpy(BGR2GRAY)| = 0.232300`, over the pooled 24 frames.

The ffmpeg route is **bit-exact** against the coded plane, and disagrees with the OpenCV route by up to 23 percentage points — 29× on c03. Coded Y for `yuv420p tv`-range content lives in 16–235; `BGR2GRAY` output is full-range 0–255. Nothing errors, nothing warns, and the number that would drive a shadow-floor decision differs by a factor of thirty.

This is the *measurement-side twin* of the range trap the sibling note establishes for the transform side [6]: there, `color_range=unknown` silently changes what a LUT does; here, it silently changes what a threshold counts. Same root, two surfaces. `ClipStats` therefore declares `luma_space` with three values — `"coded"`, `"full"`, `"cielab_L"` — and `color_range` with three — `"limited"`, `"full"`, `"untagged"` — because untagged is a third state, not a synonym for limited.

### 1d. The proposed dataclass

```python
"""Measured per-clip statistics, and the identity that makes them comparable."""

from dataclasses import dataclass, field
from typing import Literal, Mapping

Stage = Literal["source", "framed", "graded", "post_effect"]
LumaSpace = Literal["coded", "full", "cielab_L"]
ColorRange = Literal["limited", "full", "untagged"]


@dataclass(frozen=True)
class LumaSummary:
    """A five-number luma summary, in whatever :class:`ClipStats` declares as its space.

    The percentiles are p10/p90 and not p05/p95 on purpose: p10/p90 is what
    ``signalstats`` emits for free [1], and inventing a pair the zero-dependency
    tier cannot produce would make the two tiers non-interchangeable for no gain.
    ``median`` is ``None`` on the ffmpeg tier — ``signalstats`` publishes ``HUEMED``
    but no ``YMED``, and bisecting for it would cost eight extra decode passes.
    """

    p10: float
    mean: float
    p90: float
    minimum: float
    maximum: float
    median: float | None = None

    @property
    def contrast(self) -> float:
        """p90 - p10. The spread ``autograde`` solved against, in one field."""
        return self.p90 - self.p10


@dataclass(frozen=True)
class ClipStats:
    """What one source contributes to one stage of one pipeline, as measured.

    The first four fields are the value's IDENTITY, not decoration. Two
    ``ClipStats`` are comparable only if ``stage``, ``instrument`` and
    ``luma_space`` all agree; :func:`compare` raises otherwise, because the
    measured disagreements between instruments (2.98x vs 2.19x for the same
    fix) and between luma spaces (0.6% vs 17.4% for the same threshold) are
    larger than the effects a resolver is choosing between.
    """

    source_id: str
    stage: Stage
    instrument: str  # e.g. "ffmpeg-8.1/signalstats+siti", "opencv-4.13/laplacian"
    luma_space: LumaSpace

    #: How the frames were chosen. Part of identity: measured, taking the median
    #: over the 3 widest spans gave c01 a `siti.si` of 30.7 where all 17 spans
    #: gave 41.9 -- a 27% move from the SAMPLER alone.
    sample_spec: str
    n_frames: int

    #: Higher is sharper, in the instrument's own units. muvid's metric name,
    #: verbatim, because it means the same thing and has the same direction [8].
    sharpness: float | None = None
    sharpness_unit: str = ""

    luma: LumaSummary | None = None
    saturation_mean: float | None = None
    crushed_share: float | None = None
    blown_share: float | None = None

    #: Mean |Y(t) - Y(t-1)|. The flicker check, as one number [1].
    temporal_delta: float | None = None
    entropy_y: float | None = None

    color_range: ColorRange = "untagged"
    #: Instrument-specific extras (BRNG, TOUT, blurdetect's `blur`, ...).
    extra: Mapping[str, float] = field(default_factory=dict)
```

`ClipStats` is deliberately a **summary over an interval set**, not a per-frame track. `muvid` already owns the per-frame, song-time-gridded, resample-and-normalise machinery, and it needs numpy to do it [9]. `looks` needs one number per (source, statistic, stage) to run its objective, so a summary is sufficient and keeps the zero-dep promise. A caller that has a `ScoreTrack` can produce a `ClipStats` from it in three lines; `looks` should ship that direction as an optional adapter and never the reverse.

---

## 2. How they are measured, with what dependency

### 2a. The three tiers, and the answer for each

| tier | dependency | can it measure? | verdict |
|---|---|---|---|
| **(a) ffmpeg-only** | `ffmpeg`/`ffprobe` on `PATH` — shelled out to, never linked | **Yes, for everything the resolver acts on** | **This is the default tier.** |
| **(b) numpy + OpenCV** | optional extra | Yes, plus CIELAB, arbitrary percentiles, arbitrary kernels | The extra, for L\* work |
| **(c) pure stdlib over piped raw frames** | none at all | Yes in principle; measured cost below | **Rejected** |

**(c) is rejected on measured cost, not on taste.** A 720p `bgr24` frame is 2.76 MB. Computing a Laplacian variance over it in pure Python is roughly 2.8 million multiply-accumulates through `int` objects, which on CPython 3.12 is order seconds per frame — against 12 ms/frame for `siti` inside ffmpeg (measured: 6.2 s of filter time for 520 frames, §2c) and sub-millisecond for OpenCV. The `array` module and `memoryview` help with the *transport* but not the arithmetic. Stdlib does have one legitimate role and it is the transport itself: parsing `ffprobe -of json` with `json.loads`. That is tier (a)'s reader.

### 2b. Tier (a), measured — the actual commands and the actual output

**All versions:** ffmpeg 8.1 and ffprobe 8.1 (homebrew, `--enable-gpl --enable-version3 --enable-libx264 --enable-libx265 …`), macOS 24.6.0 arm64, 2026-09-02.

**The reader is `ffprobe -f lavfi`, not stderr scraping.** `metadata=print:file=-` works and is what the source material used, but it emits a bespoke text format. `ffprobe` reads the same filter metadata as structured JSON with timestamps, and `json` is stdlib:

```bash
ffprobe -v error -f lavfi \
  -i "movie=que_calor_v1e.mp4:seek_point=43.5,fps=2,signalstats,blurdetect,siti" \
  -show_entries "frame=pts_time:frame_tags=lavfi.signalstats.YAVG,lavfi.signalstats.YLOW,lavfi.signalstats.YHIGH,lavfi.signalstats.SATAVG,lavfi.blur,lavfi.siti.si" \
  -of json -read_intervals "%+2"
```

Real output (first two frames, verbatim):

```json
{ "frames": [
    { "pts_time": "43.500000",
      "tags": { "lavfi.siti.si": "45.04", "lavfi.signalstats.YLOW": "35",
                "lavfi.signalstats.YAVG": "98.739", "lavfi.signalstats.YHIGH": "156",
                "lavfi.signalstats.SATAVG": "12.9383", "lavfi.blur": "8.057350" } },
    { "pts_time": "44.000000",
      "tags": { "lavfi.siti.si": "41.61", "lavfi.signalstats.YLOW": "31",
                "lavfi.signalstats.YAVG": "92.0086", "lavfi.signalstats.YHIGH": "144",
                "lavfi.signalstats.SATAVG": "20.2115", "lavfi.blur": "7.905414" } } ] }
```

**`signalstats` publishes 30 values per frame.** The full set, from one real run on `Que Calor 03.mp4` at t=20 s:

```
YMIN=14  YLOW=20  YAVG=41.5696  YHIGH=78  YMAX=141
UMIN=99  ULOW=126 UAVG=133.172  UHIGH=141 UMAX=200
VMIN=125 VLOW=133 VAVG=146.925  VHIGH=167 VMAX=233
SATMIN=0 SATLOW=5 SATAVG=20.5488 SATHIGH=40 SATMAX=106
HUEMED=195  HUEAVG=198.623
YDIF=3.83973  UDIF=1.7035  VDIF=5.79776         (frame 1; frame 0's is 0 by construction)
YBITDEPTH=8  UBITDEPTH=8  VBITDEPTH=8
TOUT=1.69542e-05  BRNG=3.39084e-05               (with stat=tout+brng)
```

`YLOW`/`YHIGH` are documented as "the Y value at the 10% percentile" and "at the 90% percentile", expressed in 0–255 [1]. **Verified empirically** rather than taken on trust — on a synthetic 256-wide 0→255 luma ramp:

```bash
ffmpeg -v error -f lavfi -i "gradients=size=256x64:c0=black:c1=white:x0=0:y0=0:x1=255:y1=0:duration=0.05:rate=25" \
       -vf "format=gray,signalstats,metadata=print:file=-" -frames:v 1 -f null -
# YMIN=0  YLOW=25  YAVG=127.5  YHIGH=230  YMAX=255
```

25 and 230 are the 10th and 90th percentiles of a uniform 0–255 ramp (25.5 and 229.5). Confirmed.

`YDIF` is documented as "the average of sample value difference between all values of the Y plane in the current frame and corresponding values of the previous input frame" [1] — which is **exactly** what `flicker.py` computed in OpenCV.

**`siti.si` is the zero-dep sharpness.** `siti` computes Spatial and Temporal Information as defined in ITU-T Rec. P.910 (11/21) — SI is the standard deviation of the Sobel-filtered luma plane; ffmpeg's own documentation notes this is the legacy implementation corresponding to a superseded recommendation, and points at P.910 (07/22) for the current one [3][4]. Measured agreement with the OpenCV instrument the source material used, over 24 frames pooled from all three clips at 2 fps:

```
spearman(siti.si , cv2 lapvar)   = +0.8452
spearman(blurdetect, cv2 lapvar) = -0.8235      (negative as expected: more blur = less sharp)
pearson(siti.si, sqrt(lapvar))   = +0.9234
```

The Pearson against the *square root* is the tight one, and it makes sense: SI is a standard deviation of a gradient, Laplacian variance is a variance of a second derivative. **A `siti.si`-based spread target is therefore roughly the square root of a Laplacian-variance one** — which is why the two instruments reported 2.19× and 2.98× for the same picture (√2.98 = 1.73, and 2.19 sits between; they are not the same functional, only monotonically related).

`blurdetect` implements Marziliano et al.'s no-reference perceptual blur metric [2][5], and **higher means blurrier** — confirmed by measurement, since the softest clip scored highest (c03 7.51 against c01 5.36 and c02 5.67). Its dynamic range is much narrower than `siti`'s (1.40× against 2.44× across the same three clips), which makes it the weaker discriminator of the two but a useful cross-check: on this material the two agreed on the ordering in every comparison run.

**Arbitrary threshold shares, exactly, via `lutyuv` + `YAVG`.** Threshold the luma plane to 0/255 and read the mean; divide by 255:

```bash
ffprobe -v error -f lavfi \
  -i "movie=v1e.mp4:seek_point=43.5,fps=2,lutyuv=y='if(lt(val,20),255,0)',signalstats" \
  -show_entries "frame_tags=lavfi.signalstats.YAVG" -of json -read_intervals "%+1.6"
# YAVG/255 -> 0.02227, 0.01052, 0.01691   (== numpy on the coded Y plane, to 5 dp)
```

**Two thresholds in ONE decode pass, via `geq` into two planes.** Force `yuv444p` first (so the chroma plane is not subsampled) and write one predicate to Y and the other to Cb:

```bash
ffprobe -v error -f lavfi -i "movie=v1e.mp4:seek_point=43.5,fps=2,format=yuv444p,\
geq=lum_expr='if(lt(lum(X\,Y)\,20)\,255\,0)':cb_expr='if(gt(lum(X\,Y)\,235)\,255\,0)':cr_expr='128',\
signalstats" -show_entries "frame_tags=lavfi.signalstats.YAVG,lavfi.signalstats.UAVG" -of json
```

Measured against two separate `lutyuv` passes: `crushed = 0.02227 / 0.01052 / 0.01691` and `blown = 0.00002 / 0.0 / 0.0` — **identical to five decimal places by both routes**. So crushed and blown cost one pass together, not two.

**The flicker check, zero-dep.** `YDIF` reproduces `flicker.py` directly. Measured on `que_calor_v1e.mp4`, 3 s from t=55, mean `YDIF` over 89 frames, expressed as a ratio to the unstyled source's own:

| chain | mean `YDIF` | ratio to source |
|---|---|---|
| source (`v1e`) | 14.6776 | 1.00× |
| `lut3d` + posterise (the fixed-LUT stage) | 16.4263 | **1.12×** |
| `bilateral` + `lut3d` + posterise | 14.8110 | 1.01× |
| half-res round trip + `bilateral` + `lut3d` + posterise | 13.3210 | **0.91×** |
| `elbg=codebook_length=16:nb_steps=1:seed=1` (per-frame codebook) | 15.0339 | 1.02× |
| `elbg` with `pal8=1` | 15.0313 | 1.02× |

The reported range for the real chain is "0.89–1.12× the source's own". A completely different instrument, on the delivered file, lands at **0.91×–1.12×**. That is about as clean an independent reproduction as this kind of claim gets, and it means the frame-independence property that justified the whole look is **checkable in CI, offline, with no dependency**.

One honest negative from the same table: I expected `elbg` — ffmpeg's per-frame codebook posteriser, and the filter a naive implementer would reach for instead of a fixed `lut3d` — to flicker. **It did not**, at `codebook_length=16, nb_steps=1`, on this material: 1.02×. So the argument for a fixed LUT over `elbg` stands on *determinism and inspectability*, not on measured flicker, and any note claiming otherwise is overstating. Whether `elbg` flickers at larger codebooks or on other material is **unverified**.

### 2c. Cost, measured

`Que Calor 03.mp4`, 260.24 s, 1024×576, on this machine:

| pass | wall time | marginal cost |
|---|---|---|
| decode only, `-f null -` | **1.28 s** | — |
| + `fps=2, signalstats` | **1.43 s** | +0.15 s — essentially free |
| + `fps=2, blurdetect` | **6.03 s** | +4.75 s |
| + `fps=2, siti` | **7.47 s** | +6.19 s ≈ 12 ms/frame at 520 frames |
| all three at `fps=2` | **13.90 s** | 18.7× realtime |

**`signalstats` is free; `siti` and `blurdetect` are not.** So the default measurement profile is `signalstats` + the `geq` threshold pair on every clip (about 2× decode), and `siti` only when a sharpness statistic is actually the resolver's objective. Note that `fps=2` placed *before* `siti` also means its `ti` output is a half-second difference rather than a frame difference — SI is unaffected (it is per-frame), **TI under a decimating `fps=` is not the P.910 quantity** and must either be dropped or measured in a separate full-rate pass. Use `YDIF` for temporal work instead; it is free.

### 2d. What tier (a) genuinely cannot do

- **A CIELAB L\* histogram.** `tonematch.py`'s whole method — build the monotone curve carrying the source's L\* CDF onto the reference's — lives in the numpy tier. A single L\*-bin *share* is reachable (one `lutyuv` threshold per bin edge, and the `geq` trick gets two per pass), but 20 bins is 10 passes, and L\* is not a function of gamma-encoded Y alone in any case.
- **The luma median.** `signalstats` gives `HUEMED` but no `YMED`; bisection would cost 8 passes. Use `YAVG` and say so.
- **An arbitrary percentile.** p10/p90 or nothing.
- **A Laplacian variance.** `siti.si` is the substitute, and it is a different functional (see §1b).
- **Anything per-region.** Every statistic here is whole-frame. The Que Calor crop decision needed a *spatial* saliency profile; that is `muvid`'s and out of scope.
- **`cv2.VideoCapture` is not a fallback for tier (a).** Measured today: `cv2.VideoCapture` returned `isOpened() == False` on all three footage files where ffmpeg read them without complaint. That was a sandbox permission artefact on this run rather than a codec failure, so it does not prove OpenCV cannot read them — but it does prove the two readers fail *independently*, which is itself a reason for the measurer to be one path, not two.

---

## 3. The normalise-the-OUTPUT rule, as an algorithm

### 3a. Statement

Given sources `S`, an effect `E` with a free parameter `θ` drawn from a finite per-source grid `G_s`, a statistic `σ` extracted from a `ClipStats`, and a probe budget of `k` frames per (source, setting):

> Choose `θ_s` for each `s` so as to **minimise the dispersion of `σ(E(s, θ_s))` across `S`** — never to maximise `σ`, never to hit an absolute target, and never to compensate the *input*.

Three anti-rules, each of which the source material paid for:

1. **Never "sharpen the soft one".** The intervention is on the output distribution, not the input one. c03 was fixed by making its *flattening* gentler, not by adding an `unsharp`.
2. **Never pick the sharpest available setting.** Full resolution was available, scored ~150 against c01's 72 and c02's 114, and was **deliberately not used** — it would have made the softest source the sharpest thing in the edit, a new mismatch rather than a fix. Reproduced today on the ffmpeg stand-in effect: "always pick the sharpest" gave spread 2.364×, *worse* than the best uniform setting's 2.213×.
3. **Never a target in absolute units.** The family centre is whatever the clips agree on. This is the same choice `autograde.py` made when it set its target to the *median of the three clips* — "pull toward each other, don't invent a look".

### 3b. The solver is exact, and it is not a search

Take `σ > 0` and use the **log-range** dispersion, `D = max_s log M[s][θ_s] − min_s log M[s][θ_s]`, i.e. the max/min ratio. That is the right functional for two reasons: every reported figure in the source material is a ratio ("2.98× → 1.59×", "205% retained", "0.89–1.12×"), and the statistic is positive and multiplicative, so a variance in raw units would let one bright clip dominate.

`D` depends on the chosen vector **only through its max and min**. So the problem is: *given N sorted lists of measured values, find the narrowest window `[lo, hi]` that contains at least one element from every list.* That is a classical two-pointer sweep:

```python
def narrowest_window(values):
    """values: {source_id: [(param, statistic), ...]} -> (lo, hi, {source_id: param}).

    Sort all (statistic, source_id, param) triples; advance a right pointer until
    every source is represented in the window, then advance the left pointer while
    it still is. O(N log N) in N = total number of measured points -- EXACT, not
    a heuristic, and it does not blow up with the number of clips the way an
    exhaustive product (|G|^|S|) does.
    """
```

Cost: `O(N log N)` where `N = Σ_s |G_s|`. For 3 clips × 4 settings that is 12 points; for 30 clips × 8 settings it is 240. The exhaustive product used in the demonstration below is `4³ = 64` and is fine at that size and catastrophic at 30 clips (`8³⁰`). **Use the sweep.**

Ties are common (many assignments realise the same window). Break them, in order: (i) minimise the sum of squared log deviations from the window's geometric centre — pulls everyone toward family rather than parking two clips at the edges; (ii) prefer the cheaper `θ` (a smaller round-trip scale is ~6× faster, measured in §3e) — this is what makes "leave c01 and c02 unchanged" fall out for free; (iii) lexicographic on grid index, for determinism.

### 3c. The verdicts — the resolver must be allowed to say "no"

Four outcomes, and three of them are not a parameter table:

- **`already_in_family`** — the baseline dispersion is already inside `tolerance`. Return the uniform default and change nothing.
- **`inside_noise`** — the best `D` and the best *uniform* `D` differ by less than the pooled measurement uncertainty. Return the uniform default **and say why**. §3d shows this is not a rare corner.
- **`improved`** — `D` reduced by more than the uncertainty.
- **`grid_exhausted`** — the best `D` is still above `tolerance`. The parameter is not powerful enough; report it, never silently accept the best of a bad set. The demonstration in §3e lands here, which is the honest outcome for that particular stand-in effect.

`objective` is typed `Literal["min_spread"]` — an enum with exactly one member. That is a **statement**, not a stub: it makes "maximise the statistic" unrepresentable rather than merely discouraged.

### 3d. How many probe frames — the source's k=3 is too small

Measured today. Take the delivered `que_calor_v2c.mp4`, measure `siti.si` at every EDL span midpoint (16–17 spans per clip), then ask how far the median of a random k-subset falls from the full-sample median (400 draws, seeded):

| clip | spans | full median | min–max | k=1 med / p90 | k=3 med / p90 | k=5 med / p90 | k=9 med / p90 |
|---|---|---|---|---|---|---|---|
| c01 | 17 | 54.99 | 27.6–74.5 | 13.9% / 41.3% | 7.8% / 34.0% | 6.0% / 19.6% | 5.3% / 8.5% |
| c02 | 16 | 63.22 | 39.6–75.1 | 10.0% / 28.9% | 3.4% / 12.7% | 3.4% / 10.0% | 1.8% / 6.5% |
| c03 | 17 | 34.07 | 23.1–43.8 | 11.8% / 28.5% | 8.8% / 14.2% | 5.3% / 12.2% | 3.6% / 8.8% |

Read this against the decisions the resolver makes:

- **Identifying the outlier is easy and k=3 suffices.** c03 (34.1) against c02 (63.2) is 1.85× — far outside the p90 error at any k in the table. The Que Calor fix was exactly this shape, which is why 3 frames was enough *for that decision*.
- **Ranking two clips 10–15% apart is not possible at k=3.** c01 (55.0) against c02 (63.2) is 1.15×, comfortably inside the k=3 p90 of 12.7–34.0%. This is precisely why c01 and c02 swapped between instruments in §1b and between windows in §2b — the difference was never resolvable at that sample size. Anyone who "fixes" it is fitting noise.

**Default `k = 5`**, and require the reported improvement to exceed the measured uncertainty or return `inside_noise`. Estimate the uncertainty by bootstrap over the k probe frames — free, since the frames are already measured.

**Probe frame selection is part of the measurement's identity.** Measured: taking the 3 *widest* spans gave c01 a pre-effect `siti.si` of 30.7, where all 17 spans gave 41.9 — a 27% move from the sampler alone, comparable in size to the effect being tuned. So: weight by screen time, spread across the whole timeline rather than taking the first k, seed deterministically, and record the rule in `ClipStats.sample_spec`.

### 3e. A reproducible end-to-end demonstration

The real Que Calor flattener is `cv2.pyrMeanShiftFiltering`, which has no ffmpeg equivalent. But the *knob that mattered* was measured to be the downscale/upscale round trip and not the filter's colour radius ("`sr` of 30/45/55/60 all land 139–160 at full res"), and a round trip **is** ffmpeg-expressible. So here is the same-shaped effect, entirely in ffmpeg 8.1:

```
scale=iw*s:ih*s:flags=area , bilateral=sigmaS=8:sigmaR=0.2 , scale=iw/s:ih/s:flags=bicubic ,
lut3d=que_calor_b.cube , lutrgb=r='trunc(val/18)*18+9':g=...:b=...
```

Free parameter `s ∈ {0.5, 0.625, 0.75, 1.0}`; statistic `siti.si`; 3 probe frames per (clip, setting), taken at the midpoints of each clip's three widest EDL spans; objective `min_spread`. Real output:

```
PRE-effect siti.si (the INPUT statistic): {'c01': 30.7, 'c02': 69.1, 'c03': 38.5}

POST-effect siti.si  (rows = clip, cols = round-trip scale)
              0.5     0.625      0.75       1.0
  c01       23.01     23.42     23.95     25.41
  c02       50.92     52.35     54.58     60.08
  c03       26.04     27.14     28.60     32.33

best UNIFORM setting       : s=0.5   spread=2.213x   values=[23.0, 50.9, 26.0]
best PER-CLIP assignment   : {'c01': 1.0, 'c02': 0.5, 'c03': 0.5}
                                    spread=2.004x   values=[25.4, 50.9, 26.0]
'always pick the sharpest' : {'c01': 1.0, 'c02': 1.0, 'c03': 1.0}
                                    spread=2.364x   values=[25.4, 60.1, 32.3]

36 probe renders (+9 pre-effect) in 11.3s wall
```

Four things this establishes, and one it does not:

1. **The ordering of the three strategies is the one the source material argued for.** Per-clip (2.004×) beats uniform (2.213×) beats sharpest-everywhere (2.364×). The naive heuristic is the worst of the three.
2. **The algorithm pushes clips in *opposite* directions** — c01 up to `s=1.0`, c02 and c03 down to `s=0.5`. No "sharpen the soft one" rule produces that.
3. **The verdict here is `grid_exhausted`, not `improved`.** 2.004× against a plausible tolerance of 1.5× means the parameter is not powerful enough on this effect: `bilateral` at these settings is far weaker than mean-shift, and c02 sits above the others even at its gentlest setting. The resolver's job is to *say* that, and the reason it must have that verdict at all is that the alternative — silently returning the best of a bad set — reads identically to success.
4. **The cost is trivial.** 45 probe measurements in 11.3 s wall.
5. **What it does not establish** is that this stand-in behaves like the real chain. It does not: the real mean-shift + gradient-map LUT *raised* c01 by 105% of its input, while this one lowers everything. The demonstration proves the machinery, not the look.

### 3f. Probe cost, in proportion

| probe | measured cost |
|---|---|
| ffmpeg-only, 3 frames, decode + `lut3d` + posterise + `siti`+`blurdetect`+`signalstats` | **0.30 s** |
| same, measurement only (no effect) | 0.23 s |
| OpenCV `pyrMeanShiftFiltering` at 1280×720 (cv2 5.0.0, `~/.pyenv/versions/3.12.12`) | scale 0.5 → **106 ms/frame**; 0.75 → **287 ms/frame**; 1.0 → **620 ms/frame** |

So a full sweep for the real Que Calor chain — 3 clips × 8 settings × 5 frames = 120 flatten calls plus 120 LUT measurements — is roughly 120 × 300 ms + 40 × 0.30 s ≈ **48 s**. Against it: c03 alone is 17 spans × ~3.14 s ASL × 30 fps ≈ 1600 frames at 287 ms ≈ **460 s** of flatten time for one clip in one render.

**The whole search costs about 10% of one clip's single render, and about 3% of the full three-clip render.** That is the number that settles whether auto-tuning is worth having: yes, comfortably, and by an order of magnitude if the effect is ffmpeg-expressible.

---

## 4. Where the search lives — and the invariant that keeps `looks` from becoming muvid

### 4a. The objection, stated fairly

The kickoff's rule is unambiguous: *"Execution and muxing. muvid's `assemble.py` owns a bounded-memory invariant won after 30-cut OOM kills. A convenience `looks.render(clip, look)` will get used and will rebuild one big `-filter_complex`."* An auto-tuner that runs probe renders is running the effect. That is execution. So the tuner belongs outside.

### 4b. Why the objection does not survive the distinction it depends on

The rule is about **producing the deliverable**. The bounded-memory invariant it protects is about a *whole-timeline* `-filter_complex` with N cut inputs — `render_v2c.py`'s answer is to chunk the timeline into 8-second pieces, render each in an isolated process with a raw-video pipe, and concat, precisely so that no single ffmpeg graph holds the edit. None of that is at stake in a five-frame probe. A probe has no timeline, no inputs to join, no concat, no mux, and no output file.

And there is a stronger structural argument. The measurer and the compiler are things `looks` **already** owns and nobody else can: `looks` is the layer that knows a clip's `color_range`, knows the luma space a threshold was taken in, and knows the ffmpeg filter chain a named effect compiles to. A resolver built anywhere else would have to reimplement all three, and the two measured traps in §1c and §1b are exactly the ones a reimplementation gets wrong.

### 4c. The invariant, which is testable rather than aspirational

> **Every ffmpeg process `looks` starts ends in `-f null -`.**

That single sentence is the boundary. It admits every measurement, every probe, and every diagnostic. It excludes, structurally and not by convention, every render, every encode, every mux, every concat, and therefore `looks.render()` — which cannot be written without violating it. It is checkable by a test that intercepts the subprocess layer and asserts the argv of every invocation, and it is checkable by a `rg` over the package for encoder flags. Contrast with a comment saying "please don't add a render function", which is what such rules usually amount to.

Two corollaries:

- A `Look` that compiles to a non-ffmpeg backend (OpenCV mean-shift; a shader; a model) **cannot be probed by the default prober**, and must raise a typed error naming the injected `Prober` the caller has to supply. It must not silently skip, and it must not silently fall back to measuring the un-effected frames — that would return a confident wrong answer, which is worse than a refusal, and it is the same failure family as the `elbg` assumption in §2b that I had to withdraw.
- The **policy** is the caller's. What tolerance is acceptable, which clips are in scope, what to do about `grid_exhausted`, whether to spend the 48 s at all — those belong to `nw` (as a `Transform` whose `params_model` carries the tolerance and whose `impl_version` covers the objective), or to the app. `looks` returns evidence and a recommendation; it does not decide.

### 4d. The API

```python
"""Resolving an effect's free parameters against the clips it will be applied to."""

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol, Sequence

Params = Mapping[str, Any]


class Measurer(Protocol):
    """Measure one media path over an interval set -> one ClipStats.

    The default implementation is ffmpeg-only and ends in ``-f null -``.
    """

    def __call__(
        self, media: str, *, intervals: Sequence[tuple[float, float]],
        source_id: str, stage: str, n_frames: int, seed: int,
    ) -> ClipStats: ...


class Prober(Protocol):
    """Apply an effect at candidate params to k frames and measure the RESULT.

    The default implementation composes the Look compiler with the Measurer and
    still ends in ``-f null -``: it decodes k frames, pushes them through the
    compiled filter chain, and reads the statistic back. A Look whose backend is
    not ffmpeg-expressible raises ``ProbeBackendUnavailable`` naming this seam --
    it never degrades to measuring the un-effected frames.
    """

    def __call__(
        self, media: str, *, source_id: str,
        intervals: Sequence[tuple[float, float]], effect: str, params: Params,
        n_frames: int, seed: int,
    ) -> ClipStats: ...


#: Default probe frames per (source, setting). k=3 -- the count the Que Calor
#: work used -- carries a measured p90 relative error of 12.7-34.0%, larger than
#: most improvements a resolver chooses between. k=5 halves the p90.
DFLT_PROBE_FRAMES = 5
#: Below this ratio the clips count as already in family; no change is proposed.
DFLT_TOLERANCE = 1.25


@dataclass(frozen=True)
class ResolutionRequest:
    """What to resolve, over what grid, against what statistic."""

    effect: str
    grid: Mapping[str, Sequence[Params]]  # source_id -> candidate parameter sets
    statistic: str = "sharpness"
    objective: Literal["min_spread"] = "min_spread"  # one member ON PURPOSE
    tolerance: float = DFLT_TOLERANCE
    n_probe_frames: int = DFLT_PROBE_FRAMES
    seed: int = 0


Verdict = Literal["already_in_family", "inside_noise", "improved", "grid_exhausted"]


@dataclass(frozen=True)
class Resolution:
    """The resolver's evidence and its recommendation. Never just a table."""

    verdict: Verdict
    per_source: Mapping[str, Params]
    achieved: Mapping[str, float]          # post-effect statistic per source
    baseline: Mapping[str, float]          # pre-effect, for the record only
    spread: float                          # max/min of `achieved`
    uniform_spread: float                  # the best single-setting alternative
    uncertainty: Mapping[str, tuple[float, float]]   # bootstrap CI per source
    n_probes: int
    instrument: str
    note: str                              # why this verdict, in one sentence


def resolve(
    request: ResolutionRequest,
    sources: Mapping[str, str],                 # source_id -> media path
    source_map: "SourceMap | None" = None,
    *,
    prober: Prober | None = None,               # None -> the ffmpeg default
    measurer: Measurer | None = None,
) -> Resolution:
    """Probe, then pick per-source parameters that minimise the OUTPUT spread."""


def narrowest_window(
    measured: Mapping[str, Sequence[tuple[Params, float]]],
) -> tuple[float, float, Mapping[str, Params]]:
    """The exact solver: smallest [lo, hi] containing one value from every source.

    O(N log N) two-pointer sweep over the sorted measurements. Pure, no I/O, no
    dependency -- and it is the piece of this layer that nothing else in the
    federation has.
    """
```

---

## 5. The identity problem: what type `looks` accepts

### 5a. The problem, from the source

`render_v2c.py` stylises `que_calor_v1e.mp4` — a finished, flattened render. Its own comment states the difficulty exactly: the spans are *"in OUTPUT time — the stylizer sees a finished render and has no other way to know which source a frame came from."* Its implementation is thirteen lines:

```python
def _spans(edl_path):
    cfg = json.load(open(edl_path))
    t0 = cfg["edl"][0]["song_start"]
    return [(e["song_start"] - t0, e["song_end"] - t0, e["clip_id"]) for e in cfg["edl"]]

def _clip_at(spans, t):
    for a, b, c in spans:
        if a <= t < b:
            return c
    return ""
```

and then, per decoded frame: `sc, sp, sr = MS_PARAMS.get(_clip_at(spans, start + count / FPS), MS_DEFAULT)`.

### 5b. The decision: accept a `SourceMap`, and support both application points

**Recommended path: apply the effect per cut, before assembly.** There the `source_id` is known by construction, there is no identity problem at all, `muvid.assemble` already renders one bounded ffmpeg per cut, and the parameter switch happens *at* a cut where a discontinuity is invisible. `looks` should document this as the default and make it the easy thing.

**Supported path: apply to a finished render, with a `SourceMap`.** This exists because it is what actually happened, and it happens for good reasons: re-rendering V1 is expensive, and a stylizer is frequently applied to a timeline someone else cut. The `SourceMap` is what makes that path honest instead of guessy.

```python
"""Which source is on screen when — in OUTPUT time. Not an EDL."""

from dataclasses import dataclass
from bisect import bisect_right


@dataclass(frozen=True)
class Segment:
    """A half-open output-time interval [start, end) attributed to one source."""

    start: float
    end: float
    source_id: str


@dataclass(frozen=True)
class SourceMap:
    """An ordered, non-overlapping, gap-tolerant labelling of output time.

    It answers exactly one question -- *which source is on screen at output time
    t* -- and deliberately cannot answer any other. In particular it does NOT
    carry ``clip_in``, so **you cannot re-render from it**. That is the test that
    separates it from an EDL, and it is checkable rather than rhetorical: the
    Que Calor EDL entry has nine fields (``song_start``, ``song_end``,
    ``clip_id``, ``clip_in``, ``duration``, ``bars``, ``energy``, ``framing``,
    ``score``); a stylizer read three of them, one of which was a normalisation.

    Frozen, with no ``insert`` / ``split`` / ``ripple`` / ``retime``. `looks`
    ships no constructor that INVENTS segments -- only adapters that project a
    decision something else already made.
    """

    segments: tuple[Segment, ...]
    duration: float | None = None

    def source_at(self, t: float) -> str | None:
        """The source on screen at output time ``t``, or ``None`` in a gap."""
        i = bisect_right(self._starts, t) - 1
        if i < 0:
            return None
        seg = self.segments[i]
        return seg.source_id if t < seg.end else None

    def intervals_for(self, source_id: str) -> tuple[tuple[float, float], ...]:
        """Every interval this source occupies — the probe sampler's input."""

    def screen_time(self) -> dict[str, float]:
        """Seconds per source — the weights the resolver's dispersion uses."""
```

### 5c. Why this does not become an EDL

Five properties, each doing work:

1. **It is not sufficient to render.** Without `clip_in` you cannot fetch the frames. An EDL *produces* the picture; a `SourceMap` only *labels* one that exists. This is the crisp, testable definition.
2. **It is frozen and has no editing verbs.** No insert, no split, no ripple, no retime. Every mutation route is absent from the type.
3. **`looks` never authors one.** Only adapters that read one from elsewhere.
4. **Parameters may only change at segment boundaries.** A per-source parameter switch is a visible discontinuity between adjacent frames; it is invisible only because a cut is already there. So a `SourceMap` whose boundaries are not co-extensive with the cuts is a misuse, and the resolver should refuse to emit per-source parameters for it. (`render_v2c.py` gets this right by construction — it recomputes `_clip_at` per frame, so a chunk straddling a cut switches parameters mid-chunk, at the cut.)
5. **It has one honest limitation, stated rather than hidden.** A `Segment` carries one label, so a *transition* region — where two sources are both on screen, which is precisely what the six transitions `looks` inherits from `mixing.video.video_concat` produce — cannot be expressed. The v1 rule: a transition region takes the **incoming** source's label, and a parameter that differs sharply across a transition is a `looks` warning, not a silent blend. Whether a weighted, overlapping `SourceMap` is worth having is an open question, not a v1 feature.

### 5d. `lacing` — yes, as an optional adapter, and it does not touch zero-deps

The shape is already there. `muvid.footage.lacing_bridge` emits three body schemas — `annot://schema/clip-alignment/v1`, `annot://schema/clip-score-track/v1` and `annot://schema/music-video-edl/v1` — with the EDL living on a `DECISION` tier, times quantised to a microsecond rational grid, and a documented round trip `annotate → edit → export → render` [12]. A `SourceMap` is a **projection of that DECISION tier**: take each entry's interval and `clip_id`, drop the other seven fields.

The precedent for how to wire it is `illustration.persistence` [7], and it is worth copying exactly:

- the module is behind an optional extra (`illustration[persist]` → `looks[lacing]`);
- `import lacing` happens **inside** the functions, never at module top, so the base package never requires it;
- the module docstring states the modelling choice it made and why (illustration's is "selections are keyed on an ordinal beat-index timeline, which is honest, and if a general 'selection track' facade proves worth sharing it belongs upstream in `lacing`");
- and it is explicitly *"a thin adapter … it does **not** reinvent an annotation store."*

One deviation is forced: `illustration.persistence` imports `pydantic` at module top, which it can do because `illustration` declares `pydantic` as a base dependency. `looks` declares nothing, so its lacing adapter must build plain dicts and let `lacing` validate them — which is fine, since the adapter only ever **reads**.

**And it reads only.** `looks.adapters.lacing.source_map_from_decision_tier(store, tier="DECISION")` and nothing that writes an EDL annotation. Writing a decision tier is `muvid`'s and `nw`'s job; a stylization facade that could author one would have acquired exactly the authority the kickoff forbids it.

Three adapters, all optional, none in the base import:

| adapter | reads | extra |
|---|---|---|
| `looks.adapters.lacing` | a `lacing` DECISION tier (`music-video-edl/v1` and anything interval+label shaped) | `looks[lacing]` |
| `looks.sourcemap.from_records` | any `Sequence[Mapping]` with configurable key names — the Que Calor `edl_v1d.json` in three lines | **none** (stdlib) |
| `looks.adapters.otio` | an OTIO timeline's track/clip structure | `looks[otio]` — **unverified**, no OTIO round trip was run for this note |

`from_records` is deliberately in the base package and deliberately stdlib: the common case is a JSON file someone already has, and making that require an extra would push callers back to hand-rolling `_clip_at`.

---

## 6. Recommendations

1. **`ClipStats` as specified in §1d**, with `stage`, `instrument`, `luma_space` and `sample_spec` as identity fields, and a comparison that raises across mismatched identity.
2. **Reuse `muvid`'s `sharpness` verbatim; do not reuse `exposure`.** muvid's `exposure` is a [0,1] composite health score, not a luma quantity. Spell luma `luma_p10 / luma_mean / luma_p90`.
3. **Default measurement tier is ffmpeg-only**, read through `ffprobe -f lavfi … -of json`. `signalstats` always (it is free); the `geq` two-plane threshold pass for crushed+blown; `siti` only when sharpness is the objective (it costs ~5× the decode).
4. **Reject the pure-stdlib pixel tier.** The transport is stdlib (`json`); the arithmetic is not.
5. **Objective is `min_spread` in log units, with exactly one member in the enum.** Solve it with the exact two-pointer sweep, not an exhaustive product and not a heuristic.
6. **Default `k = 5` probe frames**, bootstrap the uncertainty, and return `inside_noise` when the improvement does not clear it. Record the sampler in `sample_spec`.
7. **Auto-tuning is in scope; producing a deliverable is not.** The boundary is the testable invariant *every ffmpeg process `looks` starts ends in `-f null -`*. A non-ffmpeg backend raises for an injected `Prober` rather than degrading.
8. **`looks` accepts a `SourceMap`**, frozen and unable to re-render, with `lacing` and OTIO as optional read-only adapters and a stdlib `from_records`. It never authors one.
9. **Prefer per-cut application** and document it as the default; the finished-render path exists because it is the real case, not because it is better.
10. **A licence note that falls out of this work:** `autograde.py`'s measured continuity grade compiles to `eq=gamma=…:contrast=…:saturation=…`, and `eq` is **GPL-gated** in ffmpeg [13]. A licence-tiered resolver must therefore be able to emit the same correction through `colorlevels` / `curves` / `colorbalance`, which are not — exactly the substitution the sibling prior-art note identifies as `looks`' reason to exist [14]. Whether that substitution is numerically equivalent is **unverified** and should be measured before it is offered.

## 7. Open questions

- **Does the `siti.si` ↔ Laplacian-variance relationship hold post-effect?** The +0.923 Pearson against √(lapvar) was measured on *source* frames. The stylizer creates hard flat-region boundaries, which is a different image statistic regime. **Unverified.**
- **What is the right dispersion functional above three clips?** Max/min is defensible at N=3 and fragile at N=30, where one bad clip sets the whole window. A weighted MAD in log space, or a trimmed range, is probably right — but nothing here measures it.
- **Does the two-pointer solver need a per-source feasibility relaxation?** If one source's grid cannot reach the family at all, the current formulation returns `grid_exhausted` for everyone. Dropping that source from the window and reporting it separately may be more useful.
- **Transitions.** A weighted, overlapping `SourceMap` versus the "label with the incoming source" rule. Deferred.
- **Does `elbg` flicker at larger codebooks?** Measured at `codebook_length=16` it does not (1.02×). **Unverified** elsewhere.

---

## REFERENCES

1. [FFmpeg Filters Documentation — `signalstats`](https://ffmpeg.org/ffmpeg-filters.html#signalstats). Read from the local `ffmpeg-filters(1)` man page shipped with homebrew ffmpeg 8.1_1, 2026-09-02. Source of the verbatim definitions of `YLOW` ("the Y value at the 10% percentile"), `YHIGH` (90%), `YDIF` ("the average of sample value difference between all values of the Y plane in the current frame and corresponding values of the previous input frame"), `TOUT`, `VREP` and `BRNG`.
2. [FFmpeg Filters Documentation — `blurdetect`](https://ffmpeg.org/ffmpeg-filters.html#blurdetect). Same source. "Determines blurriness of frames without altering the input frames. Based on Marziliano, Pina, et al. 'A no-reference perceptual blur metric.'"
3. [FFmpeg Filters Documentation — `siti`](https://ffmpeg.org/ffmpeg-filters.html#siti). Same source. "Calculate Spatial Information (SI) and Temporal Information (TI) scores for a video, as defined in ITU-T Rec. P.910 (11/21) … Note that this is a legacy implementation that corresponds to a superseded recommendation."
4. [ITU-T Rec. P.910 (07/22) — Subjective video quality assessment methods for multimedia applications](https://www.itu.int/rec/T-REC-P.910-202207-I/en). The current recommendation ffmpeg's own docs point at; the filter implements the superseded [P.910 (11/21)](https://www.itu.int/rec/T-REC-P.910-202111-S/en). Not read for this note — cited as ffmpeg documents it.
5. Marziliano P, Dufaux F, Winkler S, Ebrahimi T. *A no-reference perceptual blur metric.* Proc. IEEE ICIP 2002. The metric `blurdetect` implements, per [2]. Not read for this note.
6. `looks` research note — *Evidence: the colour trap in an ffmpeg colour chain is RANGE, not pixel format*, `/Users/thorwhalen/Dropbox/py/proj/t/looks/docs/research/00b_colour_range_trap_evidence.md`, 2026-09-02. Establishes that `color_range=unknown` is the normal case and silently changes what a LUT does; §1c above is its measurement-side twin.
7. `illustration.persistence` — `/Users/thorwhalen/Dropbox/py/proj/t/illustration/illustration/persistence.py`. The optional-lacing-adapter pattern: lazy import inside functions, behind an extra, "a thin adapter … it does **not** reinvent an annotation store."
8. `muvid.footage.scoring.orchestrator` — `/Users/thorwhalen/Dropbox/py/proj/t/muvid/muvid/footage/scoring/orchestrator.py:34`. `DEFAULT_METRICS = ("sharpness", "exposure", "stability_shake", "face_framing", "motion_beat_bas", "motion_onset_xcorr")`.
9. `muvid.footage.scoring.grid` — `/Users/thorwhalen/Dropbox/py/proj/t/muvid/muvid/footage/scoring/grid.py`. `ScoreTrack`, the shared song-time grid, "raw is the SSOT", per-metric-global robust normalisation clipped at the 5th/95th percentiles.
10. `muvid.footage.scoring._frame_metrics` — `/Users/thorwhalen/Dropbox/py/proj/t/muvid/muvid/footage/scoring/_frame_metrics.py`. `sharpness` = Laplacian variance; `exposure_quality` = `clip_ok * contrast`, the composite this note argues `looks` must not reuse by name. Also flagged there as a "promotion candidate for `mixing.video`".
11. *How the video got made — Technical*, `~/Downloads/que_calor/how_the_video_got_made__technical.md`, and the scripts under `~/Downloads/que_calor/work/{style,analysis,survey,palette}/`. Source of the V2b→V2c figures (72.2 / 114.3 / 38.4 → 71.8, spread 2.98× → 1.59×), the per-source resolutions (478×850, 848×478, 1024×576), and the `sr` insensitivity result.
12. `muvid.footage.lacing_bridge` — `/Users/thorwhalen/Dropbox/py/proj/t/muvid/muvid/footage/lacing_bridge.py`. `annot://schema/music-video-edl/v1` on a `DECISION` tier, and `edl_from_annotations` — the projection a `looks` `SourceMap` adapter reads.
13. [FFmpeg Filters Documentation — `eq`](https://ffmpeg.org/ffmpeg-filters.html#eq). GPL-gated in ffmpeg's `configure`; observed present in this build, which is `--enable-gpl`.
14. `looks` research note — *External prior art: what already exists, and how `looks` is different*, `/Users/thorwhalen/Dropbox/py/proj/t/looks/docs/research/01_prior_art_oss.md`, 2026-09-02. Establishes the `eq`-is-GPL / `colorlevels`-is-not substitution as `looks`' concrete contribution.
15. [OpenCV — `cv2.pyrMeanShiftFiltering`](https://docs.opencv.org/4.x/d4/d86/group__imgproc__filter.html#ga9fabdce9543bd602445f5db3827e4cc0). Timed here at cv2 5.0.0; the ordering claim (`pyrMeanShiftFiltering` over `edgePreservingFilter`) is [11]'s, not re-derived.
