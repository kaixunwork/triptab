"""Shared test harness: a fresh SQLite database and Flask test client per test.

Run the suite from the repo root with:

    python -m unittest discover -s tests -t .
"""
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing

# Must be set before importing app so it doesn't write a .secret_key file.
os.environ.setdefault("TRIPTAB_SECRET", "test-secret")

import app as triptab  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

PASSWORD = "trip1234"
# One cheap hash reused for every directly-inserted user keeps the suite fast.
FAST_HASH = generate_password_hash(PASSWORD, method="pbkdf2:sha256:1")


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_db = triptab.DATABASE
        triptab.DATABASE = os.path.join(self.tmpdir, "test.db")
        triptab.init_db()
        triptab.app.config["TESTING"] = True
        self.app = triptab.app
        self.client = self.app.test_client()

    def tearDown(self):
        triptab.DATABASE = self._orig_db
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # -- database ---------------------------------------------------------
    def db(self):
        conn = sqlite3.connect(triptab.DATABASE)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def query(self, sql, args=()):
        with closing(self.db()) as conn:
            return conn.execute(sql, args).fetchall()

    def make_user(self, username, display_name=None):
        with closing(self.db()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO users (username, display_name, password_hash) VALUES (?, ?, ?)",
                (username, display_name or username.title(), FAST_HASH),
            )
            return cur.lastrowid

    def make_expense(self, description, amount_cents, paid_by, split_ids,
                     created_by=None, spent_on="2026-12-12"):
        with closing(self.db()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO expenses (description, amount_cents, paid_by, created_by, spent_on)"
                " VALUES (?, ?, ?, ?, ?)",
                (description, amount_cents, paid_by, created_by or paid_by, spent_on),
            )
            conn.executemany("INSERT INTO expense_splits (expense_id, user_id) VALUES (?, ?)",
                             [(cur.lastrowid, uid) for uid in split_ids])
            return cur.lastrowid

    # -- client -----------------------------------------------------------
    def csrf(self):
        """Return the session's CSRF token, creating one if needed."""
        with self.client.session_transaction() as sess:
            if "csrf" not in sess:
                sess["csrf"] = "test-csrf-token"
            return sess["csrf"]

    def post(self, path, data=None, **kwargs):
        data = dict(data or {})
        data.setdefault("csrf", self.csrf())
        return self.client.post(path, data=data, **kwargs)

    def login_as(self, user_id):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

    def text(self, response):
        return response.get_data(as_text=True)
