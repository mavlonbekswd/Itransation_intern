import re
import sys
import pyodbc


SERVER = "localhost"
DATABASE = "books_db"

CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)


def parse_ruby_hash_file(filepath: str) -> list[dict]:
    print(f"[1/4] Reading and parsing file: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read()

    pattern = re.compile(
        r'\{:id=>(\d+),\s*'
        r':title=>"((?:[^"\\]|\\.)*)"\s*,\s*'
        r':author=>"((?:[^"\\]|\\.)*)"\s*,\s*'
        r':genre=>"((?:[^"\\]|\\.)*)"\s*,\s*'
        r':publisher=>"((?:[^"\\]|\\.)*)"\s*,\s*'
        r':year=>(\d+),\s*'
        r':price=>"([€$])([0-9.]+)"\}'
    )

    records = []
    for m in pattern.finditer(raw):
        records.append({
            "id": m.group(1),
            "title": m.group(2),
            "author": m.group(3),
            "genre": m.group(4),
            "publisher": m.group(5),
            "year": int(m.group(6)),
            "price_raw": m.group(7) + m.group(8),
            "currency_symbol": m.group(7),
            "price_numeric": float(m.group(8)),
        })

    if not records:
        raise ValueError("No records were parsed from the file.")

    print(f"    ✓ Parsed {len(records)} records")
    return records


def setup_database(cursor):
    print("[2/4] Setting up database schema in SQL Server...")

    cursor.execute("""
        IF OBJECT_ID('dbo.yearly_summary', 'U') IS NOT NULL
            DROP TABLE dbo.yearly_summary
    """)
    cursor.execute("""
        IF OBJECT_ID('dbo.books_raw', 'U') IS NOT NULL
            DROP TABLE dbo.books_raw
    """)

    cursor.execute("""
        CREATE TABLE dbo.books_raw (
            id               NVARCHAR(25)   NOT NULL PRIMARY KEY,
            title            NVARCHAR(500)  NOT NULL,
            author           NVARCHAR(300)  NOT NULL,
            genre            NVARCHAR(100)  NOT NULL,
            publisher        NVARCHAR(300)  NOT NULL,
            year             INT            NOT NULL,
            price_raw        NVARCHAR(20)   NOT NULL,
            currency_symbol  NCHAR(1)       NOT NULL,
            price_numeric    DECIMAL(10,2)  NOT NULL
        )
    """)
    cursor.commit()
    print("    ✓ Table 'dbo.books_raw' created")


def insert_raw_books(cursor, records: list[dict]):
    print("[3/4] Inserting raw records into books_raw...")

    rows = [(
        r["id"], r["title"], r["author"], r["genre"],
        r["publisher"], r["year"],
        r["price_raw"], r["currency_symbol"], r["price_numeric"]
    ) for r in records]

    cursor.executemany("""
        INSERT INTO dbo.books_raw
            (id, title, author, genre, publisher, year,
             price_raw, currency_symbol, price_numeric)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    cursor.commit()

    cursor.execute("SELECT COUNT(*) FROM dbo.books_raw")
    count = cursor.fetchone()[0]
    print(f"    ✓ books_raw row count: {count}")


SUMMARY_SQL = """
    SELECT
        year AS publication_year,
        COUNT(*) AS book_count,
        ROUND(AVG(
            CASE
                WHEN currency_symbol = '$' THEN price_numeric
                WHEN currency_symbol = N'€' THEN price_numeric * 1.2
            END
        ), 2) AS average_price_usd
    INTO dbo.yearly_summary
    FROM dbo.books_raw
    GROUP BY year
"""


def create_summary_table(cursor):
    print("[4/4] Creating yearly_summary via SQL transformation...")

    cursor.execute(SUMMARY_SQL)
    cursor.commit()

    cursor.execute("SELECT COUNT(*) FROM dbo.yearly_summary")
    summary_count = cursor.fetchone()[0]
    print(f"    ✓ yearly_summary row count: {summary_count}")

    cursor.execute("""
        SELECT publication_year, book_count, average_price_usd
        FROM dbo.yearly_summary
        ORDER BY publication_year
    """)
    rows = cursor.fetchall()

    print()
    print(f"{'publication_year':<20}{'book_count':<15}{'average_price_usd':<20}")
    print("-" * 55)
    for row in rows:
        print(f"{row[0]:<20}{row[1]:<15}{float(row[2]):<20.2f}")


def main():
    filepath = sys.argv[1] if len(sys.argv) > 1 else "task1_d.json"

    print("=" * 56)
    print("  Book Data Ingestion — Task 1 (SQL Server)")
    print("=" * 56)

    records = parse_ruby_hash_file(filepath)

    print(f"    Connecting to SQL Server: {SERVER} / {DATABASE}")
    conn = pyodbc.connect(CONN_STR, autocommit=False)
    cursor = conn.cursor()

    setup_database(cursor)
    insert_raw_books(cursor, records)
    create_summary_table(cursor)

    cursor.close()
    conn.close()

    print()
    print("Done")
    print("   • dbo.books_raw")
    print("   • dbo.yearly_summary")


if __name__ == "__main__":
    main()
