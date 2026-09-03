import base64

import pytest
from hope_flex_fields.registry import field_registry

from country_workspace.contrib.hope.constants import DOCUMENT_TYPES
from country_workspace.state import state
from country_workspace.utils.flex_fields import Base64ImageField
from country_workspace.workspaces.models import CountryRdp

RAW_BYTES = b"fake-png-bytes"
DATA_URI = f"data:image/png;base64,{base64.b64encode(RAW_BYTES).decode()}"


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def individual_checker_with_documents():
    from testutils.factories import DataCheckerFactory, DataCheckerFieldsetFactory, FieldsetFactory, FlexFieldFactory

    field_registry.register(Base64ImageField)

    checker = DataCheckerFactory()
    fieldset = FieldsetFactory()
    FlexFieldFactory(fieldset=fieldset, name="document_number")
    FlexFieldFactory(fieldset=fieldset, name="image", definition__field_type=Base64ImageField)
    for doc_type in DOCUMENT_TYPES:
        DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset, prefix=f"{doc_type}_")

    return checker


@pytest.fixture
def program(office, individual_checker_with_documents):
    from testutils.factories import CountryProgramFactory

    prog = CountryProgramFactory(country_office=office, individual_checker=individual_checker_with_documents)
    state.program = prog
    return prog


@pytest.fixture
def rdp(program) -> CountryRdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(program=program)


@pytest.fixture
def batch(program):
    from testutils.factories import CountryBatchFactory

    return CountryBatchFactory(program=program, country_office=program.country_office)


@pytest.fixture
def make_individual(batch, rdp):
    """Create an Individual with the given flex_fields, linked directly to rdp (people-only)."""
    from testutils.factories import IndividualFactory

    def _make(flex_fields: dict):
        return IndividualFactory(household=None, batch=batch, flex_fields=flex_fields, rdps=[rdp])

    return _make


@pytest.fixture
def complete_document_flex_fields():
    return {
        "national_id_document_number": "ID-123",
        "national_id_image": DATA_URI,
        "national_passport_document_number": "",
        "national_passport_image": "",
    }
