// BrewMyJob extension: the rules that decide what a form field is (milestone 14). No DOM here, so the web app's
// tests can run them (apps/web/lib/extension-match.test.ts). Loaded as a plain script before fill.js; it sets
// globalThis.BrewMyJobMatch.
(() => {
  // Job portals: never filled, not even on a click (CLAUDE.md). Keep in step with
  // backend/app/modules/extension/service.py: BLOCKED_DOMAINS.
  const BLOCKED = [
    "linkedin.com", "naukri.com", "indeed.com", "indeed.co.in", "foundit.in", "monsterindia.com", "glassdoor.com",
    "glassdoor.co.in", "iimjobs.com", "hirist.tech", "hirist.com", "instahyre.com", "shine.com", "timesjobs.com",
    "apna.co", "cutshort.io", "wellfound.com", "angel.co",
  ];

  /** @param {string} host */
  function isBlocked(host) {
    const h = (host || "").toLowerCase();
    return BLOCKED.some((d) => h === d || h.endsWith("." + d));
  }

  /** Which application system a page belongs to. @param {string} host */
  function system(host) {
    const h = (host || "").toLowerCase();
    if (h.endsWith("myworkdayjobs.com") || h.endsWith("myworkdaysite.com")) return "workday";
    if (h.endsWith("greenhouse.io")) return "greenhouse";
    if (h.endsWith("lever.co")) return "lever";
    if (h.endsWith("ashbyhq.com")) return "ashby";
    if (h.endsWith("smartrecruiters.com")) return "smartrecruiters";
    return "other";
  }

  // Questions BrewMyJob never answers: the user does (voluntary self-identification, and anything sensitive).
  const SENSITIVE = /gender|sex\b|ethnic|race\b|racial|veteran|disabilit|sexual orientation|pronoun|caste|religio|date of birth|\bdob\b|\bage\b|marital|nationality|passport|aadhaar|\bpan\b|social security|\bssn\b|criminal|convict|signature|password/i;

  // Voluntary self-identification the user answered in the answer bank (user, 2026-11-16): filled only from the
  // answer saved for that exact question, never by a loose match, and only when the label asks nothing else
  // sensitive ("Race/Ethnicity", "Gender and sexual orientation" stay the user's).
  const SELF_ID = [
    ["gender", /\bgender\b/i],
    ["ethnicity", /\bethnicity\b|\bethnic (group|origin|background)\b/i],
  ];
  /** The self-identification key a label asks for, or null. @param {string} label */
  function selfId(label) {
    const t = (label || "").replace(/\s+/g, " ").trim();
    for (const [key, re] of SELF_ID) if (re.test(t) && !SENSITIVE.test(t.replace(re, " "))) return key;
    return null;
  }

  // Label → field key, first match wins: more specific rules first.
  const RULES = [
    // Yes/No questions on company forms (2026-11-15). First: their long wording names a country or a location,
    // which the address rules below would otherwise take.
    ["sponsorship", /sponsor/i],
    ["legally_authorized", /(legally )?(authori[sz]ed|eligible|entitled|permitted) to work/i],
    ["non_compete", /non-?compet|non-?solicit/i],
    ["confidentiality", /confidential|proprietary information/i],
    ["under_18", /younger than 18|under (the age of )?18\b/i],
    ["family_government", /(family|relative|spouse|business partner)[^?]*(government|public official)/i],
    ["uniformed_forces", /uniformed forces|armed forces|defen[cs]e (forces|services)|paramilitary|served in the (indian )?(army|navy|air force)/i],
    ["former_government", /government employee|(government|public|civil) (servant|official)|civil service|military/i],
    ["work_location", /willing to work (in|at|from) (that|the|this|our) (location|office)|specific location/i],
    ["first_name", /\b(first|given|fore)\s*name\b|^first$/i],
    ["last_name", /\b(last|family|sur)\s*name\b|^surname$|^last$/i],
    ["current_company", /current (company|employer|organi[sz]ation)|present (company|employer)/i],
    ["current_title", /current (job )?(title|role|position|designation)/i],
    ["full_name", /^(full\s*|legal\s*|your\s*)?name\b|^name\s*\*?$/i],
    ["email", /e-?mail/i],
    ["phone", /phone|mobile|contact number|cell/i],
    ["address_line2", /address\s*(line)?\s*2|apartment|suite/i],
    ["address_line1", /address\s*(line)?\s*1|street|^address\b|^current address/i],
    ["postal_code", /postal|zip|pin\s*code|postcode/i],
    ["city", /\bcity\b|\btown\b/i],
    ["state", /\bstate\b|province/i],
    ["country", /\bcountry\b/i],
    ["linkedin", /linked\s*in/i],
    ["website", /website|portfolio|personal (site|url)|github|blog|other url/i],
    ["years_experience", /years of (total |relevant )?experience|total experience|experience \(in years\)|how many years/i],
    ["notice_period", /notice period|when can you (start|join)|earliest (start|joining)/i],
    ["expected_ctc", /expected (ctc|salary|compensation|pay)|salary expectation|desired (salary|compensation)/i],
    ["current_ctc", /current (ctc|salary|compensation|pay)/i],
    ["work_authorization", /work authori[sz]ation|right to work|visa status/i],
    ["relocation", /relocat/i],
    ["skills", /^skills\b|key skills/i],
  ];

  /** The field key for a label, or null. @param {string} label */
  function keyFor(label) {
    const t = (label || "").replace(/\s+/g, " ").trim();
    if (!t) return null;
    const own = selfId(t);
    if (own) return own;
    if (SENSITIVE.test(t)) return null;
    for (const [key, re] of RULES) if (re.test(t)) return key;
    return null;
  }

  /** @param {string} label */
  function isSensitive(label) {
    return SENSITIVE.test(label || "") && !selfId(label);
  }

  const STOP = new Set(["the", "a", "an", "of", "to", "you", "your", "do", "are", "is", "in", "for", "what", "please", "with"]);
  /** @param {string} s */
  function words(s) {
    return new Set((s || "").toLowerCase().replace(/[^a-z0-9 ]+/g, " ").split(" ").filter((w) => w && !STOP.has(w)));
  }

  /** An answer-bank answer whose question means this label (most words shared), or null.
   * @param {string} label @param {{key: string, question: string, answer: string}[]} answers */
  function answerFor(label, answers) {
    const key = keyFor(label);
    if (key) {
      const byKey = answers.find((a) => a.key === key);
      if (byKey) return byKey.answer;
    }
    if (selfId(label)) return null; // only the answer saved for that question
    const lw = words(label);
    if (lw.size < 2 || isSensitive(label)) return null;
    let best = null;
    let bestScore = 0;
    for (const a of answers) {
      const qw = words(a.question);
      const shared = [...lw].filter((w) => qw.has(w)).length;
      const score = shared / new Set([...lw, ...qw]).size;
      if (score > bestScore) [best, bestScore] = [a.answer, score];
    }
    return bestScore >= 0.6 ? best : null;
  }

  /** The option that means this value: exact text first, then starts-with, then contains.
   * @param {{text: string, value: string}[]} options @param {string} value */
  function pickOption(options, value) {
    const v = (value || "").trim().toLowerCase();
    if (!v) return null;
    const norm = (/** @type {string} */ s) => (s || "").trim().toLowerCase();
    return (
      options.find((o) => norm(o.text) === v || norm(o.value) === v) ||
      options.find((o) => norm(o.text).startsWith(v)) ||
      options.find((o) => v.length >= 4 && norm(o.text).includes(v)) ||
      null
    );
  }

  /** "resume" or "cover_letter" for a file field's label, else null. @param {string} label */
  function fileKind(label) {
    const t = (label || "").toLowerCase();
    if (/cover\s*letter/.test(t)) return "cover_letter";
    if (/resume|résumé|\bcv\b|curriculum/.test(t)) return "resume";
    return null;
  }

  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

  globalThis.BrewMyJobMatch = { BLOCKED, isBlocked, system, keyFor, isSensitive, answerFor, pickOption, fileKind, MONTHS };
})();
