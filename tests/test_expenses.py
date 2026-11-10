"""Routes: /expenses, /expenses/new, /expenses/<id>/edit, /expenses/<id>/delete.

Covers THE RULE: every member can see every expense, but only the member who
added an expense can edit or delete it.
"""
import unittest
from datetime import date

from tests.support import AppTestCase, triptab


class ExpenseTestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.alex = self.make_user("alex", "Alex")
        self.sam = self.make_user("sam", "Sam")
        self.priya = self.make_user("priya", "Priya")
        self.login_as(self.alex)

    def form(self, **overrides):
        data = {"description": "Dinner", "amount": "30.00", "paid_by": str(self.alex),
                "split_with": [str(self.alex), str(self.sam), str(self.priya)],
                "spent_on": "2026-12-12"}
        data.update(overrides)
        return data

    def splits(self, expense_id):
        return sorted(r[0] for r in self.query(
            "SELECT user_id FROM expense_splits WHERE expense_id = ?", (expense_id,)))

    def expense_count(self):
        return self.query("SELECT COUNT(*) FROM expenses")[0][0]


class ListTests(ExpenseTestCase):
    def test_empty_trip(self):
        r = self.client.get("/expenses")
        self.assertEqual(r.status_code, 200)
        page = self.text(r)
        self.assertIn("No expenses yet.", page)
        self.assertIn("3 of 10 trip members", page)
        self.assertIn("You're square", page)

    def test_everyone_sees_every_expense(self):
        self.make_expense("Hotel", 9000, self.sam, [self.alex, self.sam, self.priya])
        self.make_expense("Taxi", 1000, self.alex, [self.alex, self.sam])
        page = self.text(self.client.get("/expenses"))
        self.assertIn("Hotel", page)
        self.assertIn("Taxi", page)
        self.assertIn("$100.00", page)          # trip total
        self.assertIn("your share $30.00", page)
        self.assertIn("You owe", page)          # paid 10, share 35 -> owes 25
        self.assertIn("$25.00", page)

    def test_edit_controls_only_on_own_expenses(self):
        mine = self.make_expense("Mine", 1000, self.alex, [self.alex])
        theirs = self.make_expense("Theirs", 1000, self.sam, [self.sam])
        page = self.text(self.client.get("/expenses"))
        self.assertIn("/expenses/{}/edit".format(mine), page)
        self.assertNotIn("/expenses/{}/edit".format(theirs), page)
        self.assertIn("Added by Sam", page)
        self.assertIn("not involved", page)

    def test_newest_date_first(self):
        self.make_expense("Older", 100, self.alex, [self.alex], spent_on="2026-12-01")
        self.make_expense("Newer", 100, self.alex, [self.alex], spent_on="2026-12-20")
        page = self.text(self.client.get("/expenses"))
        self.assertLess(page.index("Newer"), page.index("Older"))

    def test_descriptions_are_escaped(self):
        self.make_expense("<script>x</script>", 100, self.alex, [self.alex])
        page = self.text(self.client.get("/expenses"))
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("&lt;script&gt;", page)


class NewExpenseTests(ExpenseTestCase):
    def test_get_defaults(self):
        r = self.client.get("/expenses/new")
        self.assertEqual(r.status_code, 200)
        page = self.text(r)
        self.assertIn("Add an expense", page)
        self.assertIn('value="{}"'.format(date.today().isoformat()), page)
        self.assertEqual(page.count("checked"), 3)  # everyone ticked by default

    def test_create(self):
        r = self.post("/expenses/new", self.form())
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/expenses"))
        row = self.query("SELECT * FROM expenses")[0]
        self.assertEqual(row["description"], "Dinner")
        self.assertEqual(row["amount_cents"], 3000)
        self.assertEqual(row["paid_by"], self.alex)
        self.assertEqual(row["created_by"], self.alex)
        self.assertEqual(row["spent_on"], "2026-12-12")
        self.assertEqual(self.splits(row["id"]), sorted([self.alex, self.sam, self.priya]))
        self.assertIn("Added “Dinner”.", self.text(self.client.get("/expenses")))

    def test_creator_is_logged_in_user_even_if_someone_else_paid(self):
        self.post("/expenses/new", self.form(paid_by=str(self.sam)))
        row = self.query("SELECT paid_by, created_by FROM expenses")[0]
        self.assertEqual((row["paid_by"], row["created_by"]), (self.sam, self.alex))

    def test_created_by_cannot_be_spoofed(self):
        self.post("/expenses/new", self.form(created_by=str(self.sam)))
        self.assertEqual(self.query("SELECT created_by FROM expenses")[0][0], self.alex)

    def test_amount_formats_accepted(self):
        cases = {"12": 1200, "12.5": 1250, "$12.50": 1250, "1,234.56": 123456,
                 " 7.07 ": 707, "0.01": 1, "100000": 10_000_000}
        for amount, cents in cases.items():
            with self.subTest(amount=amount):
                self.assertEqual(self.post("/expenses/new", self.form(amount=amount)).status_code, 302)
                self.assertEqual(self.query(
                    "SELECT amount_cents FROM expenses ORDER BY id DESC LIMIT 1")[0][0], cents)

    def test_duplicate_split_ids_are_collapsed(self):
        self.post("/expenses/new", self.form(split_with=[str(self.sam), str(self.sam)]))
        self.assertEqual(self.splits(1), [self.sam])

    def test_validation_errors(self):
        cases = [
            ({"description": ""}, "Enter a description"),
            ({"description": "   "}, "Enter a description"),
            ({"description": "x" * 81}, "Enter a description"),
            ({"amount": ""}, "Enter an amount like 12.50."),
            ({"amount": "abc"}, "Enter an amount like 12.50."),
            ({"amount": "1.234"}, "Enter an amount like 12.50."),
            ({"amount": "NaN"}, "Enter an amount like 12.50."),
            ({"amount": "Infinity"}, "Enter an amount like 12.50."),
            ({"amount": "0"}, "Amount must be between"),
            ({"amount": "-5"}, "Amount must be between"),
            ({"amount": "100000.01"}, "Amount must be between"),
            ({"paid_by": ""}, "Choose who paid."),
            ({"paid_by": "abc"}, "Choose who paid."),
            ({"paid_by": "999"}, "Choose who paid."),
            ({"split_with": []}, "Tick at least one person"),
            ({"split_with": ["999"]}, "Tick at least one person"),
            ({"split_with": [str(self.sam), "999"]}, "Tick at least one person"),
            ({"split_with": ["x"]}, "Tick at least one person"),
            ({"spent_on": ""}, "Enter a valid date."),
            ({"spent_on": "2026-02-30"}, "Enter a valid date."),
            ({"spent_on": "tomorrow"}, "Enter a valid date."),
        ]
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                r = self.post("/expenses/new", self.form(**overrides))
                self.assertEqual(r.status_code, 200)
                self.assertIn(message, self.text(r))
        self.assertEqual(self.expense_count(), 0)

    def test_multiple_errors_are_all_reported_and_input_kept(self):
        r = self.post("/expenses/new", self.form(description="Snacks", amount="abc", spent_on=""))
        page = self.text(r)
        self.assertIn("Enter an amount like 12.50.", page)
        self.assertIn("Enter a valid date.", page)
        self.assertIn('value="Snacks"', page)
        self.assertIn('value="abc"', page)


class EditExpenseTests(ExpenseTestCase):
    def setUp(self):
        super().setUp()
        self.eid = self.make_expense("Hotel", 123456, self.alex, [self.alex, self.sam])

    def test_get_prefills_form(self):
        r = self.client.get("/expenses/{}/edit".format(self.eid))
        self.assertEqual(r.status_code, 200)
        page = self.text(r)
        self.assertIn("Edit expense", page)
        self.assertIn('value="Hotel"', page)
        self.assertIn('value="1,234.56"', page)
        self.assertIn('value="2026-12-12"', page)
        self.assertEqual(page.count("checked"), 2)

    def test_prefilled_amount_round_trips(self):
        self.post("/expenses/{}/edit".format(self.eid), self.form(amount="1,234.56"))
        self.assertEqual(self.query("SELECT amount_cents FROM expenses")[0][0], 123456)

    def test_update(self):
        r = self.post("/expenses/{}/edit".format(self.eid), self.form(
            description="Hostel", amount="50", paid_by=str(self.sam),
            split_with=[str(self.priya)], spent_on="2026-12-14"))
        self.assertEqual(r.status_code, 302)
        row = self.query("SELECT * FROM expenses WHERE id = ?", (self.eid,))[0]
        self.assertEqual((row["description"], row["amount_cents"], row["paid_by"], row["spent_on"]),
                         ("Hostel", 5000, self.sam, "2026-12-14"))
        self.assertEqual(row["created_by"], self.alex)
        self.assertEqual(self.splits(self.eid), [self.priya])
        self.assertIn("Saved changes to “Hostel”.", self.text(self.client.get("/expenses")))

    def test_invalid_update_changes_nothing(self):
        r = self.post("/expenses/{}/edit".format(self.eid), self.form(amount="0"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("Amount must be between", self.text(r))
        self.assertEqual(self.query("SELECT amount_cents FROM expenses")[0][0], 123456)
        self.assertEqual(self.splits(self.eid), sorted([self.alex, self.sam]))

    def test_other_member_cannot_edit(self):
        self.login_as(self.sam)
        get = self.client.get("/expenses/{}/edit".format(self.eid))
        self.assertEqual(get.status_code, 403)
        self.assertIn("Only the person who added this expense can change it.", self.text(get))
        post = self.post("/expenses/{}/edit".format(self.eid), self.form(description="Hacked"))
        self.assertEqual(post.status_code, 403)
        self.assertEqual(self.query("SELECT description FROM expenses")[0][0], "Hotel")

    def test_payer_who_did_not_create_cannot_edit(self):
        eid = self.make_expense("Paid by Sam", 100, self.sam, [self.sam], created_by=self.alex)
        self.login_as(self.sam)
        self.assertEqual(self.client.get("/expenses/{}/edit".format(eid)).status_code, 403)

    def test_missing_expense(self):
        self.assertEqual(self.client.get("/expenses/999/edit").status_code, 404)
        self.assertEqual(self.post("/expenses/999/edit", self.form()).status_code, 404)


class DeleteExpenseTests(ExpenseTestCase):
    def setUp(self):
        super().setUp()
        self.eid = self.make_expense("Hotel", 9000, self.alex, [self.alex, self.sam])

    def test_creator_can_delete_and_splits_go_too(self):
        r = self.post("/expenses/{}/delete".format(self.eid))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.expense_count(), 0)
        self.assertEqual(self.query("SELECT COUNT(*) FROM expense_splits")[0][0], 0)
        self.assertIn("Deleted “Hotel”.", self.text(self.client.get("/expenses")))

    def test_other_member_cannot_delete(self):
        self.login_as(self.sam)
        self.assertEqual(self.post("/expenses/{}/delete".format(self.eid)).status_code, 403)
        self.assertEqual(self.expense_count(), 1)

    def test_missing_expense(self):
        self.assertEqual(self.post("/expenses/999/delete").status_code, 404)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get("/expenses/{}/delete".format(self.eid)).status_code, 405)
        self.assertEqual(self.expense_count(), 1)

    def test_requires_csrf(self):
        self.csrf()
        r = self.client.post("/expenses/{}/delete".format(self.eid), data={"csrf": "wrong"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.expense_count(), 1)


class NotFoundTests(AppTestCase):
    def test_unknown_page(self):
        r = self.client.get("/nope")
        self.assertEqual(r.status_code, 404)
        self.assertIn("That page doesn&#39;t exist.", self.text(r))


if __name__ == "__main__":
    unittest.main()
