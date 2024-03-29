class VendorClientException(Exception):
    pass


class VendorAuthenticationFailed(VendorClientException):
    pass


class MissingCredentials(VendorClientException):
    pass
