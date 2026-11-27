"""
QA Tests for RFC-011:
- bot_id required enforcement & static call-site scan
- CONFIRM_SKILLS review, replace rule, 1-step undo, HTML escaping, idempotency
- Per-bot tracked_companies_url validation & cached active companies summary
"""
import ast
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.ext import ConversationHandler

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.bots import validate_tracked_companies_url
from db.career_sources import get_tracked_companies_summary, invalidate_tracked_companies_cache
from db.users import set_onboarded, update_user_profile
from handlers.start import (
    CONFIRM_SKILLS,
    EXPERIENCE,
    WAITING_CUSTOM_SKILL,
    confirm_skills_text_receive,
    onboard_skills_ok_callback,
    onboard_skills_undo_callback,
    resume_doc_receive,
)
from utils.keyboards import onboarding_complete_keyboard


class TestRFC011(unittest.IsolatedAsyncioTestCase):
    def test_no_unscoped_profile_writes_in_repo(self):
        """Static AST scan: every update_user_profile() and set_onboarded() call must pass bot_id."""
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        target_dirs = ["handlers", "services", "db"]
        violations = []

        for folder in target_dirs:
            folder_path = os.path.join(root, folder)
            if not os.path.isdir(folder_path):
                continue
            for dirpath, _, filenames in os.walk(folder_path):
                for fname in filenames:
                    if not fname.endswith(".py"):
                        continue
                    fpath = os.path.join(dirpath, fname)
                    with open(fpath, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read(), filename=fpath)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                            if node.func.id in ("update_user_profile", "set_onboarded"):
                                has_kw = any(kw.arg == "bot_id" for kw in node.keywords)
                                has_pos = node.func.id == "set_onboarded" and len(node.args) >= 2
                                if not (has_kw or has_pos):
                                    rel = os.path.relpath(fpath, root)
                                    violations.append(f"{rel}:{node.lineno} -> {node.func.id}() missing bot_id")

        self.assertEqual(violations, [], "Unscoped profile writes found:\n" + "\n".join(violations))

    async def test_profile_writes_require_bot_id_at_runtime(self):
        with self.assertRaises(TypeError):
            await update_user_profile(12345, skills=["python"])

        with self.assertRaises(ValueError):
            await update_user_profile(12345, bot_id=None, skills=["python"])  # type: ignore

        with self.assertRaises(TypeError):
            await set_onboarded(12345)

        with self.assertRaises(ValueError):
            await set_onboarded(12345, None)  # type: ignore

    async def test_update_user_profile_scopes_by_bot_id(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"telegram_id": 999, "bot_id": 2, "skills": ["rust"]})
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("db.users.get_pool", return_value=mock_pool):
            res = await update_user_profile(999, bot_id=2, skills=["rust"])

        self.assertEqual(res["bot_id"], 2)
        sql_arg = mock_conn.fetchrow.call_args[0][0]
        self.assertIn("WHERE telegram_id = $1 AND bot_id = $", sql_arg)
        self.assertEqual(mock_conn.fetchrow.call_args[0][-1], 2)

    def _make_pdf_update_and_context(self, bot_id=1):
        doc = MagicMock()
        doc.file_name = "resume.pdf"
        doc.file_size = 1024
        tg_file = AsyncMock()
        tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"%PDF-1.4 fake"))
        doc.get_file = AsyncMock(return_value=tg_file)

        msg = AsyncMock()
        msg.document = doc
        status_msg = AsyncMock()
        status_msg.delete = AsyncMock()
        msg.reply_text = AsyncMock(side_effect=[status_msg, AsyncMock()])

        update = MagicMock()
        update.message = msg
        update.effective_user = MagicMock(id=55555)
        update.callback_query = None

        ctx = MagicMock()
        ctx.bot_data = {"bot_id": bot_id}
        ctx.user_data = {"role_pref": "fullstack"}
        return update, ctx

    async def test_resume_0_skills_skips_review(self):
        update, ctx = self._make_pdf_update_and_context()
        with patch("handlers.start.extract_text_from_pdf_bytes_safe", AsyncMock(return_value="blank")), \
             patch("handlers.start.rank_and_extract_skills", return_value=[]):
            state = await resume_doc_receive(update, ctx)
        self.assertEqual(state, WAITING_CUSTOM_SKILL)

    async def test_resume_2_skills_and_html_escape_shows_confirm_skills(self):
        update, ctx = self._make_pdf_update_and_context()
        with patch("handlers.start.extract_text_from_pdf_bytes_safe", AsyncMock(return_value="txt")), \
             patch("handlers.start.rank_and_extract_skills", return_value=["C++ <20>", "React & Next"]), \
             patch("handlers.start.update_user_profile", AsyncMock()) as mock_upd:
            state = await resume_doc_receive(update, ctx)

        self.assertEqual(state, CONFIRM_SKILLS)
        mock_upd.assert_awaited_once()
        self.assertEqual(mock_upd.call_args.kwargs["bot_id"], 1)
        sent_html = update.message.reply_text.call_args_list[-1].args[0]
        self.assertIn("We found only 2 skill(s)", sent_html)
        self.assertIn("&lt;20&gt;", sent_html)
        self.assertIn("&amp;", sent_html)

    async def test_confirm_skills_replace_and_undo_and_idempotent_ok(self):
        update = MagicMock()
        update.effective_user = MagicMock(id=55555)
        update.message = AsyncMock()
        update.message.text = "Docker"
        update.callback_query = None

        ctx = MagicMock()
        ctx.bot_data = {"bot_id": 1}
        ctx.user_data = {
            "selected_skills": ["React", "Python", "SQL"],
            "prev_extracted_skills": ["React", "Python", "SQL"],
        }

        with patch("handlers.start.validate_and_normalize_skills", return_value=(True, ["Docker"], None)), \
             patch("handlers.start.update_user_profile", AsyncMock()) as mock_upd:
            state = await confirm_skills_text_receive(update, ctx)

        self.assertEqual(state, CONFIRM_SKILLS)
        self.assertEqual(ctx.user_data["selected_skills"], ["Docker"])
        self.assertTrue(ctx.user_data["skills_edited"])
        mock_upd.assert_awaited_once_with(55555, bot_id=1, skills=["docker"])

        cb_update = MagicMock()
        cb_update.effective_user = MagicMock(id=55555)
        cb_update.callback_query = AsyncMock()
        with patch("handlers.start.update_user_profile", AsyncMock()) as mock_upd_undo:
            state2 = await onboard_skills_undo_callback(cb_update, ctx)

        self.assertEqual(state2, CONFIRM_SKILLS)
        self.assertEqual(ctx.user_data["selected_skills"], ["React", "Python", "SQL"])
        mock_upd_undo.assert_awaited_once_with(55555, bot_id=1, skills=["react", "python", "sql"])

        with patch("handlers.start.get_user", AsyncMock(return_value={"is_onboarded": False})), \
             patch("handlers.start.prompt_experience_step", AsyncMock(return_value=EXPERIENCE)) as mock_exp:
            s_ok1 = await onboard_skills_ok_callback(cb_update, ctx)
            s_ok2 = await onboard_skills_ok_callback(cb_update, ctx)

        self.assertEqual(s_ok1, EXPERIENCE)
        self.assertEqual(s_ok2, ConversationHandler.END)
        self.assertEqual(mock_exp.await_count, 1)

    def test_tracked_companies_url_validation_and_keyboard(self):
        self.assertIsNotNone(validate_tracked_companies_url("https://docs.google.com/spreadsheets/d/abc"))
        self.assertIsNone(validate_tracked_companies_url("http://docs.google.com/spreadsheets/d/abc"))
        self.assertIsNone(validate_tracked_companies_url("javascript:alert(1)"))
        self.assertIsNone(validate_tracked_companies_url("not a url"))
        self.assertIsNone(validate_tracked_companies_url(None))

        kb_none = onboarding_complete_keyboard(tracked_url=None, tracked_count=520)
        flat_urls_none = [btn.url for row in kb_none.inline_keyboard for btn in row if btn.url]
        self.assertEqual(flat_urls_none, [])

        kb_valid = onboarding_complete_keyboard(tracked_url="https://docs.google.com/spreadsheets/d/abc", tracked_count=520)
        flat_btns = [btn for row in kb_valid.inline_keyboard for btn in row if btn.url]
        self.assertEqual(len(flat_btns), 1)
        self.assertEqual(flat_btns[0].text, "📋 Tracked Companies (520)")

    async def test_tracked_companies_summary_counts_unlinked_and_caches(self):
        invalidate_tracked_companies_cache()
        mock_rows = [
            {"company_name": "Apple", "last_successful_check_at": "2026-11-26"},
            {"company_name": "apple ", "last_successful_check_at": "2026-11-26"},
            {"company_name": "Supabase", "last_successful_check_at": "2026-11-25"},
        ]
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("db.career_sources.get_pool", return_value=mock_pool):
            res1 = await get_tracked_companies_summary()
            res2 = await get_tracked_companies_summary()

        self.assertEqual(res1, {"count": 2, "samples": ["Apple", "Supabase"]})
        self.assertEqual(res2, res1)
        self.assertEqual(mock_conn.fetch.await_count, 1)


if __name__ == "__main__":
    unittest.main()
