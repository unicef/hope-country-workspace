class BeneficiaryValidationError(Exception):
    def __init__(self) -> None:
        super().__init__("Some members didn't validate.")


class BeneficiaryValidationOrAlienError(Exception):
    def __init__(self) -> None:
        super().__init__("Some members didn't validate or contains alien fields.")
