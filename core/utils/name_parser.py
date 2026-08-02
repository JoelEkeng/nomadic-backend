def split_full_name(full_name: str | None) -> tuple[str, str]:
    """Split a full name into first and last name parts.

    Examples:
        "John Doe"            -> ("John", "Doe")
        "John Michael Doe"    -> ("John", "Michael Doe")
        "Prince"              -> ("Prince", "")
        ""  or None            -> ("", "")
    """
    if not full_name:
        return "", ""

    parts = full_name.strip().split()

    if not parts:
        return "", ""

    first_name = parts[0]
    last_name = " ".join(parts[1:]).strip()

    return first_name, last_name
