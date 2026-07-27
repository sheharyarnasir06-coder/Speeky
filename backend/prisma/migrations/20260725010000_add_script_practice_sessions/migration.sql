-- CreateTable
CREATE TABLE "script_practice_sessions" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "scriptText" TEXT NOT NULL,
    "context" TEXT,
    "status" TEXT NOT NULL DEFAULT 'awaiting_baseline',
    "baselineConfidence" DOUBLE PRECISION,
    "baselineTranscript" TEXT,
    "baselineDuration" DOUBLE PRECISION,
    "afterConfidence" DOUBLE PRECISION,
    "afterTranscript" TEXT,
    "afterDuration" DOUBLE PRECISION,
    "confidenceGain" DOUBLE PRECISION,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completedAt" TIMESTAMP(3),

    CONSTRAINT "script_practice_sessions_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "script_practice_sessions_userId_status_idx" ON "script_practice_sessions"("userId", "status");

-- AddForeignKey
ALTER TABLE "script_practice_sessions" ADD CONSTRAINT "script_practice_sessions_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
