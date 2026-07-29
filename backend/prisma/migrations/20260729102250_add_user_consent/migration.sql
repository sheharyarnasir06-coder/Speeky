-- AlterTable
ALTER TABLE "users" ADD COLUMN     "consentAcceptedAt" TIMESTAMP(3),
ADD COLUMN     "consentVersion" TEXT,
ADD COLUMN     "isConsented" BOOLEAN NOT NULL DEFAULT false;
