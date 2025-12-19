"""String sanitization utilities."""

import re


def sanitize_filename(name: str) -> str:
    """Sanitizes a string to be a valid filename.

    Args:
        name: The string to sanitize.

    Returns:
        A URL-safe, filesystem-safe version of the name.
    """
    # Replace slashes and backslashes with a space
    s = re.sub(r"[/\\]+", " ", name)
    # Remove invalid filename characters
    s = re.sub(r'[<>:"|?*]', "", s)
    # Replace multiple spaces/hyphens with a single hyphen
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    # Truncate to a reasonable length
    return s[:100]
