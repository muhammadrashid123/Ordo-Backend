import requests

from services.utils.secrets import get_secret_value

QUERY_URL = "https://api.opendental.com/api/v1/queries/ShortQuery"


class OpenDentalClient:
    def __init__(self, office_key):
        self.session = requests.Session()
        developer_key = get_secret_value("OPENDENTAL_DEVELOPER_KEY")
        self.session.headers = {"Authorization": f"{developer_key}/{office_key}"}

    def query(self, query, offset=None):
        params = {"Offset": offset} if offset else None
        resp = self.session.put(QUERY_URL, params=params, json={"SqlCommand": query})
        try:
            return resp.json(), resp.status_code
        except Exception:
            return f"Open dental API response: {resp.text}", resp.status_code
