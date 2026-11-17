"use client";
import type { Me, Schemas } from "@fitfirst/api";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";

type SignUpBody = Schemas["SignupIn"];

type Status = "loading" | "signed-in" | "signed-out";

interface Session {
  status: Status;
  me: Me | null;
  setMe: (m: Me) => void;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (body: SignUpBody) => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<Session | null>(null);

/** An invite link opened before signing in: accepted on /invite once signed in (sessionStorage key). */
export const PENDING_INVITE = "bmj-pending-invite";

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);

  // On load, trade the HttpOnly refresh cookie for an access token.
  useEffect(() => {
    let alive = true;
    (async () => {
      const ok = await api.refresh();
      if (!alive) return;
      if (!ok) return setStatus("signed-out");
      try {
        setMe(await api.me());
        setStatus("signed-in");
      } catch {
        setStatus("signed-out");
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const t = await api.signIn({ email, password });
    setMe(t.user);
    setStatus("signed-in");
  }, []);

  const signUp = useCallback(async (body: SignUpBody) => {
    const t = await api.signUp(body);
    setMe(t.user);
    setStatus("signed-in");
  }, []);

  const signOut = useCallback(async () => {
    await api.signOut();
    setMe(null);
    setStatus("signed-out");
  }, []);

  const value = useMemo(() => ({ status, me, setMe, signIn, signUp, signOut }), [status, me, signIn, signUp, signOut]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession must be used inside <SessionProvider>");
  return s;
}

/** Redirects to /sign-in when signed out. Returns the session for convenience. */
export function useRequireSession(): Session {
  const s = useSession();
  const router = useRouter();
  useEffect(() => {
    if (s.status === "signed-out") router.replace("/sign-in");
  }, [s.status, router]);
  return s;
}
