import { redirect } from "next/navigation";

// The answer bank moved into Profile → Answer bank (user, 2026-11-16).
export default function AnswersMoved() {
  redirect("/profile?tab=answers");
}
