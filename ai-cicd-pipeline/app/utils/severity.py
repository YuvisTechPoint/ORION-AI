SEVERITY_ORDER = {"none": -1, "info": 0, "low": 0, "medium": 1, "high": 2, "critical": 3}


def severity_rank(value: str | None) -> int:
    return SEVERITY_ORDER.get(str(value or "none").lower(), -1)


def max_severity(*values: str | None) -> str:
    best = "none"
    for value in values:
        if severity_rank(value) > severity_rank(best):
            best = str(value).lower()
    return best


def exceeds_threshold(value: str | None, threshold: str) -> bool:
    return severity_rank(value) > severity_rank(threshold)
