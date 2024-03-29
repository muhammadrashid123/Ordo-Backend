from promotions.benco import BencoSpider
from promotions.darby import DarbySpider
from promotions.dentalcity import DentalcitySpider
from promotions.henryschein import HenrySpider
from promotions.midwest_dental import MidwestDentalSpider
from promotions.net32 import Net32Spider
from promotions.patterson import PattersonSpider
from promotions.safco import SafcoSpider
from promotions.skydentalsupply import SkydentalsupplySpider
from promotions.ultradent import UltradentSpider

PROMOTION_MAP = {
    "benco": BencoSpider,
    "darby": DarbySpider,
    "dental_city": DentalcitySpider,
    "henry_schein": HenrySpider,
    "net_32": Net32Spider,
    "patterson": PattersonSpider,
    "skydental": SkydentalsupplySpider,
    "ultradent": UltradentSpider,
    "midwest_dental": MidwestDentalSpider,
    "safco": SafcoSpider,
}
