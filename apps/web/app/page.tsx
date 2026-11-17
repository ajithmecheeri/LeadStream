import type { Metadata } from "next";
import Link from "next/link";
import { CoffeeCup } from "./_home/CoffeeCup";
import { NavEnd } from "./_home/NavEnd";
import { WaitlistForm } from "./_home/WaitlistForm";
import s from "./_home/home.module.css";

// The public home page (brewmyjob.com), from the user's editorial design of 2026-11-13 (the previous page is backed up
// in ~/code/FitFirst-backups/home-before-redesign-2026-11-13/). Truthful content only (CLAUDE.md, milestone 10):
// everything it says works today is built; the rest is marked "coming soon", and the job, scores and people shown
// are labelled examples. Keep it that way when the product changes.

const TITLE = "BrewMyJob: your job alerts, brewed into applications worth sending";
const DESCRIPTION =
  "Forward the LinkedIn and Naukri alerts you already get. BrewMyJob scores every job against what you want, " +
  "picks your best resume and tracks every application. You review it, and you click Apply.";

export const metadata: Metadata = {
  title: { absolute: TITLE },
  description: DESCRIPTION,
  alternates: { canonical: "/" },
  openGraph: { type: "website", siteName: "BrewMyJob", title: TITLE, description: DESCRIPTION, url: "/", locale: "en_IN" },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION },
};

const FONTS =
  "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600" +
  "&family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;1,6..72,400" +
  "&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap";

const PATHS = {
  arrow: "M5 12h14M13 6l6 6-6 6",
  lock: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
  explore: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M15.5 8.5l-2 5-5 2 2-5z",
  shield: "M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6zM9 12l2 2 4-4",
  block: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M5.6 5.6l12.8 12.8",
  check: "M20 6 9 17l-5-5",
  checkCircle: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M8 12l3 3 5-5",
  close: "M18 6 6 18M6 6l12 12",
  alert: "M12 3 2 20h20zM12 10v4M12 17h.01",
  coffee: "M4 9h13v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5zM17 10h1.5a2.5 2.5 0 0 1 0 5H17M8 3v2M12 3v2",
  inbox: "M3 13l3-8h12l3 8v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1zM3 13h5l1 3h6l1-3h5",
  layers: "M12 3 2 8l10 5 10-5zM2 13l10 5 10-5M2 18l10 5 10-5",
  verified: "M12 2l2.4 2.2 3.2-.4.8 3.1 2.8 1.6-1.2 3 1.2 3-2.8 1.6-.8 3.1-3.2-.4L12 22l-2.4-2.2-3.2.4-.8-3.1L2.8 15.5l1.2-3-1.2-3 2.8-1.6.8-3.1 3.2.4zM8.5 12l2.5 2.5 4.5-5",
  send: "M21 3 10 14M21 3l-7 18-4-7-7-4z",
  file: "M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5",
  tune: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M14 4v4M8 10v4M16 16v4",
  hub: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6M5 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4M19 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4M5 16a2 2 0 1 0 0 4 2 2 0 0 0 0-4M19 16a2 2 0 1 0 0 4 2 2 0 0 0 0-4M6.5 7.5l3 2.5M17.5 7.5l-3 2.5M6.5 16.5l3-2.5M17.5 16.5l-3-2.5",
  spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
  chevron: "M6 9l6 6 6-6",
  star: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z",
} as const;

function I({ name, size = 18 }: { name: keyof typeof PATHS; size?: number }) {
  return (
    <svg className={s.icon} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={PATHS[name]} />
    </svg>
  );
}

const LIVE_SOURCES = ["LinkedIn job alerts", "Naukri job alerts", "Company career pages", "Job lists from your AI assistant"];
const SOON_SOURCES = ["iimjobs", "hirist", "Indeed", "Foundit"];

const STEPS = [
  { n: "01", icon: "inbox", title: "Forward", foot: ["NO PASSWORDS", "INGESTION"],
    text: "Set one rule in Gmail or Outlook that forwards your LinkedIn and Naukri alerts to your own BrewMyJob address." },
  { n: "02", icon: "layers", title: "Sift & dedupe", foot: ["ONE CARD PER JOB", "PURIFICATION"],
    text: "Each alert is split into jobs: title, company, place, pay where listed. The same role from two sites becomes one card." },
  { n: "03", icon: "verified", title: "Score", foot: ["EVERY POINT EXPLAINED", "SCORING"],
    text: "Every job is scored against each of your resumes and what you want: role, seniority, skills, place and pay, with the reasons shown." },
  { n: "04", icon: "send", title: "You apply", foot: ["HUMAN AGENCY", "DISPATCH"],
    text: "Open your Top matches: the resume to use, who you know there, an Apply kit to copy into forms. You click Apply." },
] as const;

const COMPARE = [
  ["Your job-site login", "Often ask you to sign in to job sites for them", "No passwords. Jobs arrive by email forwarding"],
  ["What it claims about you", "Can stretch your experience to tick a form's boxes", "Only what your own resumes support"],
  ["The same job on several sites", "Can apply to it again on every site", "One card for the same role, whichever site sent it"],
  ["How many a day", "Hundreds of applications, unread", "Only the jobs above your own threshold"],
  ["Who sends it", "The bot, often without asking each time", "You. You review and click Apply, every time"],
];

const FAQS = [
  { q: "Do you need my LinkedIn or Naukri password?",
    a: "Never. You set up a forwarding rule in your email so job alerts reach your personal BrewMyJob address. We never log in to any job portal and never store portal or email passwords." },
  { q: "Why won't BrewMyJob apply for me?",
    a: "Senior hiring runs on judgement and relationships. Bots that apply for you send duplicate and badly fitting applications in your name. BrewMyJob prepares everything — the score, the best resume, who you know at the company — and you review it and click Apply on the job site yourself." },
  { q: "Will it add experience I don't have?",
    a: "No. Missing skills are shown as missing, and you decide which ones you really have. Tailored resumes and cover letters (coming soon) go through a claim check: anything your own resumes don't support is left out." },
  { q: "Can I use it while I'm quietly exploring?",
    a: "Yes. BrewMyJob only reads the alerts you forward. It never posts, connects or changes anything on LinkedIn, Naukri or any job site." },
  { q: "Which job sites does it work with?",
    a: "LinkedIn and Naukri job-alert emails, company career pages, and job lists from your AI assistant today. iimjobs, hirist, Indeed and Foundit are coming next." },
  { q: "Is my data private?",
    a: "Each account's data is isolated at the database level, not just in the app. Exporting all of it, or deleting your account and everything in it, arrives before paid plans launch." },
];

const PLANS = [
  { label: "1 month", price: "₹199", note: "For a quick look around." },
  { label: "3 months", price: "₹500", note: "₹167 a month. A typical search." },
  { label: "6 months", price: "₹750", note: "₹125 a month. Room for the right role." },
  { label: "1 year", price: "₹1,200", note: "₹100 a month. Always watching.", best: true },
];

export default function Home() {
  return (
    <div className={s.page}>
      {/* eslint-disable-next-line @next/next/no-page-custom-font */}
      <link rel="stylesheet" href={FONTS} />

      <nav className={s.nav} aria-label="Site">
        <div className={`${s.wrap} ${s.navRow}`}>
          <a className={s.brand} href="#top" aria-label="BrewMyJob, top of the page">
            <CoffeeCup className={s.cup} />
            <span className={s.mark} aria-hidden="true">BMJ</span>
            <span className={s.wordmark}>BrewMyJob</span>
          </a>
          <div className={s.navLinks}>
            <a href="#how">How it works</a>
            <a href="#features">Features</a>
            <a href="#claim-check">No made-up claims</a>
            <a href="#pricing">Pricing</a>
            <a href="#faq">FAQ</a>
          </div>
          <NavEnd />
        </div>
      </nav>

      <main className={s.main} id="top">
        {/* Hero */}
        <section className={s.hero}>
          <div className={`${s.wrap} ${s.heroGrid}`}>
            <div className={s.heroText}>
              <div className={s.pill}><span className={s.dot} /><span className={s.label}>Now brewing in India · LinkedIn + Naukri alerts</span></div>
              <h1 className={s.h1}>Fifty noisy alerts in. The three jobs worth your evening out.</h1>
              <p className={s.lead}>
                BrewMyJob sits between your job alerts and your calendar. Forward the LinkedIn and Naukri alerts you
                already get: it reads every job, scores it against what you want and the resumes you have, and brings
                the few worth your time to the top. You review, and you click Apply.
              </p>
              <div className={s.actions}>
                <a className={s.btnDark} href="#waitlist">Get my brewing address <span className={s.arrow}><I name="arrow" /></span></a>
                <a className={s.btnLine} href="#how"><I name="explore" /> See how it works</a>
              </div>
              <div className={s.trustGrid}>
                {[
                  ["shield", "Zero", "No passwords needed", "Just a forwarding address"],
                  ["block", "Pure", "No auto-apply bots", "Protects your reputation"],
                  ["verified", "True", "No made-up claims", "Only what your resumes say"],
                ].map(([icon, head, title, note]) => (
                  <div key={title}>
                    <div className={s.trustHead}><I name={icon as keyof typeof PATHS} size={16} />{head}</div>
                    <p className={s.trustTitle}>{title}</p>
                    <p className={s.trustNote}>{note}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className={s.heroMedia}>
              <div className={s.photo}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/home/desk-ritual.jpg" width={1376} height={768} fetchPriority="high"
                  alt="A desk with two espressos, a notebook and pen, a ruler, and a laptop showing charts" />
                <div className={s.photoShade} />
                <div className={s.dossier} aria-label="An example match">
                  <div className={s.dossierTop}>
                    <div>
                      <span className={s.tag}><I name="verified" size={13} /> Example match</span>
                      <h3 className={s.h3}>VP Engineering · Platform</h3>
                      <p className={`${s.small} ${s.muted}`}>A Series C software company · Bengaluru (Hybrid)</p>
                    </div>
                    <div>
                      <div className={s.bigScore}>94%</div>
                      <span className={s.labelSm} style={{ color: "var(--ink-2)" }}>Match</span>
                    </div>
                  </div>
                  <div className={s.facts}>
                    {[["Pay", "₹85L – ₹1.1Cr"], ["Seniority", "VP"], ["Best resume", "Platform & AI"], ["Warm path", "2 connections"]].map(([k, v]) => (
                      <div className={s.fact} key={k}><span className={s.labelSm}>{k}</span><b>{v}</b></div>
                    ))}
                  </div>
                </div>
              </div>
              <div className={s.cornerAccent} aria-hidden="true" />
            </div>
          </div>
        </section>

        {/* Sources */}
        <section className={s.strip} aria-label="Where jobs come from">
          <div className={`${s.wrap} ${s.stripRow}`}>
            <div className={s.stripTitle}><I name="spark" size={20} /> Where jobs come from</div>
            <div className={s.chips}>
              {LIVE_SOURCES.map((x) => <span key={x} className={s.chipLive}><i />{x}</span>)}
              <span className={s.chipSep} aria-hidden="true">|</span>
              {SOON_SOURCES.map((x) => <span key={x} className={s.chipSoon}>{x} · coming soon</span>)}
            </div>
          </div>
        </section>

        {/* The ritual */}
        <section className={s.section}>
          <div className={s.wrap}>
            <div className={s.split}>
              <div className={s.splitMedia}>
                <div className={s.photoFlat}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src="/home/hero-leader.jpg" width={1376} height={768} loading="lazy"
                    alt="A technology leader smiling at his desk in a bright, timber-framed office" />
                </div>
                <div className={s.manifesto}>
                  <span className={s.labelSm}>Craft manifesto</span>
                  <p className={s.small}>&ldquo;A good job search is like good coffee: patience, careful extraction, and leaving the bitter grounds behind.&rdquo;</p>
                </div>
              </div>
              <div className={s.splitText}>
                <span className={s.kicker}>02 / Deliberate search</span>
                <h2 className={s.h2}>The ritual of deliberate search. Sifting the signal from the noise.</h2>
                <p className={s.lead}>
                  Senior job hunting has become a flood: the same role from three sites, alerts that barely match, and
                  bots spraying applications in candidates&apos; names.
                </p>
                <p className={s.body}>
                  BrewMyJob turns it into a calm habit. Instead of opening six tabs of alerts between meetings, forward
                  them to your own <span className={s.address}>alerts-…@brewmyjob.com</span> address. By the time you
                  sit down with your coffee, every job is read, scored and sorted.
                </p>
                <div className={s.quote}>
                  <p>&ldquo;Skip the 400-application lottery. Spend your evening on the few roles where you&apos;re strongest.&rdquo;</p>
                </div>
              </div>
            </div>

            <div className={s.versus}>
              <div className={`${s.vCard} ${s.vBad}`}>
                <div className={s.vHead}><span className={s.label}>The current market hazard</span><I name="alert" size={22} /></div>
                <h3 className={s.h3}>400 blind applications can hurt your career</h3>
                <p className={`${s.small} ${s.muted}`}>
                  Spray-and-pray tools apply in your name to stale listings and roles that don&apos;t fit, and hiring
                  teams notice the same name everywhere.
                </p>
                <ul className={s.ticks}>
                  <li><I name="close" />Matching that can stretch your experience to fit the form</li>
                  <li><I name="close" />Automation on job sites that can get accounts restricted</li>
                  <li><I name="close" />Cold applications with no one who knows you</li>
                </ul>
              </div>
              <div className={`${s.vCard} ${s.vGood}`}>
                <div className={s.vHead}><span className={s.label}>The BrewMyJob way</span><I name="coffee" size={22} /></div>
                <h3 className={s.h3}>Your Top matches, best first</h3>
                <p className={`${s.small} ${s.muted}`}>
                  Only the jobs that score at or above your own threshold (85 unless you change it), each with the
                  resume to use and the reasons for its score.
                </p>
                <ul className={s.ticks}>
                  <li><I name="checkCircle" />Every score explained: what matched, and the skills it asks for that your resume doesn&apos;t show</li>
                  <li><I name="checkCircle" />The same job from different sites merged into one</li>
                  <li><I name="checkCircle" />Who you know at each company, from your LinkedIn connections</li>
                </ul>
              </div>
            </div>
          </div>
        </section>

        {/* How it works */}
        <section className={s.sectionLow} id="how">
          <div className={s.wrap}>
            <div className={s.intro}>
              <span className={s.kicker}>How it works</span>
              <h2 className={s.h2}>Four steps from noisy alerts to the right application.</h2>
              <p className={s.lead}>How the alerts you already get become a short list you can act on.</p>
            </div>
            <div className={s.steps}>
              {STEPS.map((st) => (
                <div key={st.n} className={s.step}>
                  <div>
                    <div className={s.stepTop}><span className={s.stepNo}>{st.n}</span><span className={s.stepIcon}><I name={st.icon} size={24} /></span></div>
                    <h3 className={s.h3}>{st.title}</h3>
                    <p className={`${s.small} ${s.muted}`}>{st.text}</p>
                  </div>
                  <div className={s.stepFoot}><span>{st.foot[0]}</span><b>{st.foot[1]}</b></div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Features */}
        <section className={s.section} id="features">
          <div className={s.wrap}>
            <div className={s.introCenter}>
              <span className={s.kicker}>What you get</span>
              <h2 className={s.h2}>Made for senior job searches.</h2>
              <p className={s.lead}>For directors, VPs and senior builders who want fewer, better applications.</p>
            </div>
            <div className={s.bento}>
              <div className={s.b8}>
                <div>
                  <div className={s.bHead}><span className={s.label}>Explainable match</span><span className={s.badge}>Example · 94</span></div>
                  <h3 className={s.h3}>A match score you can argue with</h3>
                  <p className={s.muted}>
                    No black box. Each score is broken down into the things that decide it, and you set how much each
                    one counts.
                  </p>
                </div>
                <div className={s.bars}>
                  {[["Role and seniority", 96], ["Skills the job asks for", 88], ["Location and work model", 100]].map(([k, v]) => (
                    <div key={k}>
                      <div className={s.barTop}><b>{k}</b><span>{v}% fit</span></div>
                      <div className={s.track}><i style={{ width: `${v}%` }} /></div>
                    </div>
                  ))}
                </div>
              </div>

              <div className={s.b4}>
                <div>
                  <div className={s.bHead}><span className={s.label}>Several resumes</span><I name="tune" /></div>
                  <h3 className={s.h3}>One resume per kind of role</h3>
                  <p className={`${s.small} ${s.muted}`}>
                    Keep up to four, say &ldquo;CTO&rdquo; and &ldquo;VP Product&rdquo;. Each has its own match profile,
                    and every job suggests the one that fits it best.
                  </p>
                </div>
                <div className={s.files}>
                  <div className={`${s.file} ${s.fileOn}`}><span><I name="file" size={16} />VP_Engineering.pdf</span><span>Best fit</span></div>
                  <div className={`${s.file} ${s.fileOff}`}><span><I name="file" size={16} />Chief_Architect.pdf</span><span>81%</span></div>
                </div>
              </div>

              <div className={s.b4} id="claim-check">
                <div>
                  <div className={s.bHead}><span className={s.label}>No made-up claims</span><I name="shield" /></div>
                  <h3 className={s.h3}>Missing means missing</h3>
                  <p className={`${s.small} ${s.muted}`}>
                    BrewMyJob never invents experience. If a job asks for a skill your resume doesn&apos;t show, it says so,
                    and you decide whether you really have it.
                  </p>
                </div>
                <div className={s.flag}>
                  <div><I name="alert" size={16} />Asked for, not in your resume</div>
                  <p className={s.labelSm} style={{ textTransform: "none", color: "var(--ink-2)" }}>Example: Kubernetes on bare metal</p>
                </div>
              </div>

              <div className={s.b8}>
                <div>
                  <div className={s.bHead}><span className={s.label}>Warm paths</span><I name="hub" /></div>
                  <h3 className={s.h3}>Warm paths, not cold spam</h3>
                  <p className={s.muted}>
                    Import your LinkedIn connections once. Each job shows who you know at the company, and each day you
                    get a few people worth a message, with a short note ready to send.
                  </p>
                </div>
                <div className={s.people}>
                  {[["Someone you know", "Engineering Director", "1st-degree connection"],
                    ["At the company", "Talent Acquisition Lead", "Recruiter"],
                    ["Today's suggestion", "Head of Platform", "Note ready to copy"]].map(([k, who, how]) => (
                    <div key={k} className={s.person}><span className={s.labelSm}>{k}</span><b>{who}</b><em>{how}</em></div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Comparison */}
        <section className={s.sectionLow} aria-labelledby="compare">
          <div className={s.wrap}>
            <div className={s.introCenter}>
              <span className={s.kicker}>Side by side</span>
              <h2 id="compare" className={s.h2}>Spray-and-pray bots vs. BrewMyJob</h2>
              <p className={s.muted} style={{ maxWidth: 560, margin: "0 auto" }}>
                Why mass auto-apply tools drown your signal, and how a careful filter keeps it strong.
              </p>
            </div>
            <div className={s.tableWrap}>
              <table className={s.table}>
                <thead>
                  <tr><th scope="col">What matters</th><th scope="col">Mass auto-apply bots</th><th scope="col">BrewMyJob</th></tr>
                </thead>
                <tbody>
                  {COMPARE.map(([what, bot, us]) => (
                    <tr key={what}><td>{what}</td><td>{bot}</td><td>{us}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* Pricing */}
        <section className={s.section} id="pricing">
          <div className={s.wrap}>
            <div className={s.introCenter}>
              <span className={s.kicker}>Pricing</span>
              <h2 className={s.h2}>One plan. Pick how long you brew.</h2>
              <p className={s.muted}>
                Everything BrewMyJob does today, for the length of your search. Online payment opens soon; until then
                people join by invite.
              </p>
            </div>
            {/* The plans (user, 2026-11-17; docs/plan-roles-and-plans.md). Same prices as the app's Choose a plan. */}
            <div className={s.prices4} data-testid="home-plans">
              {PLANS.map((p) => (
                <div key={p.label} className={`${s.plan} ${s.planTight} ${p.best ? s.planPro : s.planFree}`}>
                  {p.best ? <span className={s.planRibbon}>Best value</span> : null}
                  <div>
                    <div className={s.planHead}><span className={s.label}>{p.label}</span></div>
                    <div className={s.price}><b>{p.price}</b></div>
                    <p className={s.planNote}>{p.note}</p>
                  </div>
                </div>
              ))}
            </div>
            <div className={s.planIncludes}>
              <span className={s.label}>Every plan includes</span>
              <ul className={s.planList}>
                <li><I name="check" />Your own forwarding address for LinkedIn and Naukri alerts</li>
                <li><I name="check" />Jobs from company career pages and Google</li>
                <li><I name="check" />Up to four resumes, each with its own match profile</li>
                <li><I name="check" />Top matches with every score explained</li>
                <li><I name="check" />Applications tracker and warm paths</li>
              </ul>
              <p className={s.planNote}>
                Payment isn&apos;t open yet: join the waitlist and we&apos;ll send you an invite when your spot opens.
              </p>
              <a className={`${s.btnDark} ${s.planBtn}`} href="#waitlist">Join the waitlist</a>
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" className={s.faqWrap}>
          <div style={{ textAlign: "center" }}>
            <span className={s.kicker}>Questions</span>
            <h2 className={s.h2}>Questions, answered</h2>
          </div>
          <div className={s.faqList}>
            {FAQS.map((f, i) => (
              <details key={f.q} className={s.faq} name="faq" open={i === 0}>
                <summary>{f.q}<I name="chevron" size={20} /></summary>
                <p>{f.a}</p>
              </details>
            ))}
          </div>
        </section>

        {/* Final call to action */}
        <section id="waitlist" className={s.final}>
          <div className={s.wrap}>
            <div className={s.finalBox}>
              <div className={s.finalDots} aria-hidden="true" />
              <div className={s.finalInner}>
                <span className={s.finalPill}><i />Early access</span>
                <h2 className={s.finalTitle}>Reclaim your evenings. Let your morning coffee bring the roles worth your time.</h2>
                <p className={s.finalLead}>
                  Join the waitlist and we&apos;ll email your forwarding address when your spot opens. No credit card.
                </p>
                <WaitlistForm />
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className={s.footer}>
        <div className={s.wrap}>
          <div className={s.footerTop}>
            <div className={s.footerBrand}>
              <div className={s.brand}><CoffeeCup className={s.cup} /><span className={s.mark} aria-hidden="true">BMJ</span><span className={s.wordmark}>BrewMyJob</span></div>
              <p className={`${s.small} ${s.muted}`}>
                Your job alerts, brewed into applications worth sending. No bots, no passwords, no made-up claims.
              </p>
            </div>
            <nav aria-label="Footer" className={s.footerNav}>
              <a href="#how">How it works</a>
              <a href="#features">Features</a>
              <a href="#pricing">Pricing</a>
              <a href="#faq">FAQ</a>
              <Link href="/privacy">Privacy</Link>
              <Link href="/terms">Terms</Link>
              <Link href="/contact">Contact</Link>
              <Link href="/sign-in">Sign in</Link>
            </nav>
          </div>
          <div className={s.footerBottom}>
            <span>Brewed in Bengaluru. © 2026 BrewMyJob.</span>
            <span>You always click Apply.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
