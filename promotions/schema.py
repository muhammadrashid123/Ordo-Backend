from typing import List, Optional, TypedDict


class PromotionProduct(TypedDict):
    product_id: str
    price: str  # Decimal
    promo: Optional[str]
    sku: Optional[str]
    name: Optional[str]
    url: Optional[str]
    images: Optional[List[str]]
