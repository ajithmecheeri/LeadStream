"""Import every model so Base.metadata is complete (used by Alembic autogenerate and tests)."""

from app.core.db import Base
from app.modules.access.models import Invite, Subscription
from app.modules.admin.models import AppSetting
from app.modules.alerts.models import AlertFeed
from app.modules.applications.models import Application, ApplicationEvent, JobContact
from app.modules.apply.models import ApplyProfile
from app.modules.candidate.models import CandidateProfile
from app.modules.catalog.models import Job, JobSource
from app.modules.documents.models import CoverLetter, Resume, StoredFile
from app.modules.extension.models import ExtensionToken
from app.modules.feedback.models import JobFeedback, LearnedPreference
from app.modules.ingestion.models import ForwardSender, InboundMessage, InboundRaw
from app.modules.jobs.models import JobDuplicate, UserJob
from app.modules.llm.models import LlmCall
from app.modules.matching.models import JobMatch
from app.modules.networking.models import Connection, ConnectionImport, Outreach, OutreachEvent, Suggestion
from app.modules.notifications.models import Notification
from app.modules.profiles.models import SearchProfile
from app.modules.readiness.models import Answer
from app.modules.settings.models import NotificationSettings
from app.modules.sources.models import CompanyFeed, JobSearchSync, PlatformCompany, SourceRun, WatchedCompany
from app.modules.users.models import AuditEvent, Consent, RefreshToken, User
from app.modules.waitlist.models import ContactMessage, WaitlistEntry

__all__ = [
    "Base",
    "Invite",
    "Subscription",
    "PlatformCompany",
    "AlertFeed",
    "Answer",
    "CompanyFeed",
    "JobSearchSync",
    "SourceRun",
    "WatchedCompany",
    "AppSetting",
    "Application",
    "ApplicationEvent",
    "ApplyProfile",
    "AuditEvent",
    "JobContact",
    "CandidateProfile",
    "Consent",
    "Connection",
    "ConnectionImport",
    "CoverLetter",
    "ExtensionToken",
    "ContactMessage",
    "ForwardSender",
    "JobFeedback",
    "LearnedPreference",
    "InboundMessage",
    "InboundRaw",
    "Job",
    "JobDuplicate",
    "JobMatch",
    "JobSource",
    "LlmCall",
    "Notification",
    "NotificationSettings",
    "Outreach",
    "OutreachEvent",
    "RefreshToken",
    "Resume",
    "SearchProfile",
    "StoredFile",
    "Suggestion",
    "WaitlistEntry",
    "User",
    "UserJob",
]
