from typing import cast
from unittest.mock import MagicMock, Mock

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.kobo.api.data.helpers import VALUE_FORMAT, download_attachments, filter_out_meta_data
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from country_workspace.contrib.kobo.api.data.submission import Submission


def test_filter_out_meta_data() -> None:
    data = {
        "_key": "_value",
        (key := "key"): "value",
    }
    filtered = filter_out_meta_data(data)
    assert filtered == {key: data[key]}


@pytest.mark.parametrize("top_level_attachment", [True, False])
def test_download_attachments(mocker: MockerFixture, top_level_attachment: bool) -> None:
    data_getter = Mock()
    b64encode = mocker.patch("country_workspace.contrib.kobo.api.data.helpers.b64encode")
    content = b64encode.return_value.decode.return_value
    submission = MagicMock()
    submission.attachments = [
        {
            "download_url": (download_url := "https://test.org"),
            "mimetype": (mime_type := "mime-type"),
            "question_xpath": (
                question_xpath := (parent := "question.xpath") + "[" + str((index := 0) + 1) + "]/" + (key := "child")
            ),
        }
    ]
    submission.__contains__.return_value = not top_level_attachment
    value = VALUE_FORMAT.format(mimetype=mime_type, content=content)

    assert download_attachments(data_getter, cast("Submission", submission)) == submission
    data_getter.assert_called_once_with(download_url)
    b64encode.assert_called_once_with(data_getter.return_value.content)

    if top_level_attachment:
        submission.__getitem__.assert_called_once_with(parent)
        submission.__getitem__.return_value.__getitem__.assert_called_once_with(index)
        submission.__getitem__.return_value.__getitem__.return_value.__setitem__.assert_called_once_with(
            f"{parent}/{key}", value
        )
    else:
        submission.__setitem__.assert_called_once_with(question_xpath, value)


def test_download_attachments_empty_xpath(mocker: MockerFixture) -> None:
    data_getter = Mock()
    mocker.patch("country_workspace.contrib.kobo.api.data.helpers.b64encode")
    submission = MagicMock()
    submission.attachments = [
        {
            "download_url": "https://test.org",
            "mimetype": "mime-type",
            "question_xpath": "",
        }
    ]
    submission.__contains__.return_value = False

    assert download_attachments(data_getter, cast("Submission", submission)) == submission
    submission.__setitem__.assert_not_called()


def test_download_attachments_defaults_mimetype_and_xpath(mocker: MockerFixture) -> None:
    data_getter = Mock()
    b64encode = mocker.patch("country_workspace.contrib.kobo.api.data.helpers.b64encode")
    submission = MagicMock()
    submission.attachments = [
        {
            "download_url": "https://test.org",
        }
    ]
    submission.__contains__.return_value = False

    assert download_attachments(data_getter, cast("Submission", submission)) == submission
    b64encode.assert_called_once_with(data_getter.return_value.content)
    submission.__setitem__.assert_not_called()
