# Is a GLSL/shader backend worth it?

*2026-09-02. Research note for `looks`. Every number below was measured on the machines named in §0 during this session; every command is reproduced verbatim.*

## Verdict

**No shader backend in v1, and probably never as a *backend*. Declare the seam as one keyword argument on the effect's provider — not as a `backend="gpu"` flag — and ship no shader provider until a render host with a real GPU exists.** Three measurements decide it. First, the developer machine's FFmpeg 8.1 has **no programmable GPU path at all** — 3 of its 489 filters are GPU filters and all three are fixed-function VideoToolbox; `libplacebo` is not in the build and reaching it means replacing `ffmpeg` (11 dependencies) with `ffmpeg-full` (47). Second, the fleet's own Linux server *does* have `libplacebo`, and it is **141× slower than the equivalent CPU filter** — 62.14 s versus 0.44 s for 300 frames — because the box's "GPU" is a virtio display device and Vulkan resolves to lavapipe, Mesa's software rasteriser; it exits 0 and produces correct output, so nothing warns you. Third, a GLSL mean-shift really is **19–22× faster than `cv2.pyrMeanShiftFiltering`** as a kernel (8.85 ms versus 198.7 ms at 640×360), but end to end that only takes the Que Calor chain from 13.2 fps to 36.0 fps, because the two FFmpeg halves cost ~12.6 ms/frame regardless — and **the CPU path the project already has beats it at 52.0 fps aggregate**, because processes multiply and a GL context does not. The one genuinely strong argument for shaders is not speed at all but **licence tier**: `moderngl` + `glcontext` are 488 KB of MIT that bundle nothing (tier `PERMISSIVE`), while the wheel behind `cv2.pyrMeanShiftFiltering` is 119 MB whose `.dylibs` contain an FFmpeg built `--enable-gpl --enable-version3 --enable-libx264 --enable-libx265` (tier `COPYLEFT_SHIPPED`, rung 4 — verified here by `strings` on the shipped `libavcodec`). That argument is real, and it still does not justify a backend: it justifies at most one alternative *provider* for one *effect*, which is exactly what the provider seam is for. Meanwhile the GPU that actually pays on this machine today is the **video encode ASIC**, not the shader cores — `h264_videotoolbox` runs 3.3× faster than `libx264 -preset medium` with zero new dependencies — and that lives in the execution layer `looks` deliberately does not own.

---

## 0. What was measured, and on what

| | Developer machine | Fleet server (`tw`) |
|---|---|---|
| CPU | Apple M1 Max, 10 cores (8 P + 2 E) | 2 vCPU, x86-64 |
| OS | macOS 15.7.4 (24G517) | Ubuntu (glibc), kernel per distro |
| FFmpeg | **8.1** (Homebrew), `--enable-gpl --enable-version3 --enable-libx264 --enable-libx265 --enable-videotoolbox` | **6.1.1-3ubuntu5**, `--enable-gpl --enable-opencl --enable-opengl --enable-libplacebo --enable-libglslang` |
| GPU | Apple M1 Max (integrated, unified memory) | **Red Hat Virtio 1.0 GPU** (paravirtual display device) |
| Python | 3.12.12 (pyenv `p12`) | system python3 |
| Key libs | `cv2` 4.13.0 (from `opencv-contrib-python` 4.13.0.92), `numpy` 2.2.6, `moderngl` 5.12.0, `glcontext` 3.0.0, `torch` 2.9.0 | — |

**Load caveat, stated once and honoured throughout.** This machine was shared with other research agents for the whole session; `loadavg` ranged from 9 to 126 on a 10-core box. Every timing below records the `loadavg` at which it was taken, and where a single-shot number could mislead the estimator is **min-of-N** (the uncontended cost) rather than the mean. The one comparison that matters most — the four end-to-end pipelines in §4.3 — was run **back to back in one process** so the four share as much of the load condition as they can.

---

## 1. FFmpeg's own GPU paths, as of the builds in front of me

### 1.1 The developer machine has none

```
$ ffmpeg -hide_banner -filters | grep -iE 'placebo|opencl|vulkan|videotoolbox|_cuda|_qsv'
 .. scale_vt          V->V       Scale Videotoolbox frames
 .. transpose_vt      V->V       Transpose Videotoolbox frames
 T. yadif_videotoolbox V->V       YADIF for VideoToolbox frames using Metal compute

$ ffmpeg -hide_banner -filters | wc -l
     489

$ ffmpeg -hide_banner -h filter=libplacebo
Unknown filter 'libplacebo'.

$ ffmpeg -hide_banner -hwaccels
Hardware acceleration methods:
videotoolbox
```

Three GPU filters out of 489, and **none of them is programmable** — `scale_vt` takes `w`/`h`/`color_matrix`/`color_primaries`/`color_transfer` and nothing else. There is no OpenCL, no Vulkan, no libplacebo. This is the ordinary `brew install ffmpeg`, i.e. what every caller of `looks` on macOS will have [1][2].

Getting `libplacebo` on macOS means the `ffmpeg-full` formula, which is **keg-only** (it does not link into `/opt/homebrew/bin`, so `looks` would have to find it by an explicit path) and carries **47 direct dependencies** against `ffmpeg`'s 11 [2][3]:

```
$ brew deps ffmpeg | tr '\n' ' '
ca-certificates dav1d lame libvmaf libvpx openssl@3 opus sdl2 svt-av1 x264 x265

$ brew deps ffmpeg-full | grep -iE 'placebo|vulkan|shaderc|moltenvk'
libplacebo
shaderc
vulkan-headers
vulkan-loader
```

Note what is *not* in that list: `molten-vk`. Homebrew's `mpv` formula does depend on `molten-vk` alongside `libplacebo` and `vulkan-loader` [14], which is how mpv reaches libplacebo on macOS; whether `ffmpeg-full`'s libplacebo initialises a Vulkan device on macOS without it is **unverified** — I did not install `ffmpeg-full` (a ~100-package recursive closure) to find out.

**Licence.** `libplacebo` is **LGPL-2.1-or-later**: Homebrew's formula declares `License: LGPL-2.1-or-later` [4] and the upstream `LICENSE` is verbatim *"GNU LESSER GENERAL PUBLIC LICENSE / Version 2.1, February 1999"* [5]. That is worth stating precisely because **it changes nothing for `looks`**. libplacebo is reached *inside* an FFmpeg binary we shell out to, so the relationship is `Coupling.SUBPROCESS` + `Conveyance.FINDS`, and the governing term is the *binary's* licence, which is `GPL-3.0-or-later` for both Homebrew formulae [2][3]. On the ladder in the sibling licence note that is tier `COPYLEFT_TOOL` [18] — **exactly the tier plain FFmpeg is already at**. A libplacebo path buys no tier movement whatsoever. If anyone reaches for it hoping the LGPL badge lowers the ceiling, it does not.

### 1.2 The server has all of them, and they are catastrophically slow

This is the surprise of the investigation, and it runs the opposite way to intuition. The Ubuntu FFmpeg 6.1.1 on the fleet's own server carries **35** matching filters, including `libplacebo`, `program_opencl`, `openclsrc`, and the whole `*_vulkan` family:

```
$ ssh tw 'ffmpeg -hide_banner -filters | grep -iE "placebo|opencl|vulkan"'
 ..C libplacebo        N->V       Apply various GPU filters from libplacebo
 ... program_opencl    N->V       Filter video using an OpenCL program
 ... nlmeans_opencl    V->V       Non-local means denoiser through OpenCL
 ... nlmeans_vulkan    V->V       Non-local means denoiser (Vulkan)
 ... deshake_opencl    V->V       Feature-point based video stabilization filter
 ... convolution_opencl V->V      Apply convolution mask to input video
 ... tonemap_opencl    V->V       Perform HDR to SDR conversion with tonemapping.
 ... xfade_vulkan      VV->V      Cross fade one video with another video.
 [ … 27 more … ]

$ ssh tw 'ffmpeg -hide_banner -hwaccels'
vdpau cuda vaapi qsv drm opencl vulkan
```

But the hardware behind them is a lie of omission:

```
$ ssh tw 'lspci | grep -iE "vga|3d|display"'
00:01.0 VGA compatible controller: Red Hat, Inc. Virtio 1.0 GPU (rev 01)

$ ssh tw 'ls /etc/OpenCL/vendors'
ls: cannot access '/etc/OpenCL/vendors': No such file or directory

$ ssh tw 'ls /usr/share/vulkan/icd.d'
asahi_icd.json  gfxstream_vk_icd.json  intel_hasvk_icd.json  intel_icd.json
lvp_icd.json    nouveau_icd.json       radeon_icd.json       virtio_icd.json
```

No OpenCL ICD is installed at all, so `program_opencl` cannot initialise a platform (**unverified directly** — I did not run it, but with no vendor file there is no platform to find). And the only Vulkan implementation that can serve a virtio display device here is `lvp_icd.json` — **lavapipe**, Mesa's *software* Vulkan driver, which runs on the CPU.

The first attempt did not merely run slowly; it corrupted the heap:

```
$ ssh tw 'ffmpeg -init_hw_device vulkan -f lavfi -i testsrc2=size=1280x720:rate=30 \
    -frames:v 30 -vf "format=yuv420p,hwupload,libplacebo=w=1280:h=720,hwdownload,format=yuv420p" -f null -'
Failed to create semaphore: VK_ERROR_INVALID_EXTERNAL_HANDLE
free(): double free detected in tcache 2
```

Letting `libplacebo` manage its own upload works. And then:

```
$ ssh tw '/usr/bin/time -f "%e s wall" ffmpeg -v error -benchmark -init_hw_device vulkan \
    -f lavfi -i testsrc2=size=1280x720:rate=30 -frames:v 300 \
    -vf "libplacebo=custom_shader_path=/tmp/test.hook" -f null -'
62.14 s wall

  … same, -vf "libplacebo" (no custom shader)      55.44 s wall
  … same, CPU filter -vf "negate"                   0.44 s wall
```

| pipeline, 300 frames of 1280×720 `testsrc2` → `null` | wall | fps |
|---|---:|---:|
| `libplacebo` + a custom GLSL shader | 62.14 s | **4.8** |
| `libplacebo`, no shader (scale/passthrough only) | 55.44 s | **5.4** |
| CPU `negate` | 0.44 s | **682** |

**The GPU filter is 141× slower than the CPU filter, and exits 0.** This is the single most important fact in this note. A shader backend that dispatches on "is `libplacebo` present?" would, on this fleet's own deploy target, silently turn a 5-second job into a 12-minute one and report success. Availability is not capability, and FFmpeg's filter list cannot tell them apart.

---

## 2. The mpv / libplacebo `.hook` shader ecosystem

### 2.1 It genuinely works through FFmpeg — verified, not assumed

FFmpeg's `libplacebo` filter exposes two options for user shaders, and the help text names the format outright [6]:

```
$ ssh tw 'ffmpeg -hide_banner -h filter=libplacebo | grep -i shader'
   custom_shader_path <string>     ..FV....... Path to custom user shader (mpv .hook format)
   custom_shader_bin <binary>      ..FV....... Custom user shader as binary (mpv .hook format)
```

Accepting an option is not applying it, so I proved application rather than asserting it. A minimal inverting hook:

```glsl
//!HOOK MAIN
//!BIND HOOKED
//!DESC simple invert
vec4 hook() { vec4 c = HOOKED_tex(HOOKED_pos); return vec4(1.0 - c.rgb, c.a); }
```

rendered with and without, then compared pixel-wise:

```
mean |on-off| = 240.69 /255
is it an inversion? mean |on - (255-off)| = 0.28
identical? False
```

An exact inversion up to 8-bit rounding. **mpv `.hook` shaders are usable from FFmpeg, not only from mpv.**

And with a real, unmodified community shader — Anime4K's CNN ×2 (small) upscaler, downloaded straight from the repository and not edited:

```
$ ssh tw 'ffmpeg -init_hw_device vulkan -f lavfi -i testsrc2=size=640x360:rate=30 \
    -frames:v 30 -vf "libplacebo=w=1280:h=720:custom_shader_path=/tmp/a4k.glsl" -f null -'
Stream #0:0: Video: wrapped_avframe, yuv420p(progressive), 1280x720 …
frame=   30 fps=3.7 … speed=0.12x
8.30 s wall
```

Correct 640×360 → 1280×720 output, at **3.7 fps / 0.12× realtime** on lavapipe. Architecturally proven; operationally useless on that host.

### 2.2 The licences split the ecosystem cleanly, and one of them is a refusal

| Shader family | Licence | Verified how | Tier if `looks` **vendors** it (`CONVEYS`) |
|---|---|---|---|
| **Anime4K** (bloc97) | **MIT** | `LICENSE` reads *"MIT License … Copyright … bloc97 (2019)"* [7]; **and** every `.glsl` file carries the full MIT text in its own header — checked on `Anime4K_Upscale_CNN_x2_S.glsl` | `PERMISSIVE` |
| **mpv-prescalers** — RAVU, nnedi3 (bjin) | **LGPL-3.0** | README, verbatim: *"Shaders in this repo are licensed under terms of LGPLv3."* [8] | `COPYLEFT_SHIPPED` |
| **FSRCNNX** (igv) | **ambiguous** — the hosting repo's GitHub label reads *"GPL-3.0, MIT licenses found"* and the `.glsl` files ship as release assets of it, with nothing saying which applies [9] | GitHub licence label | `UNKNOWN` → **refusal** |

Two design consequences, both concrete and both actionable today.

**First, the conveyance axis decides this, not the reach axis.** Reading a shader file from the user's disk at runtime is `Conveyance.FINDS`; putting one in the `looks` wheel is `Conveyance.CONVEYS` [18]. So the rule is: **`looks` may vendor Anime4K's shaders and may not vendor RAVU's or FSRCNNX's** — and for FSRCNNX it may not even offer them by name, because unknown is a refusal, not a warning.

**Second — and this is why none of it matters much — these shaders do not do what `looks` wants.** Anime4K restores and upscales anime; RAVU and FSRCNNX are super-resolution prescalers. They are *quality-preservation* tools for playback. `looks` is a *stylization* facade: the Que Calor look flattens and re-palettes, deliberately destroying detail. The one ecosystem that is licence-clean is aimed at the opposite problem. There is no off-the-shelf `.hook` library of stylization effects waiting to be adopted.

---

## 3. Standalone Python GPU options

### 3.1 `moderngl` works headless on macOS today — verified

`moderngl` 5.12.0 and `glcontext` 3.0.0 are **already installed** in the ecosystem environment. A standalone (windowless) context comes up on the first try:

```
$ python -c "import moderngl; ctx = moderngl.create_standalone_context(); print(ctx.info['GL_VERSION'], '|', ctx.info['GL_RENDERER'])"
4.1 Metal - 89.4 | Apple M1 Max
```

`GL_MAX_TEXTURE_SIZE` is 16384, so 4K and 8K frames fit. But:

```
$ python -c "... ctx.compute_shader('#version 430 …')"
COMPUTE SHADER: UNAVAILABLE -> Error cannot create shader
```

**No compute shaders.** `ctx.version_code` is 410; GL compute shaders require 4.3. macOS is capped at OpenGL 4.1 through Apple's Metal-backed shim, and Apple deprecated OpenGL in macOS 10.14 [12]. So a macOS shader backend is **fragment-shader-only, on a deprecated API that has been frozen since 2018 and could be removed in any macOS release.** That is a load-bearing risk for a v1 backend, and a perfectly acceptable one for an opt-in provider that a caller chooses.

### 3.2 The dependency closure is the best thing about it

```
$ du -sh moderngl glcontext cv2 torch av imageio_ffmpeg
408K   moderngl
 80K   glcontext
119M   cv2
385M   torch
 54M   av
 47M   imageio_ffmpeg

$ otool -L moderngl/mgl.cpython-312-darwin.so
    /usr/lib/libc++.1.dylib
    /usr/lib/libSystem.B.dylib
$ otool -L glcontext/darwin.cpython-312-darwin.so
    /System/Library/Frameworks/OpenGL.framework/Versions/A/OpenGL
    /usr/lib/libc++.1.dylib
    /usr/lib/libSystem.B.dylib
```

**488 KB total, both MIT [10][11], linking nothing but the OS.** `moderngl`'s only declared dependency is `glcontext>=3.0.0`; `glcontext` declares none. Compare the incumbent:

```
$ ls site-packages/cv2/.dylibs/ | grep -iE 'x264|x265'
libx264.164.dylib
libx265.215.dylib

$ strings site-packages/cv2/.dylibs/libavcodec.61.19.101.dylib | grep -- '--enable-gpl'
--prefix=/opt/homebrew/Cellar/ffmpeg/7.1.1_3 … --enable-version3 … --enable-gpl …
--enable-libx264 --enable-libx265 …
```

The wheel providing `cv2.pyrMeanShiftFiltering` — stage one of the first look `looks` will ship — **redistributes a Homebrew FFmpeg 7.1.1 built `--enable-gpl --enable-version3` with x264 and x265 inside it.** This independently confirms, from the binary rather than from metadata, the finding in the sibling licence-tier note [18]. On the ladder that provider is `COPYLEFT_SHIPPED` (rung 4); a `moderngl` provider for the same effect is `PERMISSIVE` (rung 1). **This is the strongest argument in favour of a shader path anywhere in this note, and it is a licence argument, not a performance one.**

On the Linux side the GL provider would be Mesa, whose core is MIT with some components under the SGI Free Software License B — permissive either way [13]. But a headless Linux standalone context needs EGL, and with no GPU it falls to Mesa's `llvmpipe` software rasteriser: the same shape of trap as the lavapipe measurement in §1.2. **Unverified on this fleet's server** — `moderngl` is not installed there and I did not install it — but there is no reason to expect a different outcome from the one measured for lavapipe.

### 3.3 The rest of the field

| Library | Latest | Licence | Verdict for `looks` |
|---|---|---|---|
| `moderngl` + `glcontext` | 5.12.0 / 3.0.0 | **MIT** [10][11] | The pick, if ever. 488 KB, bundles nothing, headless-verified on macOS |
| `wgpu` (wgpu-py) | 0.32.0 | BSD-2 | The *modern* answer — Metal/Vulkan/DX12, compute shaders on macOS, no deprecated API. Pulls `cffi`, `rendercanvas`, `rubicon-objc`. **Unverified** here (not installed); the serious alternative if this is ever revisited |
| `taichi` | 1.7.4 | Apache-2.0 | Kernel-JIT, not a shader runtime; heavy |
| `vispy` | 0.16.2 | BSD-3 | Visualisation toolkit; wrong altitude |
| `PyOpenGL` | 3.1.10 | BSD | Raw bindings; `moderngl` is strictly better ergonomics for the same thing |
| `glumpy` | 1.2.1 | BSD | Requires `triangle` (declared LGPL-3.0). The underlying Shewchuk C library is widely described as forbidding commercial use without permission — **unverified**, I could not retrieve its terms. Do not adopt without checking |
| `pyopencl` | 2026.1.4 | MIT | No OpenCL on macOS worth having (Apple deprecated it alongside OpenGL); no ICD on the server |
| ISF / ShaderToy runners | — | — | No maintained Python runtime found. **Unverified** — I searched PyPI metadata only, not exhaustively |

**And a measured negative on the obvious alternative.** `torch` 2.9.0 is installed and `torch.backends.mps.is_available()` is `True`, so "just use MPS" looks like a free GPU. It is not, for this kind of kernel. A mean-shift step expressed as `unfold` + masked mean over a 25×25 window at 640×360:

```
torch/MPS mean-shift-ish, 640x360, 25x25 window, 5 iters: min 1012.8 ms -> 1.0 fps
  compare: GLSL fragment shader 8.85 ms (113 fps) | cv2 CPU 198.7 ms (5.0 fps)
```

**1012.8 ms — five times slower than `cv2` on the CPU and 114× slower than the fragment shader**, because `unfold` materialises a 625×-inflated tensor and the operation becomes memory-bound. "GPU" is not one thing. A windowed neighbourhood kernel wants a fragment shader (or a real compute kernel); expressing it as tensor ops is the wrong shape and costs a 385 MB dependency to be slower than the status quo.

---

## 4. The honest comparison: what is actually slow, and what would fix it

### 4.1 How slow the shipped chain is

The Que Calor V2 stylizer (`~/Downloads/que_calor/work/style/render_v2c.py`) decodes with FFmpeg, runs `cv2.pyrMeanShiftFiltering` on piped BGR24 frames, and pipes back into an FFmpeg doing `lut3d` + `lutrgb` posterise + `libx264 -crf 16 -preset medium`. The source material records the *design* decisions in detail but **no wall-clock figures** — so these are new measurements, not recovered ones.

The flatten step alone, at 1280×720, min-of-N (loadavg 12.3):

| configuration | min | median | fps/core |
|---|---:|---:|---:|
| mean-shift FULL 1280×720, `sp=12 sr=60` | 136.5 ms | 500.8 ms | 7.3 |
| mean-shift 0.75 → 960×540, `sp=12 sr=40` **[shipped, clip c03]** | 181.9 ms | 577.2 ms | 5.5 |
| mean-shift 0.50 → 640×360, `sp=12 sr=60` **[shipped, c01/c02]** | 60.1 ms | 200.8 ms | 16.6 |
| mean-shift 0.50 → 640×360, `sp=12 sr=30` | 173.5 ms | 399.7 ms | 5.8 |
| mean-shift 0.50 → 640×360, `sp=8 sr=60` | 29.0 ms | 89.5 ms | 34.5 |
| resize round-trip only, no mean-shift | 2.6 ms | 2.8 ms | 387 |

**A finding `looks` needs for its cost model, because it runs backwards from intuition: `sr` dominates the cost *inversely*.** At half resolution, `sr=60` costs 60.1 ms and `sr=30` costs 173.5 ms — a *narrower* colour radius is nearly 3× *more* expensive, because narrower windows converge more slowly. `sp` is roughly quadratic (`sp=8` → 29.0 ms, `sp=12` → 60.1 ms). The practical consequence: **the shipped `c03` setting (0.75 scale, `sr=40`) is the most expensive of the three shipped configurations, not the cheapest** — the per-source tuning that fixed the sharpness mismatch also tripled that clip's cost. Any `Effect.estimate()` that models mean-shift as "cost ∝ pixels × radius" will be wrong in both directions.

Also worth noting: `cv2.setNumThreads(1)` is a **no-op** on this build — OpenCV reports `Parallel framework: GCD`, and `getNumThreads()` stays at 10 after the call. There is no way to pin OpenCV to one core here, which matters when reasoning about a process pool.

### 4.2 Would an all-FFmpeg flatten fix it? Faster, yes. Correct, no.

The tempting move is to drop OpenCV entirely and approximate the flatten with an FFmpeg-native filter. It is **6× faster and wrong**, and I can put a number on the wrongness.

The metric: over six frames, the fraction of the source's **strong-edge** gradient energy (top 3% of Sobel magnitude — object boundaries) that survives, over the fraction of its **weak-edge** energy (60th–85th percentile — texture) that survives. A flattener that does what mean-shift is *for* keeps boundaries and destroys texture, so the ratio should be well above 1. `ncol@90%` is the number of 5-bit-quantised colours holding 90% of the pixel mass; `Lap` is Laplacian variance (apparent sharpness).

| | Lap | ncol@90% | strong | weak | **ratio** |
|---|---:|---:|---:|---:|---:|
| SOURCE (no effect) | 23.7 | 390 | 1.000 | 1.000 | 1.000 |
| **SHIPPED `cv2` mean-shift chain** | 41.9 | 86 | 0.731 | 0.325 | **2.251** |
| all-FFmpeg `bilateral=sigmaS=15:sigmaR=0.35` @0.5 | 18.8 | 80 | 0.301 | 0.391 | **0.811** |

`mean |shipped − allffmpeg| = 7.47/255`; only 39.1% of pixels agree within ±4.

**The obvious FFmpeg substitution inverts the property that matters.** It retains *less* boundary energy (0.301) than texture energy (0.391) — it smooths *across* object boundaries, which is precisely the `edgePreservingFilter` failure mode the Que Calor work rejected on visual grounds. And its Laplacian, 18.8, is *below the source's own 23.7*: it made the output softer than the input, which is the "mushiest thing on screen" defect the per-source tuning existed to fix. Two colour-count numbers that look almost identical (80 versus 86) conceal a completely different image.

The full candidate sweep, with `lut3d` + posterise held constant so only the flattener varies (300 frames, single ffmpeg process, `libx264 -crf 16 -preset medium`):

| candidate | fps | Lap | strong | weak | ratio |
|---|---:|---:|---:|---:|---:|
| `cv2` pyrMeanShift 0.5/12/60 **[target]** | 13.2 | 41.9 | 0.731 | 0.325 | **2.251** |
| `bilateral sS=15 sR=0.35` @0.5 | 78.9 | 15.4 | 0.298 | 0.389 | 0.805 |
| `bilateral sS=30 sR=0.10` full | 49.3 | 32.6 | 0.728 | 0.427 | 1.682 |
| `bilateral sS=60 sR=0.05` full | 53.4 | 48.3 | 0.987 | 0.501 | 2.003 |
| `smartblur lr=5 ls=1 lt=30` @0.5 (GPL) | 58.8 | 25.6 | 0.348 | 0.603 | 0.551 |
| `nlmeans s=10 p=7 r=15` @0.5 | 8.5 | 24.3 | 0.685 | 0.549 | 1.293 |
| `sab` @0.5 (GPL) | 49.5 | 40.3 | 0.950 | 0.853 | 1.077 |
| `spp=6` full (GPL) | 64.2 | 59.6 | 1.067 | 0.946 | 1.080 |
| `pp7=64` full (GPL) | 28.8 | 48.9 | 0.682 | 0.787 | 0.853 |
| `hqdn3d=8:6:12:12` full (GPL) | 58.3 | 52.7 | 1.052 | 0.762 | 1.357 |
| `dctdnoiz sigma=20` full | 8.5 | 36.6 | 0.967 | 0.766 | 1.267 |
| **no flatten** (LUT + posterise only) | 62.4 | 59.6 | 1.067 | 0.946 | 1.080 |

Two readings that carry weight. **`spp=6` scores byte-for-byte identically to "no flatten" on all four numbers** — it did nothing at that setting, which is the metric's own calibration check and shows the numbers are not noise. And the **"no flatten" row's Laplacian of 59.6 against the source's 23.7** confirms, quantitatively, the observation recorded in the Que Calor material: LUT-plus-posterise *adds* apparent sharpness by manufacturing hard edges between flat regions. The flattener's job is therefore to pull that back down — the shipped chain lands at 41.9 — which is why a "flattener" that scores *above* 59.6 has not flattened at all.

A tuned sweep gets much closer than the naive one:

| candidate | fps | Lap | strong | weak | ratio |
|---|---:|---:|---:|---:|---:|
| `bilateral sS=60 sR=0.05` @0.5 | 63.2 | 32.7 | 0.884 | 0.498 | 1.834 |
| `bilateral sS=60 sR=0.05` ×2 full | 51.3 | 75.3 | 0.842 | 0.339 | 2.763 |
| `bilateral sS=60 sR=0.05` ×3 full | 44.3 | 119.5 | 0.752 | 0.264 | 3.218 |
| `bilateral sS=120 sR=0.05` full | 58.3 | 50.9 | 0.971 | 0.488 | 2.045 |
| `bilateral sS=120 sR=0.08` full | 57.6 | 42.1 | 0.740 | 0.413 | 1.893 |
| **`bilateral sS=60 sR=0.05` ×2 @0.75** | **58.1** | 51.4 | 0.796 | 0.338 | **2.593** |

The best FFmpeg-native candidate found — two `bilateral` passes at 0.75 scale — reaches 0.796/0.338 (ratio 2.593) at 58.1 fps, **4.4× the shipped chain's throughput with comparable edge selectivity**. But its Laplacian is 51.4 against the target's 41.9, still above the 59.6 no-flatten line's neighbourhood: it is producing many small quantised patches rather than a few large flat regions, which is a different image even where the gradient statistics agree. **Whether it is visually acceptable is unverified** — I ran no side-by-side human comparison, and the Que Calor material is explicit that this class of decision was made visually first and measured second.

So: an all-FFmpeg flatten is a *live option worth a look-side experiment*, not a settled substitution, and it is emphatically **not** something a shader backend is needed to reach.

### 4.3 The decisive number: four pipelines, back to back

300 frames of the real Que Calor render at 1280×720, identical `libx264 -crf 16 -preset medium` on every row, run in one process one after another:

```
M1 Max, macOS 15.7.4, cv2 4.13.0, ffmpeg 8.1, moderngl 5.12.0

  cv2 mean-shift 0.5/12/60, 1 process [SHIPPED]      300f  22.81s ->   13.2 fps =  0.44x rt   (loadavg  30.2)
  cv2 mean-shift, 9 processes (aggregate)           2700f  51.93s ->   52.0 fps =  1.73x rt   (loadavg  23.9)
  GLSL mean-shift shader, 1 GL context               300f   8.33s ->   36.0 fps =  1.20x rt   (loadavg 125.6)
  all-ffmpeg bilateral x2 @0.75 (DIFFERENT look)     300f   4.32s ->   69.4 fps =  2.31x rt   (loadavg 108.1)
```

and the CPU path's scaling, measured separately (`max(1, cpu_count()-1)` = 9 is what the shipped renderer uses):

| workers | frames | wall | aggregate fps |
|---:|---:|---:|---:|
| 1 | 300 | 22.95 s | 13.1 |
| 3 | 900 | 28.29 s | 31.8 |
| 6 | 1800 | 39.93 s | 45.1 |
| 9 | 2700 | 51.96 s | 52.0 |

**The GPU shader kernel is 19–22× faster than `cv2`'s, and the GPU pipeline still loses.** In isolation the shader is emphatic — 8.85 ms against 198.7 ms at 640×360 (22.5×), 26.5 ms against 502.9 ms at 1280×720 (19.0×). But the pipeline around it does not shrink: the fixed GL transfer cost is 1.23 ms upload + 1.56 ms readback = **2.79 ms/frame**, a hard ~358 fps ceiling for any Python-side GL backend at 720p, and the two FFmpeg halves cost ~12.6 ms/frame no matter what sits between them. So the end-to-end gain is 13.2 → 36.0 fps, **2.7×, not 20×** — and 36.0 fps is *below* the 52.0 fps the existing 9-process CPU path already delivers, because processes multiply and one GL context does not.

**Two caveats, both against my own conclusion, stated because the load confound is real.** The GPU row was measured at loadavg 125.6 against the 9-worker CPU row's 23.9 — roughly five times the contention — and the GPU's FFmpeg halves were starved by it. On an idle machine the GPU row would be higher, and it is plausible the ordering flips. But the *structural* argument does not depend on the load: the CPU path scales with cores and the GPU path does not, so on any machine with enough cores the CPU aggregate wins, and the M1 Max has eight performance cores. Concretely, the real Que Calor job — 157.13 s at 30 fps = 4714 frames — is **about 91 seconds** at the measured 52.0 fps aggregate. **A shader backend's entire prize is roughly one minute of a two-and-a-half-minute video's stylize pass.**

### 4.4 The GPU that actually pays here is the encode ASIC

Same 300 frames, `lut3d` + posterise held constant, only the encoder varying:

| encoder | wall | fps | output |
|---|---:|---:|---:|
| `libx264 -crf 16 -preset medium` **[shipped]** | 5.15 s | 58.3 | 15.1 MB |
| `libx264 -crf 16 -preset veryfast` | 2.93 s | 102.4 | 14.4 MB |
| **`h264_videotoolbox -q:v 60`** | **1.54 s** | **194.8** | 13.3 MB |
| `hevc_videotoolbox -q:v 60` | 1.58 s | 189.9 | 7.6 MB |

**3.3× on the encode, with zero new dependencies, using hardware that is already in the build** — and it moves the licence tier in the right direction too, since `libx264` is a GPL-only external library while the VideoToolbox encoders are not [19]. Two things follow. It is more speed than the shader backend delivers, for none of the cost. And it is **not `looks`' to take**: the kickoff is explicit that execution and muxing stay out, and an encoder choice is squarely execution. The right move is to record it here so the caller (`muvid`'s `assemble.py`, or `mixing`) can act on it, and to note that a `looks` **cost model** should know the difference even though `looks` never makes the call.

---

## 5. Verdict, and the shape of the seam

### 5.1 The decision

**Never, as a `backend`. Later, as a `provider`, and only under a condition that does not hold today.**

The distinction is not pedantry, it is the architecture. On the evidence there is no such thing as "the GPU backend": there are three unrelated mechanisms with different licences, different availability, and different failure modes — FFmpeg-plus-libplacebo (subprocess, `COPYLEFT_TOOL`, absent on macOS, catastrophic on a GPU-less Linux box), in-process GLSL via `moderngl` (`PERMISSIVE`, 488 KB, macOS-verified, fragment-only, deprecated API), and the hardware video codec (already present, 3.3×, someone else's layer). A single `backend="gpu"` flag would have to mean all three, and would be a lie on every machine. So:

- **The seam is `provider` on the effect**, resolved per-effect against the machine, defaulting to the strongest implementation needing no new dependency — which for `flatten` today is `cv2`. That is one keyword argument, and it is the same seam the licence work already needs: note 06's decision procedure already resolves a *provider* to a *tier*, and refuses when the resolved tier exceeds the ceiling [18]. **A shader provider is one more row in a table that must exist anyway.** No new abstraction is owed.
- **Ship no shader provider in v1.** Not a stub, not a stub raising `NotImplementedError`, not a `backend` enum with one unimplemented member. The kickoff's rule is that a declared seam gets the strongest no-new-dependency implementation, and for every effect `looks` will ship first, that is CPU.
- **Record the three mechanisms in the licence ledger anyway**, because the ledger is a table of observations and these are observations. `ffmpeg+libplacebo` → `COPYLEFT_TOOL`, `moderngl` → `PERMISSIVE`, Anime4K → `PERMISSIVE` if vendored, RAVU → `COPYLEFT_SHIPPED` if vendored, FSRCNNX → `UNKNOWN` → refuse. A row costs nothing and prevents a future session from re-deriving §2.2.

### 5.2 What would have to be true to change the answer

Precisely three things. Any one of them alone is insufficient; the first is necessary.

1. **A render host with a real GPU.** Not "a machine that reports Vulkan support" — the server reports seven hwaccel types and delivers 4.8 fps. The test is the one in §1.2, re-run there: `libplacebo` throughput against the equivalent CPU filter. If the ratio is not comfortably above 1, there is no GPU, whatever `ffmpeg -hwaccels` says. And the bar for adopting it is the **9-process CPU aggregate**, not the single-process number — 52.0 fps on this machine — because that is what a shader path has to beat to be worth having.

2. **An effect whose CPU cost is at least ~10× the pipeline's fixed FFmpeg cost, with no FFmpeg-native equivalent.** The arithmetic is in §4.3: the decode/LUT/posterise/encode halves are ~12.6 ms/frame, so an effect costing 60 ms (mean-shift at half resolution) yields 2.7× end to end and one costing 600 ms would yield roughly 8×. Full-resolution mean-shift (502.9 ms/frame) already crosses that line, and so does anything at 4K. If `looks` acquires a look that needs full-resolution flattening, re-open this.

3. **A caller who needs tier `PERMISSIVE` for a stylization effect and refuses `COPYLEFT_SHIPPED`.** This is the argument that is genuinely alive today, since the `cv2` provider is rung 4 by its own bundled binaries (§3.2), and a `moderngl`+GLSL provider is the only measured route to rung 1 for a flatten. It justifies **one provider for one effect**, added when a caller actually asks — not a backend, and not speculatively. If it is ever built, `wgpu` (BSD-2, real compute shaders, no deprecated API) deserves an evaluation against `moderngl` first; that comparison is **unverified** here.

### 5.3 One methodological warning, earned the hard way

**My first GLSL mean-shift was a no-op and reported a 48× speedup.** The shader passed `sr` pre-divided by 255 into a body that multiplied by 255, so the colour-window test never admitted a neighbour, the window mean was always the centre pixel, and the output was **byte-identical to the input**. Everything about the benchmark looked healthy — the context came up, the shader compiled, the frames rendered, the timings were stable and plausible. It was caught only by an explicit `(out == src).all()` check bolted on afterwards, and the corrected shader is 3.4× slower than the fake one.

If `looks` ever grows a shader provider, its test suite must assert that **the output differs from the input** and that it **agrees with the reference implementation within a stated tolerance** — the corrected shader lands at `mean |GPU − cv2| = 4.73/255` with 39.8k unique colours against `cv2`'s 45.1k, which is close enough to call the same operation and far enough to require the tolerance be stated. A shader benchmark without a no-op guard is worth nothing, and a fast wrong answer is the easiest thing in graphics to produce.

---

## REFERENCES

[1] [FFmpeg](https://ffmpeg.org/) — version 8.1 (Homebrew, macOS, 2026-09-02) and 6.1.1-3ubuntu5 (Ubuntu server). All filter lists, `-h filter=…` output and timings quoted here are from these two builds, run during this session.

[2] [Homebrew formula: `ffmpeg`](https://github.com/Homebrew/homebrew-core/blob/HEAD/Formula/f/ffmpeg.rb) — `brew info ffmpeg` on 2026-09-02: stable 9.0.1, installed 8.1_1, `License: GPL-3.0-or-later`, 11 required dependencies, `libplacebo` not among them.

[3] [Homebrew formula: `ffmpeg-full`](https://github.com/Homebrew/homebrew-core/blob/HEAD/Formula/f/ffmpeg-full.rb) — `brew info ffmpeg-full` on 2026-09-02: stable 9.0.1, keg-only, `License: GPL-3.0-or-later`, 47 required dependencies including `libplacebo`, `shaderc`, `vulkan-headers`, `vulkan-loader`.

[4] [Homebrew formula: `libplacebo`](https://github.com/Homebrew/homebrew-core/blob/HEAD/Formula/lib/libplacebo.rb) — `brew info libplacebo` on 2026-09-02: stable 7.360.1, `License: LGPL-2.1-or-later`, dependencies `little-cms2`, `shaderc`, `vulkan-loader`.

[5] [libplacebo `LICENSE`](https://raw.githubusercontent.com/haasn/libplacebo/master/LICENSE) — fetched 2026-09-02: "GNU LESSER GENERAL PUBLIC LICENSE / Version 2.1, February 1999". (The canonical repository at code.videolan.org was behind an anti-bot challenge; the GitHub mirror was used.)

[6] [FFmpeg filters documentation — `libplacebo`](https://ffmpeg.org/ffmpeg-filters.html#libplacebo) — the `custom_shader_path` / `custom_shader_bin` options were read from `ffmpeg -h filter=libplacebo` on the FFmpeg 6.1.1 server build, quoted verbatim in §2.1.

[7] [Anime4K (bloc97)](https://github.com/bloc97/Anime4K) — `LICENSE` fetched 2026-09-02: MIT License, Copyright bloc97 (2019). The MIT text is additionally embedded in the header of each `.glsl` file, checked on `glsl/Upscale/Anime4K_Upscale_CNN_x2_S.glsl`.

[8] [bjin/mpv-prescalers](https://github.com/bjin/mpv-prescalers) — README fetched 2026-09-02, verbatim: "Shaders in this repo are licensed under terms of LGPLv3." Covers RAVU and nnedi3.

[9] [igv/FSRCNN-TensorFlow](https://github.com/igv/FSRCNN-TensorFlow) — GitHub licence label read 2026-09-02: "GPL-3.0, MIT licenses found". The FSRCNNX `.glsl` shaders ship as release assets of this repository; **which of the two licences governs the shader files is not stated**, hence `UNKNOWN`.

[10] [moderngl](https://github.com/moderngl/moderngl) — version 5.12.0 installed locally; `License: MIT` from the installed distribution metadata, verified 2026-09-02. Wheel is a single 0.24 MB `.so`; sole dependency `glcontext>=3.0.0`.

[11] [glcontext](https://github.com/moderngl/glcontext) — version 3.0.0 installed locally; `License: MIT`; no dependencies; the Darwin backend links only `/System/Library/Frameworks/OpenGL.framework`, `libc++` and `libSystem`.

[12] [macOS Mojave 10.14 release notes](https://developer.apple.com/documentation/macos-release-notes/macos-mojave-10_14-release-notes) — OpenGL and OpenCL deprecated on Apple platforms from macOS 10.14 (2018). **The exact deprecation sentence could not be retrieved** (the page requires JavaScript); the deprecation itself is corroborated directly here by `GL_VERSION` reporting `4.1 Metal - 89.4` on macOS 15.7.4 and by compute-shader creation failing.

[13] [Mesa 3D licensing](https://docs.mesa3d.org/license.html) — fetched 2026-09-02: "The core Mesa library is licensed according to the terms of the MIT license"; individual files may differ (e.g. GLX client code under SGI Free Software License B). Permissive throughout.

[14] [Homebrew formula: `mpv`](https://github.com/Homebrew/homebrew-core/blob/HEAD/Formula/m/mpv.rb) — `brew info mpv` on 2026-09-02: stable 0.41.0, `License: GPL-2.0-or-later AND LGPL-2.1-or-later`, dependencies include `libplacebo`, `vulkan-loader` **and** `molten-vk` — the macOS Vulkan path `ffmpeg-full` does not declare.

[15] [PyPI](https://pypi.org/) — licence and version metadata for `taichi` 1.7.4 (Apache-2.0), `vispy` 0.16.2 (BSD-3-Clause), `PyOpenGL` 3.1.10 (BSD), `glumpy` 1.2.1 (BSD, requires `triangle`), `wgpu` 0.32.0 (BSD-2-Clause), `pyopencl` 2026.1.4 (MIT), `triangle` 20250106 (declared LGPL-3.0), all read from the JSON API on 2026-09-02.

[16] [PyTorch](https://pytorch.org/) — version 2.9.0 installed locally, `torch.backends.mps.is_available()` → `True`, 385 MB installed footprint, verified 2026-09-02.

[17] [OpenCV](https://opencv.org/) — `cv2` 4.13.0, provided by `opencv-contrib-python` 4.13.0.92 in this environment. Its `.dylibs` were inspected directly: `libx264.164.dylib`, `libx265.215.dylib`, and a `libavcodec` whose embedded configuration string reads `--prefix=/opt/homebrew/Cellar/ffmpeg/7.1.1_3 … --enable-version3 … --enable-gpl … --enable-libx264 --enable-libx265`.

[18] `docs/research/06_licence_tiers.md` — the sibling licence-tier note (this repository, 2026-09-02). Source of the `PURE` / `PERMISSIVE` / `WEAK_COPYLEFT` / `COPYLEFT_TOOL` / `COPYLEFT_SHIPPED` ladder, the `Coupling` / `Reach` / `Conveyance` / `FieldOfUse` axes, and the "unknown is a refusal" rule applied throughout §2.2 and §5.1.

[19] `docs/research/00_ffmpeg_licence_gates_evidence.md` — the sibling FFmpeg licence-gate extraction (this repository, 2026-09-02), from FFmpeg's `configure` at tag `n8.1`. Source of the GPL-only status of `libx264` / `libx265` and of the filters marked "(GPL)" in the §4.2 sweep (`smartblur`, `sab`, `spp`, `pp7`, `hqdn3d`).

[20] Que Calor V2 stylizer — `~/Downloads/que_calor/work/style/render_v2c.py`, `stylize.py`, and `how_the_video_got_made__technical.md` (2026-09-02). Source of the shipped chain, the per-source `MS_PARAMS`, and the design rationale. It records no wall-clock timings; every figure in §4 is a new measurement.

[21] [Mesa lavapipe / llvmpipe](https://docs.mesa3d.org/drivers/llvmpipe.html) — Mesa's software rasterisers. `lvp_icd.json` on the fleet server is lavapipe, the software Vulkan driver, which is what makes the §1.2 measurement 141× slower than the CPU filter path rather than faster.

---

## Adversarial review (2026-09-02)

*Appended by an independent reviewer. Every command below was re-run by the reviewer; nothing here was taken on the author's word. The author's text above is unchanged.*

### Verdict on the verdict

**The headline recommendation — no shader backend in v1, `provider` rather than `backend` — survives.** So does almost all of the measurement. Two licence findings are wrong, one of them a **false refusal**, which is the failure mode this package exists to prevent. Two of the load-bearing performance *explanations* are unsound even though their conclusions hold, and the design recommendation as written is missing a reproducibility rule that its own §4.2 evidence demands.

### REFUTED — 1. FSRCNNX is not `UNKNOWN`; it is LGPL-3.0-or-later, and the note's rule would produce a false refusal

The note classifies FSRCNNX `UNKNOWN → refusal`, and §5.1 escalates that to "it may not even offer them by name". The verification cited is the GitHub repository *label* ("GPL-3.0, MIT licenses found"). That is a verification of the **repository**, not of the **artefact**, and the artefact says otherwise. Downloading the actual release asset — the file `looks` would name or vendor:

```
$ curl -sL -o fsr.glsl "https://github.com/igv/FSRCNN-TensorFlow/releases/download/1.1/FSRCNNX_x2_16-0-4-1.glsl"
$ head -6 fsr.glsl
// Copyright (C) 2017-2021 igv
//
// This program is free software; you can redistribute it and/or
// modify it under the terms of the GNU Lesser General Public
// License as published by the Free Software Foundation; either
// version 3.0 of the License, or (at your option) any later version.
```

Both 1.1 assets (`FSRCNNX_x2_16-0-4-1.glsl`, `FSRCNNX_x2_8-0-4-1.glsl`) carry that header verbatim. **The correct row is LGPL-3.0-or-later → `COPYLEFT_SHIPPED` if vendored — identical to RAVU, not a refusal.** (The older 1.0/0.5 assets carry no header and *are* ambiguous; that is a per-asset fact, not a per-project one.)

This is the exact methodological failure the note itself avoided for Anime4K — "verified at the FILE level, not just the repo LICENSE" — and then did not apply to FSRCNNX. Shipping this row into the ledger would put a permanent, wrong refusal into a product whose selling point is that its refusals are right.

### REFUTED — 2. Not every Anime4K `.glsl` is MIT

The claim "every `.glsl` file carries the full MIT text in its own header" is generalised from one file. A seven-file spot check across all five directories found two exceptions in 50 files:

```
glsl/Upscale/Anime4K_AutoDownscalePre_x2.glsl
  -> "This is free and unencumbered software released into the public domain."
     ... "For more information, please refer to <https://unlicense.org>"   (Unlicense, not MIT)
tensorflow/Upscale_Shader.glsl
  -> no licence header at all (covered only by the repo LICENSE)
```

Both land at `PERMISSIVE`, so the tier does not move — but the note's own conveyance rule ("`looks` **may** vendor Anime4K's shaders") is stated per-file and is not true per-file as written. It matters more than the tier suggests: **Unlicense is not universally accepted as permissive** by corporate policy (Fedora deprecated it; Google's OSS policy bans it), so a licence ledger that records "Anime4K = MIT" is recording something a downstream compliance reviewer will find false. If Anime4K is ever vendored, vendor it per-file with the per-file licence recorded.

### REFUTED — 3. "It exits 0 … so nothing warns you" / "availability is not capability, and FFmpeg's filter list cannot tell them apart"

The filter list cannot. **FFmpeg's own device init can, and says so in one word.** On the fleet server:

```
$ ssh tw 'ffmpeg -v verbose -init_hw_device vulkan -f lavfi -i testsrc2=size=320x180 -frames:v 1 -f null -'
[AVHWDeviceContext] GPU listing:
[AVHWDeviceContext]     0: llvmpipe (LLVM 20.1.2, 256 bits) (software) (0x0)
[AVHWDeviceContext] Device 0 selected: llvmpipe (LLVM 20.1.2, 256 bits) (software) (0x0)
```

The string `(software)` is emitted by FFmpeg's Vulkan device enumeration. A capability probe therefore costs one ~0.3 s `-frames:v 1` invocation and a substring test — not the throughput benchmark §5.2 item 1 prescribes. This does not change the verdict; it **cheapens the gate** the verdict depends on, and §5.2 should say so, because a rule that requires a benchmark on every host will not be run and a rule that requires a substring check will.

### REFUTED — 4. `spp=6` is not a no-op, so it is not the calibration check the note claims

§4.2 reads `spp=6` scoring identically to the no-flatten row as proof "the metric detects 'did nothing'". Measured directly on one 1280×720 frame:

```
spp6 vs no-filter: identical=False  mean|diff|=1.695/255  max=22  pct_changed=99.2%
spp3 vs spp6:      BYTE IDENTICAL       (and spp=quality=0 gives the same output too)
```

`spp` changed **99.2 % of pixels**, and its `quality` knob is inert on this input (`qp` defaults to 0 and no source QP is available). So the identical scores demonstrate the opposite of what is claimed: the four metrics (Lap, `ncol@90%`, strong, weak) **cannot distinguish "no filter" from "a filter that touched every pixel"** once `lut3d` + a mod-32 posterise have quantised the difference away. That is a defensible *pipeline* property, but it is not a calibration of the metric, and a real calibration needs a known no-op (`null` / `copy`). This weakens the confidence available for ranking the tuned `bilateral` candidate by the same four numbers — which the note already, correctly, refuses to call settled.

### REFUTED — 5. "Processes multiply and one GL context does not" — the structural claim behind the decisive comparison

This is the sentence that justifies comparing a **1-process** GPU row (36.0 fps) against a **9-process** CPU row (52.0 fps). It is measurably false. A 25×25 windowed colour-gated fragment shader at 640×360 (kernel cost 5.7–7.8 ms, in the author's 8.85 ms range, with an explicit `NO-OP=False` guard), run in N independent processes each with its own standalone context, on the same M1 Max:

| N contexts | per-process fps | **aggregate shader fps** |
|---:|---:|---:|
| 1 | 175.8 | **175.8** |
| 2 | 122.9 / 127.6 | **250.5** |
| 3 | 89.5 / 89.8 / 91.0 | **270.3** |
| 4 | ~66.8 ×4 | **268.0** |
| 6 | ~44.9 ×6 | **268.7** |

GPU shader throughput **does** multiply — ~1.5× — and saturates at N≈3, at roughly 270 fps of kernel capacity. The note's single-context measurement is not the ceiling it is treated as. The correct number to set against the 9-process CPU aggregate is an N-process GPU aggregate that was **never measured**.

The verdict is not thereby overturned — the per-process pipe floor still binds (below) — but recommendation 2's stated reason is unsound, and "the adoption bar is 52.0 fps" is being compared against a number taken with the GPU deliberately under-parallelised.

### REFUTED — 6. The stated cause of "only 2.7× end to end", and the transfer ceiling quoted at the wrong resolution

Two component figures were re-measured.

*Transfer.* Confirmed at 720p — 0.94 ms upload + 1.49 ms readback = 2.43 ms (author: 1.23 + 1.56 = 2.79 ms), a ~412 fps ceiling. **But the shipped chain runs the flatten at 0.5 scale = 640×360**, where the same measurement gives 0.19 + 0.30 = **0.50 ms, ceiling ~2011 fps**. Citing the 720p "hard ~358 fps ceiling for any Python-side GL backend" as one of the two reasons the e2e gain is small overstates the transfer barrier by ~5× in the context where it is used: at the resolution actually in play, transfer is 1.8 % of the 27.8 ms/frame budget.

*The FFmpeg halves.* The note's ~12.6 ms/frame is real and is, if anything, understated. Running the actual shipped topology (`ffmpeg` decode → python passthrough → `ffmpeg lut3d + posterise + libx264 -crf 16 -preset medium`) with **no filter at all**:

```
PASSTHROUGH pipe, 300 frames 1280x720: 4.92s -> 60.9 fps -> 16.41 ms/frame   (loadavg 14.9)
```

I also tested whether that floor is a harness artefact — decode alone is 1.65 ms/f and encode alone 3.21 ms/f, so the components look overlappable — by rewriting the loop with a reader thread and a bounded queue. It made no difference (`THREADED passthrough: 16.05 ms/frame`). **The floor is contention, not serialisation, and the note's additive model is empirically right.** Recorded here because it is the one place where I expected to overturn the note and could not.

So: the conclusion in §4.3 stands, but its stated causes should be replaced by the measured ones — a ~16 ms/frame per-process pipe floor (≈61 fps, above the 52 fps CPU aggregate, so a *free* kernel would win) and the shader kernel itself.

### REFUTED — 7. The videotoolbox tier claim contradicts the note's own §1.1 rule

§4.4: "it moves the licence tier in the right direction too, since `libx264` is a GPL-only external library while the VideoToolbox encoders are not."

§1.1 established the governing rule correctly for libplacebo: *"the governing term is the **binary's** licence"*. The binary here is `--enable-gpl --enable-version3` (verified: `ffmpeg -version` on this machine). Shelling out to it is `COPYLEFT_TOOL` **whichever encoder is selected**; picking `h264_videotoolbox` moves nothing. The claim is only true given an *LGPL-built* ffmpeg — a precondition the note never states.

Stated with that precondition it becomes a **stronger and more useful** finding than the note makes of it: sibling note 00 asserts that "an LGPL-safe render cannot emit H.264 or HEVC through ffmpeg at all", and `h264_videotoolbox` / `hevc_videotoolbox` **refute that** on macOS, because VideoToolbox is a system framework and appears in none of `external_gpl` in `ffmpeg_n81_licence_gates.json`. That belongs in note 00, corrected.

### Minor corrections

- **"3 of its 489 filters"** — 489 is `wc -l` of the whole listing, including 8 header/legend lines. The true count is **481** filters (`ffmpeg -hide_banner -filters | sed -n '9,$p' | wc -l` → 481). 3/481 = 0.62 %.
- **`ffmpeg -h filter=libplacebo` "exits 0"** — the note reproduces the output; worth noting the exit code is genuinely 0 with the message `Unknown filter 'libplacebo'.`, which is itself a small trap for a capability probe that tests `$?`.
- **`h264_videotoolbox` speedup** re-measured best-of-3 at loadavg ~20: libx264 medium 63.1 fps → h264_videotoolbox 180.3 fps = **2.86×** (author: 3.3×). Direction confirmed. Not drawn out by the note: `libx264 -preset veryfast` reaches 122.4 fps at a *smaller* file (18.2 MB) than videotoolbox at `-q:v 60` (20.7 MB), so the honest dependency-free gain over a tuned CPU preset is ~1.5×, not 3.3×, and at worse quality-per-bit.

### CONFIRMED — re-run independently, matching or exceeding the author's numbers

- **§1.1, developer machine has no programmable GPU path.** Reproduced exactly: same 3 `_vt` filters, `Unknown filter 'libplacebo'.`, `-hwaccels` → `videotoolbox` only.
- **§1.1, licences.** `brew info libplacebo` → `License: LGPL-2.1-or-later`; upstream `LICENSE` is LGPL-2.1 verbatim; the upstream README adds *"libplacebo is currently available under the terms of the LGPLv2.1 (or later) license"*. `brew info ffmpeg` and `brew info ffmpeg-full` both → `GPL-3.0-or-later`. `ffmpeg` Required (11), `ffmpeg-full` Required (47), keg-only. **The reasoning that this buys no tier movement is correct.**
- **§1.2, the server measurement — reproduced on an *idle* box** (loadavg 0.11, which the author's run was not), and it is worse than reported: libplacebo + custom shader **61.12 s**, libplacebo alone **53.15 s**, CPU `negate` **0.38 s** — a **161×** ratio. Note that a no-filter run is *also* 0.38 s, so the CPU denominator is source generation and the filter itself is free; the gap is if anything understated.
- **§1.2, the heap corruption.** Reproduced verbatim, including the exit status the note does not give: `Failed to create semaphore: VK_ERROR_INVALID_EXTERNAL_HANDLE` / `free(): double free detected in tcache 2` / **exit 134, core dumped**.
- **§2.1, `.hook` shaders genuinely apply through FFmpeg.** Reproduced to the second decimal: `mean |on-off| = 240.69`, `mean |on-(255-off)| = 0.28`, `identical? False`.
- **§2.1, Anime4K through libplacebo.** Reproduced: 1280×720 output from a 640×360 source, `fps=4.0`, `speed=0.13x`, 7.72 s wall.
- **§2.2, Anime4K repo LICENSE is MIT** and RAVU/nnedi3 are LGPLv3 — and the latter is **stronger than the note claims**: verified at the *file* level, not just the README (`ravu-lite-r3.hook` and `nnedi3-nns64-win8x4.hook` both open with the LGPLv3-or-later grant).
- **§3.1, moderngl headless on macOS.** Reproduced exactly: `4.1 Metal - 89.4 | Apple M1 Max`, `version_code 410`, `GL_MAX_TEXTURE_SIZE 16384`, compute shader → `cannot create shader`.
- **§3.2, the dependency closure.** Reproduced exactly: 408K/80K/119M/385M/54M/47M; `otool -L` shows moderngl links only `libc++`/`libSystem` and glcontext adds only `OpenGL.framework`; installed metadata `License: MIT` for both; `cv2/.dylibs` contains `libx264.164.dylib` + `libx265.215.dylib`; `strings` on the bundled `libavcodec.61.19.101.dylib` yields `--prefix=/opt/homebrew/Cellar/ffmpeg/7.1.1_3 … --enable-version3 … --enable-gpl … --enable-libx264 --enable-libx265`.
- **§4.1, the inverse-`sr` cost law — confirmed and extended to four points**, so it is not a two-point artefact. Real Que Calor frames, min-of-3, randomised interleaving, loadavg ~9 (absolute values higher than the author's because of load; the ordering is what matters and it is monotone):

  | 0.5 scale, sp=12 | min ms |
  |---|---:|
  | `sr=90` | 115.3 |
  | `sr=60` | 241.0 |
  | `sr=30` | 455.3 |
  | `sr=20` | 542.8 |

  and among shipped configs, `c03` (0.75 / sr=40) at **651.2 ms** is indeed the most expensive, above even full-resolution sr=60 (600.5 ms). Recommendation 5 is sound.
- **§4.1, `cv2.setNumThreads(1)` is a no-op** — the note marks this `verified: false`; it is straightforwardly verifiable and I verified it. `cv2.getNumThreads()` → 10, `setNumThreads(1)`, → 10; `Parallel framework: GCD`. **Upgrade this to verified.**
- **§3.3, `glumpy`/`triangle` — the note marks this unverified; it is now verified.** The Shewchuk terms were retrieved from `drufat/triangle-c` (the C sources the PyPI `triangle` package wraps), lines 34–46: *"Private, research, and institutional use is free… Distribution of this code as part of a commercial system is permissible **ONLY BY DIRECT ARRANGEMENT WITH THE AUTHOR**."* That is a field-of-use restriction, and it is **incompatible with the LGPL-3.0 that `triangle` 20250106 declares on PyPI** — a live specimen of the note-06 honesty rule (the licence *text* governs, not the metadata field). `glumpy` should be recorded as off-ladder `FieldOfUse.NON_COMMERCIAL`, not merely "do not adopt without checking".
- **§1.2, `program_opencl` — the note marks this unverified; I ran it.** `ffmpeg -init_hw_device opencl …` → `Failed to get number of OpenCL platforms: -1001. Device creation failed: -19.` Confirmed.
- **§1.1 / claim 23, `ffmpeg-full` on macOS.** Still not installed (the ~100-package closure is not worth it), but the doubt is now better founded: `brew deps ffmpeg-full` yields `libplacebo shaderc vulkan-headers vulkan-loader` and **no `molten-vk`**, while `brew deps mpv` yields `libplacebo molten-vk vulkan-headers vulkan-loader`; `brew info vulkan-loader` shows Required (1) `vulkan-headers` and ships no ICD. A Vulkan loader with no ICD enumerates zero devices, so `ffmpeg-full`'s libplacebo will almost certainly fail to initialise on a stock macOS install. Keep it flagged unverified, but the expected answer is "no".

### Two things the note did not check, both now measured

**1. `opencv-python-headless` does *not* escape the GPL binary.** Sibling note 06 names it as "the cheap way out of the question entirely" and flags it unverified. It is not a way out. Downloading the wheel (not installing it):

```
$ curl -sLo ocvh.whl .../opencv_python_headless-5.0.0.93-cp37-abi3-macosx_13_0_arm64.whl
$ unzip -l ocvh.whl | grep -iE 'x264|x265'
   1312400  cv2/.dylibs/libx264.164.dylib
   4954576  cv2/.dylibs/libx265.215.dylib
$ strings cv2/.dylibs/libavcodec.61.19.101.dylib | grep -- '--enable-gpl'
--prefix=/opt/homebrew/Cellar/ffmpeg/7.1.1_3 … --enable-version3 … --enable-gpl
--enable-libx264 --enable-libx265
```

Same ffmpeg build, same GPL flags, same x264/x265, under the same `License: Apache 2.0` metadata. **This strengthens the note's §5.2 item 3**: the obvious cheap escape from `COPYLEFT_SHIPPED` for the flatten does not exist, so the licence argument for an alternative provider is more alive than the note knew. Note 06's line about `opencv-python-headless` should be corrected.

**2. A pure-numpy flatten is not a viable `PERMISSIVE` provider — measured, so nobody re-derives it.** numpy is BSD-3 and bundles no codec, so it is the obvious rung-1 provider with no GL context, no deprecated API and no new wheel. The note measured torch/MPS (1012.8 ms) but never plain numpy. Accumulating over shifted slices (streaming, avoiding the 625× `unfold` inflation the note correctly diagnoses), 640×360, 25×25, 5 iterations, with a no-op guard:

```
numpy shift-accum mean-shift : 15567.9 ms  (0.1 fps)
cv2.pyrMeanShiftFiltering    :   253.7 ms  (3.9 fps)
NO-OP guard: identical to source? False   mean|out-src| = 18.85/255
agreement with cv2: mean|np-cv2| = 13.94/255
```

**61× slower than cv2.** A numpy provider is not an option. This confirms the note's position by closing the one alternative it did not test.

**3. `geq` is a programmable per-pixel path the note overlooks.** The note's framing ("no programmable GPU path at all") is correct as stated but leaves the impression that programmability requires libplacebo or in-process GL. FFmpeg 8.1 ships `geq` — "Apply generic equation to each pixel", slice-threaded, and **not in `external_gpl` or `gpl_filters`**, so it is LGPL-safe and inside the binary `looks` already shells out to. Measured, 640×360, 60 frames: a 5-tap RGB neighbourhood expression runs at **55.6 fps** against 1013.8 fps for `scale` alone, i.e. ~17 ms/frame for 15 texture lookups. That scales terribly — a 25×25 window is 625 lookups and would land near 700 ms/frame, so it is *not* a mean-shift substitute — but it is the right zero-dependency, tier-neutral home for the class of small-neighbourhood custom effects that a shader provider would otherwise be reached for. It belongs in the provider table §5.1 proposes.

### Design objections to the recommendations

**A. Recommendation 1 is missing the rule that makes it safe: a resolved `provider` must be recorded in the `Look`, and never silently substituted.** The kickoff requires a `Look` to be "inspectable, persistable, diffable and costable before anything runs" — the `falaw.Plan` shape. "`provider` … resolved per-effect **against the machine**" breaks that: the same persisted `Look` produces different pixels on different machines. The note's own §4.2 quantifies how different (`mean |shipped − allffmpeg| = 7.47/255`; only 39.1 % of pixels within ±4), and §5.3 records a `mean |GPU − cv2| = 4.73/255` gap between the cv2 and GLSL flatten providers **as an acceptable tolerance**. It is not acceptable as a *silent* substitution: muvid's `assemble.py` renders in chunks, so two chunks resolving to different providers puts a 4.73/255 systematic colour shift across a cut — a visible seam, and precisely the class of artefact the frame-independence invariant exists to prevent. And §1.2 shows machine-availability resolution picking a 141× slower path while reporting success. Rec 1 needs one more sentence: *the provider is part of the `Look`'s identity, resolved once, recorded, and a machine that cannot supply it refuses rather than substitutes.*

**B. Recommendation 3's FSRCNNX row is a false refusal and must not be written.** See refutation 1. `UNKNOWN → refuse` is the right *rule*; applying it to a shader that states LGPL-3.0-or-later in its own header is the rule misfiring on bad input, and it ships as a permanent wrong answer.

**C. §5.2 item 3 — "the strongest argument in favour of a shader path" — names the wrong rung and omits its precondition.** A `moderngl` flatten is rung 1, but the `Look` it sits in still runs `lut3d` + `lutrgb` in a `--enable-gpl` binary, which is rung 3. A caller at ceiling `PERMISSIVE` is refused by the *rest of the chain* regardless of the flatten's provider, so swapping cv2 for moderngl rescues nothing at `PERMISSIVE`. The argument works at ceiling **`WEAK_COPYLEFT`** and only for a caller who also has an LGPL ffmpeg — where cv2 (rung 4) is refused and moderngl (rung 1) is not. Correct the rung and state the precondition, or the note's headline licence argument does not apply to its own flagship look.

**D. Note 10 decides a question note 06 explicitly forbids `looks` from deciding.** §3.2 states flatly that the cv2 provider "is `COPYLEFT_SHIPPED` (rung 4)". Note 06 §7 says the cv2 tier is genuinely contested — the GPL `libavcodec` is dynamically linked *into the Python process*, which on one reading is in-process strong copyleft (forbidden at every ceiling) and on the other is `COPYLEFT_SHIPPED` — and that "**`looks` must not decide which reading is right** … record both components, report the conflict, and refuse until a human rules." Two sibling notes cannot ship with one recording a conflict and the other silently resolving it. Reconcile before either becomes a ledger row.

**E. Recommendation 2's adoption bar should be re-stated against a fair GPU number.** Given refutation 5 (~270 fps aggregate shader capacity, saturating at N≈3) and the measured ~16 ms/frame per-process pipe floor, the untested configuration is *N GPU processes*, and its plausible aggregate is above the 52 fps bar. The verdict ("ship no shader provider in v1") is still right — for the licence, complexity and deprecated-API reasons the note gives, and because rec 6's encoder change is a larger win for none of the cost. But "the CPU path already beats it" is not the reason, and should not be the reason recorded, because it will be re-litigated the first time someone runs the GPU path in a pool.

*Reviewer's summary: the empirical spine of this note is unusually solid — every load-bearing measurement I re-ran reproduced, several on an idle machine where the author's was contended, and one attempt to overturn it (the threaded-pipe hypothesis) failed and is recorded above. The defects are concentrated in exactly the place the package can least afford them: two licence classifications reached by checking a repository label instead of the artefact, one of which is a false refusal.*
