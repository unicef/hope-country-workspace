class OnaApiError(Exception):
    pass


class OnaAuthenticationError(OnaApiError):
    pass


class OnaRateLimitError(OnaApiError):
    pass


class OnaMappingError(OnaApiError):
    pass
