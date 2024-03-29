from typing import Optional

from aiohttp import ClientSession

from apps.scrapers.amazon import AmazonScraper
from apps.scrapers.atomo import AtomoScraper
from apps.scrapers.benco import BencoScraper
from apps.scrapers.bergmand import BergmandScraper
from apps.scrapers.biohorizons import BioHorizonsScraper
from apps.scrapers.bluesky_bio import BlueSkyBioScraper
from apps.scrapers.crazy_dental import CrazyDentalScraper
from apps.scrapers.darby import DarbyScraper
from apps.scrapers.dcdental import DCDentalScraper
from apps.scrapers.dental_city import DentalCityScraper
from apps.scrapers.ebay_search import EbaySearch
from apps.scrapers.edge_endo import EdgeEndoScraper
from apps.scrapers.errors import VendorNotSupported
from apps.scrapers.henryschein import HenryScheinScraper
from apps.scrapers.implant_direct import ImplantDirectScraper
from apps.scrapers.midwest_dental import MidwestDentalScraper
from apps.scrapers.net32 import Net32Scraper
from apps.scrapers.office_depot import OfficeDepotScraper
from apps.scrapers.orthoarch import OrthoarchScraper
from apps.scrapers.patterson import PattersonScraper
from apps.scrapers.pearson import PearsonScraper
from apps.scrapers.practicon import PracticonScraper
from apps.scrapers.purelife import PureLifeScraper
from apps.scrapers.safco import SafcoScraper
from apps.scrapers.salvin import SalvinScraper
from apps.scrapers.skydental import SkydentalScraper
from apps.scrapers.top_glove import TopGloveScraper
from apps.scrapers.ultradent import UltraDentScraper

SCRAPER_SLUG = "patterson"
SCRAPERS = {
    "henry_schein": HenryScheinScraper,
    "net_32": Net32Scraper,
    "ultradent": UltraDentScraper,
    "darby": DarbyScraper,
    "patterson": PattersonScraper,
    "benco": BencoScraper,
    "amazon": AmazonScraper,
    "implant_direct": ImplantDirectScraper,
    "edge_endo": EdgeEndoScraper,
    "dental_city": DentalCityScraper,
    "dcdental": DCDentalScraper,
    "crazy_dental": CrazyDentalScraper,
    "purelife": PureLifeScraper,
    "skydental": SkydentalScraper,
    "top_glove": TopGloveScraper,
    "bluesky_bio": BlueSkyBioScraper,
    "praction": PracticonScraper,
    "midwest_dental": MidwestDentalScraper,
    "pearson": PearsonScraper,
    "salvin": SalvinScraper,
    "bergmand": BergmandScraper,
    "biohorizons": BioHorizonsScraper,
    "atomo": AtomoScraper,
    "orthoarch": OrthoarchScraper,
    "office_depot": OfficeDepotScraper,
    "ebay": EbaySearch,
    "safco": SafcoScraper,
}


class ScraperFactory:
    @classmethod
    def create_scraper(
        cls,
        *,
        vendor,
        session: ClientSession,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        if vendor.slug not in SCRAPERS:
            raise VendorNotSupported(vendor.slug)

        return SCRAPERS[vendor.slug](session, vendor, username, password)
