"use client";
import Link from "next/link";
import { useSession } from "@/lib/session";
import s from "./home.module.css";

/** Signed in: one button back into the app. Otherwise: sign in, and the waitlist. */
export function NavEnd() {
  const { status } = useSession();
  if (status === "signed-in") {
    return (
      <div className={s.navEnd}>
        <Link href="/dashboard" className={`${s.btnDark} ${s.navCta}`}>Open the app</Link>
      </div>
    );
  }
  return (
    <div className={s.navEnd}>
      <Link href="/sign-in" className={s.navSignIn}>Sign in</Link>
      <a href="#waitlist" className={`${s.btnDark} ${s.navCta}`}>Join the waitlist</a>
    </div>
  );
}
