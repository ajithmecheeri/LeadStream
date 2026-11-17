import Link from "next/link";
import type { ReactNode } from "react";
import s from "./legal.module.css";

/** Until a lawyer has reviewed them, the privacy policy and terms say they are a draft (user decision pending). */
export const LEGAL_DRAFT = true;
export const LEGAL_UPDATED = "9 November 2026";

const LINKS = [
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
  { href: "/contact", label: "Contact" },
];

export function LegalPage({ title, path, children, draft = false }: { title: string; path: string; children: ReactNode; draft?: boolean }) {
  return (
    <div className={s.root}>
      <header className={s.top}>
        <div className={s.bar}>
          <Link href="/" className={s.logo}>brewmyjob</Link>
          <nav className={s.nav} aria-label="Site">
            {LINKS.map((l) => (
              <Link key={l.href} href={l.href} aria-current={l.href === path ? "page" : undefined}>{l.label}</Link>
            ))}
            <Link href="/sign-in">Sign in</Link>
          </nav>
        </div>
      </header>
      <main className={s.main}>
        <h1>{title}</h1>
        {draft ? <p className={s.updated}>Last updated {LEGAL_UPDATED}</p> : null}
        {draft && LEGAL_DRAFT ? (
          <p className={s.draft} data-testid="legal-draft">
            <strong>Draft.</strong> BrewMyJob is in early access. This page describes how the service works today and will be reviewed
            before public launch. Questions are welcome on the <Link href="/contact">contact page</Link>.
          </p>
        ) : null}
        {children}
      </main>
      <footer className={s.foot}>
        <div className={s.bar}>
          <span>Brewed in Bengaluru. © 2026 BrewMyJob.</span>
          <nav className={s.nav} aria-label="Footer">
            {LINKS.map((l) => <Link key={l.href} href={l.href}>{l.label}</Link>)}
          </nav>
        </div>
      </footer>
    </div>
  );
}
