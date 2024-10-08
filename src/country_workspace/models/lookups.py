from django.db import models

from country_workspace.models.base import BaseModel


class Relationship(BaseModel):
    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=50, unique=True)


class ResidenceStatus(BaseModel):
    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=50, unique=True)


class Role(BaseModel):
    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=50, unique=True)


class MaritalStatus(BaseModel):
    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=50, unique=True)


class ObservedDisability(BaseModel):
    code = models.CharField(max_length=100, unique=True)
    label = models.CharField(max_length=100, unique=True)
