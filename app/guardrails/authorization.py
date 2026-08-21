class AuthorizationError(Exception):
    """Raised when a tenant-scoped resource is missing or not owned by the caller."""


class TenantIsolationError(AuthorizationError):
    """Raised when a request attempts to cross tenant boundaries."""
