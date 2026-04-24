# fake — SQL Stored Procedure Library Documentation

A deterministic fake-data generator implemented as PostgreSQL stored procedures in the `fake` schema.

---

## Overview

All generators take a `(seed, batch, pos)` triplet that fully determines the output.
Identical arguments always return identical data — reproduction is guaranteed across sessions.

| Parameter | Meaning |
|-----------|---------|
| `seed`    | User-supplied integer; controls the overall randomness family |
| `batch`   | 0-based batch/page index |
| `pos`     | 1-based position within the batch (1–10) |
| `field`   | Internal discriminator per logical attribute |

---

## Core RNG

### `fake.rng(seed, batch, pos, field) → float8`

Returns a deterministic float in `[0, 1)`.

**Algorithm:**  
Concatenates the four integers with `chr(1)` separators and passes the string to PostgreSQL's built-in `hashtext()`.  
The absolute value is reduced modulo 10⁹ and divided to produce a float:

```
result = abs(hashtext(seed || '\x01' || batch || '\x01' || pos || '\x01' || field))
         % 1_000_000_000
         / 1_000_000_000.0
```

Every distinct `field` value yields an independent pseudo-random stream for the same `(seed, batch, pos)`.

---

### `fake.rng_int(seed, batch, pos, field, lo, hi) → int`

Returns a uniform integer in `[lo, hi]`.

```
result = lo + floor(rng(...) × (hi − lo + 1))
```

---

### `fake.rng_normal(seed, batch, pos, field, mean, stddev) → float8`

Returns a normally distributed float using the **Box-Muller transform**.

**Algorithm:**  
Two independent uniform samples are drawn from consecutive fields:

```
U1 = max(rng(..., field),     ε)   -- avoid log(0)
U2 =     rng(..., field + 1)

Z  = √(−2 · ln U1) · cos(2π · U2)

result = mean + stddev · Z
```

This produces a sample from N(mean, stddev²).  
Physical values are clamped to physiologically plausible ranges after generation.

---

### `fake.rng_geo(seed, batch, pos) → (lat float8, lon float8)`

Returns coordinates uniformly distributed **on the sphere**.

**Why not two independent uniform floats?**  
If latitude is drawn uniformly in `[−90°, 90°]`, points cluster near the poles because equal angular bands near the poles cover smaller surface areas than those near the equator.

**Correct algorithm (inverse CDF):**  
The PDF of latitude on a sphere is proportional to `cos(φ)`, which means `sin(φ)` is uniformly distributed in `[−1, 1]`.  
Drawing `U ~ U(0,1)` and applying the inverse CDF gives:

```
lat = arcsin(2U − 1)     →  uniform on sphere in latitude
lon = 360·U₂ − 180       →  uniform in [−180, 180)
```

Fields used: 20 (lat U), 21 (lon U).

---

## Lookup Helper

### `fake.pick(locale, category, seed, batch, pos, field) → text`

Picks a deterministic row from `fake.lookup` for the given `(locale, category)`.

1. Count rows matching `locale` + `category`.
2. Compute `idx = rng_int(..., 1, count)`.
3. Return the row at position `idx` (using `ROW_NUMBER() OVER (ORDER BY id)`).

---

### `fake.zip_fill(pattern, seed, batch, pos, field_base) → text`

Replaces each `#` character in `pattern` with a random digit (0–9).  
Each `#` consumes one field slot (field_base, field_base+1, …).  
Used for ZIP / postal codes.

---

## High-Level Generators

### `fake.gen_name(locale, seed, batch, pos) → text`

Generates a full name with optional title and middle name.

| Field | Attribute |
|-------|-----------|
| 0 | Gender (0=male, 1=female) — 50 % each |
| 1 | Include title? (25 % chance) |
| 2 | Title selection |
| 3 | First name selection |
| 4 | Include middle name? (40 % chance) |
| 5 | Middle name selection |
| 6 | Last name selection |

**EN-US title examples:** Mr., Dr., Prof., Rev., Ms., Mrs., Miss  
**DE-DE title examples:** Herr, Dr., Prof., Dipl.-Ing., Frau

---

### `fake.gen_address(locale, seed, batch, pos) → text`

Generates a multi-line postal address.

| Field | Attribute |
|-------|-----------|
| 10 | Street number (1–999) |
| 11 | Street name |
| 12 | Street suffix |
| 13 | City row (JSON: city, state, zip_pattern) |
| 14 | Format variant (0–2) |
| 15–19 | ZIP code digits |
| 70 | Apartment/suite number |

**EN-US variants:**
- `0`: `123 Maple Street\nSpringfield, IL 62701`
- `1`: `123 Maple Street, Apt 7\nSpringfield, IL 62701`
- `2`: `123 Maple Street, Suite 200\nSpringfield, IL 62701`

**DE-DE variants:**
- `0`: `Musterstraße 12\n12345 Berlin, Berlin`
- `1`: `Musterstraße 12, Wohnung 3\n12345 Berlin, Berlin`
- `2`: `Musterstraße 12, Etage 2\n12345 Berlin, Berlin`

---

### `fake.gen_geo(seed, batch, pos) → text`

Returns `"lat, lon"` with 6 decimal places.  
See `fake.rng_geo` above for the sphere-uniform algorithm.

---

### `fake.gen_physical(locale, seed, batch, pos) → jsonb`

Returns `{ height, weight, age, eye_color }`.

| Attribute | Distribution | Male params | Female params |
|-----------|-------------|-------------|---------------|
| Height    | Normal + clamp [140, 220] cm | μ=178 cm, σ=7 cm | μ=165 cm, σ=6 cm |
| Weight    | Normal + clamp [40, 180] kg  | μ=82 kg, σ=14 kg | μ=67 kg, σ=12 kg |
| Age       | Normal + clamp [18, 90]       | μ=38, σ=15 (shared) | — |
| Eye color | Discrete uniform from lookup  | — | — |

**EN-US:** height displayed as `5'10"`, weight as `lbs`.  
**DE-DE:** height as `cm`, weight as `kg`.

Fields 30–31 (height Box-Muller), 32–33 (weight Box-Muller), 34 (eye color), 35–36 (age Box-Muller).

---

### `fake.gen_phone(locale, seed, batch, pos) → text`

Generates a formatted phone number in 4 EN-US or 4 DE-DE variants.

**EN-US formats:**
- `+1 (555) 234-5678`
- `(555) 234-5678`
- `555-234-5678`
- `+1-555-234-5678`

**DE-DE formats:**
- `+49 175 1234567`
- `0175 1234567`
- `+49 (055) 1234567`
- `055-1234567`

---

### `fake.gen_email(seed, batch, pos, first_name, last_name) → text`

Generates an email address from 5 patterns + optional 2-digit numeric suffix (30 % chance).

| Pattern | Example |
|---------|---------|
| `firstname.lastname@domain` | `john.smith@gmail.com` |
| `f.lastname@domain` | `j.smith@gmail.com` |
| `firstname_lastname@domain` | `john_smith@yahoo.com` |
| `lastname.firstname@domain` | `smith.john@outlook.com` |
| `firstnamelastname@domain`  | `johnsmith42@icloud.com` |

Domain is picked from `fake.lookup` where `category = 'email_domain'` and `locale = 'any'`.

---

## Batch Generator

### `fake.gen_batch(locale, seed, batch) → TABLE(pos int, user_data jsonb)`

Returns 10 user records by calling `fake.gen_user(locale, seed, batch, i)` for `i ∈ [1, 10]`.

```sql
SELECT * FROM fake.gen_batch('en-US', 42, 0);
SELECT * FROM fake.gen_batch('en-US', 42, 1);  -- next page, same seed
SELECT * FROM fake.gen_batch('en-US', 99, 0);  -- different seed
```

---

## Benchmark

### `fake.benchmark(locale, seed, n_batches) → float8`

Generates `n_batches × 10` users and returns **users/second**.

```sql
SELECT fake.benchmark('en-US', 42, 500);
-- returns e.g. 4800.5 (users/second)
```

---

## Database Schema

```
fake.lookup
  id       SERIAL PK
  locale   VARCHAR(10)   -- 'en-US' | 'de-DE' | 'any'
  category VARCHAR(50)   -- 'first_male' | 'last' | 'city' | ...
  value    TEXT
```

All generators look up data from this single extensible table.  
Adding a new locale requires only inserting rows with the appropriate `locale` value — no schema changes needed.

---

## Reproducibility Guarantee

Given identical `(locale, seed, batch, pos)`, `fake.gen_user` always returns the same record because:

1. `fake.rng` is declared `IMMUTABLE` — PostgreSQL can cache/inline it.
2. `hashtext` is deterministic within a PostgreSQL major version.
3. No random state, no sequences, no timestamps are used.
