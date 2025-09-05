from typing import Callable

from django.http import HttpRequest

from country_workspace.workspaces.models import CountryProgram


class OfficeBasedPermission:
    def __init__(self, permission: str) -> None:
        self.permission = permission

    def __call__(self, request: HttpRequest, obj: CountryProgram, handler: Callable | None = None) -> bool:
        if request.user.is_superuser:
            return True

        if not (office := getattr(obj, "country_office", None)):
            return False

        if not (user_roles_for_given_country := request.user.roles.filter(country_office=office)):
            return False

        # user, country_office and group are unique together
        has_perm_across_any_role = False
        for role in user_roles_for_given_country:
            if role.program and role.program != obj:
                continue

            has_perm_across_any_role = role.group.permissions.filter(codename=self.permission.split(".")[-1]).exists()

        return has_perm_across_any_role
