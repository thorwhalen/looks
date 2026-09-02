# ffmpeg's internal licence surface, and how `looks` probes the local binary

**Date: 2026-09-02** · anchored to **FFmpeg n8.1** (tag committed 2026-03-16), probed against **ffmpeg 8.1** (Homebrew `ffmpeg/8.1_1`, arm64 macOS) and against a second binary on the same machine, **ffmpeg 7.1** (bundled by `imageio-ffmpeg` 0.6.0).

## Verdict

FFmpeg's GPL surface is **small, enumerable and stable**: exactly **33 filter names** are gated on `--enable-gpl` in `configure` at n8.1, plus `lensfun` which is GPL-3.0-or-later by its own file header while `configure` gates it only on `version3` — 34 names in all, out of 481 filters in the local build (6.7%). **Not one of them is a colour operation.** Everything the Que Calor look needs, and everything on the wanted-filters list except `eq`, `boxblur` and `colormatrix`, is **LGPL-2.1-or-later or more permissive** — including `geq`, which is widely believed to be GPL and has not been since FFmpeg 4.3 (relicensed 2019-12-16, first released 2020-06-15) [4,5]. The GPL wall is not in the filters; it is in the **encoders**: `libx264` and `libx265` are the only H.264/HEVC software encoders FFmpeg has, both GPL-2.0-or-later, so an LGPL-tier *deliverable* is AV1 (SVT-AV1), VP9 (libvpx), a mezzanine codec (ProRes/DNxHD/FFV1), or hardware (VideoToolbox / NVENC) — never libx264. The probe rule is: **`ffmpeg -L` is the only authority on the binary's licence** (it is a compile-time `#if` cascade in `fftools/opt_common.c` [3] and therefore cannot be patched out the way the `configuration:` line can), **`ffmpeg -filters` is the only authority on availability** (`-h filter=NAME` exits 0 for an unknown filter — measured), and anything `-L` does not match is `UNKNOWN`, which refuses. The single most consequential design finding is that **one licence ordinal is not enough**: "would this Look run on a clean-room LGPL build?" and "what does the binary I am about to shell out to carry?" are different questions with different answers, and collapsing them makes every purely-LGPL Look unrunnable on every Homebrew ffmpeg on earth.

---

## 1. The mechanism — how FFmpeg decides its own licence

Four configure flags, one cascade, one string. From `configure` at n8.1, lines 4767-4787 [2]:

```sh
map "die_license_disabled gpl"      $EXTERNAL_LIBRARY_GPL_LIST $EXTERNAL_LIBRARY_GPLV3_LIST
map "die_license_disabled version3" $EXTERNAL_LIBRARY_VERSION3_LIST $EXTERNAL_LIBRARY_GPLV3_LIST

enabled gpl && map "die_license_disabled_gpl nonfree" $EXTERNAL_LIBRARY_NONFREE_LIST
map "die_license_disabled nonfree" $HWACCEL_LIBRARY_NONFREE_LIST

enabled version3 && { enabled gpl && enable gplv3 || enable lgplv3; }
enabled gpl && enable lgpl_gpl # Files that are marked as LGPL but some developers prefer only building them with --enable-gpl

if enabled nonfree;   then license="nonfree and unredistributable"
elif enabled gplv3;   then license="GPL version 3 or later"
elif enabled lgplv3;  then license="LGPL version 3 or later"
elif enabled gpl;     then license="GPL version 2 or later"
else                       license="LGPL version 2.1 or later"
fi
```

Five mutually exclusive outcomes, and the ordering is what a parser must reproduce:

| flags | resulting licence |
|---|---|
| (none) | LGPL-2.1-or-later — the default |
| `--enable-version3` | LGPL-3.0-or-later |
| `--enable-gpl` | GPL-2.0-or-later |
| `--enable-gpl --enable-version3` | **GPL-3.0-or-later** ← the local binary |
| `--enable-nonfree` (with or without the others) | nonfree and unredistributable |

Two details worth carrying into the design:

- **`lgpl_gpl` is a policy flag, not a licence flag.** It marks files that are LGPL-licensed but whose authors prefer them built only under `--enable-gpl`. At n8.1 it applies to **nine audio decoders, one parser and one bitstream filter** and to **no video filter at all** — so `looks` can ignore it. (Grepped: `adpcm_circus`, `adpcm_ima_escape`, `adpcm_ima_hvqm2/4`, `adpcm_ima_magix`, `adpcm_ima_pda`, `adpcm_n64`, `adpcm_psxc`, `ahx` decoder/parser/bsf.)
- **`--enable-version3` is often forced by something innocuous.** The local build carries it because it links OpenSSL 3.6.3, and `configure` line 7493 refuses `--enable-gpl` + OpenSSL ≥ 3.0.0 unless `gplv3` is on [2]. Nobody chose GPL-3 for a video reason; a TLS dependency chose it. `looks` must therefore never infer intent from the flag — only read the outcome.

---

## 2. The GPL-only video filters at n8.1 — the actual list

Established on **three independent axes that agree**: (a) every `<name>_filter_deps=` line in `configure` containing `gpl`; (b) the licence header of every one of the 534 `libavfilter/*.c` files at n8.1, machine-classified; (c) FFmpeg's own `LICENSE.md` at the same tag [1].

**33 filter names gated on `--enable-gpl`** (axis a, verbatim from the grep):

`blackframe`, `boxblur`, `boxblur_opencl`, `colormatrix`, `cover_rect`, `cropdetect`, `delogo`, `eq`, `find_rect`, `fspp`, `histeq`, `hqdn3d`, `interlace`, `kerndeint`, `mcdeint`, `mpdecimate`, `mptestsrc`, `nnedi`, `owdenoise`, `perspective`, `phase`, `pp7`, `pullup`, `repeatfields`, `sab`, `signature`, `smartblur`, `spp`, `stereo3d`, `super2xsai`, `tinterlace`, `uspp`, `vaguedenoiser`

The header scan (axis b) returned **33 GPL-headered video sources**, and `LICENSE.md` (axis c) lists **33 GPL file entries under libavfilter**. The three reconcile exactly once you account for three bookkeeping facts: `interlace` and `tinterlace` are both defined in `vf_tinterlace.c`; `signature_lookup.c` and `vf_fsppdsp.c` are helpers of `vf_signature.c` and `vf_fspp.c` (`LICENSE.md` names the first, omits the second — a harmless documentation gap I am recording because it shows the file list is hand-maintained); and `boxblur_opencl` shares `vf_boxblur.c`.

**Confirmations and refutations against the list in the brief:**

| named in the brief | verdict at n8.1 | evidence |
|---|---|---|
| `geq` | **REFUTED — LGPL-2.1-or-later** | no `geq` line anywhere in `configure`; `vf_geq.c` header says Lesser GPL 2.1+ [4]; relicensed by commit `d5e7f0109`, 2019-12-16, first shipped in n4.3 (2020-06-15) [5] |
| `boxblur`, `smartblur`, `delogo`, `hqdn3d`, `owdenoise`, `perspective`, `pp7`, `spp`, `uspp`, `fspp`, `sab`, `stereo3d`, `super2xsai`, `tinterlace`, `vaguedenoiser`, `nnedi`, `mcdeint`, `repeatfields`, `kerndeint`, `cover_rect`, `find_rect` | **CONFIRMED GPL-only** | `configure` + header + `LICENSE.md` [1,2] |
| `pp` | **GPL-only, but GONE.** It wrapped `libpostproc`, which no longer exists: the `libpostproc/` directory is present at tag n7.1 and returns 404 at n8.0 and n8.1. `pp_filter_deps="gpl postproc"` at n7.1 [6]; absent from n8.1's configure, Makefile and `allfilters.c` [22]. The native ports `fspp`/`uspp`/`pp7`/`spp` survive and are still GPL | tag-diffed |
| `vidstab*` | GPL **by external library** (`libvidstab` ∈ `EXTERNAL_LIBRARY_GPL_LIST`), not by in-tree source | [1,2] |
| `frei0r` | same — `frei0r` ∈ `EXTERNAL_LIBRARY_GPL_LIST` | [1,2] |
| `ocr` | **not GPL.** `ocr_filter_deps="libtesseract"`; Tesseract is Apache-2.0. **Unverified** that Apache-2.0 is FFmpeg's own reading here — `configure` places no licence gate on it | [2] |

**The one genuine inconsistency, and `looks` must hardcode around it.** `LICENSE.md` lists `vf_lensfun.c` as *"(GPL version 3 or later)"* [1], and the file header agrees — it is the AGPL-style "either version 3 of the License" GPLv3 text [16]. But `configure` gates the filter on `lensfun_filter_deps="liblensfun version3"` — **`gpl` is not in that list** [2]. So a build configured `--enable-version3 --enable-liblensfun` *without* `--enable-gpl` compiles GPL-3.0-only code into a binary whose `ffmpeg -L` says **LGPL version 3 or later**. Trust the file header; a `looks` licence table that trusts `configure` alone gets this one wrong, and it is the only filter where the two disagree.

**A second, milder inconsistency, recorded because it is the same class of error.** `LICENSE.md` says the VMAF library is Apache-2.0 and therefore needs `--enable-version3` [1]; `configure` places `libvmaf` in the plain `EXTERNAL_LIBRARY_LIST` with no version gate [2]; and Netflix's own `LICENSE` file says **BSD-2-Clause-Patent**, explicitly designed to be GPLv2-compatible [15]. Here the document is stale and `configure` is right. `LICENSE.md` also still calls OpenSSL GPL-incompatible, which `configure` line 7493 contradicts for OpenSSL ≥ 3.0.0 [2]. **The lesson for `looks` is not "which document wins" — it is that no document wins. The binary is the fact.**

---

## 3. Verdict table for the filters `looks` wants

`min tier` = the weakest build on which the filter is legally available. `brew 8.1` / `imageio 7.1` = observed presence in each binary on this machine, parsed from `ffmpeg -filters`.

| filter | min tier | source licence (file header, n8.1) | brew 8.1 | imageio 7.1 |
|---|---|---|---|---|
| `lut3d` | LGPL-2.1+ | LGPL-2.1+ (`vf_lut3d.c`) | yes | yes |
| `lut1d` | LGPL-2.1+ | LGPL-2.1+ (`vf_lut3d.c`) | yes | yes |
| `lutrgb` | LGPL-2.1+ | LGPL-2.1+ (`vf_lut.c`) [18] | yes | yes |
| `lutyuv` | LGPL-2.1+ | LGPL-2.1+ (`vf_lut.c`) | yes | yes |
| `curves` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `colorchannelmixer` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `colorbalance` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `colorlevels` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `colorspace` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `zscale` | LGPL-2.1+ | LGPL-2.1+; needs **libzimg** (WTFPL / permissive — **unverified**) | **no** | yes |
| `eq` | **GPL-2+** | GPL-2+ (`vf_eq.c`) | yes | yes |
| `hue` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `pseudocolor` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `elbg` | LGPL-2.1+ | LGPL-2.1+ (`avcodec` dep only) | yes | yes |
| `deband` | LGPL-2.1+ | **MIT** (`vf_deband.c`) [20] | yes | yes |
| `gblur` | LGPL-2.1+ | **BSD-2-Clause** (`vf_gblur.c`) [19] | yes | yes |
| `boxblur` | **GPL-2+** | GPL-2+ | yes | yes |
| `edgedetect` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `convolution` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `unsharp` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `tmix` | LGPL-2.1+ | LGPL-2.1+ (`vf_mix.c`) | yes | yes |
| `scale` | LGPL-2.1+ | LGPL-2.1+ (`swscale` dep) | yes | yes |
| `crop` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `pad` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `xfade` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `format` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `colormatrix` | **GPL-2+** | GPL-2+ | yes | yes |
| `tonemap` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `libplacebo` | LGPL-2.1+ | LGPL-2.1+ wrapper; needs **libplacebo** (LGPL-2.1+) + Vulkan — **unverified** | **no** | **no** |
| `sharpen_npp` | LGPL-2.1+ **wrapper**, but needs `libnpp` ∈ `HWACCEL_LIBRARY_NONFREE_LIST` → **`--enable-nonfree` → always refuse** | LGPL-2.1+ | **no** | **no** |
| `dnn_processing` | LGPL-2.1+ | LGPL-2.1+ | **no** | **no** |
| `sr` | LGPL-2.1+ | LGPL-2.1+ | **no** | **no** |
| `vibrance` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `selectivecolor` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `monochrome` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `exposure` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `colortemperature` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `huesaturation` | LGPL-2.1+ | LGPL-2.1+ | yes | yes |
| `geq` | LGPL-2.1+ | **LGPL-2.1+** [4] | yes | yes |
| `bilateral` | LGPL-2.1+ | MIT | yes | yes |
| `hqx` | LGPL-2.1+ | **ISC** | yes | yes |
| `morpho` / `avgblur` / `bm3d` | LGPL-2.1+ | MIT | yes | yes |
| `lensfun` | **GPL-3+** (header; `configure` disagrees — see §2) | GPL-3+ [16] | **no** | **no** |
| `frei0r`, `vidstabdetect`, `vidstabtransform` | **GPL-2+** (external lib) | wrapper LGPL, lib GPL | **no** | `vidstab*` yes |

**Three of forty-odd wanted filters are GPL-only: `eq`, `boxblur`, `colormatrix`.** Each has an LGPL substitute that is already present: `eq` → `colorlevels` + `huesaturation` + `exposure` (or `curves`); `boxblur` → `gblur` (BSD) or `avgblur` (MIT); `colormatrix` → `colorspace` or `colorchannelmixer`. **There is no colour-grading capability behind the GPL wall.** That is the single most useful fact in this note for the effect registry: `looks` can ship a complete grading and stylization vocabulary at the LGPL tier without compromise.

**Directly answering the brief's concrete question:** the Que Calor posterise step — `lut3d` for the gradient map, then `lutrgb` with expressions for the posterise — is **entirely LGPL-2.1-or-later**, as is the `geq` alternative that was considered. Both were run against the local binary:

```
$ ffmpeg -f lavfi -i "testsrc2=size=320x180:rate=5" -frames:v 3 \
    -vf "lut3d=file=identity.cube,lutrgb=r='floor(val/32)*32':g='floor(val/32)*32':b='floor(val/32)*32'" -f null -
OK: lut3d,lutrgb chain ran (exit 0)

$ ffmpeg -f lavfi -i "testsrc2=size=160x90:rate=5" -frames:v 2 \
    -vf "format=gbrp,geq=r='floor(r(X,Y)/32)*32':g='floor(g(X,Y)/32)*32':b='floor(b(X,Y)/32)*32'" -f null -
OK: geq chain ran (exit 0)
```

So the refusal the brief hoped for — "an LGPL-tier Look cannot use `geq`" — **does not happen, and should not**. The refusal engine's first real customer is not `geq`; it is `eq` and `boxblur`, and (much more consequentially) `libx264`.

---

## 4. Encoders — where the GPL wall actually is

FFmpeg has **no native H.264 or HEVC encoder**. The only software ones are `libx264` and `libx265`, both GPL-2.0-or-later [7,8], both members of `EXTERNAL_LIBRARY_GPL_LIST` [1,2], so `--enable-libx264` on an LGPL build is a hard configure error. Confirmed empirically: the local binary dynamically links `libx264.165.dylib` (x264 r3222) and `libx265.216.dylib` (x265 4.2) from `/opt/homebrew/opt/`.

| encoder | licence of the code that matters | tier | present locally | encodes (10-frame smoke) |
|---|---|---|---|---|
| `libx264`, `libx264rgb` | x264 **GPL-2.0-or-later** [7] (commercial licence sold separately by x264 LLC — **unverified terms**) | GPL-2+ | yes | OK, 19614 B |
| `libx265` | x265 **GPL-2.0-or-later** [8] (commercial licence sold separately by MulticoreWare — **unverified terms**) | GPL-2+ | yes | not smoked |
| `libxvid`, `libxavs`, `libxavs2` | GPL, via `EXTERNAL_LIBRARY_GPL_LIST` [1] | GPL-2+ | no | — |
| `libsvtav1` (AV1) | SVT-AV1 **BSD-3-Clause-Clear** + **AOM Patent License 1.0** in a separate `PATENTS.md` [11,12] | LGPL-safe | yes (SVT-AV1 4.1.0) | OK, 15116 B |
| `libvpx-vp9`, `libvpx` (VP9/VP8) | libvpx **BSD-3-Clause** + WebM *Additional IP Rights Grant* [9,10] | LGPL-safe | yes (libvpx 1.16.0) | OK, 16491 B |
| `libaom-av1` | libaom **BSD-2-Clause** + AOM Patent License 1.0 [13,14] | LGPL-safe | no | — |
| `h264_videotoolbox`, `hevc_videotoolbox`, `prores_videotoolbox` | LGPL wrapper over Apple's system framework; no `gpl`/`nonfree` dep [2] | LGPL-safe | yes | OK, 32314 / 21028 B |
| `h264_nvenc`, `hevc_nvenc`, `av1_nvenc` | LGPL wrapper; `ffnvcodec` is in the plain `EXTERNAL_LIBRARY_LIST`, **not** the nonfree list [2] | LGPL-safe | no (macOS) | — |
| `prores`, `prores_aw`, `prores_ks` | in-tree, LGPL-2.1+ | LGPL-safe | yes | OK, 310210 B |
| `ffv1`, `huffyuv`, `ffvhuff`, `utvideo`, `magicyuv`, `qtrle`, `v210` | in-tree, LGPL-2.1+ | LGPL-safe | yes | `ffv1` OK, 64575 B |
| `dnxhd`, `cfhd`, `speedhq`, `vc2`, `snow` | in-tree, LGPL-2.1+ | LGPL-safe | yes | — |
| `mpeg4`, `mpeg2video`, `mpeg1video`, `h263p`, `msmpeg4`, `wmv2`, `flv` | in-tree, LGPL-2.1+ | LGPL-safe | yes | `mpeg4` OK, 68428 B |
| `mjpeg`, `ljpeg`, `png`, `apng`, `gif`, `webp`\*, `jpeg2000`, `qoi`, `exr`, `tiff` | in-tree, LGPL-2.1+ | LGPL-safe | yes | — |
| `libfdk_aac` (audio) | ∈ `EXTERNAL_LIBRARY_NONFREE_LIST` [1,2] | **always refuse** | no | — |

\* the *native* `webp` encoder; `libwebp` is a separate permissive external library.

**The product constraint, stated loudly.** A `looks` render at the LGPL tier **cannot output H.264 by software encoding, on any platform, ever.** Its portable options are AV1 (SVT-AV1, verified working locally at 15 KB for 10 frames of 320×180) and VP9 (libvpx). On macOS it additionally gets H.264 and HEVC via VideoToolbox, verified working. On an NVIDIA box it gets NVENC. On no platform does it get libx264. That is a **delivery-format decision, not a code-licence footnote** — a caller who says "commercial-safe only" and then asks for an MP4/H.264 for a social platform is asking for two incompatible things, and `looks` should say so at *plan* time rather than at ffmpeg-exit time.

**A separate perimeter I am explicitly not adjudicating.** Copyright licence and *patent* licence are different questions. AVC/H.264 (MPEG-LA pool) and HEVC (Access Advance and others) carry patent obligations that attach to the *format*, not to FFmpeg's source, and are unaffected by choosing VideoToolbox over libx264. AV1 and VP9 exist precisely to avoid that, and each ships an explicit royalty-free patent grant [10,12,14] — noting that the Clear BSD used by SVT-AV1 says in terms *"NO EXPRESS OR IMPLIED LICENSES TO ANY PARTY'S PATENT RIGHTS ARE GRANTED BY THIS LICENSE"* [11], which is exactly why the AOM grant is a second, separate file. **Whether the patent position is acceptable for a given product is a legal question and is marked unverified here.** What `looks` can honestly do is *report* the pair (copyright licence, patent-grant document) per encoder and refuse on `unknown`, matching the falaw ledger rule the federation already adopted.

---

## 5. The probe — real commands, real output

### 5.1 `ffmpeg -version`

```
ffmpeg version 8.1 Copyright (c) 2000-2026 the FFmpeg developers
built with Apple clang version 17.0.0 (clang-1700.6.4.2)
configuration: --prefix=/opt/homebrew/Cellar/ffmpeg/8.1_1 --enable-shared --enable-pthreads --enable-version3 --cc=clang --host-cflags= --host-ldflags= --enable-ffplay --enable-gpl --enable-libsvtav1 --enable-libopus --enable-libx264 --enable-libmp3lame --enable-libdav1d --enable-libvmaf --enable-libvpx --enable-libx265 --enable-openssl --enable-videotoolbox --enable-audiotoolbox --enable-neon
libavutil      60. 26.100 / 60. 26.100
libavcodec     62. 28.100 / 62. 28.100
libavformat    62. 12.100 / 62. 12.100
libavdevice    62.  3.100 / 62.  3.100
libavfilter    11. 14.100 / 11. 14.100
libswscale      9.  5.100 /  9.  5.100
libswresample   6.  3.100 /  6.  3.100
```

### 5.2 `ffmpeg -buildconf`

```
  configuration:
    --prefix=/opt/homebrew/Cellar/ffmpeg/8.1_1
    --enable-shared
    --enable-pthreads
    --enable-version3
    --cc=clang
    --host-cflags=
    --host-ldflags=
    --enable-ffplay
    --enable-gpl
    --enable-libsvtav1
    --enable-libopus
    --enable-libx264
    --enable-libmp3lame
    --enable-libdav1d
    --enable-libvmaf
    --enable-libvpx
    --enable-libx265
    --enable-openssl
    --enable-videotoolbox
    --enable-audiotoolbox
    --enable-neon
```

### 5.3 `ffmpeg -L`

```
ffmpeg is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 3 of the License, or
(at your option) any later version.

ffmpeg is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with ffmpeg.  If not, see <http://www.gnu.org/licenses/>.
```

### 5.4 The parsing rule, and why it is `-L` and not `-buildconf`

`-L` is generated by `show_license()` in `fftools/opt_common.c` [3] — a **compile-time `#if CONFIG_NONFREE / CONFIG_GPLV3 / CONFIG_GPL / CONFIG_LGPLV3 / else` cascade**. It is baked into the executable and there is no build option that removes it. `-buildconf` and the `configuration:` line of `-version` both stringify the `FFMPEG_CONFIGURATION` macro [3], which a packager can and sometimes does patch to an empty string — in which case `-buildconf` prints a bare `configuration:` header with nothing under it. **A licence decision that keys on the configuration string therefore has a silent-failure mode; one that keys on `-L` does not.**

Five rules, each of which the code below implements:

1. **`-L` is the only authority for the binary's licence.** Match `nonfree` first, then `Lesser General Public License` *before* `General Public License` (the former contains the latter as a substring), then the version number.
2. **No match is `UNKNOWN`, and `UNKNOWN` refuses.** Never fall back to "probably LGPL". A build whose banner was patched out is a build we know nothing about.
3. **`-buildconf` is reporting only.** Record it, print it in the refusal message when it exists, and never let an *allow* decision depend on it. `configuration is None` is a normal state, not an error.
4. **Availability comes from `-filters` and nothing else.** `ffmpeg -h filter=nosuchfilter` prints `Unknown filter 'nosuchfilter'.` **and exits 0** — measured on 8.1. Exit codes are unusable here.
5. **Parse `-filters` by the `A->B` arity column, never by the flags column.** The flags column is **3 characters in 7.1** (`TSC` = Timeline / Slice threading / Command support) and **2 in 8.1** (`TS`; the Command legend row was dropped and a `------` separator added). A parser that models either width silently under-reports on the other binary — and under-reported *availability* in a refusal engine is a **false refusal**, the failure direction that looks like safety. This was a real bug in the first draft of the code below: it reported 288 filters for the 7.1 binary instead of 484, and would have refused `lut3d` on a binary that has it.

### 5.5 The probe, stdlib only — this code was run, its output follows

```python
"""Probe an ffmpeg binary for the two facts a licence tier needs.

Stdlib only. Two independent questions, answered from two independent signals:

1. *What licence does this binary carry?*  ``ffmpeg -L`` -- a compile-time
   ``#if`` cascade in ``fftools/opt_common.c``, so it cannot be stripped the way
   the ``configuration:`` line can.
2. *Is this filter present in this binary?*  ``ffmpeg -filters`` -- never
   ``-h filter=NAME``, which exits 0 for an unknown filter (measured, 8.1).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from enum import IntEnum
from typing import FrozenSet, Optional, Sequence, Tuple

DFLT_FFMPEG = "ffmpeg"
DFLT_TIMEOUT_S = 20


class Tier(IntEnum):
    """Copyleft strength, ascending. Higher = more obligations on the caller."""

    PERMISSIVE = 0
    LGPL_2_1 = 1
    LGPL_3 = 2
    GPL_2 = 3
    GPL_3 = 4
    NONFREE = 5
    UNKNOWN = 6  # deliberately the ceiling: unknown is never allowed


class LicenceRefusal(RuntimeError):
    """Raised instead of running something the caller's tier does not permit."""


_LICENCE_PATTERNS: Sequence[Tuple[re.Pattern, Tier, str]] = (
    (
        re.compile(r"nonfree parts compiled in", re.I),
        Tier.NONFREE,
        "nonfree-and-unredistributable",
    ),
    (
        re.compile(r"Lesser General Public\s+License.{0,80}?version 3", re.I | re.S),
        Tier.LGPL_3,
        "LGPL-3.0-or-later",
    ),
    (
        re.compile(r"Lesser General Public\s+License.{0,80}?version 2\.1", re.I | re.S),
        Tier.LGPL_2_1,
        "LGPL-2.1-or-later",
    ),
    (
        re.compile(r"General Public License.{0,80}?version 3", re.I | re.S),
        Tier.GPL_3,
        "GPL-3.0-or-later",
    ),
    (
        re.compile(r"General Public License.{0,80}?version 2", re.I | re.S),
        Tier.GPL_2,
        "GPL-2.0-or-later",
    ),
)


@dataclass(frozen=True)
class FfmpegProbe:
    """What a single ffmpeg binary actually is. All fields are observed, never assumed."""

    binary: str
    version: Optional[str]
    tier: Tier
    spdx: str
    configuration: Optional[Tuple[str, ...]]  # None = absent or stripped
    filters: FrozenSet[str]

    @property
    def configuration_available(self) -> bool:
        return bool(self.configuration)


def _run(binary: str, args: Sequence[str], *, timeout_s: int = DFLT_TIMEOUT_S) -> str:
    try:
        p = subprocess.run(
            [binary, "-hide_banner", *args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise LicenceRefusal(f"cannot probe {binary!r}: {e}") from e
    return p.stdout + p.stderr


def _parse_licence(text: str) -> Tuple[Tier, str]:
    """Map ``ffmpeg -L`` output to a tier. Order matters: Lesser before plain."""
    for pattern, tier, spdx in _LICENCE_PATTERNS:
        if pattern.search(text):
            return tier, spdx
    return Tier.UNKNOWN, "unknown"


def _parse_buildconf(text: str) -> Optional[Tuple[str, ...]]:
    """Configure tokens from ``-buildconf``. ``None`` when absent or stripped."""
    toks = tuple(
        line.strip() for line in text.splitlines() if line.strip().startswith("--")
    )
    return toks or None


_ARROW = re.compile(r"^[AVN|]+->[AVN|]+$")


def _parse_filters(text: str) -> FrozenSet[str]:
    """Filter names from ``ffmpeg -filters``.

    Keys on the ``A->B`` arity column and takes the token before it. Deliberately
    models NOTHING about the flags column: it is 3 chars in 7.1 (``TSC`` --
    Timeline/Slice/Command) and 2 in 8.1 (``TS``; the Command row was dropped and
    a ``------`` separator added). A parser that models either width silently
    under-reports on the other binary, and under-reported availability in a
    refusal engine is a FALSE REFUSAL -- the failure direction that looks safe.
    """
    names = set()
    for line in text.splitlines():
        toks = line.split()
        for i, t in enumerate(toks):
            if _ARROW.match(t) and i >= 2:
                names.add(toks[i - 1])
                break
    return frozenset(names)


def probe_ffmpeg(
    binary: str = DFLT_FFMPEG, *, timeout_s: int = DFLT_TIMEOUT_S
) -> FfmpegProbe:
    """Probe ``binary``. Raises :class:`LicenceRefusal` if it cannot be run at all."""
    lic_text = _run(binary, ["-L"], timeout_s=timeout_s)
    tier, spdx = _parse_licence(lic_text)
    ver_text = _run(binary, ["-version"], timeout_s=timeout_s)
    m = re.search(r"^ffmpeg version (\S+)", ver_text, re.M)
    return FfmpegProbe(
        binary=binary,
        version=m.group(1) if m else None,
        tier=tier,
        spdx=spdx,
        configuration=_parse_buildconf(
            _run(binary, ["-buildconf"], timeout_s=timeout_s)
        ),
        filters=_parse_filters(_run(binary, ["-filters"], timeout_s=timeout_s)),
    )


# --- The static half: which filters carry a stronger tier than the binary ------
# Source: FFmpeg LICENSE.md at tag n8.1, cross-checked against every
# ``<name>_filter_deps=".*gpl.*"`` line in ``configure`` at the same tag.

TABLE_ANCHOR = "FFmpeg n8.1 (+ the one 7.x-only entry noted below)"

GPL_ONLY_VIDEO_FILTERS: FrozenSet[str] = frozenset(
    """
blackframe boxblur boxblur_opencl colormatrix cover_rect cropdetect delogo eq
find_rect fspp histeq hqdn3d interlace kerndeint mcdeint mpdecimate mptestsrc
nnedi owdenoise perspective phase pp7 pullup repeatfields sab signature
smartblur spp stereo3d super2xsai tinterlace uspp vaguedenoiser
pp
""".split()
)
# `pp` is the single 7.x-only entry: it wrapped libpostproc, which was removed
# in FFmpeg 8.0. Keeping it means an older binary on PATH is still classified
# correctly. It is also the reason this table carries an anchor at all -- the
# GPL set is version-dependent and a stale table under-refuses.

# lensfun is the one disagreement between LICENSE.md (GPL v3+) and configure
# (gated on ``version3`` only, NOT on ``gpl``). Trust the file header.
GPL3_ONLY_VIDEO_FILTERS: FrozenSet[str] = frozenset({"lensfun"})

# Filters whose availability depends on a GPL-licensed EXTERNAL library.
GPL_EXTERNAL_LIB_FILTERS = {
    "frei0r": "frei0r (GPL-2.0-or-later)",
    "frei0r_src": "frei0r (GPL-2.0-or-later)",
    "vidstabdetect": "libvidstab (GPL-2.0-or-later)",
    "vidstabtransform": "libvidstab (GPL-2.0-or-later)",
}


def filter_tier(name: str) -> Tier:
    """Minimum tier a build must carry for ``name`` to be legally available."""
    if name in GPL3_ONLY_VIDEO_FILTERS:
        return Tier.GPL_3
    if name in GPL_ONLY_VIDEO_FILTERS or name in GPL_EXTERNAL_LIB_FILTERS:
        return Tier.GPL_2
    return Tier.LGPL_2_1  # FFmpeg's floor; nothing in libavfilter is below it


def require(
    filters: Sequence[str],
    *,
    probe: FfmpegProbe,
    max_effect_tier: Tier = Tier.LGPL_2_1,
    max_binary_tier: Tier = Tier.GPL_3,
) -> None:
    """Refuse -- never warn. TWO independent ceilings, because there are two questions.

    ``max_effect_tier`` answers *would this Look run on a clean-room LGPL build?*
    It is a property of the Look and is decidable with no binary present.

    ``max_binary_tier`` answers *what does the binary I am about to invoke carry?*
    Invoking is not linking, so the default is permissive; a caller who intends
    to REDISTRIBUTE the binary lowers it, and then must say so deliberately.

    Collapsing the two into one ordinal makes a purely-LGPL Look unrunnable on
    every Homebrew ffmpeg on earth, which is over-refusal, not safety.
    """
    if probe.tier is Tier.UNKNOWN:
        raise LicenceRefusal(
            f"{probe.binary}: `ffmpeg -L` did not match any known licence text. "
            "Refusing: unknown is never treated as permissive."
        )
    if probe.tier > max_binary_tier:
        raise LicenceRefusal(
            f"{probe.binary} is {probe.spdx} (tier {probe.tier.name}); "
            f"max_binary_tier is {max_binary_tier.name}."
        )
    for f in filters:
        need = filter_tier(f)
        if need > max_effect_tier:
            raise LicenceRefusal(
                f"filter {f!r} needs a {need.name} build "
                f"(FFmpeg LICENSE.md, tag n8.1); max_effect_tier is {max_effect_tier.name}."
            )
        if need > probe.tier:
            raise LicenceRefusal(
                f"filter {f!r} needs a {need.name} build; "
                f"{probe.binary} is {probe.spdx}. It will not be present."
            )
        if f not in probe.filters:
            raise LicenceRefusal(
                f"filter {f!r} is absent from {probe.binary} ({probe.version}). "
                "Absence is a refusal, not a silent fallback."
            )
```

### 5.6 Its actual output

Five binaries: the two real ones on this machine, and three shell stubs that simulate an LGPL build with a stripped configuration line, a build whose licence banner was patched out, and a nonfree build.

```
table anchor: FFmpeg n8.1 (+ the one 7.x-only entry noted below)

ffmpeg                     v=8.1        GPL-3.0-or-later                  filters=481  buildconf=True
ffmpeg-macos-aarch64-v7.1  v=7.1        GPL-2.0-or-later                  filters=484  buildconf=True
ffmpeg-lgpl                v=8.1-lgpl   LGPL-2.1-or-later                 filters=2    buildconf=False
ffmpeg-mute                v=8.1-vendor unknown                           filters=1    buildconf=False
ffmpeg-nonfree             v=8.1-nonfree nonfree-and-unredistributable     filters=1    buildconf=False

  [LGPL_2_1] que-calor posterise  ['lut3d', 'lutrgb']    -> ALLOWED
  [LGPL_2_1] same, via geq        ['format', 'geq']      -> ALLOWED
  [LGPL_2_1] GPL grade            ['hqdn3d', 'eq']       -> REFUSED: filter 'hqdn3d' needs a GPL_2 build (FFmpeg LICENSE.md, tag n8.1); max_effect_tier is LGPL_2_1.
  [GPL_2   ] GPL grade            ['hqdn3d', 'eq']       -> ALLOWED
  [LGPL_2_1] zscale (not built)   ['zscale']             -> REFUSED: filter 'zscale' is absent from ffmpeg (8.1). Absence is a refusal, not a silent fallback.
  [GPL_2   ] lensfun              ['lensfun']            -> REFUSED: filter 'lensfun' needs a GPL_3 build (FFmpeg LICENSE.md, tag n8.1); max_effect_tier is GPL_2.

  redistribution ceiling -> REFUSED: ffmpeg is GPL-3.0-or-later (tier GPL_3); max_binary_tier is LGPL_2_1.
```

The `ffmpeg-lgpl` row is the one that justifies rule 3: its configuration line is empty (`buildconf=False`) and it is **still correctly classified LGPL-2.1-or-later**, and `lut3d` is still allowed on it. The `ffmpeg-mute` row is rule 2 doing its job.

### 5.7 Two binaries, one machine — the observed spread

Both of these are on this laptop right now, and which one `looks` sees depends entirely on how it is launched.

| | Homebrew | `imageio-ffmpeg` 0.6.0 bundle |
|---|---|---|
| version | 8.1 | 7.1 |
| `ffmpeg -L` | **GPL version 3 or later** | **GPL version 2 or later** |
| filters | 481 | 484 |
| GPL-gated filters present | 32 of 39 table entries (6.7% of the build) | includes `pp`, `vidstabtransform` |
| has `zscale` | **no** | yes (`--enable-libzimg`) |
| has `libplacebo` | no | no |
| notable configure flags | `--enable-gpl --enable-version3 --enable-libx264 --enable-libx265 --enable-libsvtav1 --enable-libvpx --enable-videotoolbox` | `--enable-gpl --enable-libx264 --enable-libx265 --enable-libvidstab --enable-postproc --enable-libzimg --enable-libaom --enable-libsvtav1` |

**This directly verifies the kickoff's claim about `imageio-ffmpeg`, with a version anchor.** `imageio-ffmpeg` 0.6.0 ships `ffmpeg-macos-aarch64-v7.1`, built `--enable-gpl --enable-libx264 --enable-libx265 --enable-libvidstab`, whose `-L` reports GPL version 2 or later. `pip install`-ing anything that pulls it in — `burns` → `moviepy` → `imageio-ffmpeg` — **places a GPL-2.0-or-later executable inside site-packages**. Running it is not linking and does not infect the caller's Python; *shipping an environment containing it* is redistribution and carries the GPL's source-offer obligation. **Unverified:** I could not confirm the `burns → moviepy → imageio-ffmpeg` chain from installed metadata in this session (the interpreter I probed from did not have those distributions installed); the binary's presence under a pyenv site-packages is direct evidence that *something* in that environment pulled it in.

The practical consequence for `looks` is a design requirement, not a warning: **the binary is a parameter, not a constant.** `FfmpegProbe` must be per-binary and cached per resolved path, and a `Look` must never be validated against "ffmpeg" as though that named one thing.

---

## 6. The nonfree cases

`--enable-nonfree` is set by exactly two lists in `configure` at n8.1 [2]:

```
EXTERNAL_LIBRARY_NONFREE_LIST="decklink libfdk_aac libmpeghdec"
HWACCEL_LIBRARY_NONFREE_LIST="cuda_nvcc cuda_sdk libnpp"
```

`libnpp` is the one that touches video *filters* — it is what `scale_npp`, `sharpen_npp` and `transpose_npp` need. `cuda_nvcc`/`cuda_sdk` gate the CUDA-compiled filters. `libfdk_aac` and `libmpeghdec` are audio; `decklink` is capture hardware.

**Detection**: `ffmpeg -L` prints *"This version of ffmpeg has nonfree parts compiled in. Therefore it is not legally redistributable."* — the very first branch of the `#if` cascade [3], so it wins over every other flag combination and cannot be missed. `-buildconf` would also show `--enable-nonfree`, but only when the configuration string survived.

**Why it is always a refusal, with no ceiling that permits it**: the binary is *by FFmpeg's own statement* not redistributable, which means a `Look` that runs on it produces output whose toolchain cannot be reproduced by anyone the caller hands the project to. That is the opposite of what a pure-data, persistable, replayable `Look` is for. The incremental capability is also nil for this package — `libfdk_aac` is an audio encoder and `sharpen_npp` has LGPL equivalents in `unsharp` and `convolution`. In the code above, `Tier.NONFREE` sits above the default `max_binary_tier=GPL_3`, so it refuses without the caller doing anything; **the recommendation is to go further and make it unconditional**, i.e. reject `Tier.NONFREE` before the ceiling comparison, so that no value of `max_binary_tier` can admit it.

---

## 7. What I could not verify

Marked explicitly, because an unverified licence claim inside a refusal engine is worse than no claim.

- **That a GPL-only filter is genuinely absent from an LGPL build.** I could not build an LGPL-only ffmpeg in this session. The claim rests on two documentary signals that agree — `configure`'s `<name>_filter_deps="gpl"` and `LICENSE.md` [1,2] — plus the fact that `die_license_disabled` is the same mechanism that hard-errors on `--enable-libx264` without `--enable-gpl`. **Recommendation: `looks` should carry one CI job that builds a minimal LGPL ffmpeg and asserts the absence of `eq`, `boxblur` and `colormatrix`.** Until that exists, the table is documented, not measured.
- **The licence of `libzimg`** (needed by `zscale`), **`libplacebo`**, **`librav1e`**, **`libopenh264`**, **`libtheora`**, **`libwebp`**, **`libjxl`**, **`libkvazaar`**, **`libvvenc`** and **`libtesseract`**. None are in FFmpeg's GPL/version3/nonfree lists, which is FFmpeg's assertion that they are LGPL-compatible; I did not fetch any of their LICENSE files. `zscale` and `libplacebo` are the two that matter for `looks` and should be checked before either is registered as an effect.
- **The commercial-licence terms sold by x264 LLC and MulticoreWare.** Their existence is well known; I read neither offer.
- **Patent positions of any codec.** Out of scope for a source-licence probe, and a legal question. See §4.
- **Whether Apple's VideoToolbox device licence covers AVC/HEVC patent obligations for a commercial product.** This is the crux of the "LGPL-safe H.264 on macOS" story and I am not qualified to assert it.
- **The `burns → moviepy → imageio-ffmpeg` dependency edge**, per §5.7 — the *binary* is verified present and GPL-2; the *chain* that installed it is not.
- **Whether any distributor actually strips `FFMPEG_CONFIGURATION`.** I demonstrated the *handling* with a stub, not an instance in the wild. The handling is correct either way and costs nothing.

---

## Findings that should change the design

1. **Two ceilings, not one.** `Look.max_effect_tier` (property of the Look, decidable offline, the "commercial-safe only" knob) and `max_binary_tier` (property of the installation, defaults permissive because invoking is not linking, lowered deliberately by anyone redistributing the binary). A single ordinal refuses every LGPL Look on every Homebrew ffmpeg — over-refusal, not safety. This was found by running the first draft, not by reasoning about it.
2. **The effect registry can be complete at the LGPL tier.** No colour operation is behind the GPL wall. Register `gblur`/`avgblur` instead of `boxblur`, `colorlevels`+`huesaturation`+`exposure` instead of `eq`, `colorspace`/`colorchannelmixer` instead of `colormatrix`, and the whole grading vocabulary is LGPL-2.1+ or better.
3. **The real refusal is at render, not at filter.** `looks` is not supposed to own execution — but it *is* supposed to own the tier, and the tier's sharpest consequence is that an LGPL deliverable cannot be software-H.264. That belongs in the `Look`'s declared output constraints, surfaced at plan time.
4. **The static GPL table must be version-anchored and regenerable.** The set changed between 7.1 and 8.1 (`pp` removed with libpostproc), `geq` changed in 4.3, and `lensfun` is a documented disagreement between two files in the same tree. Ship the table with its anchor, and ship a test that re-derives it from a pinned `LICENSE.md` so drift is a red build rather than a wrong refusal.
5. **Never model the `-filters` flags column.** It is 3 chars in 7.x and 2 in 8.x. Key on the `A->B` arity token. This is a one-line rule that prevented a false-refusal bug I actually hit.
6. **`-h filter=NAME` exits 0 on an unknown filter.** Availability probing must parse `-filters`.
7. **Record the probe in the plan.** A `Look` that was planned against a GPL-3 8.1 and replayed against a GPL-2 7.1 with different filters is a different render. The `FfmpegProbe` (binary path, version, spdx, filter-set digest) is part of the cache key, exactly as the ComfyUI decisions note requires the "environment fingerprint" and "backend interface-contract digest" to be [federation standing rule 5].

---

## REFERENCES

1. [FFmpeg, `LICENSE.md`, tag n8.1](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1/LICENSE.md) — the GPL file list, the external-library licence classes, the `--enable-version3` rule. Fetched 2026-09-02.
2. [FFmpeg, `configure`, tag n8.1](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1/configure) — `*_filter_deps`, `EXTERNAL_LIBRARY_{GPL,VERSION3,GPLV3,NONFREE}_LIST`, `HWACCEL_LIBRARY_NONFREE_LIST`, `die_license_disabled`, the licence cascade at lines 4767-4787, the OpenSSL rule at line 7493. Fetched 2026-09-02.
3. [FFmpeg, `fftools/opt_common.c`, tag n8.1](https://github.com/FFmpeg/FFmpeg/blob/n8.1/fftools/opt_common.c) — `show_license()` (the compile-time `#if` cascade behind `ffmpeg -L`), `print_buildconf()`, `print_program_info()`.
4. [FFmpeg, `libavfilter/vf_geq.c`, tag n8.1](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1/libavfilter/vf_geq.c) — LGPL-2.1-or-later header.
5. [FFmpeg commit `d5e7f0109`, "avfilter/vf_geq: Relicense to LGPL", 2019-12-16](https://github.com/FFmpeg/FFmpeg/commit/d5e7f0109) — touches `LICENSE.md`, `configure` and `vf_geq.c`; first released in [n4.3, 2020-06-15](https://github.com/FFmpeg/FFmpeg/releases/tag/n4.3).
6. [FFmpeg, `configure`, tag n7.1](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n7.1/configure) — `pp_filter_deps="gpl postproc"`; the 34-name GPL set that becomes 33 at n8.1.
7. [x264, `COPYING`](https://code.videolan.org/videolan/x264/-/raw/master/COPYING) — GNU General Public License, Version 2.
8. [x265, `COPYING`](https://bitbucket.org/multicoreware/x265_git/raw/master/COPYING) — GNU General Public License, Version 2.
9. [libvpx, `LICENSE`](https://raw.githubusercontent.com/webmproject/libvpx/main/LICENSE) — BSD-3-Clause.
10. [libvpx, `PATENTS`](https://raw.githubusercontent.com/webmproject/libvpx/main/PATENTS) — "Additional IP Rights Grant (Patents)", Google.
11. [SVT-AV1, `LICENSE.md`](https://gitlab.com/AOMediaCodec/SVT-AV1/-/raw/master/LICENSE.md) — BSD 3-Clause Clear License; note the explicit "NO EXPRESS OR IMPLIED LICENSES TO ANY PARTY'S PATENT RIGHTS ARE GRANTED BY THIS LICENSE".
12. [SVT-AV1, `PATENTS.md`](https://gitlab.com/AOMediaCodec/SVT-AV1/-/raw/master/PATENTS.md) — Alliance for Open Media Patent License 1.0.
13. [libaom, `LICENSE`](https://aomedia.googlesource.com/aom/+/refs/heads/main/LICENSE) — BSD-2-Clause, Alliance for Open Media.
14. [libaom, `PATENTS`](https://aomedia.googlesource.com/aom/+/refs/heads/main/PATENTS) — Alliance for Open Media Patent License 1.0.
15. [Netflix VMAF, `LICENSE`](https://raw.githubusercontent.com/Netflix/vmaf/master/LICENSE) — "BSD+Patent / SPDX short identifier: BSD-2-Clause-Patent"; contradicts `LICENSE.md`'s Apache-2.0 classification.
16. [FFmpeg, `libavfilter/vf_lensfun.c`, tag n8.1](https://github.com/FFmpeg/FFmpeg/blob/n8.1/libavfilter/vf_lensfun.c) — GPL "version 3 of the License, or (at your option) any later version" header, against a `configure` gate of `version3` only.
17. [FFmpeg, `Changelog`, tag n8.1](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1/Changelog) — the 8.1 and 8.0 feature lists; note neither records the libpostproc removal, which was established by tag-diffing the tree instead.
18. [FFmpeg, `libavfilter/vf_lut.c`, tag n8.1](https://github.com/FFmpeg/FFmpeg/blob/n8.1/libavfilter/vf_lut.c) — LGPL-2.1+; defines `lut`, `lutrgb`, `lutyuv`.
19. [FFmpeg, `libavfilter/vf_gblur.c`, tag n8.1](https://github.com/FFmpeg/FFmpeg/blob/n8.1/libavfilter/vf_gblur.c) — BSD-2-Clause header.
20. [FFmpeg, `libavfilter/vf_deband.c`, tag n8.1](https://github.com/FFmpeg/FFmpeg/blob/n8.1/libavfilter/vf_deband.c) — MIT header.
21. `imageio-ffmpeg` 0.6.0 bundled binary `ffmpeg-macos-aarch64-v7.1`, observed locally 2026-09-02 — `ffmpeg version 7.1`, `--enable-gpl --enable-libx264 --enable-libx265 --enable-libvidstab --enable-postproc --enable-libzimg`, `-L` = GPL version 2 or later. [imageio-ffmpeg on PyPI](https://pypi.org/project/imageio-ffmpeg/).
22. [FFmpeg, `libavfilter/allfilters.c`, tag n8.1](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1/libavfilter/allfilters.c) — the registration list; `ff_vf_pp` absent, `ff_vf_geq`/`ff_vf_pp7`/`ff_vf_spp`/`ff_vf_uspp`/`ff_vf_fspp` present.
23. [Homebrew `ffmpeg` formula](https://formulae.brew.sh/formula/ffmpeg) — declares `license "GPL-3.0-or-later"`, matching the probed `-L`. Installed keg observed locally: `ffmpeg/8.1_1`, with `x264 r3222`, `x265 4.2`, `svt-av1 4.1.0`, `libvpx 1.16.0`, `libvmaf 3.1.0`, `openssl@3 3.6.3`.
