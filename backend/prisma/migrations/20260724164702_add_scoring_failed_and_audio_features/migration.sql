-- AlterTable
ALTER TABLE "baseline_assessments" ADD COLUMN     "scoringFailed" BOOLEAN NOT NULL DEFAULT false;

-- AlterTable
ALTER TABLE "public_speaking_sessions" ADD COLUMN     "audioFeatures" JSONB;
