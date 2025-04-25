class BeneficiaryValidationError(Exception):
    def __init__(self, beneficiary: str, key: int) -> None:
        super().__init__(beneficiary, key)
        self.beneficiary = beneficiary
        self.key = key

    def __str__(self) -> str:
        return f"Failed to validate {self.beneficiary} with key {self.key}."
