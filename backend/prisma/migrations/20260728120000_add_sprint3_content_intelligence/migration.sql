-- Sprint 3 Content Intelligence: US-192, US-193, US-195, US-196, US-198.
-- Additive only: every new column is nullable or defaulted, so existing rows and
-- any deploy that is mid-rollout keep working unchanged.

-- ── CM-US-08 (US-192) Vocabulary Coverage Score ──────────────────────────────
ALTER TABLE "custom_scenarios" ADD COLUMN IF NOT EXISTS "vocabCoverageScore" INTEGER;
ALTER TABLE "custom_scenarios" ADD COLUMN IF NOT EXISTS "vocabCoverageFeedback" JSONB;
ALTER TABLE "custom_scenarios" ADD COLUMN IF NOT EXISTS "vocabCoverageAt" TIMESTAMP(3);

-- ── CM-US-11 (US-195) Prompt Explainability Report ───────────────────────────
ALTER TABLE "custom_scenarios" ADD COLUMN IF NOT EXISTS "explainabilityReport" JSONB;
ALTER TABLE "custom_scenarios" ADD COLUMN IF NOT EXISTS "explainabilityAt" TIMESTAMP(3);

-- ── CM-US-14 (US-198) Deployment Confidence ──────────────────────────────────
ALTER TABLE "custom_scenarios" ADD COLUMN IF NOT EXISTS "deploymentConfidence" INTEGER;
ALTER TABLE "custom_scenarios" ADD COLUMN IF NOT EXISTS "deploymentFeedback" JSONB;
ALTER TABLE "custom_scenarios" ADD COLUMN IF NOT EXISTS "deploymentScoredAt" TIMESTAMP(3);
ALTER TABLE "custom_scenarios" ADD COLUMN IF NOT EXISTS "sandboxRuns" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "custom_scenarios" ADD COLUMN IF NOT EXISTS "sandboxPasses" INTEGER NOT NULL DEFAULT 0;

-- ── CM-US-09 (US-193) learner satisfaction / CM-US-12 (US-196) user feedback ─
ALTER TABLE "scenario_sessions" ADD COLUMN IF NOT EXISTS "satisfactionRating" INTEGER;

-- ── CM-US-14 (US-198) deployment history ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS "template_deployments" (
    "id" TEXT NOT NULL,
    "scenarioId" TEXT NOT NULL,
    "version" INTEGER NOT NULL,
    "confidenceScore" INTEGER NOT NULL,
    "breakdown" JSONB NOT NULL,
    "outcome" TEXT NOT NULL DEFAULT 'DEPLOYED',
    "note" TEXT NOT NULL DEFAULT '',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "template_deployments_pkey" PRIMARY KEY ("id")
);
CREATE INDEX IF NOT EXISTS "template_deployments_scenarioId_createdAt_idx"
    ON "template_deployments"("scenarioId", "createdAt");

-- ── CM-US-09 (US-193) "Historical trends preserved" ──────────────────────────
CREATE TABLE IF NOT EXISTS "template_performance_snapshots" (
    "id" TEXT NOT NULL,
    "scenarioId" TEXT NOT NULL,
    "metrics" JSONB NOT NULL,
    "sampleSize" INTEGER NOT NULL,
    "capturedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "template_performance_snapshots_pkey" PRIMARY KEY ("id")
);
CREATE INDEX IF NOT EXISTS "template_performance_snapshots_scenarioId_capturedAt_idx"
    ON "template_performance_snapshots"("scenarioId", "capturedAt");

-- ── CM-US-12 (US-196) drift alerts ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS "content_drift_alerts" (
    "id" TEXT NOT NULL,
    "scenarioId" TEXT NOT NULL,
    "severity" TEXT NOT NULL,
    "summary" TEXT NOT NULL,
    "signals" JSONB NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'OPEN',
    "detectedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "acknowledgedAt" TIMESTAMP(3),
    CONSTRAINT "content_drift_alerts_pkey" PRIMARY KEY ("id")
);
CREATE INDEX IF NOT EXISTS "content_drift_alerts_scenarioId_status_idx"
    ON "content_drift_alerts"("scenarioId", "status");

-- Cascade from the parent scenario: archiving keeps the row, purging removes the
-- scenario entirely, and none of this analytics data should outlive it.
DO $$ BEGIN
    ALTER TABLE "template_deployments" ADD CONSTRAINT "template_deployments_scenarioId_fkey"
        FOREIGN KEY ("scenarioId") REFERENCES "custom_scenarios"("id") ON DELETE CASCADE ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE "template_performance_snapshots" ADD CONSTRAINT "template_performance_snapshots_scenarioId_fkey"
        FOREIGN KEY ("scenarioId") REFERENCES "custom_scenarios"("id") ON DELETE CASCADE ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE "content_drift_alerts" ADD CONSTRAINT "content_drift_alerts_scenarioId_fkey"
        FOREIGN KEY ("scenarioId") REFERENCES "custom_scenarios"("id") ON DELETE CASCADE ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
