import type { Metadata } from "next";
import Link from "next/link";
import { LegalPage } from "../_legal/LegalPage";

export const metadata: Metadata = {
  title: "Terms of use",
  description: "The terms for using BrewMyJob: what it does, what it doesn't, and what we ask of you.",
  alternates: { canonical: "/terms" },
};

export default function TermsPage() {
  return (
    <LegalPage title="Terms of use" path="/terms" draft>
      <p>
        These terms apply when you use BrewMyJob, the website and app at brewmyjob.com. By creating an account you agree to them. Our{" "}
        <Link href="/privacy">privacy policy</Link> explains what we keep about you.
      </p>

      <h2>What BrewMyJob does</h2>
      <p>
        BrewMyJob reads the job-alert emails you forward to it, and jobs from sources you choose, scores each job against your search
        profiles and resumes, helps you prepare, and tracks your applications. <strong>You decide and you apply yourself.</strong> BrewMyJob
        never submits an application, signs in to a job site, or contacts anyone for you.
      </p>

      <h2>What it doesn&apos;t promise</h2>
      <ul>
        <li>A match score is an estimate from the information available, often only a job&apos;s title. It isn&apos;t advice and doesn&apos;t predict whether you&apos;ll be hired.</li>
        <li>Jobs come from emails, AI assistants and other sources we don&apos;t control. A job may have closed, or its details may be wrong. Check the employer&apos;s page before you apply.</li>
        <li>Suggestions written by AI (once switched on) are drafts. Read and correct them before you use them; you are responsible for what you send to an employer.</li>
      </ul>

      <h2>Your account</h2>
      <ul>
        <li>An account is for one person. Keep your password to yourself and tell us if you think someone else has used your account.</li>
        <li>You must be 18 or over.</li>
        <li>Give accurate information about yourself, and upload only resumes and documents that are yours to use.</li>
      </ul>

      <h2>Using it fairly</h2>
      <ul>
        <li>Forward only emails sent to you, and import only your own data (for example your own LinkedIn connections export).</li>
        <li>Follow the terms of the job sites you use. BrewMyJob doesn&apos;t automate LinkedIn, Naukri or other job portals, and you
          mustn&apos;t use it to do so.</li>
        <li>Don&apos;t try to reach other users&apos; data, overload the service, or copy the job catalog in bulk.</li>
      </ul>
      <p>
        <strong>Browser extension (when available).</strong> It fills fields on a company&apos;s own application form only when you click,
        in your browser. It never submits, signs up or signs in, and it is blocked on job portals.
      </p>

      <h2>Fees</h2>
      <p>BrewMyJob is free during early access. Before any paid plan applies to you, its price and what it includes will be shown and you will choose it yourself.</p>

      <h2>Ending your use</h2>
      <p>
        You can stop using BrewMyJob at any time and ask us to delete your account and data (see the privacy policy). We may suspend
        an account that breaks these terms, and will tell you why when we can.
      </p>

      <h2>Liability</h2>
      <p>
        We work to keep BrewMyJob accurate and available but provide it as it is, without guarantees. To the extent the law allows, we
        aren&apos;t liable for decisions made using it, including jobs applied for or missed.
      </p>

      <h2>Changes and contact</h2>
      <p>
        If these terms change, we will update this page and tell signed-in users before the change applies. These terms are governed by
        the laws of India. Questions: the <Link href="/contact">contact page</Link>.
      </p>
    </LegalPage>
  );
}
