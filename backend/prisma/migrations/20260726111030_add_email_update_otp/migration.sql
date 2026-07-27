-- CreateTable
CREATE TABLE "email_change_otps" (
    "userId" TEXT NOT NULL,
    "newEmail" TEXT NOT NULL,
    "codeHash" TEXT NOT NULL,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "email_change_otps_pkey" PRIMARY KEY ("userId")
);
