NONE = "NONE"
SEEING = "SEEING"
HEARING = "HEARING"
WALKING = "WALKING"
MEMORY = "MEMORY"
SELF_CARE = "SELF_CARE"
COMMUNICATING = "COMMUNICATING"
OBSERVED_DISABILITY_CHOICE = (
    (NONE, "None"),
    (SEEING, "Difficulty seeing (even if wearing glasses)"),
    (HEARING, "Difficulty hearing (even if using a hearing aid)"),
    (WALKING, "Difficulty walking or climbing steps"),
    (MEMORY, "Difficulty remembering or concentrating"),
    (SELF_CARE, "Difficulty with self care (washing, dressing)"),
    (
        COMMUNICATING,
        "Difficulty communicating (e.g understanding or being understood)",
    ),
)


SOME_DIFFICULTY = "SOME_DIFFICULTY"
LOT_DIFFICULTY = "LOT_DIFFICULTY"
CANNOT_DO = "CANNOT_DO"
SEVERITY_OF_DISABILITY_CHOICES = (
    ("", "None"),
    (LOT_DIFFICULTY, "A lot of difficulty"),
    (CANNOT_DO, "Cannot do at all"),
    (SOME_DIFFICULTY, "Some difficulty"),
)
