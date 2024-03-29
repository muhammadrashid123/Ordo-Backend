from asyncio import Semaphore
from typing import Dict

from apps.scrapers.product_track.base import BaseTrack
from apps.scrapers.product_track.headers import UPS_HEADERS, UPS_TRACKING_HEADERS
from apps.scrapers.semaphore import fake_semaphore


class UPSProductTrack(BaseTrack):
    PACKAGES_LIMIT = 25
    TRACKING_BASE_URL = "https://www.ups.com/track/api/Track/GetSummaryStatus"

    async def track_products(self, tracking_numbers) -> Dict[str, str]:
        sem = Semaphore(value=self.PACKAGES_LIMIT)
        tasks = (self.track_product(tracking_number, sem=sem) for tracking_number in tracking_numbers)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return self.merge_results(results)

    async def track_product(self, tracking_number, *args, **kwargs) -> Dict[str, str]:
        sem = kwargs.get("sem")
        if not sem:
            sem = fake_semaphore

        async with sem:
            async with self.session.get(self.TRACKING_BASE_URL, headers=UPS_HEADERS) as resp:
                headers = UPS_TRACKING_HEADERS.copy()
                headers["x-xsrf-token"] = resp.cookies["X-XSRF-TOKEN-ST"].value
                headers["referer"] = f"{resp.url}"

            data = {
                "Locale": "en_US",
                "TrackingNumber": [tracking_number],
                "isMultiTrack": True,
            }
            async with self.session.post(self.TRACKING_BASE_URL, json=data, headers=headers) as resp:
                res = await resp.json()

        if "trackDetails" in res and res["trackDetails"]:
            package_status = [
                package["packageStatus"]
                for package in res["trackDetails"]
                if package["trackingNumber"] == tracking_number
            ][0]
        else:
            package_status = ""

        return {tracking_number: package_status}


async def track_products():
    from aiohttp import ClientSession, ClientTimeout

    tracking_numbers = [
        "1Z460RY40333874958",
        "92748999985220513006581088",
        "1ZY06E520399984881",
    ]
    async with ClientSession(timeout=ClientTimeout(30)) as session:
        tracker = UPSProductTrack(session)
        # print(await tracker.track_product(tracking_numbers[0]))
        print(await tracker.track_products(tracking_numbers))


if __name__ == "__main__":
    import asyncio

    asyncio.run(track_products())
