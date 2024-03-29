# Celery Settings
import os

import dotenv
from celery.schedules import crontab

from config.utils import get_bool_config

dotenv.load_dotenv()

# Our tasks are usually long running, so there is no point
# to fetch 4 per worker at once (the default behavior)
worker_prefetch_multiplier = 1

# Set up priorities
broker_transport_options = {"queue_order_strategy": "priority", "sep": ":", "priority_steps": [0, 3, 6, 9]}
task_default_priority = 6


default_queue = "celery"
broker_url = (os.getenv("REDIS_URL"),)
result_backend = os.getenv("REDIS_URL")
# BROKER_TRANSPORT_OPTIONS = {
#    "polling_interval": 2,
#    "region": "us-east-1",
# }
# RESULT_BACKEND = None
accept_content = ["application/json"]
task_serializer = "json"
result_serializer = "json"
timezone = "America/New_York"
enable_utc = False
# timezone = TIME_ZONE
task_always_eager = get_bool_config("CELERY_TASK_ALWAYS_EAGER")
task_time_limit = 300


beat_schedule = {
    "update_vendor_product_prices_for_crazy_dental": {
        "task": "apps.accounts.tasks.update_vendor_products_by_api_for_all_offices",
        "args": ("crazy_dental",),
        "schedule": crontab(hour="7,11,15", minute=30),
    },
    "update_order_history_for_crazy_dental": {
        "task": "apps.accounts.tasks.update_order_history_for_all_offices",
        "args": ("crazy_dental",),
        "schedule": crontab(day_of_week="1-5", hour=1, minute=0),
    },
    "update_office_budget": {
        "task": "apps.accounts.tasks.update_office_budget",
        "schedule": crontab(hour=6, minute=15, day_of_month=1),
    },
    "send_budget_update_notification": {
        "task": "apps.accounts.tasks.send_budget_update_notification",
        "schedule": crontab(hour=0, minute=0, day_of_month=1),
    },
    "update_office_cart_status": {
        "task": "apps.orders.tasks.update_office_cart_status",
        "schedule": crontab(minute="*/10"),
    },
    "sync_with_vendors": {
        "task": "apps.orders.tasks.sync_with_vendors",
        "schedule": crontab(minute=0, hour=0),
    },
    "update_net32_vendor_products": {
        "task": "apps.accounts.tasks.task_update_net32_products",
        "schedule": crontab(minute=0, hour=0),
    },
    "update_net32_vendor_products_prices": {
        "task": "apps.accounts.tasks.update_vendor_products_by_api_for_all_offices",
        "args": ("net_32",),
        "schedule": crontab(hour=8, minute=0, day_of_week=1),
    },
    "update_vendor_product_prices_for_henry_schein": {
        "task": "apps.accounts.tasks.update_vendor_product_prices_for_all_offices",
        "args": ("henry_schein",),
        "schedule": crontab(minute=0, hour=0, day_of_month=22),
    },
    "update_vendor_product_prices_for_benco": {
        "task": "apps.accounts.tasks.update_vendor_product_prices_for_all_offices",
        "args": ("benco",),
        "schedule": crontab(minute=0, hour=0, day_of_month=24),
    },
    "update_vendor_product_prices_for_darby": {
        "task": "apps.accounts.tasks.update_vendor_product_prices_for_all_offices",
        "args": ("darby",),
        "schedule": crontab(minute=0, hour=0, day_of_month=23),
    },
    "update_vendor_product_prices_for_dental_city": {
        "task": "apps.accounts.tasks.update_vendor_products_by_api_for_all_offices",
        "args": ("dental_city",),
        "schedule": crontab(hour="7,11,15", minute=30),
    },
    "update_vendor_product_prices_for_dcdental": {
        "task": "apps.accounts.tasks.update_vendor_products_by_api_for_all_offices",
        "args": ("dcdental",),
        "schedule": crontab(hour="7,11,15", minute=30),
    },
    "update_vendor_product_prices_for_edge_endo": {
        "task": "apps.accounts.tasks.update_vendor_product_prices_for_all_offices",
        "args": ("edge_endo",),
        "schedule": crontab(minute=0, hour=0, day_of_month=25),
    },
    "update_vendor_product_prices_for_patterson": {
        "task": "apps.accounts.tasks.update_vendor_product_prices_for_all_offices",
        "args": ("patterson",),
        "schedule": crontab(minute=0, hour=0, day_of_month=26),
    },
    "update_vendor_product_prices_for_pearson": {
        "task": "apps.accounts.tasks.update_vendor_product_prices_for_all_offices",
        "args": ("pearson",),
        "schedule": crontab(minute=0, hour=0, day_of_month=27),
    },
    "update_vendor_product_prices_for_safco": {
        "task": "apps.accounts.tasks.update_vendor_product_prices_for_all_offices",
        "args": ("safco",),
        "schedule": crontab(minute=0, hour=0, day_of_month=28),
    },
    "update_vendor_product_prices_for_ultradent": {
        "task": "apps.accounts.tasks.update_vendor_product_prices_for_all_offices",
        "args": ("ultradent",),
        "schedule": crontab(minute=0, hour=0, day_of_month=1),
    },
    "update_vendor_product_prices_for_midwest_dental": {
        "task": "apps.accounts.tasks.update_vendor_product_prices_for_all_offices",
        "args": ("midwest_dental",),
        "schedule": crontab(minute=0, hour=0, day_of_month=2),
    },
    "update_vendor_product_prices_for_implant_direct": {
        "task": "apps.accounts.tasks.update_vendor_product_prices_for_all_offices",
        "args": ("implant_direct",),
        "schedule": crontab(minute=0, hour=0, day_of_month=3),
    },
    "update_vendor_product_prices_for_bluesky_bio": {
        "task": "apps.accounts.tasks.update_vendor_product_prices_for_all_offices",
        "args": ("bluesky_bio",),
        "schedule": crontab(minute=0, hour=0, day_of_month=4),
    },
    "update_vendor_product_prices_for_top_glove": {
        "task": "apps.accounts.tasks.update_vendor_product_prices_for_all_offices",
        "args": ("top_glove",),
        "schedule": crontab(minute=0, hour=0, day_of_month=5),
    },
    "update_order_history_for_net_32": {
        "task": "apps.accounts.tasks.update_order_history_for_all_offices",
        "args": ("net_32",),
        "schedule": crontab(day_of_week="1-5", hour=1, minute=0),
    },
    "update_order_history_for_henry_schein": {
        "task": "apps.accounts.tasks.update_order_history_for_all_offices",
        "args": ("henry_schein",),
        "schedule": crontab(day_of_week="1-5", hour=1, minute=0),
    },
    "update_order_history_for_benco": {
        "task": "apps.accounts.tasks.update_order_history_for_all_offices",
        "args": ("benco",),
        "schedule": crontab(day_of_week="1-5", hour=1, minute=0),
    },
    "update_order_history_for_darby": {
        "task": "apps.accounts.tasks.update_order_history_for_all_offices",
        "args": ("darby",),
        "schedule": crontab(day_of_week="1-5", hour=1, minute=0),
    },
    "update_order_history_for_dental_city": {
        "task": "apps.accounts.tasks.update_order_history_for_all_offices",
        "args": ("dental_city",),
        "schedule": crontab(day_of_week="1-5", hour=1, minute=0),
    },
    "update_order_history_for_dcdental": {
        "task": "apps.accounts.tasks.update_order_history_for_all_offices",
        "args": ("dcdental",),
        "schedule": crontab(day_of_week="1-5", hour=1, minute=0),
    },
    "update_order_history_for_implant_direct": {
        "task": "apps.accounts.tasks.update_order_history_for_all_offices",
        "args": ("implant_direct",),
        "schedule": crontab(day_of_week="1-5", hour=1, minute=0),
    },
    "update_order_history_for_patterson": {
        "task": "apps.accounts.tasks.update_order_history_for_all_offices",
        "args": ("patterson",),
        "schedule": crontab(day_of_week="1-5", hour=1, minute=0),
    },
    "update_order_history_for_safco": {
        "task": "apps.accounts.tasks.update_order_history_for_all_offices",
        "args": ("safco",),
        "schedule": crontab(day_of_week="1-5", hour=1, minute=0),
    },
    "update_order_history_for_ultradent": {
        "task": "apps.accounts.tasks.update_order_history_for_all_offices",
        "args": ("ultradent",),
        "schedule": crontab(day_of_week="1-5", hour=1, minute=0),
    },
    "update_promotions": {
        "task": "apps.orders.tasks.update_promotions",
        "schedule": crontab(minute="0", hour="0", day_of_week="1,3,5"),  # Mon, Wed, Fri
    },
    "stream_salesforce_csv_into_ipfs": {
        "task": "apps.accounts.tasks.generate_csv_for_salesforce",
        "schedule": crontab(hour=10, minute=0),
    },
    "refresh_product_words": {"task": "apps.orders.tasks.refresh_product_words", "schedule": crontab(hour=2)},
    "refresh_price_age": {"task": "apps.orders.tasks.refresh_price_age", "schedule": crontab(hour=3)},
    "send_scheduled_invites": {
        "task": "apps.accounts.tasks.send_scheduled_invites",
        "schedule": crontab(hour="*", minute="0"),
    },
    "check_non_forumla_login": {
        "task": "apps.accounts.tasks.check_non_formula_vendors_login",
        "args": (
            [
                "net_32",
                "dental_city",
                "implant_direct",
                "edge_endo",
            ]
        ),
        "schedule": crontab(minute="0", hour="3"),
    },
    "remove_ghosted_companies": {
        "task": "apps.accounts.tasks.cleanup_ghosted_companies",
        "schedule": crontab(minute="0", hour="2"),
    },
    "auto_relink_failed_vendors": {
        "task": "apps.accounts.tasks.auto_relink_failed_vendors",
        "schedule": crontab(minute="0", hour="7"),
    },
    "pull_office_budget_from_open_dental": {
        "task": "apps.accounts.tasks.fill_office_budget_full",
        "schedule": crontab(minute=0, hour=5, day_of_month="1"),
    },
}
