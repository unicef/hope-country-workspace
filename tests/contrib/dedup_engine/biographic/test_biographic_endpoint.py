from country_workspace.contrib.dedup_engine.biographic.endpoint import APIRoot


def test_biographic_endpoints() -> None:
    dataset = APIRoot("https://de").datasets("afg", "prog").dataset(7)

    assert str(dataset) == "https://de/api/biographic/afg/prog/datasets/7/"
    assert str(dataset.records) == f"{dataset}records/"
    assert str(dataset.process) == f"{dataset}process/"
    assert str(dataset.findings) == f"{dataset}findings/"
    assert str(dataset.approve) == f"{dataset}approve/"
    assert str(dataset.reject) == f"{dataset}reject/"
    assert str(dataset.cancel) == f"{dataset}cancel/"
