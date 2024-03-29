from enum import Enum, IntEnum


class SupportedVendor(Enum):
    HenrySchein = "henry_schein"
    Net32 = "net_32"
    UltraDent = "ultradent"
    Darby = "darby"
    Patterson = "patterson"
    Benco = "benco"
    Amazon = "amazon"
    ImplantDirect = "implant_direct"
    EdgeEndo = "edge_endo"
    DentalCity = "dental_city"
    DcDental = "dcdental"
    CrazyDental = "crazy_dental"
    PureLife = "purelife"
    SkyDental = "skydental"
    TopGlove = "top_glove"
    BlueskyBio = "bluesky_bio"
    Praction = "praction"
    MidwestDental = "midwest_dental"
    Pearson = "pearson"
    Salvin = "salvin"
    Bergmand = "bergmand"
    Biohorizons = "biohorizons"
    Atomo = "atomo"
    Orthoarch = "orthoarch"
    OfficeDepot = "office_depot"
    EBay = "ebay"
    Safco = "safco"


class OnboardingStep(IntEnum):
    ACCOUNT_SETUP = 0
    OFFICE_DETAILS = 1
    BILLING_INFORMATION = 2
    LINK_VENDOR = 3
    OFFICE_BUDGET = 4
    INVITE_TEAM = 5
