from hope_country_workspace.models import Household


class CountryHousehold(Household):
    class Meta:
        proxy = True
        app_label = 'hope_country_workspace'
