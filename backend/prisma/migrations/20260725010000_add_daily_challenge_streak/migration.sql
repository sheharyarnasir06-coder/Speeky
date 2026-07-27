-- AlterTable: PDG-US-11 Daily Challenge streak fields
ALTER TABLE "users" ADD COLUMN "currentStreak" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "users" ADD COLUMN "longestStreak" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "users" ADD COLUMN "lastChallengeDate" TEXT;
ALTER TABLE "users" ADD COLUMN "streakBadges" INTEGER[] DEFAULT ARRAY[]::INTEGER[];
