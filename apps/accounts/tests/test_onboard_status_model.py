from apps.accounts.factories import CompanyFactory
from apps.accounts.models import OnboardingStatus

FIELDS = (
    "offices_added",
    "subscribed",
    "vendors_linked",
    "budget_set",
    "team_invited",
)


def test_onboard_status(db):
    company = CompanyFactory()
    status, _ = OnboardingStatus.get_for_company(company.pk)
    assert status.company == company
    for field_name in FIELDS:
        assert not getattr(status, field_name)
