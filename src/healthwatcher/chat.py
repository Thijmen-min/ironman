"""Embedded coach chat: a Claude Code session (Claude Agent SDK) per conversation.

Runs the user's installed `claude` CLI (and its login) with this project as cwd, so it picks up
CLAUDE.md, and gives it the healthwatcher + garmin MCP servers. Text streams to the UI as
server-sent events; tool calls that change things outside the local notebook are relayed to the
UI for approval.
"""

import asyncio
import json
import logging
import os
import shutil
import sys
import uuid
import warnings
from datetime import date
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from . import db
from .config import DATA_DIR, GARMIN_TOKENS, PROJECT_ROOT

log = logging.getLogger(__name__)
# Always use the Claude Code login (claude.ai subscription), never pay-as-you-go API billing:
# the CLI would prefer an API key if one were present in the environment.
for _k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
    os.environ.pop(_k, None)
# AUTO_ALLOW deliberately bypasses the permission callback for read-only tools.
warnings.filterwarnings("ignore", message="can_use_tool will not be invoked")

# Read-only / local tools that never need a prompt.
AUTO_ALLOW = ["mcp__healthwatcher", "Read", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite"]
# Live-Garmin tools that only read.
GARMIN_READ_PREFIXES = ("get_", "list_", "count_", "download_", "search_")
FILE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")

COACH_PROMPT = """
You are running inside the HealthWatcher desktop app as the athlete's personal coach and trainer
(see CLAUDE.md and data/athlete.md). The athlete chats with you in a side panel next to their
TrainingPeaks-style dashboard.

- A message may start with "[Context: ...]" naming the day, activity, week or chart the athlete is
  looking at. Look it up with the healthwatcher tools (get_day, get_activity_detail,
  get_weekly_summary, query_sql, ...) before answering, and refer to the specific numbers.
- Today is {today}. Data syncs from Garmin every ~20 minutes; call sync_now if they ask about
  something that just happened.
- Be conversational, direct and concise - this is a chat, not a report. Use a small markdown table
  only when comparing numbers. Reply in the athlete's language (Dutch or English).
- Writing to Garmin Connect (creating, scheduling or deleting workouts) needs the athlete's OK: propose
  first. The app also asks them to approve each such tool call.
- You may update data/athlete.md and write plans to data/plans/ freely; other files need approval.
"""


def _find_exe(name: str, *fallbacks: Path) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for f in fallbacks:
        for cand in (f, f.with_suffix(".exe")):
            if cand.exists():
                return str(cand)
    return None


def claude_cli() -> str | None:
    return _find_exe("claude", Path.home() / ".local" / "bin" / "claude")


def _uvx() -> str:
    winget = Path.home() / "AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe/uvx"
    return _find_exe("uvx", winget, Path.home() / ".local" / "bin" / "uvx") or "uvx"


def mcp_servers() -> dict[str, Any]:
    return {
        "healthwatcher": {"type": "stdio", "command": sys.executable, "args": ["-m", "healthwatcher.mcp_server"]},
        "garmin": {
            "type": "stdio",
            "command": _uvx(),
            "args": ["--python", "3.12", "--from", "git+https://github.com/Taxuspt/garmin_mcp", "garmin-mcp"],
            "env": {"GARMINTOKENS": GARMIN_TOKENS},
        },
    }


def _in_notebook(path: str | None) -> bool:
    if not path:
        return False
    try:
        p = Path(path)
        p = (p if p.is_absolute() else PROJECT_ROOT / p).resolve()
        return p.is_relative_to(DATA_DIR.resolve()) and p.suffix.lower() in (".md", ".txt", ".csv", ".json")
    except (OSError, ValueError):
        return False


def _auto_allowed(name: str, tool_input: dict[str, Any]) -> bool:
    if name.startswith("mcp__healthwatcher__"):
        return True
    if name.startswith("mcp__garmin__"):
        return name.removeprefix("mcp__garmin__").startswith(GARMIN_READ_PREFIXES)
    if name in FILE_TOOLS:
        return _in_notebook(tool_input.get("file_path") or tool_input.get("notebook_path"))
    return name in AUTO_ALLOW


def _short(v: Any, n: int = 600) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return s if len(s) <= n else s[:n] + " …"


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


class Conversation:
    def __init__(self, cid: str, sdk_session_id: str | None):
        self.id = cid
        self.sdk_session_id = sdk_session_id
        self.client: ClaudeSDKClient | None = None
        self.queue: asyncio.Queue | None = None
        self.pending: dict[str, asyncio.Future] = {}
        self.busy = False

    def options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            cwd=str(PROJECT_ROOT),
            cli_path=claude_cli(),
            system_prompt={"type": "preset", "preset": "claude_code",
                           "append": COACH_PROMPT.format(today=date.today().strftime("%A %d %B %Y"))},
            setting_sources=["user", "project"],
            mcp_servers=mcp_servers(),
            strict_mcp_config=True,
            allowed_tools=AUTO_ALLOW,
            can_use_tool=self._can_use_tool,
            include_partial_messages=True,
            resume=self.sdk_session_id,
        )

    async def _can_use_tool(self, name: str, tool_input: dict[str, Any], ctx: ToolPermissionContext):
        if _auto_allowed(name, tool_input):
            return PermissionResultAllow()
        if self.queue is None:
            return PermissionResultDeny(message="No active chat to ask the user.")
        pid = uuid.uuid4().hex[:12]
        fut = asyncio.get_running_loop().create_future()
        self.pending[pid] = fut
        await self.queue.put({"type": "permission", "id": pid, "tool": name, "input": _short(tool_input, 2000)})
        try:
            allow = await asyncio.wait_for(fut, timeout=900)
        except asyncio.TimeoutError:
            allow = False
        finally:
            self.pending.pop(pid, None)
        _save(self.id, "tool", json.dumps({"name": name, "permission": "allowed" if allow else "denied"}))
        if allow:
            return PermissionResultAllow()
        return PermissionResultDeny(message="The athlete declined this action in the app. Ask what they'd prefer.")

    async def ensure_client(self) -> ClaudeSDKClient:
        if self.client is None:
            if not claude_cli():
                raise RuntimeError("Claude Code CLI not found - install it and log in (`claude`).")
            self.client = ClaudeSDKClient(options=self.options())
            await self.client.connect()
        return self.client

    async def close(self) -> None:
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:  # process may already be gone
                pass
            self.client = None

    async def run_turn(self, prompt: str) -> None:
        q = self.queue
        assert q is not None
        try:
            client = await self.ensure_client()
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, StreamEvent):
                    ev = msg.event
                    if (not msg.parent_tool_use_id and ev.get("type") == "content_block_delta"
                            and ev.get("delta", {}).get("type") == "text_delta"):
                        await q.put({"type": "delta", "text": ev["delta"]["text"]})
                elif isinstance(msg, AssistantMessage):
                    if msg.parent_tool_use_id:
                        continue  # sub-agent internals
                    if msg.session_id:
                        self._remember_session(msg.session_id)
                    for b in msg.content:
                        if isinstance(b, TextBlock) and b.text.strip():
                            _save(self.id, "assistant", b.text)
                            await q.put({"type": "text", "text": b.text})
                        elif isinstance(b, ToolUseBlock):
                            _save(self.id, "tool", json.dumps({"id": b.id, "name": b.name, "input": _short(b.input)}))
                            await q.put({"type": "tool", "id": b.id, "name": b.name, "input": _short(b.input, 300)})
                    if msg.error:
                        await q.put({"type": "error", "message": str(msg.error)})
                elif isinstance(msg, UserMessage) and isinstance(msg.content, list) and not msg.parent_tool_use_id:
                    for b in msg.content:
                        if isinstance(b, ToolResultBlock):
                            await q.put({"type": "tool_result", "id": b.tool_use_id, "is_error": bool(b.is_error),
                                         "preview": _short(_result_text(b.content), 300)})
                elif isinstance(msg, SystemMessage) and msg.subtype == "init":
                    sid = msg.data.get("session_id")
                    if sid:
                        self._remember_session(sid)
                elif isinstance(msg, ResultMessage):
                    self._remember_session(msg.session_id)
                    await q.put({"type": "done", "cost_usd": msg.total_cost_usd, "duration_ms": msg.duration_ms,
                                 "is_error": msg.is_error, "turns": msg.num_turns})
        except Exception as e:
            log.exception("chat turn failed")
            _save(self.id, "error", str(e))
            await q.put({"type": "error", "message": str(e)})
            await self.close()  # start fresh (resuming the session) next time
        finally:
            self.busy = False
            await q.put(None)

    def _remember_session(self, sid: str) -> None:
        if sid and sid != self.sdk_session_id:
            self.sdk_session_id = sid
            with db.session() as c:
                c.execute("UPDATE chat_conversations SET sdk_session_id=?, updated_at=? WHERE id=?",
                          (sid, db.now_iso(), self.id))


_conversations: dict[str, Conversation] = {}


def _save(cid: str, role: str, content: str, context: str | None = None) -> None:
    with db.session() as c:
        c.execute("INSERT INTO chat_messages(conversation_id, role, content, context, created_at) VALUES (?,?,?,?,?)",
                  (cid, role, content, context, db.now_iso()))
        c.execute("UPDATE chat_conversations SET updated_at=? WHERE id=?", (db.now_iso(), cid))


def get_conversation(cid: str | None, first_message: str) -> Conversation:
    if cid and cid in _conversations:
        return _conversations[cid]
    if cid:
        row = db.rows("SELECT * FROM chat_conversations WHERE id=?", (cid,))
        if row:
            conv = Conversation(cid, row[0]["sdk_session_id"])
            _conversations[cid] = conv
            return conv
    cid = uuid.uuid4().hex[:16]
    title = first_message.strip().splitlines()[0][:80] if first_message.strip() else "New chat"
    with db.session() as c:
        c.execute("INSERT INTO chat_conversations(id, title, created_at, updated_at) VALUES (?,?,?,?)",
                  (cid, title, db.now_iso(), db.now_iso()))
    conv = Conversation(cid, None)
    _conversations[cid] = conv
    return conv


async def send(cid: str | None, message: str, context: str | None):
    """Start a turn; yields event dicts (first one names the conversation)."""
    conv = get_conversation(cid, message)
    if conv.busy:
        yield {"type": "error", "message": "Claude is still answering the previous message."}
        return
    conv.busy = True
    conv.queue = asyncio.Queue()
    _save(conv.id, "user", message, context)
    prompt = f"[Context: {context}]\n{message}" if context else message
    yield {"type": "conversation", "id": conv.id}
    task = asyncio.create_task(conv.run_turn(prompt))
    while True:
        ev = await conv.queue.get()
        if ev is None:
            break
        yield ev
    await task


def answer_permission(cid: str, pid: str, allow: bool) -> bool:
    conv = _conversations.get(cid)
    fut = conv.pending.get(pid) if conv else None
    if fut and not fut.done():
        fut.set_result(allow)
        return True
    return False


async def interrupt(cid: str) -> None:
    conv = _conversations.get(cid)
    if conv and conv.client and conv.busy:
        for fut in conv.pending.values():
            if not fut.done():
                fut.set_result(False)
        await conv.client.interrupt()


async def delete(cid: str) -> None:
    conv = _conversations.pop(cid, None)
    if conv:
        await conv.close()
    with db.session() as c:
        c.execute("DELETE FROM chat_messages WHERE conversation_id=?", (cid,))
        c.execute("DELETE FROM chat_conversations WHERE id=?", (cid,))


async def shutdown() -> None:
    for conv in list(_conversations.values()):
        await conv.close()


def history(cid: str) -> list[dict[str, Any]]:
    return db.rows("SELECT role, content, context, created_at FROM chat_messages WHERE conversation_id=? ORDER BY id", (cid,))


def conversations() -> list[dict[str, Any]]:
    return db.rows("SELECT id, title, updated_at FROM chat_conversations ORDER BY updated_at DESC LIMIT 50")
