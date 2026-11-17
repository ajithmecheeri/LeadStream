import type { Metadata } from "next";
import Link from "next/link";
import { LegalPage } from "../_legal/LegalPage";
import s from "../_legal/legal.module.css";

// Every statement here must stay true of the code: when a feature changes what is collected or who receives it,
// change this page in the same commit (docs/milestones.md, milestone 10).

export const metadata: Metadata = {
  title: "Privacy policy",
  description: "What BrewMyJob keeps about you, why, who else sees it, and how to get it changed or deleted.",
  alternates: { canonical: "/privacy" },
};

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy policy" path="/privacy" draft>
      <p>
        BrewMyJob reads the job-alert emails you forward to it, scores each job against what you are looking for, suggests
        your best resume and tracks your applications. You always apply yourself. This page explains what we keep to do that.
      </p>

      <h2>The short version</h2>
      <ul>
        <li>We keep only what you give us or forward to us, and use it to run BrewMyJob for you.</li>
        <li>We never ask for your LinkedIn, Naukri or email password, and never sign in to job sites for you.</li>
        <li>We don&apos;t sell your data, show ads, or use advertising or analytics cookies.</li>
        <li>Your data is kept apart from every other user&apos;s, and you can ask us to correct or delete it.</li>
      </ul>

      <h2>What we keep</h2>
      <table className={s.table}>
        <thead><tr><th>What</th><th>Why</th></tr></thead>
        <tbody>
          <tr><td>Your name, email address and time zone; your password, stored only as a one-way hash (Argon2id)</td><td>Your account and sign-in</td></tr>
          <tr><td>Your profile: headline, summary, location, experience, skills, notice period, current and expected salary, work authorisation, LinkedIn profile link</td><td>Scoring jobs and answering common application questions</td></tr>
          <tr><td>Search profiles, your answer bank, and the feedback you give on jobs (&quot;Not for me&quot; and its reason)</td><td>Scoring jobs the way you want them scored</td></tr>
          <tr><td>Resumes and cover letters you upload, and the text read from them</td><td>Matching jobs and suggesting the best resume</td></tr>
          <tr><td>Job-alert emails you forward to your BrewMyJob address. The email itself is deleted after 90 days; the jobs found in it stay</td><td>Finding the jobs in them</td></tr>
          <tr><td>Your applications, notes, follow-up dates and the contacts you save on a job</td><td>Your application tracker</td></tr>
          <tr><td>LinkedIn connections you import from LinkedIn&apos;s own export file (name, company, position)</td><td>Showing who you know at a company</td></tr>
          <tr><td>Your WhatsApp number, if you add one, and a log of the alerts sent to it</td><td>Job alerts on WhatsApp</td></tr>
        </tbody>
      </table>
      <p>
        <strong>The shared job catalog.</strong> The facts of a job posting (title, company, location, description) are stored once and
        shared between users who receive the same job. Nothing about you goes into it: not your links (which can carry your sign-in
        on a job site), not your notes, not lines such as &quot;2 connections&quot;.
      </p>
      <p>
        If you join the waitlist or write to us on the contact page, we keep the email address and message you send.
      </p>

      <h2>Cookies</h2>
      <p>
        One cookie keeps you signed in (a sign-in token, sent only to BrewMyJob, not readable by page scripts, valid for 30 days or
        until you sign out). There are no advertising, tracking or analytics cookies. If we add analytics, this page will say so
        first, and anything that needs your consent will ask for it.
      </p>

      <h2>Who else receives your data</h2>
      <p>Only the services BrewMyJob needs to work, each for the purpose shown:</p>
      <table className={s.table}>
        <thead><tr><th>Service</th><th>What it receives</th><th>Why</th></tr></thead>
        <tbody>
          <tr><td>Cloudflare</td><td>The emails you forward, on their way to BrewMyJob</td><td>Receiving email at your BrewMyJob address</td></tr>
          <tr><td>Voyage AI</td><td>The text of your resumes, cover letters and jobs</td><td>Measuring how closely a resume matches a job</td></tr>
          <tr><td>Meta (WhatsApp)</td><td>Your WhatsApp number and the alert text</td><td>Sending WhatsApp alerts, only if you turn them on</td></tr>
          <tr><td>Anthropic (Claude)</td><td>Resume and job text, when an AI feature runs</td><td>AI scoring and writing help, once these features are switched on</td></tr>
        </tbody>
      </table>
      <p>
        Job sources such as Adzuna and company career sites receive only search terms (roles, cities) or company names, never
        anything about you. We will name our hosting provider and where data is stored here before public launch.
      </p>

      <h2>How we protect it</h2>
      <ul>
        <li>Each user&apos;s data is separated in the database itself (row-level security), and tested on every change.</li>
        <li>Passwords are stored only as a strong one-way hash.</li>
        <li>Links in alert emails that could sign someone in to a job site are kept only for you, never shared or opened by BrewMyJob.</li>
      </ul>

      <h2>Your rights</h2>
      <p>
        Under India&apos;s Digital Personal Data Protection Act, 2023, you can ask to see the personal data we hold about you, to correct
        or complete it, and to have it deleted, and you can raise a grievance with us. Most of your data can be viewed and changed in
        the app. Self-service export and account deletion are being built; until then, send the request through
        the <Link href="/contact">contact page</Link> (topic: Privacy) from the email address on your account.
      </p>
      <p>BrewMyJob is for people aged 18 and over.</p>

      <h2>Changes</h2>
      <p>If we change what we collect or who receives it, we will update this page and tell signed-in users in the app first.</p>

      <h2>Contact</h2>
      <p>Write to us on the <Link href="/contact">contact page</Link>.</p>
    </LegalPage>
  );
}
