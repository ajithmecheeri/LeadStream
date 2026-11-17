import { redirect } from "next/navigation";

// Search profiles moved into Profile → Skill Match Profile (user feedback 2026-11-13).
export default function SearchProfilesMoved() {
  redirect("/profile?tab=match");
}
