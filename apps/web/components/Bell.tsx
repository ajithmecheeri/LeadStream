"use client";
import type { Bell as BellData } from "@fitfirst/api";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { seenAgo } from "@/lib/jobs";

const REFRESH_MS = 60_000;
const KIND_LABEL: Record<string, string> = {
  strong: "Top match",
  duplicate: "Duplicate?",
  follow_up: "Follow up",
  expiry: "Expiry",
};

/** The in-app bell (milestone 6.2): what needs attention, with an unread count. Opening it marks everything read;
 * the items stay highlighted until it is closed, so the user can see what was new. */
export function Bell() {
  const [data, setData] = useState<BellData | null>(null);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const path = usePathname();

  const load = useCallback(() => {
    api.bell().then(setData).catch(() => undefined); // the bell is extra: a failed refresh shows the last list
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => setOpen(false), [path]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && data?.unread) {
      api.bellSeen().catch(() => undefined);
    } else if (!next && data?.unread) {
      setData((d) => (d ? { unread: 0, items: d.items.map((i) => ({ ...i, unread: false })) } : d));
    }
  };

  const unread = data?.unread ?? 0;
  return (
    <div className="bell" ref={box}>
      <button
        type="button"
        className="bell-button"
        onClick={toggle}
        aria-expanded={open}
        aria-label={unread ? `Notifications, ${unread} new` : "Notifications"}
        data-testid="bell"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {unread ? <span className="bell-count" data-testid="bell-count">{unread > 99 ? "99+" : unread}</span> : null}
      </button>
      {open ? (
        <div className="bell-panel" role="dialog" aria-label="Notifications">
          <div className="bell-head">Needs your attention</div>
          {!data?.items.length ? (
            <p className="subtle bell-empty">Nothing right now. New top matches, possible duplicates, follow-ups and jobs that may have expired show here.</p>
          ) : (
            <ul className="bell-list">
              {data.items.map((i) => (
                <li key={i.key} className={i.unread ? "unread" : undefined} data-testid="bell-item">
                  <Link href={`/jobs/${i.user_job_id}`}>
                    <span className={`bell-kind ${i.kind}`}>{KIND_LABEL[i.kind] ?? i.kind}</span>
                    <strong>{i.title}</strong>
                    <span className="bell-detail">{i.detail}</span>
                    <span className="bell-at">{seenAgo(i.at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
