# Evidence: FFmpeg's own licence gates, extracted from `configure` at tag `n8.1`

*2026-09-02. Extracted by the orchestrating session, independently of the research agents, so their licence briefs have something to be checked against. Machine-readable companion: [`ffmpeg_n81_licence_gates.json`](ffmpeg_n81_licence_gates.json).*

## Verdict

Every ffmpeg filter `looks` wants for its colour and geometry vocabulary is **LGPL-safe — except `eq`**, which is GPL-only. `eq` is the obvious brightness/contrast/gamma/saturation filter, i.e. the first thing anyone reaches for to build a grade. That single fact is the clearest possible demonstration of why this package exists: a `looks` Look at an LGPL ceiling must **refuse** `eq` and route the same intent through `curves` / `lutyuv` / `colorlevels` / `colorbalance` / `huesaturation` / `exposure`, all of which are LGPL. Nothing in the ffmpeg CLI tells you this; the binary happily runs `eq` because the binary is GPL.

Two corollaries of the same shape:

- **`cropdetect` is GPL-only**, so an LGPL-safe auto-crop cannot use it — and auto-crop is precisely the kind of thing the geometry tier inherited from `mixing` will want.
- **`libx264` and `libx265` are GPL-only external libraries**, so an LGPL-safe *render* cannot emit H.264 or HEVC through ffmpeg at all. This bounds what "commercial-safe, no-GPL" can actually output, and it is a product constraint, not a footnote.

Also worth recording because it contradicts a plausible guess: **`geq` is NOT GPL-gated.** It is LGPL-safe in 8.1. (The orchestrator guessed otherwise before checking — which is the argument for checking.)

## How this was obtained

FFmpeg's `configure` declares each component's licence gate as a dependency. The authoritative form is `<name>_filter_deps="… gpl …"` for filters, and four named lists for external libraries.

```bash
curl -sL https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1/configure -o configure
grep -E '^[a-z0-9_]+_filter_deps=' configure | grep -E '\bgpl\b'
awk '/^EXTERNAL_LIBRARY_GPL_LIST=/,/^"$/' configure
```

This is a source-of-truth extraction, not documentation reading: the same file is what decides whether `--enable-gpl` is required at build time.

## The 33 GPL-gated filters in n8.1

| filter | declared deps |
|---|---|
| `blackframe` | gpl |
| `boxblur` | gpl |
| `boxblur_opencl` | opencl gpl |
| `colormatrix` | gpl |
| `cover_rect` | avcodec avformat gpl |
| `cropdetect` | gpl |
| `delogo` | gpl |
| `eq` | gpl |
| `find_rect` | avcodec avformat gpl |
| `fspp` | gpl |
| `histeq` | gpl |
| `hqdn3d` | gpl |
| `interlace` | gpl |
| `kerndeint` | gpl |
| `mcdeint` | avcodec gpl |
| `mpdecimate` | gpl |
| `mptestsrc` | gpl |
| `nnedi` | gpl |
| `owdenoise` | gpl |
| `perspective` | gpl |
| `phase` | gpl |
| `pp7` | gpl |
| `pullup` | gpl |
| `repeatfields` | gpl |
| `sab` | gpl swscale |
| `signature` | gpl avcodec avformat |
| `smartblur` | gpl swscale |
| `spp` | gpl avcodec |
| `stereo3d` | gpl |
| `super2xsai` | gpl |
| `tinterlace` | gpl |
| `uspp` | gpl avcodec |
| `vaguedenoiser` | gpl |

`--enable-version3` upgrades (L)GPL to v3; `configure` line 4773 reads `enabled version3 && { enabled gpl && enable gplv3 || enable lgplv3; }`, so version3 alone does **not** imply GPL — the combination does.

## External libraries, by gate

- **GPL** (`EXTERNAL_LIBRARY_GPL_LIST`): `avisynth`, `frei0r`, `libcdio`, `libdavs2`, `libdvdnav`, `libdvdread`, `librubberband`, `libvidstab`, `libx264`, `libx265`, `libxavs`, `libxavs2`, `libxvid`
- **version3** (`EXTERNAL_LIBRARY_VERSION3_LIST`): `gmp`, `libaribb24`, `liblensfun`, `libopencore_amrnb`, `libopencore_amrwb`, `libvo_amrwbenc`, `mbedtls`, `rkmpp`
- **GPLv3** (`EXTERNAL_LIBRARY_GPLV3_LIST`): `libsmbclient`
- **nonfree** (`EXTERNAL_LIBRARY_NONFREE_LIST`): `decklink`, `libfdk_aac`, `libmpeghdec` — a nonfree build is **non-redistributable**, so it is always a refusal.

## Confirmed LGPL-safe (absent from every gate above)

`geq`, `lut3d`, `lut1d`, `lutrgb`, `lutyuv`, `curves`, `colorchannelmixer`, `colorbalance`, `colorlevels`, `colorspace`, `zscale`, `hue`, `pseudocolor`, `elbg`, `deband`, `gblur`, `edgedetect`, `convolution`, `unsharp`, `tmix`, `scale`, `crop`, `pad`, `xfade`, `format`, `tonemap`, `libplacebo`, `vibrance`, `selectivecolor`, `monochrome`, `exposure`, `colortemperature`, `huesaturation`, `signalstats`, `blurdetect`, `entropy`, `histogram`, `atadenoise`, `removegrain`.

Note the substitutions this makes available, which are what turn a refusal into something useful rather than a dead end: `gblur` for `boxblur`, `curves`/`colorlevels`/`exposure` for `eq`, `atadenoise`/`removegrain` for `hqdn3d`.

## The gap this does NOT close

This extraction says what the ffmpeg *project* gates. It says nothing about **which build is on the caller's machine** — a binary configured `--enable-gpl` is GPL whether or not the Look uses a GPL filter, because the binary you executed is the GPL work. Probing the local binary is a separate question (`ffmpeg -L`, `ffmpeg -buildconf`), and the rule there must be **unknown ⇒ refuse**: some distribution builds strip the configuration line, and "no evidence of GPL" is not evidence of LGPL.

## REFERENCES

1. [FFmpeg `configure`, tag `n8.1`](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1/configure) — the extraction source.
2. [FFmpeg License and Legal Considerations](https://ffmpeg.org/legal.html) — the project's own statement that `--enable-gpl` makes the resulting binary GPL.


---

## Correction (same day): the grep recipe was incomplete, in the dangerous direction

The extraction above — `grep -E '^[a-z0-9_]+_filter_deps=' configure | grep gpl` — finds only the filters whose deps line carries the **literal** `gpl`. **Five more are GPL-gated indirectly**, through a library that is itself in `EXTERNAL_LIBRARY_GPL_LIST`, with no `gpl` token anywhere on their own line:

| filter | reaches | which is in |
|---|---|---|
| `frei0r`, `frei0r_src` | `frei0r` | `EXTERNAL_LIBRARY_GPL_LIST` |
| `rubberband` | `librubberband` | `EXTERNAL_LIBRARY_GPL_LIST` |
| `vidstabdetect`, `vidstabtransform` | `libvidstab` | `EXTERNAL_LIBRARY_GPL_LIST` |

So the correct count for n8.1 is **38**, not 33, and the recipe is: literal `gpl` in the deps line **OR** any dep that appears in `EXTERNAL_LIBRARY_GPL_LIST` / `EXTERNAL_LIBRARY_GPLV3_LIST`.

**This is a false permission, which is the direction that matters.** `vidstabtransform` is video stabilisation — a perfectly plausible *normalisation* effect for this package — and the naive table tiers it permissive. A caller asking for stabilisation under an LGPL ceiling would have been allowed, silently, to require a GPL build.

Found by the adversarial review appended to [`01_prior_art_oss.md`](01_prior_art_oss.md), not by any test, and not by the session that wrote this note. `looks/data/ffmpeg_gates.json` is now schema `v2` and stores the two classes **separately** (`gpl_filters_direct` / `gpl_filters_indirect`) so a future re-extraction cannot quietly drop one; `looks/tests/test_environment.py::TestIndirectGplGates` asserts each of the five reaches a real GPL library, and pins the count of both halves.

One genuine subtlety this exposed, worth keeping: **a directly-gated filter is present in every GPL build, an indirectly-gated one is not.** The direct set needs only `--enable-gpl`; the indirect set additionally needs its external library, which is a *separate* build flag Homebrew does not pass. So "this GPL build has every GPL-gated filter" is true only of the direct half, and a test that asserts it over both fails for a reason that has nothing to do with licensing.
