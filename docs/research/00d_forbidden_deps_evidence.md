# Evidence: the two forbidden dependencies, verified on disk

*2026-09-02. Verified by the orchestrating session against the packages installed in this machine's ecosystem interpreter (`~/.pyenv/versions/p12`). These are the package's loudest prohibitions, so they get first-hand evidence rather than a citation.*

## Verdict

Both prohibitions are **confirmed**, and the `av` case is worse than the kickoff states. It is not merely that the metadata is wrong — **three layers disagree with each other, and each one individually looks reassuring**:

| layer | what it says | how obtained |
|---|---|---|
| wheel metadata | `License-Expression: BSD-3-Clause` | `pip show av` |
| FFmpeg's own self-report | `LGPL version 3 or later` | `av._core.library_meta['libavcodec']['license']` |
| **what is actually linked** | **`libx264.165.dylib`, `libx265.215.dylib`** — both GPL-2.0-or-later | `otool -L` |

An audit that reads the metadata clears it. An audit that goes one level deeper and asks FFmpeg itself *also* clears it, because `avutil_license()` is computed from the `CONFIG_GPL` build flag rather than from what the linker actually resolved. Only `otool -L` on the shipped dylib tells the truth.

**This is the single best argument in the whole research programme for why `looks` refuses rather than warns, and why its evidence must be binary-level.** A licence check that trusts a declared field is not a check.

*(A caution recorded because it nearly went the other way: a first pass listed `av/.dylibs/` with a glob and read the output — which was truncated before the `x*` entries, since the directory is alphabetical and x sorts last. The apparent conclusion was "av bundles libopenh264, not x264/x265", i.e. that the kickoff was wrong. It took `otool -L` to get it right. Alphabetical truncation is a real way to be confidently wrong about exactly the last-sorting name.)*

## `av` — evidence

```
$ pip show av
Name: av
Version: 16.0.1
License-Expression: BSD-3-Clause

$ python -c "from av._core import library_meta; print(library_meta['libavcodec']['license'])"
LGPL version 3 or later

$ otool -L .../site-packages/av/.dylibs/libavcodec.62.11.100.dylib
	…
	@loader_path/libx264.165.dylib (compatibility version 0.0.0, current version 0.0.0)
	@loader_path/libx265.215.dylib (compatibility version 215.0.0, current version 215.0.0)
	@loader_path/libopenh264.7.dylib …

$ ls .../site-packages/av/.dylibs/ | grep x26
libx264.165.dylib
libx265.215.dylib
```

The recorded build configuration confirms the intent — `--enable-libx264 --enable-libx265` — while notably **not** containing `--enable-gpl`, which is why the self-report says LGPL. FFmpeg's own `configure` places `libx264` and `libx265` in `EXTERNAL_LIBRARY_GPL_LIST` (see [`00_ffmpeg_licence_gates_evidence.md`](00_ffmpeg_licence_gates_evidence.md)), so a stock `configure` would `die` on that combination. However that build was produced, the shipped artifact links both.

The categorical point stands independently of any of this: **`av` is a linked binding, not a shell-out.** It loads libav\* into the calling process. That is a different licence posture from executing a separate binary, and it is the posture `looks` exists to avoid — which is why the prohibition should rest on *linking*, not only on *what today's wheel happens to bundle*. A future av wheel could drop x264 and the prohibition would still hold.

## `imageio-ffmpeg` — evidence

```
$ python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
.../site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1

$ .../ffmpeg-macos-aarch64-v7.1 -version
ffmpeg version 7.1 Copyright (c) 2000-2024 the FFmpeg developers
configuration: --prefix=/Volumes/tempdisk/sw … --enable-gpl --enable-libvmaf …
```

`--enable-gpl` present, `--enable-nonfree` absent. So a **GPL ffmpeg 7.1 binary is sitting in site-packages right now**, shipped by a package whose declared licence is BSD-2-Clause. Confirmed exactly as the kickoff states.

## The consequence for the federation, stated plainly

`burns` depends on `moviepy`, which reaches `imageio-ffmpeg`. So **`pip install burns` already puts that GPL binary on disk.** Executing it is not linking, so the Python code is not infected — but installing it *is* redistribution when `burns` is itself redistributed, and that should be a recorded decision rather than an accident. `looks`' own answer is structural: it declares zero dependencies and shells out to whatever `ffmpeg` is on `PATH`, so it never puts a binary anywhere.

## Version anchor

Everything above is `av` 16.0.1, `imageio-ffmpeg` 0.6.0, on macOS arm64, read 2026-09-02. **A wheel's bundled contents vary by version and by platform**, so this evidence expires. The rule that does not expire is the method: `otool -L` (macOS) / `ldd` or `readelf -d` (Linux) on the shipped shared object, never the metadata and never the library's own licence string.

---

## Postscript: it is three packages, not two — and that makes it a pattern

Research note [`06_licence_tiers.md`](06_licence_tiers.md) found a third instance, which the orchestrating session then verified independently:

```
$ pip show opencv-contrib-python
Name: opencv-contrib-python
Version: 4.13.0.92
License: Apache 2.0

$ ls .../site-packages/cv2/.dylibs/ | grep -E 'libav|x26'
libavcodec.61.19.101.dylib   libavdevice.61.3.100.dylib   libavfilter.10.4.100.dylib
libavformat.61.7.100.dylib   libavutil.59.39.100.dylib    libx264.164.dylib   libx265.215.dylib

$ strings -a .../cv2/.dylibs/libavutil.59.39.100.dylib | grep -m1 -- --enable-shared | tr ' ' '\n' | grep -E '^--enable-(gpl|version3|libx26)'
--enable-gpl
--enable-libx264
--enable-libx265
--enable-version3
```

**`opencv-contrib-python` 4.13.0.92 bundles a GPL-3.0-or-later ffmpeg, under `License: Apache 2.0` metadata.** And this is not a package `looks` merely *could* offer — it is the wheel behind `cv2.pyrMeanShiftFiltering`, which is **stage one of the first look `looks` will ship**.

So: **`av`, `imageio-ffmpeg`, and `opencv-contrib-python` — three of the most obvious media dependencies in Python — all declare permissive licences while shipping GPL binaries.** That is not three coincidences; it is what the packaging ecosystem normally does, because wheel metadata describes the *project's own source* and nobody's tooling looks inside `.dylibs/`.

The distinction that keeps this from being a counsel of despair, and which the tier model must therefore represent: **OpenCV the library really is Apache-2.0, and `pyrMeanShiftFiltering` is pure OpenCV that never calls ffmpeg.** The GPL ffmpeg is there for `cv2.VideoCapture` / `VideoWriter`. So the *algorithm* is clean and the *wheel* conveys GPL — which is exactly why "what licence is this dependency?" is the wrong question and **"what does my declared dependency closure convey, and what does my code actually reach?"** is the right one. A single scalar per package cannot express that; the coupling/reach/conveyance/field-of-use axes in note 06 can.

Practical consequence worth checking before it is stated as advice: whether `opencv-python-headless` avoids the bundled ffmpeg. "Headless" removes the GUI (`highgui`), not video I/O (`videoio`), so it very likely bundles it too — **unverified**, and it must be verified before any documentation recommends it as the clean choice.
