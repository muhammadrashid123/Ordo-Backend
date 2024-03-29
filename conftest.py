def pytest_configure(config):
    from django.db import connection
    from django.db.models.signals import pre_migrate

    def app_pre_migration(sender, app_config, **kwargs):
        cur = connection.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        cur.execute("CREATE EXTENSION IF NOT EXISTS btree_gin;")

    pre_migrate.connect(app_pre_migration)
