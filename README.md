# TripTab

A tiny Splitwise for **one group trip of up to 10 friends**.

▶️ **[Watch the 30-second intro](TripTab-intro.mp4)**

## Product thinking

**Audience:** a group of friends (max 10) on one trip, like a weekend away or a grad trip.

**Problem:** on a trip, different people pay for the stay, the taxis and the dinners. By the end nobody remembers who owes whom, and settling up gets awkward. Apps like Splitwise are built for ongoing households and have more features (and friction) than a one-off trip needs.

**What TripTab does:** everyone logs what they paid, and the app tells the group the fewest payments needed to settle up.

| Brief requirement | TripTab |
|---|---|
| One main record | **Expense**: description, amount, who paid, who it's split between, date |
| One shared action | Everyone adds expenses, and **Balances** works out who pays whom |
| One rule | Every member can **see** every expense; only the member who **added** it can **edit or delete** it |
| Max ten | Joining needs the trip's invite code, and sign-ups close at 10 members |

## Run it locally (Windows)

Needs Python 3.7+.

```bash
python -m pip install -r requirements.txt
```

```bash
python seed.py
```

```bash
python app.py
```

Then open http://127.0.0.1:5000.

`seed.py` is optional. It **wipes** the database and loads a demo Bangkok trip with 4 members: `alex`, `sam`, `priya` and `jun`, all with password `trip1234`. Skip it to start with an empty trip.

- **Invite code** to join: `BKK2026`
- Change the trip name or invite code with the environment variables `TRIPTAB_NAME` and `TRIPTAB_INVITE`.

## Run the tests

```bash
python -m unittest discover -s tests -t .
```

Uses only the standard library's `unittest`. Each test gets a throwaway SQLite database.

## How it's built

- **Flask** (Python web framework) renders HTML pages on the server.
- **SQLite** database in `triptab.db` (created automatically). Tables are in `schema.sql`.
- **Login:** username and password, with passwords hashed using Werkzeug and sessions stored in a signed cookie. Forms carry a CSRF token.
- **Money** is stored as integer cents. Uneven splits hand the leftover cents to members one at a time, so totals always add up exactly.

```
app.py           routes, auth, the edit rule, balance maths
schema.sql       users, expenses, expense_splits
seed.py          demo data
tests/           route and money-maths tests (unittest)
templates/       HTML pages (Jinja)
static/style.css styles (light and dark mode)
```
