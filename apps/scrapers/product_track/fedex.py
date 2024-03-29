import json
from typing import Dict

from apps.scrapers.product_track.base import BaseTrack
from apps.scrapers.product_track.headers import FEDEX_TRACKING_HEADERS


class FedexProductTrack(BaseTrack):
    PACKAGES_LIMIT = 30
    TRACKING_BASE_URL = (
        "https://www.fedex.com/apps/fedextrack?action=track&cntry_code=us&language=english&tracknumber_list="
    )

    async def track_shipping_products(self, tracking_numbers) -> Dict[str, str]:
        tracking_numbers_str = ",".join(tracking_numbers)
        headers = FEDEX_TRACKING_HEADERS.copy()
        headers["Referer"] = f"{self.TRACKING_BASE_URL}{tracking_numbers_str}"
        payload = {
            "TrackPackagesRequest": {
                "appDeviceType": "DESKTOP",
                "appType": "WTRK",
                "processingParameters": {},
                "uniqueKey": "",
                "supportCurrentLocation": True,
                "supportHTML": True,
                "trackingInfoList": [
                    {
                        "trackNumberInfo": {
                            "trackingNumber": tracking_number,
                            "trackingQualifier": None,
                            "trackingCarrier": None,
                        }
                    }
                    for tracking_number in tracking_numbers
                ],
            }
        }
        data = {
            "action": "trackpackages",
            "data": json.dumps(payload),
            "format": "json",
            "locale": "en_US",
            "version": 1,
        }
        async with self.session.post("https://www.fedex.com/trackingCal/track", headers=headers, data=data) as resp:
            res = json.loads(await resp.text())
            return {
                package["trackingNbr"]: package["keyStatus"] for package in res["TrackPackagesResponse"]["packageList"]
            }

    async def track_product(self, tracking_number, *args, **kwargs) -> Dict[str, str]:
        return await self.track_shipping_products([tracking_number])


async def track_products():
    from aiohttp import ClientSession, ClientTimeout

    tracking_numbers = [
        "280191637997",
        "785069973480",
        "784552797222",
        "783510021590",
        "783357601120",
    ]
    async with ClientSession(timeout=ClientTimeout(30)) as session:
        tracker = FedexProductTrack(session)
        print(await tracker.track_product(tracking_numbers[0]))
        # print(await tracker.track_products(tracking_numbers))


if __name__ == "__main__":
    import asyncio

    asyncio.run(track_products())
