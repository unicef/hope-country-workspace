import pytest
from django.core.exceptions import ValidationError

from country_workspace.models import Program, Office, UserRole
from country_workspace.models.role import PROGRAM_DOES_NOT_BELONG_TO_OFFICE
from testutils.factories import ProgramFactory, OfficeFactory


@pytest.fixture
def office() -> Office:
    return OfficeFactory()


@pytest.fixture
def another_office() -> Office:
    return OfficeFactory()


@pytest.fixture
def program(office: Office) -> Program:
    return ProgramFactory(country_office=office)


def test_clean_no_program(office: Office) -> None:
    UserRole(country_office=office).clean()


def test_clean_with_correct_office_and_program(office: Office, program: Program) -> None:
    UserRole(country_office=office, program=program).clean()


def test_clean_with_incorrect_office_and_program(another_office: Office, program: Program) -> None:
    with pytest.raises(ValidationError) as e:
        UserRole(country_office=another_office, program=program).clean()

    assert e.value.messages == [PROGRAM_DOES_NOT_BELONG_TO_OFFICE]
