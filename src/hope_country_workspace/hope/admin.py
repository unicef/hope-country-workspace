from admin_extra_buttons.decorators import button
from admin_extra_buttons.mixins import ExtraButtonsMixin
from django.contrib import admin
from .models import Program


@admin.register(Program)
class ProgramAdmin(ExtraButtonsMixin, admin.ModelAdmin):
    @button()
    def sync(self, request):
        base = "https://hope.unicef.org/api/rest/"
