class TooManyBeneficiaryError(Exception):
    def __init__(self, beneficiary: str, record_id: int, count: int) -> None:
        super().__init__(beneficiary, record_id, count)
        self.beneficiary = beneficiary
        self.record_id = record_id
        self.count = count

    def __str__(self) -> str:
        return f"Expected one {self.beneficiary} for record {self.record_id}, but got {self.count}."
