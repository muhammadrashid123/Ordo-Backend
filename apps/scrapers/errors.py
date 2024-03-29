class ScraperException(Exception):
    pass


class VendorSiteError(ScraperException):
    pass


class VendorNotSupported(ScraperException):
    pass


class VendorAuthenticationFailed(ScraperException):
    pass


class OrderFetchException(ScraperException):
    pass


class NetworkConnectionException(ScraperException):
    pass


class VendorNotConnected(ScraperException):
    pass


class DownloadInvoiceError(ScraperException):
    def __init__(self, message):
        self.message = message
        super().__init__(message)
