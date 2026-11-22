# OpenClipper engine - notices

Upstream: https://github.com/GrepCut/OpenClipper  (commit `a2fc42482d041f7034c24bc41ac5d868de72da60`, 2026-11-07)
Copyright 2026 GrepCut - MIT License (see `LICENSE.OpenClipper.txt`).

## What is taken from upstream
* `planner.mjs` - OpenClipper's TypeScript AutoFlip camera planner (`src/features/clipper/engine/autoflip/**` plus its shared types), bundled with
  esbuild into one Node script (`planner_entry.ts` is the wrapper). Upstream credits Google MediaPipe AutoFlip (Apache-2.0) as the origin of the approach.
* `models/yolox_s.onnx`, `models/yolox_s.fp16.onnx`, `models/coco80.txt` - **downloaded at install time** from the pinned commit above and
  verified against sha256 (`models.json`). YOLOX is Apache-2.0 (Megvii). Same input preprocessing and box decoding as upstream's `yolox.rs`.

## Modifications (this is a modified fork of the planner - do not report them upstream)
1. `camera/scene-motion.util.ts`: `STEADY_MOTION_THRESHOLD` 0.5 -> 0.06. Upstream keeps a near-static camera unless the subject moves more than half the
   frame; gameplay needs a real tracking camera.
2. Detection runs on a 5 fps sample with `oc_detect.py` (own code): ONNX Runtime (DirectML / CUDA / CPU) instead of WinML; own compact ByteTrack-style
   two-stage IoU tracker (not upstream's Kalman implementation); cut times refined to the exact frame; vehicle classes (bus, motorcycle, bicycle, boat,
   airplane, train) are mapped to `car` because the planner only weights car/truck as vehicle subjects; "hero lock" (score floor for the most persistent,
   large, central subject per shot) is a SONIVERSE addition.
3. Upstream's `enhancedIdentityFusion` (face/pose-verified people) is NOT used, so people without a visible face (third-person game characters seen from behind) are kept.

## Deliberately NOT used
* SCRFD-10G face model - InsightFace's weights are non-commercial research only (see upstream `MODEL_LICENSES.md`). MoveNet pose model - not needed.
* OpenClipper's desktop app, MCP server, transcription (sherpa-onnx), vocals isolation, caption renderer, publishing - none has a headless interface.

## Rebuilding planner.mjs
```
git clone https://github.com/GrepCut/OpenClipper && git -C OpenClipper checkout a2fc42482d041f7034c24bc41ac5d868de72da60
cp -r OpenClipper/src/features ./src/features            # next to planner_entry.ts (edit its import path to ./src/features/...)
sed -i 's/const STEADY_MOTION_THRESHOLD = 0.5;/const STEADY_MOTION_THRESHOLD = 0.06;/' src/features/clipper/engine/autoflip/camera/scene-motion.util.ts
npx esbuild planner_entry.ts --bundle --platform=node --format=esm --target=node20 --outfile=planner.mjs
```
