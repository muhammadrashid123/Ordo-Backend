from typing import Optional, TypedDict


class CompanyInvite(TypedDict):
    company_id: int
    email: str
    office_id: Optional[int]
