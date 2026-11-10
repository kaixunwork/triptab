"""Reset the database and fill it with a demo trip.

    python seed.py

Every demo member's password is "trip1234".
WARNING: this deletes triptab.db and starts fresh.
"""
import os
import sqlite3

from werkzeug.security import generate_password_hash

from app import DATABASE, init_db

MEMBERS = [  # (username, display name)
    ("alex", "Alex"),
    ("sam", "Sam"),
    ("priya", "Priya"),
    ("jun", "Jun"),
]
PASSWORD = "trip1234"

# (description, amount in cents, payer username, split usernames, date)
EXPENSES = [
    ("Airbnb in Sukhumvit (3 nights)", 48000, "alex", ["alex", "sam", "priya", "jun"], "2026-12-12"),
    ("Airport taxi", 3600, "sam", ["alex", "sam", "priya", "jun"], "2026-12-12"),
    ("Street food at Chinatown", 5240, "priya", ["alex", "priya", "jun"], "2026-12-12"),
    ("Floating market tour", 14000, "jun", ["alex", "sam", "priya", "jun"], "2026-12-13"),
    ("Rooftop bar drinks", 8800, "sam", ["sam", "priya"], "2026-12-13"),
    ("Grab rides back to Airbnb", 1850, "alex", ["alex", "jun"], "2026-12-14"),
]


def main():
    if os.path.exists(DATABASE):
        os.remove(DATABASE)
    init_db()
    db = sqlite3.connect(DATABASE)
    ids = {}
    for username, name in MEMBERS:
        cur = db.execute(
            "INSERT INTO users (username, display_name, password_hash) VALUES (?, ?, ?)",
            (username, name, generate_password_hash(PASSWORD)),
        )
        ids[username] = cur.lastrowid
    for desc, cents, payer, split, spent_on in EXPENSES:
        cur = db.execute(
            "INSERT INTO expenses (description, amount_cents, paid_by, created_by, spent_on) VALUES (?, ?, ?, ?, ?)",
            (desc, cents, ids[payer], ids[payer], spent_on),
        )
        db.executemany("INSERT INTO expense_splits (expense_id, user_id) VALUES (?, ?)",
                       [(cur.lastrowid, ids[u]) for u in split])
    db.commit()
    db.close()
    print("Seeded {} members and {} expenses. Log in as alex / {}".format(len(MEMBERS), len(EXPENSES), PASSWORD))


if __name__ == "__main__":
    main()
