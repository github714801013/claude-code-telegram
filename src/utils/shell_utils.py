"""Shell argument parsing and validation utilities."""

import shlex
from typing import List


def split_shell_args(text: str) -> List[str]:
    """Safely split shell arguments, respecting quotes.

    Uses shlex.split() but falls back to simple whitespace split if parsing fails.

    Args:
        text: Shell command text to split

    Returns:
        List of split arguments
    """
    try:
        return shlex.split(text)
    except ValueError:
        # If quotes are mismatched, fall back to simple whitespace split
        # This is less accurate but still safe for detecting dangerous flags
        return text.split()


def extract_command_args(text: str, command: str) -> str:
    """Extract arguments from a command like '/cc args' or '/cc@botname args'.

    Args:
        text: Full command text
        command: Command name without slash (e.g., 'cc')

    Returns:
        The argument string (trimmed), or empty string if no arguments.
    """
    import re
    # Handle /command@botname format
    pattern = rf"^/{re.escape(command)}(?:@\w+)?\s+"
    match = re.match(pattern, text)
    if not match:
        return ""

    # Return everything after the matched prefix, stripped
    return text[match.end():].strip()


def is_dangerous_flag(arg: str) -> bool:
    """Check if argument contains dangerous flags.

    Args:
        arg: Shell argument to check

    Returns:
        True if argument contains dangerous flag patterns
    """
    # Check for dangerous flags that could bypass security
    dangerous_prefixes = [
        "--dangerously",
        "--no-sandbox",
        "--insecure",
        "--allow-file-access",
        "--disable-web-security",
    ]

    return any(arg.startswith(prefix) for prefix in dangerous_prefixes)


def validate_shell_args(args_text: str, max_length: int = 2000) -> str:
    """Validate shell arguments for security and length.

    Args:
        args_text: Arguments text to validate
        max_length: Maximum allowed length

    Returns:
        Error message if validation fails, empty string if valid
    """
    if not args_text:
        return "参数不能为空"

    if len(args_text) > max_length:
        return f"参数过长（最大 {max_length} 字符）"

    args = split_shell_args(args_text)
    for arg in args:
        if is_dangerous_flag(arg):
            return "参数包含危险标记"

    return ""