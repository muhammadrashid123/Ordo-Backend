from django.db import models


class BUDGET_SPEND_TYPE(models.TextChoices):
    DENTAL_SUPPLY_SPEND_BUDGET = "dental", "Dental Supply Budget"
    FRONT_OFFICE_SUPPLY_SPEND_BUDGET = "office", "Front Office Supply Budget"
    MISCELLANEOUS_SPEND_BUDGET = "miscellaneous", "Other"


class OrderStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"
    PENDING_APPROVAL = "pendingapproval", "Pending Approval"


class ProductStatus(models.TextChoices):
    PENDING_APPROVAL = "pendingapproval", "Pending Approval"
    REJECTED = "rejected", "Rejected"
    PROCESSING = "processing", "Processing"
    BACK_ORDERED = "backordered", "Back Ordered"
    RETURNED = "returned", "Returned"
    CANCELLED = "cancelled", "Cancelled"
    RECEIVED = "received", "Received"
    SHIPPED = "shipped", "Shipped"
    DELIVERED = "delivered", "Delivered"
    CREDITED = "credited", "Credited"
    REPAIR_OR_MAINTENANCE = "maintenance", "Repair/Maintenance"


class OrderType(models.TextChoices):
    ORDER_PROCESSING = "processing", "Ordo Order - Processing"
    ORDO_ORDER = "ordo", "Ordo Order"
    VENDOR_DIRECT = "vendor", "Vendor Direct"
