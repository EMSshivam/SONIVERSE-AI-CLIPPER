// SONIVERSE headless wrapper around OpenClipper's AutoFlip planner (MIT, GrepCut).  Input/Output: JSON files.
import { buildAutoFlipTrack, AUTOFLIP_ANALYZER_VERSION } from "./src/features/clipper/engine/autoflip/index";
import { readFileSync, writeFileSync } from "node:fs";
const [inp, out] = process.argv.slice(2);
const input = JSON.parse(readFileSync(inp, "utf8"));
const blob = buildAutoFlipTrack({ faces: [], ...input });
writeFileSync(out, JSON.stringify({
  analyzerVersion: AUTOFLIP_ANALYZER_VERSION,
  degradedReason: blob.degradedReason ?? null,
  aspectTracks: blob.aspectTracks,
}));
