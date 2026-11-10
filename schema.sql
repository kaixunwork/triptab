-- TripTab database schema (SQLite)

-- Trip members. Capped at 10 by the app.
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- The one main record: an expense someone paid for the group.
CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    description  TEXT    NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    paid_by      INTEGER NOT NULL REFERENCES users(id),
    created_by   INTEGER NOT NULL REFERENCES users(id),  -- only this user may edit/delete
    spent_on     TEXT    NOT NULL,                       -- YYYY-MM-DD
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Which members an expense is split between (split equally).
CREATE TABLE IF NOT EXISTS expense_splits (
    expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (expense_id, user_id)
);
