from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

W, H = A4
OUT = "/Users/user/Desktop/Itransation (Intern)/task6/documentation.pdf"

doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm,
    topMargin=2*cm, bottomMargin=2*cm
)

base = getSampleStyleSheet()

# ── custom styles ──────────────────────────────────────────
DARK   = colors.HexColor("#0f3460")
ACCENT = colors.HexColor("#1a5276")
GRAY   = colors.HexColor("#555555")
LGRAY  = colors.HexColor("#f0f2f5")

title_s = ParagraphStyle("mytitle", parent=base["Title"],
    textColor=DARK, fontSize=24, spaceAfter=4)
sub_s = ParagraphStyle("mysub", parent=base["Normal"],
    textColor=ACCENT, fontSize=11, spaceAfter=14, alignment=TA_CENTER)
h1_s = ParagraphStyle("myh1", parent=base["Heading1"],
    textColor=DARK, fontSize=13, spaceBefore=14, spaceAfter=4,
    borderPad=4)
h2_s = ParagraphStyle("myh2", parent=base["Heading2"],
    textColor=ACCENT, fontSize=11, spaceBefore=8, spaceAfter=3)
body_s = ParagraphStyle("mybody", parent=base["Normal"],
    fontSize=9.5, leading=14, textColor=colors.HexColor("#222222"))
code_s = ParagraphStyle("mycode", parent=base["Code"],
    fontSize=8.5, leading=13, textColor=colors.HexColor("#1a1a2e"),
    backColor=LGRAY, borderPad=6, fontName="Courier")
bullet_s = ParagraphStyle("mybullet", parent=body_s,
    leftIndent=14, bulletIndent=4, spaceAfter=2)

def h1(txt):  return Paragraph(txt, h1_s)
def h2(txt):  return Paragraph(txt, h2_s)
def p(txt):   return Paragraph(txt, body_s)
def code(txt): return Paragraph(txt, code_s)
def b(txt):   return Paragraph(f"• {txt}", bullet_s)
def sp(n=6):  return Spacer(1, n)
def hr():     return HRFlowable(color=DARK, thickness=0.5, spaceAfter=4)

def table(data, col_widths=None):
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (-1,0), DARK),
        ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
        ("FONTNAME",    (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",    (0,0), (-1,-1), 8.5),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LGRAY]),
        ("GRID",        (0,0), (-1,-1), 0.3, colors.HexColor("#cccccc")),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",  (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    return t

# ══════════════════════════════════════════════════════════
story = []

# ── Title ────────────────────────────────────────────────
story.append(sp(10))
story.append(Paragraph("Fake User Generator", title_s))
story.append(Paragraph("Task 6 &nbsp;|&nbsp; PostgreSQL + Python / Flask", sub_s))
story.append(hr())
story.append(sp(4))

# ── 1. Overview ──────────────────────────────────────────
story.append(h1("1. Overview"))
story.append(p("A web application that generates deterministic fake user contact data. "
               "All generation logic lives exclusively in PostgreSQL stored procedures — "
               "Python/Flask is just a read-only client that calls them and renders HTML."))
story.append(sp())
story += [
    b("Two locales supported: <b>English / USA</b> and <b>German / Germany</b>"),
    b("User picks a <b>seed</b> and a <b>batch index</b> — same inputs always return same data"),
    b("10 users generated per batch; navigate forward/backward freely"),
]
story.append(sp(8))

# ── 2. Tech Stack ────────────────────────────────────────
story.append(h1("2. Tech Stack"))
story.append(table(
    [["Component", "Role"],
     ["PostgreSQL 17", "All generation logic — stored procedures only"],
     ["Python 3 + Flask", "Web server, renders HTML templates"],
     ["psycopg2", "Python ↔ PostgreSQL connector"],
     ["HTML / CSS", "Frontend UI"]],
    col_widths=[5.5*cm, 11*cm]
))
story.append(sp(8))

# ── 3. Database Schema ───────────────────────────────────
story.append(h1("3. Database Schema"))
story.append(p("One extensible table — adding a new locale requires only inserting rows, no schema changes:"))
story.append(sp(4))
story.append(code(
    "fake.lookup ( id SERIAL, locale VARCHAR(10), category VARCHAR(50), value TEXT )\n"
    "\n"
    "locale    →  'en-US' | 'de-DE' | 'any'\n"
    "category  →  'first_male' | 'first_female' | 'last' | 'middle_male'\n"
    "             'title_male' | 'title_female' | 'street_name' | 'street_suffix'\n"
    "             'city' | 'eye_color' | 'email_domain'"
))
story.append(sp(4))
story += [
    b("~150 first names per gender per locale, ~500 last names → 150 000+ unique full names"),
    b("50 cities per locale with state and ZIP pattern (stored as JSON in value)"),
    b("100+ street names, 6 eye colors, 20 email domains"),
]
story.append(sp(8))

# ── 4. Core RNG ──────────────────────────────────────────
story.append(h1("4. Core RNG — fake.rng(seed, idx, field)"))
story.append(p("Hash-based deterministic pseudo-random number generator. No RANDOM(), no sequences."))
story.append(sp(4))
story.append(code(
    "key    =  seed || chr(1) || idx || chr(1) || field\n"
    "raw    =  abs( hashtext(key) )          -- int in [0, 2^31)\n"
    "result =  (raw % 1_000_000_000) / 1e9   -- float in [0, 1)"
))
story.append(sp(4))
story += [
    b("Declared <b>IMMUTABLE</b> — PostgreSQL can cache / inline it"),
    b("Each (seed, idx, field) triple is an independent, reproducible stream"),
    b("chr(1) separator prevents collisions like '1|23' vs '12|3'"),
]
story.append(sp(8))

# ── 5. Stored Procedures ─────────────────────────────────
story.append(h1("5. Stored Procedures — Public API"))
story.append(table(
    [["Procedure", "Returns", "Description"],
     ["fake.rng(seed, idx, field)", "float8", "Base deterministic RNG"],
     ["fake.rng_int(..., lo, hi)", "int", "Uniform integer in [lo, hi]"],
     ["fake.rng_normal(..., mean, s)", "float8", "Normal dist. via Box-Muller"],
     ["fake.generate_name(locale, seed, idx)", "text", "Full name, optional title/middle"],
     ["fake.generate_address(locale, seed, idx)", "text", "Postal address, 3 variants"],
     ["fake.generate_coordinates(seed, idx)", "text", "Lat/lon uniform on sphere"],
     ["fake.generate_physical_attributes(...)", "jsonb", "Height, weight, age, eye color"],
     ["fake.generate_phone(locale, seed, idx)", "text", "Phone, 4 format variants"],
     ["fake.generate_email(locale, seed, idx)", "text", "Email, 5 pattern variants"],
     ["fake.generate_user(locale, seed, idx)", "jsonb", "Complete user record"],
     ["fake.generate_users(locale, seed, batch, n)", "TABLE", "Batch of n users"],
     ["fake.benchmark(locale, seed, n_batches)", "float8", "Throughput in users/sec"]],
    col_widths=[6.5*cm, 2.5*cm, 7.5*cm]
))
story.append(sp(8))

# ── 6. Key Algorithms ────────────────────────────────────
story.append(h1("6. Key Algorithms"))

story.append(h2("Normal Distribution — Box-Muller Transform"))
story.append(code(
    "U1 = max( rng(..., field),   1e-10 )   -- avoid ln(0)\n"
    "U2 =      rng(..., field+1)\n"
    "Z  = sqrt( -2 * ln(U1) ) * cos( 2*pi * U2 )   -- N(0,1)\n"
    "result = mean + stddev * Z"
))
story.append(sp(4))
story += [
    b("Height: male N(178 cm, 7) &nbsp; female N(165 cm, 6) &nbsp; clamped [140, 220]"),
    b("Weight: male N(82 kg, 14) &nbsp; female N(67 kg, 12) &nbsp; clamped [40, 180]"),
    b("Age: N(38, 15) clamped [18, 90]"),
]
story.append(sp(8))

story.append(h2("Sphere-Uniform Geolocation"))
story.append(p("Naive approach (uniform lat in [−90, 90]) clusters points near the poles "
               "because equal angular bands cover less surface area there. "
               "The correct method uses the inverse CDF:"))
story.append(sp(4))
story.append(code(
    "lat = degrees( arcsin( 2*U1 - 1 ) )   -- uniform on sphere surface\n"
    "lon = 360 * U2 - 180                   -- uniform in [-180, 180)"
))
story.append(sp(8))

story.append(h2("Reproducibility"))
story.append(code(
    "global_index = batch_index * batch_size + position_in_batch\n"
    "fake.rng( seed, global_index, field )  -- always the same value"
))
story.append(sp(8))

# ── 7. Generated Fields ──────────────────────────────────
story.append(h1("7. Generated Fields per User"))
story.append(table(
    [["Field", "Details"],
     ["Full name", "Title (25%) + First + Middle (40%) + Last"],
     ["Address", "Number + Street + Suffix + City + State + ZIP, 3 layout variants"],
     ["Geolocation", "Lat / lon — uniform on sphere (inverse CDF method)"],
     ["Physical", "Height & weight (normal dist.), age (normal, clamped), eye color (discrete)"],
     ["Phone", "4 format variants per locale — e.g. +1 (555) 234-5678 or 0175 1234567"],
     ["Email", "5 patterns: firstname.last, f.last, first_last, last.first, firstlast"]],
    col_widths=[3.5*cm, 13*cm]
))
story.append(sp(8))

# ── 8. How to Run ────────────────────────────────────────
story.append(h1("8. How to Run"))
story.append(code(
    "# 1. Create database\n"
    "createdb fakegen\n\n"
    "# 2. Load schema, procedures, data\n"
    "psql fakegen -f db/01_schema.sql\n"
    "psql fakegen -f db/02_procedures.sql\n"
    "psql fakegen -f db/03_seed_data.sql\n\n"
    "# 3. Install Python deps and start\n"
    "pip install -r requirements.txt\n"
    "python app.py         # → http://localhost:5000"
))
story.append(sp(8))

# ── 9. Benchmark ─────────────────────────────────────────
story.append(h1("9. Benchmark"))
story += [
    b("Browser: <b>GET /api/benchmark?locale=en-US&amp;seed=42&amp;n_batches=200</b>"),
    b("SQL:     <b>SELECT fake.benchmark('en-US', 42, 500);</b>"),
    b("Returns users/second — typically several thousand on a local machine"),
]
story.append(sp(8))
story.append(hr())
story.append(Paragraph("Generated for Task 6 — Itransition Internship",
    ParagraphStyle("foot", parent=body_s, textColor=GRAY,
                   fontSize=8, alignment=TA_CENTER, spaceBefore=6)))

doc.build(story)
print("PDF saved to", OUT)
