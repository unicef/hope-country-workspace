class AuroraAlienFieldError(Exception):
    def __init__(self, alien_fields: set[str]) -> None:
        self.alien_fields = alien_fields
        message = f"Alien fields found during import: {', '.join(sorted(alien_fields))}"
        super().__init__(message)
