-- GAP-03 (US-201) Anomaly Alerting + GAP-04 (US-202) Scheduled Reports.
-- Additive only — hand-written instead of a raw `prisma migrate diff` output
-- because this shared dev database currently has tables/columns (e.g.
-- content_drift_alerts, template_deployments, template_performance_snapshots,
-- users.consent*/learningGoal*) that are not present in this branch's
-- schema.prisma or migration history — almost certainly unmerged work from
-- another branch applied directly to the same shared DB. A full diff-based
-- migration would have DROPPED all of that; this migration only creates the
-- 6 new tables this feature needs and touches nothing else.

-- CreateTable
CREATE TABLE "metric_thresholds" (
    "id" TEXT NOT NULL,
    "metricKey" TEXT NOT NULL,
    "ownerAdminId" TEXT NOT NULL,
    "thresholdType" TEXT NOT NULL DEFAULT 'stddev_multiplier',
    "thresholdValue" DOUBLE PRECISION NOT NULL DEFAULT 2.0,
    "direction" TEXT NOT NULL DEFAULT 'any',
    "channels" TEXT[] DEFAULT ARRAY['email']::TEXT[],
    "slackWebhookUrl" TEXT,
    "isActive" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "metric_thresholds_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "anomaly_alerts" (
    "id" TEXT NOT NULL,
    "metricKey" TEXT NOT NULL,
    "value" DOUBLE PRECISION NOT NULL,
    "baselineValue" DOUBLE PRECISION NOT NULL,
    "deviation" DOUBLE PRECISION NOT NULL,
    "windowStart" TIMESTAMP(3) NOT NULL,
    "windowEnd" TIMESTAMP(3) NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'open',
    "digestGroupId" TEXT,
    "isUnassigned" BOOLEAN NOT NULL DEFAULT false,
    "incidentKey" TEXT NOT NULL,
    "deepLinkPath" TEXT NOT NULL,
    "acknowledgedBy" TEXT,
    "acknowledgedAt" TIMESTAMP(3),
    "falsePositiveMarkedBy" TEXT,
    "resolvedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "anomaly_alerts_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "alert_delivery_logs" (
    "id" TEXT NOT NULL,
    "alertId" TEXT,
    "digestGroupId" TEXT,
    "channel" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "error" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "alert_delivery_logs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "report_templates" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "ownerAdminId" TEXT NOT NULL,
    "metrics" TEXT[],
    "dateRangeType" TEXT NOT NULL DEFAULT 'last_7_days',
    "recurrence" TEXT NOT NULL DEFAULT 'weekly',
    "recurrenceDay" INTEGER,
    "recurrenceHour" INTEGER NOT NULL DEFAULT 9,
    "recurrenceMinute" INTEGER NOT NULL DEFAULT 0,
    "timezone" TEXT NOT NULL DEFAULT 'UTC',
    "recipients" JSONB NOT NULL DEFAULT '[]',
    "format" TEXT NOT NULL DEFAULT 'pdf',
    "isActive" BOOLEAN NOT NULL DEFAULT true,
    "nextRunAt" TIMESTAMP(3),
    "currentlyGenerating" BOOLEAN NOT NULL DEFAULT false,
    "pendingScheduleUpdate" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "report_templates_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "report_runs" (
    "id" TEXT NOT NULL,
    "templateId" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "attempt" INTEGER NOT NULL DEFAULT 0,
    "triggeredBy" TEXT NOT NULL DEFAULT 'schedule',
    "fileUrl" TEXT,
    "format" TEXT,
    "deliveryLog" JSONB NOT NULL DEFAULT '[]',
    "errorMessage" TEXT,
    "startedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "report_runs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "audit_log_entries" (
    "id" TEXT NOT NULL,
    "actorId" TEXT,
    "action" TEXT NOT NULL,
    "targetType" TEXT NOT NULL,
    "targetId" TEXT,
    "metadata" JSONB NOT NULL DEFAULT '{}',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "audit_log_entries_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "metric_thresholds_metricKey_isActive_idx" ON "metric_thresholds"("metricKey", "isActive");

-- CreateIndex
CREATE UNIQUE INDEX "metric_thresholds_metricKey_ownerAdminId_key" ON "metric_thresholds"("metricKey", "ownerAdminId");

-- CreateIndex
CREATE INDEX "anomaly_alerts_metricKey_createdAt_idx" ON "anomaly_alerts"("metricKey", "createdAt");

-- CreateIndex
CREATE INDEX "anomaly_alerts_status_idx" ON "anomaly_alerts"("status");

-- CreateIndex
CREATE INDEX "anomaly_alerts_digestGroupId_idx" ON "anomaly_alerts"("digestGroupId");

-- CreateIndex
CREATE INDEX "anomaly_alerts_incidentKey_status_idx" ON "anomaly_alerts"("incidentKey", "status");

-- CreateIndex
CREATE INDEX "alert_delivery_logs_alertId_idx" ON "alert_delivery_logs"("alertId");

-- CreateIndex
CREATE INDEX "alert_delivery_logs_digestGroupId_idx" ON "alert_delivery_logs"("digestGroupId");

-- CreateIndex
CREATE INDEX "report_templates_nextRunAt_isActive_idx" ON "report_templates"("nextRunAt", "isActive");

-- CreateIndex
CREATE INDEX "report_templates_ownerAdminId_idx" ON "report_templates"("ownerAdminId");

-- CreateIndex
CREATE INDEX "report_runs_templateId_createdAt_idx" ON "report_runs"("templateId", "createdAt");

-- CreateIndex
CREATE INDEX "audit_log_entries_targetType_targetId_idx" ON "audit_log_entries"("targetType", "targetId");

-- CreateIndex
CREATE INDEX "audit_log_entries_actorId_createdAt_idx" ON "audit_log_entries"("actorId", "createdAt");
