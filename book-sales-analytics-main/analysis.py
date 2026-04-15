"""
Book Sales Data Analysis
Processes DATA1, DATA2, DATA3 and produces JSON results for the dashboard.
"""

import json
import re
import warnings
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import yaml

warnings.filterwarnings("ignore")

DATA_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = Path(__file__).parent / "docs"
OUTPUT_DIR.mkdir(exist_ok=True)

EUR_TO_USD = 1.2


# ──────────────────────────────────────────────────────────────
# Price parsing
# ──────────────────────────────────────────────────────────────

def parse_price(raw: str) -> float | None:
    """
    Parse messy price strings to USD float.
    Handles: '$27.00', '27.00$', 'USD 45.99', '€71.00', 'EUR 61.75',
             '€50€50' (€ as decimal), '$54€25' (€ as decimal), '22$75€', etc.
    """
    s = str(raw).strip()

    # Detect currency by reading explicit markers
    upper = s.upper()
    # Replace replacement char (?) that encodes €
    s = s.replace("\ufffd", "€")

    has_eur_marker = "€" in s or "EUR" in upper
    has_usd_marker = "$" in s or "USD" in upper

    # Determine which is the real currency indicator vs decimal separator
    if has_eur_marker and not has_usd_marker:
        currency = "EUR"
    elif has_usd_marker and not has_eur_marker:
        currency = "USD"
    elif has_eur_marker and has_usd_marker:
        # Both present: the one at the boundary (start or end of string) is currency;
        # the one embedded between digits is the decimal separator.
        first_char = re.sub(r"\s", "", s)[0] if s.strip() else ""
        last_char = re.sub(r"\s", "", s)[-1] if s.strip() else ""
        if first_char == "€" or upper.startswith("EUR"):
            currency = "EUR"
        elif first_char == "$" or upper.startswith("USD"):
            currency = "USD"
        elif last_char == "€" or upper.endswith("EUR"):
            currency = "EUR"
        elif last_char == "$" or upper.endswith("USD"):
            currency = "USD"
        else:
            currency = "USD"
    else:
        currency = "USD"  # no marker → assume USD

    # Strip known currency codes/symbols (but not embedded ones between digits yet)
    s = re.sub(r"(?i)\beur\b|\busd\b", "", s)

    # Replace a $ or € that sits between two digit-characters with a dot
    s = re.sub(r"(?<=\d)[\$€](?=\d)", ".", s)

    # Remove all remaining non-numeric characters except dot and minus
    s = re.sub(r"[^\d.\-]", "", s)

    # Collapse multiple dots (keep only first)
    parts = s.split(".")
    if len(parts) > 2:
        s = parts[0] + "." + "".join(parts[1:])

    try:
        value = float(s)
    except ValueError:
        return None

    if currency == "EUR":
        value = round(value * EUR_TO_USD, 2)
    return round(value, 2)


# ──────────────────────────────────────────────────────────────
# Timestamp parsing
# ──────────────────────────────────────────────────────────────

def _normalize_ts(s: str) -> str:
    """Pre-normalize timestamp string before format matching."""
    # Normalize A.M./P.M. → AM/PM (remove dots)
    s = re.sub(r"[Aa]\.?[Mm]\.", "AM", s)
    s = re.sub(r"[Pp]\.?[Mm]\.", "PM", s)
    # Collapse multiple spaces
    s = re.sub(r"  +", " ", s).strip()
    return s


# Separator variants we want to handle: space, comma, semicolon
# We'll normalize separators between date and time parts to a single space
# then try a compact set of format templates.

_TS_FORMATS = [
    # ISO-like
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %I:%M:%S %p",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %I:%M %p",
    # date first (YYYY-MM-DD) with various seps
    "%Y-%m-%d,%H:%M:%S",
    "%Y-%m-%d,%I:%M:%S %p",
    "%Y-%m-%d,%H:%M",
    "%Y-%m-%d;%H:%M:%S",
    "%Y-%m-%d;%I:%M:%S %p",
    "%Y-%m-%d;%H:%M",
    # time first, then YYYY-MM-DD
    "%H:%M:%S,%Y-%m-%d",
    "%H:%M:%S %Y-%m-%d",
    "%H:%M:%S;%Y-%m-%d",
    "%I:%M:%S %p,%Y-%m-%d",
    "%I:%M:%S %p %Y-%m-%d",
    "%I:%M:%S %p;%Y-%m-%d",
    "%H:%M,%Y-%m-%d",
    "%H:%M %Y-%m-%d",
    "%H:%M;%Y-%m-%d",
    "%I:%M %p,%Y-%m-%d",
    "%I:%M %p %Y-%m-%d",
    # MM/DD/YY
    "%m/%d/%y %H:%M:%S",
    "%m/%d/%y %I:%M:%S %p",
    "%m/%d/%y %H:%M",
    "%m/%d/%y %I:%M %p",
    "%m/%d/%y,%H:%M:%S",
    "%m/%d/%y,%I:%M:%S %p",
    "%m/%d/%y,%H:%M",
    "%m/%d/%y;%H:%M:%S",
    "%m/%d/%y;%I:%M:%S %p",
    "%m/%d/%y;%H:%M",
    # time first then MM/DD/YY
    "%H:%M:%S,%m/%d/%y",
    "%H:%M:%S %m/%d/%y",
    "%H:%M:%S;%m/%d/%y",
    "%I:%M:%S %p,%m/%d/%y",
    "%I:%M:%S %p %m/%d/%y",
    "%I:%M:%S %p;%m/%d/%y",
    "%H:%M,%m/%d/%y",
    "%H:%M %m/%d/%y",
    "%H:%M;%m/%d/%y",
    "%I:%M %p,%m/%d/%y",
    "%I:%M %p %m/%d/%y",
    # YYYY-MM-DD date-first with comma-space separator
    "%Y-%m-%d, %H:%M:%S",
    "%Y-%m-%d, %I:%M:%S %p",
    "%Y-%m-%d, %H:%M",
    "%Y-%m-%d, %I:%M %p",
    # MM/DD/YY date-first with comma-space separator
    "%m/%d/%y, %H:%M:%S",
    "%m/%d/%y, %I:%M:%S %p",
    "%m/%d/%y, %H:%M",
    "%m/%d/%y, %I:%M %p",
    # time first, YYYY-MM-DD with space after sep
    "%H:%M:%S, %Y-%m-%d",
    "%I:%M:%S %p, %Y-%m-%d",
    "%H:%M, %Y-%m-%d",
    # MM/DD/YY with space after sep
    "%H:%M:%S, %m/%d/%y",
    "%I:%M:%S %p, %m/%d/%y",
    "%H:%M, %m/%d/%y",
    "%I:%M %p, %m/%d/%y",
    # DD-Mon-YYYY (abbreviated month)
    "%d-%b-%Y %H:%M:%S",
    "%d-%b-%Y %I:%M:%S %p",
    "%d-%b-%Y %H:%M",
    "%d-%b-%Y %I:%M %p",
    "%d-%b-%Y,%H:%M:%S",
    "%d-%b-%Y,%I:%M:%S %p",
    "%d-%b-%Y,%H:%M",
    "%d-%b-%Y, %H:%M:%S",
    "%d-%b-%Y, %I:%M:%S %p",
    "%d-%b-%Y, %H:%M",
    "%d-%b-%Y;%H:%M:%S",
    "%d-%b-%Y;%I:%M:%S %p",
    "%d-%b-%Y;%H:%M",
    # time first then DD-Mon-YYYY
    "%H:%M:%S,%d-%b-%Y",
    "%H:%M:%S %d-%b-%Y",
    "%H:%M:%S;%d-%b-%Y",
    "%H:%M:%S, %d-%b-%Y",
    "%I:%M:%S %p,%d-%b-%Y",
    "%I:%M:%S %p %d-%b-%Y",
    "%I:%M:%S %p;%d-%b-%Y",
    "%I:%M:%S %p, %d-%b-%Y",
    "%H:%M,%d-%b-%Y",
    "%H:%M %d-%b-%Y",
    "%H:%M;%d-%b-%Y",
    "%H:%M, %d-%b-%Y",
    # DD-Month-YYYY (full month)
    "%d-%B-%Y %H:%M:%S",
    "%d-%B-%Y %I:%M:%S %p",
    "%d-%B-%Y %H:%M",
    "%d-%B-%Y %I:%M %p",
    "%d-%B-%Y,%H:%M:%S",
    "%d-%B-%Y,%I:%M:%S %p",
    "%d-%B-%Y,%H:%M",
    "%d-%B-%Y, %H:%M:%S",
    "%d-%B-%Y, %I:%M:%S %p",
    "%d-%B-%Y, %H:%M",
    "%d-%B-%Y;%H:%M",
    # DD-Month-YYYY (full month) date-first semicolon
    "%d-%B-%Y;%H:%M:%S",
    "%d-%B-%Y;%I:%M:%S %p",
    # time first then DD-Month-YYYY
    "%H:%M:%S,%d-%B-%Y",
    "%H:%M:%S %d-%B-%Y",
    "%H:%M:%S;%d-%B-%Y",
    "%H:%M:%S; %d-%B-%Y",
    "%H:%M:%S, %d-%B-%Y",
    "%I:%M:%S %p,%d-%B-%Y",
    "%I:%M:%S %p %d-%B-%Y",
    "%I:%M:%S %p;%d-%B-%Y",
    "%I:%M:%S %p; %d-%B-%Y",
    "%I:%M:%S %p, %d-%B-%Y",
    "%H:%M,%d-%B-%Y",
    "%H:%M %d-%B-%Y",
    "%H:%M, %d-%B-%Y",
    "%H:%M; %d-%B-%Y",
    "%H:%M; %d-%b-%Y",
    "%I:%M:%S %p; %d-%B-%Y",
    "%I:%M:%S %p; %d-%b-%Y",
    # time;DD-Mon-YYYY (semicolon no space)
    "%H:%M:%S; %d-%b-%Y",
    "%H:%M; %d-%b-%Y",
    # DD.MM.YYYY
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %I:%M:%S %p",
    "%d.%m.%Y %H:%M",
    # ctime-like: Fri Dec 20 03:15:05 2024
    "%a %b %d %H:%M:%S %Y",
    # D-Mon-YYYY (no zero-pad)  → handle via str pre-processing
]


def parse_timestamp(raw: str) -> object:
    """Return pd.Timestamp or pd.NaT."""
    s = _normalize_ts(str(raw).strip())

    # Pad single-digit day: "3-OCT-2024" → "03-OCT-2024", "6-JUL-2024" → "06-JUL-2024"
    s = re.sub(r"^(\d)-", r"0\1-", s)
    # Also handle: "9-April" → "09-April"
    s = re.sub(r"(?<=[\s,;])(\d)-", r"0\1-", s)

    # Upper-case month abbreviations like OCT, JUL → Oct, Jul (strptime is case-sensitive on %b/%B)
    # Convert all-upper month tokens to title-case
    s = re.sub(r"\b([A-Z]{3,9})\b", lambda m: m.group(1).capitalize(), s)

    for fmt in _TS_FORMATS:
        try:
            return pd.to_datetime(s, format=fmt)
        except Exception:
            continue

    return pd.NaT


# ──────────────────────────────────────────────────────────────
# User reconciliation (Union-Find)
# ──────────────────────────────────────────────────────────────

class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


def normalize_phone(p) -> str:
    if pd.isna(p) or str(p).strip() == "":
        return ""
    return re.sub(r"\D", "", str(p))


def normalize_str(v) -> str:
    if pd.isna(v) or str(v).strip() == "":
        return ""
    return str(v).strip().lower()


def reconcile_users(users: pd.DataFrame) -> pd.Series:
    """
    Return a Series mapping each user row index → canonical group id.
    Two users are the same person if they differ in at most 1 field
    out of {name, address, phone, email}.
    Strategy: index on every PAIR of fields; any pair match → same person.
    Only use non-empty values for matching.
    """
    n = len(users)
    uf = UnionFind(n)
    idx = users.index.tolist()
    row_pos = {orig_idx: pos for pos, orig_idx in enumerate(idx)}

    name_arr = [normalize_str(v) for v in users["name"]]
    addr_arr = [normalize_str(v) for v in users["address"]]
    phone_arr = [normalize_phone(v) for v in users["phone"]]
    email_arr = [normalize_str(v) for v in users["email"]]

    def build_pair_index(a_arr, b_arr):
        """Map (a_val, b_val) → list of positions."""
        d = defaultdict(list)
        for pos, (a, b) in enumerate(zip(a_arr, b_arr)):
            if a and b:  # only index if both fields present
                d[(a, b)].append(pos)
        return d

    pair_fields = [
        (name_arr, email_arr),
        (name_arr, phone_arr),
        (name_arr, addr_arr),
        (email_arr, phone_arr),
        (email_arr, addr_arr),
        (phone_arr, addr_arr),
    ]

    for fa, fb in pair_fields:
        pair_idx = build_pair_index(fa, fb)
        for positions in pair_idx.values():
            for i in range(1, len(positions)):
                uf.union(positions[0], positions[i])

    # Build group mapping: original user_id → root position
    roots = [uf.find(i) for i in range(n)]
    # Map root position → a stable canonical id (use min user_id in group)
    root_to_ids = defaultdict(list)
    for pos, root in enumerate(roots):
        root_to_ids[root].append(idx[pos])

    canonical = {}
    for root, positions_idx in root_to_ids.items():
        canonical_id = min(users.loc[positions_idx, "id"])
        for orig_idx in positions_idx:
            canonical[orig_idx] = canonical_id

    return pd.Series(canonical)


# ──────────────────────────────────────────────────────────────
# Data loading & cleaning
# ──────────────────────────────────────────────────────────────

def load_books(path: Path) -> pd.DataFrame:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    df = pd.DataFrame(raw)
    # Keys have leading colon
    df.columns = [c.lstrip(":") for c in df.columns]
    df["id"] = df["id"].astype(int)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    # author: strip whitespace
    df["author"] = df["author"].astype(str).str.strip()
    return df


def load_users(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"id": int})
    # Strip whitespace from string columns
    for col in ["name", "address", "phone", "email"]:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace({"nan": "", "": pd.NA})
    return df


def load_orders(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    # Replace encoding artifacts
    df["unit_price"] = df["unit_price"].astype(str).str.replace("\ufffd", "€", regex=False)

    # Parse prices
    df["paid_price_raw"] = df["unit_price"].apply(parse_price)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["paid_price"] = (df["paid_price_raw"] * df["quantity"]).round(2)

    # Parse timestamps
    df["parsed_ts"] = pd.to_datetime(df["timestamp"].apply(parse_timestamp), errors="coerce")

    # Extract date parts
    df["date"] = df["parsed_ts"].dt.date
    df["year"] = df["parsed_ts"].dt.year
    df["month"] = df["parsed_ts"].dt.month
    df["day"] = df["parsed_ts"].dt.day

    # Report parsing issues
    ts_fail = df["parsed_ts"].isna().sum()
    price_fail = df["paid_price_raw"].isna().sum()
    if ts_fail:
        print(f"  [WARN] {ts_fail} timestamps could not be parsed")
    if price_fail:
        print(f"  [WARN] {price_fail} prices could not be parsed")

    return df


# ──────────────────────────────────────────────────────────────
# Analysis
# ──────────────────────────────────────────────────────────────

def author_set_key(author_str: str) -> str:
    """Canonical key for an author set: sorted, comma-separated."""
    authors = sorted(a.strip() for a in author_str.split(",") if a.strip())
    return ", ".join(authors)


def analyze(dataset_name: str) -> dict:
    root = DATA_ROOT / dataset_name
    print(f"\n{'='*60}\nAnalyzing {dataset_name}\n{'='*60}")

    users = load_users(root / "users.csv")
    orders = load_orders(root / "orders.parquet")
    books = load_books(root / "books.yaml")

    # Drop exact duplicate rows
    users = users.drop_duplicates()
    orders = orders.drop_duplicates(subset=["id"])
    books = books.drop_duplicates(subset=["id"])

    print(f"  Users: {len(users)}, Orders: {len(orders)}, Books: {len(books)}")

    # ── 1. Reconcile users ──────────────────────────────────────
    canonical_map = reconcile_users(users)
    users["canonical_id"] = canonical_map.values
    unique_users = users["canonical_id"].nunique()
    print(f"  Raw user rows: {len(users)}, Unique real users: {unique_users}")

    # ── 2. Enrich orders ───────────────────────────────────────
    user_id_to_canonical = users.set_index("id")["canonical_id"].to_dict()
    orders["canonical_user_id"] = orders["user_id"].map(user_id_to_canonical)

    orders_with_books = orders.merge(books[["id", "author"]], left_on="book_id", right_on="id", how="left")
    orders_with_books["author_set_key"] = orders_with_books["author"].apply(
        lambda x: author_set_key(str(x)) if pd.notna(x) else ""
    )

    # ── 3. Daily revenue ───────────────────────────────────────
    daily = (
        orders_with_books.dropna(subset=["date", "paid_price"])
        .groupby("date")["paid_price"]
        .sum()
        .reset_index()
        .rename(columns={"paid_price": "revenue"})
        .sort_values("date")
    )
    daily["date_str"] = daily["date"].astype(str)
    daily["revenue"] = daily["revenue"].round(2)

    top5 = daily.nlargest(5, "revenue")[["date_str", "revenue"]].values.tolist()
    print(f"  Top 5 days by revenue:")
    for d, r in top5:
        print(f"    {d}: ${r:,.2f}")

    # ── 4. Unique author sets ─────────────────────────────────
    unique_author_sets = orders_with_books["author_set_key"].nunique()
    print(f"  Unique author sets: {unique_author_sets}")

    # ── 5. Most popular author set ────────────────────────────
    author_sales = (
        orders_with_books.dropna(subset=["paid_price"])
        .groupby("author_set_key")["quantity"]
        .sum()
        .reset_index()
        .rename(columns={"quantity": "total_qty"})
    )
    most_popular_row = author_sales.loc[author_sales["total_qty"].idxmax()]
    most_popular_author = most_popular_row["author_set_key"]
    most_popular_qty = int(most_popular_row["total_qty"])
    print(f"  Most popular author set: {most_popular_author} ({most_popular_qty} books)")

    # ── 6. Top customer ───────────────────────────────────────
    customer_spend = (
        orders_with_books.dropna(subset=["paid_price"])
        .groupby("canonical_user_id")["paid_price"]
        .sum()
        .reset_index()
        .rename(columns={"paid_price": "total_spend"})
    )
    top_canonical = customer_spend.loc[customer_spend["total_spend"].idxmax(), "canonical_user_id"]
    top_user_ids = sorted(
        users[users["canonical_id"] == top_canonical]["id"].tolist()
    )
    top_spend = customer_spend[customer_spend["canonical_user_id"] == top_canonical]["total_spend"].values[0]
    top_names = users[users["canonical_id"] == top_canonical]["name"].unique().tolist()
    print(f"  Top customer: {top_names} | IDs: {top_user_ids} | Spend: ${top_spend:,.2f}")

    # ── 7. Daily revenue chart ────────────────────────────────
    chart_path = OUTPUT_DIR / f"{dataset_name}_revenue.png"
    fig, ax = plt.subplots(figsize=(12, 4))
    dates_dt = pd.to_datetime(daily["date_str"])
    ax.plot(dates_dt, daily["revenue"], color="#2563eb", linewidth=1.5)
    ax.fill_between(dates_dt, daily["revenue"], alpha=0.1, color="#2563eb")
    ax.set_title(f"{dataset_name} – Daily Revenue (USD)", fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel("Date")
    ax.set_ylabel("Revenue (USD)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    fig.autofmt_xdate()
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Chart saved: {chart_path}")

    return {
        "dataset": dataset_name,
        "unique_users": unique_users,
        "unique_author_sets": unique_author_sets,
        "most_popular_author": most_popular_author,
        "most_popular_qty": most_popular_qty,
        "top_customer_ids": top_user_ids,
        "top_customer_names": top_names,
        "top_customer_spend": round(float(top_spend), 2),
        "top5_days": [[d, round(r, 2)] for d, r in top5],
        "daily_revenue": daily[["date_str", "revenue"]].values.tolist(),
    }


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    results = {}
    for ds in ["DATA1", "DATA2", "DATA3"]:
        results[ds] = analyze(ds)

    out_json = OUTPUT_DIR / "results.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults written to {out_json}")


if __name__ == "__main__":
    main()
