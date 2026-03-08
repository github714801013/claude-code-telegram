"""File reading and processing utilities."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import structlog

logger = structlog.get_logger()


def read_jsonl_file(file_path: Path, max_lines: int = 0) -> List[Dict[str, Any]]:
    """Read and parse JSONL file with proper error handling.

    Args:
        file_path: Path to JSONL file
        max_lines: Maximum number of lines to read (0 for unlimited)

    Returns:
        List of parsed JSON objects

    Raises:
        FileNotFoundError: If file does not exist
        json.JSONDecodeError: If JSON parsing fails
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    results = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue

                if max_lines > 0 and i >= max_lines:
                    break

                try:
                    data = json.loads(line)
                    results.append(data)
                except json.JSONDecodeError as e:
                    logger.warning(
                        "Failed to parse JSONL line",
                        file=str(file_path),
                        line_number=i,
                        error=str(e)
                    )
                    # Continue with next line
                    continue

    except (IOError, OSError) as e:
        logger.error("Failed to read JSONL file", file=str(file_path), error=str(e))
        raise

    return results


def find_jsonl_file_by_session_id(session_id: str) -> Optional[Path]:
    """Find JSONL file for a given session ID.

    Searches in ~/.claude/projects/*/{session_id}.jsonl

    Args:
        session_id: Session ID to search for

    Returns:
        Path to JSONL file if found, None otherwise
    """
    import glob
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return None

    pattern = projects_dir / "*" / f"{session_id}.jsonl"
    matches = list(glob.glob(str(pattern)))
    return Path(matches[0]) if matches else None


def read_file_safely(
    file_path: Path,
    encoding: str = 'utf-8',
    max_size: int = 1024 * 1024  # 1MB
) -> Optional[str]:
    """Read file safely with size and encoding validation.

    Args:
        file_path: Path to file
        encoding: File encoding
        max_size: Maximum file size to read (in bytes)

    Returns:
        File content if successful, None otherwise
    """
    try:
        # Check file size
        if file_path.stat().st_size > max_size:
            logger.warning("File too large", file=str(file_path), max_size=max_size)
            return None

        with open(file_path, 'r', encoding=encoding) as f:
            return f.read()

    except FileNotFoundError:
        logger.warning("File not found", file=str(file_path))
        return None
    except UnicodeDecodeError as e:
        logger.warning("Failed to decode file", file=str(file_path), encoding=encoding, error=str(e))
        return None
    except (IOError, OSError) as e:
        logger.warning("Failed to read file", file=str(file_path), error=str(e))
        return None


def extract_message_content(data: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Extract role and text content from Claude message data.

    Args:
        data: JSON data from Claude CLI session

    Returns:
        Tuple of (role, text) if valid message, None otherwise
    """
    try:
        # Support different message formats
        if "message" in data:
            msg = data["message"]
            if not isinstance(msg, dict):
                return None
        else:
            msg = data

        role = msg.get("role")
        if role not in ("user", "assistant"):
            return None

        content = msg.get("content", "")

        # Handle different content formats
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            text = " ".join(text_parts).strip()
        else:
            return None

        if not text:
            return None

        return (role, text)

    except (KeyError, AttributeError, TypeError) as e:
        logger.debug("Failed to extract message content", error=str(e))
        return None