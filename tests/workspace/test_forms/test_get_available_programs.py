import pytest

from country_workspace.models import Office, User, Program, UserRole
from country_workspace.workspaces.forms import get_available_programs
from testutils.factories import OfficeFactory, UserFactory, ProgramFactory, UserRoleFactory, SuperUserFactory


@pytest.fixture
def office() -> Office:
    return OfficeFactory()


@pytest.fixture
def program0(office: Office) -> Program:
    return ProgramFactory(country_office=office)


@pytest.fixture
def program1(office: Office) -> Program:
    return ProgramFactory(country_office=office)


@pytest.fixture
def all_programs(program0: Program, program1: Program) -> tuple[Program, ...]:
    return program0, program1


@pytest.fixture
def user() -> User:
    return UserFactory()


@pytest.fixture
def single_program_role(office: Office, user: User, program0: Program) -> UserRole:
    return UserRoleFactory(user=user, country_office=office, program=program0)


@pytest.fixture
def none_program_role(office: Office, user: User) -> Program:
    return UserRoleFactory(country_office=office, user=user)


@pytest.fixture
def super_user() -> User:
    return SuperUserFactory()


def test_no_roles(office: Office, all_programs: tuple[Program, ...], user: User) -> None:
    assert get_available_programs(office, user).count() == 0


def test_single_program_role(
    office: Office, all_programs: tuple[Program, ...], single_program_role: UserRole, user: User
) -> None:
    assert get_available_programs(office, user).count() == 1


def test_none_program_role(
    office: Office, all_programs: tuple[Program, ...], none_program_role: Program, user: User
) -> None:
    assert get_available_programs(office, user).count() == len(all_programs)


def test_single_program_role_and_none_program_role(
    office: Office,
    all_programs: tuple[Program, ...],
    single_program_role: UserRole,
    none_program_role: UserRole,
    user: User,
) -> None:
    assert get_available_programs(office, user).count() == 1


def test_super_user(office: Office, all_programs: tuple[Program, ...], program1: Program, super_user: User) -> None:
    assert get_available_programs(office, super_user).count() == len(all_programs)
