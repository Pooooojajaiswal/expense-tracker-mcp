import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from fastmcp import FastMCP

DB_PATH = Path(__file__).parent / "expenses.db"
mcp = FastMCP(name="ExpenseTracker")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT NOT NULL,
                time      TEXT NOT NULL,
                item      TEXT NOT NULL,
                cost      REAL NOT NULL,
                category  TEXT,
                subcategory TEXT,
                note      TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON expenses(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON expenses(category)")
        conn.commit()


init_db()


# ── 1. ADD ────────────────────────────────────────────────────────────────────
@mcp.tool
def add_expense(
    item: str,
    cost: float,
    category: str = "Uncategorized",
    subcategory: str = "",
    note: str = "",
    date: str = "",
    time: str = "",
) -> str:
    """
    Add a new expense entry.

    Args:
        item:        Name of the purchased item (e.g. 'table').
        cost:        Amount spent in INR.
        category:    High-level category (e.g. 'Furniture', 'Food', 'Transport').
        subcategory: More specific sub-type (e.g. 'Table', 'Lunch').
        note:        Free-text note / description.
        date:        Date in DD-MM-YYYY format. Defaults to today.
        time:        Time in HH:MM format. Defaults to now.

    Returns a confirmation string with the new expense ID.
    """
    now = datetime.now()
    date = date or now.strftime("%d-%m-%Y")
    time = time or now.strftime("%H:%M")

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO expenses (date, time, item, cost, category, subcategory, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (date, time, item, cost, category, subcategory, note),
        )
        conn.commit()
        new_id = cur.lastrowid

    return (
        f"✅ Expense added!\n"
        f"  ID: {new_id}\n"
        f"  Date: {date}  Time: {time}\n"
        f"  Item: {item}  |  Cost: ₹{cost:.2f}\n"
        f"  Category: {category} › {subcategory}\n"
        f"  Note: {note}"
    )


# ── 2. LIST ───────────────────────────────────────────────────────────────────
@mcp.tool
def list_expenses(
    limit: int = 20,
    category: str = "",
    from_date: str = "",
    to_date: str = "",
) -> str:
    """
    List recent expenses, optionally filtered by category or date range.

    Args:
        limit:     Max number of rows to return (default 20).
        category:  Filter by category name (partial match, case-insensitive).
        from_date: Start date DD-MM-YYYY (inclusive).
        to_date:   End date   DD-MM-YYYY (inclusive).

    Returns a formatted table of expenses.
    """
    query = "SELECT * FROM expenses WHERE 1=1"
    params: list = []

    if category:
        query += " AND LOWER(category) LIKE ?"
        params.append(f"%{category.lower()}%")
    if from_date:
        # Store dates as DD-MM-YYYY; convert to YYYY-MM-DD for comparison
        try:
            fd = datetime.strptime(from_date, "%d-%m-%Y").strftime("%Y-%m-%d")
            query += " AND date(substr(date,7)||'-'||substr(date,4,2)||'-'||substr(date,1,2)) >= date(?)"
            params.append(fd)
        except ValueError:
            pass
    if to_date:
        try:
            td = datetime.strptime(to_date, "%d-%m-%Y").strftime("%Y-%m-%d")
            query += " AND date(substr(date,7)||'-'||substr(date,4,2)||'-'||substr(date,1,2)) <= date(?)"
            params.append(td)
        except ValueError:
            pass

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        return "No expenses found."

    lines = [f"{'ID':<5} {'Date':<12} {'Time':<6} {'Item':<20} {'Cost':>8}  {'Category':<15} {'Subcategory':<15} Note"]
    lines.append("-" * 100)
    for r in rows:
        lines.append(
            f"{r['id']:<5} {r['date']:<12} {r['time']:<6} {r['item']:<20} ₹{r['cost']:>7.2f}  "
            f"{r['category']:<15} {r['subcategory']:<15} {r['note']}"
        )
    lines.append("-" * 100)
    lines.append(f"Total shown: {len(rows)} expense(s)")
    return "\n".join(lines)


# ── 3. SUMMARIZE ──────────────────────────────────────────────────────────────
@mcp.tool
def summarize_expenses(period: str = "all") -> str:
    """
    Summarize expenses grouped by category.

    Args:
        period: 'today' | 'week' | 'month' | 'all'  (default 'all')

    Returns totals per category and an overall grand total.
    """
    base = "SELECT category, SUM(cost) as total, COUNT(*) as cnt FROM expenses"
    where = ""
    now = datetime.now()

    if period == "today":
        d = now.strftime("%d-%m-%Y")
        where = f" WHERE date = '{d}'"
    elif period == "week":
        days = [(now - timedelta(days=i)).strftime("%d-%m-%Y") for i in range(7)]
        date_list = ", ".join(f"'{d}'" for d in days)
        where = f" WHERE date IN ({date_list})"
    elif period == "month":
        month = now.strftime("%m-%Y")
        where = f" WHERE date LIKE '%-{month}'"  # DD-MM-YYYY ends with MM-YYYY

    query = base + where + " GROUP BY category ORDER BY total DESC"

    with get_conn() as conn:
        rows = conn.execute(query).fetchall()
        grand = conn.execute("SELECT SUM(cost) FROM expenses" + where).fetchone()[0] or 0

    if not rows:
        return f"No expenses found for period: {period}."

    lines = [f"📊 Expense Summary ({period.upper()})", "=" * 40]
    for r in rows:
        lines.append(f"  {r['category']:<20} ₹{r['total']:>9.2f}  ({r['cnt']} item(s))")
    lines.append("=" * 40)
    lines.append(f"  {'GRAND TOTAL':<20} ₹{grand:>9.2f}")
    return "\n".join(lines)


# ── 4. EDIT ───────────────────────────────────────────────────────────────────
@mcp.tool
def edit_expense(
    id: int,
    item: str = "",
    cost: float = -1,
    category: str = "",
    subcategory: str = "",
    note: str = "",
    date: str = "",
    time: str = "",
) -> str:
    """
    Edit one or more fields of an existing expense by its ID.
    Only the fields you provide (non-empty / non-default) will be updated.

    Args:
        id:          The expense ID to edit.
        item:        New item name (leave blank to keep existing).
        cost:        New cost in INR (-1 to keep existing).
        category:    New category (leave blank to keep existing).
        subcategory: New subcategory (leave blank to keep existing).
        note:        New note (leave blank to keep existing).
        date:        New date DD-MM-YYYY (leave blank to keep existing).
        time:        New time HH:MM (leave blank to keep existing).

    Returns a confirmation string.
    """
    updates = {}
    if item:         updates["item"] = item
    if cost != -1:   updates["cost"] = cost
    if category:     updates["category"] = category
    if subcategory:  updates["subcategory"] = subcategory
    if note:         updates["note"] = note
    if date:         updates["date"] = date
    if time:         updates["time"] = time

    if not updates:
        return "⚠️ No fields provided to update."

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [id]

    with get_conn() as conn:
        cur = conn.execute(f"UPDATE expenses SET {set_clause} WHERE id = ?", values)
        conn.commit()
        if cur.rowcount == 0:
            return f"❌ No expense found with ID {id}."

    return f"✅ Expense ID {id} updated: {updates}"


# ── 5. DELETE ─────────────────────────────────────────────────────────────────
@mcp.tool
def delete_expense(id: int) -> str:
    """
    Delete an expense by its ID.

    Args:
        id: The expense ID to delete.

    Returns a confirmation string.
    """
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (id,)).fetchone()
        if not row:
            return f"❌ No expense found with ID {id}."
        conn.execute("DELETE FROM expenses WHERE id = ?", (id,))
        conn.commit()

    return (
        f"🗑️ Deleted expense ID {id}: "
        f"{row['item']} (₹{row['cost']:.2f}) on {row['date']}"
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)