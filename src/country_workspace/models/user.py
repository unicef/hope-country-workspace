from unicef_security.models import AbstractUser, SecurityMixin, TimeStampedModel


class User(SecurityMixin, TimeStampedModel, AbstractUser):
    class Meta:
        abstract = False
