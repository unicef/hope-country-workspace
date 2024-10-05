class TenantAdminError(Exception):
    pass


class InvalidTenantError(TenantAdminError):
    pass


class TenantNotAuthorisedError(TenantAdminError):
    pass


class SelectTenantException(TenantAdminError):
    pass
