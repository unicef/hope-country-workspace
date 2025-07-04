from country_workspace.admin.base import BaseModelAdmin
from country_workspace.models.serializer import DataSerializer
from django.contrib import admin


@admin.register(DataSerializer)
class DataSerializerAdmin(BaseModelAdmin):
    pass
