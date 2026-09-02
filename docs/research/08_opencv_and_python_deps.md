# The OpenCV / Python-dependency licence surface for `looks`' optional extras

*2026-09-02. Research note for `looks`. Companion to [`00_ffmpeg_licence_gates_evidence.md`](00_ffmpeg_licence_gates_evidence.md), which covers the ffmpeg **filter** gates; this note covers the **Python packages** `looks` would name in `[project.optional-dependencies]`. All commands below were run on this machine (macOS 15.7.4 / Darwin 24.6.0, arm64, CPython 3.12.12 at `~/.pyenv/versions/p12`) on 2026-09-02, and every output shown is real.*

## Verdict

**The kickoff's two headline prohibitions are confirmed, and a third one — bigger, because it lands on the dependency `looks` genuinely needs — was found.** `imageio-ffmpeg` 0.6.0 does ship a `--enable-gpl` ffmpeg binary (49 MB, sitting in site-packages right now, reached through `burns → moviepy`, a **hard** requirement, not an extra); `av` 16.0.1 does bundle `libx264`/`libx265` under `License-Expression: BSD-3-Clause`, and its build **patches FFmpeg's `configure` to move `libx264`/`libx265` out of `EXTERNAL_LIBRARY_GPL_LIST`**, which is why its `avutil_license()` misreports "LGPL version 3 or later" — so the self-report is engineered, not merely absent. The new finding: **the macOS wheels of `opencv-python*` bundle a GPL-3.0-or-later FFmpeg** (Homebrew 7.1.1_3, `--enable-gpl --enable-version3`, with `libx264`, `libx265`, `libvidstab`, `librubberband`, `libpostproc` and `frei0r`), and `import cv2` loads `libx264` and `libx265` into the process, while the project README states "All wheels ship with FFmpeg licensed under the LGPLv2.1" and the wheel's own `LICENSE-3RD-PARTY.txt` mentions x264 zero times. This is upstream issue [opencv/opencv-python#1260](https://github.com/opencv/opencv-python/issues/1260), open since 2026-08-12, predicted by [#142](https://github.com/opencv/opencv-python/issues/142) in 2018. **The `manylinux` wheels are clean** (LGPL-2.1-or-later, no x264/x265) — so the tier of `pip install looks[flatten]` is *platform-dependent*, which is the single most consequential design fact in this note. OpenCV the library is fine (Apache-2.0 since 4.5.0, BSD-3 through 4.4.0), `pyrMeanShiftFiltering` and `edgePreservingFilter` are both **main-module, unencumbered, in all four distributions**, and `numpy`/`Pillow`/`scipy`/`scikit-image` are all permissive. The recommendation is a narrow `[flatten]` extra pinning `opencv-python-headless`, a `[flatten-permissive]` alternative on `scikit-image`, a `[measure]` extra on `numpy` alone, **no moviepy extra at all**, and a runtime tier probe that reports `gpl` when it finds a GPL-listed vendored library next to `cv2` — because a static extras declaration cannot tell the truth about a package whose licence changes with the wheel you happened to get.

---

## 0. What "verified" means in this note

Three levels are used, and they are marked:

- **Verified** — a command was run on this machine, or a file was fetched at a named URL/tag, and the output is reproduced below.
- **Verified upstream** — the claim rests on a source file or issue fetched today at a pinned ref, not on a local run.
- **Unverified** — stated as such, explicitly, every time.

The distinction matters because the central finding of this note is that *published metadata about media packages is unreliable in the direction that hurts*. Three of the four packages examined (`opencv-python*`, `av`, `imageio-ffmpeg`) carry permissive metadata over copyleft binaries. So nothing here is taken from a `License:` field.

---

## 1. OpenCV

### 1.1 The library's own licence, and the version it changed

**Verified upstream.** OpenCV relicensed from 3-clause BSD to Apache-2.0 between 4.4.0 and 4.5.0. Fetched today:

```
$ curl -sL https://raw.githubusercontent.com/opencv/opencv/4.4.0/LICENSE | head -12
...
                          License Agreement
               For Open Source Computer Vision Library
                       (3-clause BSD License)

Copyright (C) 2000-2020, Intel Corporation, all rights reserved.

$ curl -sL https://raw.githubusercontent.com/opencv/opencv/4.5.0/LICENSE | head -4

                                 Apache License
                           Version 2.0, January 2004
```

At tag `4.13.0`, both `opencv/opencv` and `opencv/opencv_contrib` are Apache-2.0 [1][2]. Note that **individual source files still carry the old BSD-3 header** — `modules/imgproc/src/segmentation.cpp` and `modules/photo/src/npr.cpp` both open with the legacy "License Agreement / For Open Source Computer Vision Library" BSD-3 block at 4.13.0. The repository `LICENSE` is Apache-2.0 and governs; the per-file headers were never scrubbed. Both are permissive, so nothing turns on it, but do not be surprised by it.

**Both are permissive. Neither is the thing that matters.**

### 1.2 The four PyPI distributions

**Verified.** All four are published by the same project (`opencv/opencv-python`), all four declare `License: Apache 2.0` on PyPI, and all four are at `5.0.0.93` as of today (with `4.14.0.94`, `4.13.0.92` and `4.13.0.90` also on the index):

```
$ curl -sL https://pypi.org/pypi/opencv-python-headless/json | python -c "import json,sys; i=json.load(sys.stdin)['info']; print(i['version'], repr(i['license']))"
5.0.0.93 'Apache 2.0'
```

| distribution | OpenCV modules | GUI backend | bundles FFmpeg? |
|---|---|---|---|
| `opencv-python` | main only | yes (Cocoa / Qt5 on Linux) | **yes** |
| `opencv-python-headless` | main only | no Qt5 on Linux | **yes** |
| `opencv-contrib-python` | main + `opencv_contrib` | yes | **yes** |
| `opencv-contrib-python-headless` | main + `opencv_contrib` | no Qt5 on Linux | **yes** |

There is **no** FFmpeg-free wheel. That has been an open feature request since 2020 ([#353](https://github.com/opencv/opencv-python/issues/353)) [3]. The only supported escape is a source build: the README documents a `CMAKE_ARGS` environment variable for exactly this [4], so `CMAKE_ARGS="-DWITH_FFMPEG=OFF" pip install --no-binary opencv-python-headless opencv-python-headless` is the FFmpeg-free path. **Unverified** — I did not run that build; it takes tens of minutes and needs a toolchain.

One correction to a common assumption: **`headless` does not mean "fewer bundled binaries" on macOS.** The README's own statement is that Qt 5 ships in "non-headless Linux wheels" [4] — the headless distinction is a *Linux GUI* distinction. The macOS headless wheel installed here reports `GUI: COCOA / Cocoa: YES` in its own build information, which is surprising but is what the loaded binary says (see §1.7 for how I established which wheel is loaded). Choosing headless still buys you the absence of Qt-5-LGPLv3 on Linux, which is worth having; it buys you nothing on macOS.

### 1.3 The finding: the macOS wheel bundles a GPL-3.0-or-later FFmpeg

This is the part that must not be taken on trust, so here is the whole chain.

**(a) The wheel bundles 93 native libraries.** Verified:

```
$ ls ~/.pyenv/versions/p12/lib/python3.12/site-packages/cv2/.dylibs | wc -l
      93
$ ls ~/.pyenv/versions/p12/lib/python3.12/site-packages/cv2/.dylibs | grep -Ei 'x264|x265'
libx264.164.dylib
libx265.215.dylib
```

Also present, all of which FFmpeg gates behind `--enable-gpl`: `libvidstab.1.2.dylib`, `librubberband.3.dylib`, `libpostproc.58.3.100.dylib`. (`frei0r` is `dlopen`ed at runtime rather than linked, so it has no vendored dylib, but it is in the configure line.)

**(b) The bundled FFmpeg is Homebrew's, configured `--enable-gpl --enable-version3`.** Verified, by reading the configuration string out of the binary:

```
$ strings -a cv2/.dylibs/libavcodec.61.19.101.dylib | grep -m1 -- '--prefix='
--prefix=/opt/homebrew/Cellar/ffmpeg/7.1.1_3 --enable-shared --enable-pthreads --enable-version3 --cc=clang ... --enable-ffplay --enable-gnutls --enable-gpl --enable-libaom --enable-libaribb24 ... --enable-librubberband ... --enable-libvidstab --enable-libvmaf --enable-libvorbis --enable-libvpx --enable-libwebp --enable-libx264 --enable-libx265 --enable-libxml2 --enable-libxvid ... --enable-frei0r ...
```

**(c) FFmpeg itself says so.** Verified, calling the library's own accessor through `ctypes`:

```
$ python -c "import ctypes; l=ctypes.CDLL('./libavutil.59.39.100.dylib'); l.avutil_license.restype=ctypes.c_char_p; print(l.avutil_license().decode())"
GPL version 3 or later
```

`avcodec_license()` and `avformat_license()` return the same string. `--enable-gpl` alone gives GPL-2.0-or-later; **`--enable-gpl` together with `--enable-version3` gives GPL-3.0-or-later**, which is what this is.

**(d) `cv2` is directly linked to it, not `dlopen`ing it.** Verified:

```
$ otool -L cv2/cv2.abi3.so | grep -E 'libav|libsw'
	@loader_path/.dylibs/libavformat.61.7.100.dylib
	@loader_path/.dylibs/libavcodec.61.19.101.dylib
	@loader_path/.dylibs/libswscale.8.3.100.dylib
	@loader_path/.dylibs/libavutil.59.39.100.dylib
	@loader_path/.dylibs/libavdevice.61.3.100.dylib
```

**(e) So `import cv2` pulls GPL code into the process.** Verified, by snapshotting `dyld`'s loaded-image list before and after the import:

```
FFmpeg-family images loaded into the process after `import cv2`:
   .../cv2/.dylibs/libavformat.61.7.100.dylib
   .../cv2/.dylibs/libavcodec.61.19.101.dylib
   .../cv2/.dylibs/libavutil.59.39.100.dylib
   .../cv2/.dylibs/libswscale.8.3.100.dylib
   .../cv2/.dylibs/libavdevice.61.3.100.dylib
   .../cv2/.dylibs/libswresample.5.3.100.dylib
   .../cv2/.dylibs/libx264.164.dylib
   .../cv2/.dylibs/libx265.215.dylib
   .../cv2/.dylibs/libavfilter.10.4.100.dylib
   .../cv2/.dylibs/libpostproc.58.3.100.dylib
   .../cv2/.dylibs/librubberband.3.dylib
   .../cv2/.dylibs/libvidstab.1.2.dylib
```

This is not a dormant file on disk. `libx264` and `libx265` are resolved and mapped by `dyld` on `import cv2`, whether or not a single OpenCV call is made.

**(f) The published documentation says the opposite.** Verified upstream — `opencv-python`'s README on the `4.x` branch, fetched today, line 203 [4]:

> All wheels ship with [FFmpeg](http://ffmpeg.org) licensed under the [LGPLv2.1](http://www.gnu.org/licenses/old-licenses/lgpl-2.1.html).

**(g) And the wheel's own notice file does not list what it ships.** Verified:

```
$ grep -ci x264 cv2/LICENSE-3RD-PARTY.txt ; grep -ci x265 cv2/LICENSE-3RD-PARTY.txt
0
0
$ grep -ci vidstab cv2/LICENSE-3RD-PARTY.txt ; grep -ci rubberband cv2/LICENSE-3RD-PARTY.txt
0
0
$ grep -c 'is redistributed within' cv2/LICENSE-3RD-PARTY.txt
36
```

36 declarations for 93 bundled libraries — and `x264`, `x265`, `vidstab`, `rubberband`, `SDL2`, `tesseract`, `zmq`, `aribb24`, `jxl` and `mbedcrypto` are among the ones with no declaration at all. **The notice file is byte-identical between the macOS-arm64 and the manylinux wheel** (`md5 = 4816c658beed4c135da7fc79751ce438` for both), which is the mechanism: it is one static file checked into the repo, not a per-wheel manifest generated from what `delocate`/`auditwheel` actually vendored.

**(h) This is known upstream, and it is old.** Verified upstream. [opencv/opencv-python#1260](https://github.com/opencv/opencv-python/issues/1260) — *"macOS ARM64 wheel 5.0.0.93 bundles GPL-configured FFmpeg (libx264/libx265) — conflicts with README LGPLv2.1 statement"* — is **open**, filed 2026-08-12, with binary-level evidence against the current release [5]. Its cause was diagnosed in 2018 by [#142](https://github.com/opencv/opencv-python/issues/142), *"OSX FFmpeg can no longer be built without GPL libs"* [6], which observed that Homebrew had dropped `--without-gpl` and concluded: *"This means that an OSX build built after 2018-10-17 would be covered by GPLv2."* That issue was closed 2018-11-25 with no README change. The macOS wheels have been GPL for seven years.

Why macOS and not Linux: the README's own build description says *"Linux and macOS wheels are transformed with auditwheel and delocate, correspondingly"* [4]. The Linux job builds its own minimal FFmpeg in the manylinux container; the macOS job links against `brew install ffmpeg` and `delocate` faithfully vendors the entire transitive closure of that — all 93 libraries.

### 1.4 The manylinux wheel is clean

**Verified.** Downloaded (not installed) into a scratch directory:

```
$ pip download --no-deps --only-binary=:all: --platform manylinux_2_17_x86_64 \
    --python-version 3.12 --implementation cp --abi abi3 opencv-python-headless==4.13.0.92
Saved ./opencv_python_headless-4.13.0.92-cp37-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
```

Its entire vendored-library set is 16 files:

```
opencv_python_headless.libs/libaom-969ba5f6.so.3.13.1
opencv_python_headless.libs/libavcodec-f34387fd.so.62.11.100
opencv_python_headless.libs/libavformat-3b50f3e1.so.62.3.100
opencv_python_headless.libs/libavif-3b21aa2d.so.16.3.0
opencv_python_headless.libs/libavutil-725d6688.so.60.8.100
opencv_python_headless.libs/libcrypto-a3a73854.so.1.1
opencv_python_headless.libs/libdrm-827b956f.so.2.4.0
opencv_python_headless.libs/libgfortran-91cc3cb1.so.3.0.0
opencv_python_headless.libs/libopenblasp-r0-37b5f859.3.3.so
opencv_python_headless.libs/libpng16-bd5c241b.so.16.53.0
opencv_python_headless.libs/libquadmath-96973f99.so.0.0.0
opencv_python_headless.libs/libssl-28bef1ac.so.1.1
opencv_python_headless.libs/libswresample-9cc684ef.so.6.1.100
opencv_python_headless.libs/libswscale-4da61192.so.9.1.100
opencv_python_headless.libs/libvpx-e2bf207e.so.11.0.1
```

No `libx264`, no `libx265`, no `libvidstab`, no `librubberband`, no `libpostproc`. The FFmpeg is 8.0 (`libavcodec.so.62`), configured `--enable-openssl --enable-libvpx --enable-shared --enable-pic --bindir=/root/bin` — no `--enable-gpl` — and the embedded licence string confirms it:

```
$ strings -a libavutil-725d6688.so.60.8.100 | grep -E 'GPL version'
libavutil license: LGPL version 2.1 or later
```

Two secondary observations on the Linux wheel, neither disqualifying:

- **`libquadmath` is LGPL-2.1-or-later and is *not* covered by the GCC Runtime Library Exception**, unlike `libgfortran`/`libgcc_s`, which are GPL-3.0-or-later WITH GCC-exception-3.1. This is a well-known packaging wrinkle in the scientific-Python wheel world. It is a dynamically-linked LGPL library, so it sits in the same tier as the LGPL FFmpeg, not above it.
- The wheel bundles **OpenSSL 1.1** (`libcrypto-…so.1.1`). FFmpeg 8.1's `configure` no longer lists `openssl` in `EXTERNAL_LIBRARY_NONFREE_LIST` (which now holds only `decklink`, `libfdk_aac`, `libmpeghdec` — see companion note 00), so FFmpeg does not flag the combination. **Unverified**: whether OpenSSL 1.1's own licence (the pre-3.0 OpenSSL/SSLeay licence, with an advertising clause) creates any obligation for a redistributor here. It does not affect `looks`, which never calls the network paths.

### 1.5 contrib and the nonfree question

**Verified.** The PyPI `opencv-contrib-python` wheels ship **without** nonfree algorithms. From the build information of the loaded binary:

```
    Non-free algorithms:         NO
```

Consequences:

- **SIFT is available and unencumbered.** The Fourier–Lowe patent (US 6,711,293) expired 2020-03-06, and OpenCV moved `SIFT` from `xfeatures2d` into the **main** `features2d` module at 4.4.0. `cv2.SIFT_create` exists in the installed build.
- **SURF is not available.** It remains in `xfeatures2d` behind `OPENCV_ENABLE_NONFREE`, which the PyPI wheels do not set. Verified: `cv2.xfeatures2d.SURF_create` raises `AttributeError`. Its patent (US 8,165,401) is also long expired, but the build flag is what governs what you get, and you get nothing.
- Therefore **there is no nonfree-algorithm reason to prefer or avoid `opencv-contrib-python`.** The reasons to avoid it are size and irrelevance: `contrib`'s `cv2.abi3.so` is 47.8 MB against headless's 34.9 MB (from the two wheels' `RECORD` files), and `looks` needs nothing from `opencv_contrib`.

Worth flagging for the wider federation: **`mixing` currently declares `opencv-contrib-python`**, which is both larger than it needs and — on macOS — the same GPL wheel. That is a separate ticket, not a `looks` problem, but `looks` should not copy it.

### 1.6 The two filters `looks` actually needs

| function | OpenCV module | distribution needed | licence | patent / nonfree notes |
|---|---|---|---|---|
| `cv2.pyrMeanShiftFiltering` | `imgproc` (**main**) | any of the four | Apache-2.0 (file header still BSD-3) | none found |
| `cv2.edgePreservingFilter` | `photo` (**main**) | any of the four | Apache-2.0 (file header still BSD-3) | none found |

**Verified upstream**: `pyrMeanShiftFiltering` lives in [`modules/imgproc/src/segmentation.cpp`](https://github.com/opencv/opencv/blob/4.13.0/modules/imgproc/src/segmentation.cpp) at tag 4.13.0; grepping that file for `patent`, `nonfree`, `non-free` returns nothing. `edgePreservingFilter` lives in [`modules/photo/src/npr.cpp`](https://github.com/opencv/opencv/blob/4.13.0/modules/photo/src/npr.cpp), which uses the domain-transform machinery in `npr.hpp`; grepping `npr.cpp`, `npr.hpp` and `edge_filter.hpp` for the same terms returns only the standard licence-header lines. Both are in `imgproc`/`photo`, i.e. **main** modules present in all four distributions.

**Verified locally** that both run in the installed build:

```
pyrMeanShiftFiltering ok, shape (64, 64, 3)
edgePreservingFilter ok, shape (64, 64, 3)
```

One caveat I want on the record because it is easy to trip over later. `edgePreservingFilter` implements Gastal & Oliveira's domain transform (SIGGRAPH 2011). The *authors'* own reference implementation is distributed for non-commercial use; OpenCV's is an independent implementation under OpenCV's own licence, and OpenCV's build carries no patent or nonfree flag for it. **Unverified**: whether any patent covers the domain transform itself. It does not matter for `looks` — the measured Que Calor work rules `edgePreservingFilter` out on *quality* grounds (it smooths across object boundaries and dissolves figures into the background), so `looks` should never register it as a flattening effect anyway. Recording it so nobody re-opens the question thinking there is a licence angle.

### 1.7 An environment gotcha worth knowing before you trust any `pip show`

**Verified.** This machine has **three** OpenCV distributions installed at once, all writing into the same `site-packages/cv2/` directory:

```
$ pip show opencv-python opencv-contrib-python opencv-python-headless | grep -E '^(Name|Version)'
Name: opencv-python
Version: 4.12.0.88
Name: opencv-contrib-python
Version: 4.13.0.92
Name: opencv-python-headless
Version: 4.13.0.92
```

`import cv2` reports `4.13.0`. Which of the three is actually loaded is settled by hashing the extension module against each distribution's `RECORD`:

```
$ python -c "import hashlib,base64; h=hashlib.sha256(open('cv2/cv2.abi3.so','rb').read()).digest(); print(base64.urlsafe_b64encode(h).rstrip(b'=').decode())"
KiYt5rcNO2z6LMeKdqXX7dARfrH-Jg29o_KdYSDIgfA

opencv_python_headless-4.13.0.92 RECORD: cv2/cv2.abi3.so,sha256=KiYt5rcNO2z6LMeKdqXX7dARfrH-Jg29o_KdYSDIgfA,34937504   ← match
opencv_contrib_python-4.13.0.92  RECORD: cv2/cv2.abi3.so,sha256=hHVrsm7UcYC_UW6112NXC1KoOxP9zDtkweL8fJhC94U,47781680
opencv_python-4.12.0.88          RECORD: cv2/cv2.abi3.so,sha256=05DFeJWUEwGAryR2tOpegMyGeWJLXtYXmgvqtgjZiu0,33965344
```

**The loaded build is `opencv-python-headless` 4.13.0.92**, last writer wins, and the other two distributions' metadata is now lying. Worse, the overwrite left behind orphaned stub directories from the contrib install, so `cv2.ximgproc` and `cv2.xfeatures2d` **import successfully as empty namespace packages**:

```
$ python -c "import cv2; print(cv2.ximgproc); print([x for x in dir(cv2.ximgproc) if not x.startswith('_')])"
<module 'cv2.ximgproc' (namespace) from ['.../site-packages/cv2/ximgproc']>
[]
```

`hasattr(cv2, 'ximgproc')` is `True` and every function in it is missing. A capability probe written as `hasattr(cv2, 'ximgproc')` will pass and then fail at call time. If `looks` ever probes for contrib, probe for a **function**, never a submodule.

---

## 2. numpy, Pillow, scipy, scikit-image

All four are permissive. **Verified** at the versions installed here.

| package | version | licence | how established | notes |
|---|---|---|---|---|
| `numpy` | 2.2.6 | **BSD-3-Clause** | `numpy-2.2.6.dist-info/LICENSE.txt` (verbatim BSD-3 text, "Copyright (c) 2005-2024, NumPy Developers") | no vendored native libs on this macOS wheel (`numpy/.dylibs` absent) |
| `Pillow` | 11.3.0 | **MIT-CMU** (the HPND/PIL variant) | `License-Expression: MIT-CMU` in METADATA, and the LICENSE file itself says "licensed under the open source MIT-CMU License" | bundles 18 natives — libjpeg, libtiff, libwebp, freetype, harfbuzz, lcms2, openjpeg, brotli, liblzma, zlib-ng, libavif, libxcb/libXau — **all permissive**; no copyleft |
| `scipy` | 1.16.3 | **BSD-3-Clause** | `scipy-1.16.3.dist-info/LICENSE.txt` (DEP-5 style; BSD-3 text for scipy itself) | bundles `libgfortran.5`, `libquadmath.0`, `libgcc_s.1.1`. Its own LICENSE.txt declares libgfortran/libgcc as `GPL-3.0-or-later WITH GCC-exception-3.1`, and documents libquadmath separately (LGPL-2.1-or-later, **not** covered by the runtime exception) |
| `scikit-image` | 0.26.0 | **BSD-3-Clause** | `LICENSE.txt`, DEP-5 style: 14 `License:` stanzas, of which 11 BSD-3, 2 BSD-2, 3 MIT — **nothing copyleft** | pure-Python + Cython over numpy/scipy; no vendored media codecs |

Which of them `looks` actually needs, per capability:

| capability | needs | why not more |
|---|---|---|
| `Look` / `Effect` dataclasses, registry, tiers, argv compilation, `.cube` LUT writing | **nothing** (stdlib) | a `.cube` file is text; a filter chain is a string; the geometry tier is arithmetic |
| Post-effect measurement — Laplacian variance for the per-source flattening scale, L\* histogram for the shadow floor | **numpy** | frames arrive from `ffmpeg -f rawvideo -pix_fmt rgb24 pipe:` straight into `np.frombuffer`; a 3×3 Laplacian is four slices and a subtraction. No cv2, no Pillow, no scipy |
| Flattening (`pyrMeanShiftFiltering`) | **opencv-python-headless** | there is no numpy-speed mean-shift, and no ffmpeg filter equivalent (see §5.3) |
| Permissive-only flattening fallback | **scikit-image** | `skimage.segmentation.quickshift` (present in 0.26.0, verified) is a mode-seeking segmenter in the same family; BSD-3, and its wheel vendors no media codecs |
| Reading/writing reference stills, palette extraction, LUT preview PNGs | **Pillow** | Pillow's wheel is the only image-IO wheel examined here with an all-permissive native bundle |

**`scipy` is not needed.** Everything `looks` would use it for (a small convolution, a histogram) is numpy. Naming it would drag in `libquadmath`'s LGPL-2.1 for nothing.

---

## 3. The forbidden list, verified

### 3.1 `imageio-ffmpeg` — kickoff claim **CONFIRMED, exactly as stated**

**Verified.** Installed version 0.6.0, `License: BSD-2-Clause`, one `LICENSE` file in dist-info covering `imageio-ffmpeg` itself and nothing else. It ships a 49 MB binary:

```
$ python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
.../site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1

$ ls -la .../imageio_ffmpeg/binaries/
-rwxr-xr-x  1 thorwhalen  staff  49368728 Oct 22  2025 ffmpeg-macos-aarch64-v7.1
-rw-r--r--  1 thorwhalen  staff        45 Oct 22  2025 README.md      # "Exes are dropped here by the release script."

$ .../ffmpeg-macos-aarch64-v7.1 -version
ffmpeg version 7.1 Copyright (c) 2000-2024 the FFmpeg developers
configuration: --prefix=/Volumes/tempdisk/sw ... --enable-gpl --enable-libvmaf --enable-libopenjpeg
  --enable-libopus --enable-libmp3lame --enable-libx264 --enable-libx265 --enable-libvpx --enable-libwebp
  --enable-libass --enable-libfreetype --enable-fontconfig --enable-libtheora --enable-libvorbis
  --enable-libsnappy --enable-libaom --enable-libvidstab --enable-libzimg --enable-libsvtav1
  --enable-libharfbuzz --enable-libkvazaar --pkg-config-flags=--static --enable-ffplay --enable-postproc ...
```

`--enable-gpl`, no `--enable-version3` ⇒ **GPL-2.0-or-later**. A GPL-2.0-or-later ffmpeg binary is sitting in site-packages on this machine right now, redistributed under BSD-2-Clause metadata, with no accompanying GPL notice and no offer of source.

### 3.2 `av` — kickoff claim **CONFIRMED, and the mechanism is worse than stated**

**Verified.** `av` 16.0.1 is installed (pulled in by `faster-whisper` and `manim`). Its metadata:

```
License-Expression: BSD-3-Clause
License-File: LICENSE.txt
```

Its dist-info `licenses/` directory contains exactly three files — `LICENSE.txt`, `AUTHORS.py`, `AUTHORS.rst` — i.e. **zero licence text for any of the 27 vendored native libraries**. And those libraries include:

```
$ ls av/.dylibs | grep -Ei 'x264|x265'
libx264.165.dylib
libx265.215.dylib

$ otool -L av/.dylibs/libavcodec.62.11.100.dylib | grep -Ei 'x264|x265'
	@loader_path/libx264.165.dylib
	@loader_path/libx265.215.dylib

$ python -c "from av.codec import Codec; print(Codec('libx264','w').long_name)"
libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10
```

Now the part the kickoff did not know. `av`'s bundled FFmpeg **reports itself as LGPL**:

```
$ python -c "import ctypes; l=ctypes.CDLL('./libavutil.60.8.100.dylib'); l.avutil_license.restype=ctypes.c_char_p; print(l.avutil_license().decode())"
LGPL version 3 or later
```

and its configure line contains `--enable-libx264 --enable-libx265` with **no `--enable-gpl`** — a combination stock FFmpeg refuses to build. FFmpeg 8.1's `configure` puts `libx264` and `libx265` in `EXTERNAL_LIBRARY_GPL_LIST` and then runs [7]:

```sh
die_license_disabled_gpl() {
    enabled $1 || { enabled $v && die "$v is incompatible with the gpl and --enable-$1 is not specified."; }
}
map "die_license_disabled gpl"      $EXTERNAL_LIBRARY_GPL_LIST $EXTERNAL_LIBRARY_GPLV3_LIST
```

**Verified upstream** — the reason it builds anyway is a patch in the build repo. `PyAV-Org/pyav-ffmpeg` ships `patches/ffmpeg.patch` [8], reproduced here in full:

```diff
--- a/configure
+++ b/configure
@@ -1996,8 +1996,6 @@ EXTERNAL_LIBRARY_GPL_LIST="
     librubberband
     libvidstab
-    libx264
-    libx265
     libxavs
@@ -2010,6 +2008,8 @@ EXTERNAL_LIBRARY_NONFREE_LIST="
 EXTERNAL_LIBRARY_VERSION3_LIST="
+    libx264
+    libx265
     gmp
```

The patch **relocates `libx264` and `libx265` from FFmpeg's GPL list into its version3 list**, which is what makes the resulting libavcodec self-report "LGPL version 3 or later" while linking two GPL-2.0-or-later libraries. x264 is GPL-2.0-or-later from VideoLAN and x265 is GPL-2.0-or-later from MulticoreWare; both offer separate commercial licences, which is presumably the theory, but **`pyav-ffmpeg`'s README has no licensing section at all** — grepping it for "licen" returns nothing [9]. Its README does confirm x264 and x265 are enabled "for all platforms" [9].

For `looks` the conclusion is not a legal one and does not need to be. Under "unknown is a refusal", a dependency whose FFmpeg licence self-report has been *engineered by patch* to disagree with the upstream project's own classification is exactly what a refusal is for. **`av` stays on the never list, and the reason is now stronger than the kickoff's version of it.** Corollary for the tier probe (§5.4): `avutil_license()` alone is **not** a sufficient check — PyAV is the counterexample. It must be corroborated by looking at what is actually vendored.

### 3.3 `ultralytics` — **CONFIRMED**

```
$ pip show ultralytics | grep -E '^(Name|Version|License|Requires)'
Name: ultralytics
Version: 8.4.75
License: AGPL-3.0
Requires: matplotlib, numpy, nvidia-ml-py, opencv-python, pillow, polars, psutil, pyyaml, requests, scipy, torch, torchvision, ultralytics-thop

$ python -c "import ultralytics; print(ultralytics.__version__)"
8.4.75
```

Installed and importable, AGPL-3.0 by its own metadata. Note it also **hard-requires `opencv-python`** (the non-headless one), so anything that touches ultralytics drags the GUI wheel in as well.

The kickoff's named alternative checks out: `torchvision` 0.24.0 is installed, `License: BSD`. **Unverified**: the terms attached to torchvision's *pretrained keypoint R-CNN weights* — the code is BSD-3, but pretrained weights carry their own provenance (COCO), and that is a separate question from the package licence. Anyone reaching for person detection should check the weights, not just the wheel.

---

## 4. What the fleet already installs

**Verified.** The chain is one hop shorter than the kickoff describes, and that matters:

```
$ pip show burns   | grep Requires   → Requires: moviepy, numpy, pillow
$ pip show mixing  | grep Requires   → Requires: burns, config2py, dol, moviepy, numpy, opencv-contrib-python, pillow, pydub, scipy, xdol
$ grep '^Requires-Dist' moviepy-2.2.1.dist-info/METADATA
Requires-Dist: imageio<3.0,>=2.5
Requires-Dist: imageio_ffmpeg>=0.2.0        ← unconditional, not an extra
```

`moviepy` 2.2.1 requires `imageio_ffmpeg` **directly and unconditionally**. `imageio` itself only names it under the `ffmpeg` / `all-plugins` / `full` extras — so the route is `burns → moviepy → imageio-ffmpeg`, not `burns → moviepy → imageio → imageio-ffmpeg`. There is no extras flag anyone can decline.

So the kickoff's statement stands, corrected in the caller's favour (it is more direct, not less): **`pip install burns` today redistributes a GPL-2.0-or-later ffmpeg binary**, and so does `pip install mixing`, `pip install muvid` and `pip install braidio`, all of which reach `burns`. This should be a recorded federation decision, not an accident. It is not a *linking* problem — moviepy shells out — but it is unambiguously *redistribution* of a GPL work inside an MIT-labelled dependency tree with no GPL notice and no source offer.

The three things sitting in this environment right now, then:

| what | where | licence of the binary |
|---|---|---|
| Homebrew ffmpeg 8.1_1 on `PATH` | `/opt/homebrew/Cellar/ffmpeg/8.1_1` | **GPL-3.0-or-later** — `ffmpeg -L` says so verbatim: *"under the terms of the GNU General Public License … version 3"*; configure has `--enable-gpl --enable-version3` |
| imageio-ffmpeg's vendored binary | `site-packages/imageio_ffmpeg/binaries/` | **GPL-2.0-or-later** |
| cv2's vendored FFmpeg libraries | `site-packages/cv2/.dylibs/` | **GPL-3.0-or-later** |

Three independent GPL ffmpegs, none of them declared as such by the Python package that put them there. That is the environment `looks` is being designed for, and it is the concrete case for the package.

---

## 5. Recommendation

### 5.1 The two tier axes are different, and `looks` needs both

Companion note 00 tiers **effects** by which ffmpeg filter they compile to. This note is about a second, orthogonal axis: the tier of an **install**. A `Look` that compiles to nothing but `lut3d` and `lutrgb` is LGPL-clean at the *filter* level and can still be executed by a GPL-3 binary and computed by a process that has mapped `libx264` — because of what got installed, not what got called.

`looks` should therefore carry:

- **`Effect.tier`** — static, declared, per effect. Note 00's axis.
- **`environment_tier()`** — probed at runtime, per machine. This note's axis.
- and a `Look`'s effective ceiling is `max(effect tiers, environment tier)`, with `unknown` absorbing everything.

Conflating them produces the exact failure this package exists to prevent: a green "LGPL-safe" verdict on a machine whose ffmpeg is GPL-3.

### 5.2 The proposed `[project.optional-dependencies]`

```toml
[project.optional-dependencies]
# --- tier: permissive -------------------------------------------------------
# Post-effect measurement: Laplacian variance for the per-source flattening
# scale, L* histograms for the shadow floor. Frames arrive over an ffmpeg
# rawvideo pipe, so nothing here decodes media itself.
measure = ["numpy>=1.24"]

# Reference stills, palette extraction, LUT preview strips. Pillow's wheel
# vendors only permissive natives (libjpeg, libtiff, libwebp, freetype,
# harfbuzz, lcms2, openjpeg, brotli, lzma, zlib-ng, libavif, libxcb).
image = ["pillow>=10.0"]

# Permissive-only flattening. skimage.segmentation.quickshift is a different
# algorithm from mean-shift and will NOT reproduce the Que Calor look; it is
# here so a caller pinned to a permissive ceiling has a route that runs.
flatten-permissive = ["scikit-image>=0.22", "numpy>=1.24"]

# --- tier: PLATFORM-DEPENDENT — see docs/research/08 §1.3 -------------------
# cv2.pyrMeanShiftFiltering, and nothing else. Headless deliberately: it drops
# Qt5 (LGPL-3) on Linux and is 13 MB smaller than the contrib build, which
# `looks` needs nothing from.
#
#   manylinux / Windows wheel : FFmpeg is LGPL-2.1-or-later      -> tier "lgpl"
#   macOS wheel              : FFmpeg is GPL-3.0-or-later,       -> tier "gpl"
#                              and `import cv2` maps libx264 and
#                              libx265 into the process.
#
# `looks.environment_tier()` reports the real tier at runtime. Do not assume
# this extra is LGPL because the metadata says Apache 2.0.
flatten = ["opencv-python-headless>=4.10", "numpy>=1.24"]

# --- convenience aggregate --------------------------------------------------
all = ["looks[measure,image,flatten]"]
```

Notes on each decision:

- **No `[render]`, no `[clips]`, no moviepy.** The `mixing/video/video_util.py` refactor the kickoff schedules is moviepy-through-and-through (`from moviepy import VideoFileClip, VideoClip, ImageClip, CompositeVideoClip` at module top — verified), and moviepy hard-requires `imageio-ffmpeg`. Taking it as-is would give `looks` a GPL binary in its own dependency tree, in a package whose *entire premise* is refusing that. **Port it instead**: `SOCIAL_SIZES`, `resize_to_dimensions` and `normalize_video_dimensions` are pure arithmetic over a `(width, height)` pair; their output should be `scale`/`crop`/`pad` filter arguments, not a `CompositeVideoClip`. The same goes for the six transitions in `video_concat.py`, which map onto ffmpeg's LGPL `xfade`. This converts the moviepy dependency into zero dependencies and is the right shape anyway — a `Look` is data, and moviepy clips are execution.
- **No `scipy`.** Everything wanted from it is numpy, and it drags LGPL-2.1 `libquadmath`.
- **`opencv-python-headless`, never `opencv-contrib-python`.** Smaller, no Qt5 on Linux, and `looks` uses zero contrib functions. (`mixing` should be moved off contrib too, separately.)
- **`numpy` appears in three extras rather than becoming a hard dependency.** The zero-dependency promise is the package's identity; a core that can emit an argv list without importing numpy is also a core that can be imported by a licence-auditing tool with no build toolchain.

### 5.3 Extras `looks` must NOT offer, with the reason for each

| never offer | reason |
|---|---|
| `av` | GPL-2.0-or-later x264/x265 vendored and linked, under BSD-3-Clause metadata, with FFmpeg's own GPL gate patched out (§3.2). No licence text for any of its 27 vendored natives |
| `imageio-ffmpeg` | ships a 49 MB `--enable-gpl` ffmpeg binary under BSD-2-Clause metadata (§3.1) |
| `moviepy` | hard-requires `imageio-ffmpeg` (§4). MIT itself; the tree is not |
| `ultralytics` | AGPL-3.0 (§3.3) |
| `opencv-contrib-python*` | no capability `looks` needs, 13 MB larger, same platform-dependent FFmpeg problem |
| `ffmpeg-python`, `python-ffmpeg`, and friends | not examined here, but the same question applies to each: do they *vendor* a binary or find one on `PATH`? A wrapper that vendors is disqualified by the same rule. **Unverified** for these specific packages |

And a related negative result worth recording, because someone will ask: **there is no ffmpeg filter that substitutes for `pyrMeanShiftFiltering`.** FFmpeg 8.1 has `bilateral` (LGPL) and `smartblur` (GPL), and the measured Que Calor work rules the whole bilateral family out on quality grounds — it smooths across object boundaries. Mean-shift clusters in colour *and* position, and nothing in libavfilter does that. So the `[flatten]` extra is not avoidable by pushing work into ffmpeg; it is a genuine capability boundary, which is precisely why it deserves its own extra and its own tier.

### 5.4 The runtime probe, and why it needs two checks

`looks.environment_tier()` should report the highest tier among the executables and libraries it will actually use, and **`unknown` must be a refusal, never a warning**. Three probes, each cheap:

1. **The ffmpeg binary on `PATH`.** `ffmpeg -L` prints the licence in prose (`"under the terms of the GNU General Public License … version 3"` on this machine); `ffmpeg -buildconf` prints the flags. Some distribution builds strip both — that case is `unknown`, hence a refusal. Companion note 00 already states this rule.
2. **The vendored FFmpeg beside `cv2`, if `cv2` is imported.** Call `avutil_license()` through `ctypes` on `cv2/.dylibs/libavutil.*` (or `cv2/../opencv_python*.libs/libavutil-*.so`). One call, no import of OpenCV needed, and it produced the correct answer for all three wheels examined here.
3. **Corroboration by inventory.** List the vendored-library directory and match against FFmpeg's own `EXTERNAL_LIBRARY_GPL_LIST` — `x264`, `x265`, `xvid`, `vidstab`, `rubberband`, `frei0r`, `davs2`, `xavs`, `xavs2`, `avisynth`, `cdio`, `dvdnav`, `dvdread` (companion note 00 has the full list, extracted from `configure` at `n8.1`).

**Probe 2 alone is insufficient, and PyAV is the proof** (§3.2): a patched build reports LGPL while shipping GPL libraries. **When probe 2 and probe 3 disagree, the answer is the stricter one, and the disagreement itself should be surfaced** — it is the single most informative thing `looks` can tell a user, and no other tool in this space tells them at all.

---

## 6. Evidence table

| # | Claim | Verdict | How verified | Version anchor | Ref |
|---|---|---|---|---|---|
| 1 | OpenCV was BSD-3 through 4.4.0 | **Confirmed** | fetched `LICENSE` at tag `4.4.0`; header reads "(3-clause BSD License)" | opencv 4.4.0 | [1] |
| 2 | OpenCV is Apache-2.0 from 4.5.0 | **Confirmed** | fetched `LICENSE` at tags `4.5.0` and `4.13.0`; both Apache-2.0 | opencv 4.5.0, 4.13.0 | [1] |
| 3 | `opencv_contrib` is also Apache-2.0 | **Confirmed** | fetched `LICENSE` at tag `4.13.0` | opencv_contrib 4.13.0 | [2] |
| 4 | All four opencv PyPI dists declare Apache 2.0 | **Confirmed** | PyPI JSON API, all four projects | latest = 5.0.0.93 | — |
| 5 | The PyPI wheel bundles an FFmpeg build | **Confirmed** | `cv2.getBuildInformation()` → `FFMPEG: YES, avcodec 61.19.101`; `ls cv2/.dylibs` | opencv-python-headless 4.13.0.92 | — |
| 6 | **macOS wheel's FFmpeg is GPL-3.0-or-later** | **Confirmed** | `ctypes` → `avutil_license()` = `"GPL version 3 or later"`; configure string shows `--enable-gpl --enable-version3` | headless 4.13.0.92, macosx_13_0_arm64, ffmpeg 7.1.1_3 (Homebrew) | [5][6] |
| 7 | macOS wheel bundles libx264 + libx265 | **Confirmed** | `ls cv2/.dylibs` → `libx264.164.dylib`, `libx265.215.dylib` | same | — |
| 8 | `import cv2` maps them into the process | **Confirmed** | `_dyld_get_image_name` snapshot before/after import; also `otool -L cv2.abi3.so` shows direct `@loader_path` links to the av* family | same | — |
| 9 | The wheel's LICENSE-3RD-PARTY.txt omits them | **Confirmed** | `grep -ci x264` = 0, `x265` = 0, `vidstab` = 0, `rubberband` = 0; 36 declarations for 93 dylibs | same | — |
| 10 | That notice file is identical across platforms | **Confirmed** | `md5` of macOS-installed vs extracted-from-manylinux = `4816c658beed4c135da7fc79751ce438` for both | 4.13.0.92 | — |
| 11 | opencv-python's README claims LGPLv2.1 for all wheels | **Confirmed** | fetched README, branch `4.x`, line 203 | fetched 2026-09-02 | [4] |
| 12 | This is a known open upstream issue | **Confirmed** | GitHub API: issue #1260, state `open`, created 2026-08-12; #142 closed 2018-11-25 predicted it; #353 (FFmpeg-free wheel) open since 2020 | — | [3][5][6] |
| 13 | **manylinux wheel is LGPL-2.1, no x264/x265** | **Confirmed** | `pip download --platform manylinux_2_17_x86_64`; 16 vendored libs, none GPL; `strings` → `"libavutil license: LGPL version 2.1 or later"` | headless 4.13.0.92, manylinux2014_x86_64, ffmpeg 8.0 | — |
| 14 | `opencv-contrib-python` on PyPI ships no nonfree | **Confirmed** | build info: `Non-free algorithms: NO`; `cv2.xfeatures2d.SURF_create` → AttributeError | 4.13.0.92 | — |
| 15 | SIFT is in main `features2d` and available | **Confirmed** | `hasattr(cv2, 'SIFT_create')` → True | 4.13.0 | — |
| 16 | `pyrMeanShiftFiltering` is main-module, unencumbered | **Confirmed** | `modules/imgproc/src/segmentation.cpp` at tag 4.13.0; no patent/nonfree strings; runs locally | opencv 4.13.0 | [1] |
| 17 | `edgePreservingFilter` is main-module, unencumbered | **Confirmed** | `modules/photo/src/npr.cpp` + `npr.hpp` + `edge_filter.hpp` at 4.13.0; no patent/nonfree strings; runs locally | opencv 4.13.0 | [1] |
| 18 | Three opencv dists installed here; headless is the loaded one | **Confirmed** | sha256 of `cv2/cv2.abi3.so` matches only `opencv_python_headless-4.13.0.92`'s RECORD | — | — |
| 19 | `cv2.ximgproc` imports as an empty namespace | **Confirmed** | `dir(cv2.ximgproc)` == `[]`, module has `__file__ is None` | — | — |
| 20 | numpy BSD-3 | **Confirmed** | `numpy-2.2.6.dist-info/LICENSE.txt` | numpy 2.2.6 | — |
| 21 | Pillow MIT-CMU | **Confirmed** | `License-Expression: MIT-CMU` + LICENSE text; all 18 vendored natives permissive | pillow 11.3.0 | — |
| 22 | scipy BSD-3, vendors GCC runtime + libquadmath | **Confirmed** | `LICENSE.txt` DEP-5 stanzas; `ls scipy/.dylibs` | scipy 1.16.3 | — |
| 23 | scikit-image BSD-3 (with BSD-2 and MIT files) | **Confirmed** | `LICENSE.txt`: 14 stanzas, 11 BSD-3 / 2 BSD-2 / 3 MIT, none copyleft | scikit-image 0.26.0 | — |
| 24 | **`av` bundles GPL x264/x265 under BSD-3 metadata** | **Confirmed** | `License-Expression: BSD-3-Clause`; `ls av/.dylibs` → libx264.165, libx265.215; `otool -L libavcodec` links both; `Codec('libx264','w')` resolves | av 16.0.1, ffmpeg 8.0-ish (avcodec 62.11.100) | — |
| 25 | `av`'s FFmpeg self-reports LGPL-3 | **Confirmed** | `ctypes` → `avutil_license()` = `"LGPL version 3 or later"`; configure has no `--enable-gpl` | av 16.0.1 | — |
| 26 | …because the build patches FFmpeg's GPL list | **Confirmed** | `pyav-ffmpeg/patches/ffmpeg.patch` moves libx264/libx265 from `EXTERNAL_LIBRARY_GPL_LIST` to `EXTERNAL_LIBRARY_VERSION3_LIST` | fetched 2026-09-02 | [8] |
| 27 | Stock FFmpeg would refuse that build | **Confirmed** | `configure` n8.1: `die_license_disabled gpl` mapped over `EXTERNAL_LIBRARY_GPL_LIST` | ffmpeg n8.1 | [7] |
| 28 | `av` ships no licence text for its vendored natives | **Confirmed** | `av-16.0.1.dist-info/licenses/` = LICENSE.txt + AUTHORS.py + AUTHORS.rst only | av 16.0.1 | — |
| 29 | **`imageio-ffmpeg` bundles an `--enable-gpl` binary** | **Confirmed** | ran the binary: `--enable-gpl --enable-libx264 --enable-libx265 --enable-libvidstab --enable-libkvazaar` | imageio-ffmpeg 0.6.0, ffmpeg 7.1 | — |
| 30 | moviepy requires it unconditionally | **Confirmed** (kickoff phrasing corrected) | `Requires-Dist: imageio_ffmpeg>=0.2.0` with no `extra ==` marker; `imageio` names it only under extras | moviepy 2.2.1, imageio 2.37.0 | — |
| 31 | `burns` → `moviepy` → GPL binary | **Confirmed** | `pip show burns` → `Requires: moviepy, numpy, pillow` | burns 0.0.9 | — |
| 32 | `ultralytics` AGPL-3.0, installed, importable | **Confirmed** | `pip show` → `License: AGPL-3.0`; import succeeds | ultralytics 8.4.75 | — |
| 33 | ultralytics hard-requires `opencv-python` | **Confirmed** | `pip show ultralytics` Requires line | 8.4.75 | — |
| 34 | torchvision is BSD | **Confirmed** (code only) | `pip show torchvision` → `License: BSD` | torchvision 0.24.0 | — |
| 35 | local ffmpeg is GPL-3-or-later | **Confirmed** | `ffmpeg -L` prose + `--enable-gpl --enable-version3` | Homebrew ffmpeg 8.1_1 | — |
| 36 | `mixing/video/video_util.py` is moviepy-coupled | **Confirmed** | module-level `from moviepy import VideoFileClip, VideoClip, ImageClip, CompositeVideoClip` | mixing 0.0.38 | — |

---

## 7. Explicitly unverified

Every item here is unverified and must not be quoted as fact:

1. **Whether a source build of `opencv-python-headless` with `CMAKE_ARGS="-DWITH_FFMPEG=OFF"` actually produces an FFmpeg-free `cv2`.** The README documents the knob [4]; I did not run the build.
2. **Whether conda-forge's `py-opencv` links an LGPL FFmpeg on macOS.** Frequently suggested as the clean alternative; no conda on this machine, so not checked.
3. **Whether the macOS *x86_64* opencv wheel matches the arm64 one.** No `macosx_*_x86_64` wheel exists for 4.13.0.92 at the platform tag I tried (`macosx_13_0_x86_64`); PyPI lists `macosx_14_0_x86_64` for that release, which I did not download. Issue #142's diagnosis (Homebrew's formula) applies to both architectures, so the arm64 result almost certainly generalises — but I have only measured arm64.
4. **Whether PyAV, or any downstream, holds a commercial x264/x265 licence** that would make the `configure` reclassification defensible. Nothing in either repo says so; the `pyav-ffmpeg` README has no licensing section at all [9].
5. **Whether any patent covers the Gastal–Oliveira domain transform** behind `cv2.edgePreservingFilter`. OpenCV's build carries no nonfree flag for it. Moot for `looks`, which rules the filter out on measured quality grounds.
6. **The provenance terms of torchvision's pretrained keypoint R-CNN weights.** The package is BSD; the weights are a separate question.
7. **Whether OpenSSL 1.1's licence creates obligations** for a redistributor of the manylinux opencv wheel. FFmpeg 8.1 does not flag the combination; that is not the same as clearance.
8. **The vendoring behaviour of other PyPI ffmpeg wrappers** (`ffmpeg-python`, `python-ffmpeg`, `ffmpy`, …). Not examined. Apply the same test before naming any of them.
9. **Whether the macOS headless wheel genuinely enables Cocoa**, as its own `getBuildInformation()` reports. The report is the loaded binary's own string and the binary is hash-confirmed to be the headless wheel, so the observation is solid; the *reason* is not established.

---

## REFERENCES

1. [opencv/opencv — `LICENSE`](https://github.com/opencv/opencv/blob/4.13.0/LICENSE) — Apache-2.0 at 4.13.0; compare [4.4.0](https://raw.githubusercontent.com/opencv/opencv/4.4.0/LICENSE) (3-clause BSD) with [4.5.0](https://raw.githubusercontent.com/opencv/opencv/4.5.0/LICENSE) (Apache-2.0). Also [`modules/imgproc/src/segmentation.cpp`](https://github.com/opencv/opencv/blob/4.13.0/modules/imgproc/src/segmentation.cpp) and [`modules/photo/src/npr.cpp`](https://github.com/opencv/opencv/blob/4.13.0/modules/photo/src/npr.cpp). Fetched 2026-09-02.
2. [opencv/opencv_contrib — `LICENSE`](https://github.com/opencv/opencv_contrib/blob/4.13.0/LICENSE) — Apache-2.0 at 4.13.0. Fetched 2026-09-02.
3. [opencv/opencv-python#353 — "Provide wheel without FFmpeg (non-LGPL wheel)"](https://github.com/opencv/opencv-python/issues/353) — open since 2020-06-26.
4. [opencv/opencv-python — `README.md`, branch `4.x`](https://github.com/opencv/opencv-python/blob/4.x/README.md) — the "Licensing" section ("All wheels ship with FFmpeg licensed under the LGPLv2.1"), the `CMAKE_ARGS` build knob, and the `auditwheel`/`delocate` step. Fetched 2026-09-02.
5. [opencv/opencv-python#1260 — "macOS ARM64 wheel 5.0.0.93 bundles GPL-configured FFmpeg (libx264/libx265) — conflicts with README LGPLv2.1 statement"](https://github.com/opencv/opencv-python/issues/1260) — open, filed 2026-08-12, with per-file SHA-256 evidence.
6. [opencv/opencv-python#142 — "OSX FFmpeg can no longer be built without GPL libs"](https://github.com/opencv/opencv-python/issues/142) — filed 2018-11-10, closed 2018-11-25; the origin of the macOS problem.
7. [FFmpeg `configure`, tag `n8.1`](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1/configure) — `EXTERNAL_LIBRARY_GPL_LIST`, `EXTERNAL_LIBRARY_VERSION3_LIST`, `EXTERNAL_LIBRARY_NONFREE_LIST`, and the `die_license_disabled` enforcement. See also companion note [`00_ffmpeg_licence_gates_evidence.md`](00_ffmpeg_licence_gates_evidence.md).
8. [PyAV-Org/pyav-ffmpeg — `patches/ffmpeg.patch`](https://github.com/PyAV-Org/pyav-ffmpeg/blob/main/patches/ffmpeg.patch) — moves `libx264`/`libx265` from FFmpeg's GPL list into its version3 list. Fetched 2026-09-02.
9. [PyAV-Org/pyav-ffmpeg — `README.md`](https://github.com/PyAV-Org/pyav-ffmpeg/blob/main/README.md) — confirms x264/x265 enabled on all platforms; contains no licensing section. Fetched 2026-09-02.
10. [FFmpeg — License and Legal Considerations](https://ffmpeg.org/legal.html) — the project's statement that `--enable-gpl` makes the resulting binary GPL, and `--enable-version3` upgrades to v3.
11. [x264 (VideoLAN)](https://www.videolan.org/developers/x264.html) — GPL-2.0-or-later, with a separate commercial licence from x264 LLC.
12. [x265 (MulticoreWare)](https://www.x265.org/) — GPL-2.0-or-later, with a separate commercial licence.
