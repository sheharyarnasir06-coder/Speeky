-- CreateTable
CREATE TABLE "code_switch_words" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "word" TEXT NOT NULL,
    "suggestion" TEXT NOT NULL,
    "count" INTEGER NOT NULL DEFAULT 1,
    "firstSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lastSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "code_switch_words_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "code_switch_words_userId_word_key" ON "code_switch_words"("userId", "word");

-- CreateIndex
CREATE INDEX "code_switch_words_userId_lastSeenAt_idx" ON "code_switch_words"("userId", "lastSeenAt");

-- AddForeignKey
ALTER TABLE "code_switch_words" ADD CONSTRAINT "code_switch_words_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
