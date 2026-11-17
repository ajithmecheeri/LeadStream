"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Bell } from "@/components/Bell";
import { Icon, type IconName } from "@/components/Icon";
import { api } from "@/lib/api";
import { useRequireSession } from "@/lib/session";

type Counts = { newJobs: number; needsInput: number; openApps: number; followUps: number };
type NavItem = { href: string; label: string; icon: IconName; badge?: (c: Counts) => { text: string; kind?: "alert" | "good" } | null };

// The sidebar in groups (the 2026-11-13 redesign). Badges are live counts; they're hidden from screen readers so
// each link's name stays its label ("Jobs"), and the pages say the same numbers in words.
const GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: "Workspace",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: "home",
        badge: (c) => (c.needsInput ? { text: `${c.needsInput} to do`, kind: "alert" } : null) },
      { href: "/jobs", label: "Jobs", icon: "briefcase", badge: (c) => (c.newJobs ? { text: `${c.newJobs}` } : null) },
      // A menu item of its own for job seekers, with Google Alerts (user, 2026-11-17); the button on Jobs stays.
      { href: "/jobs/find", label: "Find on Google", icon: "search" },
      { href: "/applications", label: "Applications", icon: "send",
        badge: (c) =>
          c.followUps ? { text: `${c.followUps} due`, kind: "alert" } : c.openApps ? { text: `${c.openApps} open`, kind: "good" } : null },
      { href: "/inbox", label: "Inbox", icon: "inbox" },
    ],
  },
  {
    title: "Your material",
    items: [
      // Resumes, search profiles and the answer bank live on Profile, in its tabs (user feedback 2026-11-13, 11-16).
      { href: "/profile", label: "Profile", icon: "user" },
    ],
  },
  {
    title: "Setup",
    items: [
      { href: "/settings/mail", label: "Mail setup", icon: "mail" },
      { href: "/settings", label: "Settings", icon: "settings" },
    ],
  },
];
// Job sources is for admins, Admin settings for the super admin (user, 2026-11-17).
const SOURCES: NavItem = { href: "/sources", label: "Job sources", icon: "globe" };
const ADMIN: NavItem = { href: "/admin/settings", label: "Admin settings", icon: "admin" };
const OPEN = ["applied", "interviewing", "offer"];

function initials(name: string): string {
  const parts = name.replace(/\([^)]*\)/g, " ").replace(/[^\p{L}\s]/gu, " ").trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1]![0] : "")).toUpperCase() || "?";
}

export default function AppLayout({ children }: { children: ReactNode }) {
  const { status, me, signOut } = useRequireSession();
  const path = usePathname();
  const router = useRouter();
  const blocked = status === "signed-in" && me !== null && !me.access.active;

  // A job seeker without a plan or coupon sees the plans (docs/plan-roles-and-plans.md, decision 5).
  useEffect(() => {
    if (blocked) router.replace("/plans");
  }, [blocked, router]);
  const [counts, setCounts] = useState<Counts | null>(null);

  // Refreshed on each page change: cheap, and the numbers follow what the user just did.
  useEffect(() => {
    if (status !== "signed-in" || blocked) return;
    Promise.all([api.jobStats(), api.applications({ due: true, limit: 1 })])
      .then(([s, a]) =>
        setCounts({
          newJobs: s.new,
          needsInput: s.needs_input,
          openApps: OPEN.reduce((n, k) => n + (a.counts[k] ?? 0), 0),
          followUps: a.follow_ups_due,
        }),
      )
      .catch(() => setCounts(null));
  }, [status, path, blocked]);

  if (status !== "signed-in" || !me || blocked) return <div className="loading">Loading…</div>;
  // Admins also get Job sources; the super admin Admin settings too (the API checks the roles as well).
  const extra = me.role === "super_admin" ? [SOURCES, ADMIN] : me.role === "admin" ? [SOURCES] : [];
  const groups = extra.length ? [...GROUPS.slice(0, 2), { ...GROUPS[2]!, items: [...GROUPS[2]!.items, ...extra] }] : GROUPS;
  const all = groups.flatMap((g) => g.items);
  // /settings/mail lights up Mail setup, not Settings as well.
  const matches = (href: string) => path.startsWith(href.split("#")[0]!) && !href.includes("#");
  const isActive = (href: string) =>
    matches(href) && !all.some((o) => o.href.length > href.length && o.href.startsWith(href + "/") && matches(o.href));
  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="brand">
          {/* The home page (user feedback 2026-11-11); the bell stays outside the link. */}
          <Link href="/" className="brand-link" data-testid="brand-home">
            <span className="brand-mug" aria-hidden="true"><Icon name="mug" size={20} /></span>
            <span className="brand-mark">BMJ</span>
            <span className="brand-name">
              <b>BrewMyJob</b>
              <small>Job copilot</small>
            </span>
          </Link>
          <Bell />
        </div>
        {groups.map((g) => (
          <div className="nav-group" key={g.title}>
            <div className="nav-group-title">{g.title}</div>
            {g.items.map((n) => {
              const badge = counts && n.badge ? n.badge(counts) : null;
              return (
                <Link key={n.href} href={n.href} className={`nav-link ${isActive(n.href) ? "active" : ""}`}
                  aria-current={isActive(n.href) ? "page" : undefined}>
                  <Icon name={n.icon} />
                  <span>{n.label}</span>
                  {badge ? <span className={`nav-badge ${badge.kind ?? ""}`} aria-hidden="true">{badge.text}</span> : null}
                </Link>
              );
            })}
          </div>
        ))}
        <div className="rail-foot">
          <span className="avatar" aria-hidden="true">{initials(me.name)}</span>
          <span className="rail-user">
            <b>{me.name}</b>
            <small>{me.email}</small>
          </span>
          <button type="button" className="rail-signout" onClick={signOut} title="Sign out">
            <Icon name="logout" />
            <span className="sr-only">Sign out</span>
          </button>
        </div>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
