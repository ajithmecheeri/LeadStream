/**
 * FitFirst API client. Types come from src/schema.d.ts, generated from the backend:
 *   pnpm api:gen
 *
 * The access token lives in memory only. The refresh token is an HttpOnly cookie on web
 * (sent automatically to /api/v1/auth/*) and is passed in the body on mobile.
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

export type { components, paths };
export type Schemas = components["schemas"];
export type Me = Schemas["MeOut"];
export type TokenOut = Schemas["TokenOut"];
export type Candidate = Schemas["CandidateOut"];
export type CandidateIn = Schemas["CandidateIn"];
export type SearchProfile = Schemas["SearchProfileOut"];
export type SearchProfileIn = Schemas["SearchProfileIn"];
export type SearchProfilePatch = Schemas["SearchProfilePatch"];
export type ProfilesMeta = Schemas["ProfilesMeta"];
export type NotificationSettings = Schemas["NotificationSettingsIO"];
export type Mail = Schemas["MailOut"];
export type ForwardSender = Schemas["ForwardSenderOut"];
export type InboxMessage = Schemas["InboxMessageOut"];
export type UserJob = Schemas["UserJobOut"];
export type UserJobDetail = Schemas["UserJobDetail"];
export type JobList = Schemas["JobList"];
export type JobStats = Schemas["JobStats"];
export type GoogleSearches = Schemas["GoogleSearchesOut"];
export type FoundJobIn = Schemas["FoundJobIn"];
export type JobQuery = NonNullable<paths["/api/v1/jobs"]["get"]["parameters"]["query"]>;
export type JobStatus = UserJob["status"];
export type JobTab = NonNullable<JobQuery["tab"]>;
export type MatchSummary = Schemas["MatchSummary"];
export type MatchDetail = Schemas["MatchDetail"];
export type ResumeComparison = Schemas["ResumeComparisonOut"];
export type Resume = Schemas["ResumeOut"];
export type ResumeDetail = Schemas["ResumeDetail"];
export type ResumeIn = Schemas["ResumeIn"];
export type CoverLetter = Schemas["CoverLetterOut"];
export type CoverLetterDetail = Schemas["CoverLetterDetail"];
export type DocumentIn = Schemas["DocumentIn"];
export type CandidateDraft = Schemas["CandidateDraft"];
export type MatchingStatus = Schemas["MatchingStatus"];
export type Readiness = Schemas["ReadinessOut"];
export type Blocker = Schemas["BlockerOut"];
export type Answer = Schemas["AnswerOut"];
export type Todo = Schemas["TodoOut"];
export type Application = Schemas["ApplicationOut"];
export type ApplicationDetail = Schemas["ApplicationDetail"];
export type ApplicationList = Schemas["ApplicationList"];
export type ApplicationPatch = Schemas["ApplicationPatch"];
export type ApplicationQuery = NonNullable<paths["/api/v1/applications"]["get"]["parameters"]["query"]>;
export type ApplicationStatus = Application["status"];
export type Contact = Schemas["ContactOut"];
export type ContactIn = Schemas["ContactIn"];
export type ContactList = Schemas["ContactList"];
export type AppSettings = Schemas["AppSettingsIO"];
export type AdminSettings = Schemas["AdminSettingsOut"];
export type Waitlist = Schemas["WaitlistOut"];
export type NetworkSummary = Schemas["NetworkSummary"];
export type ConnectionImport = Schemas["ImportOut"];
export type ConnectionPerson = Schemas["ConnectionOut"];
export type ConnectionList = Schemas["ConnectionList"];
export type WarmPath = Schemas["WarmPath"];
export type JobPeople = Schemas["JobPeople"];
export type Daily = Schemas["Daily"];
export type InviteNote = Schemas["InviteNoteOut"];
export type Suggestion = Schemas["SuggestionOut"];
export type AppliedCompany = Schemas["AppliedCompany"];
export type Outreach = Schemas["OutreachOut"];
export type OutreachDetail = Schemas["OutreachDetail"];
export type OutreachList = Schemas["OutreachList"];
export type OutreachStage = Outreach["stage"];
export type Sources = Schemas["SourcesOut"];
export type RunJob = Schemas["RunJobOut"];
export type CompanyJob = Schemas["CompanyJobOut"];
export type CompanyJobs = Schemas["CompanyJobsOut"];
export type Alerts = Schemas["AlertsOut"];
export type AlertFeed = Schemas["AlertFeedOut"];
export type FollowedCompany = Schemas["CompanyOut"];
export type FoundBoard = Schemas["FoundBoardOut"];
export type Ats = FollowedCompany["ats"];
export type WhatsApp = Schemas["WhatsAppOut"];
export type SentMessage = Schemas["NotificationOut"];
export type Bell = Schemas["BellOut"];
export type BellItem = Schemas["BellItemOut"];
export type Learned = Schemas["LearnedOut"];
export type ContactMessages = Schemas["ContactMessageList"];
export type ApplyProfile = Schemas["ApplyProfileOut"];
export type ApplyProfileIn = Schemas["ApplyProfileIn"];
export type WorkEntry = Schemas["WorkEntry"];
export type EducationEntry = Schemas["EducationEntry"];
export type ApplyKit = Schemas["ApplyKitOut"];
export type PairedBrowser = Schemas["DeviceOut"];
export type NotForMeReason = Schemas["NotForMeIn"]["reason"];
export type Access = Schemas["AccessOut"];
export type Plans = Schemas["PlansOut"];
export type Invite = Schemas["InviteOut"];
export type InviteMade = Schemas["InviteMade"];
export type InviteView = Schemas["InviteView"];
export type SourceJobs = Schemas["SourceJobsOut"];

export interface ApiErrorBody {
  error: { code: string; message: string; details?: { field: string; message: string }[] | null; request_id?: string | null };
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: { field: string; message: string }[] = []) {
    super(message);
  }
  fieldErrors(): Record<string, string> {
    return Object.fromEntries(this.details.map((d) => [d.field, d.message]));
  }
}

export interface ApiOptions {
  baseUrl?: string;
  /** "web" uses the refresh cookie; "mobile" sends the refresh token in the body. */
  client?: "web" | "mobile";
  getRefreshToken?: () => Promise<string | null>;
  onTokens?: (t: TokenOut) => void | Promise<void>;
  onSignedOut?: () => void;
}

export function createApi(opts: ApiOptions = {}) {
  const baseUrl = opts.baseUrl ?? "";
  const clientKind = opts.client ?? "web";
  let accessToken: string | null = null;
  let refreshing: Promise<boolean> | null = null;

  const headers = (): Record<string, string> => (clientKind === "mobile" ? { "X-Client": "mobile" } : {});

  async function refresh(): Promise<boolean> {
    // One refresh at a time: concurrent 401s wait for the same promise.
    refreshing ??= (async () => {
      try {
        const body = clientKind === "mobile" ? { refresh_token: await opts.getRefreshToken?.() } : undefined;
        const res = await fetch(`${baseUrl}/api/v1/auth/refresh`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", ...headers() },
          body: body ? JSON.stringify(body) : undefined,
        });
        if (!res.ok) {
          accessToken = null;
          return false;
        }
        const t = (await res.json()) as TokenOut;
        accessToken = t.access_token;
        await opts.onTokens?.(t);
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshing = null), 0);
      }
    })();
    return refreshing;
  }

  const auth: Middleware = {
    async onRequest({ request }) {
      if (accessToken) request.headers.set("Authorization", `Bearer ${accessToken}`);
      for (const [k, v] of Object.entries(headers())) request.headers.set(k, v);
      return request;
    },
  };

  const http = createClient<paths>({ baseUrl, credentials: "include" });
  http.use(auth);

  /** Run a call; on an expired/missing token refresh once and retry. Throws ApiError on failure. */
  async function call<T>(fn: () => Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
    let r = await fn();
    if (r.response.status === 401 && !r.response.url.includes("/auth/")) {
      if (await refresh()) r = await fn();
      else opts.onSignedOut?.();
    }
    if (r.error !== undefined || !r.response.ok) {
      const e = (r.error as ApiErrorBody | undefined)?.error;
      throw new ApiError(r.response.status, e?.code ?? "http_error", e?.message ?? r.response.statusText, e?.details ?? []);
    }
    return r.data as T;
  }

  function setSession(t: TokenOut) {
    accessToken = t.access_token;
  }

  return {
    http,
    call,
    refresh,
    setSession,
    get signedIn() {
      return accessToken !== null;
    },

    async signUp(body: Schemas["SignupIn"]) {
      const t = await call(() => http.POST("/api/v1/auth/signup", { body }));
      setSession(t);
      await opts.onTokens?.(t);
      return t;
    },
    async signIn(body: Schemas["LoginIn"]) {
      const t = await call(() => http.POST("/api/v1/auth/login", { body }));
      setSession(t);
      await opts.onTokens?.(t);
      return t;
    },
    async signOut() {
      const body = clientKind === "mobile" ? { refresh_token: (await opts.getRefreshToken?.()) ?? null } : undefined;
      await http.POST("/api/v1/auth/logout", { body }).catch(() => undefined);
      accessToken = null;
      opts.onSignedOut?.();
    },

    me: () => call(() => http.GET("/api/v1/me")),
    updateMe: (body: Schemas["MePatch"]) => call(() => http.PATCH("/api/v1/me", { body })),

    candidate: () => call(() => http.GET("/api/v1/candidate")),
    saveCandidate: (body: CandidateIn) => call(() => http.PUT("/api/v1/candidate", { body })),
    saveJobLocations: (job_locations: string[]) =>
      call(() => http.PUT("/api/v1/candidate/job-locations", { body: { job_locations } })),
    /** Read a resume into profile fields for review; nothing is saved. */
    candidateFromResume: (resume_id: string) =>
      call(() => http.POST("/api/v1/candidate/from-resume", { body: { resume_id } })),

    resumes: () => call(() => http.GET("/api/v1/resumes")),
    resume: (id: string) => call(() => http.GET("/api/v1/resumes/{resume_id}", { params: { path: { resume_id: id } } })),
    addResume: (body: ResumeIn) => call(() => http.POST("/api/v1/resumes", { body })),
    updateResume: (id: string, body: Schemas["ResumePatch"]) =>
      call(() => http.PATCH("/api/v1/resumes/{resume_id}", { params: { path: { resume_id: id } }, body })),
    makePrimaryResume: (id: string) =>
      call(() => http.POST("/api/v1/resumes/{resume_id}/primary", { params: { path: { resume_id: id } } })),
    deleteResume: (id: string) =>
      call(() => http.DELETE("/api/v1/resumes/{resume_id}", { params: { path: { resume_id: id } } })),
    /** A new version of the resume: keeps its label, primary flag and Skill Match profile. */
    replaceResume: (id: string, body: DocumentIn) =>
      call(() => http.POST("/api/v1/resumes/{resume_id}/replace", { params: { path: { resume_id: id } }, body })),
    resumeFile: (id: string) =>
      call(() => http.GET("/api/v1/resumes/{resume_id}/file", { params: { path: { resume_id: id } }, parseAs: "blob" })) as Promise<Blob>,

    coverLetters: () => call(() => http.GET("/api/v1/cover-letters")),
    coverLetter: (id: string) =>
      call(() => http.GET("/api/v1/cover-letters/{letter_id}", { params: { path: { letter_id: id } } })),
    addCoverLetter: (body: DocumentIn) => call(() => http.POST("/api/v1/cover-letters", { body })),
    updateCoverLetter: (id: string, body: Schemas["CoverLetterPatch"]) =>
      call(() => http.PATCH("/api/v1/cover-letters/{letter_id}", { params: { path: { letter_id: id } }, body })),
    makeDefaultCoverLetter: (id: string) =>
      call(() => http.POST("/api/v1/cover-letters/{letter_id}/default", { params: { path: { letter_id: id } } })),
    deleteCoverLetter: (id: string) =>
      call(() => http.DELETE("/api/v1/cover-letters/{letter_id}", { params: { path: { letter_id: id } } })),
    coverLetterFile: (id: string) =>
      call(() => http.GET("/api/v1/cover-letters/{letter_id}/file", { params: { path: { letter_id: id } }, parseAs: "blob" })) as Promise<Blob>,

    answers: () => call(() => http.GET("/api/v1/answers")),
    saveAnswer: (key: string, answer: string, version?: number | null) =>
      call(() => http.PUT("/api/v1/answers/{key}", { params: { path: { key } }, body: { answer, version: version ?? null } })),
    addAnswer: (question: string, answer: string) => call(() => http.POST("/api/v1/answers", { body: { question, answer } })),
    deleteAnswer: (key: string) => call(() => http.DELETE("/api/v1/answers/{key}", { params: { path: { key } } })),
    readiness: (id: string) =>
      call(() => http.GET("/api/v1/jobs/{user_job_id}/readiness", { params: { path: { user_job_id: id } } })),
    /** Answer a question blocker (saved to the answer bank) or accept a gap. */
    resolveBlocker: (id: string, key: string, answer?: string) =>
      call(() =>
        http.POST("/api/v1/jobs/{user_job_id}/blockers/{key}/resolve", {
          params: { path: { user_job_id: id, key } },
          body: { answer: answer ?? null },
        }),
      ),

    matchingStatus: () => call(() => http.GET("/api/v1/matching/status")),
    rescore: () => call(() => http.POST("/api/v1/matching/rescore")),

    profilesMeta: () => call(() => http.GET("/api/v1/profiles/meta")),
    profiles: () => call(() => http.GET("/api/v1/profiles")),
    profile: (id: string) => call(() => http.GET("/api/v1/profiles/{profile_id}", { params: { path: { profile_id: id } } })),
    createProfile: (body: SearchProfileIn) => call(() => http.POST("/api/v1/profiles", { body })),
    updateProfile: (id: string, body: SearchProfilePatch) =>
      call(() => http.PATCH("/api/v1/profiles/{profile_id}", { params: { path: { profile_id: id } }, body })),
    deleteProfile: (id: string) =>
      call(() => http.DELETE("/api/v1/profiles/{profile_id}", { params: { path: { profile_id: id } } })),
    /** Read the resume's skills again; skills you added stay. */
    refreshProfile: (id: string) =>
      call(() => http.POST("/api/v1/profiles/{profile_id}/refresh", { params: { path: { profile_id: id } } })),
    addProfileSkill: (id: string, skill: string) =>
      call(() => http.POST("/api/v1/profiles/{profile_id}/skills", { params: { path: { profile_id: id } }, body: { skill } })),

    notificationSettings: () => call(() => http.GET("/api/v1/settings/notifications")),
    saveNotificationSettings: (body: NotificationSettings) =>
      call(() => http.PUT("/api/v1/settings/notifications", { body })),
    whatsapp: () => call(() => http.GET("/api/v1/notifications/whatsapp")),
    setWhatsAppNumber: (number: string) =>
      call(() => http.POST("/api/v1/notifications/whatsapp/number", { body: { number } })),
    sendWhatsAppCode: () => call(() => http.POST("/api/v1/notifications/whatsapp/code")),
    verifyWhatsApp: (code: string) => call(() => http.POST("/api/v1/notifications/whatsapp/verify", { body: { code } })),
    setWhatsAppJobs: (jobs: boolean) => call(() => http.PATCH("/api/v1/notifications/whatsapp", { body: { jobs } })),
    testWhatsApp: () => call(() => http.POST("/api/v1/notifications/whatsapp/test")),
    removeWhatsApp: () => call(() => http.DELETE("/api/v1/notifications/whatsapp")),
    /** What needs attention: new top matches, possible duplicates, follow-ups due, jobs that may have expired. */
    bell: () => call(() => http.GET("/api/v1/notifications/bell")),
    /** The bell was opened: its items count as read. */
    bellSeen: () => call(() => http.POST("/api/v1/notifications/bell/seen")),
    /** Kinds of job the user said weren't for them: these score at most 40. */
    learnedPreferences: () => call(() => http.GET("/api/v1/preferences/learned")),
    forgetPreference: (id: string) =>
      call(() => http.DELETE("/api/v1/preferences/learned/{pref_id}", { params: { path: { pref_id: id } } })),

    mail: () => call(() => http.GET("/api/v1/mail")),
    rotateMailAddress: () => call(() => http.POST("/api/v1/mail/address/rotate")),
    addForwardSender: (address: string) => call(() => http.POST("/api/v1/mail/senders", { body: { address } })),
    removeForwardSender: (id: string) =>
      call(() => http.DELETE("/api/v1/mail/senders/{sender_id}", { params: { path: { sender_id: id } } })),
    inbox: (query?: { limit?: number; before?: string }) =>
      call(() => http.GET("/api/v1/inbox/messages", { params: { query } })),
    /** Local development only (ENV=local): deliver a saved .eml file as if it had been forwarded. */
    uploadEmail: (raw_mime_base64: string) => call(() => http.POST("/api/v1/inbox/upload", { body: { raw_mime_base64 } })),

    jobs: (query?: JobQuery) => call(() => http.GET("/api/v1/jobs", { params: { query } })),
    jobStats: () => call(() => http.GET("/api/v1/jobs/stats")),
    job: (id: string) => call(() => http.GET("/api/v1/jobs/{user_job_id}", { params: { path: { user_job_id: id } } })),
    setJobStatus: (id: string, status: JobStatus, version: number) =>
      call(() => http.PATCH("/api/v1/jobs/{user_job_id}", { params: { path: { user_job_id: id } }, body: { status, version } })),
    pasteDescription: (id: string, text: string, version: number) =>
      call(() =>
        http.POST("/api/v1/jobs/{user_job_id}/description", { params: { path: { user_job_id: id } }, body: { text, version } }),
      ),
    /** Ready-made Google searches for LinkedIn, Naukri and Foundit job pages (you run them in your browser). */
    googleSearches: () => call(() => http.GET("/api/v1/jobs/google-searches")),
    /** Add a job you found on LinkedIn, Naukri or Foundit; BrewMyJob never opens the link. */
    addFoundJob: (body: Schemas["FoundJobIn"]) => call(() => http.POST("/api/v1/jobs/found", { body })),
    /** You checked the posting: it's still open (clears "May have expired"). */
    stillOpen: (id: string) =>
      call(() => http.POST("/api/v1/jobs/{user_job_id}/still-open", { params: { path: { user_job_id: id } } })),
    /** Add a skill you really have to your profile; the job is re-scored. */
    addSkill: (id: string, skill: string) =>
      call(() => http.POST("/api/v1/jobs/{user_job_id}/skills", { params: { path: { user_job_id: id } }, body: { skill } })),
    /** The job isn't a fit because of this gap: it is re-scored (at most 40) and moves to Other jobs. */
    notAFit: (id: string, gap: Schemas["NotAFitIn"]["gap"]) =>
      call(() => http.POST("/api/v1/jobs/{user_job_id}/not-a-fit", { params: { path: { user_job_id: id } }, body: { gap } })),
    /** Not for me, with a reason: the job is ignored, and a reason about its company, city, field or level is learned. */
    notForMe: (id: string, body: Schemas["NotForMeIn"]) =>
      call(() => http.POST("/api/v1/jobs/{user_job_id}/not-for-me", { params: { path: { user_job_id: id } }, body })),
    /** Take back "not a fit": the job is re-scored on its merits. */
    undoNotAFit: (id: string) =>
      call(() => http.DELETE("/api/v1/jobs/{user_job_id}/not-a-fit", { params: { path: { user_job_id: id } } })),
    /** Same job (merged into one) or different jobs (kept apart, never flagged again) for a possible duplicate. */
    answerDuplicate: (id: string, pairId: string, same: boolean) =>
      call(() =>
        http.POST("/api/v1/jobs/{user_job_id}/duplicates/{pair_id}", {
          params: { path: { user_job_id: id, pair_id: pairId } },
          body: { same },
        }),
      ),
    /** Another resume's breakdown on this job, to compare with the suggested one. Nothing is saved. */
    compareResume: (id: string, resumeId: string) =>
      call(() => http.GET("/api/v1/jobs/{user_job_id}/resumes/{resume_id}", { params: { path: { user_job_id: id, resume_id: resumeId } } })),

    contacts: (id: string) =>
      call(() => http.GET("/api/v1/jobs/{user_job_id}/contacts", { params: { path: { user_job_id: id } } })),
    addContact: (id: string, body: ContactIn) =>
      call(() => http.POST("/api/v1/jobs/{user_job_id}/contacts", { params: { path: { user_job_id: id } }, body })),
    updateContact: (id: string, contactId: string, body: Schemas["ContactPatch"]) =>
      call(() =>
        http.PUT("/api/v1/jobs/{user_job_id}/contacts/{contact_id}", {
          params: { path: { user_job_id: id, contact_id: contactId } },
          body,
        }),
      ),
    deleteContact: (id: string, contactId: string) =>
      call(() =>
        http.DELETE("/api/v1/jobs/{user_job_id}/contacts/{contact_id}", {
          params: { path: { user_job_id: id, contact_id: contactId } },
        }),
      ),

    applications: (query?: ApplicationQuery) => call(() => http.GET("/api/v1/applications", { params: { query } })),
    application: (id: string) =>
      call(() => http.GET("/api/v1/applications/{application_id}", { params: { path: { application_id: id } } })),
    updateApplication: (id: string, body: ApplicationPatch) =>
      call(() => http.PATCH("/api/v1/applications/{application_id}", { params: { path: { application_id: id } }, body })),
    addApplicationNote: (id: string, text: string) =>
      call(() =>
        http.POST("/api/v1/applications/{application_id}/notes", { params: { path: { application_id: id } }, body: { text } }),
      ),

    /** Upload LinkedIn's Connections export (CSV or ZIP), base64. */
    importConnections: (body: Schemas["ImportIn"]) => call(() => http.POST("/api/v1/network/imports", { body })),
    networkSummary: () => call(() => http.GET("/api/v1/network/summary")),
    connections: (query?: { q?: string; limit?: number; offset?: number }) =>
      call(() => http.GET("/api/v1/network/connections", { params: { query } })),
    deleteConnections: () => call(() => http.DELETE("/api/v1/network/connections")),
    warmPaths: () => call(() => http.GET("/api/v1/network/warm-paths")),
    appliedCompanies: () => call(() => http.GET("/api/v1/network/applied")),
    jobPeople: (id: string) => call(() => http.GET("/api/v1/jobs/{user_job_id}/people", { params: { path: { user_job_id: id } } })),
    daily: (query?: { date?: string; regenerate?: boolean }) => call(() => http.GET("/api/v1/network/daily", { params: { query } })),
    inviteNote: () => call(() => http.GET("/api/v1/network/invite-note")),
    setInviteNote: (note: string | null) => call(() => http.PUT("/api/v1/network/invite-note", { body: { note } })),
    markSuggestion: (id: string, body: Schemas["MarkIn"]) =>
      call(() => http.POST("/api/v1/network/suggestions/{suggestion_id}/mark", { params: { path: { suggestion_id: id } }, body })),
    outreachList: (stage?: OutreachStage) => call(() => http.GET("/api/v1/network/outreach", { params: { query: stage ? { stage } : {} } })),
    outreach: (id: string) => call(() => http.GET("/api/v1/network/outreach/{outreach_id}", { params: { path: { outreach_id: id } } })),
    addOutreach: (body: Schemas["OutreachIn"]) => call(() => http.POST("/api/v1/network/outreach", { body })),
    updateOutreach: (id: string, body: Schemas["OutreachPatch"]) =>
      call(() => http.PATCH("/api/v1/network/outreach/{outreach_id}", { params: { path: { outreach_id: id } }, body })),

    appSettings: () => call(() => http.GET("/api/v1/app-settings")),
    adminSettings: () => call(() => http.GET("/api/v1/admin/settings")),
    saveAdminSettings: (body: AppSettings) => call(() => http.PUT("/api/v1/admin/settings", { body })),

    /** Job sources (milestone 9): company career feeds and Adzuna. */
    sources: () => call(() => http.GET("/api/v1/sources")),
    lookupCompany: (query: string) => call(() => http.POST("/api/v1/sources/lookup", { body: { query } })),
    followCompany: (body: Schemas["CompanyIn"]) => call(() => http.POST("/api/v1/sources/companies", { body })),
    followSuggested: (boards: string[]) =>
      call(() => http.POST("/api/v1/sources/companies/suggested", { body: { boards } })),
    unfollowCompany: (id: string) =>
      call(() => http.DELETE("/api/v1/sources/companies/{employer_id}", { params: { path: { employer_id: id } } })),
    checkSources: () => call(() => http.POST("/api/v1/sources/check")),
    lastRunJobs: () => call(() => http.GET("/api/v1/sources/last-run/jobs")),
    addRunJob: (jobId: string) =>
      call(() => http.POST("/api/v1/sources/last-run/jobs/{job_id}", { params: { path: { job_id: jobId } } })),
    /** Every open India job at a company you follow, kept or not (user, 2026-11-16). */
    companyJobs: (employerId: string) =>
      call(() => http.GET("/api/v1/sources/companies/{employer_id}/jobs", { params: { path: { employer_id: employerId } } })),
    addCompanyJob: (employerId: string, jobId: string) =>
      call(() =>
        http.POST("/api/v1/sources/companies/{employer_id}/jobs/{job_id}", {
          params: { path: { employer_id: employerId, job_id: jobId } },
        }),
      ),
    /** Google Alerts by RSS (discovery plan decision 10). */
    alerts: () => call(() => http.GET("/api/v1/alerts")),
    addAlertFeed: (feed_url: string) => call(() => http.POST("/api/v1/alerts", { body: { feed_url } })),
    setAlertRoles: (roles: string[]) => call(() => http.PUT("/api/v1/alerts/roles", { body: { roles } })),
    removeAlertFeed: (id: string) =>
      call(() => http.DELETE("/api/v1/alerts/{feed_id}", { params: { path: { feed_id: id } } })),

    joinWaitlist: (body: Schemas["WaitlistIn"]) => call(() => http.POST("/api/v1/waitlist", { body })),
    contact: (body: Schemas["ContactMessageIn"]) => call(() => http.POST("/api/v1/contact", { body })),

    /** What application forms ask for beyond the profile (milestone 14.1). Version 0 until the first save. */
    applyProfile: () => call(() => http.GET("/api/v1/apply-profile")),
    saveApplyProfile: (body: Schemas["ApplyProfileIn"]) => call(() => http.PUT("/api/v1/apply-profile", { body })),
    /** Phone, city, work history and education read from a resume, to review. Nothing is saved. */
    applyDraft: (resumeId: string) =>
      call(() => http.POST("/api/v1/apply-profile/from-resume", { body: { resume_id: resumeId } })),
    /** Everything a job's application form is likely to ask, to copy field by field (14.2). */
    /** Browser extension (14.3): a one-time pairing code, the paired browsers, and unpairing one. */
    extensionPairingCode: () => call(() => http.POST("/api/v1/extension/pairing-code")),
    extensionDevices: () => call(() => http.GET("/api/v1/extension/devices")),
    unpairExtension: (id: string) =>
      call(() => http.DELETE("/api/v1/extension/devices/{device_id}", { params: { path: { device_id: id } } })),
    applyKit: (id: string) =>
      call(() => http.GET("/api/v1/jobs/{user_job_id}/apply-kit", { params: { path: { user_job_id: id } } })),
    contactMessages: (offset = 0) => call(() => http.GET("/api/v1/admin/contact", { params: { query: { offset } } })),
    waitlist: (offset = 0) => call(() => http.GET("/api/v1/admin/waitlist", { params: { query: { offset } } })),

    /** Plans, access and invites (user, 2026-11-17; docs/plan-roles-and-plans.md). */
    plans: () => call(() => http.GET("/api/v1/plans")),
    viewInvite: (token: string) => call(() => http.GET("/api/v1/invites/view", { params: { query: { token } } })),
    acceptInvite: (token: string) => call(() => http.POST("/api/v1/invites/accept", { body: { token } })),
    invites: () => call(() => http.GET("/api/v1/admin/invites")),
    makeInvite: (body: Schemas["InviteIn"]) => call(() => http.POST("/api/v1/admin/invites", { body })),
    revokeInvite: (id: string) =>
      call(() => http.DELETE("/api/v1/admin/invites/{invite_id}", { params: { path: { invite_id: id } } })),
    /** Jobs -> From sources: every job the job sources brought you, the last run and older. */
    sourceJobs: () => call(() => http.GET("/api/v1/sources/jobs")),
    addSourceJob: (jobId: string) =>
      call(() => http.POST("/api/v1/sources/jobs/{job_id}", { params: { path: { job_id: jobId } } })),
  };
}

export type Api = ReturnType<typeof createApi>;
