-- AlterTable
ALTER TABLE "users" ADD COLUMN     "accentModelPreference" TEXT NOT NULL DEFAULT 'generic_global',
ADD COLUMN     "isAccentSuspended" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN     "livenessFlagCount" INTEGER NOT NULL DEFAULT 0;

-- CreateTable
CREATE TABLE "liveness_flags" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "passageId" TEXT,
    "sentenceId" TEXT,
    "promptToken" TEXT,
    "reason" TEXT NOT NULL,
    "appealed" BOOLEAN NOT NULL DEFAULT false,
    "appealPassed" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "liveness_flags_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "liveness_flags_userId_createdAt_idx" ON "liveness_flags"("userId", "createdAt");

-- AddForeignKey
ALTER TABLE "liveness_flags" ADD CONSTRAINT "liveness_flags_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
