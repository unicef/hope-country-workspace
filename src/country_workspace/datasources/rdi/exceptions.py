class ColumnConfigurationError(Exception):
    def __init__(self, column_name: str) -> None:
        super().__init__(column_name)
        self.column_name = column_name

    def __str__(self) -> str:
        return f"Column {self.column_name} not found."


class SheetProcessingError(Exception):
    def __init__(self, sheet_name: str, object_id: int) -> None:
        super().__init__(sheet_name, object_id)
        self.sheet_name = sheet_name
        self.object_id = object_id

    def __str__(self) -> str:
        return f"Failed to process sheet '{self.sheet_name}' at row with object id: {self.object_id}"


class SheetNotFoundError(Exception):
    def __init__(self, sheet_names: str | tuple[str, ...]) -> None:
        if isinstance(sheet_names, str):
            sheet_names = (sheet_names,)
        super().__init__(sheet_names)
        self.sheet_names = sheet_names

    def __str__(self) -> str:
        if len(self.sheet_names) == 1:
            return f"Sheet with index {self.sheet_names[0]} was not found in the provided file."
        indices_str = ", ".join(map(str, self.sheet_names))
        return f"Sheets with indices {indices_str} were not found in the provided file."
