"""
Role-based access control helper for admin permissions.

# TODO(RBAC): Replace this minimal check with the full RBAC/permission system when available.
No call sites should need to change when swapping this out.
"""

from typing import Any, List, Union

from lib.admin_constants import (
    ROLE_ADMIN,
    ROLE_COMPLIANCE,
    ROLE_FINANCE,
    ROLE_SUPER_ADMIN,
)


def has_role(user: Any, required_roles: Union[str, List[str]]) -> bool:
    """
    Check if the given admin user has the required role(s).

    # TODO(RBAC): Replace this minimal role check with fine-grained RBAC permissions.
    
    :param user: Prisma User object, dict with 'role', or role string.
    :param required_roles: A single role string or list of acceptable role strings.
    :return: bool indicating permission grant.
    """
    if user is None:
        return False

    # Extract role string from input
    user_role: str
    if isinstance(user, str):
        user_role = user
    elif isinstance(user, dict):
        user_role = user.get("role", "")
    elif hasattr(user, "role"):
        role_attr = getattr(user, "role")
        user_role = role_attr.value if hasattr(role_attr, "value") else str(role_attr)
    else:
        return False

    if isinstance(required_roles, str):
        targets = [required_roles]
    else:
        targets = list(required_roles)

    # SUPER_ADMIN has elevated access across all admin roles
    if user_role == ROLE_SUPER_ADMIN:
        return True

    # COMPLIANCE role mapping fallback if user_role is SUPER_ADMIN (already handled above)
    for target in targets:
        if user_role == target:
            return True
        if target == ROLE_ADMIN and user_role in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
            return True
        if target == ROLE_COMPLIANCE and user_role in (ROLE_COMPLIANCE, ROLE_SUPER_ADMIN):
            return True
        if target == ROLE_FINANCE and user_role in (ROLE_FINANCE, ROLE_SUPER_ADMIN):
            return True

    return False
