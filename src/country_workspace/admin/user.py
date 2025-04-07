from admin_extra_buttons.decorators import view
from django.contrib import admin
from django.db.models import Q, QuerySet
from django.http import HttpRequest, JsonResponse
from unicef_security.admin import UserAdminPlus

from ..models import User


@admin.register(User)
class UserAdmin(UserAdminPlus):
    def get_search_results(
        self, request: HttpRequest, queryset: QuerySet[User], search_term: str
    ) -> tuple[QuerySet[User], bool]:
        return super().get_search_results(request, queryset, search_term)

    @view()
    def autocomplete(self, request: HttpRequest) -> JsonResponse:
        filters = {}
        if term := request.GET.get("term"):
            filters["username__icontains"] = term
        qs = User.objects.filter(**filters).distinct()
        if program := request.GET.get("program"):
            qs = qs.filter(
                Q(roles__program__id=program) | Q(is_superuser=True) | Q(roles__country_office__programs__pk=program),
            )
        results = [{"id": user.id, "text": user.username} for user in qs.all()]
        res = {"results": results, "pagination": {"more": False}}
        return JsonResponse(res)
