"use client";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Icon } from "@/components/Icon";
import { PENDING_INVITE, useSession } from "@/lib/session";

export default function AuthLayout({ children }: { children: ReactNode }) {
  const { status } = useSession();
  const router = useRouter();
  useEffect(() => {
    if (status !== "signed-in") return;
    let pending: string | null = null;
    try {
      pending = sessionStorage.getItem(PENDING_INVITE);
    } catch {
      // storage blocked
    }
    router.replace(pending ? `/invite?token=${encodeURIComponent(pending)}` : "/dashboard");
  }, [status, router]);
  return (
    <main className="auth-wrap">
      <div className="card auth-card">
        <div className="brand">
          <span className="brand-mug" aria-hidden="true"><Icon name="mug" size={24} /></span>
          <span className="brand-mark">BMJ</span>BrewMyJob
        </div>
        {children}
      </div>
    </main>
  );
}
