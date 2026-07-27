-- CreateTable
CREATE TABLE "script_practice_history" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "sessionId" TEXT,
    "scriptText" TEXT NOT NULL,
    "context" TEXT,
    "baselineConfidence" DOUBLE PRECISION NOT NULL,
    "afterConfidence" DOUBLE PRECISION NOT NULL,
    "confidenceGain" DOUBLE PRECISION NOT NULL,
    "baselineMetrics" JSONB NOT NULL DEFAULT '{}',
    "afterMetrics" JSONB NOT NULL DEFAULT '{}',
    "feedback" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "script_practice_history_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "script_practice_history_userId_createdAt_idx" ON "script_practice_history"("userId", "createdAt");

-- AddForeignKey
ALTER TABLE "script_practice_history" ADD CONSTRAINT "script_practice_history_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
