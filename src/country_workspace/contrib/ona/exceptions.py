class OnaApiError(Exception):
    pass


class OnaAuthenticationError(OnaApiError):
    pass


class OnaRateLimitError(OnaApiError):
    pass


class OnaMappingError(OnaApiError):
    pass


class OnaNotFoundError(OnaApiError):
    pass


class OnaAttachmentTooLargeError(OnaApiError):
    pass
