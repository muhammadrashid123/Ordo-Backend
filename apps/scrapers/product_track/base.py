import asyncio
from typing import Dict


class BaseTrack:
    PACKAGES_LIMIT = 30

    def __init__(self, session):
        self.session = session

    async def track_product(self, tracking_number, *args, **kwargs) -> Dict[str, str]:
        raise NotImplementedError("Must implement `track_product`")

    async def track_shipping_products(self, tracking_numbers) -> Dict[str, str]:
        raise NotImplementedError("Must implement `track_product`")

    async def track_products(self, tracking_numbers) -> Dict[str, str]:
        tasks = (
            self.track_shipping_products(tracking_numbers[i : i + self.PACKAGES_LIMIT])
            for i in range(0, len(tracking_numbers), self.PACKAGES_LIMIT)
        )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return self.merge_results(results)

    @staticmethod
    def merge_results(results):
        return {
            product_id: product_status
            for result in results
            if isinstance(result, dict)
            for product_id, product_status in result.items()
        }
