class PromotionProductException(Exception):
    pass


class VendorSiteNotAvailableError(PromotionProductException):
    pass


class VendorSiteDataParsingError(PromotionProductException):
    pass
