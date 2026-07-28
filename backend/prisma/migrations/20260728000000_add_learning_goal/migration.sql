-- AlterTable: US-08/US-10 learning goal on the user profile.
-- Default (not NULL) so an abandoned goal step (E-03) still leaves a usable profile.
ALTER TABLE "users" ADD COLUMN "learningGoal" TEXT NOT NULL DEFAULT 'improve_english';
