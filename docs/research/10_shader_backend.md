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
