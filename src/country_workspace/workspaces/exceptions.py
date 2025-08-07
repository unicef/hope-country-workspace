class BeneficiaryValidationError(Exception):
    def __init__(self, beneficiary: str, keys: list[int]) -> None:
        super().__init__(beneficiary, keys)
        self.beneficiary = beneficiary
        self.keys = keys

    def __str__(self) -> str:
        return f"Failed to validate {self.beneficiary} with keys {self.keys}."
