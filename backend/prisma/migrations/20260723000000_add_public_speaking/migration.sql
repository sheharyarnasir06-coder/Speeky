-- CreateTable
CREATE TABLE "public_speaking_sessions" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "speechType" TEXT NOT NULL,
    "inputMode" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'in_progress',
    "topic" TEXT,
    "transcript" TEXT,
    "scorecard" JSONB,
    "aiQuestion" TEXT,
    "userQaResponse" TEXT,
    "qaScore" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completedAt" TIMESTAMP(3),

    CONSTRAINT "public_speaking_sessions_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "public_speaking_sessions_userId_completedAt_idx" ON "public_speaking_sessions"("userId", "completedAt");

-- AddForeignKey
ALTER TABLE "public_speaking_sessions" ADD CONSTRAINT "public_speaking_sessions_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
