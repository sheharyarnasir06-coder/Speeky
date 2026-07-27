-- AlterTable
ALTER TABLE "baseline_assessments" ADD COLUMN     "outlierFlags" JSONB NOT NULL DEFAULT '[]';

-- AlterTable
ALTER TABLE "public_speaking_sessions" ADD COLUMN     "outlierFlags" JSONB NOT NULL DEFAULT '[]';
