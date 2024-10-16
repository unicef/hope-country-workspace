from typing import TypeVar, Union

from django_webtest import DjangoTestApp

from country_workspace.models import User

class CWTestApp(DjangoTestApp):
    _user: User
