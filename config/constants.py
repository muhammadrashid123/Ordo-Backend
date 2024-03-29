FORMULA_VENDORS = (
    "henry_schein",
    "darby",
    "patterson",
    "amazon",
    "benco",
    "ultradent",
    "implant_direct",
    "edge_endo",
    "dental_city",
    "dcdental",
    "purelife",
    "skydental",
    "top_glove",
    "bluesky_bio",
    "practicon",
    "midwest_dental",
    "pearson",
    "salvin",
    "bergmand",
    "biohorizons",
    "atomo",
    "orthoarch",
    "office_depot",
    "safco",
    "staples",
)

NON_FORMULA_VENDORS = ("net_32", "crazy_dental")

API_AVAILABLE_VENDORS = ("dental_city", "dcdental", "crazy_dental")

ALL_VENDORS = (*FORMULA_VENDORS, *NON_FORMULA_VENDORS)
