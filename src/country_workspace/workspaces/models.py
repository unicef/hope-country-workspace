from country_workspace.models import Household, Individual


class CountryHousehold(Household):
    class Meta:
        proxy = True
        app_label = "country_workspace"


class CountryIndividual(Individual):
    class Meta:
        proxy = True
        app_label = "country_workspace"
