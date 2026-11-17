"""Skills by meaning, not spelling: matching a profile's key skills to a job, and the skills a job asks for.

Key skills are often broad phrases ("Cloud and infrastructure management", "AI & GenAI", "Enterprise
Architecture"), so a one-to-one match would rarely hit. A key skill matches a job:
  - fully (1.0) when the phrase, one of its parts ("cloud", "infrastructure management": split on and / & / ,),
    a synonym of either, or a narrower term ("AWS" for "cloud") appears in the job;
  - partly (RELATED) when only a part's main word does: "Enterprise Architecture" and a job asking for
    "architecture". Generic words ("management", "enterprise", "strategy") are never main words.

The skills a job asks for are the ones its listing names, the VOCABULARY terms its text mentions, and the user's
key skills it mentions. Whether a resume shows one is a full match only: "DevOps" doesn't cover "DevSecOps".
"""

import re

from app.modules.matching import taxonomy as tx

RELATED = 0.75  # credit for a key skill matched only through a part's main word

# Spellings of the same skill.
SAME: list[list[str]] = [
    ["ai", "artificial intelligence"],
    ["genai", "gen ai", "gen-ai", "generative ai", "llm", "llms", "large language models"],
    ["ml", "machine learning"],
    ["kubernetes", "k8s"],
    ["presales", "pre-sales", "pre sales", "solution consulting", "solutioning"],
    ["ci/cd", "cicd", "ci cd", "continuous integration", "continuous delivery"],
    ["devsecops", "dev sec ops"],
    ["p&l", "profit and loss"],
    ["pci compliance", "pci dss", "pci-dss", "pci"],
    ["budgeting", "budget", "budgets"],
    ["stakeholder management", "stakeholders", "stakeholder"],
    ["roadmap", "roadmaps"],
    ["monetization", "monetisation"],
    ["golang", "go lang"],
    ["node.js", "nodejs", "node js"],
    ["gcp", "google cloud"],
    ["data engineering", "data pipelines", "etl"],
    ["cybersecurity", "cyber security", "information security", "infosec"],
    ["people management", "people leadership", "managing teams"],
    ["sre", "site reliability"],
    [
        "incident management",
        "incident response",
        "post-incident",
        "on-call",
        "root cause analysis",
        "root-cause analysis",
        "rca",
        "rcas",
    ],
    ["finops", "cloud cost optimization", "cloud cost management"],
    ["multi-cloud", "multi cloud", "multicloud"],
    ["infrastructure as code", "infrastructure as a code", "iac"],
    ["release management", "change and release management", "release engineering"],
    ["slos", "slo", "slis", "service level objectives", "error budgets"],
    ["performance engineering", "performance optimization", "performance tuning"],
    [
        "single-page apps",
        "spa frameworks",
        "spa framework",
        "single-page applications",
        "single page applications",
    ],
    ["hpc", "high-performance computing", "high performance computing"],
    ["networking protocols", "network protocols", "tcp/ip"],
    ["databases", "database management systems", "database management", "dbms"],
    ["full-stack", "full stack", "fullstack"],
    # Trading and capital markets (user feedback 2026-11-14: a Caxton trading-systems job showed no trading gap).
    [
        "trading systems",
        "trading system",
        "trading platform",
        "trading platforms",
        "trading technology",
        "electronic trading",
        "algorithmic trading",
        "algo trading",
    ],
    ["fix protocol", "fix connectivity", "fix engine", "fix messaging", "fix api", "quickfix"],
    ["order management systems", "order management system", "oms"],
    ["trade lifecycle", "order-to-trade lifecycle", "trade life cycle", "pre-trade", "post-trade"],
    ["market data", "market data feeds", "real-time market data"],
    ["bloomberg api", "bloomberg apis", "b-pipe", "bpipe", "blpapi", "bloomberg terminal"],
    ["capital markets", "investment banking", "hedge fund", "hedge funds", "buy-side", "sell-side"],
    # AI research and AI security (user feedback 2026-11-16: a CTO AI Security job asking for model forensics,
    # interpretability and unlearning scored 85 with no gaps).
    ["fine-tuning", "fine tuning", "finetuning", "lora", "qlora", "peft"],
    ["foundation models", "foundation model"],
    [
        "interpretability",
        "model interpretability",
        "mechanistic interpretability",
        "explainability",
        "explainable ai",
        "model internals",
    ],
    [
        "ai security",
        "ml security",
        "model security",
        "llm security",
        "adversarial ml",
        "adversarial machine learning",
        "ai red teaming",
        "secure ai",
    ],
    ["model forensics", "ai forensics", "model fingerprinting", "backdoor detection", "forensics"],
    ["machine unlearning", "model unlearning", "unlearning"],
    ["research publications", "publications", "peer-reviewed", "published research"],
    ["patents", "patent", "ip generation", "intellectual property generation"],
]
# A broad skill and narrower ones: a job asking for a narrower one asks for the broad one too.
NARROWER: dict[str, list[str]] = {
    "cloud": ["aws", "azure", "gcp", "cloud native", "cloud-native", "multi-cloud"],
    "architecture": [
        "architect",
        "architects",
        "solution architecture",
        "enterprise architecture",
        "system design",
    ],
    "security": ["cybersecurity", "devsecops", "appsec", "application security", "zero trust", "iam"],
    "compliance": ["regulatory", "soc2", "soc 2", "iso 27001", "gdpr", "pci dss", "hipaa"],
    "ai": ["genai", "ml", "deep learning", "nlp", "computer vision", "agentic ai"],
    "infrastructure": ["infra", "devops", "sre", "platform engineering"],
    "devops": ["ci/cd", "devsecops"],
    "data": ["data engineering", "data platform", "analytics", "big data", "data science", "data warehouse"],
    "talent management": ["talent acquisition", "hiring", "recruiting"],
    "project management": ["program management", "delivery management", "pmp"],
    "budgeting": ["p&l", "cost management", "financial planning"],
}
# Never a main word on their own: they qualify a skill rather than name one.
GENERIC = frozenset(
    "management manager managing development developing enterprise strategy strategic team teams driven "
    "data-driven decision decision-making making business transformation solution solutions consulting vision "
    "skills skill and of the for in with to financials performance based people excellence operations data "
    "leadership-level senior advanced "
    # Words any engineering listing uses (2026-11-13: a Caxton trading-systems job "asked for" AI/LLM Integration
    # through "integration testing", Microservices & Full-Stack Systems through "systems").
    "integration integrations system systems platform platforms ownership owner deployment deployments "
    "compliance tool tools".split()
)
# Skills worth finding in a job description (shown as written here).
VOCABULARY: list[str] = [
    "AWS",
    "Azure",
    "GCP",
    "Kubernetes",
    "Docker",
    "Terraform",
    "Microservices",
    "Serverless",
    "DevOps",
    "DevSecOps",
    "CI/CD",
    "SRE",
    "Observability",
    "Incident management",
    "SLOs",
    "Capacity planning",
    "Chaos engineering",
    "Performance engineering",
    "Infrastructure as code",
    "Release management",
    "FinOps",
    "Multi-cloud",
    "Prometheus",
    "Grafana",
    "Datadog",
    "Splunk",
    "Kafka",
    "Event-driven architecture",
    "Distributed systems",
    "Full-stack",
    "Single-page apps",
    "HPC",
    "Networking protocols",
    "Databases",
    "Data architecture",
    "Design patterns",
    "Java",
    "Python",
    "Golang",
    "Rust",
    "Kotlin",
    "Scala",
    "C#",
    ".NET",
    "C++",
    "JavaScript",
    "TypeScript",
    "React",
    "Angular",
    "Node.js",
    "Spring Boot",
    "SQL",
    "NoSQL",
    "MongoDB",
    "PostgreSQL",
    "Spark",
    "Snowflake",
    "Databricks",
    "Airflow",
    "Data engineering",
    "Data science",
    "Analytics",
    "Machine learning",
    "Deep learning",
    "NLP",
    "Computer vision",
    "GenAI",
    "Agentic AI",
    "RAG",
    "MLOps",
    "Enterprise architecture",
    "Solution architecture",
    "TOGAF",
    "System design",
    "API design",
    "Cybersecurity",
    "Zero trust",
    "IAM",
    "SOC2",
    "ISO 27001",
    "GDPR",
    "PCI DSS",
    "Agile",
    "Scrum",
    "SAFe",
    "ITIL",
    "PMP",
    "Program management",
    "Product management",
    "Roadmap",
    "Presales",
    "P&L",
    "Budgeting",
    "Stakeholder management",
    "Vendor management",
    "M&A",
    "Salesforce",
    "SAP",
    "ServiceNow",
    "ERP",
    "CRM",
    "Blockchain",
    "IoT",
    "Embedded",
    "Mobile",
    "SaaS",
    "Platform engineering",
    "Digital transformation",
    "Cloud migration",
    "Modernization",
    "Trading systems",
    "FIX protocol",
    "Order management systems",
    "Trade lifecycle",
    "Market data",
    "Bloomberg API",
    "Capital markets",
    "Fine-tuning",
    "Foundation models",
    "Interpretability",
    "AI security",
    "Model forensics",
    "Machine unlearning",
    "Research publications",
    "Patents",
]

# Vocabulary terms that are also plain words, found only where they mean the skill: "safe and explainable AI"
# isn't SAFe, and "go" is Go only in a list of languages ("Go, Java, Python").
_IN_CONTEXT: dict[str, re.Pattern[str]] = {
    "golang": re.compile(r"golang|go lang|(?:^|[,(/:]|\blike|\bin)\s*go\s*(?=[,)/])", re.M),
    "safe": re.compile(
        r"scaled agile|\bsafe\s*(?:®|agile|framework|\d)|\(safe\)|agile\s*(?:/|and|or|,)\s*safe\b"
    ),
}
# Where a description names fields of study ("Bachelor's degree in ... Statistics, Analytics, Mathematics"): the
# rest of that sentence lists subjects, not skills the job asks for.
_DEGREE = re.compile(r"\b(?:bachelor|master|degree)(?:['’]?s)?(?:\s+degree)?\s+in\b[^\n.;]*")
_SPLIT = re.compile(r"\s*(?:,|&|\+|\band\b|\s/\s)\s*")
_WORDS = re.compile(r"[a-z0-9+#.&/-]+")
_SAME: dict[str, list[str]] = {form: group for group in SAME for form in group}


def norm(skill: str) -> str:
    return " ".join(skill.lower().replace("’", "'").split())


def forms(term: str) -> set[str]:
    """The term, its spellings, and narrower terms (with their spellings)."""
    out = set(_SAME.get(term, [term])) | {term}
    for broad in list(out):
        for narrow in NARROWER.get(broad, []):
            out |= set(_SAME.get(narrow, [narrow])) | {narrow}
    return out


def _parts(skill: str) -> list[str]:
    return [p for p in _SPLIT.split(skill) if p]


def _main_words(part: str) -> list[str]:
    """Words that name something: "ai-driven" gives "ai"; a known hyphenated skill ("pre-sales") stays whole."""
    words = []
    for w in _WORDS.findall(part):
        words += [w] if w in _SAME or not re.search(r"[-/]", w) else re.split(r"[-/]", w)  # "ai/llm": ai, llm
    return [w for w in words if w not in GENERIC and len(w) > 1]


def _found(text: str, terms: set[str]) -> bool:
    return any(tx.has(text, t) for t in terms)


def match(text: str, skill: str) -> float:
    """How well `text` (lower-cased) shows `skill`: 1.0, RELATED (a main word only) or 0."""
    s = norm(skill)
    if not s:
        return 0.0
    if _found(text, forms(s)):
        return 1.0
    parts = _parts(s)
    # A part counts on its own when it names something: "infrastructure management", not "people".
    if any((_main_words(p) or " " in p) and _found(text, forms(p)) for p in parts if p != s):
        return 1.0
    words = {w for p in parts for w in _main_words(p)} - {s, *parts}
    return RELATED if any(_found(text, forms(w)) for w in words) else 0.0


def key_skill_hits(text: str, skills: list[str]) -> list[tuple[str, float]]:
    """The key skills the job shows, each with its match strength, in the user's order."""
    return [(s, m) for s in skills if (m := match(text, s))]


def asked_for(text: str, listed: list[str], key_skills: list[str]) -> list[str]:
    """The skills a job asks for, as worded by the listing, the vocabulary or the user: the listed ones, then
    vocabulary terms and key skills the text names (fully). One entry per skill, whatever its spelling."""
    out: list[str] = []
    seen: set[str] = set()

    def add(skill: str) -> None:
        s = norm(skill)
        if s and s not in seen:
            seen.update(_spellings(s))
            out.append(skill.strip())

    for s in listed:
        add(s)
    plain = _DEGREE.sub(" ", text)
    for s in VOCABULARY:  # by its own spellings only: a job naming "DevSecOps" doesn't ask for "DevOps"
        n = norm(s)
        if _IN_CONTEXT[n].search(plain) if n in _IN_CONTEXT else _found(plain, _spellings(n)):
            add(s)
    for s in key_skills:
        if match(text, s) == 1.0:
            add(s)
    return out


def _spellings(term: str) -> set[str]:
    return set(_SAME.get(term, [term])) | {term}


# A practice the user shows by naming one of its tools (2026-11-12: Terraform on the profile, yet "Infrastructure
# as code" was listed as missing on a PwC job).
SHOWN_BY: dict[str, list[str]] = {
    "infrastructure as code": ["terraform", "cloudformation", "pulumi", "bicep", "arm templates"],
}


def shows(resume_text: str, resume_skills: set[str], skill: str, by_meaning: bool = False) -> bool:
    """The resume (or the skills the user said they have) shows the skill: fully, or for one of the user's own
    broad key skills (`by_meaning`) also through a part's main word, as when matching it to a job."""
    s = norm(skill)
    if _spellings(s) & resume_skills:
        return True
    for broad, tools in SHOWN_BY.items():
        if s in _spellings(broad) and any(t in resume_skills or _found(resume_text, forms(t)) for t in tools):
            return True
    m = match(resume_text, s)
    return m == 1.0 or (by_meaning and m > 0)
