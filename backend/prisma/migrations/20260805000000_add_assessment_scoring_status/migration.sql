-- Records whether a completed baseline carries a real grade.
-- "scored"      : graded normally.
-- "unavailable" : the relevance grader could not run, so confidenceScore is null and the
--                 UI must show "not yet graded" instead of a number. Paired with
--                 scoringFailed = true so the existing retry path re-grades it later.
-- Existing rows default to "scored": they were graded, just under the older scoring
-- logic. This column distinguishes ungraded from graded, not old from new.
-- AlterTable
-- Table is "baseline_assessments", not the model name — see @@map on BaselineAssessment.
ALTER TABLE "baseline_assessments" ADD COLUMN     "scoringStatus" TEXT NOT NULL DEFAULT 'scored';
