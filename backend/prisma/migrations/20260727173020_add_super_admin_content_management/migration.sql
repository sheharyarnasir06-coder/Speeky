-- AlterEnum
ALTER TYPE "Role" ADD VALUE 'SUPER_ADMIN';

-- AlterTable
ALTER TABLE "custom_scenarios" ADD COLUMN     "confidenceFeedback" JSONB,
ADD COLUMN     "confidenceScore" INTEGER,
ADD COLUMN     "difficulty" TEXT NOT NULL DEFAULT 'intermediate',
ADD COLUMN     "qualityFeedback" JSONB,
ADD COLUMN     "qualityScore" INTEGER,
ADD COLUMN     "readinessChecklist" JSONB,
ADD COLUMN     "readinessScore" INTEGER,
ADD COLUMN     "sandboxTested" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN     "scoredAt" TIMESTAMP(3),
ADD COLUMN     "status" TEXT NOT NULL DEFAULT 'ACTIVE',
ADD COLUMN     "version" INTEGER NOT NULL DEFAULT 1;

-- AlterTable
ALTER TABLE "scenario_sessions" ADD COLUMN     "scenarioMeta" JSONB;

-- CreateTable
CREATE TABLE "custom_scenario_versions" (
    "id" TEXT NOT NULL,
    "scenarioId" TEXT NOT NULL,
    "version" INTEGER NOT NULL,
    "snapshot" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "custom_scenario_versions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "categories" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "icon" TEXT NOT NULL DEFAULT 'folder',
    "order" INTEGER NOT NULL DEFAULT 0,
    "protected" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "categories_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "custom_scenario_versions_scenarioId_version_idx" ON "custom_scenario_versions"("scenarioId", "version");

-- CreateIndex
CREATE UNIQUE INDEX "categories_name_key" ON "categories"("name");

-- CreateIndex
CREATE UNIQUE INDEX "categories_slug_key" ON "categories"("slug");

-- AddForeignKey
ALTER TABLE "custom_scenario_versions" ADD CONSTRAINT "custom_scenario_versions_scenarioId_fkey" FOREIGN KEY ("scenarioId") REFERENCES "custom_scenarios"("id") ON DELETE CASCADE ON UPDATE CASCADE;
