"""Words that carry meaning for matching: seniority, job families, themes, domains and city names.

Shared by the resume reader and the scorer. Lower-case; matched on word boundaries.
"""

import functools
import re

# Same levels as app.modules.profiles.schemas.SENIORITY (1 Engineer … 9 CXO). First match wins.
SENIORITY_PATTERNS: list[tuple[int, str]] = [
    (6, r"\bchief (architect|engineer|scientist)\b"),
    # Not the company's CTO: a customer-facing technical leader (about VP), or a role in the CTO's team.
    (7, r"\bfield cto\b"),
    (6, r"\b(office of the cto|cto'?s office|cto office)\b"),
    (9, r"\b(chief|cto|ceo|cfo|coo|cio|ciso|cpo|cdo|cmo|chro)\b"),
    (8, r"\b(svp|evp|senior vice president|sr\.? vice president|executive vice president)\b"),
    (6, r"\b(dvp|avp|assistant vice president|deputy vice president)\b"),
    (7, r"\b(vp|vice president)\b"),
    (6, r"\b(head|senior director|sr\.? director|general manager|gm)\b"),
    (5, r"\bdirector\b"),
    (4, r"\b(senior manager|sr\.? manager|principal|principle|associate director|leader)\b"),
    (3, r"\b(manager|architect)\b"),
    (2, r"\b(lead|staff)\b"),
    (1, r"\b(engineer|developer|analyst|consultant|specialist|executive)\b"),
]

# Job families. A title can belong to several; matching compares the sets.
FAMILIES: dict[str, list[str]] = {
    "technology": [
        "engineer",
        "engineering",
        "technology",
        "technical",
        "tech",
        "architect",
        "architecture",
        "software",
        "platform",
        "cto",
        "cio",
        "developer",
        "development",
        "devops",
        "sre",
        "cloud",
        "it",
        "digital",
        "solution",
        "solutions",
        "infrastructure",
        "security",
        "ciso",
    ],
    "product": ["product", "products", "cpo", "pom"],
    "ai_data": ["ai", "ml", "genai", "data", "analytics", "machine learning", "robotics", "intelligence"],
    "delivery": [
        "delivery",
        "program",
        "programme",
        "project",
        "projects",
        "services",
        "transformation",
        "pmo",
    ],
    "finance": [
        "finance",
        "financial planning",
        "cfo",
        "fp&a",
        "fpna",
        "accounting",
        "controller",
        "treasury",
        "tax",
    ],
    "sales": ["sales", "account", "accounts", "business development", "revenue", "partnerships", "alliances"],
    "operations": [
        "s&op",
        "siop",
        "supply chain",
        "procurement",
        "manufacturing",
        "plant",
        "logistics",
        "operations",
        "supply",
        "fulfilment",
        "fulfillment",
        "last mile",
        "warehouse",
    ],
    "people": [
        "hr",
        "human resources",
        "talent",
        "people",
        "chro",
        "recruitment",
        "recruiting",
        "recruiter",
        "talent acquisition",
        "industrial relations",
        "employee relations",
        "learning & development",
        "learning and development",
        "org development",
        "organisation development",
        "organization development",
        "payroll",
    ],
    "marketing": ["marketing", "brand", "cmo", "communications"],
    "strategy": [
        "strategy",
        "strategic",
        "corporate affairs",
        "ceo's office",
        "chief of staff",
    ],
    # User feedback 2026-11-11: NTT DATA's "Data & AI Consulting Mgt. Managing Dir." (a client-facing advisory
    # and presales role) scored 76 for a product and engineering leader. Consulting is client work, not running a
    # product or an engineering organisation; a title naming it is consulting whatever else it names.
    "consulting": ["consulting", "consultant", "consultants", "advisory"],
    # Added 2026-11-03 for company-feed titles (milestone 9): fields that used to go unrecognised, so they never
    # clashed with an engineering leader's profile.
    "design": ["design", "designer", "ux", "ui", "user experience", "user research", "visual", "creative"],
    "legal": ["legal", "counsel", "lawyer", "compliance", "regulatory", "company secretary", "litigation"],
    "customer": ["support", "customer success", "customer experience", "customer service", "customer care"],
    "lending": ["lending", "credit", "collections", "underwriting", "loans", "merchant lending"],
    # Added 2026-11-04 (an "SAP GRC / BR&C Technology Architect" invite was a Top match for an engineering and
    # product leader): packaged enterprise applications are a specialism of their own, not general technology.
    "enterprise_apps": [
        "sap",
        "s/4hana",
        "s4hana",
        "abap",
        "erp",
        "oracle ebs",
        "oracle fusion",
        "oracle apps",
        "peoplesoft",
        "jd edwards",
        "netsuite",
        "salesforce",
        "workday",
        "servicenow",
        "dynamics 365",
        "d365",
        "siebel",
    ],
}
# Words that look like a field but describe another discipline: "Product Design" is design, not product;
# "Digital Marketing" is marketing, not technology.
_DESIGN_PHRASES = re.compile(r"\b(product|ux|ui|service|interaction|visual)\s+design(er|ers)?\b")
_MARKETING_PHRASES = re.compile(r"\bdigital\s+marketing\b")
_QUALIFIERS = {"strategy", "operations"}

# Specialisms read from a job's description, not its title (user feedback 2026-11-05: "MCCB Product Engineering",
# a switchgear manufacturing role, was a Top match for a software leader because its title says "Product
# Engineering"). Each term is specific to the specialism; a job belongs to one when its description names at
# least SPECIALISM_MIN different terms, and a candidate has it when a resume names at least SPECIALISM_HAVE.
SPECIALISMS: dict[str, list[str]] = {
    "hardware": [
        "manufacturing process",
        "manufacturing processes",
        "manufacturing engineering",
        "manufacturability",
        "industrialization",
        "industrialisation",
        "new product introduction",
        "npi",
        "apqp",
        "ppap",
        "pfmea",
        "dfmea",
        "fmea",
        "control plan",
        "control plans",
        "cpk",
        "spc",
        "injection moulding",
        "injection molding",
        "moulding",
        "molding",
        "stamping",
        "sheet-metal",
        "sheet metal",
        "casting",
        "forging",
        "machining",
        "cnc",
        "welding",
        "tooling",
        "plating",
        "shop floor",
        "switchgear",
        "circuit breaker",
        "circuit breakers",
        "mccb",
        "low-voltage",
        "pcb",
        "power electronics",
        "mechanical design",
        "solidworks",
        "creo",
        "catia",
        "gd&t",
        "iatf",
        "plc",
        "scada",
        "lean manufacturing",
        "kaizen",
        "pilot builds",
    ],
    "enterprise_apps": [
        "sap",
        "s/4hana",
        "s4hana",
        "abap",
        "fico",
        "sap fi",
        "sap mm",
        "sap sd",
        "sap basis",
        "fiori",
        "successfactors",
        "ariba",
        "erp",
        "oracle ebs",
        "oracle fusion",
        "oracle financials",
        "oracle financial",
        "oracle cloud erp",
        "oracle apps",
        # Oracle's technology stack (2026-11-06: PwC's "Oracle Technical Director" scored 95 for a software
        # leader whose resumes name none of it).
        "oracle",
        "oracle cloud",
        "oracle cloud infrastructure",
        "oci",
        "oracle adf",
        "application development framework",
        "oracle business intelligence",
        "bi publisher",
        "obiee",
        "oracle data integration",
        "oracle data integrator",
        "oracle integration cloud",
        "oracle forms",
        "weblogic",
        "jdeveloper",
        "hyperion",
        "oracle epm",
        "oracle hcm",
        "oracle scm",
        "e-business suite",
        "peoplesoft",
        "jd edwards",
        "netsuite",
        "salesforce",
        "sales cloud",
        "service cloud",
        "visualforce",
        "apex",
        "lightning web components",
        "cpq",
        "workday",
        "workday hcm",
        "servicenow",
        "dynamics 365",
        "d365",
        "siebel",
    ],
    # User feedback 2026-11-09: Axiro's "Product Line Director" (a portfolio of semiconductor products) scored 85
    # for a software product leader; its product-management words all matched. Chips are their own field.
    "semiconductor": [
        "semiconductor",
        "semiconductors",
        "chip",
        "chips",
        "chipset",
        "chipsets",
        "silicon",
        "foundry",
        "fabless",
        "asic",
        "asics",
        "fpga",
        "vlsi",
        "rtl",
        "verilog",
        "systemverilog",
        "tape-out",
        "tapeout",
        "wafer",
        "wafers",
        "pre-silicon",
        "post-silicon",
        "ic design",
        "analog",
        "mixed-signal",
        "rfic",
        "rf",
        "mmwave",
        "gaas",
        "osat",
        "photonics",
    ],
    # User feedback 2026-11-11: GE HealthCare's "Senior Director, Software Engineering" scored 92, but "embedded
    # knowledge is required". Embedded and firmware work is a primary skill of its own.
    "embedded": [
        "embedded",
        "embedded software",
        "embedded systems",
        "embedded linux",
        "embedded c",
        "firmware",
        "rtos",
        "real-time operating system",
        "freertos",
        "vxworks",
        "microcontroller",
        "microcontrollers",
        "mcu",
        "bsp",
        "board support package",
        "device driver",
        "device drivers",
        "bare-metal",
        "bare metal",
        "yocto",
        "linux kernel",
        "kernel drivers",
        "arm cortex",
        "iec 62304",
        "hardware-software integration",
        "hardware/software integration",
        "jtag",
        "uart",
        "i2c",
        "spi",
    ],
    # GE HealthCare's job is regulated medical-device software (IEC 62304, ISO 14971, AAMI TIR45): a field of its
    # own, whatever the engineering words around it.
    "medical_devices": [
        "medical device",
        "medical devices",
        "fda",
        "iec 62304",
        "iso 14971",
        "iec 82304",
        "iec 82304-1",
        "iso 13485",
        "aami",
        "aami tir45",
        "21 cfr",
        "samd",
        "software as a medical device",
        "design controls",
        "regulated medical software",
        "regulated health software",
        "regulated-health-software",
        "medical software",
        "eu mdr",
        "class ii",
    ],
    # User feedback 2026-11-11: Rakuten Symphony's "Senior Director, Software Development (Wireless O-RAN)"
    # scored 92; it must come from a RAN product organisation, hands-on in C/C++.
    "wireless": [
        "wireless",
        "5g",
        "4g",
        "6g",
        "lte",
        "ran product",
        "ran software",
        "ran systems",
        "vran",
        "cloud ran",
        "o-ran",
        "oran",
        "open ran",
        "ai-ran",
        "radio access network",
        "radio access networks",
        "3gpp",
        "baseband",
        "phy",
        "gnodeb",
        "enodeb",
        "gnb",
        "mimo",
        "massive mimo",
        "beamforming",
        "small cells",
        "rrc",
        "pdcp",
        "rlc",
    ],
    # User feedback 2026-11-11: HARMAN's "Executive Director, Product Management, SBU Connectivity" (automotive
    # telematics) scored 87 for a software product leader.
    "automotive": [
        "automotive",
        "automotive-grade",
        "vehicle",
        "vehicles",
        "in-vehicle",
        "connected car",
        "connected vehicle",
        "connected vehicles",
        "telematics",
        "v2x",
        "autosar",
        "infotainment",
        "ecu",
        "ecus",
        "adas",
        "gnss",
        "can bus",
        "iso 26262",
        "aspice",
        "digital cockpit",
        "tier 1",
        "tier-1",
        "oem",
        "oems",
        "ota",
        "mobility",
    ],
    # User feedback 2026-11-11: GSK's "Senior Director - Design Assurance & Product Management" is cyber security
    # governance and assurance (quality gates, risk registers, audit, lines of defence), not product building.
    "security_governance": [
        "design assurance",
        "security assurance",
        "assurance",
        "governance framework",
        "quality gate",
        "risk register",
        "risk appetite",
        "lines of defence",
        "lines of defense",
        "line of defence",
        "line of defense",
        "internal audit",
        "risk and exception",
        "exception management",
        "control framework",
        "security posture",
        "cyber risk",
        "grc",
        "nist csf",
        "ciso",
        "cyber security",
        "cybersecurity",
        "audit",
        "regulators",
    ],
    # User feedback 2026-11-11: PUMA's "Head, Product Line Management, Footwear & Apparel" (merchandising,
    # assortment, costing) scored 84 from its title alone. Consumer goods product lines are a trade of their own.
    "apparel_retail": [
        "footwear",
        "apparel",
        "fashion",
        "garment",
        "garments",
        "textile",
        "textiles",
        "sportswear",
        "merchandising",
        "merchandiser",
        "assortment",
        "assortment planning",
        "range planning",
        "line planning",
        "sell-through",
        "open to buy",
        "otb",
        "costing",
        "sourcing",
        "retail",
    ],
}
SPECIALISM_MIN = 4
SPECIALISM_HAVE = 2
# Bare product names: a software job lists them as integrations ("connectors for Salesforce, Workday,
# ServiceNow"), so a job also needs SPECIALISM_HANDS_ON of the other, hands-on terms (ABAP, Fiori, Apex, CPQ…).
SPECIALISM_NAMES_ONLY = {
    "enterprise_apps": {
        "sap",
        "erp",
        "salesforce",
        "workday",
        "servicenow",
        "netsuite",
        "peoplesoft",
        "oracle apps",
        "oracle",
        "oracle cloud",
    },
    # Software jobs say these too: "AI chips", "Silicon Valley", Palantir Foundry, "the semiconductor sector".
    "semiconductor": {"semiconductor", "semiconductors", "chip", "chips", "silicon", "foundry"},
    # "Embedded analytics", "embedded in the team", "Linux kernel" tuning: software jobs say these too.
    "embedded": {"embedded", "linux kernel", "spi"},
    # A health-tech software job may name the FDA or medical devices in passing; the regulated work names the
    # standards.
    "medical_devices": {"medical device", "medical devices", "fda", "medical software"},
    # A software job says "5G-ready", "wireless"; RAN work names the radio stack.
    "wireless": {"wireless", "5g", "4g", "6g", "lte"},
    # Software for mobility, fleets or car makers says "vehicle", "OEM", "OTA updates"; automotive work names
    # telematics, V2X, AUTOSAR, ECUs…
    "automotive": {"automotive", "vehicle", "vehicles", "oem", "oems", "ota", "mobility", "tier 1", "tier-1"},
    # Every engineering leader's job mentions security, audit and the CISO; assurance work names its machinery.
    "security_governance": {"cyber security", "cybersecurity", "audit", "regulators", "ciso", "assurance"},
    # Any e-commerce or retail-tech job says retail, sourcing, costing; the trade names footwear, assortment…
    "apparel_retail": {"retail", "sourcing", "costing", "fashion"},
}
SPECIALISM_HANDS_ON = 2
# A vendor building its own product is software work: an SAP Labs engineering job names SAP throughout.
SPECIALISM_VENDORS = {
    "enterprise_apps": ("sap", "oracle", "salesforce", "workday", "servicenow", "microsoft", "netsuite"),
}

# Industry experience a job requires (user feedback 2026-11-06: Shell Recharge's "Director, Product Management"
# scored 89 for a product leader, but its must-haves are EV charging, OCPP/OCPI and CPO/MSP platforms). Unlike a
# specialism, the function may fit: only sentences that ask for something ("experience", "knowledge"…) count,
# since an EV company describes itself in EV words whatever the job. Same thresholds as specialisms.
INDUSTRIES: dict[str, list[str]] = {
    "ev_charging": [
        "ev charging",
        "e-mobility",
        "emobility",
        "electric mobility",
        "charge point",
        "charge points",
        "charging network",
        "charging networks",
        "charging infrastructure",
        "charging protocols",
        "charging ecosystems",
        "smart charging",
        "ocpp",
        "ocpi",
        "oicp",
        "demand response",
        "site load management",
        "energy management",
        "battery management",
        "ev",
        "electric vehicle",
        "electric vehicles",
        "cpo",
        "msp",
        "roaming",
        "ems",
    ],
    "core_banking": [
        "core banking",
        "temenos",
        "t24",
        "finacle",
        "flexcube",
        "mambu",
        "thought machine",
        "loan origination",
        "iso 20022",
        "swift",
        "basel",
        "banking",
        "bank",
        "lending",
    ],
    "insurance": [
        "guidewire",
        "duck creek",
        "policycenter",
        "claimcenter",
        "billingcenter",
        "policy administration",
        "underwriting",
        "actuarial",
        "reinsurance",
        "insurance",
        "claims",
    ],
    "healthcare": [
        "hl7",
        "fhir",
        "ehr",
        "emr",
        "cerner",
        "clinical",
        "icd-10",
        "healthcare",
        "hipaa",
        "patient",
        "hospital",
    ],
    "telecom": ["oss/bss", "bss", "5g", "volte", "nfv", "mvno", "telecom billing", "telecom", "telco"],
}
INDUSTRY_NAMES_ONLY = {
    "ev_charging": {"ev", "electric vehicle", "electric vehicles", "cpo", "msp", "roaming", "ems"},
    "core_banking": {"banking", "bank", "lending"},
    "insurance": {"insurance", "claims"},
    "healthcare": {"healthcare", "hipaa", "patient", "hospital"},
    "telecom": {"telecom", "telco"},
}
_ASKS = re.compile(
    r"\b(experience|experienced|knowledge|expertise|background|familiar|familiarity|proficien\w*)\b"
)
_SENTENCES = re.compile(r"[\n•▪●;]|(?<=[a-z0-9)])\.\s")
# Where a title's main function ends and its qualifiers begin: "Director of Recruiting, Engineering & IT".
_TITLE_PARTS = re.compile(r"\s*(?:[,(|:/]|\s[-–—]\s|\s[-–—]|[-–—]\s)\s*")
# Families close enough that a move between them is plausible.
ADJACENT: set[frozenset[str]] = {
    frozenset({"technology", "product"}),
    frozenset({"technology", "ai_data"}),
    frozenset({"product", "ai_data"}),
    frozenset({"technology", "delivery"}),
    frozenset({"product", "delivery"}),
    frozenset({"technology", "strategy"}),
}

# Themes behind the core / cloud / ai scoring factors.
THEMES: dict[str, list[str]] = {
    "core": [
        "product development",
        "product management",
        "engineering",
        "software",
        "saas",
        "platform",
        "full-stack",
        "full stack",
        "agile",
        "scrum",
        "delivery",
        "roadmap",
        "product strategy",
        "sdlc",
    ],
    "cloud": [
        "aws",
        "azure",
        "gcp",
        "google cloud",
        "cloud",
        "kubernetes",
        "docker",
        "microservices",
        "devops",
        "devsecops",
        "sre",
        "serverless",
        "lambda",
        "terraform",
        "architecture",
        "distributed systems",
        "event-driven",
        "kafka",
    ],
    "ai": [
        "ai",
        "ml",
        "genai",
        "gen-ai",
        "generative ai",
        "llm",
        "llms",
        "machine learning",
        "deep learning",
        "rag",
        "nlp",
        "data science",
        "physical ai",
        "robotics",
        "intelligent automation",
        "computer vision",
    ],
}

DOMAINS: dict[str, list[str]] = {
    "banking": ["bank", "banking", "bny", "wealth management", "investment banking", "lending", "mortgage"],
    # Not "finance": in a title that is the job function (FP&A, CFO), not the industry.
    "financial services": [
        "financial services",
        "fintech",
        "visa",
        "mastercard",
        "payments",
    ],
    "insurance": ["insurance", "insurtech"],
    "retail": [
        "retail",
        "retailer",
        "grocery",
        "e-commerce",
        "ecommerce",
        "order fulfillment",
        "click & collect",
    ],
    "healthcare": ["healthcare", "health", "pharma", "hospital", "medical"],
    "automotive": ["automotive", "electric vehicle", "ev", "ola electric"],
    "real estate": ["real estate", "construction", "brigade"],
    "media": ["media", "tv", "entertainment", "ticketing", "theater", "theatre"],
    "logistics": ["logistics", "supply chain", "shipping"],
    "telecom": ["telecom", "telecommunications"],
    "regulatory": ["regulatory", "compliance", "pci", "soc2", "iso 27001"],
}

# Spellings of the same city. The first name is the canonical one.
CITY_ALIASES: list[list[str]] = [
    ["bengaluru", "bangalore", "bengaluru east", "bangalore urban", "bengaluru urban"],
    ["mumbai", "bombay", "navi mumbai", "thane"],
    ["delhi", "new delhi", "delhi ncr", "ncr"],
    ["gurugram", "gurgaon"],
    ["noida", "greater noida"],
    ["chennai", "madras"],
    ["kolkata", "calcutta"],
    ["hyderabad", "secunderabad"],
    ["pune"],
    ["kochi", "cochin"],
    ["thiruvananthapuram", "trivandrum"],
    ["ahmedabad"],
    ["jaipur"],
    ["coimbatore"],
    ["chandigarh", "mohali"],
    ["indore"],
    ["kozhikode", "calicut"],
]
_CITY: dict[str, str] = {alias: names[0] for names in CITY_ALIASES for alias in names}
REMOTE_WORDS = ("remote", "work from home", "wfh", "anywhere")


# Lines of legal boilerplate (equal opportunity, accommodation, AI-in-hiring notices): they say nothing about the
# job, but name things like "artificial intelligence, machine learning" that would read as skills asked for.
BOILERPLATE = re.compile(
    r"equal (?:employment )?opportunity|without regard to|reasonable accommodation|local law 144"
    r"|automated employment decision|arrest and conviction|e-verify",
    re.IGNORECASE,
)


def without_boilerplate(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not BOILERPLATE.search(line))


@functools.lru_cache(maxsize=16384)
def _phrase(phrase: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w&]){re.escape(phrase)}(?![\w&])")


def has(text: str, phrase: str) -> bool:
    """`phrase` as a whole word or phrase in `text`. Hot (scoring calls it ~3,500 times a job): the substring
    check rules most phrases out without a regex, and the patterns are compiled once (2026-11-15: re's own
    cache of 512 overflowed and recompiled on nearly every call)."""
    return phrase in text and _phrase(phrase).search(text) is not None


def count(text: str, phrases: list[str]) -> int:
    return sum(1 for p in phrases if has(text, p))


def seniority(title: str | None) -> int | None:
    t = (title or "").lower()
    for level, pattern in SENIORITY_PATTERNS:
        if re.search(pattern, t):
            return level
    return None


def families(text: str | None) -> set[str]:
    t = _DESIGN_PHRASES.sub("design", (text or "").lower())
    t = _MARKETING_PHRASES.sub("marketing", t)
    return {f for f, words in FAMILIES.items() if any(has(t, w) for w in words)}


def specialisms(text: str | None, company: str | None = None) -> set[str]:
    """The specialisms a job's description is about (see SPECIALISMS). The company's own name is left out, and
    a vendor's jobs are never its own specialism."""
    t = (text or "").lower()
    co = (company or "").lower()
    if co.strip():
        t = t.replace(co.strip(), " ")
    out = set()
    for name, words in SPECIALISMS.items():
        if any(has(co, v) for v in SPECIALISM_VENDORS.get(name, ())):
            continue
        if count(t, words) >= SPECIALISM_MIN and count(t, _hands_on(name)) >= SPECIALISM_HANDS_ON:
            out.add(name)
    return out


def title_specialisms(title: str | None) -> set[str]:
    """Specialisms a title names outright, with SPECIALISM_HANDS_ON hands-on terms: "Senior Director, Analog &
    Mixed-Signal (AMS) Engineering" is chip design even when an alert gives nothing else."""
    t = (title or "").lower()
    return {name for name in SPECIALISMS if count(t, _hands_on(name)) >= SPECIALISM_HANDS_ON}


def _hands_on(name: str) -> list[str]:
    if name in INDUSTRIES:
        return [w for w in INDUSTRIES[name] if w not in INDUSTRY_NAMES_ONLY.get(name, set())]
    names_only = SPECIALISM_NAMES_ONLY.get(name, set())
    return [w for w in SPECIALISMS[name] if w not in names_only]


def _asking(text: str | None) -> str:
    return "\n".join(s for s in _SENTENCES.split((text or "").lower()) if _ASKS.search(s))


def industry_terms(text: str | None) -> list[str]:
    """The hands-on industry terms in the sentences of a job that ask for something, as the job words them
    (lower-case): what the job page lists under an industry gap."""
    asks = _asking(text)
    return [w for name in INDUSTRIES for w in _hands_on(name) if has(asks, w)]


def industries(text: str | None) -> set[str]:
    """The industries whose experience a job asks for (see INDUSTRIES), from the sentences that ask."""
    asks = _asking(text)
    return {
        name
        for name, words in INDUSTRIES.items()
        if count(asks, words) >= SPECIALISM_MIN and count(asks, _hands_on(name)) >= SPECIALISM_HANDS_ON
    }


def has_specialism(text: str | None, name: str) -> bool:
    """A resume shows the specialism or industry: it names at least SPECIALISM_HAVE of its terms, one of them
    hands-on (a resume that only mentions "Oracle" and "ERP" in passing doesn't)."""
    t = (text or "").lower()
    words = INDUSTRIES.get(name) or SPECIALISMS[name]
    return count(t, words) >= SPECIALISM_HAVE and count(t, _hands_on(name)) >= 1


def title_families(title: str | None) -> set[str]:
    """A job title's families, from its main function: the first part that names one. "Director of Recruiting,
    Engineering & IT" is recruiting (people); "Director, Product Design" is design; "VP - Engineering" is
    technology. The rest of the title says whom the job serves, not what it is. A packaged application in that
    part makes it that specialism: "SAP Technology Architect" is SAP work, not general technology. Strategy and
    operations beside another function only qualify it: "Digital Marketing Strategy & Operations" is marketing."""
    for part in _TITLE_PARTS.split(title or ""):
        if found := families(part):
            for dominant in ("enterprise_apps", "consulting"):
                if dominant in found:
                    return {dominant}
            return found - _QUALIFIERS or found
    return set()


# The track a title is on (user feedback 2026-11-06: "Principal Engineer, UCX Platform, VP" at NatWest scored 100
# for a VP Product Development; at banks "VP" there is a grade, and the role is hands-on). Read from the title's
# first part, so a bank grade after a comma doesn't make an engineer a leader.
_LEADS = re.compile(
    r"\b(head|director|vp|vice president|svp|evp|chief|cto|cio|cpo|general manager|gm|leader"
    r"|engineering manager|development manager|delivery manager|manager,? engineering|manager,? software)\b"
)
_HANDS_ON = re.compile(r"\b(engineer|developer|scientist|architect|programmer)\b")


def title_main(title: str | None) -> str:
    """The title's first part: "Principal Engineer, UCX Platform, VP" → "Principal Engineer"."""
    return next((p.strip() for p in _TITLE_PARTS.split(title or "") if p.strip()), "")


def track(title: str | None) -> str | None:
    """ "lead" for a role leading teams, "ic" for a hands-on (individual contributor) role, None when the title
    doesn't say ("Product Manager", "Consultant")."""
    first = title_main(title).lower()
    if _LEADS.search(first):
        return "lead"
    if _HANDS_ON.search(first):
        return "ic"
    return None


def domains(text: str | None) -> list[str]:
    t = (text or "").lower()
    return [d for d, words in DOMAINS.items() if any(has(t, w) for w in words)]


def cities(location: str | None) -> tuple[set[str], bool]:
    """Canonical cities named in a location, and whether the text was cut short ("Pune, Chennai, Be...")."""
    loc = (location or "").lower()
    truncated = loc.rstrip().endswith(("...", "…"))
    found = set()
    for part in re.split(r"[,/;|()]+", loc.replace("…", "").replace("...", "")):
        part = part.strip()
        if not part:
            continue
        if part in _CITY:
            found.add(_CITY[part])
            continue
        for alias, city in _CITY.items():
            if has(part, alias):
                found.add(city)
    return found, truncated


def is_remote(text: str | None) -> bool:
    t = (text or "").lower()
    return any(has(t, w) for w in REMOTE_WORDS)
