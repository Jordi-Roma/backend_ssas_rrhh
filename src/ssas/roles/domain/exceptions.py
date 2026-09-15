class RoleError(Exception):
    """Base exception for role and permission business errors."""


class RoleNotFoundError(RoleError):
    pass


class PermissionNotFoundError(RoleError):
    pass


class DuplicateRoleError(RoleError):
    pass


class PermissionDeniedError(RoleError):
    pass


class ProtectedRoleError(RoleError):
    pass
