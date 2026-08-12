-- Physical-delivery metrics for camera-enabled Public Speaking sessions.
--
-- Holds the aggregate plus a downsampled per-second timeline only. No video, no frames, and no
-- per-frame landmarks: MediaPipe runs in the browser and the backend never receives raw media,
-- mirroring how "audioFeatures" stores derived signal rather than audio.
--
-- Nullable with no default: a NULL column means the camera was off, which is distinct from a
-- session that ran with the camera on but produced unmeasurable data (that case stores a blob
-- with status = 'insufficient_data').

-- AlterTable
ALTER TABLE "public_speaking_sessions" ADD COLUMN     "videoFeatures" JSONB;
