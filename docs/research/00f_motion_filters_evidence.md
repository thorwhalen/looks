# 00f — Which ffmpeg filter compiles a camera path: measured, and a fleet fact corrected

**Status: first-hand evidence.** Every number below came from running the command shown, on the binary named below, on 2026-09-02. Nothing here is quoted from documentation, and where it disagrees with a recorded fleet fact, the measurement wins and the disagreement is stated rather than smoothed over.

**Binary:** `ffmpeg` on PATH — `ffmpeg version 8.1`, the same build `looks.probe()` reports. **Source clip:** `testsrc2=size=320x240:rate=10:duration=2` encoded to H.264/yuv420p — 20 frames, 2.000 s, verified by `ffprobe -count_frames` before every comparison.

---

## 1. Why this note exists

RULE G, ratified 2026-09-02, splits authored geometry from its compilation: `burns` owns the `BurnsPath` (keyframes, easing, the decision that this is the shot), and `looks` owns turning a sampled path into filter syntax. Building the `looks` half requires knowing which filter can express a moving window — and the fleet already had a recorded answer.

`muvid/footage/assemble.py::_crop_filter` carries it in its own docstring, and research note 02 §2.1 and note 11 §4.4 both propagate it verbatim:

> Not `zoompan`: its expression vocabulary has no `t` at all (it exposes `on`/`in`/`pon`), and it duplicates frames on video input.

Note 11 escalates that into a recommendation to hand the `burns` owner: *"the promised zoompan fast-path is questionable for video input"*, and note 02 §2.3 repeats it. So the fleet's position going in was: **compile with `crop`, and warn `burns` off `zoompan`.**

Both of that sentence's premises are true. Its conclusion is wrong, and the module built on it would have been unable to express a zoom at all.

---

## 2. The measurements

### 2.1 `t` is genuinely undefined in `zoompan` — the first premise holds

```
$ ffmpeg -i src.mp4 -vf "zoompan=z='1+0.5*t':d=1:x=0:y=0:s=320x240:fps=10" -f null -
[Parsed_zoompan_0 @ ...] [Eval @ ...] Undefined constant or missing '(' in 't'
[Parsed_zoompan_0 @ ...] Failed to configure output pad on Parsed_zoompan_0
```

Confirmed, and it fails loudly rather than silently — an important detail, because a silent zero would have been far worse.

### 2.2 …but `in_time` and `it` are defined, which the recorded fact omits

| expression | result |
|---|---|
| `zoompan=z='1+0.5*t':d=1:…` | **error** — `Undefined constant … 't'` |
| `zoompan=z='1+0.5*in_time':d=1:…` | **20 frames**, no error |
| `zoompan=z='1+0.5*it':d=1:…` | **20 frames**, no error |

`ffmpeg -h filter=zoompan` does **not** list expression variables at all — it prints only the AVOptions (`zoom`, `x`, `y`, `d`, `s`, `fps`). So the variable set is not discoverable from the binary's own help, which is very likely how the recorded fact came to be half-complete: `t` was tried, it failed, and the conclusion "no time variable" followed. There is a time variable; it is spelled differently.

### 2.3 The frame duplication is real, and `d=1` removes it exactly

Same 20-frame source, counted with `ffprobe -count_frames`:

| `d` | output frames |
|---|---|
| default (`d=90` on this build) | **1800** = 20 × 90 |
| `d=1` | **20** — 1:1 |

So the second premise is true *at the default* and false at `d=1`. `d` is the number of output frames per input frame; it exists for the still-image case, where one input frame must become a whole clip. On video it is simply the wrong default, not an intrinsic property.

### 2.4 `crop` cannot vary a window's SIZE — and this is the decisive fact

The recorded fact recommends `crop`. `crop` can ramp `x` and `y` per frame — verified, two frames at t=0 and t=1.9 hash differently:

```
$ ffmpeg -ss 0   -i src.mp4 -vf "crop=w=160:h=120:x='160*min(t/2,1)':y=0" -frames:v 1 … → fa30f13056e4
$ ffmpeg -ss 1.9 -i src.mp4 -vf "crop=w=160:h=120:x='160*min(t/2,1)':y=0" -frames:v 1 … → ee05cf9e9c26
```

But `t` in `w` or `h` does not merely evaluate once — it is **not in scope and the filter refuses to configure**:

```
$ ffprobe -f lavfi -i "movie=src.mp4,crop=w='iw*(0.9-0.4*t)':h='ih*(0.9-0.4*t)':x=0:y=0"
[Parsed_crop_1 @ ...] Error when evaluating the expression 'ih*(0.9-0.4*t)'
[Parsed_crop_1 @ ...] Failed to configure input pad on Parsed_crop_1
```

This is structural rather than an oversight: a filter link has one fixed frame size, so a per-frame `w` would mean a per-frame output geometry. The same ramp with `t` removed configures fine and yields `288,216` on all 20 frames.

**Consequence:** `crop` cannot express a zoom, at all, ever. A Ken Burns path — which is a zoom by definition — is not compilable to `crop`. `zoompan` is not merely *an* option for it; it is the only one of the two.

### 2.5 `zoompan`'s `x`/`y` are in ORIGINAL input pixels — measured, not assumed

The plausible readings differ by a factor of the zoom, and both are asserted by different sources on the internet. Settled by building the same window two ways and asking `psnr`:

> reference: `crop=w=160:h=120:x=80:y=60,scale=320:240` — the normalised window `(0.25, 0.25, 0.5, 0.5)` of a 320×240 source, resampled to 320×240.

| candidate | reading | PSNR (avg) |
|---|---|---|
| `z=2:x=80:y=60` | x, y in **original input px** | **60.54 dB** |
| `z=2:x=160:y=120` | x, y in zoomed px | 6.34 dB |
| `z=2:x=40:y=30` | half of original | 7.16 dB |

60.5 dB is scaler-choice difference; 6.3 dB is a different picture. So the mapping from a normalised window to `zoompan` is:

```
zoom = 1 / nw          x = nx * iw          y = ny * ih
```

and the visible region in original pixels is `(iw/zoom, ih/zoom)` at `(x, y)`.

**A constraint falls straight out of that, and it is worth stating as a refusal rather than discovering as a bug:** `zoom` is one scalar, so the visible window is always geometrically similar to the source frame — `nw` and `nh` must be equal as normalised fractions. A window with a different aspect ratio than its source cannot be expressed by `zoompan`, and pretending otherwise would silently honour one axis and distort the other.

### 2.6 `in_time` tracks `crop`'s `t` frame for frame

The two filters' clocks agreeing is what lets a compiler choose between them freely. Same pan path (`nx: 0 → 0.5` at `nw = nh = 0.5` over 2 s), compiled both ways, compared with `psnr`:

```
[0:v]zoompan=z=2:d=1:x='320*(0.5*min(in_time/2,1))':y=60:s=320x240:fps=10 [a];
[1:v]crop=w=160:h=120:x='320*(0.5*min(t/2,1))':y=60,scale=320:240        [b];
[a][b]psnr
→ PSNR y:60.543675 average:60.543675 min:58.525377 max:65.851669   (20 frames)
```

**Minimum 58.5 dB on the worst single frame.** The clocks agree; the paths agree; the difference is resampling, not timing.

### 2.7 `zoompan`'s `fps` silently retimes, and is therefore not optional

`d=1` preserves the frame *count* but `fps` restamps them:

| `fps=` | frames out | rate out | duration |
|---|---|---|---|
| `10` (the source's) | 20 | 10/1 | 2.0 s |
| `25` | **20** | 25/1 | **0.8 s** |

The frame count is identical, so a frame-count check — the obvious check — passes in both rows. The clip is 60% shorter in the second. Nothing warns. A compiler must therefore *require* the source rate rather than defaulting to `zoompan`'s own `25`.

### 2.8 `zoom` is clamped at 10, and the clamp is silent

Same reference construction as §2.5 — `zoompan=z=Z` against `crop`+`scale` of the window that Z names:

| `z` | window in original px | PSNR (avg) |
|---|---|---|
| 2 | 160×120 | 59.15 dB |
| 5 | 64×48 | 55.75 dB |
| 10 | 32×24 | **54.39 dB** |
| 12 | 26×20 | **13.17 dB** |
| 20 | 16×12 | 10.65 dB |

The drop between 10 and 12 is not degradation, it is a different picture: past 10 the filter renders the 10× window and says nothing. So the smallest window `zoompan` can show is **1/10 of the frame**, and a caller asking for less gets a framing they did not ask for, with no warning anywhere.

`looks.motion` refuses below that fraction rather than passing it through — the same posture as every other refusal in this package, and for the same reason: a silently different answer is worse than no answer.

### 2.9 `clip()` exists, and is not used anyway

`crop=…:x='clip(t*10,0,20)':…` configures and runs. It is nonetheless not what this package emits: `min(max(e,0),1)` is what `muvid._crop_filter` already ships across the fleet's builds, and a two-character saving is not worth a portability question that has been tested on exactly one binary.

---

## 3. What this settles

| motion | filter | why |
|---|---|---|
| static window | `crop` | no clock needed; any aspect |
| **pan** — `x`/`y` vary, size constant | `crop` with ramped `x`/`y` in `t`, `setpts=PTS-STARTPTS` prepended | per-frame `x`/`y` confirmed §2.4; any aspect; muvid's shipped form |
| **zoom** — size varies | `zoompan`, `d=1`, `fps=<source rate>`, expressions in `in_time` | `crop` structurally cannot (§2.4); window must keep the source aspect (§2.5) |

## 4. The correction, stated plainly

The recorded fleet fact is **right in both premises and wrong in its conclusion**. `t` really is undefined in `zoompan` (§2.1) and it really does duplicate frames (§2.3) — but `in_time` exists (§2.2) and `d=1` removes the duplication exactly (§2.3), so neither premise survives as an objection. Meanwhile the recommended alternative cannot express the zoom half of the problem at all (§2.4).

`muvid`'s own use is unaffected and its code is correct: `_crop_filter` compiles a *pan* at constant window size, which is exactly the case where `crop` is right and simpler. What is wrong is the docstring's generalisation from "wrong for my case" to "wrong filter", and the two research notes that carried it forward into a warning aimed at `burns`.

**The warning to hand the `burns` owner is therefore withdrawn and replaced.** The `zoompan` fast-path that `burns/backends.py` names is viable on video, on these terms: `d=1`, an explicit `fps` equal to the source rate, expressions in `in_time` rather than `t`, and a window that keeps the source's aspect ratio. All four are compiled by `looks.motion`, so an adapter does not have to remember any of them.

## 5. What this note does not claim

- **No benchmark.** Note 11 flagged that the *speed* advantage of an ffmpeg fast-path over `burns`' `pillow` backend is inherited from a docstring and unmeasured. It still is. Nothing here times anything.
- **One binary.** ffmpeg 8.1 on macOS/arm64. `in_time` has been in `zoompan` for many releases, but "many" is not a version and this note does not pretend to know the floor. A caller on an older build gets a configure-time error, which is loud.
- **The clamp boundary is measured at 10, not read from a spec.** z=10 works and z=12 does not; nothing here tests 10.5, so the boundary is known to lie in (10, 12] and is assumed to be exactly 10 because that is the documented range.
- **No quality claim about `zoompan`'s resampling.** Its integer rounding of `x`/`y` per frame is a known source of stair-step on slow pans. Not measured here; `crop` rounds to integer pixels too, so the pan case is likely a wash, but *likely* is not measured.
