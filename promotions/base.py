from typing import List

import requests

from promotions.schema import PromotionProduct


class SpiderBase:
    def __init__(self):
        self._session = requests.Session()

    @property
    def session(self):
        return self._session

    def run(self) -> List[PromotionProduct]:
        raise NotImplementedError("Promotion scraper must implement `run`")
