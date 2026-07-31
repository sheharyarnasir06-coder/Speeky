"""
Constants for Admin & Analytics backend features (US-205, US-206, US-207).
No hardcoded literals — all thresholds, role names, namespaces, and widget/provider keys live here.
"""

# Role definitions
ROLE_SUPER_ADMIN = "SUPER_ADMIN"
ROLE_ADMIN = "ADMIN"
ROLE_COMPLIANCE = "COMPLIANCE"
ROLE_FINANCE = "FINANCE"
ROLE_USER = "USER"

# US-205 Audit Log Constants
AUDIT_LOG_NS = "admin_audit_logs"
GENESIS_HASH = "0" * 64

ACTION_EXPORT = "EXPORT"
ACTION_VIEW_RESTRICTED = "VIEW_RESTRICTED"
ACTION_FILTER = "FILTER"

# Analytics module name constants (used in audit log entries)
ANALYTICS_MODULE_OVERVIEW = "Overview"
ANALYTICS_MODULE_FUNNEL = "Funnel"
ANALYTICS_MODULE_FEATURE_USAGE = "FeatureUsage"
ANALYTICS_MODULE_RETENTION = "RetentionByFeature"
ANALYTICS_MODULE_REVENUE = "Revenue"

RESTRICTED_ANALYTICS_MODULES = {
    ANALYTICS_MODULE_OVERVIEW,
    ANALYTICS_MODULE_FUNNEL,
    ANALYTICS_MODULE_FEATURE_USAGE,
    ANALYTICS_MODULE_RETENTION,
    ANALYTICS_MODULE_REVENUE,
    "Financials",
    "UserPiiExport",
}


# US-206 Custom Dashboard Layout & Saved Views Constants
DASHBOARD_VIEW_NS = "dashboard_saved_views"

AVAILABLE_WIDGETS = {
    "revenue_summary",
    "user_growth",
    "retention_funnel",
    "feature_usage",
    "daily_sessions",
    "active_users_overview",
}

DEPRECATED_WIDGETS = {
    "legacy_conversion_v1",
    "old_mrr_tracker",
}

WIDGET_REQUIRED_ROLES = {
    "revenue_summary": [ROLE_SUPER_ADMIN, ROLE_COMPLIANCE, ROLE_FINANCE],
    "old_mrr_tracker": [ROLE_SUPER_ADMIN, ROLE_FINANCE],
}

AVAILABLE_SEGMENTS = {
    "all",
    "us_users",
    "eu_users",
    "enterprise_tier",
    "freemium_tier",
}

# US-207 Cross-Source Data Reconciliation Constants
RECONCILIATION_LOG_NS = "reconciliation_logs"
RECONCILIATION_STATUS_NS = "reconciliation_status"
RECONCILIATION_RESYNC_NS = "reconciliation_resync_queue"

PAYMENT_PROVIDERS = ["stripe", "apple", "google"]

DEFAULT_VARIANCE_TOLERANCE_PCT = 1.0  # 1% tolerance
DEFAULT_GRACE_PERIOD_MINUTES = 120    # 2 hours buffer for timing window mismatch

STATUS_RECONCILED = "RECONCILED"
STATUS_DISCREPANCY_DETECTED = "DISCREPANCY_DETECTED"
STATUS_RECONCILIATION_PENDING = "RECONCILIATION_PENDING"
STATUS_RECONCILIATION_FAILED = "RECONCILIATION_FAILED"

MAX_BACKOFF_RETRIES = 3
