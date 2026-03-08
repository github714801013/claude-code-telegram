"""Utilities for handling /cc command operations."""

import argparse
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ...claude.facade import ClaudeIntegration
from ...config.settings import Settings
from ...security.audit import AuditLogger
from ...storage.repositories import SessionRepository
from ...utils.shell_utils import split_shell_args, validate_shell_args
from ..utils.html_format import escape_html


def parse_cc_arguments(args_text: str) -> Tuple[argparse.Namespace, List[str]]:
    """Parse /cc command arguments.

    Args:
        args_text: Raw arguments text from user

    Returns:
        Tuple of (parsed_args, unknown_args)
    """
    parser = argparse.ArgumentParser(prog="/cc", add_help=False)
    parser.add_argument("-r", "--resume", nargs="?", const="last", default=None)
    parser.add_argument("-p", "--print", action="store_true")
    parser.add_argument("prompt_args", nargs=argparse.REMAINDER)

    try:
        parsed_args, unknown = parser.parse_known_args(split_shell_args(args_text))
        return parsed_args, unknown
    except (SystemExit, ValueError):
        raise ValueError("参数解析失败，请检查语法。")


async def validate_cc_arguments(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    args_text: str,
    audit_logger: Optional[AuditLogger] = None
) -> bool:
    """Validate /cc command arguments.

    Args:
        update: Telegram update
        context: Context
        args_text: Arguments text to validate
        audit_logger: Optional audit logger

    Returns:
        True if arguments are valid, False otherwise
    """
    user_id = update.effective_user.id

    if not args_text:
        await update.message.reply_text("用法：/cc <claude 参数>")
        if audit_logger:
            await audit_logger.log_security_event(
                user_id=user_id,
                event_type="cc_rejected",
                event_data={"reason": "empty_args", "args_len": 0, "snippet": ""},
                success=False,
            )
        return False

    # 使用统一的参数验证
    error_msg = validate_shell_args(args_text, max_length=2000)
    if error_msg:
        await update.message.reply_text(error_msg)
        if audit_logger:
            await audit_logger.log_security_event(
                user_id=user_id,
                event_type="cc_rejected",
                event_data={
                    "reason": "too_long" if "过长" in error_msg else "validation_failed",
                    "args_len": len(args_text),
                    "snippet": args_text[:200]
                },
                success=False,
            )
        return False

    return True


def get_effective_working_directory(
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    project_root: Optional[Path] = None
) -> Path:
    """Get effective working directory with project thread support.

    Args:
        settings: Application settings
        context: Telegram context
        project_root: Optional project root from thread context

    Returns:
        Effective working directory path
    """
    # Determine project root if not provided
    if not project_root and settings.enable_project_threads:
        thread_context = context.user_data.get("_thread_context")
        if thread_context and "project_root" in thread_context:
            project_root = Path(thread_context["project_root"]).resolve()

    current_dir = context.user_data.get("current_directory")

    if current_dir:
        # Check if it's valid within the project root
        if project_root:
            try:
                current_dir.resolve().relative_to(project_root)
            except ValueError:
                current_dir = project_root
    else:
        current_dir = project_root if project_root else settings.approved_directory

    return current_dir


def extract_prompt_from_args(
    parsed_args: argparse.Namespace,
    unknown_args: List[str]
) -> str:
    """Extract prompt from parsed arguments.

    Args:
        parsed_args: Parsed arguments from argparse
        unknown_args: Unknown arguments from parse_known_args

    Returns:
        Prompt string for Claude
    """
    prompt_parts = []
    for token in unknown_args:
        if not token.startswith("-"):
            prompt_parts.append(token)
    prompt_parts.extend(parsed_args.prompt_args)

    if not prompt_parts and parsed_args.resume:
        return "Please continue where we left off"
    elif not prompt_parts:
        return "Hello"
    else:
        prompt = " ".join(prompt_parts)
        if prompt.startswith(("'", '"')) and prompt.endswith(("'", '"')):
            prompt = prompt[1:-1]
        return prompt


async def get_combined_sessions_list(
    storage: Optional[SessionRepository],
    current_dir: Path,
    include_cli: bool = True
) -> List[Dict[str, Any]]:
    """Get combined list of bot sessions and CLI sessions.

    Args:
        storage: Storage repository for bot sessions
        current_dir: Current working directory
        include_cli: Whether to include CLI sessions

    Returns:
        List of session dictionaries
    """
    combined_sessions = []

    if storage:
        # Get bot database sessions
        db_sessions = await storage.sessions.get_sessions_by_project(str(current_dir))
        for s in db_sessions:
            combined_sessions.append({
                "session_id": s.session_id,
                "session_name": getattr(s, "session_name", "") or s.session_id[:6],
                "last_used": getattr(s, "last_used", getattr(s, "created_at", None)),
                "message_count": getattr(s, "message_count", 0),
                "is_cli": False
            })

    if include_cli:
        # Get local CLI transcripts
        try:
            from .command import _get_local_cli_sessions
            cli_sessions = await _get_local_cli_sessions(current_dir)
            combined_sessions.extend(cli_sessions)
        except Exception:
            # Silently fail for CLI sessions - they're optional
            pass

    # Sort by last_used desc
    combined_sessions.sort(
        key=lambda x: x["last_used"].timestamp() if x["last_used"] else 0,
        reverse=True
    )

    return combined_sessions


async def create_session_selection_keyboard(
    combined_sessions: List[Dict[str, Any]],
    context: ContextTypes.DEFAULT_TYPE,
    max_sessions: int = 10
) -> Tuple[str, InlineKeyboardMarkup]:
    """Create session selection keyboard.

    Args:
        combined_sessions: List of session dictionaries
        context: Telegram context
        max_sessions: Maximum number of sessions to show

    Returns:
        Tuple of (message_text, keyboard_markup)
    """
    if not combined_sessions:
        return "该目录下没有找到最近的活动会话。", InlineKeyboardMarkup([])

    if "session_names" not in context.user_data:
        context.user_data["session_names"] = {}

    keyboard = []

    for s in combined_sessions[:max_sessions]:
        date_ts = s["last_used"]
        date_str = date_ts.astimezone().strftime("%m-%d %H:%M") if date_ts else "Unknown"
        msgs = s["message_count"]

        full_name = s["session_name"] or ""
        if full_name:
            full_name = full_name.replace("\n", " ").strip()
            if len(full_name) > 50:
                full_name = full_name[:49] + "…"
        else:
            full_name = s["session_id"][:6]

        context.user_data["session_names"][s["session_id"]] = full_name

        name = full_name
        if len(name) > 15:
            name = name[:14] + "…"

        icon = "💻" if s["is_cli"] else "📄"
        btn_text = f"{icon} {name} ({date_str}, {msgs}条)"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"resume:{s['session_id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    return "请选择要恢复的历史会话：", reply_markup