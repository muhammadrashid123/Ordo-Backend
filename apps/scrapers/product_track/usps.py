import json
from typing import Dict

from apps.scrapers.product_track.base import BaseTrack
from apps.scrapers.product_track.headers import USPS_TRACKING_HEADERS


class USPSProductTrack(BaseTrack):
    PACKAGES_LIMIT = 35
    TRACKING_BASE_URL = "https://tools.usps.com/go/TrackConfirmAction_input"

    async def track_shipping_products(self, tracking_numbers) -> Dict[str, str]:
        params = {"tLabels": ",".join(tracking_numbers)}

        async with self.session.get(self.TRACKING_BASE_URL, params=params, headers=USPS_TRACKING_HEADERS) as resp:
            response_text = await resp.text()
            # TODO: error handling
            data = json.loads(response_text.split("dataLayer.push(", 1)[1].split(")\n</script>")[0])
            if data:
                return {package["id"]: package["category"] for package in data["ecommerce"]["impressions"]}
            else:
                return {tracking_number: "" for tracking_number in tracking_numbers}

    async def track_product(self, tracking_number, *args, **kwargs) -> Dict[str, str]:
        return await self.track_shipping_products([tracking_number])


async def track_products():
    from aiohttp import ClientSession, ClientTimeout

    tracking_numbers = [
        "9400111899220505042529",
        "9400111108250803232044",
    ]
    async with ClientSession(timeout=ClientTimeout(30)) as session:
        tracker = USPSProductTrack(session)
        # print(await tracker.track_product(tracking_numbers[0]))
        print(await tracker.track_products(tracking_numbers))


if __name__ == "__main__":
    import asyncio

    asyncio.run(track_products())
