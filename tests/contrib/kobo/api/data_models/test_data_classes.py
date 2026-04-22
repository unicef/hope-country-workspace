from unittest.mock import Mock
from country_workspace.contrib.kobo.api.data.submission import Submission
from country_workspace.contrib.kobo.api.data.asset import Asset


def test_submission() -> None:
    raw_submission = {
        "_id": 123,
        "_attachments": [{"download_url": "url", "mimetype": "mime", "question_xpath": "xpath"}],
        "name": "test",
        "_meta": "meta",
    }
    submission = Submission(raw_submission)

    assert submission.id == 123
    assert submission.attachments == raw_submission["_attachments"]
    assert submission["name"] == "test"
    assert "_meta" not in submission
    assert submission.raw == raw_submission


def test_asset() -> None:
    raw_asset = {"uid": "abc", "name": "Asset Name"}
    mock_submissions_func = Mock()
    mock_submissions_func.return_value = [Mock(spec=Submission)]

    asset = Asset(raw_asset, mock_submissions_func)

    assert asset.uid == "abc"
    assert asset.name == "Asset Name"
    assert str(asset) == "Asset: Asset Name"

    submissions = list(asset.submissions(min_id=100))
    assert len(submissions) == 1
    mock_submissions_func.assert_called_once_with(100)
