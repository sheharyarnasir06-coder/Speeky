-- CreateTable
CREATE TABLE "rewrite_vocab_words" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "word" TEXT NOT NULL,
    "useCount" INTEGER NOT NULL DEFAULT 0,
    "status" TEXT NOT NULL DEFAULT 'introduced',
    "needsReview" BOOLEAN NOT NULL DEFAULT false,
    "introducedFrom" TEXT,
    "introducedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lastUsedAt" TIMESTAMP(3),

    CONSTRAINT "rewrite_vocab_words_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "rewrite_vocab_words_userId_status_idx" ON "rewrite_vocab_words"("userId", "status");

-- CreateIndex
CREATE UNIQUE INDEX "rewrite_vocab_words_userId_word_key" ON "rewrite_vocab_words"("userId", "word");

-- AddForeignKey
ALTER TABLE "rewrite_vocab_words" ADD CONSTRAINT "rewrite_vocab_words_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
