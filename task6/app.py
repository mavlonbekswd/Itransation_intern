import os
import time
import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:w3soox1mm@localhost/fakegen"
)

LOCALES = [
    ("en-US", "English / USA"),
    ("de-DE", "German / Germany"),
]


def get_conn():
    return psycopg2.connect(DB_DSN)


@app.route("/")
def index():
    locale = request.args.get("locale", "en-US")
    seed   = int(request.args.get("seed",  42))
    batch  = int(request.args.get("batch",  0))

    users = []
    error = None
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT pos, user_data"
                    " FROM fake.generate_users(%s, %s, %s, 10)",
                    (locale, seed, batch)
                )
                for row in cur.fetchall():
                    u = row["user_data"]
                    u["pos"] = row["pos"]
                    phys = u["physical"]
                    u["physical_items"] = [
                        ("Gender",    phys.get("gender", "")),
                        ("Height",    phys.get("height", "")),
                        ("Weight",    phys.get("weight", "")),
                        ("Age",       phys.get("age", "")),
                        ("Eye color", phys.get("eye_color", "")),
                    ]
                    users.append(u)
    except Exception as exc:
        error = str(exc)

    return render_template(
        "index.html",
        users=users,
        locales=LOCALES,
        locale=locale,
        seed=seed,
        batch=batch,
        error=error,
    )


@app.route("/api/users")
def api_users():
    locale = request.args.get("locale", "en-US")
    seed   = int(request.args.get("seed",  42))
    batch  = int(request.args.get("batch",  0))

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT pos, user_data"
                " FROM fake.generate_users(%s, %s, %s, 10)",
                (locale, seed, batch)
            )
            rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/benchmark")
def api_benchmark():
    locale    = request.args.get("locale",    "en-US")
    seed      = int(request.args.get("seed",      42))
    n_batches = int(request.args.get("n_batches", 100))

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fake.benchmark(%s, %s, %s)",
                (locale, seed, n_batches)
            )
            rate = cur.fetchone()[0]
    return jsonify({
        "users_generated": n_batches * 10,
        "users_per_second": round(rate, 1),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
