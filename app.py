"""TripTab - a tiny Splitwise for one group trip (max 10 people).

One record:   Expense (description, amount, who paid, who it's split between, date)
One action:   Everyone adds expenses; the Balances page works out who owes whom.
One rule:     Every member can SEE every expense, but only the member who ADDED
              an expense can EDIT or DELETE it.
"""
import os
import secrets
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "triptab.db")
SCHEMA = os.path.join(BASE_DIR, "schema.sql")
SECRET_FILE = os.path.join(BASE_DIR, ".secret_key")

MAX_MEMBERS = 10
TRIP_NAME = os.environ.get("TRIPTAB_NAME", "Bangkok Getaway")
INVITE_CODE = os.environ.get("TRIPTAB_INVITE", "BKK2026")
MAX_AMOUNT_CENTS = 10_000_000  # $100,000 sanity cap


def load_secret_key():
    """Keep one random secret on disk so logins survive server restarts."""
    if os.environ.get("TRIPTAB_SECRET"):
        return os.environ["TRIPTAB_SECRET"]
    if not os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, "w") as f:
            f.write(secrets.token_hex(32))
    with open(SECRET_FILE) as f:
        return f.read().strip()


app = Flask(__name__)
app.config["SECRET_KEY"] = load_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DATABASE) as db, open(SCHEMA) as f:
        db.executescript(f.read())


def get_members():
    return get_db().execute(
        "SELECT id, username, display_name FROM users ORDER BY display_name COLLATE NOCASE"
    ).fetchall()


def member_count():
    return get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0]


# --------------------------------------------------------------------------
# Auth + CSRF
# --------------------------------------------------------------------------
@app.before_request
def load_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if g.user is None:
            session.clear()


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@app.before_request
def check_csrf():
    if request.method == "POST":
        sent = request.form.get("csrf", "")
        if not session.get("csrf") or not secrets.compare_digest(sent, session["csrf"]):
            abort(400, "Form expired - please go back, refresh and try again.")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_globals():
    return {"csrf_token": csrf_token, "trip_name": TRIP_NAME, "max_members": MAX_MEMBERS}


@app.template_filter("money")
def money(cents):
    cents = int(cents)
    sign = "-" if cents < 0 else ""
    dollars, rem = divmod(abs(cents), 100)
    return "{}${:,}.{:02d}".format(sign, dollars, rem)


@app.template_filter("nicedate")
def nicedate(iso):
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return d.strftime("%a %d %b").replace(" 0", " ")


# --------------------------------------------------------------------------
# Money maths
# --------------------------------------------------------------------------
def split_shares(amount_cents, user_ids):
    """Split equally; leftover cents go one each to the first members (by id)."""
    ids = sorted(user_ids)
    base, rem = divmod(amount_cents, len(ids))
    return {uid: base + (1 if i < rem else 0) for i, uid in enumerate(ids)}


def load_expenses():
    db = get_db()
    rows = db.execute(
        """SELECT e.*, p.display_name AS payer_name, c.display_name AS creator_name
           FROM expenses e
           JOIN users p ON p.id = e.paid_by
           JOIN users c ON c.id = e.created_by
           ORDER BY e.spent_on DESC, e.id DESC"""
    ).fetchall()
    splits = {}
    for s in db.execute(
        """SELECT s.expense_id, u.id, u.display_name FROM expense_splits s
           JOIN users u ON u.id = s.user_id ORDER BY u.display_name COLLATE NOCASE"""
    ):
        splits.setdefault(s["expense_id"], []).append({"id": s["id"], "name": s["display_name"]})

    expenses = []
    for r in rows:
        e = dict(r)
        e["split"] = splits.get(r["id"], [])
        e["shares"] = split_shares(e["amount_cents"], [m["id"] for m in e["split"]]) if e["split"] else {}
        expenses.append(e)
    return expenses


def compute_balances(members, expenses):
    """Return per-member totals and the fewest-ish payments to settle up."""
    stats = {m["id"]: {"id": m["id"], "name": m["display_name"], "paid": 0, "share": 0} for m in members}
    for e in expenses:
        stats[e["paid_by"]]["paid"] += e["amount_cents"]
        for uid, share in e["shares"].items():
            stats[uid]["share"] += share
    for s in stats.values():
        s["net"] = s["paid"] - s["share"]  # + means the group owes them

    # Greedy: biggest debtor pays biggest creditor until everyone is square.
    creditors = sorted([[s["net"], s["id"]] for s in stats.values() if s["net"] > 0], reverse=True)
    debtors = sorted([[-s["net"], s["id"]] for s in stats.values() if s["net"] < 0], reverse=True)
    payments = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i][0], creditors[j][0])
        payments.append({
            "from_id": debtors[i][1], "from": stats[debtors[i][1]]["name"],
            "to_id": creditors[j][1], "to": stats[creditors[j][1]]["name"],
            "amount": amount,
        })
        debtors[i][0] -= amount
        creditors[j][0] -= amount
        if debtors[i][0] == 0:
            i += 1
        if creditors[j][0] == 0:
            j += 1

    ordered = sorted(stats.values(), key=lambda s: s["name"].lower())
    return ordered, payments


# --------------------------------------------------------------------------
# Auth routes
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return redirect(url_for("expenses" if g.user else "login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("expenses"))
    count = member_count()
    form = {}
    if request.method == "POST":
        form = request.form
        display_name = form.get("display_name", "").strip()
        username = form.get("username", "").strip()
        password = form.get("password", "")
        code = form.get("invite_code", "").strip()

        error = None
        if count >= MAX_MEMBERS:
            error = "This trip is full ({} members).".format(MAX_MEMBERS)
        elif not secrets.compare_digest(code.upper(), INVITE_CODE.upper()):
            error = "That invite code isn't right. Ask the trip organiser."
        elif not display_name or len(display_name) > 30:
            error = "Enter a name (up to 30 characters)."
        elif not username.isalnum() or not 3 <= len(username) <= 20:
            error = "Username must be 3-20 letters or numbers."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            try:
                cur = get_db().execute(
                    "INSERT INTO users (username, display_name, password_hash) VALUES (?, ?, ?)",
                    (username, display_name, generate_password_hash(password)),
                )
                get_db().commit()
            except sqlite3.IntegrityError:
                error = "That username is taken."
            else:
                session.clear()
                session["user_id"] = cur.lastrowid
                flash("Welcome to the trip, {}!".format(display_name), "success")
                return redirect(url_for("expenses"))
        flash(error, "error")
    return render_template("signup.html", count=count, form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("expenses"))
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            nxt = request.args.get("next", "")
            # Only allow local redirects. Browsers read a backslash as "/" and
            # drop tabs/newlines, so "/\evil.com" or "/<TAB>/evil.com" would
            # act as "//evil.com"; reject those characters outright.
            if (not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt
                    or any(ord(ch) < 32 for ch in nxt)):
                nxt = url_for("expenses")
            return redirect(nxt)
        flash("Wrong username or password.", "error")
    return render_template("login.html", username=username, count=member_count())


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------
# Expense routes
# --------------------------------------------------------------------------
@app.route("/expenses")
@login_required
def expenses():
    members = get_members()
    all_expenses = load_expenses()
    stats, _ = compute_balances(members, all_expenses)
    me = next(s for s in stats if s["id"] == g.user["id"])
    total = sum(e["amount_cents"] for e in all_expenses)
    return render_template("expenses.html", expenses=all_expenses, me=me, total=total,
                           member_total=len(members))


def parse_expense_form(members):
    """Validate the add/edit form. Returns (data, errors)."""
    f = request.form
    member_ids = {m["id"] for m in members}
    errors = []

    description = f.get("description", "").strip()
    if not description or len(description) > 80:
        errors.append("Enter a description (up to 80 characters).")

    amount_cents = 0
    try:
        amount = Decimal(f.get("amount", "").strip().replace(",", "").lstrip("$"))
        if amount != amount.quantize(Decimal("0.01")):
            raise InvalidOperation
        amount_cents = int(amount * 100)
    except (InvalidOperation, ValueError):
        errors.append("Enter an amount like 12.50.")
    else:
        if not 0 < amount_cents <= MAX_AMOUNT_CENTS:
            errors.append("Amount must be between $0.01 and $100,000.")

    try:
        paid_by = int(f.get("paid_by", ""))
        if paid_by not in member_ids:
            raise ValueError
    except ValueError:
        paid_by = None
        errors.append("Choose who paid.")

    try:
        split_ids = sorted({int(x) for x in f.getlist("split_with")})
        if not split_ids or not set(split_ids) <= member_ids:
            raise ValueError
    except ValueError:
        split_ids = []
        errors.append("Tick at least one person to split with.")

    spent_on = f.get("spent_on", "").strip()
    try:
        date.fromisoformat(spent_on)
    except ValueError:
        errors.append("Enter a valid date.")

    data = {"description": description, "amount": f.get("amount", ""), "amount_cents": amount_cents,
            "paid_by": paid_by, "split_ids": split_ids, "spent_on": spent_on}
    return data, errors


def get_own_expense(expense_id):
    """THE RULE: anyone can view, but only the creator can change an expense."""
    expense = get_db().execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    if expense is None:
        abort(404)
    if expense["created_by"] != g.user["id"]:
        abort(403)
    return expense


def save_splits(db, expense_id, split_ids):
    db.execute("DELETE FROM expense_splits WHERE expense_id = ?", (expense_id,))
    db.executemany("INSERT INTO expense_splits (expense_id, user_id) VALUES (?, ?)",
                   [(expense_id, uid) for uid in split_ids])


@app.route("/expenses/new", methods=["GET", "POST"])
@login_required
def new_expense():
    members = get_members()
    if request.method == "POST":
        data, errors = parse_expense_form(members)
        if not errors:
            db = get_db()
            cur = db.execute(
                """INSERT INTO expenses (description, amount_cents, paid_by, created_by, spent_on)
                   VALUES (?, ?, ?, ?, ?)""",
                (data["description"], data["amount_cents"], data["paid_by"], g.user["id"], data["spent_on"]),
            )
            save_splits(db, cur.lastrowid, data["split_ids"])
            db.commit()
            flash("Added “{}”.".format(data["description"]), "success")
            return redirect(url_for("expenses"))
        for e in errors:
            flash(e, "error")
    else:
        data = {"description": "", "amount": "", "paid_by": g.user["id"],
                "split_ids": [m["id"] for m in members], "spent_on": date.today().isoformat()}
    return render_template("expense_form.html", members=members, data=data, editing=False)


@app.route("/expenses/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    expense = get_own_expense(expense_id)
    members = get_members()
    if request.method == "POST":
        data, errors = parse_expense_form(members)
        if not errors:
            db = get_db()
            db.execute(
                """UPDATE expenses SET description = ?, amount_cents = ?, paid_by = ?, spent_on = ?
                   WHERE id = ?""",
                (data["description"], data["amount_cents"], data["paid_by"], data["spent_on"], expense_id),
            )
            save_splits(db, expense_id, data["split_ids"])
            db.commit()
            flash("Saved changes to “{}”.".format(data["description"]), "success")
            return redirect(url_for("expenses"))
        for e in errors:
            flash(e, "error")
    else:
        split_ids = [r[0] for r in get_db().execute(
            "SELECT user_id FROM expense_splits WHERE expense_id = ?", (expense_id,))]
        data = {"description": expense["description"], "amount": money(expense["amount_cents"]).lstrip("$"),
                "paid_by": expense["paid_by"], "split_ids": split_ids, "spent_on": expense["spent_on"]}
    return render_template("expense_form.html", members=members, data=data, editing=True,
                           expense_id=expense_id)


@app.route("/expenses/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete_expense(expense_id):
    expense = get_own_expense(expense_id)
    db = get_db()
    db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    db.commit()
    flash("Deleted “{}”.".format(expense["description"]), "success")
    return redirect(url_for("expenses"))


@app.route("/balances")
@login_required
def balances():
    stats, payments = compute_balances(get_members(), load_expenses())
    return render_template("balances.html", stats=stats, payments=payments)


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403,
                           message="Only the person who added this expense can change it."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="That page doesn't exist."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400, message=e.description), 400


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("TRIPTAB_DEBUG", "1") == "1")
