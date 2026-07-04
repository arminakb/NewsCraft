def redact_secret(value):
    if not value:
        return value
    text = str(value)
    return text[:4] + "..." if len(text) > 4 else "***"
