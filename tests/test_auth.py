"""Routes: /, /signup, /login, /logout, plus CSRF and the login_required guard."""
import unittest
from unittest import mock

from tests.support import PASSWORD, AppTestCase, triptab

GOOD_SIGNUP = {"display_name": "Alex", "username": "alex", "password": "secret1",
               "invite_code": triptab.INVITE_CODE}


class IndexTests(AppTestCase):
    def test_anonymous_goes_to_login(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/login"))

    def test_logged_in_goes_to_expenses(self):
        self.login_as(self.make_user("alex"))
        r = self.client.get("/")
        self.assertTrue(r.headers["Location"].endswith("/expenses"))


class LoginRequiredTests(AppTestCase):
    def test_protected_pages_redirect_with_next(self):
        for path in ["/expenses", "/expenses/new", "/expenses/1/edit", "/balances"]:
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 302)
                self.assertIn("/login?next=" + path.replace("/", "%2F"), r.headers["Location"])

    def test_delete_requires_login(self):
        r = self.post("/expenses/1/delete")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_session_for_deleted_user_is_cleared(self):
        self.login_as(999)
        r = self.client.get("/expenses")
        self.assertEqual(r.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)


class CsrfTests(AppTestCase):
    def test_post_without_token_rejected(self):
        r = self.client.post("/login", data={"username": "a", "password": "b"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Form expired", self.text(r))

    def test_post_with_wrong_token_rejected(self):
        self.csrf()
        r = self.client.post("/login", data={"csrf": "nope", "username": "a", "password": "b"})
        self.assertEqual(r.status_code, 400)

    def test_post_without_session_token_rejected(self):
        r = self.client.post("/login", data={"csrf": "anything"})
        self.assertEqual(r.status_code, 400)

    def test_rendered_form_token_is_accepted(self):
        page = self.text(self.client.get("/login"))
        with self.client.session_transaction() as sess:
            token = sess["csrf"]
        self.assertIn('value="{}"'.format(token), page)
        r = self.client.post("/login", data={"csrf": token, "username": "x", "password": "y"})
        self.assertEqual(r.status_code, 200)


class SignupTests(AppTestCase):
    def signup(self, **overrides):
        data = dict(GOOD_SIGNUP, **overrides)
        return self.post("/signup", data)

    def test_get_shows_form_and_count(self):
        self.make_user("sam")
        r = self.client.get("/signup")
        self.assertEqual(r.status_code, 200)
        self.assertIn("1 of 10 spots taken", self.text(r))
        self.assertIn('name="invite_code"', self.text(r))

    def test_success_creates_user_and_logs_in(self):
        r = self.signup()
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/expenses"))
        rows = self.query("SELECT id, username, display_name FROM users")
        self.assertEqual([(r["username"], r["display_name"]) for r in rows], [("alex", "Alex")])
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["user_id"], rows[0]["id"])
        self.assertIn("Welcome to the trip, Alex!", self.text(self.client.get("/expenses")))

    def test_password_is_hashed_and_usable(self):
        self.signup()
        stored = self.query("SELECT password_hash FROM users")[0][0]
        self.assertNotIn("secret1", stored)
        self.post("/logout")
        r = self.post("/login", {"username": "alex", "password": "secret1"})
        self.assertEqual(r.status_code, 302)

    def test_invite_code_is_case_insensitive_and_trimmed(self):
        r = self.signup(invite_code="  " + triptab.INVITE_CODE.lower() + " ")
        self.assertEqual(r.status_code, 302)

    def test_validation_errors(self):
        cases = [
            ({"invite_code": "WRONG"}, "invite code isn"),
            ({"invite_code": ""}, "invite code isn"),
            ({"display_name": "   "}, "Enter a name"),
            ({"display_name": "x" * 31}, "Enter a name"),
            ({"username": "ab"}, "Username must be 3-20"),
            ({"username": "a" * 21}, "Username must be 3-20"),
            ({"username": "bad name"}, "Username must be 3-20"),
            ({"username": "bad-name"}, "Username must be 3-20"),
            ({"password": "12345"}, "at least 6 characters"),
        ]
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                r = self.signup(**overrides)
                self.assertEqual(r.status_code, 200)
                self.assertIn(message, self.text(r))
        self.assertEqual(self.query("SELECT COUNT(*) FROM users")[0][0], 0)

    def test_failed_signup_keeps_form_values(self):
        r = self.signup(password="123")
        self.assertIn('value="Alex"', self.text(r))
        self.assertIn('value="alex"', self.text(r))

    def test_duplicate_username_is_case_insensitive(self):
        self.make_user("alex")
        r = self.signup(username="ALEX")
        self.assertEqual(r.status_code, 200)
        self.assertIn("That username is taken.", self.text(r))
        self.assertEqual(self.query("SELECT COUNT(*) FROM users")[0][0], 1)

    def test_trip_full_blocks_signup(self):
        for i in range(triptab.MAX_MEMBERS):
            self.make_user("user{}".format(i))
        get = self.client.get("/signup")
        self.assertIn("this trip is full", self.text(get))
        self.assertNotIn('name="invite_code"', self.text(get))
        r = self.signup(username="eleventh")
        self.assertIn("This trip is full (10 members).", self.text(r))
        self.assertEqual(self.query("SELECT COUNT(*) FROM users")[0][0], triptab.MAX_MEMBERS)

    def test_logged_in_user_is_redirected(self):
        self.login_as(self.make_user("sam"))
        self.assertTrue(self.client.get("/signup").headers["Location"].endswith("/expenses"))
        r = self.signup()
        self.assertTrue(r.headers["Location"].endswith("/expenses"))
        self.assertEqual(self.query("SELECT COUNT(*) FROM users")[0][0], 1)

    def test_custom_invite_code(self):
        with mock.patch.object(triptab, "INVITE_CODE", "PARIS"):
            self.assertEqual(self.signup(invite_code="BKK2026").status_code, 200)
            self.assertEqual(self.signup(invite_code="paris").status_code, 302)


class LoginTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("alex", "Alex")

    def login(self, username="alex", password=PASSWORD, query=""):
        return self.post("/login" + query, {"username": username, "password": password})

    def test_get_shows_form_and_count(self):
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)
        self.assertIn("1 of 10 spots taken", self.text(r))

    def test_get_when_trip_full_hides_signup_link(self):
        for i in range(triptab.MAX_MEMBERS - 1):
            self.make_user("user{}".format(i))
        self.assertIn("This trip is full", self.text(self.client.get("/login")))

    def test_success(self):
        r = self.login()
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/expenses"))
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["user_id"], self.uid)

    def test_username_is_case_insensitive_and_trimmed(self):
        self.assertEqual(self.login(username="  ALEX ").status_code, 302)

    def test_wrong_password(self):
        r = self.login(password="wrong")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Wrong username or password.", self.text(r))
        self.assertIn('value="alex"', self.text(r))
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)

    def test_unknown_user(self):
        r = self.login(username="nobody")
        self.assertIn("Wrong username or password.", self.text(r))

    def test_login_rotates_session(self):
        with self.client.session_transaction() as sess:
            sess["stale"] = "x"
        self.login()
        with self.client.session_transaction() as sess:
            self.assertNotIn("stale", sess)

    def test_next_local_path_is_followed(self):
        r = self.login(query="?next=/balances")
        self.assertTrue(r.headers["Location"].endswith("/balances"))

    def test_next_external_targets_are_ignored(self):
        for nxt in ["https://evil.com", "//evil.com", "evil.com", "",
                    "/\\evil.com", "/%5Cevil.com", "/%09/evil.com", "/%0A/evil.com"]:
            with self.subTest(next=nxt):
                self.post("/logout")
                r = self.login(query="?next=" + nxt)
                self.assertTrue(r.headers["Location"].endswith("/expenses"), r.headers["Location"])

    def test_logged_in_user_is_redirected(self):
        self.login_as(self.uid)
        self.assertTrue(self.client.get("/login").headers["Location"].endswith("/expenses"))


class LogoutTests(AppTestCase):
    def test_logout_clears_session(self):
        self.login_as(self.make_user("alex"))
        r = self.post("/logout")
        self.assertTrue(r.headers["Location"].endswith("/login"))
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)
        self.assertEqual(self.client.get("/expenses").status_code, 302)

    def test_logout_rejects_get(self):
        self.assertEqual(self.client.get("/logout").status_code, 405)

    def test_logout_requires_csrf(self):
        self.login_as(self.make_user("alex"))
        self.assertEqual(self.client.post("/logout").status_code, 400)
        with self.client.session_transaction() as sess:
            self.assertIn("user_id", sess)


if __name__ == "__main__":
    unittest.main()
