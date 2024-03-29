class APIClientError(Exception):
    pass


class APIForbiddenError(APIClientError):
    pass
