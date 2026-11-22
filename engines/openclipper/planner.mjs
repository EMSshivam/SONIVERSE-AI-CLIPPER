// src/features/clipper/engine/autoflip/geometry/frame-crop-region.util.ts
function expandSegment(segmentToAdd, baseSegment, maxLength, minCoverageFraction = 0.5) {
  const [addLeft, addRight] = segmentToAdd;
  const [baseLeft, baseRight] = baseSegment;
  const segmentLength = addRight - addLeft;
  const maxLeftout = Math.ceil((1 - minCoverageFraction) * segmentLength / 2);
  const minCoverageLeft = addLeft + maxLeftout;
  const minCoverageRight = addRight - maxLeftout;
  let combinedLeft = Math.min(addLeft, baseLeft);
  let combinedRight = Math.max(addRight, baseRight);
  const minCoverageCombinedLeft = Math.min(minCoverageLeft, baseLeft);
  const minCoverageCombinedRight = Math.max(minCoverageRight, baseRight);
  if (combinedRight - combinedLeft <= maxLength) {
    return { segment: [combinedLeft, combinedRight], cover: "fully" };
  }
  if (minCoverageCombinedRight - minCoverageCombinedLeft <= maxLength) {
    return {
      segment: [minCoverageCombinedLeft, minCoverageCombinedRight],
      cover: "partially"
    };
  }
  return { segment: [baseLeft, baseRight], cover: "none" };
}
function expandRect(rectToAdd, baseRect, maxWidth, maxHeight) {
  const horizontal = expandSegment(
    [rectToAdd.x, rectToAdd.x + rectToAdd.width],
    [baseRect.x, baseRect.x + baseRect.width],
    maxWidth
  );
  const vertical = expandSegment(
    [rectToAdd.y, rectToAdd.y + rectToAdd.height],
    [baseRect.y, baseRect.y + baseRect.height],
    maxHeight
  );
  if (horizontal.cover === "none" || vertical.cover === "none") {
    return { rect: baseRect, cover: "none" };
  }
  return {
    rect: {
      x: horizontal.segment[0],
      y: vertical.segment[0],
      width: horizontal.segment[1] - horizontal.segment[0],
      height: vertical.segment[1] - vertical.segment[0]
    },
    cover: horizontal.cover === "fully" && vertical.cover === "fully" ? "fully" : "partially"
  };
}
function unionRect(a, b) {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  return { x, y, width: Math.max(a.x + a.width, b.x + b.width) - x, height: Math.max(a.y + a.height, b.y + b.height) - y };
}
var FACE_SIGNALS = /* @__PURE__ */ new Set(["face_core", "face_all", "face_full"]);
var POSE_HEAD_SIGNALS = /* @__PURE__ */ new Set(["pose_head"]);
var POSE_TORSO_SIGNALS = /* @__PURE__ */ new Set(["pose_torso"]);
var SUBJECT_SIGNALS = /* @__PURE__ */ new Set(["human", "pet", "car"]);
function focusBandRegions(regions) {
  const faces = regions.filter((region) => FACE_SIGNALS.has(region.signalType));
  if (faces.length) return faces;
  const poseHeads = regions.filter((region) => POSE_HEAD_SIGNALS.has(region.signalType));
  if (poseHeads.length) return poseHeads;
  const poseTorsos = regions.filter((region) => POSE_TORSO_SIGNALS.has(region.signalType));
  if (poseTorsos.length) return poseTorsos;
  const subjects = regions.filter((region) => SUBJECT_SIGNALS.has(region.signalType));
  if (subjects.length) return subjects;
  return regions;
}
function focusAggregate(regions) {
  const band = focusBandRegions(regions);
  if (!band.length) return null;
  let weightSum = 0;
  let x = 0;
  let y = 0;
  let box = null;
  for (const region of band) {
    const weight = region.score * Math.sqrt(Math.max(0, region.box.width * region.box.height)) + 1e-6;
    weightSum += weight;
    x += (region.box.x + region.box.width / 2) * weight;
    y += (region.box.y + region.box.height / 2) * weight;
    box = box ? unionRect(box, region.box) : { ...region.box };
  }
  return { center: { x: x / weightSum, y: y / weightSum }, box };
}
function computeFrameCropRegionResult(input2) {
  const { frameWidth, frameHeight, targetAspectRatio, regions } = input2;
  if (frameWidth <= 0 || frameHeight <= 0 || targetAspectRatio <= 0) {
    return { region: { x: 0, y: 0, width: 1, height: 1 }, regionIsEmpty: true, requiredRegionIsEmpty: true, areRequiredRegionsCoveredInTargetSize: true, fractionNonRequiredCovered: 0, regionScore: 0 };
  }
  const sourceAspect = frameWidth / frameHeight;
  let cropWidthNorm;
  let cropHeightNorm;
  if (sourceAspect >= targetAspectRatio) {
    cropHeightNorm = 1;
    cropWidthNorm = targetAspectRatio / sourceAspect;
  } else {
    cropWidthNorm = 1;
    cropHeightNorm = sourceAspect / targetAspectRatio;
  }
  if (regions.length === 0) return { region: { x: 0, y: 0, width: 0, height: 0 }, regionIsEmpty: true, requiredRegionIsEmpty: true, areRequiredRegionsCoveredInTargetSize: true, fractionNonRequiredCovered: 0, regionScore: 0 };
  const sorted = [...regions].sort((a, b) => b.score - a.score);
  const required = sorted.filter((region) => region.isRequired);
  const requiredBox = required.reduce((union2, region) => union2 ? unionRect(union2, region.box) : { ...region.box }, null);
  if (requiredBox) {
    cropWidthNorm = Math.max(cropWidthNorm, requiredBox.width);
    cropHeightNorm = Math.max(cropHeightNorm, requiredBox.height);
  }
  const anchor = requiredBox ?? sorted[0].box;
  const anchorCenterX = anchor.x + anchor.width / 2;
  const anchorCenterY = anchor.y + anchor.height / 2;
  let crop = requiredBox ? { ...requiredBox } : { x: anchorCenterX, y: anchorCenterY, width: 0, height: 0 };
  let aggregateScore = required.length ? 1 : 0;
  let fullyCovered = 0;
  const optional = sorted.filter((region) => !region.isRequired);
  for (const region of sorted) {
    if (region.isRequired) continue;
    const expanded = expandRect(region.box, crop, cropWidthNorm, cropHeightNorm);
    if (expanded.cover !== "none") {
      crop = expanded.rect;
      if (expanded.cover === "fully") fullyCovered++;
      if (expanded.cover === "fully") aggregateScore = 1;
    }
  }
  const focus = focusAggregate(regions);
  return {
    region: { ...crop },
    regionIsEmpty: false,
    requiredRegionIsEmpty: required.length === 0,
    requiredRegion: requiredBox ?? void 0,
    areRequiredRegionsCoveredInTargetSize: !requiredBox || requiredBox.width <= cropWidthNorm && requiredBox.height <= cropHeightNorm,
    fractionNonRequiredCovered: optional.length ? fullyCovered / optional.length : 0,
    regionScore: aggregateScore,
    focusCenter: focus?.center,
    focusBox: focus?.box
  };
}
function computeTargetCropSize(frameWidth, frameHeight, targetAspectRatio) {
  const sourceAspect = frameWidth / frameHeight;
  if (sourceAspect >= targetAspectRatio) {
    return { cropWidth: frameHeight * targetAspectRatio, cropHeight: frameHeight };
  }
  return { cropWidth: frameWidth, cropHeight: frameWidth / targetAspectRatio };
}

// src/features/clipper/engine/autoflip/camera/scene-motion.util.ts
var STEADY_MOTION_THRESHOLD = 0.06;
var STEADY_CENTER_DEADBAND = 0.08;
function rectCenter(rect) {
  return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
}
function clampCenter(center2, cropSize) {
  return Math.max(cropSize / 2, Math.min(1 - cropSize / 2, center2));
}
function motionSpanPercent(crops, frameWidth, frameHeight, targetAspectRatio) {
  if (crops.length <= 1) return { horizontal: 0, vertical: 0 };
  const xs = crops.map((crop) => rectCenter(crop).x * frameWidth);
  const ys = crops.map((crop) => rectCenter(crop).y * frameHeight);
  const xSpan = Math.max(...xs) - Math.min(...xs);
  const ySpan = Math.max(...ys) - Math.min(...ys);
  const { cropWidth, cropHeight } = computeTargetCropSize(frameWidth, frameHeight, targetAspectRatio);
  return { horizontal: xSpan / Math.max(1, frameWidth), vertical: ySpan / Math.max(1, frameHeight) };
}
function clampKeyframeCenter(rect, cropWidthNorm, cropHeightNorm) {
  const center2 = rectCenter(rect);
  const x = Math.max(cropWidthNorm / 2, Math.min(1 - cropWidthNorm / 2, center2.x));
  const y = Math.max(cropHeightNorm / 2, Math.min(1 - cropHeightNorm / 2, center2.y));
  return { ...rect, x: x - rect.width / 2, y: y - rect.height / 2 };
}
function decideMotionType(motion, successRate, sceneSpanSec, allowSweeping, hasSolidColorBackground, hasSalientRegion, hasPersistentTrack) {
  if (!hasSalientRegion) return "steady";
  if (allowSweeping && !hasSolidColorBackground && !hasPersistentTrack && successRate < 0.4 && sceneSpanSec >= 1) return "sweeping";
  return motion.horizontal < STEADY_MOTION_THRESHOLD && motion.vertical < STEADY_MOTION_THRESHOLD ? "steady" : "tracking";
}
function interpolateRect(a, b, t) {
  return {
    x: a.x + (b.x - a.x) * t,
    y: a.y + (b.y - a.y) * t,
    width: a.width + (b.width - a.width) * t,
    height: a.height + (b.height - a.height) * t
  };
}
function interpolateAtTime(keyframeCrops, time) {
  if (keyframeCrops.length === 0) {
    return { x: 0, y: 0, width: 1, height: 1 };
  }
  if (time <= keyframeCrops[0].time) return keyframeCrops[0].rect;
  const last = keyframeCrops.at(-1);
  if (time >= last.time) return last.rect;
  for (let index = 1; index < keyframeCrops.length; index++) {
    const current = keyframeCrops[index];
    const previous = keyframeCrops[index - 1];
    if (time <= current.time) {
      const span = Math.max(Number.EPSILON, current.time - previous.time);
      const fraction = (time - previous.time) / span;
      return interpolateRect(previous.rect, current.rect, fraction);
    }
  }
  return last.rect;
}
function analyzeSceneMotion(input2) {
  const { frameWidth, frameHeight, targetAspectRatio } = input2;
  const { cropWidth, cropHeight } = computeTargetCropSize(frameWidth, frameHeight, targetAspectRatio);
  const targetWidthNorm = cropWidth / frameWidth;
  const targetHeightNorm = cropHeight / frameHeight;
  const cropScale = Math.min(1, Math.max(0.05, input2.cropScale ?? 1));
  const scaledTargetWidthNorm = targetWidthNorm * cropScale;
  const scaledTargetHeightNorm = targetHeightNorm * cropScale;
  const keyframeResults = input2.keyframes.map((keyframe) => ({
    time: keyframe.time,
    result: computeFrameCropRegionResult({
      frameWidth,
      frameHeight,
      targetAspectRatio,
      regions: keyframe.regions
    })
  }));
  const nonEmptyResults = keyframeResults.filter((item) => !item.result.regionIsEmpty);
  const keyframeCrops = nonEmptyResults.map(({ time, result }) => {
    const focus = result.focusCenter;
    const rect = focus ? { ...result.region, x: focus.x - result.region.width / 2, y: focus.y - result.region.height / 2 } : result.region;
    return { time, rect: clampKeyframeCenter(rect, scaledTargetWidthNorm, scaledTargetHeightNorm) };
  });
  const motionAmount = motionSpanPercent(
    keyframeCrops.map((item) => item.rect),
    frameWidth,
    frameHeight,
    targetAspectRatio
  );
  const hasSalientRegion = keyframeResults.some((item) => !item.result.regionIsEmpty);
  const successRate = keyframeResults.length ? keyframeResults.reduce((sum, item) => sum + (item.result.areRequiredRegionsCoveredInTargetSize ? item.result.fractionNonRequiredCovered : 0), 0) / keyframeResults.length : 0;
  const sceneTimes = input2.sceneTimestampsUs?.map((time) => time / 1e6) ?? input2.keyframes.map((keyframe) => keyframe.time);
  const sceneSpanSec = Math.max(0, (sceneTimes.at(-1) ?? 0) - (sceneTimes[0] ?? 0));
  const trackedFrameCounts = /* @__PURE__ */ new Map();
  for (const keyframe of input2.keyframes) {
    const ids = new Set(focusBandRegions(keyframe.regions).filter((region) => !region.predicted && region.trackId != null).map((region) => region.trackId));
    for (const id of ids) trackedFrameCounts.set(id, (trackedFrameCounts.get(id) ?? 0) + 1);
  }
  const hasPersistentTrack = [...trackedFrameCounts.values()].some((count) => count >= 2);
  const requestedMotionType = decideMotionType(motionAmount, successRate, sceneSpanSec, input2.allowSweeping ?? true, Boolean(input2.hasSolidColorBackground), hasSalientRegion, hasPersistentTrack);
  const keyframeCenters = keyframeCrops.map((item) => rectCenter(item.rect));
  const unscaledAggWidthNorm = Math.max(targetWidthNorm, ...nonEmptyResults.map(({ result }) => result.region.width));
  const sweepHorizontally = unscaledAggWidthNorm > targetWidthNorm + 1e-6 || targetHeightNorm >= 1 - 1e-6;
  const sweepAxisCenters = keyframeCenters.map((center2) => sweepHorizontally ? center2.x : center2.y);
  const sweepCropSize = sweepHorizontally ? targetWidthNorm : targetHeightNorm;
  const sweepStartCenter = sweepAxisCenters.length ? clampCenter(Math.min(...sweepAxisCenters), sweepCropSize) : 0.5;
  const sweepEndCenter = sweepAxisCenters.length ? clampCenter(Math.max(...sweepAxisCenters), sweepCropSize) : 0.5;
  const motionType = requestedMotionType === "sweeping" && sweepEndCenter - sweepStartCenter <= 1e-6 ? "steady" : requestedMotionType;
  const sceneCropWidthNorm = scaledTargetWidthNorm;
  const sceneCropHeightNorm = scaledTargetHeightNorm;
  const centerMinX = keyframeCenters.length ? Math.min(...keyframeCenters.map((center2) => center2.x)) : 0.5;
  const centerMaxX = keyframeCenters.length ? Math.max(...keyframeCenters.map((center2) => center2.x)) : 0.5;
  const centerMinY = keyframeCenters.length ? Math.min(...keyframeCenters.map((center2) => center2.y)) : 0.5;
  const centerMaxY = keyframeCenters.length ? Math.max(...keyframeCenters.map((center2) => center2.y)) : 0.5;
  let lookAtCenterX = 0.5;
  let lookAtCenterY = 0.5;
  if (motionType === "steady" && hasSalientRegion && keyframeCenters.length > 0) {
    lookAtCenterX = (centerMinX + centerMaxX) / 2;
    lookAtCenterY = (centerMinY + centerMaxY) / 2;
    if (Math.abs(lookAtCenterX - 0.5) < STEADY_CENTER_DEADBAND * cropScale) lookAtCenterX = 0.5;
    if (Math.abs(lookAtCenterY - 0.5) < STEADY_CENTER_DEADBAND * cropScale) lookAtCenterY = 0.5;
  } else if (motionType === "sweeping") {
    if (sweepHorizontally) {
      lookAtCenterX = (sweepStartCenter + sweepEndCenter) / 2;
      lookAtCenterY = (centerMinY + centerMaxY) / 2;
    } else {
      lookAtCenterX = (centerMinX + centerMaxX) / 2;
      lookAtCenterY = (sweepStartCenter + sweepEndCenter) / 2;
    }
  } else if (keyframeCenters.length > 0) {
    const last = keyframeCenters.at(-1);
    lookAtCenterX = last.x;
    lookAtCenterY = last.y;
  }
  const steadyRect = {
    x: Math.max(0, Math.min(1 - sceneCropWidthNorm, lookAtCenterX - sceneCropWidthNorm / 2)),
    y: Math.max(0, Math.min(1 - sceneCropHeightNorm, lookAtCenterY - sceneCropHeightNorm / 2)),
    width: sceneCropWidthNorm,
    height: sceneCropHeightNorm
  };
  const focusTimes = sceneTimes.length ? sceneTimes : [input2.keyframes[0]?.time ?? 0];
  const focusPointFrames = [];
  for (const time of focusTimes) {
    const frameIndex = focusPointFrames.length;
    const sweepFraction = focusTimes.length > 1 ? frameIndex / (focusTimes.length - 1) : 0;
    const rect = motionType === "steady" ? steadyRect : motionType === "sweeping" ? {
      x: sweepHorizontally ? sweepStartCenter + (sweepEndCenter - sweepStartCenter) * sweepFraction - sceneCropWidthNorm / 2 : clampCenter(lookAtCenterX, sceneCropWidthNorm) - sceneCropWidthNorm / 2,
      y: sweepHorizontally ? clampCenter(lookAtCenterY, sceneCropHeightNorm) - sceneCropHeightNorm / 2 : sweepStartCenter + (sweepEndCenter - sweepStartCenter) * sweepFraction - sceneCropHeightNorm / 2,
      width: sceneCropWidthNorm,
      height: sceneCropHeightNorm
    } : interpolateAtTime(keyframeCrops, time);
    const center2 = rectCenter(rect);
    const points = sceneCropHeightNorm >= 1 - 1e-6 ? [{ x: center2.x, y: 0, weight: 1 }, { x: center2.x, y: 1, weight: 1 }] : sceneCropWidthNorm >= 1 - 1e-6 ? [{ x: 0, y: center2.y, weight: 1 }, { x: 1, y: center2.y, weight: 1 }] : [{ x: center2.x, y: center2.y, weight: 1 }];
    focusPointFrames.push({ timeUs: Math.round(time * 1e6), points });
  }
  return {
    summary: {
      sceneFrameWidth: frameWidth,
      sceneFrameHeight: frameHeight,
      cropWindowWidth: sceneCropWidthNorm * frameWidth,
      cropWindowHeight: sceneCropHeightNorm * frameHeight,
      motionType,
      lookAtCenterX,
      lookAtCenterY,
      frameSuccessRate: successRate,
      horizontalMotionAmount: motionAmount.horizontal,
      verticalMotionAmount: motionAmount.vertical,
      hasSalientRegion
    },
    keyframeCrops,
    focusPointFrames
  };
}

// src/features/clipper/lib/math.util.ts
function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

// src/features/clipper/engine/autoflip/config/config.constants.ts
var AUTOFLIP_ANALYZER_VERSION = "autoflip-v43-snap-layout-on-cut";
var AUTOFLIP_MODEL_ID = "clipper-vision-v5-yolox-s-scrfd10g-tiled";
var AUTOFLIP_FIELD_OF_VIEW_DEG = 60;
var AUTOFLIP_MAX_SCENE_FRAMES = 600;
var AUTOFLIP_KEYFRAME_INTERVAL_SEC = 0.2;
var AUTOFLIP_TRACK_FPS = 5;
var DEFAULT_KINEMATIC_OPTIONS = {
  reframeWindow: 0,
  updateRateSeconds: 0.2,
  maxUpdateRate: 0.8,
  filteringTimeWindowUs: 0,
  meanPeriodUpdateRate: 0.25,
  maxDeltaTimeSec: 0
};

// src/features/clipper/engine/autoflip/camera/kinematic-solver.util.ts
var MIN_VELOCITY = 0.5;
var KinematicPathError = class extends Error {
  constructor(message) {
    super(message);
    this.name = "KinematicPathError";
  }
};
function medianPosition(positions) {
  const values = positions.map(([, position]) => position);
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}
var KinematicPathSolver = class {
  options;
  minLocation;
  maxLocation;
  pixelsPerDegree;
  initialized = false;
  currentPositionPx = 0;
  priorPositionPx = 0;
  targetPositionPx = 0;
  currentTimeUs = 0;
  currentVelocityDegPerS = 0;
  meanDeltaT = -1;
  motionState = false;
  rawPositionsAtTime = [];
  constructor(options, minLocation, maxLocation, pixelsPerDegree) {
    this.options = { ...DEFAULT_KINEMATIC_OPTIONS, ...options };
    this.minLocation = minLocation;
    this.maxLocation = maxLocation;
    this.pixelsPerDegree = pixelsPerDegree;
  }
  validateOptions() {
    if (this.pixelsPerDegree <= 0) throw new KinematicPathError("pixels_per_degree must be larger than 0.");
    const updateRateSeconds = this.options.updateRateSeconds ?? DEFAULT_KINEMATIC_OPTIONS.updateRateSeconds;
    const filteringTimeWindowUs = this.options.filteringTimeWindowUs ?? DEFAULT_KINEMATIC_OPTIONS.filteringTimeWindowUs;
    const meanPeriodUpdateRate = this.options.meanPeriodUpdateRate ?? DEFAULT_KINEMATIC_OPTIONS.meanPeriodUpdateRate;
    if (updateRateSeconds < 0) throw new KinematicPathError("update_rate_seconds must be greater than 0.");
    if (filteringTimeWindowUs < 0) throw new KinematicPathError("filtering_time_window_us must be greater than 0.");
    if (meanPeriodUpdateRate < 0) throw new KinematicPathError("mean_period_update_rate must be greater than 0.");
    const hasUnifiedMin = this.options.minMotionToReframe != null;
    const hasSplitMin = this.options.minMotionToReframeLower != null && this.options.minMotionToReframeUpper != null;
    if (hasUnifiedMin === hasSplitMin) {
      throw new KinematicPathError(
        "Must set min_motion_to_reframe or min_motion_to_reframe_upper and min_motion_to_reframe_lower."
      );
    }
    const reframeWindow = this.options.reframeWindow ?? DEFAULT_KINEMATIC_OPTIONS.reframeWindow;
    const minReframe = hasUnifiedMin ? this.options.minMotionToReframe : Math.min(this.options.minMotionToReframeLower, this.options.minMotionToReframeUpper);
    if (reframeWindow > minReframe) {
      throw new KinematicPathError("Reframe window cannot exceed min_motion_to_reframe.");
    }
    const hasMaxVelocity = this.options.maxVelocity != null;
    const hasScaledMax = this.options.maxVelocityScale != null && this.options.maxVelocityShift != null;
    if (hasMaxVelocity === hasScaledMax) {
      throw new KinematicPathError(
        "Must either set max_velocity or set both max_velocity_scale and max_velocity_shift."
      );
    }
  }
  isMotionTooSmall(deltaDegs) {
    if (this.options.minMotionToReframe != null) {
      return Math.abs(deltaDegs) < this.options.minMotionToReframe;
    }
    if (deltaDegs > 0) {
      return deltaDegs < this.options.minMotionToReframeUpper;
    }
    return Math.abs(deltaDegs) < this.options.minMotionToReframeLower;
  }
  trimHistory(timeUs) {
    const filteringTimeWindowUs = this.options.filteringTimeWindowUs ?? DEFAULT_KINEMATIC_OPTIONS.filteringTimeWindowUs;
    while (this.rawPositionsAtTime.length > 1) {
      if (this.rawPositionsAtTime.at(-1)[0] < timeUs - filteringTimeWindowUs) {
        this.rawPositionsAtTime.pop();
      } else {
        break;
      }
    }
  }
  predictMotionState(position, timeUs) {
    if (!this.initialized) return false;
    const history = [[timeUs, position], ...this.rawPositionsAtTime];
    const filteringTimeWindowUs = this.options.filteringTimeWindowUs ?? DEFAULT_KINEMATIC_OPTIONS.filteringTimeWindowUs;
    while (history.length > 1 && history.at(-1)[0] < timeUs - filteringTimeWindowUs) {
      history.pop();
    }
    let filteredPosition = clamp(medianPosition(history), this.minLocation, this.maxLocation);
    const deltaDegs = (filteredPosition - this.currentPositionPx) / this.pixelsPerDegree;
    const reframeWindow = this.options.reframeWindow ?? DEFAULT_KINEMATIC_OPTIONS.reframeWindow;
    if (this.isMotionTooSmall(deltaDegs) && !this.motionState) return false;
    if (Math.abs(deltaDegs) < reframeWindow && this.motionState) return false;
    if (this.priorPositionPx === this.currentPositionPx && this.motionState) return false;
    return true;
  }
  addObservation(position, timeUs) {
    if (!this.initialized) {
      this.currentPositionPx = clamp(position, this.minLocation, this.maxLocation);
      this.targetPositionPx = position;
      this.priorPositionPx = this.currentPositionPx;
      this.motionState = false;
      this.meanDeltaT = -1;
      this.rawPositionsAtTime = [[timeUs, position]];
      this.currentTimeUs = timeUs;
      this.initialized = true;
      this.currentVelocityDegPerS = 0;
      this.validateOptions();
      return;
    }
    if (this.currentTimeUs >= timeUs) {
      throw new KinematicPathError("Observation added before a prior observation.");
    }
    this.rawPositionsAtTime.unshift([timeUs, position]);
    this.trimHistory(timeUs);
    let filteredPosition = medianPosition(this.rawPositionsAtTime);
    const minReframePx = (this.options.minMotionToReframe ?? this.options.minMotionToReframeLower) * this.pixelsPerDegree;
    const maxReframePx = (this.options.minMotionToReframe ?? this.options.minMotionToReframeUpper) * this.pixelsPerDegree;
    filteredPosition = Math.max(this.minLocation - minReframePx, filteredPosition);
    filteredPosition = Math.min(this.maxLocation + maxReframePx, filteredPosition);
    let deltaDegs = (filteredPosition - this.currentPositionPx) / this.pixelsPerDegree;
    const reframeWindow = this.options.reframeWindow ?? DEFAULT_KINEMATIC_OPTIONS.reframeWindow;
    const maxVelocity = this.resolveMaxVelocity(deltaDegs);
    if (this.isMotionTooSmall(deltaDegs) && !this.motionState) {
      deltaDegs = 0;
      this.motionState = false;
    } else if (Math.abs(deltaDegs) < reframeWindow && this.motionState) {
      deltaDegs = 0;
      this.motionState = false;
    } else if (deltaDegs > 0) {
      this.targetPositionPx = filteredPosition - this.pixelsPerDegree * reframeWindow;
      deltaDegs = (this.targetPositionPx - this.currentPositionPx) / this.pixelsPerDegree;
      this.motionState = true;
    } else {
      this.targetPositionPx = filteredPosition + this.pixelsPerDegree * reframeWindow;
      deltaDegs = (this.targetPositionPx - this.currentPositionPx) / this.pixelsPerDegree;
      this.motionState = true;
    }
    let deltaTSec = (timeUs - this.currentTimeUs) / 1e6;
    const maxDeltaTimeSec = this.options.maxDeltaTimeSec ?? DEFAULT_KINEMATIC_OPTIONS.maxDeltaTimeSec;
    if (maxDeltaTimeSec > 0) deltaTSec = Math.min(deltaTSec, maxDeltaTimeSec);
    const meanPeriodUpdateRate = this.options.meanPeriodUpdateRate ?? DEFAULT_KINEMATIC_OPTIONS.meanPeriodUpdateRate;
    if (this.meanDeltaT < 0) {
      this.meanDeltaT = deltaTSec;
    } else {
      this.meanDeltaT = this.meanDeltaT * (1 - meanPeriodUpdateRate) + deltaTSec * meanPeriodUpdateRate;
    }
    const observedVelocity = deltaDegs / deltaTSec;
    const updateRateSeconds = this.options.updateRateSeconds ?? DEFAULT_KINEMATIC_OPTIONS.updateRateSeconds;
    const maxUpdateRate = this.options.maxUpdateRate ?? DEFAULT_KINEMATIC_OPTIONS.maxUpdateRate;
    const updateRate = Math.min(this.meanDeltaT / updateRateSeconds, maxUpdateRate);
    const updatedVelocity = this.currentVelocityDegPerS * (1 - updateRate) + observedVelocity * updateRate;
    this.currentVelocityDegPerS = updatedVelocity > 0 ? Math.min(updatedVelocity, maxVelocity) : Math.max(updatedVelocity, -maxVelocity);
    this.updatePrediction(timeUs);
  }
  updatePrediction(timeUs) {
    if (!this.initialized) throw new KinematicPathError("Prediction before first observation.");
    if (this.currentTimeUs >= timeUs) {
      throw new KinematicPathError("Prediction time added before a prior observation or prediction.");
    }
    this.priorPositionPx = this.currentPositionPx;
    const updatePositionPx = this.currentPositionPx + this.currentVelocityDegPerS * this.meanDeltaT * this.pixelsPerDegree;
    if (updatePositionPx < this.minLocation) {
      this.currentPositionPx = this.minLocation;
      this.currentVelocityDegPerS = 0;
      this.motionState = false;
    } else if (updatePositionPx > this.maxLocation) {
      this.currentPositionPx = this.maxLocation;
      this.currentVelocityDegPerS = 0;
      this.motionState = false;
    } else {
      this.currentPositionPx = updatePositionPx;
    }
    this.currentTimeUs = timeUs;
  }
  getState() {
    if (!this.initialized) throw new KinematicPathError("GetState called before first observation added.");
    return this.currentPositionPx;
  }
  getStateInt() {
    return Math.round(this.getState());
  }
  getTargetPosition() {
    if (!this.initialized) throw new KinematicPathError("GetTargetPosition called before first observation added.");
    return Math.round(clamp(this.targetPositionPx, this.minLocation, this.maxLocation));
  }
  setState(position) {
    if (!this.initialized) throw new KinematicPathError("SetState called before first observation added.");
    this.currentPositionPx = clamp(position, this.minLocation, this.maxLocation);
  }
  updatePixelsPerDegree(pixelsPerDegree) {
    if (pixelsPerDegree <= 0) throw new KinematicPathError("pixels_per_degree must be larger than 0.");
    this.pixelsPerDegree = pixelsPerDegree;
  }
  updateMinMaxLocation(minLocation, maxLocation) {
    if (!this.initialized) {
      this.minLocation = minLocation;
      this.maxLocation = maxLocation;
      return;
    }
    const priorDistance = this.maxLocation - this.minLocation;
    const updatedDistance = maxLocation - minLocation;
    const scaleChange = updatedDistance / priorDistance;
    this.currentPositionPx *= scaleChange;
    this.priorPositionPx *= scaleChange;
    this.targetPositionPx *= scaleChange;
    this.rawPositionsAtTime = this.rawPositionsAtTime.map(
      ([time, position]) => [time, position * scaleChange]
    );
    this.minLocation = minLocation;
    this.maxLocation = maxLocation;
  }
  resolveMaxVelocity(deltaDegs) {
    if (this.options.maxVelocity != null) return this.options.maxVelocity;
    return Math.max(
      Math.abs(deltaDegs * this.options.maxVelocityScale) + this.options.maxVelocityShift,
      MIN_VELOCITY
    );
  }
};

// src/features/clipper/engine/autoflip/camera/polynomial-solver.util.ts
function solveLinearSystem(matrix, vector) {
  const n = vector.length;
  const augmented = matrix.map((row, index) => [...row, vector[index]]);
  for (let pivot = 0; pivot < n; pivot++) {
    let best = pivot;
    for (let row = pivot + 1; row < n; row++) {
      if (Math.abs(augmented[row][pivot]) > Math.abs(augmented[best][pivot])) best = row;
    }
    if (Math.abs(augmented[best][pivot]) < 1e-10) return null;
    [augmented[pivot], augmented[best]] = [augmented[best], augmented[pivot]];
    const divisor = augmented[pivot][pivot];
    for (let column = pivot; column <= n; column++) augmented[pivot][column] /= divisor;
    for (let row = 0; row < n; row++) {
      if (row === pivot) continue;
      const factor = augmented[row][pivot];
      for (let column = pivot; column <= n; column++) augmented[row][column] -= factor * augmented[pivot][column];
    }
  }
  return augmented.map((row) => row[n]);
}
function evaluate(coefficients, time) {
  return coefficients[0] * time + coefficients[1] * time ** 2 + coefficients[2] * time ** 3 + coefficients[3] * time ** 4 + coefficients[4];
}
function solveAutoFlipPolynomialPath(frames, axis, outputTimesUs = frames.map((frame) => frame.timeUs), priorFrames = []) {
  const allFrames = [...priorFrames, ...frames];
  const observations = allFrames.flatMap((frame, frameIndex) => frame.points.map((point) => ({
    time: frameIndex,
    value: axis === "x" ? point.x : point.y
  })));
  if (!observations.length) return outputTimesUs.map(() => 0.5);
  let coefficients = [0, 0, 0, 0, observations.reduce((sum, point) => sum + point.value, 0) / observations.length];
  for (let iteration = 0; iteration < 8; iteration++) {
    const normal = Array.from({ length: 5 }, () => Array(5).fill(0));
    const rhs = Array(5).fill(0);
    for (const point of observations) {
      const residual = point.value - evaluate(coefficients, point.time);
      const robustWeight = 1 / (1 + (residual / 0.5) ** 2);
      const weight = robustWeight;
      const basis = [point.time, point.time ** 2, point.time ** 3, point.time ** 4, 1];
      for (let row = 0; row < 5; row++) {
        rhs[row] += weight * basis[row] * point.value;
        for (let column = 0; column < 5; column++) normal[row][column] += weight * basis[row] * basis[column];
      }
    }
    for (let diagonal = 0; diagonal < 5; diagonal++) normal[diagonal][diagonal] += 1e-6;
    const solved = solveLinearSystem(normal, rhs);
    if (!solved) break;
    coefficients = solved;
  }
  return outputTimesUs.map(
    (_, outputIndex) => Math.max(0, Math.min(1, evaluate(coefficients, outputIndex + priorFrames.length)))
  );
}

// src/features/clipper/engine/autoflip/camera/scene-path.util.ts
function cropScenePath(input2) {
  const { summary, focusPointFrames, sceneTimestampsUs, isKeyFrames, kinematicOptions } = input2;
  const frameWidth = summary.sceneFrameWidth;
  const frameHeight = summary.sceneFrameHeight;
  const cropWidthNorm = summary.cropWindowWidth / frameWidth;
  const cropHeightNorm = summary.cropWindowHeight / frameHeight;
  if ((input2.pathSolver ?? "polynomial") === "polynomial") {
    const xs = solveAutoFlipPolynomialPath(focusPointFrames, "x", sceneTimestampsUs, input2.priorFocusPointFrames);
    const ys = solveAutoFlipPolynomialPath(focusPointFrames, "y", sceneTimestampsUs, input2.priorFocusPointFrames);
    return sceneTimestampsUs.map((_, index) => ({
      x: Math.max(0, Math.min(1 - cropWidthNorm, xs[index] - cropWidthNorm / 2)),
      y: Math.max(0, Math.min(1 - cropHeightNorm, ys[index] - cropHeightNorm / 2)),
      width: cropWidthNorm,
      height: cropHeightNorm
    }));
  }
  const minX = summary.cropWindowWidth / 2;
  const maxX = summary.sceneFrameWidth - summary.cropWindowWidth / 2;
  const minY = summary.cropWindowHeight / 2;
  const maxY = summary.sceneFrameHeight - summary.cropWindowHeight / 2;
  const pixelsPerDegree = frameWidth / AUTOFLIP_FIELD_OF_VIEW_DEG;
  const xSolver = new KinematicPathSolver(kinematicOptions, minX, maxX, pixelsPerDegree);
  const ySolver = new KinematicPathSolver(kinematicOptions, minY, maxY, pixelsPerDegree);
  const crops = [];
  let hasObservation = false;
  for (let index = 0; index < sceneTimestampsUs.length; index++) {
    const timestampUs = sceneTimestampsUs[index];
    const isKeyframe = isKeyFrames[index] || !hasObservation;
    if (isKeyframe) {
      const focus = focusPointFrames[index] ?? focusPointFrames.at(-1) ?? {
        points: [{ x: 0.5, y: 0.5, weight: 1 }]
      };
      const observedX = Math.round((focus.points[0]?.x ?? 0.5) * frameWidth);
      const observedY = Math.round((focus.points[0]?.y ?? 0.5) * frameHeight);
      xSolver.addObservation(observedX, timestampUs);
      ySolver.addObservation(observedY, timestampUs);
      hasObservation = true;
    } else {
      xSolver.updatePrediction(timestampUs);
      ySolver.updatePrediction(timestampUs);
    }
    const centerX2 = xSolver.getState() / frameWidth;
    const centerY = ySolver.getState() / frameHeight;
    crops.push({
      x: centerX2 - cropWidthNorm / 2,
      y: centerY - cropHeightNorm / 2,
      width: cropWidthNorm,
      height: cropHeightNorm
    });
  }
  return crops;
}
function buildSceneTimeline(startSec, endSec, fps = 30, includeEnd = true) {
  const stepSec = 1 / fps;
  const keyframeStepSec = 0.2;
  const timestampsUs = [];
  const isKeyFrames = [];
  for (let time = startSec; time < endSec - 1e-9 || includeEnd && time <= endSec + 1e-9; time += stepSec) {
    timestampsUs.push(Math.round(time * 1e6));
    isKeyFrames.push(Math.abs(time / keyframeStepSec - Math.round(time / keyframeStepSec)) < stepSec * 0.5);
  }
  if (includeEnd && timestampsUs.at(-1) !== Math.round(endSec * 1e6)) {
    timestampsUs.push(Math.round(endSec * 1e6));
    isKeyFrames.push(false);
  }
  return { timestampsUs, isKeyFrames };
}

// src/features/clipper/engine/autoflip/filters/one-euro-filter.util.ts
var DEFAULT_FREQUENCY = 30;
var DEFAULT_MIN_CUTOFF = 2.5;
var DEFAULT_BETA = 300;
var DEFAULT_DERIVATIVE_CUTOFF = 2.5;
function smoothingFactor(deltaSeconds, cutoff) {
  const tau = 1 / (2 * Math.PI * Math.max(Number.EPSILON, cutoff));
  return 1 / (1 + tau / Math.max(Number.EPSILON, deltaSeconds));
}
function lowPass(alpha, value, previous) {
  return alpha * value + (1 - alpha) * previous;
}
var OneEuroFilter = class {
  constructor(minCutoff = DEFAULT_MIN_CUTOFF, beta = DEFAULT_BETA, derivativeCutoff = DEFAULT_DERIVATIVE_CUTOFF) {
    this.minCutoff = minCutoff;
    this.beta = beta;
    this.derivativeCutoff = derivativeCutoff;
  }
  previousTime = null;
  previousValue = null;
  previousDerivative = 0;
  reset() {
    this.previousTime = null;
    this.previousValue = null;
    this.previousDerivative = 0;
  }
  filter(value, timeSeconds) {
    if (this.previousTime == null || this.previousValue == null || timeSeconds <= this.previousTime) {
      this.previousTime = timeSeconds;
      this.previousValue = value;
      this.previousDerivative = 0;
      return value;
    }
    const delta = timeSeconds - this.previousTime;
    const frequency = delta > 0 ? 1 / delta : DEFAULT_FREQUENCY;
    const derivative = (value - this.previousValue) * frequency;
    const derivativeAlpha = smoothingFactor(delta, this.derivativeCutoff);
    const filteredDerivative = lowPass(derivativeAlpha, derivative, this.previousDerivative);
    const cutoff = this.minCutoff + this.beta * Math.abs(filteredDerivative);
    const filtered = lowPass(smoothingFactor(delta, cutoff), value, this.previousValue);
    this.previousTime = timeSeconds;
    this.previousValue = filtered;
    this.previousDerivative = filteredDerivative;
    return filtered;
  }
};

// src/features/clipper/engine/autoflip/salience/salient-region.util.ts
var clamp01 = (value) => Math.max(0, Math.min(1, value));
var MAX_KEYFRAME_SAMPLE_DELTA_SEC = 0.16;
var SIGNAL_WEIGHTS = {
  face_core: { minScore: 0.85, maxScore: 0.9, required: false },
  face_all: { minScore: 0.8, maxScore: 0.85, required: false },
  face_full: { minScore: 0.8, maxScore: 0.85, required: false },
  pose_head: { minScore: 0.78, maxScore: 0.82, required: false },
  pose_torso: { minScore: 0.76, maxScore: 0.81, required: false },
  human: { minScore: 0.75, maxScore: 0.8, required: false },
  pet: { minScore: 0.7, maxScore: 0.75, required: false },
  car: { minScore: 0.7, maxScore: 0.75, required: false },
  object: { minScore: 0.1, maxScore: 0.2, required: false },
  head: { minScore: 0.78, maxScore: 0.88, required: false },
  screen: { minScore: 0.72, maxScore: 0.88, required: false },
  motion: { minScore: 0.45, maxScore: 0.7, required: false },
  active_speaker: { minScore: 0.82, maxScore: 0.98, required: false }
};
var PET_LABELS = /* @__PURE__ */ new Set(["cat", "dog", "bird", "horse"]);
var CAR_LABELS = /* @__PURE__ */ new Set(["car", "truck"]);
function mapDetectionLabel(label) {
  const normalized = label.toLowerCase();
  if (normalized === "person") return "human";
  if (PET_LABELS.has(normalized)) return "pet";
  if (CAR_LABELS.has(normalized)) return "car";
  return "object";
}
function weightedScore(rawScore, signalType) {
  const weights = SIGNAL_WEIGHTS[signalType];
  const clamped = clamp01(rawScore);
  return weights.minScore + clamped * (weights.maxScore - weights.minScore);
}
function faceRegionsFromDetection(face) {
  const points = face.keypoints.length >= 4 ? face.keypoints : [];
  const boxFrom = (items) => {
    if (!items.length) return face.box;
    const xs = items.map((point) => point.x);
    const ys = items.map((point) => point.y);
    const x = Math.max(0, Math.min(...xs));
    const y = Math.max(0, Math.min(...ys));
    return { x, y, width: Math.min(1, Math.max(...xs)) - x, height: Math.min(1, Math.max(...ys)) - y };
  };
  const core = boxFrom(points.slice(0, 4));
  const all = boxFrom(points.slice(0, 6));
  return [
    // VisualScorer's default is area-only and it evaluates each emitted
    // landmark rectangle independently.
    { box: core, score: weightedScore(clamp01(core.width * core.height), "face_core"), signalType: "face_core", isRequired: false, trackId: face.trackId, predicted: face.predicted, associationConfidence: face.associationConfidence, identityAmbiguous: face.identityAmbiguous, projectIdentityId: face.projectIdentityId, trust: "verified-person" },
    { box: all, score: weightedScore(clamp01(all.width * all.height), "face_all"), signalType: "face_all", isRequired: false, trackId: face.trackId, predicted: face.predicted, associationConfidence: face.associationConfidence, identityAmbiguous: face.identityAmbiguous, projectIdentityId: face.projectIdentityId, trust: "verified-person" },
    // Landmarks describe the facial core, not the visible extent of the
    // subject. Keep that precision for focus scoring while also carrying the
    // detector's full face rectangle into coverage and pair geometry. This is
    // detector-agnostic and prevents tightly clustered landmarks from making
    // a real foreground person look smaller than a background head.
    { box: face.box, score: weightedScore(clamp01(face.box.width * face.box.height), "face_full"), signalType: "face_full", isRequired: false, trackId: face.trackId, predicted: face.predicted, associationConfidence: face.associationConfidence, identityAmbiguous: face.identityAmbiguous, projectIdentityId: face.projectIdentityId, trust: "verified-person" }
  ];
}
function regionsFromDetections(detections, verifiedCanonicalIds) {
  return detections.flatMap((detection) => {
    const signalType = mapDetectionLabel(detection.label);
    const trust = signalType === "human" ? detection.detectorSource === "pose" || detection.canonicalId != null && verifiedCanonicalIds.has(detection.canonicalId) ? "verified-person" : "unverified-person" : "object";
    const specific = {
      box: detection.box,
      // LocalizationToRegionCalculator sets raw score to one, independent of
      // the detector confidence that already passed the graph threshold.
      score: weightedScore(1, signalType),
      detectorConfidence: detection.score,
      signalType,
      // The reference AutoFlip graph marks every configured signal optional.
      isRequired: false,
      trackId: detection.trackId,
      predicted: detection.predicted,
      associationConfidence: detection.associationConfidence,
      identityAmbiguous: detection.identityAmbiguous,
      projectIdentityId: detection.projectIdentityId,
      trust
    };
    return signalType === "object" ? [specific] : [specific, { ...specific, score: weightedScore(1, "object"), signalType: "object" }];
  });
}
var POSE_HEAD_COVERAGE_THRESHOLD = 0.4;
var POSE_FILTER_RESET_GAP_SEC = 1;
function clampBox(box) {
  const x = clamp01(box.x);
  const y = clamp01(box.y);
  return { x, y, width: Math.max(0, Math.min(1 - x, box.width)), height: Math.max(0, Math.min(1 - y, box.height)) };
}
var BoxOneEuroFilter = class {
  filters = Array.from({ length: 4 }, () => new OneEuroFilter());
  filter(box, time) {
    return clampBox({
      x: this.filters[0].filter(box.x, time),
      y: this.filters[1].filter(box.y, time),
      width: this.filters[2].filter(box.width, time),
      height: this.filters[3].filter(box.height, time)
    });
  }
};
function smoothPoseSamples(samples, sceneCuts) {
  const states = /* @__PURE__ */ new Map();
  let lastTime = -Infinity;
  return [...samples].sort((a, b) => a.time - b.time).map((sample) => {
    if (sceneCuts.some((cut) => cut > lastTime + 1e-9 && cut <= sample.time + 1e-9)) states.clear();
    lastTime = sample.time;
    return {
      ...sample,
      poseSubjects: sample.poseSubjects?.map((pose, index) => {
        const key = pose.trackId != null ? `t${pose.trackId}` : `i${index}`;
        let state = states.get(key);
        if (!state || sample.time - state.lastTime > POSE_FILTER_RESET_GAP_SEC) {
          state = { lastTime: sample.time, box: new BoxOneEuroFilter(), head: new BoxOneEuroFilter(), torso: new BoxOneEuroFilter() };
          states.set(key, state);
        }
        state.lastTime = sample.time;
        return {
          ...pose,
          box: state.box.filter(pose.box, sample.time),
          headBox: pose.headBox ? state.head.filter(pose.headBox, sample.time) : void 0,
          torsoBox: pose.torsoBox ? state.torso.filter(pose.torsoBox, sample.time) : void 0
        };
      })
    };
  });
}
function poseRegions(poses, faces, preferTorso) {
  const regions = [];
  for (const pose of poses) {
    if (pose.predicted) continue;
    if (pose.headBox && faces.some((face) => boxesIntersect(pose.headBox, face.box))) continue;
    const head = pose.headBox;
    const chosen = preferTorso || pose.trackId == null ? pose.torsoBox ?? head : head ?? pose.torsoBox;
    if (!chosen || chosen.width <= 0 || chosen.height <= 0) continue;
    const signalType = chosen === head ? "pose_head" : "pose_torso";
    regions.push({
      box: chosen,
      score: weightedScore(pose.score, signalType),
      signalType,
      isRequired: false,
      trackId: pose.trackId,
      predicted: pose.predicted,
      associationConfidence: pose.associationConfidence,
      identityAmbiguous: pose.identityAmbiguous,
      projectIdentityId: pose.projectIdentityId,
      trust: "verified-person"
    });
  }
  return regions;
}
var HEAD_BAND_WIDTH_FRACTION = 0.6;
var HEAD_BAND_HEIGHT_FRACTION = 0.22;
var HEAD_MIN_DETECTION_SCORE = 0.5;
function boxesIntersect(a, b) {
  return Math.min(a.x + a.width, b.x + b.width) > Math.max(a.x, b.x) && Math.min(a.y + a.height, b.y + b.height) > Math.max(a.y, b.y);
}
function syntheticHeadRegions(detections, faces, verifiedCanonicalIds) {
  const regions = [];
  for (const detection of detections) {
    if (mapDetectionLabel(detection.label) !== "human") continue;
    if (detection.predicted || detection.score < HEAD_MIN_DETECTION_SCORE) continue;
    if (detection.detectorSource !== "pose" && (detection.canonicalId == null || !verifiedCanonicalIds.has(detection.canonicalId))) continue;
    const box = detection.box;
    const head = {
      x: box.x + box.width * (1 - HEAD_BAND_WIDTH_FRACTION) / 2,
      y: box.y,
      width: box.width * HEAD_BAND_WIDTH_FRACTION,
      height: box.height * HEAD_BAND_HEIGHT_FRACTION
    };
    if (head.width <= 0 || head.height <= 0) continue;
    if (faces.some((face) => boxesIntersect(head, face.box))) continue;
    regions.push({
      box: head,
      score: weightedScore(0.5, "face_full"),
      signalType: "face_full",
      isRequired: false,
      trackId: detection.trackId,
      associationConfidence: detection.associationConfidence,
      identityAmbiguous: detection.identityAmbiguous,
      projectIdentityId: detection.projectIdentityId,
      trust: "verified-person"
    });
  }
  return regions;
}
function nearest(items, time, maxDelta) {
  let best = null;
  let delta = maxDelta;
  for (const item of items) {
    const distance = Math.abs(item.time - time);
    if (distance < delta) {
      best = item;
      delta = distance;
    }
  }
  return best;
}
function buildSalientKeyframes(input2) {
  const interval = input2.keyframeIntervalSec ?? AUTOFLIP_KEYFRAME_INTERVAL_SEC;
  const smoothedDetections = smoothPoseSamples(input2.detections, input2.sceneCuts);
  const boundaries = [input2.clipStart, ...input2.sceneCuts.filter((cut) => cut > input2.clipStart && cut < input2.clipEnd), input2.clipEnd].sort((a, b) => a - b);
  const preferTorsoByScene = boundaries.slice(0, -1).map((start, index) => {
    const end = boundaries[index + 1];
    const poseFrames = smoothedDetections.filter((sample) => sample.time >= start - 1e-9 && sample.time <= end + 1e-9 && (sample.poseSubjects?.length ?? 0) > 0);
    if (!poseFrames.length) return false;
    const headFrames = poseFrames.filter((sample) => sample.poseSubjects.some((pose) => pose.headBox != null));
    return headFrames.length / poseFrames.length < POSE_HEAD_COVERAGE_THRESHOLD;
  });
  const keyframes = [];
  for (let time = input2.clipStart; time <= input2.clipEnd + 1e-9; time += interval) {
    const detectionSample = nearest(smoothedDetections, time, Math.max(interval / 2, MAX_KEYFRAME_SAMPLE_DELTA_SEC));
    const nextBoundaryIndex = boundaries.findIndex((boundary) => boundary > time + 1e-9);
    const sceneIndex = nextBoundaryIndex < 0 ? preferTorsoByScene.length - 1 : Math.max(0, Math.min(preferTorsoByScene.length - 1, nextBoundaryIndex - 1));
    const faces = detectionSample?.autoflipFaces ?? [];
    const verifiedCanonicalIds = new Set((detectionSample?.canonicalPersons ?? []).filter((person) => !person.identityAmbiguous && (person.sources.includes("face") || person.sources.includes("pose"))).map((person) => person.canonicalId));
    const regions = [
      ...regionsFromDetections(detectionSample?.detections ?? [], verifiedCanonicalIds),
      ...faces.flatMap(faceRegionsFromDetection),
      ...poseRegions(detectionSample?.poseSubjects ?? [], faces, preferTorsoByScene[sceneIndex] ?? false),
      ...syntheticHeadRegions(detectionSample?.detections ?? [], faces, verifiedCanonicalIds)
    ];
    const isShotChange = input2.sceneCuts.some((cut) => Math.abs(cut - time) <= interval * 0.6);
    keyframes.push({ time, regions, isShotChange });
  }
  return keyframes;
}

// src/features/clipper/engine/autoflip/salience/importance-ranker.util.ts
var clamp012 = (value) => Math.max(0, Math.min(1, value));
var SIGNAL_POLICY = {
  face_core: { kind: "face", source: "face", prior: 0.82 },
  face_all: { kind: "face", source: "face", prior: 0.8 },
  face_full: { kind: "head", source: "head", prior: 0.76 },
  pose_head: { kind: "head", source: "pose", prior: 0.7 },
  pose_torso: { kind: "action", source: "pose", prior: 0.58 },
  human: { kind: "person", source: "person", prior: 0.62 },
  pet: { kind: "object", source: "object", prior: 0.58 },
  car: { kind: "object", source: "object", prior: 0.58 },
  object: { kind: "object", source: "object", prior: 0.32 },
  head: { kind: "head", source: "head", prior: 0.82 },
  screen: { kind: "screen", source: "object", prior: 0.82 },
  motion: { kind: "action", source: "motion", prior: 0.66 },
  active_speaker: { kind: "speaker", source: "active-speaker", prior: 0.96 }
};
var EXTERNAL_SIGNAL_TYPE = {
  "active-speaker": "active_speaker",
  head: "head",
  screen: "screen",
  motion: "motion"
};
var TEMPORAL_PERSON_MIN_OBSERVATIONS = 3;
var TEMPORAL_PERSON_MIN_SPAN_SEC = 0.35;
var TEMPORAL_PERSON_MAX_GAP_SEC = 0.75;
var TEMPORAL_PERSON_MAX_HOLD_SEC = 1.2;
var TEMPORAL_PERSON_MIN_DETECTOR_CONFIDENCE = 0.25;
var TEMPORAL_PERSON_MIN_ASSOCIATION_CONFIDENCE = 0.6;
var CONVERSATION_PAIR_HOLD_SEC = 0.5;
var CONVERSATION_SLOT_MAX_CENTER_DELTA = 0.12;
var GROUP_THIRD_MIN_AREA_RATIO = 0.5;
var TARGET_RETENTION_MARGIN = 0.04;
var FACE_PRIMARY_MIN_AREA_RATIO = 1 / 16;
var FACE_FOCUS_MIN_OVERLAP = 0.3;
var PAIR_MAX_PRIMARY_WIDTH_FACTOR = 2.5;
function boxArea(box) {
  return Math.max(0, box.width) * Math.max(0, box.height);
}
function intersectionArea(a, b) {
  const width = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
  const height = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
  return width * height;
}
function overlapFractionOfSmaller(a, b) {
  const smaller = Math.min(boxArea(a), boxArea(b));
  return smaller > 0 ? intersectionArea(a, b) / smaller : 0;
}
function unionBoxes(a, b) {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const right = Math.max(a.x + a.width, b.x + b.width);
  const bottom = Math.max(a.y + a.height, b.y + b.height);
  return { x, y, width: right - x, height: bottom - y };
}
function centerX(box) {
  return box.x + box.width / 2;
}
function isHumanRegion(region) {
  return region.kind === "face" || region.kind === "head" || region.kind === "speaker" || region.kind === "person";
}
function humanSemanticQuality(region) {
  if (region.kind === "face" || region.kind === "speaker") return 1;
  if (region.kind === "head") return 0.95;
  if (region.kind === "person") return 0.72;
  return 0;
}
function targetSelectionScore(region, maximumFocusArea) {
  const prominence = maximumFocusArea > 0 ? Math.sqrt(Math.min(1, boxArea(region.box) / maximumFocusArea)) : 0;
  return region.importanceScore * 0.3 + humanSemanticQuality(region) * 0.55 + prominence * 0.15;
}
function rememberedConversationPair(eligible, time, state) {
  const memory = state?.memory;
  if (!memory || time - memory.lastObservedAt > CONVERSATION_PAIR_HOLD_SEC) return null;
  const humans = eligible.filter(isHumanRegion);
  const byId = memory.ids.map((id) => humans.find((region) => region.id === id));
  if (byId[0] && byId[1] && byId[0].id !== byId[1].id) return [byId[0], byId[1]];
  const nearestSlot = (center2, excludedId) => humans.filter((region) => region.id !== excludedId).filter((region) => Math.abs(centerX(region.contentBox) - center2) <= CONVERSATION_SLOT_MAX_CENTER_DELTA).sort((a, b) => Math.abs(centerX(a.contentBox) - center2) - Math.abs(centerX(b.contentBox) - center2))[0];
  const left = nearestSlot(memory.centers[0]);
  const right = nearestSlot(memory.centers[1], left?.id);
  return left && right ? [left, right] : null;
}
function rememberConversationPair(pair, time, state) {
  if (!state) return;
  const ordered = [...pair].sort((a, b) => centerX(a.contentBox) - centerX(b.contentBox));
  state.memory = {
    ids: [ordered[0].id, ordered[1].id],
    centers: [centerX(ordered[0].contentBox), centerX(ordered[1].contentBox)],
    lastObservedAt: time
  };
}
function isFaceLike(region) {
  return region.kind === "face" || region.kind === "speaker" || region.sources.includes("face") || region.sources.includes("active-speaker");
}
function preferFacePrimaryPool(eligible) {
  if (!eligible.length) return eligible;
  const facePool = eligible.filter(isFaceLike);
  if (!facePool.length) return eligible;
  const bestArea = boxArea(eligible[0].box);
  const competitive = facePool.filter((face) => boxArea(face.box) >= bestArea * FACE_PRIMARY_MIN_AREA_RATIO);
  return competitive.length ? competitive : eligible;
}
function pairFitsSharedCrop(primary, secondary) {
  const left = Math.min(primary.contentBox.x, secondary.contentBox.x);
  const right = Math.max(
    primary.contentBox.x + primary.contentBox.width,
    secondary.contentBox.x + secondary.contentBox.width
  );
  const primaryWidth = Math.max(1e-9, primary.contentBox.width);
  return right - left <= primaryWidth * PAIR_MAX_PRIMARY_WIDTH_FACTOR;
}
function shouldPromoteSecondary(primary, secondary) {
  if (isFaceLike(primary) && !isFaceLike(secondary) && !pairFitsSharedCrop(primary, secondary)) {
    return false;
  }
  return true;
}
function isMeaningfulThirdPerson(pair, third) {
  if (!third || !isHumanRegion(third)) return false;
  const largerPairArea = Math.max(boxArea(pair[0].contentBox), boxArea(pair[1].contentBox));
  const minimumPairSemanticQuality = Math.min(...pair.map(humanSemanticQuality));
  return largerPairArea > 0 && boxArea(third.contentBox) >= largerPairArea * GROUP_THIRD_MIN_AREA_RATIO && humanSemanticQuality(third) >= minimumPairSemanticQuality - 0.15 && overlapFractionOfSmaller(third.contentBox, pair[0].contentBox) < 0.7 && overlapFractionOfSmaller(third.contentBox, pair[1].contentBox) < 0.7;
}
function signalCandidate(region) {
  const policy = SIGNAL_POLICY[region.signalType];
  const confidence = clamp012(region.score);
  let evidence = policy.prior * 0.68 + confidence * 0.32;
  if (region.predicted) evidence *= 0.42;
  const centerX2 = region.box.x + region.box.width / 2;
  const centerDistance3 = Math.abs(centerX2 - 0.5) * 2;
  evidence *= 1 - Math.min(0.05, centerDistance3 * 0.05);
  return {
    box: region.box,
    evidence: clamp012(evidence),
    confidence,
    detectorConfidence: region.detectorConfidence,
    kind: policy.kind,
    source: policy.source,
    trackId: region.trackId,
    predicted: region.predicted,
    associationConfidence: region.associationConfidence,
    identityAmbiguous: region.identityAmbiguous,
    projectIdentityId: region.projectIdentityId,
    trust: region.trust ?? (policy.kind === "person" || policy.kind === "face" || policy.kind === "head" || policy.kind === "speaker" ? "unverified-person" : "object")
  };
}
function belongsToCluster(candidate, cluster) {
  if (candidate.projectIdentityId != null && cluster.projectIdentityId != null) {
    return candidate.projectIdentityId === cluster.projectIdentityId;
  }
  if (candidate.trackId != null && cluster.trackId === candidate.trackId && !candidate.identityAmbiguous && cluster.candidates.every((existing) => !existing.identityAmbiguous)) return true;
  return cluster.candidates.some((existing) => overlapFractionOfSmaller(candidate.box, existing.box) >= 0.48);
}
function clusterCandidates(regions) {
  const candidates = regions.filter((region) => region.box.width > 0 && region.box.height > 0).map(signalCandidate).sort((a, b) => b.evidence - a.evidence);
  const clusters = [];
  for (const candidate of candidates) {
    const cluster = clusters.find((item) => belongsToCluster(candidate, item));
    if (cluster) {
      cluster.candidates.push(candidate);
      cluster.trackId ??= candidate.trackId;
      cluster.projectIdentityId ??= candidate.projectIdentityId;
    } else {
      clusters.push({ candidates: [candidate], trackId: candidate.trackId, projectIdentityId: candidate.projectIdentityId });
    }
  }
  return clusters;
}
function clusterRegion(cluster) {
  const ordered = [...cluster.candidates].sort((a, b) => b.evidence - a.evidence);
  const semantic = ordered.filter((candidate) => candidate.source !== "motion");
  if (!semantic.length) throw new Error("motion-only importance cluster");
  const topSemantic = semantic[0];
  const faceFocus = semantic.find((candidate) => candidate.kind === "face" || candidate.kind === "speaker");
  const focus = faceFocus && overlapFractionOfSmaller(faceFocus.box, topSemantic.box) >= FACE_FOCUS_MIN_OVERLAP ? faceFocus : topSemantic;
  const sources = [...new Set(ordered.map((candidate) => candidate.source))];
  const semanticEvidence = 1 - semantic.reduce((remaining, candidate) => remaining * (1 - candidate.evidence), 1);
  const motionBoost = ordered.some((candidate) => candidate.source === "motion") ? 0.12 : 0;
  const combinedEvidence = Math.min(1, semanticEvidence + motionBoost);
  const shouldPreserveContext = focus.kind === "person" || focus.kind === "action" || focus.kind === "screen" || focus.kind === "object";
  const contextCandidates = shouldPreserveContext ? semantic.filter((candidate) => candidate.source !== "face" && candidate.source !== "head") : semantic.filter((candidate) => candidate.source === "face" || candidate.source === "head" || candidate.source === "active-speaker");
  const contentBox = (contextCandidates.length ? contextCandidates : [focus]).reduce((box, candidate) => unionBoxes(box, candidate.box), (contextCandidates[0] ?? focus).box);
  const trust = semantic.some((candidate) => candidate.trust === "verified-person") ? "verified-person" : semantic.some((candidate) => candidate.trust === "unverified-person") ? "unverified-person" : semantic.some((candidate) => candidate.trust === "object") ? "object" : "unverified-person";
  return {
    box: focus.box,
    contentBox,
    kind: focus.kind,
    importanceScore: clamp012(combinedEvidence),
    confidence: Math.max(...ordered.map((candidate) => candidate.confidence)),
    detectorConfidence: Math.max(...ordered.map((candidate) => candidate.detectorConfidence ?? 0)),
    sources,
    trackId: cluster.trackId,
    predicted: ordered.every((candidate) => candidate.predicted),
    associationConfidence: Math.min(...ordered.map((candidate) => candidate.associationConfidence ?? 1)),
    identityAmbiguous: ordered.some((candidate) => candidate.identityAmbiguous),
    projectIdentityId: cluster.projectIdentityId,
    trust
  };
}
function stableUntrackedId(region) {
  const x = Math.round((region.box.x + region.box.width / 2) * 20);
  const y = Math.round((region.box.y + region.box.height / 2) * 20);
  return `region:${region.kind}:${x}:${y}`;
}
function matchPreviousId(region, previous) {
  if (region.trackId != null) {
    const isCanonicalPerson = region.sources.some((source) => source === "person" || source === "pose" || source === "face" || source === "head" || source === "active-speaker");
    if (isCanonicalPerson) return `canonical-person:${region.trackId}`;
    const namespace = ["person", "pose", "face", "head", "active-speaker", "object"].find((source) => region.sources.includes(source)) ?? region.sources[0] ?? "unknown";
    return `track:${namespace}:${region.trackId}`;
  }
  const best = previous.map((candidate) => ({ candidate, overlap: overlapFractionOfSmaller(region.box, candidate.box) })).filter(({ candidate, overlap }) => candidate.kind === region.kind && overlap >= 0.35).sort((a, b) => b.overlap - a.overlap)[0]?.candidate;
  return best?.id ?? stableUntrackedId(region);
}
function isTemporalPersonCandidate(region) {
  return region.kind === "person" && region.trust === "unverified-person" && region.trackId != null && !region.predicted && !region.identityAmbiguous && (region.detectorConfidence ?? 0) >= TEMPORAL_PERSON_MIN_DETECTOR_CONFIDENCE && (region.associationConfidence ?? 0) >= TEMPORAL_PERSON_MIN_ASSOCIATION_CONFIDENCE;
}
function observeTemporalPeople(ranked, time, state) {
  const qualified = /* @__PURE__ */ new Set();
  for (const [id, observation] of state.observations) {
    if (time - observation.lastObservedAt > TEMPORAL_PERSON_MAX_HOLD_SEC) state.observations.delete(id);
  }
  for (const region of ranked.filter(isTemporalPersonCandidate)) {
    const prior = state.observations.get(region.id);
    const continuous = prior != null && time - prior.lastObservedAt <= TEMPORAL_PERSON_MAX_GAP_SEC;
    const observation = continuous ? { count: prior.count + 1, startedAt: prior.startedAt, lastObservedAt: time } : { count: 1, startedAt: time, lastObservedAt: time };
    state.observations.set(region.id, observation);
    if (observation.count >= TEMPORAL_PERSON_MIN_OBSERVATIONS && time - observation.startedAt >= TEMPORAL_PERSON_MIN_SPAN_SEC) qualified.add(region.id);
  }
  for (const region of ranked) {
    if (!region.predicted || region.trust !== "unverified-person") continue;
    const observation = state.observations.get(region.id);
    if (observation && time - observation.lastObservedAt <= TEMPORAL_PERSON_MAX_HOLD_SEC && observation.count >= TEMPORAL_PERSON_MIN_OBSERVATIONS && time - observation.startedAt >= TEMPORAL_PERSON_MIN_SPAN_SEC) {
      qualified.add(region.id);
    }
  }
  return qualified;
}
function evidenceSummary(ranked, qualifiedTemporalIds, status) {
  return {
    status,
    verifiedPersonCount: ranked.filter((region) => region.trust === "verified-person").length,
    unverifiedPersonCount: ranked.filter((region) => (region.trust === "unverified-person" || region.trust === "temporally-qualified-person") && region.kind === "person").length,
    temporallyQualifiedPersonCount: qualifiedTemporalIds.size
  };
}
function rankFrame(regions, time, previous, compositionScores, temporalPersonState, conversationPairState) {
  const clusters = clusterCandidates(regions).filter((cluster) => cluster.candidates.some((candidate) => candidate.source !== "motion")).filter((cluster) => !cluster.candidates.some((candidate) => candidate.identityAmbiguous));
  const ranked = clusters.map((cluster) => {
    const region = clusterRegion(cluster);
    const id = matchPreviousId(region, previous);
    const previousRegion = previous.find((candidate) => candidate.id === id);
    const localImportanceScore = previousRegion ? clamp012(region.importanceScore * 0.72 + previousRegion.importanceScore * 0.28 + 0.025) : region.importanceScore;
    const compositionScore = region.projectIdentityId == null ? void 0 : compositionScores?.get(region.projectIdentityId);
    const importanceScore = compositionScore == null ? localImportanceScore : clamp012(localImportanceScore * 0.58 + compositionScore * 0.42);
    return { ...region, id, importanceScore, compositionScore, required: false, role: "candidate" };
  }).sort((a, b) => b.importanceScore - a.importanceScore);
  if (!ranked.length) return { regions: ranked, targetEvidence: evidenceSummary(ranked, /* @__PURE__ */ new Set(), "no-candidate") };
  const verifiedPeople = ranked.filter((region) => region.trust === "verified-person");
  const qualifiedTemporalIds = temporalPersonState ? observeTemporalPeople(ranked, time, temporalPersonState) : /* @__PURE__ */ new Set();
  const eligibleUnordered = verifiedPeople.length ? verifiedPeople : ranked.filter((region) => region.trust === "object");
  const maximumFocusArea = Math.max(0, ...eligibleUnordered.filter(isHumanRegion).map((region) => boxArea(region.box)));
  const eligible = [...eligibleUnordered].sort((left, right) => targetSelectionScore(right, maximumFocusArea) - targetSelectionScore(left, maximumFocusArea));
  if (!eligible.length) {
    const temporalPrimary = ranked.find((region) => qualifiedTemporalIds.has(region.id));
    if (!temporalPrimary) {
      const hasPendingTemporalPerson = ranked.some(isTemporalPersonCandidate);
      return {
        regions: ranked,
        targetEvidence: evidenceSummary(ranked, qualifiedTemporalIds, hasPendingTemporalPerson ? "temporal-pending" : "no-candidate")
      };
    }
    temporalPrimary.trust = "temporally-qualified-person";
    temporalPrimary.role = "primary";
    temporalPrimary.required = true;
    return {
      regions: ranked,
      targetEvidence: evidenceSummary(ranked, qualifiedTemporalIds, "qualified")
    };
  }
  const primaryPool = preferFacePrimaryPool(eligible);
  const priorPrimary = previous.find((region) => region.role === "primary" && region.trust !== "unverified-person");
  const retainedPrimary = priorPrimary ? primaryPool.find((region) => region.id === priorPrimary.id && targetSelectionScore(region, maximumFocusArea) >= targetSelectionScore(primaryPool[0], maximumFocusArea) - TARGET_RETENTION_MARGIN) : void 0;
  const rememberedPair = rememberedConversationPair(eligible, time, conversationPairState);
  const rememberedPrimary = rememberedPair?.find((region) => primaryPool.some((candidate) => candidate.id === region.id));
  const primary = rememberedPair?.find((region) => region.id === retainedPrimary?.id && primaryPool.some((c) => c.id === region.id)) ?? rememberedPrimary ?? retainedPrimary ?? primaryPool[0];
  primary.role = "primary";
  primary.required = true;
  const topThree = eligible.slice(0, 3);
  const groupPair = rememberedPair ?? (topThree[0] && topThree[1] ? [topThree[0], topThree[1]] : null);
  if (topThree.length === 3 && topThree.every(isHumanRegion) && targetSelectionScore(topThree[2], maximumFocusArea) >= targetSelectionScore(topThree[1], maximumFocusArea) * 0.85 && groupPair != null && isMeaningfulThirdPerson(groupPair, topThree.find((region) => !groupPair.some((member) => member.id === region.id)))) {
    primary.kind = "action";
    primary.contentBox = topThree.reduce(
      (box, region) => unionBoxes(box, region.contentBox),
      topThree[0].contentBox
    );
    for (const region of ranked) {
      if (region.id === primary.id) continue;
      region.role = "candidate";
      region.required = false;
    }
    return { regions: ranked, targetEvidence: evidenceSummary(ranked, qualifiedTemporalIds, "qualified") };
  }
  const secondaryCandidate = rememberedPair?.find((region) => region.id !== primary.id) ?? eligible.find(
    (region) => region.id !== primary.id && region.importanceScore >= 0.5 && region.importanceScore >= primary.importanceScore * 0.68 && overlapFractionOfSmaller(region.contentBox, primary.contentBox) < 0.7
  );
  const secondary = secondaryCandidate && shouldPromoteSecondary(primary, secondaryCandidate) ? secondaryCandidate : void 0;
  if (secondary) {
    secondary.role = "secondary";
    secondary.required = true;
    rememberConversationPair([primary, secondary], time, conversationPairState);
  }
  return { regions: ranked, targetEvidence: evidenceSummary(ranked, qualifiedTemporalIds, "qualified") };
}
function attachImportanceSignals(keyframes, signalSamples) {
  if (!signalSamples?.length) return keyframes;
  return keyframes.map((keyframe) => {
    const nearest2 = signalSamples.map((sample) => ({ sample, delta: Math.abs(sample.time - keyframe.time) })).filter(({ delta }) => delta <= 0.15).sort((a, b) => a.delta - b.delta)[0]?.sample;
    if (!nearest2) return keyframe;
    const added = nearest2.regions.map((region) => ({
      box: region.box,
      score: clamp012(region.confidence),
      signalType: EXTERNAL_SIGNAL_TYPE[region.kind],
      isRequired: false,
      trackId: region.trackId,
      predicted: region.predicted
    }));
    return { ...keyframe, regions: [...keyframe.regions, ...added] };
  });
}
function buildImportanceTimeline(keyframes, compositionScores) {
  let previous = [];
  let previousObservedTime = Number.NEGATIVE_INFINITY;
  const temporalPersonState = { observations: /* @__PURE__ */ new Map() };
  const conversationPairState = { memory: null };
  return keyframes.map((keyframe) => {
    if (keyframe.isShotChange || keyframe.time - previousObservedTime > 0.6) {
      previous = [];
      temporalPersonState.observations.clear();
      conversationPairState.memory = null;
    }
    const ranked = rankFrame(
      keyframe.regions,
      keyframe.time,
      previous,
      compositionScores,
      temporalPersonState,
      conversationPairState
    );
    const regions = ranked.regions;
    if (regions.length) {
      previous = regions;
      previousObservedTime = keyframe.time;
    }
    return {
      time: keyframe.time,
      regions,
      cut: keyframe.isShotChange || void 0,
      targetEvidence: ranked.targetEvidence
    };
  });
}
var importanceGeometry = {
  intersectionArea,
  overlapFractionOfSmaller,
  unionBoxes
};

// src/features/clipper/engine/autoflip/layout/arbiter.util.ts
var EPSILON = 1e-9;
var LEGACY_ARBITER_PARAMS = Object.freeze({
  decisionConfidenceScale: 0.3,
  minimumSemanticScoreGain: 0.05,
  emergencyBaselineCoverage: 0.85
});
var DEFAULT_ARBITER_PARAMS = Object.freeze({
  ...LEGACY_ARBITER_PARAMS,
  allowSplit: true
});
function requiredRegions(sample) {
  return sample.regions.filter((region) => region.required).slice(0, 3);
}
function coveredFraction(viewport, box) {
  const area2 = Math.max(EPSILON, box.width * box.height);
  return clamp(importanceGeometry.intersectionArea(viewport, box) / area2, 0, 1);
}
function proposalScore(viewports, required) {
  if (!required.length || !viewports.length) return 0;
  const totalWeight = required.reduce((sum, region) => sum + Math.max(0.01, region.importanceScore), 0);
  const coverage2 = required.reduce((sum, region) => sum + Math.max(...viewports.map((viewport) => coveredFraction(viewport, region.contentBox))) * region.importanceScore, 0) / totalWeight;
  const primary = required.find((region) => region.role === "primary") ?? required[0];
  const primaryX = primary.box.x + primary.box.width / 2;
  const primaryY = primary.box.y + primary.box.height / 2;
  const distance = Math.min(...viewports.map((viewport) => {
    const dx = primaryX - (viewport.x + viewport.width / 2);
    const dy = primaryY - (viewport.y + viewport.height / 2);
    return Math.hypot(dx, dy);
  }));
  const composition = 1 - clamp(distance / 0.25, 0, 1);
  return coverage2 * 0.7 + composition * 0.3;
}
function precedingIndex(items, time) {
  if (!items.length || time <= items[0].time) return 0;
  if (items.length === 1 || time >= items.at(-1).time) return items.length - 1;
  let low = 1;
  let high = items.length - 1;
  while (low < high) {
    const middle = low + Math.floor((high - low) / 2);
    if (items[middle].time <= time) low = middle + 1;
    else high = middle;
  }
  return items[low].time <= time ? low : low - 1;
}
function interpolateBox(a, b, factor) {
  return {
    x: a.x + (b.x - a.x) * factor,
    y: a.y + (b.y - a.y) * factor,
    width: a.width + (b.width - a.width) * factor,
    height: a.height + (b.height - a.height) * factor
  };
}
function importanceAtTime(samples, time) {
  if (!samples.length) return { time, regions: [], targetEvidence: { status: "no-candidate", verifiedPersonCount: 0, unverifiedPersonCount: 0, temporallyQualifiedPersonCount: 0 } };
  const index = precedingIndex(samples, time);
  const previous = samples[index];
  const next = samples[index + 1];
  if (!previous.regions.length && next?.regions.length && !next.cut && next.time - time <= 0.4 + EPSILON) {
    return { ...next, time, cut: previous.cut };
  }
  if (!next || next.cut || next.time <= previous.time + EPSILON) return { ...previous, time };
  const factor = clamp((time - previous.time) / (next.time - previous.time), 0, 1);
  const regions = previous.regions.map((region) => {
    const nextRegion = next.regions.find((candidate) => candidate.id === region.id);
    return nextRegion ? {
      ...region,
      box: interpolateBox(region.box, nextRegion.box, factor),
      contentBox: interpolateBox(region.contentBox, nextRegion.contentBox, factor),
      importanceScore: region.importanceScore + (nextRegion.importanceScore - region.importanceScore) * factor
    } : region;
  });
  return { time, regions, cut: previous.cut, targetEvidence: previous.targetEvidence };
}
function decideLayoutStrategy(ctx, params) {
  const modeAllowed = ctx.desiredMode === "single-crop" || ctx.desiredMode === "split" && params.allowSplit === true;
  const controllerApproved = ctx.controllerReasonCodes != null;
  const scoreGain = ctx.semanticScore - ctx.baselineScore;
  const minimumGain = params.minimumSemanticScoreGain ?? 0.05;
  const emergencyCoverage = params.emergencyBaselineCoverage ?? 0.85;
  const baselineUnsafe = (ctx.baselineCoverage ?? 1) < emergencyCoverage;
  const scoreApproved = scoreGain >= minimumGain || baselineUnsafe;
  const selectSemantic = modeAllowed && controllerApproved && scoreApproved;
  const strategy = selectSemantic ? ctx.desiredMode === "split" ? "semantic-split" : "semantic-single" : "legacy-baseline";
  const reasonCodes = selectSemantic ? [
    "visibility-controller",
    ...ctx.controllerReasonCodes ?? [],
    ...baselineUnsafe && scoreGain < minimumGain ? ["baseline-coverage-rescue"] : []
  ] : [
    ...!controllerApproved ? ["no-controller-decision"] : [],
    ...controllerApproved ? ["visibility-controller", ...ctx.controllerReasonCodes ?? []] : [],
    ...controllerApproved && !modeAllowed ? ["mode-not-allowed"] : [],
    ...controllerApproved && modeAllowed && !scoreApproved ? [baselineUnsafe ? "baseline-coverage-unsafe" : "insufficient-semantic-margin"] : []
  ];
  return {
    selectSemantic,
    strategy,
    reasonCodes,
    decisionConfidence: clamp(Math.max(0, ctx.semanticScore - ctx.baselineScore) / params.decisionConfidenceScale, 0, 1)
  };
}

// src/features/clipper/engine/autoflip/layout/visibility-controller.constants.ts
var LEGACY_VISIBILITY_PARAMS = Object.freeze({
  enabled: true,
  lookaheadSec: 0.8,
  envelopeMargin: 0.08,
  velocityMarginSec: 0.25,
  edgeRiskFraction: 0.12,
  widerHoldSec: 0.8,
  splitStableSamples: 8,
  splitMinDurationSec: 3,
  splitExitStableSec: 1.5
});
var DEFAULT_VISIBILITY_PARAMS = Object.freeze({
  ...LEGACY_VISIBILITY_PARAMS,
  splitStableSamples: 8,
  splitPendingSec: 1.5,
  splitMinDurationSec: 3,
  splitExitStableSec: 1.5,
  mergePendingSec: 1.5,
  splitVariant: "v3",
  minimumAssociationConfidence: 0.75,
  maxSwitchesPerMinute: 3,
  riskMergeGapSec: 0.4,
  // A known pair may return over the next two 5 FPS samples without paying
  // the full split-entry debounce again. Longer gaps must be re-confirmed.
  identityHoldSec: 0.5,
  widerHoldSec: 1.2
});
function createVisibilityControllerState() {
  return {
    scene: 0,
    activeMode: "single-crop",
    activeViewportCount: 1,
    modeSince: Number.NEGATIVE_INFINITY,
    riskClearedAt: null,
    lastRiskAt: null,
    panelOrder: [],
    previousViewport: null,
    machineState: "common",
    pendingSince: null,
    lastSplitViewports: [],
    lastSplitPanelSubjects: [],
    identityLostAt: null,
    modeSwitchTimestamps: [],
    sceneStartedAt: 0,
    singlePrimaryId: null,
    pendingSinglePrimaryId: null,
    pendingSinglePrimarySince: null,
    singleViewport: null,
    singleVelocity: { x: 0, y: 0 },
    singleLastUpdatedAt: null
  };
}

// src/features/clipper/engine/autoflip/layout/viewport-geometry.util.ts
var EPSILON2 = 1e-9;
var MAX_SPLIT_VIEWPORT_OVERLAP = 0;
var MIN_SPLIT_VIEWPORT_GAP = 0.1;
function boxesIntersect2(a, b) {
  const overlapX = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
  const overlapY = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
  return overlapX > EPSILON2 && overlapY > EPSILON2;
}
function splitViewportsAreDistinct(viewports, minGap = MIN_SPLIT_VIEWPORT_GAP) {
  if (viewports.length < 2) return true;
  return viewports.every((viewport, index) => viewports.slice(index + 1).every((other) => {
    if (boxesIntersect2(viewport, other)) return false;
    if (importanceGeometry.overlapFractionOfSmaller(viewport, other) > MAX_SPLIT_VIEWPORT_OVERLAP + EPSILON2) {
      return false;
    }
    const gapX = Math.max(viewport.x, other.x) - Math.min(viewport.x + viewport.width, other.x + other.width);
    const gapY = Math.max(viewport.y, other.y) - Math.min(viewport.y + viewport.height, other.y + other.height);
    const minDistance = Math.max(gapX, gapY);
    return minDistance >= minGap - EPSILON2;
  }));
}
function splitPanelsPreserveSubjects(viewports, panelSubjects) {
  if (!panelSubjects) return true;
  if (viewports.length < 2 || viewports.length !== panelSubjects.length) return false;
  return panelSubjects.every((subject, index) => containsBox(viewports[index], subject.focusBox) && viewports.every((viewport, otherIndex) => otherIndex === index || !boxesIntersect2(viewport, subject.focusBox)));
}
function fitSeparatedSplitPanels(panelRegions, sourceAspect, targetAspects, minGap = MIN_SPLIT_VIEWPORT_GAP, minScaleThreshold = 0.35) {
  if (panelRegions.length !== targetAspects.length) return null;
  const panelSubjects = panelRegions.map((region) => ({ id: region.id, focusBox: region.box }));
  const scaleMultipliers = [1, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5, 0.45, 0.4, 0.35];
  for (const k of scaleMultipliers) {
    const panels = panelRegions.map((region, index) => {
      const targetAspect = targetAspects[index];
      const nominal = nominalCropSize(sourceAspect, targetAspect);
      const rawScale = Math.max(
        minScaleThreshold,
        region.contentBox.width / Math.max(EPSILON2, nominal.width),
        region.contentBox.height / Math.max(EPSILON2, nominal.height)
      );
      const clampedScale = Math.min(1, Math.max(minScaleThreshold, rawScale * k));
      const width = nominal.width * clampedScale;
      const height = nominal.height * clampedScale;
      const faceCenter = {
        x: region.box.x + region.box.width / 2,
        y: region.box.y + region.box.height * framingCenterYFraction(region.box, height)
      };
      if (region.contentBox.width > width + EPSILON2 || region.contentBox.height > height + EPSILON2) {
        return null;
      }
      const minimumX = Math.max(0, region.contentBox.x + region.contentBox.width - width);
      const maximumX = Math.min(1 - width, region.contentBox.x);
      const minimumY = Math.max(0, region.contentBox.y + region.contentBox.height - height);
      const maximumY = Math.min(1 - height, region.contentBox.y);
      if (minimumX > maximumX + EPSILON2 || minimumY > maximumY + EPSILON2) return null;
      return {
        x: clamp(faceCenter.x - width / 2, minimumX, maximumX),
        y: clamp(faceCenter.y - height / 2, minimumY, maximumY),
        width,
        height
      };
    });
    if (panels.every((panel) => panel != null) && splitViewportsAreDistinct(panels, minGap) && splitPanelsPreserveSubjects(panels, panelSubjects)) {
      return panels;
    }
  }
  return null;
}
function unionAll(boxes) {
  return boxes.reduce(
    (result, box) => result ? importanceGeometry.unionBoxes(result, box) : { ...box },
    null
  );
}
function expandBox(box, margin) {
  const x = clamp(box.x - box.width * margin, 0, 1);
  const y = clamp(box.y - box.height * margin, 0, 1);
  const right = clamp(box.x + box.width * (1 + margin), 0, 1);
  const bottom = clamp(box.y + box.height * (1 + margin), 0, 1);
  return { x, y, width: right - x, height: bottom - y };
}
function nominalCropSize(sourceAspect, targetAspect) {
  if (sourceAspect >= targetAspect) return { width: targetAspect / sourceAspect, height: 1 };
  return { width: 1, height: sourceAspect / targetAspect };
}
function boxFitsStrictCrop(box, sourceAspect, targetAspect) {
  const nominal = nominalCropSize(sourceAspect, targetAspect);
  const expanded = expandBox(box, 0.08);
  return expanded.width <= nominal.width + EPSILON2 && expanded.height <= nominal.height + EPSILON2;
}
var HEADROOM_CENTER_Y = 0.44;
var CENTER_Y = 0.5;
function framingCenterYFraction(subjectBox, cropHeight, headroomFraction = HEADROOM_CENTER_Y) {
  if (cropHeight >= 1 - EPSILON2) return CENTER_Y;
  if (subjectBox.y < 0.04) return CENTER_Y;
  const desiredTop = subjectBox.y + subjectBox.height * headroomFraction - cropHeight / 2;
  if (desiredTop <= 0.02) return CENTER_Y;
  return headroomFraction;
}
function cropAroundBox(box, sourceAspect, targetAspect, minimumScale = 0.3, padding = 0.18, centerYFraction = HEADROOM_CENTER_Y) {
  const nominal = nominalCropSize(sourceAspect, targetAspect);
  const expanded = expandBox(box, padding);
  const scale = clamp(Math.max(
    minimumScale,
    expanded.width / Math.max(EPSILON2, nominal.width),
    expanded.height / Math.max(EPSILON2, nominal.height)
  ), minimumScale, 1);
  const width = nominal.width * scale;
  const height = nominal.height * scale;
  const centerX2 = box.x + box.width / 2;
  const centerY = box.y + box.height * framingCenterYFraction(box, height, centerYFraction);
  return {
    x: clamp(centerX2 - width / 2, 0, 1 - width),
    y: clamp(centerY - height / 2, 0, 1 - height),
    width,
    height
  };
}
function strictAspectViewport(viewport, sourceAspect, targetAspect) {
  const nominal = nominalCropSize(sourceAspect, targetAspect);
  const scale = clamp(Math.max(
    viewport.width / Math.max(EPSILON2, nominal.width),
    viewport.height / Math.max(EPSILON2, nominal.height)
  ), 0.05, 1);
  const width = nominal.width * scale;
  const height = nominal.height * scale;
  const centerX2 = viewport.x + viewport.width / 2;
  const centerY = viewport.y + viewport.height / 2;
  return {
    x: clamp(centerX2 - width / 2, 0, 1 - width),
    y: clamp(centerY - height / 2, 0, 1 - height),
    width,
    height
  };
}
function centerViewportOnBox(viewport, box) {
  const centerX2 = box.x + box.width / 2;
  const centerY = box.y + box.height * framingCenterYFraction(box, viewport.height);
  return {
    ...viewport,
    x: clamp(centerX2 - viewport.width / 2, 0, 1 - viewport.width),
    y: clamp(centerY - viewport.height / 2, 0, 1 - viewport.height)
  };
}
function containsBox(viewport, box) {
  return box.x >= viewport.x - EPSILON2 && box.y >= viewport.y - EPSILON2 && box.x + box.width <= viewport.x + viewport.width + EPSILON2 && box.y + box.height <= viewport.y + viewport.height + EPSILON2;
}
function viewportScale(viewport, sourceAspect, targetAspect) {
  const nominal = nominalCropSize(sourceAspect, targetAspect);
  return Math.max(
    viewport.width / Math.max(EPSILON2, nominal.width),
    viewport.height / Math.max(EPSILON2, nominal.height)
  );
}
function centerDistance(a, b) {
  const ax = a.x + a.width / 2;
  const ay = a.y + a.height / 2;
  const bx = b.x + b.width / 2;
  const by = b.y + b.height / 2;
  return Math.hypot(ax - bx, ay - by);
}

// src/features/clipper/engine/autoflip/layout/visibility-envelope.util.ts
var EPSILON3 = 1e-9;
function expand(box, marginX, marginY = marginX) {
  const x = clamp(box.x - marginX, 0, 1);
  const y = clamp(box.y - marginY, 0, 1);
  const right = clamp(box.x + box.width + marginX, 0, 1);
  const bottom = clamp(box.y + box.height + marginY, 0, 1);
  return { x, y, width: right - x, height: bottom - y };
}
function union(boxes) {
  return boxes.reduce(
    (result, box) => result ? importanceGeometry.unionBoxes(result, box) : { ...box },
    null
  );
}
function coverage(viewports, regions) {
  return regions.map((region) => Math.max(0, ...viewports.map((viewport) => coveredFraction(viewport, region.contentBox))));
}
function coversAll(values, threshold = 1 - EPSILON3) {
  return values.length > 0 && values.every((value) => value >= threshold);
}
function fitViewport(anchor, width, height, preferredCenter) {
  if (anchor.width > width + EPSILON3 || anchor.height > height + EPSILON3) return null;
  const minimumX = Math.max(0, anchor.x + anchor.width - width);
  const maximumX = Math.min(1 - width, anchor.x);
  const minimumY = Math.max(0, anchor.y + anchor.height - height);
  const maximumY = Math.min(1 - height, anchor.y);
  if (minimumX > maximumX + EPSILON3 || minimumY > maximumY + EPSILON3) return null;
  const center2 = preferredCenter ?? {
    x: anchor.x + anchor.width / 2,
    y: anchor.y + anchor.height * framingCenterYFraction(anchor, height)
  };
  return {
    x: clamp(center2.x - width / 2, minimumX, maximumX),
    y: clamp(center2.y - height / 2, minimumY, maximumY),
    width,
    height
  };
}
function cropForEnvelope(envelope, sourceAspect, targetAspect, minimumScale) {
  const nominal = nominalCropSize(sourceAspect, targetAspect);
  const scale = clamp(Math.max(
    minimumScale,
    envelope.width / Math.max(EPSILON3, nominal.width),
    envelope.height / Math.max(EPSILON3, nominal.height)
  ), minimumScale, 1);
  return fitViewport(envelope, nominal.width * scale, nominal.height * scale);
}
function findPreviousRegion(samples, index, id) {
  const currentTime = samples[index]?.time ?? 0;
  for (let cursor = index - 1; cursor >= 0; cursor--) {
    const sample = samples[cursor];
    if (samples[cursor + 1]?.cut || sample.cut || currentTime - sample.time > 0.6) break;
    const region = sample.regions.find((candidate) => candidate.id === id && !candidate.predicted);
    if (region) return { region, time: sample.time };
  }
  return null;
}
function buildVisibilityEnvelopes(samples, index, params) {
  const sample = samples[index] ?? { time: 0, regions: [] };
  return requiredRegions(sample).map((region) => {
    let contentBox = { ...region.contentBox };
    const previous = findPreviousRegion(samples, index, region.id);
    const currentCenterX = region.contentBox.x + region.contentBox.width / 2;
    const currentCenterY = region.contentBox.y + region.contentBox.height / 2;
    let speedX = 0;
    let speedY = 0;
    if (previous && sample.time > previous.time + EPSILON3) {
      const dt = sample.time - previous.time;
      speedX = (currentCenterX - (previous.region.contentBox.x + previous.region.contentBox.width / 2)) / dt;
      speedY = (currentCenterY - (previous.region.contentBox.y + previous.region.contentBox.height / 2)) / dt;
    }
    for (let cursor = index + 1; cursor < samples.length; cursor++) {
      const future = samples[cursor];
      if (future.cut || future.time - sample.time > params.lookaheadSec + EPSILON3) break;
      const next = future.regions.find((candidate) => candidate.id === region.id);
      if (next) contentBox = importanceGeometry.unionBoxes(contentBox, next.contentBox);
    }
    const speedMarginX = Math.min(0.12, Math.abs(speedX) * params.velocityMarginSec);
    const speedMarginY = Math.min(0.08, Math.abs(speedY) * params.velocityMarginSec);
    contentBox = expand(
      contentBox,
      params.envelopeMargin * Math.max(0.02, region.contentBox.width) + speedMarginX,
      params.envelopeMargin * Math.max(0.02, region.contentBox.height) + speedMarginY
    );
    return { ...region, contentBox };
  });
}

// src/features/clipper/engine/autoflip/layout/visibility-rescue-helpers.util.ts
var EPSILON4 = 1e-9;
var PAIR_SLOT_MAX_CENTER_DELTA = 0.13;
var PAIR_SLOT_MAX_VERTICAL_DELTA = 0.25;
function hasIndependentEvidence(region) {
  const semantic = new Set(region.sources.filter((source) => source !== "motion"));
  return !region.predicted && region.confidence >= 0.75 && !region.identityAmbiguous && (semantic.has("person") || semantic.has("pose") || semantic.has("face") || semantic.has("head"));
}
function stablePair(samples, index, regions, minimumSamples) {
  if (regions.length !== 2) return false;
  const current = requiredRegions(samples[index] ?? { time: 0, regions: [] }).filter(hasIndependentEvidence);
  if (current.length !== 2 || !pairObservationMatches(regions, current)) return false;
  const minimumObserved = Math.max(2, Math.ceil(minimumSamples * 0.625));
  return matchingPairObservations(samples, index, regions, minimumSamples, -1) >= minimumObserved || matchingPairObservations(samples, index, regions, minimumSamples, 1) >= minimumObserved;
}
function boxCenter(box) {
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}
function orderedPairByPosition(regions) {
  if (regions.length !== 2) return null;
  const ordered = [...regions].sort((left, right) => boxCenter(left.contentBox).x - boxCenter(right.contentBox).x);
  return [ordered[0], ordered[1]];
}
function pairObservationMatches(reference, observed) {
  const referenceKey = reference.map((region) => region.id).sort().join("|");
  const observedKey = observed.map((region) => region.id).sort().join("|");
  if (referenceKey === observedKey) return true;
  const referenceSlots = orderedPairByPosition(reference);
  const observedSlots = orderedPairByPosition(observed);
  if (!referenceSlots || !observedSlots) return false;
  return referenceSlots.every((slot, slotIndex) => {
    const candidate = observedSlots[slotIndex];
    if (slot.id === candidate.id) return true;
    const expected = boxCenter(slot.contentBox);
    const actual = boxCenter(candidate.contentBox);
    return Math.abs(expected.x - actual.x) <= PAIR_SLOT_MAX_CENTER_DELTA && Math.abs(expected.y - actual.y) <= PAIR_SLOT_MAX_VERTICAL_DELTA;
  });
}
function matchingPairObservations(samples, index, reference, maximumSamples, direction) {
  let observed = 0;
  for (let offset = 0; offset < maximumSamples; offset++) {
    const cursor = index + offset * direction;
    if (cursor < 0 || cursor >= samples.length) break;
    const sample = samples[cursor];
    if (offset > 0) {
      const boundary = direction < 0 ? samples[cursor + 1] : sample;
      if (boundary?.cut) break;
    }
    const required = requiredRegions(sample).filter(hasIndependentEvidence);
    if (required.length === 2 && pairObservationMatches(reference, required)) observed++;
  }
  return observed;
}
function stableTriple(samples, index, ids, minimumSamples) {
  if (ids.length !== 3) return false;
  const key = [...ids].sort().join("|");
  let observed = 0;
  for (let cursor = index; cursor >= 0 && observed < minimumSamples; cursor--) {
    const sample = samples[cursor];
    if (cursor < index && (samples[cursor + 1]?.cut || sample.cut)) break;
    const required = requiredRegions(sample).filter(hasIndependentEvidence);
    if (required.length !== 3 || required.map((region) => region.id).sort().join("|") !== key) break;
    observed++;
  }
  return observed >= minimumSamples;
}
function edgeRisk(samples, index, regions, fraction) {
  const previous = /* @__PURE__ */ new Map();
  if (index > 0 && !samples[index]?.cut) {
    for (const region of samples[index - 1].regions) previous.set(region.id, region);
  }
  return regions.some((region) => {
    const center2 = region.contentBox.x + region.contentBox.width / 2;
    const prior = previous.get(region.id);
    const priorCenter = prior ? prior.contentBox.x + prior.contentBox.width / 2 : center2;
    return center2 <= fraction && center2 < priorCenter - EPSILON4 || center2 >= 1 - fraction && center2 > priorCenter + EPSILON4;
  });
}
function orderedPair(regions, state) {
  if (state.panelOrder.length === 2) {
    const ordered2 = state.panelOrder.map((id) => regions.find((region) => region.id === id)).filter((region) => region != null);
    if (ordered2.length === 2) return ordered2;
  }
  const ordered = [...regions].sort((a, b) => a.contentBox.x + a.contentBox.width / 2 - (b.contentBox.x + b.contentBox.width / 2));
  state.panelOrder = ordered.map((region) => region.id);
  return ordered;
}
function orderedTriple(regions, state) {
  const primary = regions.find((region) => region.role === "primary") ?? [...regions].sort((a, b) => b.importanceScore - a.importanceScore)[0];
  const others = regions.filter((region) => region.id !== primary.id);
  if (state.panelOrder.length === 3 && state.panelOrder[0] === primary.id) {
    const ordered2 = state.panelOrder.map((id) => regions.find((region) => region.id === id)).filter((region) => region != null);
    if (ordered2.length === 3) return ordered2;
  }
  others.sort((a, b) => a.contentBox.x + a.contentBox.width / 2 - (b.contentBox.x + b.contentBox.width / 2));
  const ordered = [primary, ...others];
  state.panelOrder = ordered.map((region) => region.id);
  return ordered;
}
function variant(kind, mode, viewports, envelopes, panelSubjects = envelopes) {
  return {
    kind,
    mode,
    viewports,
    requiredCoverage: coverage(viewports, envelopes),
    panelSubjects: mode === "split" ? panelSubjects.map((region) => ({ id: region.id, focusBox: { ...region.box } })) : void 0
  };
}
function minimumCoverage(values) {
  return values.length ? Math.min(...values) : 0;
}
var VISIBILITY_EPSILON = EPSILON4;

// src/features/clipper/engine/autoflip/layout/emergency-primary-crop.util.ts
function buildEmergencyPrimaryCrop(primary, baseline, envelopes) {
  const center2 = {
    x: primary.box.x + primary.box.width / 2,
    y: primary.box.y + primary.box.height * framingCenterYFraction(primary.box, baseline.height)
  };
  const fitted = fitViewport(primary.box, baseline.width, baseline.height, center2);
  const viewport = fitted ?? {
    x: Math.max(0, Math.min(1 - baseline.width, center2.x - baseline.width / 2)),
    y: Math.max(0, Math.min(1 - baseline.height, center2.y - baseline.height / 2)),
    width: baseline.width,
    height: baseline.height
  };
  return variant("emergency-primary-crop", "single-crop", [viewport], envelopes);
}
function primaryCoverageOf(candidate, envelopes, primaryId) {
  const index = envelopes.findIndex((region) => region.id === primaryId);
  return candidate.requiredCoverage[index >= 0 ? index : 0] ?? 0;
}

// src/features/clipper/engine/autoflip/layout/visibility-rescue.util.ts
var EPSILON5 = VISIBILITY_EPSILON;
var EMERGENCY_PRIMARY_COVERAGE = 0.8;
var SINGLE_TARGET_HOLD_SEC = 0.6;
var SINGLE_CAMERA_DEAD_ZONE = 0.03;
var SINGLE_CAMERA_MAX_SPEED_PER_SEC = 0.16;
var SINGLE_CAMERA_MAX_ACCELERATION_PER_SEC2 = 0.4;
var EMERGENCY_CAMERA_MAX_SPEED_PER_SEC = 0.4;
var EMERGENCY_CAMERA_MAX_ACCELERATION_PER_SEC2 = 1;
var REVERSE_BRAKE_MULT = 2;
var LAYOUT_SAMPLE_DT_SEC = 0.2;
function signNonZero(value) {
  if (value > EPSILON5) return 1;
  if (value < -EPSILON5) return -1;
  return 0;
}
function clampAxisVelocity(previous, desired, maxSpeed, maxAccelDelta) {
  const reversing = signNonZero(previous) !== 0 && signNonZero(desired) !== 0 && signNonZero(previous) !== signNonZero(desired);
  const budget = reversing ? maxAccelDelta * REVERSE_BRAKE_MULT : maxAccelDelta;
  return Math.max(-maxSpeed, Math.min(
    maxSpeed,
    Math.max(previous - budget, Math.min(previous + budget, desired))
  ));
}
function splitThreePanelAspects(targetAspect) {
  return targetAspect < 1 ? [targetAspect * 2, targetAspect, targetAspect] : [targetAspect * 0.6, targetAspect * 0.8, targetAspect * 0.8];
}
function currentVariant(state, envelopes) {
  if (state.activeMode !== "split" || !state.lastSplitViewports.length) return null;
  const kind = state.lastSplitViewports.length === 3 ? "stable-split-3" : "stable-split-v3";
  return variant(kind, "split", state.lastSplitViewports, envelopes, state.lastSplitPanelSubjects.map((subject) => ({
    id: subject.id,
    box: subject.focusBox
  })));
}
function layoutKey(mode, viewportCount) {
  return `${mode}:${viewportCount}`;
}
function resetSingleTargetState(state) {
  state.singlePrimaryId = null;
  state.pendingSinglePrimaryId = null;
  state.pendingSinglePrimarySince = null;
  state.singleViewport = null;
  state.singleVelocity = { x: 0, y: 0 };
  state.singleLastUpdatedAt = null;
}
function viewportCenter(viewport) {
  return { x: viewport.x + viewport.width / 2, y: viewport.y + viewport.height / 2 };
}
function stabilizeSinglePrimaryViewport(state, primaryId, candidate, baseline, time, emergency, snap = false) {
  if (snap) {
    state.singlePrimaryId = primaryId;
    state.pendingSinglePrimaryId = null;
    state.pendingSinglePrimarySince = null;
    state.singleViewport = { ...candidate };
    state.singleVelocity = { x: 0, y: 0 };
    state.singleLastUpdatedAt = time;
    return state.singleViewport;
  }
  if (state.singlePrimaryId !== primaryId) {
    if (!emergency) {
      if (state.pendingSinglePrimaryId !== primaryId) {
        state.pendingSinglePrimaryId = primaryId;
        state.pendingSinglePrimarySince = time;
      }
      if (time - (state.pendingSinglePrimarySince ?? time) < SINGLE_TARGET_HOLD_SEC) {
        state.singleVelocity = { x: 0, y: 0 };
        state.singleLastUpdatedAt = time;
        return state.singleViewport;
      }
    }
    state.singlePrimaryId = primaryId;
    state.pendingSinglePrimaryId = null;
    state.pendingSinglePrimarySince = null;
    state.singleViewport ??= baseline;
    state.singleVelocity = { x: 0, y: 0 };
  }
  const current = state.singleViewport ?? baseline;
  const previousCenter = viewportCenter(current);
  const candidateCenter = viewportCenter(candidate);
  const dx = candidateCenter.x - previousCenter.x;
  const dy = candidateCenter.y - previousCenter.y;
  const distance = Math.hypot(dx, dy);
  const elapsed = Math.max(0, time - (state.singleLastUpdatedAt ?? time));
  if (distance <= SINGLE_CAMERA_DEAD_ZONE || elapsed <= 0) {
    state.singleViewport = current;
    state.singleVelocity = { x: 0, y: 0 };
    state.singleLastUpdatedAt = time;
    return current;
  }
  const maxSpeed = emergency ? EMERGENCY_CAMERA_MAX_SPEED_PER_SEC : SINGLE_CAMERA_MAX_SPEED_PER_SEC;
  const maxAccel = emergency ? EMERGENCY_CAMERA_MAX_ACCELERATION_PER_SEC2 : SINGLE_CAMERA_MAX_ACCELERATION_PER_SEC2;
  const desiredVelocity = { x: dx / elapsed, y: dy / elapsed };
  const maxVelocityDelta = maxAccel * elapsed;
  const velocity = {
    x: clampAxisVelocity(state.singleVelocity.x, desiredVelocity.x, maxSpeed, maxVelocityDelta),
    y: clampAxisVelocity(state.singleVelocity.y, desiredVelocity.y, maxSpeed, maxVelocityDelta)
  };
  const width = candidate.width;
  const height = candidate.height;
  const viewport = {
    ...candidate,
    x: Math.max(0, Math.min(1 - width, previousCenter.x + velocity.x * elapsed - width / 2)),
    y: Math.max(0, Math.min(1 - height, previousCenter.y + velocity.y * elapsed - height / 2))
  };
  state.singleViewport = viewport;
  state.singleVelocity = velocity;
  state.singleLastUpdatedAt = time;
  return viewport;
}
function seedSingleFromSplitPanel(state, time) {
  const panel = state.lastSplitViewports[0];
  if (!panel) return;
  state.singleViewport = { ...panel };
  state.singleVelocity = { x: 0, y: 0 };
  state.singleLastUpdatedAt = time - LAYOUT_SAMPLE_DT_SEC;
}
function easeFinalSingleCrop(input2) {
  const { state, selected, centeredSingle, primaryId, baseline, envelopes, time, emergency, snap } = input2;
  if (selected.mode !== "single-crop" || !selected.viewports[0]) return selected;
  if (input2.splitSeed) seedSingleFromSplitPanel(state, time);
  if (selected === centeredSingle && !input2.splitSeed) return selected;
  if (!snap && state.singleLastUpdatedAt != null && state.singleLastUpdatedAt >= time - 1e-9) {
    state.singleLastUpdatedAt = time - LAYOUT_SAMPLE_DT_SEC;
  }
  const eased = stabilizeSinglePrimaryViewport(
    state,
    primaryId,
    selected.viewports[0],
    baseline,
    time,
    emergency || selected.kind === "emergency-primary-crop",
    snap
  );
  if (!eased) return selected;
  return variant(selected.kind, "single-crop", [eased], envelopes);
}
function planVisibilityRescue(input2) {
  const params = input2.params ?? LEGACY_VISIBILITY_PARAMS;
  const sample = input2.samples[input2.importanceIndex] ?? { time: 0, regions: [] };
  const time = sample.time;
  if (sample.cut) {
    input2.state.scene++;
    input2.state.activeMode = "single-crop";
    input2.state.activeViewportCount = 1;
    input2.state.modeSince = time;
    input2.state.riskClearedAt = null;
    input2.state.lastRiskAt = null;
    input2.state.panelOrder = [];
    input2.state.previousViewport = null;
    input2.state.machineState = "common";
    input2.state.pendingSince = null;
    input2.state.lastSplitViewports = [];
    input2.state.identityLostAt = null;
    input2.state.modeSwitchTimestamps = [];
    input2.state.sceneStartedAt = time;
    resetSingleTargetState(input2.state);
  }
  const lookaheadEnvelopes = buildVisibilityEnvelopes(input2.samples, input2.importanceIndex, params);
  const envelopes = buildVisibilityEnvelopes(input2.samples, input2.importanceIndex, { ...params, lookaheadSec: 0 });
  const baseline = variant("run8-baseline", "single-crop", [input2.baselineViewport], envelopes);
  const variants = [baseline];
  const activeSplitBeforeEvidence = currentVariant(input2.state, envelopes);
  const emergency = (baseline.requiredCoverage[0] ?? 1) < EMERGENCY_PRIMARY_COVERAGE;
  const trackedPrediction = envelopes.length === 1 && envelopes[0]?.role === "primary" && envelopes[0].predicted === true && (envelopes[0].trust === "temporally-qualified-person" || envelopes[0].trust === "object");
  const singlePrimary = envelopes.length === 1 && envelopes[0]?.role === "primary" && (hasIndependentEvidence(envelopes[0]) || trackedPrediction);
  if (!singlePrimary) resetSingleTargetState(input2.state);
  if (!params.enabled || !envelopes.length || sample.cut && !singlePrimary || envelopes.some((region) => region.identityAmbiguous) || envelopes.some((region) => region.predicted) && !trackedPrediction) {
    if (!sample.cut && activeSplitBeforeEvidence) {
      input2.state.identityLostAt ??= time;
      if (time - input2.state.identityLostAt < params.splitExitStableSec) {
        return {
          mode: "split",
          viewports: activeSplitBeforeEvidence.viewports,
          envelopes,
          variants: [...variants, activeSplitBeforeEvidence],
          baselineCoverage: baseline.requiredCoverage,
          selectedCoverage: activeSplitBeforeEvidence.requiredCoverage,
          reasonCodes: ["stable-split-dropout-hold"],
          visibilityRisk: true
        };
      }
    }
    if (input2.state.activeMode === "split") {
      input2.state.activeMode = "single-crop";
      input2.state.activeViewportCount = 1;
      input2.state.modeSince = time;
      input2.state.lastSplitViewports = [];
      input2.state.identityLostAt = null;
    }
    const noTargetReason = sample.targetEvidence?.status === "temporal-pending" ? "temporal-person-pending" : "no-target-evidence";
    return {
      mode: "single-crop",
      viewports: [input2.baselineViewport],
      envelopes,
      variants,
      baselineCoverage: baseline.requiredCoverage,
      selectedCoverage: baseline.requiredCoverage,
      reasonCodes: [sample.cut ? "shot-boundary" : !envelopes.length ? noTargetReason : "stable-single-fallback"],
      visibilityRisk: false
    };
  }
  const requiredUnion = union(envelopes.map((region) => region.contentBox));
  const lookaheadUnion = union(lookaheadEnvelopes.map((region) => region.contentBox)) ?? requiredUnion;
  const lookAheadCenterY = lookaheadUnion.y + lookaheadUnion.height * framingCenterYFraction(lookaheadUnion, input2.baselineViewport.height);
  const centeredSingleCandidate = singlePrimary ? fitViewport(requiredUnion, input2.baselineViewport.width, input2.baselineViewport.height, {
    x: requiredUnion.x + requiredUnion.width / 2,
    y: lookAheadCenterY
  }) : null;
  const stabilizedSingleViewport = centeredSingleCandidate && envelopes[0] ? stabilizeSinglePrimaryViewport(
    input2.state,
    envelopes[0].id,
    centeredSingleCandidate,
    input2.baselineViewport,
    time,
    emergency,
    sample.cut === true
  ) : null;
  const centeredSingle = stabilizedSingleViewport ? variant("shifted-crop", "single-crop", [stabilizedSingleViewport], envelopes) : null;
  if (centeredSingle) variants.push(centeredSingle);
  const shifted = fitViewport(requiredUnion, input2.baselineViewport.width, input2.baselineViewport.height, {
    x: lookaheadUnion.x + lookaheadUnion.width / 2,
    y: lookAheadCenterY
  });
  if (shifted) variants.push(variant("shifted-crop", "single-crop", [shifted], envelopes));
  const nominal = nominalCropSize(input2.sourceAspect, input2.targetAspect);
  const currentScale = Math.max(
    input2.baselineViewport.width / Math.max(EPSILON5, nominal.width),
    input2.baselineViewport.height / Math.max(EPSILON5, nominal.height)
  );
  const wider = cropForEnvelope(requiredUnion, input2.sourceAspect, input2.targetAspect, Math.min(1, currentScale + 0.08));
  if (wider) variants.push(variant("wider-crop", "single-crop", [wider], envelopes));
  const primaryRegion = envelopes.find((region) => region.role === "primary") ?? envelopes[0];
  const emergencyPrimary = emergency || !shifted ? buildEmergencyPrimaryCrop(primaryRegion, input2.baselineViewport, envelopes) : null;
  if (emergencyPrimary) variants.push(emergencyPrimary);
  const allowSplitForAspect = input2.targetAspect <= 1;
  const stableEvidence = envelopes.every(hasIndependentEvidence) && envelopes.every((region) => (region.associationConfidence ?? 1) >= (params.minimumAssociationConfidence ?? 0));
  const pairStable = allowSplitForAspect && envelopes.length === 2 && stableEvidence && stablePair(input2.samples, input2.importanceIndex, envelopes, params.splitStableSamples);
  const ids = envelopes.map((region) => region.id);
  const tripleStable = allowSplitForAspect && envelopes.length === 3 && stableEvidence && stableTriple(input2.samples, input2.importanceIndex, ids, params.splitStableSamples);
  if (pairStable) {
    const panelRegions = orderedPair(envelopes, input2.state);
    const targetAspects = [input2.targetAspect * 2, input2.targetAspect * 2];
    const panels = fitSeparatedSplitPanels(
      panelRegions.map((r) => ({ id: r.id, box: r.box, contentBox: r.contentBox })),
      input2.sourceAspect,
      targetAspects
    );
    if (panels) {
      variants.push(variant(params.splitVariant === "v3" ? "stable-split-v3" : "stable-split-v2", "split", panels, envelopes, panelRegions));
    }
  }
  if (tripleStable) {
    const aspects = splitThreePanelAspects(input2.targetAspect);
    const panelRegions = orderedTriple(envelopes, input2.state);
    const panels = fitSeparatedSplitPanels(
      panelRegions.map((r) => ({ id: r.id, box: r.box, contentBox: r.contentBox })),
      input2.sourceAspect,
      aspects
    );
    if (panels) {
      variants.push(variant("stable-split-3", "split", panels, envelopes, panelRegions));
    }
  }
  const predictedEdgeRisk = edgeRisk(input2.samples, input2.importanceIndex, lookaheadEnvelopes, params.edgeRiskFraction);
  const lookaheadCoverage = coverage([input2.baselineViewport], lookaheadEnvelopes);
  const baselineSafe = coversAll(baseline.requiredCoverage) && coversAll(lookaheadCoverage) && !predictedEdgeRisk;
  const safeCommonCrop = singlePrimary ? void 0 : variants.find((candidate) => (candidate.kind === "shifted-crop" || candidate.kind === "wider-crop") && coversAll(candidate.requiredCoverage));
  const splitCandidate = variants.find((candidate) => (candidate.kind === "stable-split-v2" || candidate.kind === "stable-split-v3" || candidate.kind === "stable-split-3") && coversAll(candidate.requiredCoverage));
  const primaryCenterSafe = centeredSingle != null && (coversAll(centeredSingle.requiredCoverage) || input2.state.singlePrimaryId === envelopes[0]?.id);
  const preferSingleForSquare = Math.abs(input2.targetAspect - 1) < EPSILON5;
  let selected = primaryCenterSafe ? centeredSingle : baselineSafe ? baseline : preferSingleForSquare ? safeCommonCrop ?? splitCandidate ?? emergencyPrimary ?? baseline : safeCommonCrop ?? splitCandidate ?? emergencyPrimary ?? baseline;
  if (preferSingleForSquare && (safeCommonCrop || baselineSafe)) {
    selected = primaryCenterSafe ? centeredSingle : baselineSafe ? baseline : safeCommonCrop ?? baseline;
  }
  if (emergencyPrimary && primaryCoverageOf(selected, envelopes, primaryRegion.id) < EMERGENCY_PRIMARY_COVERAGE && primaryCoverageOf(emergencyPrimary, envelopes, primaryRegion.id) >= EMERGENCY_PRIMARY_COVERAGE) {
    selected = emergencyPrimary;
  }
  const heldSplit = currentVariant(input2.state, envelopes);
  let holdingActiveSplit = false;
  if (input2.state.activeMode === "split" && !pairStable) {
    input2.state.identityLostAt ??= time;
    if (heldSplit && time - input2.state.identityLostAt < params.splitExitStableSec) {
      selected = heldSplit;
      holdingActiveSplit = true;
    }
  }
  const currentKey = layoutKey(input2.state.activeMode, input2.state.activeViewportCount);
  const selectedKey = layoutKey(selected.mode, selected.viewports.length);
  const activeFor = time - input2.state.modeSince;
  const switching = currentKey !== selectedKey;
  const resumesKnownPair = pairStable && input2.state.identityLostAt != null && time - input2.state.identityLostAt <= (params.identityHoldSec ?? 0.6);
  if (switching && selected.mode === "split" && !emergency) {
    if (resumesKnownPair) {
      input2.state.pendingSince = null;
    } else if (input2.state.machineState !== "split-pending") {
      input2.state.machineState = "split-pending";
      input2.state.pendingSince = time;
    }
    if (!resumesKnownPair && time - (input2.state.pendingSince ?? time) < (params.splitPendingSec ?? 1.5)) {
      selected = safeCommonCrop ?? emergencyPrimary ?? baseline;
      if (emergencyPrimary && primaryCoverageOf(selected, envelopes, primaryRegion.id) < EMERGENCY_PRIMARY_COVERAGE && primaryCoverageOf(emergencyPrimary, envelopes, primaryRegion.id) >= EMERGENCY_PRIMARY_COVERAGE) {
        selected = emergencyPrimary;
      }
    }
  } else if (selected.mode !== "split") {
    input2.state.pendingSince = null;
  }
  const selectedAfterPendingKey = layoutKey(selected.mode, selected.viewports.length);
  const activeSplit = currentVariant(input2.state, envelopes);
  if (!emergency && currentKey !== selectedAfterPendingKey && activeFor < params.splitMinDurationSec && activeSplit) {
    selected = activeSplit;
  } else if (!emergency && input2.state.activeMode === "split" && baselineSafe) {
    input2.state.riskClearedAt ??= time;
    if (time - input2.state.riskClearedAt < params.splitExitStableSec && activeSplit) {
      input2.state.machineState = "merge-pending";
      selected = activeSplit;
    }
  }
  const finalKey = layoutKey(selected.mode, selected.viewports.length);
  if (finalKey !== currentKey) {
    input2.state.modeSwitchTimestamps = input2.state.modeSwitchTimestamps.filter((timestamp) => time - timestamp < 60);
    const rate = params.maxSwitchesPerMinute ?? Number.POSITIVE_INFINITY;
    const coverageImproves = minimumCoverage(selected.requiredCoverage) > minimumCoverage(activeSplit?.requiredCoverage ?? baseline.requiredCoverage) + EPSILON5;
    if (!emergency && input2.state.modeSwitchTimestamps.length >= rate && !coverageImproves) {
      selected = activeSplit ?? baseline;
    }
  }
  const risk = !baselineSafe;
  if (risk) {
    input2.state.lastRiskAt = time;
    input2.state.riskClearedAt = null;
  } else {
    input2.state.riskClearedAt ??= time;
  }
  const committedKey = layoutKey(selected.mode, selected.viewports.length);
  if (committedKey !== currentKey) {
    input2.state.modeSwitchTimestamps.push(time);
    input2.state.activeMode = selected.mode;
    input2.state.activeViewportCount = selected.viewports.length;
    input2.state.modeSince = time;
  }
  if (!(input2.state.machineState === "split-pending" && selected.mode !== "split")) {
    input2.state.machineState = selected.mode === "split" ? "split-active" : "common";
  }
  if (selected.mode === "split") {
    if (pairStable) input2.state.identityLostAt = null;
    input2.state.lastSplitViewports = selected.viewports.map((viewport) => ({ ...viewport }));
    input2.state.lastSplitPanelSubjects = selected.panelSubjects?.map((subject) => ({
      id: subject.id,
      focusBox: { ...subject.focusBox }
    })) ?? [];
  }
  let splitSeed = selected.mode === "single-crop" && currentKey.startsWith("split:") && input2.state.lastSplitViewports.length > 0;
  if (emergencyPrimary && primaryCoverageOf(selected, envelopes, primaryRegion.id) < EMERGENCY_PRIMARY_COVERAGE && primaryCoverageOf(emergencyPrimary, envelopes, primaryRegion.id) >= EMERGENCY_PRIMARY_COVERAGE) {
    if (currentKey.startsWith("split:") && input2.state.lastSplitViewports[0]) {
      splitSeed = true;
    }
    selected = emergencyPrimary;
    if (currentKey.startsWith("split:") || input2.state.activeMode === "split") {
      if (splitSeed) seedSingleFromSplitPanel(input2.state, time);
      input2.state.activeMode = "single-crop";
      input2.state.activeViewportCount = 1;
      input2.state.modeSince = time;
      input2.state.lastSplitViewports = [];
      input2.state.machineState = "common";
      splitSeed = false;
    }
  }
  selected = easeFinalSingleCrop({
    state: input2.state,
    selected,
    centeredSingle,
    primaryId: primaryRegion.id,
    baseline: input2.baselineViewport,
    envelopes,
    time,
    emergency,
    splitSeed,
    snap: sample.cut === true
  });
  input2.state.previousViewport = selected.viewports[0] ?? input2.baselineViewport;
  const reason = selected === centeredSingle ? "primary-horizontal-center" : selected.kind === "emergency-primary-crop" ? "emergency-primary-crop" : selected.kind === "shifted-crop" ? "visibility-shift" : selected.kind === "wider-crop" ? "visibility-widen" : selected.kind === "stable-split-3" ? "stable-split-3" : selected.kind === "stable-split-v2" || selected.kind === "stable-split-v3" ? selected.kind : "stable-primary-crop";
  return {
    mode: selected.mode,
    viewports: selected.viewports,
    envelopes,
    variants,
    baselineCoverage: baseline.requiredCoverage,
    selectedCoverage: selected.requiredCoverage,
    reasonCodes: [
      reason,
      ...holdingActiveSplit ? ["stable-split-dropout-hold"] : [],
      ...emergency ? ["primary-coverage-emergency"] : [],
      ...predictedEdgeRisk ? ["outward-edge-risk"] : [],
      "lookahead-envelope"
    ],
    visibilityRisk: risk,
    panelSubjects: selected.panelSubjects
  };
}

// src/features/clipper/engine/autoflip/layout/layout-mode.util.ts
function rawMode(sample, sourceAspect, targetAspect) {
  const required = requiredRegions(sample);
  if (!required.length) return "single-crop";
  if (targetAspect > 1) return "single-crop";
  const union2 = unionAll(required.map((region) => region.contentBox));
  if (boxFitsStrictCrop(union2, sourceAspect, targetAspect)) return "single-crop";
  if (required.length >= 2) {
    const overlap = importanceGeometry.overlapFractionOfSmaller(required[0].contentBox, required[1].contentBox);
    if (overlap <= 0.2) return "split";
  }
  return "single-crop";
}

// src/features/clipper/engine/autoflip/layout/visibility-framing.util.ts
var EPSILON6 = 1e-9;
function createVisibilityFramingState() {
  return { primaryId: null, observedKeyframes: 0, previousViewport: null };
}
function viewportAtScale(anchor, guard, scale, sourceAspect, targetAspect, centerYFraction) {
  const nominal = nominalCropSize(sourceAspect, targetAspect);
  const width = nominal.width * scale;
  const height = nominal.height * scale;
  if (guard.width > width + EPSILON6 || guard.height > height + EPSILON6) return null;
  const desiredX = anchor.x + anchor.width / 2 - width / 2;
  const desiredY = anchor.y + anchor.height * framingCenterYFraction(anchor, height, centerYFraction) - height / 2;
  const minimumX = Math.max(0, guard.x + guard.width - width);
  const maximumX = Math.min(1 - width, guard.x);
  const minimumY = Math.max(0, guard.y + guard.height - height);
  const maximumY = Math.min(1 - height, guard.y);
  if (minimumX > maximumX + EPSILON6 || minimumY > maximumY + EPSILON6) return null;
  return {
    x: clamp(desiredX, minimumX, maximumX),
    y: clamp(desiredY, minimumY, maximumY),
    width,
    height
  };
}
function limitViewportMotion(candidate, previous, guard, sourceAspect, targetAspect, params) {
  const previousScale = viewportScale(previous, sourceAspect, targetAspect);
  const candidateScale = viewportScale(candidate, sourceAspect, targetAspect);
  const maxScaleStep = params.maxScaleStep ?? 0.05;
  const scale = clamp(candidateScale, previousScale - maxScaleStep, previousScale + maxScaleStep);
  const nominal = nominalCropSize(sourceAspect, targetAspect);
  const width = nominal.width * scale;
  const height = nominal.height * scale;
  const previousCenterX = previous.x + previous.width / 2;
  const previousCenterY = previous.y + previous.height / 2;
  const candidateCenterX = candidate.x + candidate.width / 2;
  const candidateCenterY = candidate.y + candidate.height / 2;
  const deltaX = candidateCenterX - previousCenterX;
  const deltaY = candidateCenterY - previousCenterY;
  const distance = Math.hypot(deltaX, deltaY);
  const maxCenterStep = params.maxCenterStep ?? 0.08;
  const factor = distance > maxCenterStep ? maxCenterStep / distance : 1;
  const limited = {
    x: clamp(previousCenterX + deltaX * factor - width / 2, 0, 1 - width),
    y: clamp(previousCenterY + deltaY * factor - height / 2, 0, 1 - height),
    width,
    height
  };
  return containsBox(limited, guard) ? limited : null;
}
function visibilityConstrainedViewport(importance, legacyViewport, sourceAspect, targetAspect, params, state, cut) {
  const required = requiredRegions(importance);
  const primary = required.find((region) => region.role === "primary") ?? required[0];
  if (cut) {
    state.primaryId = null;
    state.observedKeyframes = 0;
    state.previousViewport = null;
  }
  if (!primary || required.length !== 1 || primary.predicted) {
    state.primaryId = null;
    state.observedKeyframes = 0;
    state.previousViewport = legacyViewport;
    return legacyViewport;
  }
  if (state.primaryId === primary.id) state.observedKeyframes++;
  else {
    state.primaryId = primary.id;
    state.observedKeyframes = 1;
  }
  const minimumObserved = params.stablePrimaryKeyframes ?? 5;
  if (cut || state.observedKeyframes < minimumObserved) {
    state.previousViewport = legacyViewport;
    return legacyViewport;
  }
  const guard = expandBox(primary.contentBox, params.visibilityGuardMargin ?? 0.08);
  const anchor = primary.box;
  const scales = [...new Set(params.allowedScales ?? [1, 0.95, 0.9, 0.8])].filter((scale) => Number.isFinite(scale) && scale >= 0.8 && scale <= 1).sort((a, b) => a - b);
  const candidates = scales.map((scale) => viewportAtScale(anchor, guard, scale, sourceAspect, targetAspect, params.centerYFraction)).filter((viewport) => viewport != null && containsBox(viewport, guard));
  if (!candidates.length) {
    state.previousViewport = legacyViewport;
    return legacyViewport;
  }
  const anchorPoint = {
    x: anchor.x + anchor.width / 2,
    y: anchor.y + anchor.height * framingCenterYFraction(
      anchor,
      Math.max(...candidates.map((candidate) => candidate.height)),
      params.centerYFraction
    ),
    width: 0,
    height: 0
  };
  const previous = state.previousViewport;
  candidates.sort((a, b) => {
    const anchorDelta = centerDistance(a, anchorPoint) - centerDistance(b, anchorPoint);
    if (Math.abs(anchorDelta) > EPSILON6) return anchorDelta;
    const compositionDelta = viewportScale(a, sourceAspect, targetAspect) - viewportScale(b, sourceAspect, targetAspect);
    if (Math.abs(compositionDelta) > EPSILON6) return compositionDelta;
    if (!previous) return 0;
    const changeA = Math.abs(viewportScale(a, sourceAspect, targetAspect) - viewportScale(previous, sourceAspect, targetAspect)) + centerDistance(a, previous);
    const changeB = Math.abs(viewportScale(b, sourceAspect, targetAspect) - viewportScale(previous, sourceAspect, targetAspect)) + centerDistance(b, previous);
    return changeA - changeB;
  });
  let selected = candidates[0];
  if (previous) {
    const previousScale = viewportScale(previous, sourceAspect, targetAspect);
    const hysteresis = params.scaleHysteresis ?? 0.025;
    if (Math.abs(viewportScale(selected, sourceAspect, targetAspect) - previousScale) <= hysteresis) {
      selected = previous;
    }
    selected = limitViewportMotion(selected, previous, guard, sourceAspect, targetAspect, params) ?? legacyViewport;
  }
  if (!containsBox(selected, guard)) selected = legacyViewport;
  state.previousViewport = selected;
  return selected;
}

// src/features/clipper/engine/autoflip/camera/shot-smoothing.util.ts
var EPSILON7 = 1e-9;
var DEFAULT_LAMBDA_EMA = 3;
var MAX_CAMERA_SPEED_PER_SEC = 0.5;
var MAX_CAMERA_ACCELERATION_PER_SEC2 = 1.5;
var SPIKE_THRESHOLD = 0.04;
var MEDIAN_WINDOW = 5;
var DEAD_ZONE_FRAC = 0.025;
var REVERSE_BRAKE_MULT2 = 2;
function viewportArea(viewport) {
  return Math.max(0, viewport.width) * Math.max(0, viewport.height);
}
function centerOf(box) {
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}
function boxFromCenter(box, cx, cy) {
  return {
    ...box,
    x: Math.max(0, Math.min(1 - box.width, cx - box.width / 2)),
    y: Math.max(0, Math.min(1 - box.height, cy - box.height / 2))
  };
}
function centerDistance2(a, b) {
  const ca = centerOf(a);
  const cb = centerOf(b);
  return Math.hypot(ca.x - cb.x, ca.y - cb.y);
}
function interpolateBox2(a, b, alpha) {
  const clampedAlpha = Math.max(0, Math.min(1, alpha));
  return {
    x: a.x + (b.x - a.x) * clampedAlpha,
    y: a.y + (b.y - a.y) * clampedAlpha,
    width: a.width + (b.width - a.width) * clampedAlpha,
    height: a.height + (b.height - a.height) * clampedAlpha
  };
}
function signNonZero2(value) {
  if (value > EPSILON7) return 1;
  if (value < -EPSILON7) return -1;
  return 0;
}
function clampAxisVelocity2(previous, desired, maxSpeed, maxAccelDelta) {
  const reversing = signNonZero2(previous) !== 0 && signNonZero2(desired) !== 0 && signNonZero2(previous) !== signNonZero2(desired);
  const budget = reversing ? maxAccelDelta * REVERSE_BRAKE_MULT2 : maxAccelDelta;
  return Math.max(-maxSpeed, Math.min(
    maxSpeed,
    Math.max(previous - budget, Math.min(previous + budget, desired))
  ));
}
function clampCameraMotion(previous, candidate, previousVelocity, dt) {
  const safeDt = Math.max(1 / 120, dt);
  const previousCenter = centerOf(previous);
  let candidateCenter = centerOf(candidate);
  const deadX = DEAD_ZONE_FRAC * candidate.width;
  const deadY = DEAD_ZONE_FRAC * candidate.height;
  if (Math.abs(candidateCenter.x - previousCenter.x) < deadX) candidateCenter = { ...candidateCenter, x: previousCenter.x };
  if (Math.abs(candidateCenter.y - previousCenter.y) < deadY) candidateCenter = { ...candidateCenter, y: previousCenter.y };
  const desiredVelocity = {
    x: (candidateCenter.x - previousCenter.x) / safeDt,
    y: (candidateCenter.y - previousCenter.y) / safeDt
  };
  const maxVelocityDelta = MAX_CAMERA_ACCELERATION_PER_SEC2 * safeDt;
  const velocity = {
    x: clampAxisVelocity2(previousVelocity.x, desiredVelocity.x, MAX_CAMERA_SPEED_PER_SEC, maxVelocityDelta),
    y: clampAxisVelocity2(previousVelocity.y, desiredVelocity.y, MAX_CAMERA_SPEED_PER_SEC, maxVelocityDelta)
  };
  const x = Math.max(0, Math.min(1 - candidate.width, previousCenter.x + velocity.x * safeDt - candidate.width / 2));
  const y = Math.max(0, Math.min(1 - candidate.height, previousCenter.y + velocity.y * safeDt - candidate.height / 2));
  return { crop: { ...candidate, x, y }, velocity };
}
function hasSceneCutBetween(sceneCuts, previousT, currentT) {
  return sceneCuts.some((cut) => cut > previousT + EPSILON7 && cut <= currentT + EPSILON7);
}
function continuousSegments(samples, sceneCuts) {
  const segments = [];
  let start = -1;
  for (let index = 0; index < samples.length; index++) {
    const sample = samples[index];
    const cutBreak = sample.cut === true || index > 0 && hasSceneCutBetween(sceneCuts, samples[index - 1].t, sample.t);
    if (cutBreak) {
      if (start >= 0 && index > start) segments.push({ start, end: index });
      start = sample.cut ? -1 : index;
      continue;
    }
    if (start < 0) start = index;
  }
  if (start >= 0 && start < samples.length) segments.push({ start, end: samples.length });
  return segments;
}
function rejectCenterSpikes(samples, start, end) {
  const n = end - start;
  if (n < 3) return;
  for (let i = start + 1; i < end - 1; i++) {
    const prev = samples[i - 1];
    const curr = samples[i];
    const next = samples[i + 1];
    const dPrev = centerDistance2(curr.crop, prev.crop);
    const dNext = centerDistance2(curr.crop, next.crop);
    const dOuter = centerDistance2(prev.crop, next.crop);
    if (dPrev > SPIKE_THRESHOLD && dNext > SPIKE_THRESHOLD && dOuter < 0.5 * Math.min(dPrev, dNext)) {
      const dtTotal = Math.max(1e-6, next.t - prev.t);
      const alpha = Math.max(0, Math.min(1, (curr.t - prev.t) / dtTotal));
      const ca = centerOf(prev.crop);
      const cb = centerOf(next.crop);
      curr.crop = boxFromCenter(curr.crop, ca.x + (cb.x - ca.x) * alpha, ca.y + (cb.y - ca.y) * alpha);
    }
  }
  for (let i = start + 1; i < end - 2; i++) {
    const s0 = samples[i - 1];
    const s1 = samples[i];
    const s2 = samples[i + 1];
    const s3 = samples[i + 2];
    const d01 = centerDistance2(s1.crop, s0.crop);
    const d12 = centerDistance2(s2.crop, s1.crop);
    const d23 = centerDistance2(s3.crop, s2.crop);
    const d03 = centerDistance2(s0.crop, s3.crop);
    if (d01 > SPIKE_THRESHOLD && d23 > SPIKE_THRESHOLD && d12 < SPIKE_THRESHOLD && d03 < 0.5 * Math.min(d01, d23)) {
      const dtTotal = Math.max(1e-6, s3.t - s0.t);
      const c0 = centerOf(s0.crop);
      const c3 = centerOf(s3.crop);
      const a1 = Math.max(0, Math.min(1, (s1.t - s0.t) / dtTotal));
      const a2 = Math.max(0, Math.min(1, (s2.t - s0.t) / dtTotal));
      s1.crop = boxFromCenter(s1.crop, c0.x + (c3.x - c0.x) * a1, c0.y + (c3.y - c0.y) * a1);
      s2.crop = boxFromCenter(s2.crop, c0.x + (c3.x - c0.x) * a2, c0.y + (c3.y - c0.y) * a2);
    }
  }
}
function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}
function medianFilterCenters(samples, start, end) {
  const length = end - start;
  if (length < MEDIAN_WINDOW) return;
  const half = Math.floor(MEDIAN_WINDOW / 2);
  const centers = samples.slice(start, end).map((s) => centerOf(s.crop));
  for (let i = 0; i < length; i++) {
    const lo = Math.max(0, i - half);
    const hi = Math.min(length, i + half + 1);
    const window = centers.slice(lo, hi);
    const cx = median(window.map((c) => c.x));
    const cy = median(window.map((c) => c.y));
    const sample = samples[start + i];
    sample.crop = boxFromCenter(sample.crop, cx, cy);
  }
}
function denoiseSegment(samples, start, end) {
  rejectCenterSpikes(samples, start, end);
  medianFilterCenters(samples, start, end);
}
function zeroPhaseEmaSegment(samples, start, end, lambdaEma) {
  const length = end - start;
  if (length <= 2) return;
  for (let index = start + 1; index < end; index++) {
    const current = samples[index];
    const previous = samples[index - 1];
    const dt = Math.max(1e-3, current.t - previous.t);
    const alpha = 1 - Math.exp(-lambdaEma * dt);
    current.crop = interpolateBox2(previous.crop, current.crop, alpha);
  }
  for (let index = end - 2; index >= start; index--) {
    const current = samples[index];
    const following = samples[index + 1];
    const dt = Math.max(1e-3, following.t - current.t);
    const alpha = 1 - Math.exp(-lambdaEma * dt);
    current.crop = interpolateBox2(following.crop, current.crop, alpha);
  }
}
function applyKinematicLimits(samples, sceneCuts) {
  let lastTime = -Infinity;
  let previousCrop = null;
  let previousVelocity = { x: 0, y: 0 };
  return samples.map((sample, index) => {
    if (hasSceneCutBetween(sceneCuts, lastTime, sample.t) || sample.cut) {
      previousCrop = null;
      previousVelocity = { x: 0, y: 0 };
      lastTime = sample.t;
      if (sample.cut) return sample;
    }
    lastTime = sample.t;
    if (!previousCrop) {
      previousCrop = sample.crop;
      return sample;
    }
    const limited = clampCameraMotion(
      previousCrop,
      sample.crop,
      previousVelocity,
      sample.t - (samples[index - 1]?.t ?? sample.t)
    );
    previousCrop = limited.crop;
    previousVelocity = limited.velocity;
    return { ...sample, crop: limited.crop };
  });
}
function smoothShotCropSamples(samples, sceneCuts, options) {
  if (!samples.length) return samples;
  const lambdaEma = options?.lambdaEma ?? DEFAULT_LAMBDA_EMA;
  const working = samples.map((sample) => ({
    ...sample,
    crop: { ...sample.crop }
  }));
  for (const { start, end } of continuousSegments(working, sceneCuts)) {
    denoiseSegment(working, start, end);
    zeroPhaseEmaSegment(working, start, end, lambdaEma);
  }
  return applyKinematicLimits(working, sceneCuts);
}

// src/features/clipper/engine/autoflip/layout/group-union-layout.util.ts
var EPSILON8 = 1e-9;
function minSubjectDisplayHeight(viewport, required) {
  if (!required.length) return 0;
  return Math.min(
    ...required.map((region) => {
      const top = Math.max(viewport.y, region.contentBox.y);
      const bottom = Math.min(viewport.y + viewport.height, region.contentBox.y + region.contentBox.height);
      const visible = Math.max(0, bottom - top);
      return visible / Math.max(EPSILON8, region.contentBox.height);
    })
  );
}
function groupUnionLexicographicOk(groupViewport, fallbackViewport, required) {
  const groupArea = viewportArea(groupViewport);
  const fallbackArea = viewportArea(fallbackViewport);
  if (groupArea > fallbackArea + EPSILON8) return false;
  const groupHeight = minSubjectDisplayHeight(groupViewport, required);
  const fallbackHeight = minSubjectDisplayHeight(fallbackViewport, required);
  return groupHeight + EPSILON8 >= fallbackHeight;
}
function unionBoxesForGroup(boxes) {
  const left = Math.min(...boxes.map((box) => box.x));
  const top = Math.min(...boxes.map((box) => box.y));
  const right = Math.max(...boxes.map((box) => box.x + box.width));
  const bottom = Math.max(...boxes.map((box) => box.y + box.height));
  return { x: left, y: top, width: right - left, height: bottom - top };
}
function fitAspectViewport(box, sourceAspect, targetAspect, minimumScale, margin) {
  const left = Math.max(0, box.x - box.width * margin);
  const top = Math.max(0, box.y - box.height * margin);
  const right = Math.min(1, box.x + box.width * (1 + margin));
  const bottom = Math.min(1, box.y + box.height * (1 + margin));
  const expanded = {
    x: left,
    y: top,
    width: right - left,
    height: bottom - top
  };
  const normalizedAspect = targetAspect / Math.max(1e-9, sourceAspect);
  const nominal = normalizedAspect <= 1 ? { width: normalizedAspect, height: 1 } : { width: 1, height: 1 / normalizedAspect };
  const scale = Math.max(
    minimumScale,
    expanded.width / Math.max(1e-9, nominal.width),
    expanded.height / Math.max(1e-9, nominal.height)
  );
  if (scale > 1 + 1e-9) return null;
  const width = nominal.width * scale;
  const height = nominal.height * scale;
  const minimumX = Math.max(0, expanded.x + expanded.width - width);
  const maximumX = Math.min(1 - width, expanded.x);
  const minimumY = Math.max(0, expanded.y + expanded.height - height);
  const maximumY = Math.min(1 - height, expanded.y);
  if (minimumX > maximumX + 1e-9 || minimumY > maximumY + 1e-9) return null;
  const centerX2 = expanded.x + expanded.width / 2;
  const centerY = expanded.y + expanded.height * framingCenterYFraction(expanded, height);
  return {
    x: Math.max(minimumX, Math.min(maximumX, centerX2 - width / 2)),
    y: Math.max(minimumY, Math.min(maximumY, centerY - height / 2)),
    width,
    height
  };
}
function buildGroupUnionLayout(boxes, sourceAspect, targetAspect, options = {}) {
  if (boxes.length < 2) return null;
  const minimumScale = options.minimumScale ?? 0.55;
  const margin = options.margin ?? 0.08;
  const common = fitAspectViewport(
    unionBoxesForGroup(boxes),
    sourceAspect,
    targetAspect,
    minimumScale,
    margin
  );
  if (common) {
    return {
      mode: "single-crop",
      viewports: [common],
      reasonCode: "group-union-crop"
    };
  }
  if (boxes.length !== 2) return null;
  const panels = [...boxes].sort((a, b) => a.x + a.width / 2 - (b.x + b.width / 2)).map(
    (box) => fitAspectViewport(
      box,
      sourceAspect,
      targetAspect * 2,
      minimumScale,
      margin
    )
  );
  if (!panels.every((panel) => panel != null))
    return null;
  return { mode: "split", viewports: panels, reasonCode: "group-stable-split" };
}

// src/features/clipper/engine/autoflip/layout/viewport-builder.util.ts
function buildViewports(mode, importance, fallbackCrop, sourceAspect, targetAspect, framing, visibilityState, cut = false, allowGroupUnion = false, groupUnionMeta) {
  const required = requiredRegions(importance);
  if (allowGroupUnion && mode === "single-crop" && required.length >= 3 && required[0]?.kind === "action") {
    const groupUnion = buildGroupUnionLayout(
      required.map((region) => region.contentBox),
      sourceAspect,
      targetAspect
    );
    if (groupUnion?.reasonCode === "group-union-crop") {
      if (groupUnionMeta) groupUnionMeta.used = true;
      return groupUnion.viewports;
    }
  }
  if (mode === "single-crop" || !required.length) {
    const primary = required.find((region) => region.role === "primary") ?? required[0];
    const legacyViewport = strictAspectViewport(fallbackCrop, sourceAspect, targetAspect);
    if (!primary) return [legacyViewport];
    if (!framing) return [centerViewportOnBox(legacyViewport, primary.box)];
    const legacySemanticViewport = centerViewportOnBox(legacyViewport, primary.box);
    if (framing.visibilityConstrained && visibilityState) {
      return [visibilityConstrainedViewport(
        importance,
        legacySemanticViewport,
        sourceAspect,
        targetAspect,
        framing,
        visibilityState,
        cut
      )];
    }
    const target = framing.targetBoxSource === "contentBox" ? primary.contentBox : primary.box;
    return [cropAroundBox(
      target,
      sourceAspect,
      targetAspect,
      framing.minimumScale,
      framing.padding,
      framing.centerYFraction
    )];
  }
  if (mode === "split" && (targetAspect > 1 || required.length < 2)) {
    return buildViewports(
      "single-crop",
      importance,
      fallbackCrop,
      sourceAspect,
      targetAspect,
      framing,
      visibilityState,
      cut,
      allowGroupUnion,
      groupUnionMeta
    );
  }
  if (mode === "split" && required.length === 2) {
    const panelAspect = targetAspect * 2;
    const panelRegions = [
      { id: required[0].id, box: required[0].box, contentBox: required[0].contentBox },
      { id: required[1].id, box: required[1].box, contentBox: required[1].contentBox }
    ];
    const panels = fitSeparatedSplitPanels(panelRegions, sourceAspect, [panelAspect, panelAspect]);
    return panels ?? buildViewports(
      "single-crop",
      importance,
      fallbackCrop,
      sourceAspect,
      targetAspect,
      framing,
      visibilityState,
      cut,
      allowGroupUnion,
      groupUnionMeta
    );
  }
  if (mode === "split" && required.length >= 3) {
    const primary = required.find((region) => region.role === "primary") ?? required[0];
    const secondary = required.filter((region) => region.id !== primary.id).sort((a, b) => a.contentBox.x + a.contentBox.width / 2 - (b.contentBox.x + b.contentBox.width / 2));
    const ordered = [primary, ...secondary].slice(0, 3);
    const aspects = targetAspect < 1 ? [targetAspect * 2, targetAspect, targetAspect] : [targetAspect * 0.6, targetAspect * 0.8, targetAspect * 0.8];
    return ordered.map((region, index) => cropAroundBox(region.contentBox, sourceAspect, aspects[index]));
  }
  const union2 = unionAll(required.map((region) => region.contentBox)) ?? required[0].contentBox;
  return [strictAspectViewport(expandBox(union2, 0.12), sourceAspect, targetAspect)];
}

// src/features/clipper/engine/autoflip/layout/trajectory-smoothing.util.ts
var DEFAULT_SPIKE_THRESHOLD = 0.04;
var DEFAULT_LAMBDA_EMA2 = 4;
function boxDistance(a, b) {
  const cxA = a.x + a.width / 2;
  const cyA = a.y + a.height / 2;
  const cxB = b.x + b.width / 2;
  const cyB = b.y + b.height / 2;
  return Math.hypot(cxA - cxB, cyA - cyB);
}
function interpolateBox3(a, b, alpha) {
  const clampedAlpha = Math.max(0, Math.min(1, alpha));
  return {
    x: a.x + (b.x - a.x) * clampedAlpha,
    y: a.y + (b.y - a.y) * clampedAlpha,
    width: a.width + (b.width - a.width) * clampedAlpha,
    height: a.height + (b.height - a.height) * clampedAlpha
  };
}
function panelOwnerKey(sample) {
  return sample.mode === "split" ? sample.panelSubjects?.map((subject) => subject.id).join("|") ?? "unknown" : "single";
}
function sameLayoutIdentity(a, b) {
  return a.mode === b.mode && a.viewports.length === b.viewports.length && panelOwnerKey(a) === panelOwnerKey(b);
}
function validSplit(sample, viewports) {
  return sample.mode !== "split" || splitViewportsAreDistinct(viewports) && splitPanelsPreserveSubjects(viewports, sample.panelSubjects);
}
function smoothLayoutTrackSamples(samples, options) {
  if (!samples || samples.length <= 2) return samples;
  const spikeThreshold = options?.spikeThreshold ?? DEFAULT_SPIKE_THRESHOLD;
  const lambdaEma = options?.lambdaEma ?? DEFAULT_LAMBDA_EMA2;
  const cleaned = samples.map((s) => ({
    ...s,
    viewports: s.viewports.map((v) => ({ ...v })),
    candidateViewports: s.candidateViewports?.map((v) => ({ ...v })),
    baselineViewports: s.baselineViewports?.map((v) => ({ ...v }))
  }));
  const n = cleaned.length;
  for (let i = 1; i < n - 1; i++) {
    const prev = cleaned[i - 1];
    const curr = cleaned[i];
    const next = cleaned[i + 1];
    if (curr.cut || next.cut) continue;
    if (!sameLayoutIdentity(prev, curr) || !sameLayoutIdentity(curr, next)) continue;
    const interpolatedViewports = [];
    let isSpike = false;
    for (let vIdx = 0; vIdx < curr.viewports.length; vIdx++) {
      const vPrev = prev.viewports[vIdx];
      const vCurr = curr.viewports[vIdx];
      const vNext = next.viewports[vIdx];
      const dPrev = boxDistance(vCurr, vPrev);
      const dNext = boxDistance(vCurr, vNext);
      const dOuter = boxDistance(vPrev, vNext);
      if (dPrev > spikeThreshold && dNext > spikeThreshold && dOuter < 0.5 * Math.min(dPrev, dNext)) {
        isSpike = true;
        const dtTotal = Math.max(1e-6, next.t - prev.t);
        const alpha = Math.max(0, Math.min(1, (curr.t - prev.t) / dtTotal));
        interpolatedViewports.push(interpolateBox3(vPrev, vNext, alpha));
      } else {
        interpolatedViewports.push(vCurr);
      }
    }
    if (isSpike && validSplit(curr, interpolatedViewports)) {
      curr.viewports = interpolatedViewports;
      curr.reasonCodes = [...curr.reasonCodes ?? [], "spike-filtered-1"];
    }
  }
  for (let i = 1; i < n - 2; i++) {
    const s0 = cleaned[i - 1];
    const s1 = cleaned[i];
    const s2 = cleaned[i + 1];
    const s3 = cleaned[i + 2];
    if (s1.cut || s2.cut || s3.cut) continue;
    if (!sameLayoutIdentity(s0, s1) || !sameLayoutIdentity(s1, s2) || !sameLayoutIdentity(s2, s3)) continue;
    let isSpike2 = false;
    const interpolatedS1 = [];
    const interpolatedS2 = [];
    for (let vIdx = 0; vIdx < s1.viewports.length; vIdx++) {
      const v0 = s0.viewports[vIdx];
      const v1 = s1.viewports[vIdx];
      const v2 = s2.viewports[vIdx];
      const v3 = s3.viewports[vIdx];
      const d01 = boxDistance(v1, v0);
      const d12 = boxDistance(v2, v1);
      const d23 = boxDistance(v3, v2);
      const d03 = boxDistance(v0, v3);
      if (d01 > spikeThreshold && d23 > spikeThreshold && d12 < spikeThreshold && d03 < 0.5 * Math.min(d01, d23)) {
        isSpike2 = true;
        const dtTotal = Math.max(1e-6, s3.t - s0.t);
        const alpha1 = Math.max(0, Math.min(1, (s1.t - s0.t) / dtTotal));
        const alpha2 = Math.max(0, Math.min(1, (s2.t - s0.t) / dtTotal));
        interpolatedS1.push(interpolateBox3(v0, v3, alpha1));
        interpolatedS2.push(interpolateBox3(v0, v3, alpha2));
      } else {
        interpolatedS1.push(v1);
        interpolatedS2.push(v2);
      }
    }
    if (isSpike2 && validSplit(s1, interpolatedS1) && validSplit(s2, interpolatedS2)) {
      s1.viewports = interpolatedS1;
      s1.reasonCodes = [...s1.reasonCodes ?? [], "spike-filtered-2"];
      s2.viewports = interpolatedS2;
      s2.reasonCodes = [...s2.reasonCodes ?? [], "spike-filtered-2"];
    }
  }
  const smoothed = cleaned.map((s) => ({
    ...s,
    viewports: s.viewports.map((v) => ({ ...v }))
  }));
  let segmentStart = 0;
  while (segmentStart < cleaned.length) {
    let segmentEnd = segmentStart + 1;
    while (segmentEnd < cleaned.length && !cleaned[segmentEnd].cut && sameLayoutIdentity(cleaned[segmentEnd], cleaned[segmentStart])) segmentEnd++;
    for (let index = segmentStart + 1; index < segmentEnd; index++) {
      const current = cleaned[index];
      const previous = smoothed[index - 1];
      const dt = Math.max(1e-3, current.t - cleaned[index - 1].t);
      const alpha = 1 - Math.exp(-lambdaEma * dt);
      const proposed = current.viewports.map((viewport, viewportIndex) => interpolateBox3(previous.viewports[viewportIndex], viewport, alpha));
      smoothed[index].viewports = validSplit(current, proposed) ? proposed : previous.viewports.map((viewport) => ({ ...viewport }));
    }
    for (let index = segmentEnd - 2; index >= segmentStart; index--) {
      const current = smoothed[index];
      const following = smoothed[index + 1];
      const dt = Math.max(1e-3, cleaned[index + 1].t - cleaned[index].t);
      const alpha = 1 - Math.exp(-lambdaEma * dt);
      const proposed = current.viewports.map((viewport, viewportIndex) => interpolateBox3(following.viewports[viewportIndex], viewport, alpha));
      current.viewports = validSplit(cleaned[index], proposed) ? proposed : following.viewports.map((viewport) => ({ ...viewport }));
    }
    segmentStart = segmentEnd;
  }
  return smoothed;
}

// src/features/clipper/engine/autoflip/layout/offline-split-confirmation.util.ts
var EPSILON9 = 1e-9;
function stableSplitVariant(sample) {
  if (sample.reasonCodes?.includes("stable-split-dropout-hold")) return void 0;
  return sample.candidateVariants?.find((variant2) => (variant2.kind === "stable-split-v2" || variant2.kind === "stable-split-v3" || variant2.kind === "stable-split-3") && variant2.viewports.length >= 2);
}
function appendReason(sample, reasonCode) {
  if (!(sample.reasonCodes ?? []).includes(reasonCode)) {
    sample.reasonCodes = [...sample.reasonCodes ?? [], reasonCode];
  }
}
function promoteStableSplit(sample, reasonCode, split = stableSplitVariant(sample)) {
  persistStableSplitCandidate(sample, split, reasonCode);
  sample.mode = "split";
  sample.strategy = "semantic-split";
  sample.viewports = split.viewports.map((viewport) => ({ ...viewport }));
  sample.selectedRequiredCoverage = [...split.requiredCoverage];
  sample.panelSubjects = split.panelSubjects?.map((subject) => ({ id: subject.id, focusBox: { ...subject.focusBox } }));
}
function persistStableSplitCandidate(sample, split, reasonCode) {
  sample.candidateMode = "split";
  sample.candidateViewports = split.viewports.map((viewport) => ({ ...viewport }));
  if (!stableSplitVariant(sample)) {
    sample.candidateVariants = [...sample.candidateVariants ?? [], {
      kind: split.kind,
      mode: "split",
      viewports: split.viewports.map((viewport) => ({ ...viewport })),
      requiredCoverage: [...split.requiredCoverage],
      panelSubjects: split.panelSubjects?.map((subject) => ({ id: subject.id, focusBox: { ...subject.focusBox } }))
    }];
  }
  appendReason(sample, reasonCode);
}
function splitIdentityKey(sample) {
  return [...sample.requiredRegionIds].sort().join("|");
}
function compatibleSplitBoundaries(left, right) {
  const leftSplit = stableSplitVariant(left);
  const rightSplit = stableSplitVariant(right);
  if (!leftSplit || !rightSplit || leftSplit.viewports.length !== rightSplit.viewports.length) return false;
  const leftOwners = leftSplit.panelSubjects;
  const rightOwners = rightSplit.panelSubjects;
  if (leftOwners && rightOwners && leftOwners.length === rightOwners.length) {
    if (leftOwners.every((owner, index) => owner.id === rightOwners[index]?.id)) {
      return true;
    }
  }
  if (splitIdentityKey(left) === splitIdentityKey(right)) return true;
  const sharedIds = left.requiredRegionIds.filter((id) => right.requiredRegionIds.includes(id));
  if (sharedIds.length > 0) return true;
  return leftSplit.viewports.every((leftPanel, index) => {
    const rightPanel = rightSplit.viewports[index];
    const overlapWidth = Math.max(0, Math.min(leftPanel.x + leftPanel.width, rightPanel.x + rightPanel.width) - Math.max(leftPanel.x, rightPanel.x));
    const overlapHeight = Math.max(0, Math.min(leftPanel.y + leftPanel.height, rightPanel.y + rightPanel.height) - Math.max(leftPanel.y, rightPanel.y));
    return overlapWidth * overlapHeight > EPSILON9;
  });
}
function interpolateSplit(left, right, progress) {
  const viewports = left.viewports.map((leftPanel, index) => {
    const rightPanel = right.viewports[index];
    return {
      x: leftPanel.x + (rightPanel.x - leftPanel.x) * progress,
      y: leftPanel.y + (rightPanel.y - leftPanel.y) * progress,
      width: leftPanel.width + (rightPanel.width - leftPanel.width) * progress,
      height: leftPanel.height + (rightPanel.height - leftPanel.height) * progress
    };
  });
  return {
    kind: left.kind,
    mode: "split",
    viewports,
    requiredCoverage: left.requiredCoverage.map((value, index) => Math.min(value, right.requiredCoverage[index] ?? value)),
    panelSubjects: left.panelSubjects?.map((subject) => ({ id: subject.id, focusBox: { ...subject.focusBox } }))
  };
}
function confirmOfflineSplitEntries(samples) {
  const confirmed = samples.map((sample) => ({
    ...sample,
    viewports: sample.viewports.map((viewport) => ({ ...viewport })),
    candidateViewports: sample.candidateViewports?.map((viewport) => ({ ...viewport }))
  }));
  let start = 0;
  while (start < confirmed.length) {
    const initial = stableSplitVariant(confirmed[start]);
    if (!initial) {
      start++;
      continue;
    }
    let end = start + 1;
    while (end < confirmed.length && !confirmed[end].cut && stableSplitVariant(confirmed[end])) end++;
    const firstSelected = confirmed.slice(start, end).findIndex((sample) => sample.mode === "split" && sample.viewports.length >= 2);
    if (firstSelected >= 0) {
      for (let index = start; index < end; index++) {
        const sample = confirmed[index];
        if (sample.mode !== "split" || sample.viewports.length < 2) {
          promoteStableSplit(sample, "offline-split-confirmed");
        }
      }
    }
    start = end;
  }
  return confirmed;
}
function bridgeTransientSplitGaps(samples, splitExitStableSec) {
  const denoised = samples.map((sample) => ({
    ...sample,
    viewports: sample.viewports.map((viewport) => ({ ...viewport })),
    candidateViewports: sample.candidateViewports?.map((viewport) => ({ ...viewport }))
  }));
  let cursor = 1;
  while (cursor < denoised.length - 1) {
    if (stableSplitVariant(denoised[cursor]) || denoised[cursor].cut) {
      cursor++;
      continue;
    }
    const start = cursor;
    while (cursor < denoised.length && !stableSplitVariant(denoised[cursor]) && !denoised[cursor].cut) cursor++;
    const end = cursor;
    const left = denoised[start - 1];
    const right = denoised[end];
    const gapElapsed = right == null ? Number.POSITIVE_INFINITY : right.t - left.t;
    const compatible = right != null && stableSplitVariant(left) != null && stableSplitVariant(right) != null && gapElapsed <= splitExitStableSec + EPSILON9 && compatibleSplitBoundaries(left, right);
    if (compatible) {
      const leftSplit = stableSplitVariant(left);
      const rightSplit = stableSplitVariant(right);
      const count = end - start;
      for (let index = start; index < end; index++) {
        const progress = (index - start + 1) / (count + 1);
        persistStableSplitCandidate(
          denoised[index],
          interpolateSplit(leftSplit, rightSplit, progress),
          "transient-baseline-gap-bridged"
        );
      }
    }
    cursor = Math.max(end + 1, start + 1);
  }
  return confirmOfflineSplitEntries(denoised);
}

// src/features/clipper/engine/autoflip/layout/short-split-policy.util.ts
var MINIMUM_SPLIT_DURATION_SEC = 2;
var MINIMUM_ORPHAN_SPLIT_DURATION_SEC = 0.75;
var HIGH_CONFIDENCE_SPLIT_THRESHOLD = 0.8;
var UNSAFE_BASELINE_COVERAGE = 0.85;
function hasSplit(sample, source) {
  return source === "selected" ? sample.mode === "split" && sample.viewports.length >= 2 : sample.candidateMode === "split" && (sample.candidateViewports?.length ?? 0) >= 2;
}
function hasStableSplitVariant(sample) {
  return sample.candidateVariants?.some((variant2) => variant2.kind === "stable-split-v2" || variant2.kind === "stable-split-v3" || variant2.kind === "stable-split-3") ?? false;
}
function baselineMissesRequiredTarget(sample) {
  const coverage2 = sample.baselineRequiredCoverage;
  return coverage2?.some((value) => value < UNSAFE_BASELINE_COVERAGE) ?? false;
}
function isHighConfidenceSplitSample(sample) {
  return sample.requiredRegionIds.length >= 2 && sample.targetEvidence?.status === "qualified" && (sample.decisionConfidence ?? 0) >= HIGH_CONFIDENCE_SPLIT_THRESHOLD && hasStableSplitVariant(sample) && baselineMissesRequiredTarget(sample);
}
function splitRun(samples, index, source) {
  if (!samples[index] || !hasSplit(samples[index], source)) return [];
  let start = index;
  while (start > 0 && hasSplit(samples[start - 1], source) && !samples[start].cut) start--;
  let end = index + 1;
  while (end < samples.length && hasSplit(samples[end], source) && !samples[end].cut) end++;
  return samples.slice(start, end);
}
function isShortSplitRun(samples, index, source) {
  const run = splitRun(samples, index, source);
  if (!run.length) return false;
  const endTime = run.at(-1).t;
  return endTime - run[0].t < MINIMUM_SPLIT_DURATION_SEC;
}
function isShortSelectedSplitRun(samples, index) {
  return isShortSplitRun(samples, index, "selected");
}
function shouldKeepShortSplitRun(samples, index) {
  const source = hasSplit(samples[index], "selected") ? "selected" : "candidate";
  const run = splitRun(samples, index, source);
  if (!run.length) return false;
  const endTime = run.at(-1).t;
  if (endTime - run[0].t < MINIMUM_ORPHAN_SPLIT_DURATION_SEC) return false;
  if (endTime - run[0].t >= MINIMUM_SPLIT_DURATION_SEC) return true;
  return run.every(isHighConfidenceSplitSample);
}
function withShortSplitConfidenceReason(sample) {
  const reasonCodes = sample.reasonCodes ?? [];
  return reasonCodes.includes("short-split-confidence-rescue") ? sample : { ...sample, reasonCodes: [...reasonCodes, "short-split-confidence-rescue"] };
}

// src/features/clipper/engine/autoflip/layout/layout-planner.util.ts
var EPSILON10 = 1e-9;
function removeShortSplitRuns(samples) {
  const stabilized = samples.map((sample) => ({ ...sample, viewports: [...sample.viewports] }));
  for (let index = 0; index < stabilized.length; index++) {
    const sample = stabilized[index];
    if (sample.mode !== "split" || !isShortSelectedSplitRun(stabilized, index)) continue;
    if (shouldKeepShortSplitRun(stabilized, index)) {
      stabilized[index] = withShortSplitConfidenceReason(sample);
      continue;
    }
    sample.mode = "single-crop";
    sample.strategy = "legacy-baseline";
    sample.viewports = sample.baselineViewports?.map((viewport) => ({ ...viewport })) ?? [sample.viewports[0]];
    sample.reasonCodes = [...sample.reasonCodes ?? [], "split-too-short"];
  }
  return stabilized;
}
function buildLayoutTracks(input2) {
  const sourceAspect = input2.frameWidth / Math.max(1, input2.frameHeight);
  const arbiterParams = input2.arbiterParams ?? DEFAULT_ARBITER_PARAMS;
  return Object.fromEntries(Object.entries(input2.aspectTracks).map(([formatId, aspectTrack]) => {
    const visibilityState = createVisibilityFramingState();
    const visibilityControllerState = createVisibilityControllerState();
    const samples = aspectTrack.samples.map((cropSample) => {
      const importance = importanceAtTime(input2.importanceSamples, cropSample.t);
      const required = requiredRegions(importance);
      const baselineMode = "single-crop";
      const baselineViewports = [cropSample.crop];
      const importanceIndex = precedingIndex(input2.importanceSamples, cropSample.t);
      let desiredMode = rawMode(importance, sourceAspect, aspectTrack.targetAspectRatio);
      const groupUnionMeta = { used: false };
      let semanticViewports = buildViewports(
        desiredMode,
        importance,
        cropSample.crop,
        sourceAspect,
        aspectTrack.targetAspectRatio,
        input2.semanticFramingParams,
        visibilityState,
        Boolean(cropSample.cut),
        Boolean(arbiterParams.allowGroupUnion),
        groupUnionMeta
      );
      if (desiredMode === "split" && semanticViewports.length < 2) {
        desiredMode = "single-crop";
      }
      if (groupUnionMeta.used) {
        const fallbackViewports = buildViewports(
          desiredMode,
          importance,
          cropSample.crop,
          sourceAspect,
          aspectTrack.targetAspectRatio,
          input2.semanticFramingParams,
          visibilityState,
          Boolean(cropSample.cut),
          false
        );
        if (!groupUnionLexicographicOk(semanticViewports[0], fallbackViewports[0], required)) {
          semanticViewports = fallbackViewports;
        }
      }
      const visibilityDecision = input2.visibilityControllerParams?.enabled ? planVisibilityRescue({
        samples: input2.importanceSamples,
        importanceIndex,
        baselineViewport: baselineViewports[0],
        sourceAspect,
        targetAspect: aspectTrack.targetAspectRatio,
        state: visibilityControllerState,
        params: input2.visibilityControllerParams
      }) : null;
      if (visibilityDecision) {
        desiredMode = visibilityDecision.mode;
        semanticViewports = visibilityDecision.viewports;
      }
      const coverageRegions = visibilityDecision?.envelopes ?? required;
      const baselineScore = proposalScore(baselineViewports, coverageRegions);
      const semanticScore = proposalScore(semanticViewports, coverageRegions);
      const baselineCoverage = coverageRegions.length ? Math.min(...coverageRegions.map((region) => Math.max(...baselineViewports.map((viewport) => coveredFraction(viewport, region.contentBox))))) : 1;
      const decision = decideLayoutStrategy({
        desiredMode,
        baselineScore,
        semanticScore,
        controllerReasonCodes: visibilityDecision?.reasonCodes,
        baselineCoverage
      }, arbiterParams);
      return {
        t: cropSample.t,
        mode: decision.selectSemantic ? desiredMode : baselineMode,
        strategy: decision.strategy,
        viewports: decision.selectSemantic ? semanticViewports : baselineViewports,
        candidateMode: desiredMode,
        candidateViewports: semanticViewports,
        baselineViewports,
        primaryRegionId: required.find((region) => region.role === "primary")?.id,
        requiredRegionIds: required.map((region) => region.id),
        panelSubjects: decision.selectSemantic && desiredMode === "split" ? visibilityDecision?.panelSubjects?.map((subject) => ({
          id: subject.id,
          focusBox: { ...subject.focusBox }
        })) : void 0,
        baselineScore,
        semanticScore,
        decisionConfidence: decision.decisionConfidence,
        reasonCodes: decision.reasonCodes,
        targetEvidence: importance.targetEvidence,
        candidateVariants: visibilityDecision?.variants,
        baselineRequiredCoverage: visibilityDecision?.baselineCoverage,
        selectedRequiredCoverage: decision.selectSemantic ? visibilityDecision?.selectedCoverage : visibilityDecision?.baselineCoverage,
        visibilityRisk: visibilityDecision?.visibilityRisk,
        qualityTelemetry: visibilityDecision ? {
          containDutyCandidate: false,
          subjectDisplayHeightFractions: coverageRegions.map((region) => Math.min(1, Math.max(
            ...(decision.selectSemantic ? semanticViewports : baselineViewports).map((viewport) => region.contentBox.height / Math.max(EPSILON10, viewport.height))
          )))
        } : void 0,
        coverageBoxes: coverageRegions.map((region) => ({ ...region.contentBox })),
        cut: cropSample.cut,
        solidBackgroundColor: cropSample.solidBackgroundColor
      };
    });
    const denoisedSamples = bridgeTransientSplitGaps(
      samples,
      input2.visibilityControllerParams?.splitExitStableSec ?? 0
    );
    const smoothedSamples = smoothLayoutTrackSamples(denoisedSamples);
    return [formatId, { targetAspectRatio: aspectTrack.targetAspectRatio, samples: removeShortSplitRuns(smoothedSamples) }];
  }));
}

// src/features/clipper/engine/autoflip/config/kinematic-options.util.ts
function kinematicOptionsForSmooth() {
  return {
    minMotionToReframe: 1.2,
    reframeWindow: 0.35,
    updateRateSeconds: 0.35,
    maxUpdateRate: 0.45,
    maxVelocity: 12,
    filteringTimeWindowUs: 5e5,
    meanPeriodUpdateRate: 0.15
  };
}

// src/features/clipper/engine/autoflip/identity/active-speaker.util.ts
var DEFAULT_ACTIVE_SPEAKER_POLICY = {
  threshold: 0.6,
  runnerUpMargin: 0.1,
  stableMultiFaceSamples: 5,
  maximumSampleGapSec: 0.6,
  minimumMultiFaceDurationSec: 1,
  minimumHoldSec: 0.8
};
function applyActiveSpeakerPolicy(samples, policy = DEFAULT_ACTIVE_SPEAKER_POLICY) {
  const telemetry = {
    enabled: false,
    evaluatedWindows: 0,
    speakerSwitches: 0,
    ambiguousWindows: 0,
    asdDutyCycle: 0
  };
  const disabledReason = samples.find((sample) => sample.activeSpeakerDisabledReason)?.activeSpeakerDisabledReason;
  const invalidContract = samples.some((sample) => sample.activeSpeakerScores?.some((score) => !Number.isFinite(score.confidence) || score.confidence < 0 || score.confidence > 1));
  if (disabledReason || invalidContract) {
    telemetry.disabledReason = disabledReason ?? "tensor-contract-mismatch";
    return { samples, telemetry };
  }
  let stableSamples = 0;
  let previousTime = null;
  let multiFaceStartedAt = null;
  let activeTrackId = null;
  let activeSince = Number.NEGATIVE_INFINITY;
  let signalSamples = 0;
  const output = samples.map((sample) => {
    const observed = (sample.autoflipFaces ?? []).filter((face2) => face2.trackId != null && !face2.predicted);
    if (sample.sceneCut || previousTime == null || sample.time - previousTime > policy.maximumSampleGapSec) {
      stableSamples = observed.length >= 2 ? 1 : 0;
      multiFaceStartedAt = observed.length >= 2 ? sample.time : null;
      activeTrackId = null;
      activeSince = Number.NEGATIVE_INFINITY;
    } else {
      stableSamples = observed.length >= 2 ? stableSamples + 1 : 0;
      if (observed.length >= 2) multiFaceStartedAt ??= sample.time;
      else multiFaceStartedAt = null;
    }
    previousTime = sample.time;
    const stableDuration = multiFaceStartedAt == null ? 0 : sample.time - multiFaceStartedAt;
    if (stableSamples < policy.stableMultiFaceSamples || stableDuration + 1e-9 < policy.minimumMultiFaceDurationSec || !sample.activeSpeakerScores?.length) return sample;
    telemetry.evaluatedWindows++;
    const faces = new Map(observed.map((face2) => [face2.trackId, face2]));
    const ranked = sample.activeSpeakerScores.filter((score) => faces.has(score.trackId) && Number.isFinite(score.confidence)).sort((a, b) => b.confidence - a.confidence);
    const winner = ranked[0];
    const runnerUp = ranked[1]?.confidence ?? 0;
    if (!winner || winner.confidence < policy.threshold || winner.confidence - runnerUp < policy.runnerUpMargin) {
      telemetry.ambiguousWindows++;
      return sample;
    }
    if (activeTrackId != null && winner.trackId !== activeTrackId && sample.time - activeSince < policy.minimumHoldSec) {
      return sample;
    }
    if (winner.trackId !== activeTrackId) {
      if (activeTrackId != null) telemetry.speakerSwitches++;
      activeTrackId = winner.trackId;
      activeSince = sample.time;
    }
    const face = faces.get(winner.trackId);
    signalSamples++;
    return {
      ...sample,
      importanceSignals: [
        ...sample.importanceSignals ?? [],
        {
          box: face.box,
          kind: "active-speaker",
          confidence: winner.confidence,
          trackId: winner.trackId,
          predicted: false
        }
      ]
    };
  });
  telemetry.enabled = telemetry.evaluatedWindows > 0;
  telemetry.asdDutyCycle = samples.length ? signalSamples / samples.length : 0;
  if (!telemetry.enabled) telemetry.disabledReason = "insufficient-stable-canonical-persons";
  return { samples: output, telemetry };
}

// src/features/clipper/engine/autoflip/identity/canonical-person.util.ts
var MAX_DROPOUT_SEC = 0.9;
var EPSILON11 = 1e-9;
function center(box) {
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}
function area(box) {
  return Math.max(0, box.width) * Math.max(0, box.height);
}
function iou(a, b) {
  const left = Math.max(a.x, b.x);
  const top = Math.max(a.y, b.y);
  const right = Math.min(a.x + a.width, b.x + b.width);
  const bottom = Math.min(a.y + a.height, b.y + b.height);
  const intersection = Math.max(0, right - left) * Math.max(0, bottom - top);
  return intersection / Math.max(EPSILON11, area(a) + area(b) - intersection);
}
function containsCenter(container, child) {
  const point = center(child);
  return point.x >= container.x && point.x <= container.x + container.width && point.y >= container.y && point.y <= container.y + container.height;
}
function trackBox(track) {
  return track.personBox ?? track.poseBox ?? track.faceBox;
}
function predictedCenter(track, time) {
  const box = trackBox(track);
  const current = box ? center(box) : { x: 0.5, y: 0.5 };
  const dt = Math.max(0, Math.min(MAX_DROPOUT_SEC, time - track.lastObservedTime));
  return { x: current.x + track.velocity.x * dt, y: current.y + track.velocity.y * dt };
}
function associationScore(track, evidence, kind, time) {
  const box = trackBox(track);
  if (!box || time - track.lastObservedTime > MAX_DROPOUT_SEC + EPSILON11) return Number.NEGATIVE_INFINITY;
  const priorId = kind === "person" ? track.personSourceId : kind === "face" ? track.faceSourceId : track.poseSourceId;
  const point = center(evidence.box);
  const expected = predictedCenter(track, time);
  const distance = Math.hypot(point.x - expected.x, point.y - expected.y);
  const overlap = iou(box, evidence.box);
  const containment = kind === "face" ? Number(containsCenter(track.personBox ?? box, evidence.box)) : Number(containsCenter(evidence.box, track.faceBox ?? box) || containsCenter(box, evidence.box));
  const continuity = evidence.sourceId != null && evidence.sourceId === priorId ? 2.5 : 0;
  let score = continuity + overlap * 1.6 + containment * 0.9 + Math.max(0, 0.65 - distance) * 1.4;
  const geometryValid = continuity > 0 || overlap >= 0.08 || containment > 0 || distance <= 0.28;
  return geometryValid ? score : Number.NEGATIVE_INFINITY;
}
function assignGlobally(evidence, tracks, kind, time) {
  if (evidence.length === 0 || tracks.length === 0) return /* @__PURE__ */ new Map();
  const scores = evidence.map((item) => tracks.map((track) => associationScore(track, item, kind, time)));
  const eligible = scores.map((row) => row.map((score) => Number.isFinite(score) && score >= 0.45));
  const best = maximumWeightAssignment(scores, eligible, tracks.length);
  const result = /* @__PURE__ */ new Map();
  for (const [evidenceIndex, trackIndex] of best.entries()) {
    if (trackIndex == null || !eligible[evidenceIndex][trackIndex]) continue;
    const row = scores[evidenceIndex];
    const selected = row[trackIndex];
    const runnerUp = Math.max(0, ...row.filter((score, index) => index !== trackIndex && Number.isFinite(score)));
    const confidence = Math.max(0, Math.min(1, 0.45 + selected / 5));
    result.set(evidenceIndex, { track: tracks[trackIndex], confidence, ambiguous: selected - runnerUp < 0.25 });
  }
  return result;
}
function maximumWeightAssignment(scores, eligible, trackCount) {
  const rowCount = scores.length;
  const columnCount = trackCount + rowCount;
  const u = new Array(rowCount + 1).fill(0);
  const v = new Array(columnCount + 1).fill(0);
  const p = new Array(columnCount + 1).fill(0);
  const way = new Array(columnCount + 1).fill(0);
  for (let row = 1; row <= rowCount; row++) {
    p[0] = row;
    let column = 0;
    const minValue = new Array(columnCount + 1).fill(Number.POSITIVE_INFINITY);
    const used = new Array(columnCount + 1).fill(false);
    do {
      used[column] = true;
      const currentRow = p[column];
      let delta = Number.POSITIVE_INFINITY;
      let nextColumn = 0;
      for (let candidateColumn = 1; candidateColumn <= columnCount; candidateColumn++) {
        if (used[candidateColumn]) continue;
        const trackIndex = candidateColumn - 1;
        const weight = trackIndex < trackCount && eligible[currentRow - 1][trackIndex] ? scores[currentRow - 1][trackIndex] : 0;
        const reducedCost = -weight - u[currentRow] - v[candidateColumn];
        if (reducedCost < minValue[candidateColumn]) {
          minValue[candidateColumn] = reducedCost;
          way[candidateColumn] = column;
        }
        if (minValue[candidateColumn] < delta) {
          delta = minValue[candidateColumn];
          nextColumn = candidateColumn;
        }
      }
      for (let index = 0; index <= columnCount; index++) {
        if (used[index]) {
          u[p[index]] += delta;
          v[index] -= delta;
        } else {
          minValue[index] -= delta;
        }
      }
      column = nextColumn;
    } while (p[column] !== 0);
    do {
      const previousColumn = way[column];
      p[column] = p[previousColumn];
      column = previousColumn;
    } while (column !== 0);
  }
  const assignment = new Array(rowCount).fill(-1);
  for (let column = 1; column <= trackCount; column++) {
    const row = p[column];
    if (row > 0) assignment[row - 1] = column - 1;
  }
  return assignment;
}
function snapshot(track, time) {
  return {
    canonicalId: track.canonicalId,
    personBox: track.personBox,
    faceBox: track.faceBox,
    poseBox: track.poseBox,
    sources: [...track.sources],
    confidence: track.confidence,
    associationConfidence: track.associationConfidence,
    velocity: { ...track.velocity },
    lastObservedTime: track.lastObservedTime,
    state: time - track.lastObservedTime > EPSILON11 ? "predicted" : track.state,
    identityAmbiguous: track.identityAmbiguous
  };
}
function observedPersonEvidence(sample) {
  return sample.detections.filter((item) => item.label.toLowerCase() === "person").map((value) => ({
    value,
    box: value.box,
    sourceId: value.trackId,
    predicted: Boolean(value.predicted),
    confidence: value.score
  }));
}
function buildCanonicalPersonTracks(samples) {
  const telemetry = {
    births: 0,
    deaths: 0,
    switches: 0,
    ambiguousSamples: 0,
    sampleCount: samples.length,
    dropoutDurationsSec: [],
    successfulReacquisitions: 0,
    associationConfidences: []
  };
  let tracks = [];
  let nextId = 1;
  const sourceOwners = {
    person: /* @__PURE__ */ new Map(),
    face: /* @__PURE__ */ new Map(),
    pose: /* @__PURE__ */ new Map()
  };
  const recordSourceOwner = (kind, sourceId, canonicalId) => {
    if (sourceId == null) return;
    const previous = sourceOwners[kind].get(sourceId);
    if (previous != null && previous !== canonicalId) telemetry.switches++;
    sourceOwners[kind].set(sourceId, canonicalId);
  };
  const output = [...samples].sort((a, b) => a.time - b.time).map((sample) => {
    if (sample.sceneCut) {
      telemetry.deaths += tracks.length;
      tracks = [];
      nextId = 1;
      sourceOwners.person.clear();
      sourceOwners.face.clear();
      sourceOwners.pose.clear();
    }
    const expired = tracks.filter((track) => sample.time - track.lastObservedTime > MAX_DROPOUT_SEC + EPSILON11);
    telemetry.deaths += expired.length;
    tracks = tracks.filter((track) => sample.time - track.lastObservedTime <= MAX_DROPOUT_SEC + EPSILON11);
    for (const track of tracks) track.identityAmbiguous = false;
    const people = observedPersonEvidence(sample);
    const primary = people.filter((item) => !item.predicted);
    const personAssignments = assignGlobally(primary, tracks, "person", sample.time);
    const assignedPeople = /* @__PURE__ */ new Map();
    for (const [index, assignment] of personAssignments) assignedPeople.set(primary[index].value, assignment);
    for (const item of primary) {
      if (assignedPeople.has(item.value)) continue;
      const point = center(item.box);
      const track = {
        canonicalId: nextId++,
        personBox: item.box,
        sources: ["person"],
        confidence: item.confidence,
        associationConfidence: 1,
        velocity: { x: 0, y: 0 },
        lastObservedTime: sample.time,
        state: "observed",
        identityAmbiguous: false,
        personSourceId: item.sourceId,
        previousCenter: { ...point, time: sample.time }
      };
      tracks.push(track);
      assignedPeople.set(item.value, { track, confidence: 1, ambiguous: false });
      telemetry.births++;
    }
    const faces = (sample.autoflipFaces ?? []).map((value) => ({
      value,
      box: value.box,
      sourceId: value.trackId,
      predicted: Boolean(value.predicted),
      confidence: 1
    }));
    const poses = (sample.poseSubjects ?? []).map((value) => ({
      value,
      box: value.box,
      sourceId: value.trackId,
      predicted: Boolean(value.predicted),
      confidence: value.score
    }));
    const faceAssignments = assignGlobally(faces, tracks, "face", sample.time);
    for (const [index, item] of faces.entries()) {
      if (item.predicted || faceAssignments.has(index)) continue;
      const point = center(item.box);
      const track = {
        canonicalId: nextId++,
        faceBox: item.box,
        sources: ["face"],
        confidence: item.confidence,
        associationConfidence: 1,
        velocity: { x: 0, y: 0 },
        lastObservedTime: sample.time,
        state: "observed",
        identityAmbiguous: false,
        faceSourceId: item.sourceId,
        previousCenter: { ...point, time: sample.time }
      };
      tracks.push(track);
      faceAssignments.set(index, { track, confidence: 1, ambiguous: false });
      telemetry.births++;
    }
    const poseAssignments = assignGlobally(poses, tracks, "pose", sample.time);
    for (const [index, item] of poses.entries()) {
      if (item.predicted || poseAssignments.has(index)) continue;
      const point = center(item.box);
      const track = {
        canonicalId: nextId++,
        poseBox: item.box,
        sources: ["pose"],
        confidence: item.confidence,
        associationConfidence: 1,
        velocity: { x: 0, y: 0 },
        lastObservedTime: sample.time,
        state: "observed",
        identityAmbiguous: false,
        poseSourceId: item.sourceId,
        previousCenter: { ...point, time: sample.time }
      };
      tracks.push(track);
      poseAssignments.set(index, { track, confidence: 1, ambiguous: false });
      telemetry.births++;
    }
    const secondaryPeople = people.filter((item) => item.predicted);
    const secondaryAssignments = assignGlobally(secondaryPeople, tracks, "person", sample.time);
    for (const [index, assignment] of secondaryAssignments) assignedPeople.set(secondaryPeople[index].value, assignment);
    const touch = (track, box, confidence, observed) => {
      if (!observed) return;
      const point = center(box);
      if (track.dropoutStartedAt != null) {
        telemetry.dropoutDurationsSec.push(sample.time - track.dropoutStartedAt);
        telemetry.successfulReacquisitions++;
        track.dropoutStartedAt = void 0;
      }
      if (track.previousCenter && sample.time > track.previousCenter.time + EPSILON11) {
        const dt = sample.time - track.previousCenter.time;
        track.velocity = { x: (point.x - track.previousCenter.x) / dt, y: (point.y - track.previousCenter.y) / dt };
      }
      track.previousCenter = { ...point, time: sample.time };
      track.lastObservedTime = sample.time;
      track.confidence = Math.max(track.confidence * 0.7, confidence);
    };
    const mappedDetections = sample.detections.map((detection) => {
      const assignment = assignedPeople.get(detection);
      if (!assignment) return detection;
      const item = people.find((candidate) => candidate.value === detection);
      const { track } = assignment;
      const observed = !item.predicted;
      if (observed) track.personBox = detection.box;
      if (item.sourceId != null) track.personSourceId = item.sourceId;
      recordSourceOwner("person", item.sourceId, track.canonicalId);
      track.state = item.predicted ? "predicted" : "observed";
      track.sources = [.../* @__PURE__ */ new Set([...track.sources, "person"])];
      track.associationConfidence = assignment.confidence;
      track.identityAmbiguous ||= assignment.ambiguous;
      touch(track, detection.box, detection.score, observed);
      telemetry.associationConfidences.push(assignment.confidence);
      return {
        ...detection,
        trackId: track.canonicalId,
        canonicalId: track.canonicalId,
        associationConfidence: assignment.confidence,
        identityAmbiguous: assignment.ambiguous
      };
    });
    const mappedFaces = faces.map((item, index) => {
      const assignment = faceAssignments.get(index);
      if (!assignment) return item.value;
      const { track } = assignment;
      if (!item.predicted) track.faceBox = item.box;
      if (item.sourceId != null) track.faceSourceId = item.sourceId;
      recordSourceOwner("face", item.sourceId, track.canonicalId);
      track.sources = [.../* @__PURE__ */ new Set([...track.sources, "face"])];
      track.associationConfidence = Math.min(track.associationConfidence, assignment.confidence);
      track.identityAmbiguous ||= assignment.ambiguous;
      touch(track, item.box, item.confidence, !item.predicted);
      telemetry.associationConfidences.push(assignment.confidence);
      return { ...item.value, trackId: track.canonicalId, canonicalId: track.canonicalId, associationConfidence: assignment.confidence, identityAmbiguous: assignment.ambiguous };
    });
    const mappedPoses = poses.map((item, index) => {
      const assignment = poseAssignments.get(index);
      if (!assignment) return item.value;
      const { track } = assignment;
      if (!item.predicted) track.poseBox = item.box;
      if (item.sourceId != null) track.poseSourceId = item.sourceId;
      recordSourceOwner("pose", item.sourceId, track.canonicalId);
      track.sources = [.../* @__PURE__ */ new Set([...track.sources, "pose"])];
      track.associationConfidence = Math.min(track.associationConfidence, assignment.confidence);
      track.identityAmbiguous ||= assignment.ambiguous;
      touch(track, item.box, item.confidence, !item.predicted);
      telemetry.associationConfidences.push(assignment.confidence);
      return { ...item.value, trackId: track.canonicalId, canonicalId: track.canonicalId, associationConfidence: assignment.confidence, identityAmbiguous: assignment.ambiguous };
    });
    for (const track of tracks) {
      if (sample.time > track.lastObservedTime + EPSILON11) track.dropoutStartedAt ??= track.lastObservedTime;
    }
    if (tracks.some((track) => track.identityAmbiguous)) telemetry.ambiguousSamples++;
    return {
      ...sample,
      detections: mappedDetections,
      autoflipFaces: mappedFaces,
      poseSubjects: mappedPoses,
      activeSpeakerScores: sample.activeSpeakerScores?.flatMap((score) => {
        const mapped = mappedFaces.find((face, index) => faces[index]?.sourceId === score.trackId && face.canonicalId != null);
        return mapped?.canonicalId != null ? [{ ...score, trackId: mapped.canonicalId }] : [];
      }),
      canonicalPersons: tracks.map((track) => snapshot(track, sample.time))
    };
  });
  telemetry.deaths += tracks.length;
  return { samples: output, telemetry };
}

// src/features/clipper/engine/autoflip/identity/project-composition-memory.util.ts
var MAX_ENTITIES_PER_KIND = 12;
var MAX_ACTIVE_ENTITIES_PER_KIND = MAX_ENTITIES_PER_KIND * 2;
var MAX_DURATION_DELTA_SEC = 0.5;
function clamp013(value) {
  return Math.max(0, Math.min(1, value));
}
function median2(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}
function intersectionOverUnion(a, b) {
  if (!a || !b) return 0;
  const left = Math.max(a.x, b.x);
  const top = Math.max(a.y, b.y);
  const right = Math.min(a.x + a.width, b.x + b.width);
  const bottom = Math.min(a.y + a.height, b.y + b.height);
  const intersection = Math.max(0, right - left) * Math.max(0, bottom - top);
  const union2 = a.width * a.height + b.width * b.height - intersection;
  return union2 > Number.EPSILON ? intersection / union2 : 0;
}
function entityKey(kind, scene, localId, label) {
  return `${kind}:${scene}:${label ?? "unknown"}:${localId ?? "untracked"}`;
}
function findEntity(states, kind, label, box, time) {
  const candidates = states.filter((state) => state.kind === kind && (kind === "person" || state.label === label));
  return candidates.filter((state) => time - state.lastSeen <= MAX_DURATION_DELTA_SEC).map((state) => ({ state, overlap: intersectionOverUnion(state.lastBox, box) })).filter(({ overlap }) => overlap >= 0.25).sort((a, b) => b.overlap - a.overlap)[0]?.state;
}
function appendHeight(state, height) {
  state.heights.push(clamp013(height));
  if (state.heights.length > 32) state.heights.shift();
}
function updateEntity(state, time, scene, box, confidence, speaker) {
  const elapsed = Math.max(0, Math.min(MAX_DURATION_DELTA_SEC, time - state.lastSeen));
  state.observedSeconds += elapsed;
  if (speaker) state.speakerSeconds += elapsed;
  if (elapsed > 0 && intersectionOverUnion(state.lastBox, box) >= 0.25) state.continuityHits++;
  state.lastSeen = time;
  state.lastBox = box;
  state.sceneIds.add(scene);
  state.saliencyTotal += clamp013(confidence);
  state.observationCount++;
  appendHeight(state, box.height);
}
function makeEntity(id, kind, label, time, scene, box, confidence, speaker) {
  const state = {
    id,
    kind,
    label,
    observedSeconds: 0,
    speakerSeconds: 0,
    sceneIds: /* @__PURE__ */ new Set([scene]),
    heights: [],
    saliencyTotal: 0,
    observationCount: 0,
    continuityHits: 0,
    lastSeen: time,
    lastBox: box
  };
  updateEntity(state, time, scene, box, confidence, speaker);
  return state;
}
function scoreEntities(states) {
  const grouped = /* @__PURE__ */ new Map();
  for (const state of states) grouped.set(state.kind, [...grouped.get(state.kind) ?? [], state]);
  return [...grouped.values()].flatMap((items) => {
    const maxObserved = Math.max(1, ...items.map((state) => state.observedSeconds));
    const maxSpeaker = Math.max(1, ...items.map((state) => state.speakerSeconds));
    return items.map((state) => {
      const observed = state.observedSeconds / maxObserved;
      const speaker = state.speakerSeconds / maxSpeaker;
      const medianHeight = median2(state.heights);
      const continuity = state.observationCount > 1 ? state.continuityHits / (state.observationCount - 1) : 0;
      const saliency = state.observationCount ? state.saliencyTotal / state.observationCount : 0;
      const semanticPrior = state.kind === "object" && ["car", "truck", "cat", "dog", "bird", "horse"].includes(state.label ?? "") ? 1 : 0.45;
      const importanceScore = state.kind === "person" ? clamp013(observed * 0.35 + speaker * 0.3 + medianHeight * 0.2 + continuity * 0.1 + saliency * 0.05) : clamp013(observed * 0.3 + medianHeight * 0.25 + saliency * 0.2 + continuity * 0.15 + semanticPrior * 0.1);
      return {
        id: state.id,
        kind: state.kind,
        label: state.label,
        importanceScore,
        observedSeconds: state.observedSeconds,
        speakerSeconds: state.speakerSeconds,
        sceneCount: state.sceneIds.size,
        medianHeight,
        continuity,
        saliency
      };
    }).sort((a, b) => b.importanceScore - a.importanceScore).slice(0, MAX_ENTITIES_PER_KIND);
  });
}
function retentionScore(state) {
  const averageSaliency = state.observationCount ? state.saliencyTotal / state.observationCount : 0;
  return state.observedSeconds + state.speakerSeconds * 1.5 + averageSaliency * 0.5 + state.continuityHits * 0.05;
}
function trimWorkingSet(states, localOwners) {
  for (const kind of ["person", "object"]) {
    const candidates = states.filter((state) => state.kind === kind).sort((left, right) => retentionScore(right) - retentionScore(left));
    while (candidates.length > MAX_ACTIVE_ENTITIES_PER_KIND) {
      const discarded = candidates.shift();
      if (!discarded) break;
      const index = states.indexOf(discarded);
      if (index >= 0) states.splice(index, 1);
      for (const [key, ownerId] of localOwners) {
        if (ownerId === discarded.id) localOwners.delete(key);
      }
    }
  }
}
function buildProjectCompositionMemory(samples) {
  const states = [];
  const localOwners = /* @__PURE__ */ new Map();
  let nextId = 1;
  let scene = 0;
  let previousTime = Number.NEGATIVE_INFINITY;
  const output = [...samples].sort((a, b) => a.time - b.time).map((sample) => {
    if (sample.sceneCut) {
      scene++;
      localOwners.clear();
    }
    const speakerTrackIds = new Set(
      (sample.importanceSignals ?? []).filter((signal) => signal.kind === "active-speaker" && signal.confidence >= 0.7).flatMap((signal) => signal.trackId == null ? [] : [signal.trackId])
    );
    const personOwners = /* @__PURE__ */ new Map();
    const resolve = (kind, label, localId, box, confidence, speaker = false) => {
      const localKey = entityKey(kind, scene, localId, label);
      const owned = localOwners.get(localKey);
      const existing = owned ? states.find((state) => state.id === owned) : void 0;
      const entity = existing ?? findEntity(states, kind, label, box, sample.time) ?? makeEntity(`project-${kind}-${nextId++}`, kind, label, sample.time, scene, box, confidence, speaker);
      if (!states.includes(entity)) states.push(entity);
      localOwners.set(localKey, entity.id);
      if (entity.lastSeen !== sample.time || entity.observationCount === 0) {
        updateEntity(entity, sample.time, scene, box, confidence, speaker);
      } else if (speaker) {
        entity.speakerSeconds += Math.max(0, Math.min(MAX_DURATION_DELTA_SEC, sample.time - previousTime));
      }
      return entity.id;
    };
    const detections = sample.detections.map((detection) => {
      if (detection.predicted) return detection;
      const kind = detection.label.toLowerCase() === "person" ? "person" : "object";
      const identity = resolve(kind, kind === "object" ? detection.label.toLowerCase() : void 0, detection.canonicalId ?? detection.trackId, detection.box, detection.score, speakerTrackIds.has(detection.canonicalId ?? detection.trackId ?? -1));
      if (kind === "person" && detection.canonicalId != null) personOwners.set(detection.canonicalId, identity);
      return { ...detection, projectIdentityId: identity };
    });
    const faces = sample.autoflipFaces?.map((face) => ({
      ...face,
      projectIdentityId: face.canonicalId != null ? personOwners.get(face.canonicalId) : void 0
    }));
    const poses = sample.poseSubjects?.map((pose) => ({
      ...pose,
      projectIdentityId: pose.canonicalId != null ? personOwners.get(pose.canonicalId) : void 0
    }));
    trimWorkingSet(states, localOwners);
    previousTime = sample.time;
    return { ...sample, detections, autoflipFaces: faces, poseSubjects: poses };
  });
  const entities = scoreEntities(states);
  const rankedEntityIds = [...entities].sort((left, right) => right.importanceScore - left.importanceScore || right.observedSeconds - left.observedSeconds || right.continuity - left.continuity).map((entity) => entity.id);
  return {
    samples: output,
    summary: { version: 2, entities, rankedEntityIds, maxEntitiesPerKind: MAX_ENTITIES_PER_KIND }
  };
}
function compositionScoreByIdentity(summary) {
  return new Map(summary.entities.map((entity) => [entity.id, entity.importanceScore]));
}

// src/features/clipper/engine/autoflip/face-cache-evidence.util.ts
var MAX_FACE_CACHE_DELTA_SEC = 0.25;
var DUPLICATE_FACE_OVERLAP = 0.5;
var EPSILON12 = 1e-9;
function clamp014(value) {
  return Math.max(0, Math.min(1, value));
}
function normalizeFace(face, sample) {
  if (sample.frameW <= 0 || sample.frameH <= 0 || face.width <= 0 || face.height <= 0) return null;
  const x = clamp014(face.x / sample.frameW);
  const y = clamp014(face.y / sample.frameH);
  const right = clamp014((face.x + face.width) / sample.frameW);
  const bottom = clamp014((face.y + face.height) / sample.frameH);
  if (right <= x || bottom <= y) return null;
  return { box: { x, y, width: right - x, height: bottom - y }, keypoints: [] };
}
function overlapFractionOfSmaller2(a, b) {
  const overlapWidth = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
  const overlapHeight = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
  const smallerArea = Math.min(a.width * a.height, b.width * b.height);
  return smallerArea > 0 ? overlapWidth * overlapHeight / smallerArea : 0;
}
function boxCenter2(box) {
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}
function unionBoxes2(a, b) {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const right = Math.max(a.x + a.width, b.x + b.width);
  const bottom = Math.max(a.y + a.height, b.y + b.height);
  return { x, y, width: right - x, height: bottom - y };
}
function matchingNativeFaceIndex(nativeFaces, cached) {
  const cachedCenter = boxCenter2(cached.box);
  return nativeFaces.map((native, index) => {
    const nativeCenter = boxCenter2(native.box);
    const dx = Math.abs(nativeCenter.x - cachedCenter.x);
    const dy = Math.abs(nativeCenter.y - cachedCenter.y);
    const overlaps = overlapFractionOfSmaller2(cached.box, native.box) >= DUPLICATE_FACE_OVERLAP;
    const centerCompatible = dx <= Math.max(0.025, cached.box.width * 0.4) && dy <= Math.max(0.025, cached.box.height * 0.4);
    return { index, distance: Math.hypot(dx, dy), compatible: overlaps && centerCompatible };
  }).filter((candidate) => candidate.compatible).sort((left, right) => left.distance - right.distance)[0]?.index ?? -1;
}
function crossesSceneCut(from, to, sceneCuts) {
  const start = Math.min(from, to);
  const end = Math.max(from, to);
  return sceneCuts.some((cut) => cut > start + EPSILON12 && cut <= end + EPSILON12);
}
function nearestFaceSample(faceSamples, time, sceneCuts) {
  let closest = null;
  let closestDelta = MAX_FACE_CACHE_DELTA_SEC + EPSILON12;
  for (const sample of faceSamples) {
    const delta = Math.abs(sample.time - time);
    if (delta > closestDelta || crossesSceneCut(sample.time, time, sceneCuts)) continue;
    if (delta < closestDelta) {
      closest = sample;
      closestDelta = delta;
    }
  }
  return closest;
}
function attachFaceCacheEvidence(detections, faceSamples, sceneCuts) {
  if (!detections.length || !faceSamples.length) return [...detections];
  const sortedFaces = [...faceSamples].sort((left, right) => left.time - right.time);
  return detections.map((sample) => {
    const cached = nearestFaceSample(sortedFaces, sample.time, sceneCuts);
    if (!cached?.faces.length) return sample;
    const nativeFaces = (sample.autoflipFaces ?? []).map((face) => ({ ...face, box: { ...face.box } }));
    const cachedFaces = cached.faces.map((face) => normalizeFace(face, cached)).filter((face) => face != null);
    if (!cachedFaces.length) return sample;
    const merged = [...nativeFaces];
    for (const cachedFace of cachedFaces) {
      const nativeIndex = matchingNativeFaceIndex(merged, cachedFace);
      if (nativeIndex < 0) {
        merged.push(cachedFace);
        continue;
      }
      const native = merged[nativeIndex];
      merged[nativeIndex] = { ...native, box: unionBoxes2(native.box, cachedFace.box) };
    }
    return { ...sample, autoflipFaces: merged };
  });
}

// src/features/clipper/engine/autoflip/content-rect.util.ts
var FULL_FRAME = { x: 0, y: 0, width: 1, height: 1 };
function validContentRect(rect) {
  if (!rect || rect.width <= 0 || rect.height <= 0) return FULL_FRAME;
  const x = Math.max(0, Math.min(1, rect.x));
  const y = Math.max(0, Math.min(1, rect.y));
  const width = Math.max(0, Math.min(1 - x, rect.width));
  const height = Math.max(0, Math.min(1 - y, rect.height));
  return width > 0 && height > 0 ? { x, y, width, height } : FULL_FRAME;
}
function intoContentRect(box, content) {
  const left = Math.max(content.x, box.x);
  const top = Math.max(content.y, box.y);
  const right = Math.min(content.x + content.width, box.x + box.width);
  const bottom = Math.min(content.y + content.height, box.y + box.height);
  if (right <= left || bottom <= top) return null;
  return {
    x: (left - content.x) / content.width,
    y: (top - content.y) / content.height,
    width: (right - left) / content.width,
    height: (bottom - top) / content.height
  };
}
function intoSourceRect(rect, content) {
  return {
    x: content.x + rect.x * content.width,
    y: content.y + rect.y * content.height,
    width: rect.width * content.width,
    height: rect.height * content.height
  };
}

// src/features/clipper/engine/autoflip/build-track.util.ts
function detectionsInContent(detections, content) {
  if (content === FULL_FRAME) return detections;
  return detections.map((sample) => ({
    ...sample,
    detections: sample.detections.flatMap((detection) => {
      const box = intoContentRect(detection.box, content);
      return box ? [{ ...detection, box }] : [];
    }),
    autoflipFaces: sample.autoflipFaces?.flatMap((face) => {
      const box = intoContentRect(face.box, content);
      if (!box) return [];
      return [{
        ...face,
        box,
        keypoints: face.keypoints.flatMap(
          (point) => point.x >= content.x && point.x <= content.x + content.width && point.y >= content.y && point.y <= content.y + content.height ? [{ x: (point.x - content.x) / content.width, y: (point.y - content.y) / content.height }] : []
        )
      }];
    }),
    poseSubjects: sample.poseSubjects?.flatMap((pose) => {
      const box = intoContentRect(pose.box, content);
      if (!box) return [];
      return [{
        ...pose,
        box,
        headBox: pose.headBox ? intoContentRect(pose.headBox, content) ?? void 0 : void 0,
        torsoBox: pose.torsoBox ? intoContentRect(pose.torsoBox, content) ?? void 0 : void 0
      }];
    }),
    importanceSignals: sample.importanceSignals?.flatMap((region) => {
      const box = intoContentRect(region.box, content);
      return box ? [{ ...region, box }] : [];
    })
  }));
}
function importanceSignalsInContent(samples, content) {
  if (!samples || content === FULL_FRAME) return samples;
  return samples.map((sample) => ({
    ...sample,
    regions: sample.regions.flatMap((region) => {
      const box = intoContentRect(region.box, content);
      return box ? [{ ...region, box }] : [];
    })
  }));
}
function splitScenes(clipStart, clipEnd, sceneCuts, sourceFrameRate) {
  const boundaries = [.../* @__PURE__ */ new Set([clipStart, ...sceneCuts, clipEnd])].filter((time) => time >= clipStart && time <= clipEnd).sort((a, b) => a - b);
  const scenes = [];
  for (let index = 1; index < boundaries.length; index++) {
    scenes.push({
      start: boundaries[index - 1],
      end: boundaries[index],
      cut: index > 1,
      continueLastScene: false
    });
  }
  if (scenes.length === 0) scenes.push({ start: clipStart, end: clipEnd, cut: false, continueLastScene: false });
  const chunked = [];
  for (const scene of scenes) {
    const maxSceneSec = AUTOFLIP_MAX_SCENE_FRAMES / sourceFrameRate;
    if (scene.end - scene.start <= maxSceneSec) {
      chunked.push(scene);
      continue;
    }
    for (let start = scene.start; start < scene.end - 1e-9; start += maxSceneSec) {
      chunked.push({
        start,
        end: Math.min(scene.end, start + maxSceneSec),
        cut: start === scene.start && scene.cut,
        continueLastScene: start > scene.start
      });
    }
  }
  return chunked;
}
function samplesWithVerifiedPeopleOnly(samples) {
  return samples.map((sample) => {
    const verifiedCanonicalIds = new Set((sample.canonicalPersons ?? []).filter((person) => !person.identityAmbiguous && (person.sources.includes("face") || person.sources.includes("pose"))).map((person) => person.canonicalId));
    return {
      ...sample,
      detections: sample.detections.filter((detection) => detection.label.toLowerCase() !== "person" || detection.detectorSource === "pose" || detection.canonicalId != null && verifiedCanonicalIds.has(detection.canonicalId))
    };
  });
}
function buildAutoFlipTrack(input2) {
  const sourceFrameWidth = input2.frameWidth ?? 1920;
  const sourceFrameHeight = input2.frameHeight ?? 1080;
  const contentRect = validContentRect(input2.contentRect);
  const frameWidth = sourceFrameWidth * contentRect.width;
  const frameHeight = sourceFrameHeight * contentRect.height;
  const sourceFrameRate = Number.isFinite(input2.sourceFrameRate) && input2.sourceFrameRate > 0 ? input2.sourceFrameRate : 30;
  const kinematicOptions = kinematicOptionsForSmooth();
  const scenes = splitScenes(input2.clipStart, input2.clipEnd, input2.sceneCuts, sourceFrameRate);
  const detectionsWithCachedFaces = attachFaceCacheEvidence(input2.detections, input2.faces, input2.sceneCuts);
  const canonicalFusion = buildCanonicalPersonTracks(detectionsWithCachedFaces);
  const activeSpeaker = applyActiveSpeakerPolicy(canonicalFusion.samples);
  const compositionInputs = input2.enhancedIdentityFusion ? samplesWithVerifiedPeopleOnly(activeSpeaker.samples) : activeSpeaker.samples;
  const compositionMemory = buildProjectCompositionMemory(compositionInputs);
  const contentDetections = detectionsInContent(
    input2.enhancedIdentityFusion ? activeSpeaker.samples : detectionsWithCachedFaces,
    contentRect
  );
  const rawKeyframes = buildSalientKeyframes({
    clipStart: input2.clipStart,
    clipEnd: input2.clipEnd,
    detections: contentDetections,
    sceneCuts: input2.sceneCuts
  });
  const compositionScores = input2.enhancedIdentityFusion ? compositionScoreByIdentity(compositionMemory.summary) : void 0;
  const compositionAwareKeyframes = compositionScores ? rawKeyframes.map((keyframe) => ({
    ...keyframe,
    regions: keyframe.regions.map((region) => {
      const globalScore = region.projectIdentityId == null ? void 0 : compositionScores.get(region.projectIdentityId);
      return globalScore == null ? region : { ...region, score: Math.min(1, region.score * 0.58 + globalScore * 0.42) };
    })
  })) : rawKeyframes;
  const semanticKeyframes = attachImportanceSignals(
    compositionAwareKeyframes,
    input2.importanceSignals ? importanceSignalsInContent(input2.importanceSignals, contentRect) : contentDetections.flatMap((sample) => sample.importanceSignals?.length ? [{ time: sample.time, regions: sample.importanceSignals }] : [])
  );
  const importanceSamples = buildImportanceTimeline(
    semanticKeyframes,
    compositionScores
  ).map((sample) => ({
    ...sample,
    regions: sample.regions.map((region) => ({
      ...region,
      box: intoSourceRect(region.box, contentRect),
      contentBox: intoSourceRect(region.contentBox, contentRect)
    }))
  }));
  const targets = Object.keys(input2.targetAspectRatios ?? {}).length ? input2.targetAspectRatios : { default: input2.targetAspectRatio ?? 9 / 16 };
  const aspectTracks = {};
  const debugScenes = input2.collectDebug ? [] : void 0;
  for (const [formatId, targetAspectRatio] of Object.entries(targets)) {
    const samples = [];
    let continuationFocus = [];
    for (const scene of scenes) {
      const sceneKeyframes = compositionAwareKeyframes.filter(
        (keyframe) => keyframe.time >= scene.start - 1e-9 && (keyframe.time < scene.end - 1e-9 || scene.end >= input2.clipEnd - 1e-9)
      );
      if (sceneKeyframes.length === 0) continue;
      const timeline = buildSceneTimeline(scene.start, scene.end, Math.min(AUTOFLIP_TRACK_FPS, sourceFrameRate), scene.end >= input2.clipEnd - 1e-9);
      const motion = analyzeSceneMotion({
        keyframes: sceneKeyframes,
        frameWidth,
        frameHeight,
        targetAspectRatio,
        hasSolidColorBackground: false,
        sceneTimestampsUs: timeline.timestampsUs
      });
      const cropRects = cropScenePath({
        summary: motion.summary,
        focusPointFrames: motion.focusPointFrames,
        priorFocusPointFrames: scene.continueLastScene ? continuationFocus : [],
        sceneTimestampsUs: timeline.timestampsUs,
        isKeyFrames: timeline.isKeyFrames,
        kinematicOptions,
        continueLastScene: scene.continueLastScene,
        pathSolver: motion.summary.motionType === "tracking" ? "kinematic" : "polynomial"
      });
      cropRects.forEach((crop, index) => {
        samples.push({ t: timeline.timestampsUs[index] / 1e6, crop: intoSourceRect(crop, contentRect), cut: index === 0 && scene.cut });
      });
      continuationFocus = motion.focusPointFrames.slice(-30);
      debugScenes?.push({
        formatId,
        start: scene.start,
        end: scene.end,
        motionType: motion.summary.motionType,
        lookAtCenterX: motion.summary.lookAtCenterX,
        lookAtCenterY: motion.summary.lookAtCenterY,
        cropWindowWidthNorm: motion.summary.cropWindowWidth / frameWidth,
        cropWindowHeightNorm: motion.summary.cropWindowHeight / frameHeight,
        successRate: motion.summary.frameSuccessRate,
        keyframes: sceneKeyframes.map((keyframe) => ({
          time: keyframe.time,
          regions: keyframe.regions.map((region) => ({ box: region.box, score: region.score, signalType: region.signalType })),
          chosenRect: motion.keyframeCrops.find((crop) => Math.abs(crop.time - keyframe.time) < 1e-9)?.rect
        }))
      });
    }
    if (samples.length === 0) {
      const sourceAspect = frameWidth / frameHeight;
      const width = sourceAspect >= targetAspectRatio ? targetAspectRatio / sourceAspect : 1;
      const height = sourceAspect >= targetAspectRatio ? 1 : sourceAspect / targetAspectRatio;
      for (let time = input2.clipStart; time <= input2.clipEnd + 1e-9; time += 1 / Math.min(AUTOFLIP_TRACK_FPS, sourceFrameRate)) {
        samples.push({ t: time, crop: intoSourceRect({ x: (1 - width) / 2, y: (1 - height) / 2, width, height }, contentRect) });
      }
    }
    const smoothedSamples = smoothShotCropSamples(samples, input2.sceneCuts);
    aspectTracks[formatId] = {
      targetAspectRatio,
      samples: smoothedSamples.map((sample) => ({
        ...sample,
        crop: sample.crop
      }))
    };
  }
  const primaryTrack = aspectTracks[Object.keys(aspectTracks)[0]];
  const layoutTracks = buildLayoutTracks({
    aspectTracks,
    importanceSamples,
    frameWidth: sourceFrameWidth,
    frameHeight: sourceFrameHeight,
    arbiterParams: {
      ...input2.enhancedIdentityFusion ? DEFAULT_ARBITER_PARAMS : LEGACY_ARBITER_PARAMS,
      allowGroupUnion: true
    },
    visibilityControllerParams: input2.enhancedIdentityFusion ? { ...DEFAULT_VISIBILITY_PARAMS } : void 0
  });
  return {
    analyzerVersion: AUTOFLIP_ANALYZER_VERSION,
    modelId: AUTOFLIP_MODEL_ID,
    trackerVersion: input2.trackerVersion,
    clipStart: input2.clipStart,
    clipEnd: input2.clipEnd,
    cameraSmoothing: "smooth",
    targetAspectRatio: primaryTrack.targetAspectRatio,
    contentRect,
    solidBackgroundColor: void 0,
    degradedReason: input2.degradedReason,
    aspectTracks,
    importanceSamples,
    layoutTracks,
    canonicalIdentityTelemetry: canonicalFusion.telemetry,
    activeSpeakerTelemetry: activeSpeaker.telemetry,
    compositionMemory: input2.enhancedIdentityFusion ? compositionMemory.summary : void 0,
    debug: debugScenes
  };
}

// entry.ts
import { readFileSync, writeFileSync } from "node:fs";
var [inp, out] = process.argv.slice(2);
var input = JSON.parse(readFileSync(inp, "utf8"));
var blob = buildAutoFlipTrack({ faces: [], ...input });
writeFileSync(out, JSON.stringify({
  analyzerVersion: AUTOFLIP_ANALYZER_VERSION,
  degradedReason: blob.degradedReason ?? null,
  aspectTracks: blob.aspectTracks
}));
