def to_cents(amount_str: str | float | int) -> int:
    """
    Convert a dollar amount string or float to integer cents.
    Examples: "1937.82" -> 193782, 50 -> 5000
    """
    if not amount_str:
        return 0
    return int(round(float(amount_str) * 100))

def from_cents(cents: int) -> float:
    """
    Convert integer cents back to a float dollar amount.
    Example: 193782 -> 1937.82
    """
    return round(cents / 100.0, 2)

def amounts_match(cents1: int, cents2: int, tolerance_cents: int = 1) -> bool:
    """
    Check if two amounts match within a penny tolerance (to handle minor rounding).
    """
    return abs(cents1 - cents2) <= tolerance_cents
