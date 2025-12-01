class AlienFieldsError(Exception):
    """Raised when alien fields are detected in imported data."""

    def __init__(self, household_alien_fields: set[str], individual_alien_fields: set[str]) -> None:
        self.household_alien_fields = household_alien_fields
        self.individual_alien_fields = individual_alien_fields
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        parts = []
        if self.household_alien_fields:
            parts.append(f"Household alien fields: {', '.join(sorted(self.household_alien_fields))}")
        if self.individual_alien_fields:
            parts.append(f"Individual alien fields: {', '.join(sorted(self.individual_alien_fields))}")
        return " | ".join(parts) if parts else "Alien fields detected"
