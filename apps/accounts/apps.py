from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"

    def ready(self):
        import apps.accounts.signals  # noqa

    async def initialize(self):
        from aiohttp import ClientSession, ClientTimeout

        self.session = ClientSession(timeout=ClientTimeout(300))

    async def finalize(self):
        await self.session.close()
