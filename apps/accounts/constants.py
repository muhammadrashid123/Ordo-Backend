CALCULATED_STATUS_SENT = 0
CALCULATED_STATUS_ACCEPTED = 1
CALCULATED_STATUS_EXPIRED = 2

INVITE_STATUS_LABELS = {
    CALCULATED_STATUS_SENT: "Sent",
    CALCULATED_STATUS_ACCEPTED: "Accepted",
    CALCULATED_STATUS_EXPIRED: "Expired",
}
INVITE_EXPIRES_DAYS = 21

GHOST_COMPANY_PERIOD = 30

# For these vendors, default budget_type = "office", otherwise, "dental"
DEFAULT_FRONT_OFFICE_BUDGET_VENDORS = ["amazon", "staples", "office_depot"]
MONTHS_BACKWARDS = 24
