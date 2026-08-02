-- GAP-05 (US-203) Regional Segmentation + GAP-06 (US-204) Period-over-Period
-- Comparison. Additive only — hand-written instead of a raw `prisma migrate diff`
-- output for the same reason as the GAP-03/04 migration: this shared dev database
-- still carries tables/columns (content_drift_alerts, template_deployments,
-- template_performance_snapshots, extra custom_scenarios/scenario_sessions columns)
-- that are not in this branch's schema.prisma or migration history — unmerged work
-- from another branch applied directly to the same shared DB. A full diff-based
-- migration would DROP all of that; this migration only adds what GAP-05/GAP-06 need.

-- AlterTable
ALTER TABLE "users" ADD COLUMN "country" TEXT;

-- CreateTable
CREATE TABLE "regional_rollups" (
    "id" TEXT NOT NULL,
    "metricKey" TEXT NOT NULL,
    "regionCode" TEXT NOT NULL,
    "date" TIMESTAMP(3) NOT NULL,
    "value" DOUBLE PRECISION NOT NULL,
    "sampleSize" INTEGER NOT NULL,
    "isLowVolume" BOOLEAN NOT NULL DEFAULT false,
    "isSpoofingFlagged" BOOLEAN NOT NULL DEFAULT false,
    "spoofingNote" TEXT,
    "computedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "regional_rollups_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "currency_rates" (
    "currencyCode" TEXT NOT NULL,
    "rateToBase" DOUBLE PRECISION NOT NULL,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "currency_rates_pkey" PRIMARY KEY ("currencyCode")
);

-- CreateIndex
CREATE INDEX "regional_rollups_metricKey_date_idx" ON "regional_rollups"("metricKey", "date");

-- CreateIndex
CREATE UNIQUE INDEX "regional_rollups_metricKey_regionCode_date_key" ON "regional_rollups"("metricKey", "regionCode", "date");
