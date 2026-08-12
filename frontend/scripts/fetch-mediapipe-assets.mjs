/**
 * Populates public/mediapipe/ with the MediaPipe Tasks Vision runtime assets.
 *
 * Runs as a postinstall hook. public/mediapipe/ is gitignored — 30MB of binaries would
 * bloat every clone forever — so this script is what makes a fresh `npm ci` produce a
 * working build.
 *
 * Two jobs:
 *   1. COPY the wasm from node_modules rather than downloading it. MediaPipe's JS<->wasm
 *      ABI is version-locked and a mismatch aborts with a cryptic error, so sourcing both
 *      halves from the same installed package makes them provably the same version.
 *   2. DOWNLOAD the .task model bundles, which npm does not ship, verifying each against a
 *      pinned sha256.
 *
 * Deliberately non-fatal: air-gapped CI must still be able to build. startVideo() already
 * has to degrade gracefully when an asset 404s, so a failure here is a degraded runtime,
 * not a broken build.
 */

import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { copyFile, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PACKAGE_WASM_DIR = path.join(FRONTEND_DIR, "node_modules", "@mediapipe", "tasks-vision", "wasm");
const PUBLIC_DIR = path.join(FRONTEND_DIR, "public", "mediapipe");
const WASM_DIR = path.join(PUBLIC_DIR, "wasm");
const MODELS_DIR = path.join(PUBLIC_DIR, "models");

/**
 * Both single-threaded builds: SIMD, and the no-SIMD fallback.
 *
 * FilesetResolver probes the browser and requests exactly one of these pairs, so serving both
 * costs ~11MB of disk on the server and zero bandwidth for any individual visitor. Shipping only
 * the SIMD pair meant a browser without wasm SIMD was refused outright with "unsupported_browser"
 * — a hard "this feature does not exist for you" traded against a directory listing.
 *
 * Skipped on purpose:
 *   vision_wasm_module_internal.*  needs SharedArrayBuffer, which needs COOP/COEP headers we
 *                                  deliberately do not set (see next.config.mjs).
 */
const WASM_FILES = [
  "vision_wasm_internal.js",
  "vision_wasm_internal.wasm",
  "vision_wasm_nosimd_internal.js",
  "vision_wasm_nosimd_internal.wasm",
];

/**
 * Pinned by sha256, not just by URL: these are longitudinal inputs. Blendshape and landmark
 * behaviour shifts between model revisions, so a session scored in August must be traceable to
 * the exact weights that produced it. `version` is surfaced through
 * video_features.quality.model_versions.
 */
const MODELS = [
  {
    key: "face",
    file: "face_landmarker.task",
    version: "face_landmarker/float16/1",
    url: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    sha256: "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
    bytes: 3758596,
  },
  {
    key: "pose",
    file: "pose_landmarker_lite.task",
    version: "pose_landmarker_lite/float16/1",
    url: "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
    sha256: "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
    bytes: 5777746,
  },
  {
    key: "hand",
    file: "hand_landmarker.task",
    version: "hand_landmarker/float16/1",
    url: "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
    sha256: "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1",
    bytes: 7819105,
  },
];

const log = (msg) => console.log(`[mediapipe-assets] ${msg}`);

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

async function fileMatches(filePath, expectedSha) {
  if (!existsSync(filePath)) return false;
  try {
    return sha256(await readFile(filePath)) === expectedSha;
  } catch {
    return false;
  }
}

/** Copy the SIMD wasm pair out of the installed package, and drop variants we don't serve. */
async function syncWasm() {
  if (!existsSync(PACKAGE_WASM_DIR)) {
    log(`SKIP wasm — ${path.relative(FRONTEND_DIR, PACKAGE_WASM_DIR)} not found.`);
    log("       Run `npm install` so @mediapipe/tasks-vision is present, then re-run.");
    return;
  }

  await mkdir(WASM_DIR, { recursive: true });

  for (const name of WASM_FILES) {
    const src = path.join(PACKAGE_WASM_DIR, name);
    if (!existsSync(src)) {
      log(`SKIP ${name} — missing from the installed package.`);
      continue;
    }
    await copyFile(src, path.join(WASM_DIR, name));
    log(`copied ${name}`);
  }

  // Earlier hand-staging copied all six variants. Prune whatever we don't serve so the
  // directory doesn't quietly carry 22MB of dead weight.
  for (const name of await readdir(WASM_DIR)) {
    if (WASM_FILES.includes(name)) continue;
    await rm(path.join(WASM_DIR, name), { force: true });
    log(`pruned unused variant ${name}`);
  }
}

/** Download a model unless a byte-identical copy is already on disk. */
async function syncModel(model) {
  const dest = path.join(MODELS_DIR, model.file);

  if (await fileMatches(dest, model.sha256)) {
    log(`ok ${model.file} (hash matches, skipped)`);
    return true;
  }

  log(`fetching ${model.file} (${(model.bytes / 1e6).toFixed(1)}MB)...`);
  const response = await fetch(model.url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ${response.statusText}`);
  }

  const buffer = Buffer.from(await response.arrayBuffer());
  const actual = sha256(buffer);
  if (actual !== model.sha256) {
    // Refuse to write rather than half-install: a wrong model silently changes every score.
    throw new Error(`sha256 mismatch — expected ${model.sha256}, got ${actual}`);
  }

  await writeFile(dest, buffer);
  log(`ok ${model.file}`);
  return true;
}

async function main() {
  await mkdir(MODELS_DIR, { recursive: true });

  await syncWasm();

  const failed = [];
  for (const model of MODELS) {
    try {
      await syncModel(model);
    } catch (err) {
      failed.push(model.file);
      log(`FAILED ${model.file} — ${err.message}`);
    }
  }

  // Read at runtime for video_features.quality.model_versions.
  await writeFile(
    path.join(PUBLIC_DIR, "manifest.json"),
    `${JSON.stringify(
      Object.fromEntries(MODELS.map((m) => [m.key, { version: m.version, sha256: m.sha256 }])),
      null,
      2,
    )}\n`,
  );

  if (failed.length) {
    log(`${failed.length} model(s) unavailable: ${failed.join(", ")}`);
    log("Build continues; camera-based analysis will report unsupported until these are present.");
    log("Re-run with: npm run fetch:mediapipe");
  } else {
    log("all assets present.");
  }
}

// Never fail the install. A broken build is worse than a degraded camera feature.
main().catch((err) => {
  log(`unexpected error — ${err?.message ?? err}`);
  log("Build continues; camera-based analysis will be unavailable.");
});
