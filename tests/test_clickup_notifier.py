#!/usr/bin/env python3
import json
import unittest
from unittest.mock import patch

import clickup_notifier as cu

USER_ID = "123"
USERNAME = "testuser"

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _tag_part(user_id):
    return {"type": "tag", "user": {"id": user_id}}

def _comment(comment_id, user_id, date, text="", parts=None, reply_count=0, reactions=None):
    return {
        "id": comment_id,
        "user": {"id": user_id},
        "date": str(date),
        "comment_text": text,
        "comment": parts or [],
        "reply_count": reply_count,
        "reactions": reactions or [],
    }

def _task(task_id, name="Task", desc="", md_desc="", date_created=1000):
    return {
        "id": task_id,
        "name": name,
        "description": desc,
        "markdown_description": md_desc,
        "date_created": str(date_created),
        "creator": {"username": "alice"},
        "url": f"https://app.clickup.com/t/{task_id}",
    }


# ─── _user_replied_after ──────────────────────────────────────────────────────

class TestUserRepliedAfter(unittest.TestCase):

    def test_replied_after_mention(self):
        comments = [_comment("c1", USER_ID, 2000)]
        self.assertTrue(cu._user_replied_after(comments, USER_ID, 1000))

    def test_replied_before_mention(self):
        comments = [_comment("c1", USER_ID, 500)]
        self.assertFalse(cu._user_replied_after(comments, USER_ID, 1000))

    def test_different_user_replied(self):
        comments = [_comment("c1", "99", 2000)]
        self.assertFalse(cu._user_replied_after(comments, USER_ID, 1000))

    def test_empty_comments(self):
        self.assertFalse(cu._user_replied_after([], USER_ID, 1000))


# ─── _user_reacted ────────────────────────────────────────────────────────────

class TestUserReacted(unittest.TestCase):

    def test_user_reacted(self):
        comment = {"reactions": [{"user": {"id": USER_ID}}]}
        self.assertTrue(cu._user_reacted(comment, USER_ID))

    def test_other_user_reacted(self):
        comment = {"reactions": [{"user": {"id": "99"}}]}
        self.assertFalse(cu._user_reacted(comment, USER_ID))

    def test_no_reactions(self):
        self.assertFalse(cu._user_reacted({"reactions": []}, USER_ID))


# ─── _mention_in_quill_delta ──────────────────────────────────────────────────

class TestMentionInQuillDelta(unittest.TestCase):

    def test_structured_mention_matches(self):
        delta = json.dumps({"ops": [{"insert": {"mention": {"id": USER_ID}}}]})
        self.assertTrue(cu._mention_in_quill_delta(delta, USER_ID))

    def test_structured_mention_wrong_user(self):
        delta = json.dumps({"ops": [{"insert": {"mention": {"id": "99"}}}]})
        self.assertFalse(cu._mention_in_quill_delta(delta, USER_ID))

    def test_not_quill_delta(self):
        self.assertFalse(cu._mention_in_quill_delta("plain text", USER_ID))

    def test_invalid_json(self):
        self.assertFalse(cu._mention_in_quill_delta('{"ops": broken}', USER_ID))


# ─── find_task_mentions — comment detection ───────────────────────────────────

class TestFindTaskMentionsComments(unittest.TestCase):

    def _run(self, comments, tasks=None):
        if tasks is None:
            tasks = [_task("t1")]
        with patch.object(cu, "api_get", return_value={"comments": comments}):
            with patch.object(cu, "_fetch_thread_replies", return_value=[]):
                return cu.find_task_mentions(tasks, USER_ID, USERNAME)

    def test_structured_tag_mention_fires(self):
        c = _comment("c1", "99", 2000, parts=[_tag_part(USER_ID)])
        result = self._run([c])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["kind"], "task")

    def test_plain_text_mention_fires(self):
        # The bug fix: no structured tag, just @username in comment_text
        c = _comment("c1", "99", 2000, text=f"@{USERNAME}, any update on this?")
        result = self._run([c])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["kind"], "task")

    def test_plain_text_mention_case_insensitive(self):
        c = _comment("c1", "99", 2000, text=f"@{USERNAME.upper()}, please check")
        result = self._run([c])
        self.assertEqual(len(result), 1)

    def test_no_mention_no_fire(self):
        c = _comment("c1", "99", 2000, text="no mention here")
        result = self._run([c])
        self.assertEqual(len(result), 0)

    def test_suppressed_if_user_replied_after(self):
        c_mention = _comment("c1", "99", 2000, parts=[_tag_part(USER_ID)])
        c_reply   = _comment("c2", USER_ID, 3000)
        result = self._run([c_mention, c_reply])
        self.assertEqual(len(result), 0)

    def test_suppressed_if_user_replied_before(self):
        # User replied BEFORE the mention — should still fire
        c_reply   = _comment("c2", USER_ID, 500)
        c_mention = _comment("c1", "99", 2000, parts=[_tag_part(USER_ID)])
        result = self._run([c_reply, c_mention])
        self.assertEqual(len(result), 1)

    def test_suppressed_if_user_reacted(self):
        c = _comment("c1", "99", 2000, parts=[_tag_part(USER_ID)],
                     reactions=[{"user": {"id": USER_ID}}])
        result = self._run([c])
        self.assertEqual(len(result), 0)

    def test_suppressed_if_thread_reply_by_user(self):
        c = _comment("c1", "99", 2000, parts=[_tag_part(USER_ID)], reply_count=1)
        thread_reply = _comment("r1", USER_ID, 3000)
        with patch.object(cu, "api_get", return_value={"comments": [c]}):
            with patch.object(cu, "_fetch_thread_replies", return_value=[thread_reply]):
                result = cu.find_task_mentions([_task("t1")], USER_ID, USERNAME)
        self.assertEqual(len(result), 0)

    def test_commenter_username_in_result(self):
        c = _comment("c1", "99", 2000, text=f"@{USERNAME} ping")
        c["user"]["username"] = "alice"
        result = self._run([c])
        self.assertEqual(result[0]["commenter"], "alice")


# ─── find_task_mentions — description detection ───────────────────────────────

class TestFindTaskMentionsDescription(unittest.TestCase):

    def _run(self, task, comments=None):
        with patch.object(cu, "api_get", return_value={"comments": comments or []}):
            return cu.find_task_mentions([task], USER_ID, USERNAME)

    def test_marker_in_markdown_desc_fires(self):
        t = _task("t1", md_desc=f"hey #user_mention#{USER_ID} check this")
        result = self._run(t)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["kind"], "description")

    def test_quill_delta_mention_fires(self):
        delta = json.dumps({"ops": [{"insert": {"mention": {"id": USER_ID}}}]})
        t = _task("t1", desc=delta)
        result = self._run(t)
        self.assertEqual(len(result), 1)

    def test_plain_text_at_username_in_desc_fires(self):
        t = _task("t1", desc=f"@{USERNAME} please review")
        result = self._run(t)
        self.assertEqual(len(result), 1)

    def test_suppressed_if_user_replied_after_creation(self):
        t = _task("t1", md_desc=f"#user_mention#{USER_ID}", date_created=1000)
        reply = _comment("c1", USER_ID, 2000)
        result = self._run(t, comments=[reply])
        self.assertEqual(len(result), 0)

    def test_suppressed_if_user_reacted_to_any_comment(self):
        t = _task("t1", md_desc=f"#user_mention#{USER_ID}", date_created=1000)
        c = _comment("c1", "99", 500, reactions=[{"user": {"id": USER_ID}}])
        result = self._run(t, comments=[c])
        self.assertEqual(len(result), 0)

    def test_no_mention_no_fire(self):
        t = _task("t1", desc="nothing here", md_desc="also nothing")
        result = self._run(t)
        self.assertEqual(len(result), 0)


# ─── find_chat_mentions ───────────────────────────────────────────────────────

class TestFindChatMentions(unittest.TestCase):

    SINCE = 1000
    STATE = {"conv_view_ids": [{"space_name": "Dev", "view_name": "Chat", "view_id": "v1"}],
             "conv_view_ids_ts": 9_999_999_999}

    def _msg(self, msg_id, user_id, date, text="", parts=None, reply_count=0, reactions=None):
        return _comment(msg_id, user_id, date, text=text, parts=parts or [],
                        reply_count=reply_count, reactions=reactions)

    def _run(self, messages, thread_replies=None):
        with patch.object(cu, "api_get", return_value={"comments": messages}):
            with patch.object(cu, "_fetch_thread_replies", return_value=thread_replies or []):
                return cu.find_chat_mentions("team1", USER_ID, self.SINCE, dict(self.STATE))

    def test_structured_tag_mention_fires(self):
        msg = self._msg("m1", "99", 2000, parts=[_tag_part(USER_ID)])
        result = self._run([msg])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["kind"], "chat")

    def test_older_than_since_suppressed(self):
        msg = self._msg("m1", "99", 500, parts=[_tag_part(USER_ID)])
        result = self._run([msg])
        self.assertEqual(len(result), 0)

    def test_suppressed_if_user_replied_in_channel(self):
        msg   = self._msg("m1", "99",     2000, parts=[_tag_part(USER_ID)])
        reply = self._msg("m2", USER_ID,  3000)
        result = self._run([msg, reply])
        self.assertEqual(len(result), 0)

    def test_suppressed_if_user_reacted(self):
        msg = self._msg("m1", "99", 2000, parts=[_tag_part(USER_ID)],
                        reactions=[{"user": {"id": USER_ID}}])
        result = self._run([msg])
        self.assertEqual(len(result), 0)

    def test_suppressed_if_thread_reply_by_user(self):
        msg = self._msg("m1", "99", 2000, parts=[_tag_part(USER_ID)], reply_count=1)
        thread_reply = self._msg("r1", USER_ID, 3000)
        result = self._run([msg], thread_replies=[thread_reply])
        self.assertEqual(len(result), 0)

    def test_no_mention_no_fire(self):
        msg = self._msg("m1", "99", 2000, text="hey team")
        result = self._run([msg])
        self.assertEqual(len(result), 0)

    def test_embedded_url_used_when_present(self):
        raw = "check https://app.clickup.com/12345/chat/r/abc-xyz for context"
        msg = self._msg("m1", "99", 2000, text=raw, parts=[_tag_part(USER_ID)])
        result = self._run([msg])
        self.assertEqual(result[0]["url"], "https://app.clickup.com/12345/chat/r/abc-xyz")

    def test_fallback_url_when_no_embedded(self):
        msg = self._msg("m1", "99", 2000, parts=[_tag_part(USER_ID)])
        result = self._run([msg])
        self.assertEqual(result[0]["url"], "https://app.clickup.com/team1/chat")


if __name__ == "__main__":
    unittest.main(verbosity=2)
