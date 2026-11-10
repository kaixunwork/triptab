"""Route /balances and the money maths behind it."""
import unittest

from tests.support import AppTestCase, triptab


class BalancesRouteTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.alex = self.make_user("alex", "Alex")
        self.sam = self.make_user("sam", "Sam")
        self.jun = self.make_user("jun", "Jun")
        self.login_as(self.alex)

    def test_everyone_square_with_no_expenses(self):
        r = self.client.get("/balances")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Everyone is square.", self.text(r))

    def test_payments_listed(self):
        self.make_expense("Hotel", 9000, self.sam, [self.alex, self.sam, self.jun])
        page = self.text(self.client.get("/balances"))
        self.assertIn("The fewest payments", page)
        self.assertIn("<strong>You</strong>\n          → <strong>Sam</strong>", page)
        self.assertIn("<strong>Jun</strong>\n          → <strong>Sam</strong>", page)
        self.assertIn("+$60.00", page)
        self.assertIn("-$30.00", page)

    def test_viewer_is_labelled(self):
        self.make_expense("Hotel", 9000, self.alex, [self.alex, self.sam, self.jun])
        page = self.text(self.client.get("/balances"))
        self.assertIn("Alex (you)", page)
        self.assertIn("→ <strong>you</strong>", page)


class SplitSharesTests(unittest.TestCase):
    def test_even_split(self):
        self.assertEqual(triptab.split_shares(900, [1, 2, 3]), {1: 300, 2: 300, 3: 300})

    def test_leftover_cents_go_to_lowest_ids(self):
        self.assertEqual(triptab.split_shares(1000, [3, 1, 2]), {1: 334, 2: 333, 3: 333})

    def test_shares_always_sum_to_total(self):
        for amount in [1, 2, 7, 99, 100, 101, 12345]:
            for n in range(1, 11):
                with self.subTest(amount=amount, n=n):
                    self.assertEqual(sum(triptab.split_shares(amount, range(1, n + 1)).values()), amount)


class ComputeBalancesTests(unittest.TestCase):
    MEMBERS = [{"id": 1, "display_name": "Alex"}, {"id": 2, "display_name": "sam"},
               {"id": 3, "display_name": "Jun"}]

    def expense(self, amount, paid_by, split):
        return {"amount_cents": amount, "paid_by": paid_by,
                "shares": triptab.split_shares(amount, split)}

    def test_no_expenses(self):
        stats, payments = triptab.compute_balances(self.MEMBERS, [])
        self.assertEqual(payments, [])
        self.assertEqual([s["name"] for s in stats], ["Alex", "Jun", "sam"])  # case-insensitive sort
        self.assertTrue(all(s["net"] == 0 for s in stats))

    def test_payments_settle_everyone(self):
        expenses = [self.expense(1000, 1, [1, 2, 3]), self.expense(500, 2, [2, 3]),
                    self.expense(1, 3, [1])]
        stats, payments = triptab.compute_balances(self.MEMBERS, expenses)
        self.assertEqual(sum(s["net"] for s in stats), 0)
        net = {s["id"]: s["net"] for s in stats}
        for p in payments:
            net[p["from_id"]] += p["amount"]
            net[p["to_id"]] -= p["amount"]
            self.assertGreater(p["amount"], 0)
        self.assertEqual(set(net.values()), {0})
        self.assertLessEqual(len(payments), len(self.MEMBERS) - 1)

    def test_paid_and_share_totals(self):
        stats, payments = triptab.compute_balances(self.MEMBERS, [self.expense(900, 1, [1, 2, 3])])
        alex = next(s for s in stats if s["id"] == 1)
        self.assertEqual((alex["paid"], alex["share"], alex["net"]), (900, 300, 600))
        self.assertEqual(sorted((p["from_id"], p["to_id"], p["amount"]) for p in payments),
                         [(2, 1, 300), (3, 1, 300)])


class FilterTests(unittest.TestCase):
    def test_money(self):
        self.assertEqual(triptab.money(0), "$0.00")
        self.assertEqual(triptab.money(5), "$0.05")
        self.assertEqual(triptab.money(123456), "$1,234.56")
        self.assertEqual(triptab.money(-250), "-$2.50")

    def test_nicedate(self):
        self.assertEqual(triptab.nicedate("2026-12-05"), "Sat 5 Dec")
        self.assertEqual(triptab.nicedate("not a date"), "not a date")


if __name__ == "__main__":
    unittest.main()
