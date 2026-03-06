#!/usr/bin/env python3
"""
ClickUp Desktop Notifier for macOS
Checks for new task assignments, task comment @mentions, and chat @mentions.
Runs on a configurable interval (set via launchd StartInterval). Mentions repeat every run until:
  - Task mentions: task is closed, OR user has replied after the mention
  - Chat mentions: user has posted in that channel after the mention
"""

import json
import os
import re
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────────────────
CLICKUP_API_TOKEN = os.environ.get("CLICKUP_API_TOKEN", "")
CLICKUP_API_BASE = "https://api.clickup.com/api/v2"

STATE_FILE = Path.home() / ".clickup_notifier_state.json"
LOOKBACK_HOURS = 72  # 3 days — covers weekends / leaves

NOTIFY_TASKS = os.environ.get("NOTIFY_TASKS", "true").strip().lower() == "true"
NOTIFY_CHAT  = os.environ.get("NOTIFY_CHAT",  "true").strip().lower() == "true"

_interval_sec = int(os.environ.get("START_INTERVAL", "1800"))
_interval_min = _interval_sec // 60
CHECK_INTERVAL_LABEL = f"{_interval_min} min" if _interval_min < 60 else f"{_interval_min // 60}h"


# ─── API Helpers ─────────────────────────────────────────────────────────────
def api_get(endpoint, params=None):
    url = f"{CLICKUP_API_BASE}{endpoint}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url)
    req.add_header("Authorization", CLICKUP_API_TOKEN)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[ERROR] API {e.code}: {endpoint} — {e.read().decode()[:200]}")
        return None
    except Exception as e:
        print(f"[ERROR] API request failed: {e}")
        return None


# ─── macOS Notification ──────────────────────────────────────────────────────
# Hardcode known Homebrew paths — launchd runs with a minimal PATH so
# `which terminal-notifier` always fails there.
_NOTIFIER_CANDIDATES = [
    "/opt/homebrew/bin/terminal-notifier",  # Apple Silicon
    "/usr/local/bin/terminal-notifier",     # Intel
]
_terminal_notifier_path = None

def _find_terminal_notifier():
    global _terminal_notifier_path
    if _terminal_notifier_path is None:
        _terminal_notifier_path = next(
            (p for p in _NOTIFIER_CANDIDATES if Path(p).exists()), ""
        )
    return _terminal_notifier_path


def send_notification(title, message, subtitle="", url=""):
    """Send a macOS notification. Clicking opens url in the default browser."""
    notifier = _find_terminal_notifier()
    if notifier:
        cmd = [notifier, "-title", title, "-message", message]
        if subtitle:
            cmd += ["-subtitle", subtitle]
        if url:
            # Use full path to open — launchd PATH doesn't include /usr/bin
            cmd += ["-execute", f"/usr/bin/open '{url}'"]
        subprocess.run(cmd, capture_output=True)
        return
    # Fallback: osascript (no click-through URL)
    t, m, s = (x.replace('"', '\\"') for x in (title, message, subtitle))
    script = f'display notification "{m}" with title "{t}"'
    if s:
        script += f' subtitle "{s}"'
    subprocess.run(["osascript", "-e", script], capture_output=True)


# ─── State Management ────────────────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"last_check_ts": None, "seen_task_ids": [], "conv_view_ids": []}


def save_state(state):
    state["seen_task_ids"] = state["seen_task_ids"][-500:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ─── Core Logic ──────────────────────────────────────────────────────────────
def get_user_info():
    data = api_get("/user")
    return data["user"] if data and "user" in data else None


def get_teams():
    data = api_get("/team")
    return data["teams"] if data and "teams" in data else []


def check_assigned_tasks(team_id, user_id, since_ts):
    data = api_get(f"/team/{team_id}/task", {
        "assignees[]": str(user_id),
        "order_by": "updated",
        "reverse": "true",
        "date_updated_gt": str(since_ts),
        "subtasks": "true",
        "include_closed": "false",
    })
    return data["tasks"] if data and "tasks" in data else []


def fetch_all_recent_tasks(team_id, since_ts):
    """Paginate through all open tasks updated in the lookback window."""
    tasks, page = [], 0
    while True:
        data = api_get(f"/team/{team_id}/task", {
            "order_by": "updated",
            "reverse": "true",
            "date_updated_gt": str(since_ts),
            "subtasks": "true",
            "include_closed": "false",
            "include_markdown_description": "true",
            "page": str(page),
        })
        batch = data.get("tasks", []) if data else []
        if not batch:
            break
        tasks.extend(batch)
        page += 1
    print(f"  [INFO] {len(tasks)} open tasks in window ({page} page(s))")
    return tasks


def _user_replied_after(comments, user_id, mention_date):
    """Return True if the user posted any comment/reply after mention_date."""
    return any(
        int(c.get("date", 0)) > mention_date
        and str(c.get("user", {}).get("id", "")) == str(user_id)
        for c in comments
    )


def _user_reacted(comment, user_id):
    """Return True if the user added any emoji reaction to this comment/message."""
    for reaction in comment.get("reactions", []):
        # Reactions can be a flat list {"user": {...}} or a dict keyed by emoji
        if isinstance(reaction, dict):
            if str(reaction.get("user", {}).get("id", "")) == str(user_id):
                return True
    return False


def _fetch_thread_replies(comment_id):
    """Fetch thread replies for a comment (returns [] on unsupported endpoint)."""
    data = api_get(f"/comment/{comment_id}/reply")
    if data and isinstance(data, dict):
        # Response is either {"replies": [...]} or {"comments": [...]}
        return data.get("replies") or data.get("comments") or []
    return []


def find_task_mentions(tasks, user_id, username=""):
    """
    Find @mentions in task comments AND task descriptions.
    Shares the comment fetch so description clear-checks add no extra API calls.

    Comment mention clears: user replied/reacted after the mention.
    Description mention clears: user has posted any comment after task creation,
      or reacted to any comment on the task.
    """
    mention_marker = f"#user_mention#{user_id}"
    desc_pattern = f"@{username}".lower() if username else None
    mentions = []
    for task in tasks:
        data = api_get(f"/task/{task['id']}/comment")
        comments = (data.get("comments") or []) if data else []
        task_url = task.get("url") or f"https://app.clickup.com/t/{task['id']}"

        # ── Description @mention ──────────────────────────────────────────────
        md_desc = task.get("markdown_description") or ""
        plain_desc = task.get("description") or ""
        desc_mentioned = (
            (mention_marker in md_desc)
            or _mention_in_quill_delta(plain_desc, user_id)
            or (desc_pattern and desc_pattern in plain_desc.lower())
        )
        if desc_mentioned:
            task_created = int(task.get("date_created", 0))
            # Cleared if user replied in comments after task creation
            desc_cleared = _user_replied_after(comments, user_id, task_created)
            # Also cleared if user reacted to any comment
            if not desc_cleared:
                desc_cleared = any(_user_reacted(c, user_id) for c in comments)
            if not desc_cleared:
                creator = task.get("creator", {}).get("username", "Someone")
                mentions.append({
                    "kind": "description",
                    "task_name": task.get("name", "Unknown"),
                    "commenter": creator,
                    "text_preview": plain_desc[:80],
                    "url": task_url,
                })

        # ── Comment @mentions ─────────────────────────────────────────────────
        comment_pattern = f"@{username}".lower() if username else None
        for comment in comments:
            mentioned = any(
                isinstance(part, dict)
                and part.get("type") == "tag"
                and str(part.get("user", {}).get("id", "")) == str(user_id)
                for part in comment.get("comment", [])
            )
            if not mentioned and comment_pattern:
                mentioned = comment_pattern in comment.get("comment_text", "").lower()
            if not mentioned:
                continue

            mention_date = int(comment.get("date", 0))

            if _user_replied_after(comments, user_id, mention_date):
                continue

            if comment.get("reply_count", 0) > 0:
                thread_replies = _fetch_thread_replies(comment["id"])
                if _user_replied_after(thread_replies, user_id, mention_date):
                    continue

            if _user_reacted(comment, user_id):
                continue

            mentions.append({
                "kind": "task",
                "task_name": task.get("name", "Unknown"),
                "commenter": comment.get("user", {}).get("username", "Someone"),
                "text_preview": comment.get("comment_text", "")[:80],
                "url": task_url,
            })
    return mentions


def _mention_in_quill_delta(desc, user_id):
    """
    Return True if the description is a Quill delta JSON string that contains
    a structured @mention of user_id ({"insert": {"mention": {"id": ...}}}).
    """
    if not desc.startswith('{"ops":'):
        return False
    try:
        delta = json.loads(desc)
        for op in delta.get("ops", []):
            insert = op.get("insert", "")
            if isinstance(insert, dict):
                mention = insert.get("mention", {})
                if str(mention.get("id", "")) == str(user_id):
                    return True
    except (json.JSONDecodeError, AttributeError):
        pass
    return False


def get_conv_view_ids(team_id, state):
    """
    Return list of {space_name, view_id, space_id} for all space chat views.
    Cached in state; refreshed every 24 h.
    """
    cache = state.get("conv_view_ids", [])
    cache_ts = state.get("conv_view_ids_ts", 0)
    if cache and (datetime.now().timestamp() - cache_ts) < 86400:
        return cache

    print("  [INFO] Refreshing chat channel index...")
    spaces_data = api_get(f"/team/{team_id}/space", {"archived": "false"})
    spaces = spaces_data.get("spaces", []) if spaces_data else []

    result = []
    for space in spaces:
        views_data = api_get(f"/space/{space['id']}/view")
        if not views_data:
            continue
        for view in views_data.get("views", []):
            if view.get("type") == "conversation":
                result.append({
                    "space_name": space.get("name", "?"),
                    "space_id": space["id"],
                    "view_id": view["id"],
                    "view_name": view.get("name", "Chat"),
                })

    state["conv_view_ids"] = result
    state["conv_view_ids_ts"] = datetime.now().timestamp()
    print(f"  [INFO] Found {len(result)} chat channel(s) across {len(spaces)} space(s)")
    return result


def find_chat_mentions(team_id, user_id, since_ts, state):
    """
    Find @mentions in space chat channels (conversation views).
    Skips a mention if the user has posted anything in that channel after it.
    """
    channels = get_conv_view_ids(team_id, state)
    mentions = []

    for ch in channels:
        data = api_get(f"/view/{ch['view_id']}/comment", {
            "date_created_gt": str(since_ts),
        })
        messages = data.get("comments", []) if data else []
        if not messages:
            continue

        for msg in messages:
            mentioned = any(
                isinstance(part, dict)
                and part.get("type") == "tag"
                and str(part.get("user", {}).get("id", "")) == str(user_id)
                for part in msg.get("comment", [])
            )
            if not mentioned:
                continue

            mention_date = int(msg.get("date", 0))
            if mention_date < since_ts:
                continue  # Older than lookback window (API ignores date_created_gt for chat)

            if _user_replied_after(messages, user_id, mention_date):
                continue  # Already replied in channel — considered cleared

            # Check thread replies if the mention has any
            if msg.get("reply_count", 0) > 0:
                thread_replies = _fetch_thread_replies(msg["id"])
                if _user_replied_after(thread_replies, user_id, mention_date):
                    continue

            # Emoji reaction on the mention = acknowledged
            if _user_reacted(msg, user_id):
                continue

            # Prefer an embedded chat/r/ link from the message itself;
            # fall back to the workspace Chat section.
            raw_text = msg.get("comment_text", "")
            embedded = re.search(r"app\.clickup\.com/\d+/chat/r/[\w-]+", raw_text)
            chat_url = (
                f"https://{embedded.group(0)}" if embedded
                else f"https://app.clickup.com/{team_id}/chat"
            )
            mentions.append({
                "kind": "chat",
                "task_name": f"{ch['space_name']} / {ch['view_name']}",
                "commenter": msg.get("user", {}).get("username", "Someone"),
                "text_preview": msg.get("comment_text", "")[:80],
                "url": chat_url,
            })

    return mentions


def main():
    print(f"\n{'='*50}")
    print(f"ClickUp Notifier — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
    print(f"[CONFIG] Tasks={NOTIFY_TASKS}  Chat={NOTIFY_CHAT}")

    if not CLICKUP_API_TOKEN:
        print("[ERROR] CLICKUP_API_TOKEN environment variable is not set.")
        send_notification("ClickUp Notifier", "CLICKUP_API_TOKEN not set.", subtitle="Error")
        return

    state = load_state()
    since_ts = int((datetime.now() - timedelta(hours=LOOKBACK_HOURS)).timestamp() * 1000)
    print(f"[INFO] Checking since: {datetime.fromtimestamp(since_ts / 1000).strftime('%Y-%m-%d %H:%M')}")

    user = get_user_info()
    if not user:
        print("[ERROR] Could not authenticate. Check your API token.")
        send_notification("ClickUp Notifier", "Authentication failed.", subtitle="Error")
        return

    user_id = user["id"]
    print(f"[INFO] Logged in as: {user.get('username', user.get('email'))} (ID: {user_id})")

    teams = get_teams()
    if not teams:
        print("[ERROR] No teams found.")
        return

    total_assignments = total_task_mentions = total_chat_mentions = 0

    for team in teams:
        team_id = team["id"]
        print(f"\n[INFO] Checking workspace: {team.get('name', 'Unknown')}")

        if NOTIFY_TASKS:
            # ── New assignments (notify once per task) ────────────────────────
            tasks = check_assigned_tasks(team_id, user_id, since_ts)
            new_tasks = [t for t in tasks if t["id"] not in state["seen_task_ids"]]
            for task in new_tasks:
                task_url = task.get("url") or f"https://app.clickup.com/t/{task['id']}"
                status = task.get("status", {}).get("status", "?")
                print(f"  [ASSIGN] {task.get('name', 'Untitled')} ({status})")
                print(f"           {task_url}")
                send_notification(
                    "ClickUp — New Assignment",
                    task.get("name", "Untitled"),
                    subtitle=status,
                    url=task_url,
                )
                state["seen_task_ids"].append(task["id"])
                total_assignments += 1

            # ── Task comment + description @mentions ──────────────────────────
            recent_tasks = fetch_all_recent_tasks(team_id, since_ts)
            task_mentions = find_task_mentions(recent_tasks, user_id, user.get("username", ""))
            for m in task_mentions:
                if m["kind"] == "description":
                    print(f"  [MENTION/DESC] @{m['commenter']} in description: {m['task_name']}")
                else:
                    print(f"  [MENTION/TASK] @{m['commenter']} in: {m['task_name']}")
                print(f"                 {m['url']}")
                if m["text_preview"]:
                    print(f"                 \"{m['text_preview']}\"")
                title = (
                    f"ClickUp — mentioned in task description"
                    if m["kind"] == "description"
                    else f"ClickUp — @{m['commenter']} mentioned you"
                )
                send_notification(
                    title,
                    m["task_name"],
                    subtitle=m["text_preview"] or "Click to open",
                    url=m["url"],
                )
                total_task_mentions += 1
        else:
            print("  [INFO] Task notifications disabled (NOTIFY_TASKS=false)")

        if NOTIFY_CHAT:
            # ── Chat @mentions ────────────────────────────────────────────────
            chat_mentions = find_chat_mentions(team_id, user_id, since_ts, state)
            for m in chat_mentions:
                print(f"  [MENTION/CHAT] @{m['commenter']} in: {m['task_name']}")
                print(f"                 {m['url']}")
                if m["text_preview"]:
                    print(f"                 \"{m['text_preview']}\"")
                send_notification(
                    f"ClickUp Chat — @{m['commenter']} mentioned you",
                    m["task_name"],
                    subtitle=m["text_preview"] or "Click to open",
                    url=m["url"],
                )
                total_chat_mentions += 1
        else:
            print("  [INFO] Chat notifications disabled (NOTIFY_CHAT=false)")

    if total_assignments == 0 and total_task_mentions == 0 and total_chat_mentions == 0:
        print("\n[INFO] No mentions or new assignments. All clear!")
    else:
        print(f"\n[SUMMARY] {total_assignments} assignment(s), "
              f"{total_task_mentions} task mention(s), "
              f"{total_chat_mentions} chat mention(s)")

    state["last_check_ts"] = int(datetime.now().timestamp() * 1000)
    save_state(state)
    print(f"[DONE] Next check in ~{CHECK_INTERVAL_LABEL}.")


if __name__ == "__main__":
    main()
