-- AlterTable: US-08 fallback for pre-existing accounts. learningGoal's default value
-- ("improve_english") is indistinguishable from a real choice, so this flag is the
-- actual "has the user ever picked a goal" signal. Default false backfills every
-- existing row as "needs the onboarding prompt" — new/legacy users alike only flip
-- to true once they actually submit a goal (services.user_service.set_learning_goal).
ALTER TABLE "users" ADD COLUMN "learningGoalSet" BOOLEAN NOT NULL DEFAULT false;
