import {
  Briefcase,
  Coffee,
  Folder,
  GraduationCap,
  Heart,
  Home,
  Globe,
  Plane,
  ShoppingBag,
  Stethoscope,
  UtensilsCrossed,
  BookOpen,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

// Closed vocabulary — keys must match backend/schemas/category_schemas.py's
// ALLOWED_ICONS exactly. Unknown keys (e.g. an older/renamed icon) fall back to
// Folder rather than breaking the tile (CM-US-05 default-icon exception).
export const ICON_MAP: Record<string, LucideIcon> = {
  folder: Folder,
  briefcase: Briefcase,
  coffee: Coffee,
  plane: Plane,
  utensils: UtensilsCrossed,
  heart: Heart,
  book: BookOpen,
  "shopping-bag": ShoppingBag,
  "graduation-cap": GraduationCap,
  stethoscope: Stethoscope,
  home: Home,
  globe: Globe,
};

export const ICON_NAMES = Object.keys(ICON_MAP);

export function resolveIcon(name: string): LucideIcon {
  return ICON_MAP[name] ?? Folder;
}
