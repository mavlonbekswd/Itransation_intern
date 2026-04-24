-- ============================================================
-- Fake Data Generator — Stored Procedures
-- ALL data generation logic lives here. Python is a read-only client.
--
-- Public API (new single-index design):
--   fake.generate_random_number(seed, index)         → float8
--   fake.generate_name(locale, seed, index)          → text
--   fake.generate_address(locale, seed, index)       → text
--   fake.generate_coordinates(seed, index)           → text
--   fake.generate_physical_attributes(locale, seed, index) → jsonb
--   fake.generate_phone(locale, seed, index)         → text
--   fake.generate_email(locale, seed, index)         → text
--   fake.generate_user(locale, seed, index)          → jsonb
--   fake.generate_users(locale, seed, batch_index, batch_size) → TABLE
--   fake.benchmark(locale, seed, n_batches)          → float8
-- ============================================================


-- ────────────────────────────────────────────────────────────
-- §1  CORE DETERMINISTIC RNG
-- ────────────────────────────────────────────────────────────

-- fake.rng(seed, idx, field) → float8 in [0, 1)
--
-- Deterministic hash-based PRNG. No RANDOM(), no sequences.
--
-- Algorithm:
--   key    = seed ‖ chr(1) ‖ idx ‖ chr(1) ‖ field
--   raw    = abs(hashtext(key))          -- int4 → [0, 2^31)
--   scaled = (raw::int8 mod 10^9)        -- [0, 999_999_999]
--   result = scaled / 10^9               -- [0.000…, 0.999…)
--
-- chr(1) is used as a separator so "1|23" ≠ "12|3".
--
-- Properties:
--   • IMMUTABLE — PostgreSQL may cache or inline calls
--   • Each (seed, idx, field) triple is an independent stream
--   • Identical arguments always return identical value
--
-- Field numbers are reserved per generator (see each function).
CREATE OR REPLACE FUNCTION fake.rng(
    p_seed  INT,
    p_idx   INT,
    p_field INT
) RETURNS FLOAT8 AS $$
    SELECT (
        abs(hashtext(
            p_seed::TEXT  || chr(1) ||
            p_idx::TEXT   || chr(1) ||
            p_field::TEXT
        ))::BIGINT % 1000000000
    ) / 1000000000.0;
$$ LANGUAGE SQL IMMUTABLE STRICT;


-- fake.rng_int(seed, idx, field, lo, hi) → int in [lo, hi]
--
-- Uniform integer in the closed interval [lo, hi].
-- Uses floor() not cast, avoiding rounding bias at the upper bound:
--   floor(rng() × (hi−lo+1)) ∈ {0,…,hi−lo}   since rng() < 1 strictly
CREATE OR REPLACE FUNCTION fake.rng_int(
    p_seed  INT,
    p_idx   INT,
    p_field INT,
    p_lo    INT,
    p_hi    INT
) RETURNS INT AS $$
    SELECT p_lo + floor(fake.rng(p_seed, p_idx, p_field) * (p_hi - p_lo + 1))::INT;
$$ LANGUAGE SQL IMMUTABLE STRICT;


-- fake.rng_normal(seed, idx, field, mean, stddev) → float8
--
-- Normal distribution N(mean, stddev²) via Box-Muller transform.
-- Consumes two consecutive fields: p_field and p_field+1.
--
-- Algorithm:
--   U1 = max(rng(…, field  ), ε)   -- clamp away from 0 to avoid ln(0)
--   U2 =     rng(…, field+1)
--   Z  = √(−2·ln U1) · cos(2π·U2) -- standard normal N(0,1)
--   result = mean + σ·Z
--
-- Callers must reserve two adjacent field IDs per invocation.
CREATE OR REPLACE FUNCTION fake.rng_normal(
    p_seed   INT,
    p_idx    INT,
    p_field  INT,
    p_mean   FLOAT8,
    p_stddev FLOAT8
) RETURNS FLOAT8 AS $$
DECLARE
    u1 FLOAT8 := GREATEST(fake.rng(p_seed, p_idx, p_field),     1e-10);
    u2 FLOAT8 :=          fake.rng(p_seed, p_idx, p_field + 1);
BEGIN
    RETURN p_mean + p_stddev * sqrt(-2.0 * ln(u1)) * cos(2.0 * pi() * u2);
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT;


-- ────────────────────────────────────────────────────────────
-- §2  PUBLIC ENTRY POINT: generate_random_number
-- ────────────────────────────────────────────────────────────

-- fake.generate_random_number(seed, index) → float8 in [0, 1)
--
-- Exposes the raw deterministic RNG. Same (seed, index) always
-- returns the same float. Useful for testing or custom logic.
CREATE OR REPLACE FUNCTION fake.generate_random_number(
    p_seed  INT,
    p_index INT
) RETURNS FLOAT8 AS $$
    SELECT fake.rng(p_seed, p_index, 0);
$$ LANGUAGE SQL IMMUTABLE STRICT;


-- ────────────────────────────────────────────────────────────
-- §3  LOOKUP HELPERS
-- ────────────────────────────────────────────────────────────

-- fake.pick(locale, category, seed, idx, field) → text
--
-- Picks one row from fake.lookup deterministically.
-- Algorithm:
--   1. Count N rows for (locale, category)
--   2. offset = floor(rng(…) × N)   — in [0, N-1]
--   3. Return row at OFFSET via the composite index (locale, category, id)
--      which allows an index-only seek without scanning all N rows.
CREATE OR REPLACE FUNCTION fake.pick(
    p_locale   TEXT,
    p_category TEXT,
    p_seed     INT,
    p_idx      INT,
    p_field    INT
) RETURNS TEXT AS $$
DECLARE
    v_count  INT;
    v_offset INT;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM   fake.lookup
    WHERE  locale = p_locale AND category = p_category;

    IF v_count = 0 THEN RETURN NULL; END IF;

    v_offset := floor(fake.rng(p_seed, p_idx, p_field) * v_count)::INT;

    RETURN (
        SELECT value
        FROM   fake.lookup
        WHERE  locale = p_locale AND category = p_category
        ORDER  BY id
        LIMIT  1
        OFFSET v_offset
    );
END;
$$ LANGUAGE plpgsql STABLE STRICT;


-- fake.zip_fill(pattern, seed, idx, field_base) → text
--
-- Replaces each '#' in pattern with a random digit 0-9.
-- Each '#' consumes one field slot starting at field_base.
-- Example: zip_fill('606##', seed, idx, 15) uses fields 15 and 16.
CREATE OR REPLACE FUNCTION fake.zip_fill(
    p_pattern    TEXT,
    p_seed       INT,
    p_idx        INT,
    p_field_base INT
) RETURNS TEXT AS $$
DECLARE
    v_result TEXT := '';
    v_ch     CHAR;
    v_fld    INT  := p_field_base;
BEGIN
    FOR i IN 1..length(p_pattern) LOOP
        v_ch := substr(p_pattern, i, 1);
        IF v_ch = '#' THEN
            v_result := v_result || fake.rng_int(p_seed, p_idx, v_fld, 0, 9)::TEXT;
            v_fld    := v_fld + 1;
        ELSE
            v_result := v_result || v_ch;
        END IF;
    END LOOP;
    RETURN v_result;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT;


-- ────────────────────────────────────────────────────────────
-- §4  INTERNAL NAME HELPERS
-- ────────────────────────────────────────────────────────────
-- These share field IDs with generate_name so generate_email
-- always derives the same first/last name as the displayed name.
--
-- Field allocation for names:
--   0  gender         (< 0.5 → male)
--   1  title flag     (< 0.25 → include title)
--   2  title index
--   3  first-name index
--   4  middle flag    (< 0.40 → include middle name)
--   5  middle-name index
--   6  last-name index
--   7  middle initial flag (< 0.5 → initial only)

CREATE OR REPLACE FUNCTION fake._first_name(
    p_locale TEXT,
    p_seed   INT,
    p_idx    INT
) RETURNS TEXT AS $$
DECLARE
    v_cat TEXT := CASE WHEN fake.rng(p_seed, p_idx, 0) < 0.5
                       THEN 'first_male' ELSE 'first_female' END;
BEGIN
    RETURN fake.pick(p_locale, v_cat, p_seed, p_idx, 3);
END;
$$ LANGUAGE plpgsql STABLE STRICT;

CREATE OR REPLACE FUNCTION fake._last_name(
    p_locale TEXT,
    p_seed   INT,
    p_idx    INT
) RETURNS TEXT AS $$
BEGIN
    RETURN fake.pick(p_locale, 'last', p_seed, p_idx, 6);
END;
$$ LANGUAGE plpgsql STABLE STRICT;


-- ────────────────────────────────────────────────────────────
-- §5  generate_name
-- ────────────────────────────────────────────────────────────

-- fake.generate_name(locale, seed, index) → text
--
-- Builds a full name with optional title and middle name.
-- Gender is determined once (field 0) and used by all sub-picks.
--
-- 25 % of records include a title prefix.
-- 40 % of records include a middle name; of those, 50 % show initial only.
CREATE OR REPLACE FUNCTION fake.generate_name(
    p_locale TEXT,
    p_seed   INT,
    p_idx    INT
) RETURNS TEXT AS $$
DECLARE
    v_gender     INT  := CASE WHEN fake.rng(p_seed, p_idx, 0) < 0.5 THEN 0 ELSE 1 END;
    v_gtype      TEXT := CASE WHEN v_gender = 0 THEN 'male' ELSE 'female' END;
    v_use_title  BOOL := fake.rng(p_seed, p_idx, 1) < 0.25;
    v_use_middle BOOL := fake.rng(p_seed, p_idx, 4) < 0.40;
    v_title      TEXT := '';
    v_first      TEXT;
    v_middle     TEXT := '';
    v_last       TEXT;
    v_parts      TEXT[];
BEGIN
    IF v_use_title THEN
        v_title := coalesce(
            fake.pick(p_locale, 'title_' || v_gtype, p_seed, p_idx, 2), '');
    END IF;

    v_first := fake.pick(p_locale, 'first_' || v_gtype, p_seed, p_idx, 3);
    v_last  := fake.pick(p_locale, 'last',               p_seed, p_idx, 6);

    IF v_use_middle THEN
        v_middle := coalesce(
            fake.pick(p_locale, 'middle_' || v_gtype, p_seed, p_idx, 5), '');
        IF v_middle <> '' AND fake.rng(p_seed, p_idx, 7) < 0.5 THEN
            v_middle := substr(v_middle, 1, 1) || '.';
        END IF;
    END IF;

    v_parts := ARRAY_REMOVE(
        ARRAY[nullif(v_title, ''), v_first, nullif(v_middle, ''), v_last],
        NULL
    );
    RETURN array_to_string(v_parts, ' ');
END;
$$ LANGUAGE plpgsql STABLE STRICT;


-- ────────────────────────────────────────────────────────────
-- §6  generate_address
-- ────────────────────────────────────────────────────────────

-- fake.generate_address(locale, seed, index) → text
--
-- Generates a locale-formatted multi-line postal address.
-- City rows in fake.lookup store JSON: {"city":…,"state":…,"zip":"pattern"}
-- ZIP patterns use '#' placeholders filled by zip_fill().
--
-- Field map:
--   10  street number  (1–9999)
--   11  street name index
--   12  street suffix index
--   13  city JSON index
--   14  format variant (0–2)
--   15–19  ZIP digit fields (one per '#' in zip pattern; max 5)
--   20  apartment / floor number
--   21  floor number (de-DE variant 2)
--
-- EN-US variants:
--   0: "742 Evergreen Terrace\nSpringfield, IL 62704"
--   1: "742 Evergreen Terrace, Apt 7\nSpringfield, IL 62704"
--   2: "742 Evergreen Terrace, Suite 200\nSpringfield, IL 62704"
--
-- DE-DE variants:
--   0: "Hauptstraße 17\n10115 Berlin, Berlin"
--   1: "Hauptstraße 17, Wohnung 3\n10115 Berlin, Berlin"
--   2: "Hauptstraße 17, Etage 2\n10115 Berlin, Berlin"
CREATE OR REPLACE FUNCTION fake.generate_address(
    p_locale TEXT,
    p_seed   INT,
    p_idx    INT
) RETURNS TEXT AS $$
DECLARE
    v_num      INT  := fake.rng_int(p_seed, p_idx, 10, 1, 9999);
    v_street   TEXT := fake.pick(p_locale, 'street_name',   p_seed, p_idx, 11);
    v_suffix   TEXT := fake.pick(p_locale, 'street_suffix', p_seed, p_idx, 12);
    v_city_raw TEXT := fake.pick(p_locale, 'city',          p_seed, p_idx, 13);
    v_variant  INT  := fake.rng_int(p_seed, p_idx, 14, 0, 2);
    v_apt      INT  := fake.rng_int(p_seed, p_idx, 20, 1, 99);
    v_city_j   JSONB;
    v_city     TEXT;
    v_state    TEXT;
    v_zip      TEXT;
    v_line1    TEXT;
    v_line2    TEXT;
BEGIN
    v_city_j := v_city_raw::JSONB;
    v_city   := v_city_j->>'city';
    v_state  := v_city_j->>'state';
    v_zip    := fake.zip_fill(v_city_j->>'zip', p_seed, p_idx, 15);

    IF p_locale = 'en-US' THEN
        v_line1 := v_num::TEXT || ' ' || v_street || ' ' || v_suffix;
        CASE v_variant
            WHEN 1 THEN v_line1 := v_line1 || ', Apt '   || v_apt::TEXT;
            WHEN 2 THEN v_line1 := v_line1 || ', Suite ' || (v_apt * 10)::TEXT;
            ELSE NULL;
        END CASE;
        v_line2 := v_city || ', ' || v_state || ' ' || v_zip;
    ELSE  -- de-DE
        v_line1 := v_street || v_suffix || ' ' || v_num::TEXT;
        CASE v_variant
            WHEN 1 THEN v_line1 := v_line1 || ', Wohnung ' || v_apt::TEXT;
            WHEN 2 THEN v_line1 := v_line1 || ', Etage '
                                           || fake.rng_int(p_seed, p_idx, 21, 1, 5)::TEXT;
            ELSE NULL;
        END CASE;
        v_line2 := v_zip || ' ' || v_city || ', ' || v_state;
    END IF;

    RETURN v_line1 || E'\n' || v_line2;
END;
$$ LANGUAGE plpgsql STABLE STRICT;


-- ────────────────────────────────────────────────────────────
-- §7  generate_coordinates
-- ────────────────────────────────────────────────────────────

-- fake.generate_coordinates(seed, index) → text  "lat, lon"
--
-- Generates coordinates uniformly distributed ON THE SPHERE,
-- not merely uniformly over the latitude/longitude rectangle.
--
-- Why naive uniform([-90°,+90°]) fails:
--   Equal angular latitude bands have different surface areas
--   (poles have smaller area per degree), causing clustering near poles.
--
-- Correct algorithm — inverse CDF of the spherical PDF:
--   The PDF of latitude φ on a sphere is proportional to cos(φ).
--   Equivalently, sin(φ) is uniformly distributed in [-1, +1].
--   Applying the inverse CDF:
--
--     U1 ~ Uniform(0,1)
--     lat = arcsin(2·U1 − 1)    →  uniform in sin(lat) → uniform on sphere
--
--     U2 ~ Uniform(0,1)
--     lon = 360·U2 − 180        →  uniform in [−180°, +180°)
--
-- Fields: 30 = U1 (lat), 31 = U2 (lon)
-- Output: 6 decimal places ≈ 0.1 m precision
CREATE OR REPLACE FUNCTION fake.generate_coordinates(
    p_seed INT,
    p_idx  INT
) RETURNS TEXT AS $$
DECLARE
    u1  FLOAT8 := fake.rng(p_seed, p_idx, 30);
    u2  FLOAT8 := fake.rng(p_seed, p_idx, 31);
    lat FLOAT8 := degrees(asin(2.0 * u1 - 1.0));
    lon FLOAT8 := u2 * 360.0 - 180.0;
BEGIN
    RETURN round(lat::NUMERIC, 6)::TEXT || ', ' || round(lon::NUMERIC, 6)::TEXT;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT;


-- ────────────────────────────────────────────────────────────
-- §8  generate_physical_attributes
-- ────────────────────────────────────────────────────────────

-- fake.generate_physical_attributes(locale, seed, index) → jsonb
--
-- Returns {gender, height, weight, age, eye_color}.
-- Gender reuses field 0 (same as generate_name) for consistency.
--
-- All continuous attributes follow normal distributions
-- implemented with the Box-Muller transform (§1).
-- Each attribute consumes two adjacent fields (U1, U2).
--
-- Distribution parameters and field allocation:
--
--   Attribute  Gender   Mean    σ     Clamp        Fields
--   ─────────────────────────────────────────────────────
--   Height     Male     178 cm  7     [150, 220]   32, 33
--              Female   165 cm  6     [140, 200]
--   Weight     Male      82 kg  14    [ 45, 180]   34, 35
--              Female    67 kg  12    [ 40, 160]
--   Age        shared    38     15    [ 18,  90]   36, 37
--   Eye color  —         —      —     lookup       38
--
-- Locale formatting:
--   en-US: height → ft′ in″  (e.g. "5' 11\""), weight → lbs
--   de-DE: height → cm,      weight → kg
CREATE OR REPLACE FUNCTION fake.generate_physical_attributes(
    p_locale TEXT,
    p_seed   INT,
    p_idx    INT
) RETURNS JSONB AS $$
DECLARE
    v_gender    INT    := CASE WHEN fake.rng(p_seed, p_idx, 0) < 0.5 THEN 0 ELSE 1 END;
    v_height_cm FLOAT8;
    v_weight_kg FLOAT8;
    v_age       INT;
    v_eye       TEXT;
    v_height_s  TEXT;
    v_weight_s  TEXT;
    v_total_in  INT;
BEGIN
    -- Height  (fields 32, 33)
    IF v_gender = 0 THEN
        v_height_cm := fake.rng_normal(p_seed, p_idx, 32, 178.0,  7.0);
        v_weight_kg := fake.rng_normal(p_seed, p_idx, 34,  82.0, 14.0);
    ELSE
        v_height_cm := fake.rng_normal(p_seed, p_idx, 32, 165.0,  6.0);
        v_weight_kg := fake.rng_normal(p_seed, p_idx, 34,  67.0, 12.0);
    END IF;

    v_height_cm := GREATEST(140.0, LEAST(220.0, v_height_cm));
    v_weight_kg := GREATEST( 40.0, LEAST(180.0, v_weight_kg));

    -- Age  (fields 36, 37)
    v_age := GREATEST(18, LEAST(90,
        round(fake.rng_normal(p_seed, p_idx, 36, 38.0, 15.0))::INT
    ));

    -- Eye color  (field 38)
    v_eye := coalesce(
        fake.pick(p_locale, 'eye_color', p_seed, p_idx, 38),
        fake.pick('any',    'eye_color', p_seed, p_idx, 38)
    );

    -- Locale formatting
    IF p_locale = 'en-US' THEN
        v_total_in := round(v_height_cm / 2.54)::INT;
        v_height_s := (v_total_in / 12)::TEXT || '''' || ' '
                      || (v_total_in % 12)::TEXT || '"';
        v_weight_s := round(v_weight_kg * 2.20462)::INT::TEXT || ' lbs';
    ELSE
        v_height_s := round(v_height_cm)::INT::TEXT || ' cm';
        v_weight_s := round(v_weight_kg)::INT::TEXT || ' kg';
    END IF;

    RETURN jsonb_build_object(
        'gender',    CASE WHEN v_gender = 0 THEN 'Male' ELSE 'Female' END,
        'height',    v_height_s,
        'weight',    v_weight_s,
        'age',       v_age,
        'eye_color', v_eye
    );
END;
$$ LANGUAGE plpgsql STABLE STRICT;


-- ────────────────────────────────────────────────────────────
-- §9  generate_phone
-- ────────────────────────────────────────────────────────────

-- fake.generate_phone(locale, seed, index) → text
--
-- Generates a realistic phone number in one of 4 locale-specific formats.
-- Each digit is independently seeded (one field per digit).
--
-- Field map:
--   40  format variant (0–3)
--   41–50  digit groups (fields 41..43 = area/prefix, 44..46 = mid,
--                        47..50 = end; 51–52 = DE mobile suffix)
--
-- EN-US — North American Numbering Plan (NANP):
--   Area code: NXX  (N ∈ [2,9], X ∈ [0,9])
--   0: "+1 (NXX) NXX-XXXX"
--   1: "(NXX) NXX-XXXX"
--   2: "NXX-NXX-XXXX"
--   3: "+1-NXX-NXX-XXXX"
--
-- DE-DE — German mobile numbers (BNetzA format):
--   Mobile prefix: 015x / 016x / 017x
--   0: "+49 17X XXXXXXX"
--   1: "017X XXXXXXX"
--   2: "+49 (0XX) XXXXXXX"
--   3: "0XX-XXXXXXX"
CREATE OR REPLACE FUNCTION fake.generate_phone(
    p_locale TEXT,
    p_seed   INT,
    p_idx    INT
) RETURNS TEXT AS $$
DECLARE
    v_fmt INT := fake.rng_int(p_seed, p_idx, 40, 0, 3);
    a1 INT := fake.rng_int(p_seed, p_idx, 41, 2, 9);
    a2 INT := fake.rng_int(p_seed, p_idx, 42, 0, 9);
    a3 INT := fake.rng_int(p_seed, p_idx, 43, 0, 9);
    b1 INT := fake.rng_int(p_seed, p_idx, 44, 2, 9);
    b2 INT := fake.rng_int(p_seed, p_idx, 45, 0, 9);
    b3 INT := fake.rng_int(p_seed, p_idx, 46, 0, 9);
    c1 INT := fake.rng_int(p_seed, p_idx, 47, 0, 9);
    c2 INT := fake.rng_int(p_seed, p_idx, 48, 0, 9);
    c3 INT := fake.rng_int(p_seed, p_idx, 49, 0, 9);
    c4 INT := fake.rng_int(p_seed, p_idx, 50, 0, 9);
    v_area TEXT;
    v_mid  TEXT;
    v_end  TEXT;
    v_mob  TEXT;
BEGIN
    v_area := a1::TEXT || a2::TEXT || a3::TEXT;
    v_mid  := b1::TEXT || b2::TEXT || b3::TEXT;
    v_end  := c1::TEXT || c2::TEXT || c3::TEXT || c4::TEXT;

    IF p_locale = 'en-US' THEN
        RETURN CASE v_fmt
            WHEN 0 THEN '+1 (' || v_area || ') ' || v_mid || '-' || v_end
            WHEN 1 THEN '('    || v_area || ') ' || v_mid || '-' || v_end
            WHEN 2 THEN v_area || '-' || v_mid || '-' || v_end
            ELSE       '+1-'  || v_area || '-' || v_mid || '-' || v_end
        END;
    ELSE  -- de-DE: prefix 15x/16x/17x
        v_mob := '1' || fake.rng_int(p_seed, p_idx, 51, 5, 7)::TEXT
                      || fake.rng_int(p_seed, p_idx, 52, 0, 9)::TEXT;
        RETURN CASE v_fmt
            WHEN 0 THEN '+49 '    || v_mob || ' '  || v_mid || v_end
            WHEN 1 THEN '0'       || v_mob || ' '  || v_mid || v_end
            WHEN 2 THEN '+49 (0'  || a1::TEXT || a2::TEXT || ') ' || v_mid || v_end
            ELSE       '0'        || a1::TEXT || a2::TEXT || a3::TEXT
                                  || '-' || v_mid || v_end
        END;
    END IF;
END;
$$ LANGUAGE plpgsql STABLE STRICT;


-- ────────────────────────────────────────────────────────────
-- §10  generate_email
-- ────────────────────────────────────────────────────────────

-- fake.generate_email(locale, seed, index) → text
--
-- Email is derived from the same first/last name as generate_name
-- (via _first_name/_last_name which use fields 0, 3, 6).
-- This guarantees email always matches the displayed name.
--
-- Field map:
--   55  pattern  (0–4)
--   56  domain index
--   57  numeric suffix flag  (< 0.30 → append 2-digit number)
--   58  numeric suffix value (10–99)
--
-- Patterns:
--   0: firstname.lastname@domain
--   1: f.lastname@domain          (first initial)
--   2: firstname_lastname@domain
--   3: lastname.firstname@domain
--   4: firstnamelastname@domain
--
-- Non-alpha characters are stripped from name components
-- (handles umlauts, hyphens, etc.) before building the local part.
CREATE OR REPLACE FUNCTION fake.generate_email(
    p_locale TEXT,
    p_seed   INT,
    p_idx    INT
) RETURNS TEXT AS $$
DECLARE
    v_first  TEXT := lower(regexp_replace(
                        fake._first_name(p_locale, p_seed, p_idx),
                        '[^a-zA-Z]', '', 'g'));
    v_last   TEXT := lower(regexp_replace(
                        fake._last_name(p_locale, p_seed, p_idx),
                        '[^a-zA-Z]', '', 'g'));
    v_fmt    INT  := fake.rng_int(p_seed, p_idx, 55, 0, 4);
    v_domain TEXT := fake.pick('any', 'email_domain', p_seed, p_idx, 56);
    v_suffix TEXT := CASE WHEN fake.rng(p_seed, p_idx, 57) < 0.30
                          THEN fake.rng_int(p_seed, p_idx, 58, 10, 99)::TEXT
                          ELSE '' END;
    v_local  TEXT;
BEGIN
    v_local := CASE v_fmt
        WHEN 0 THEN v_first || '.' || v_last
        WHEN 1 THEN left(v_first, 1) || '.' || v_last
        WHEN 2 THEN v_first || '_' || v_last
        WHEN 3 THEN v_last  || '.' || v_first
        ELSE        v_first || v_last
    END || v_suffix;

    RETURN v_local || '@' || v_domain;
END;
$$ LANGUAGE plpgsql STABLE STRICT;


-- ────────────────────────────────────────────────────────────
-- §11  generate_user
-- ────────────────────────────────────────────────────────────

-- fake.generate_user(locale, seed, index) → jsonb
--
-- Assembles all generators into one complete user record.
-- Every attribute is seeded from (seed, index, field), so they are
-- independently random but collectively reproducible:
-- identical (locale, seed, index) always returns identical JSON.
CREATE OR REPLACE FUNCTION fake.generate_user(
    p_locale TEXT,
    p_seed   INT,
    p_idx    INT
) RETURNS JSONB AS $$
BEGIN
    RETURN jsonb_build_object(
        'name',     fake.generate_name(p_locale, p_seed, p_idx),
        'address',  fake.generate_address(p_locale, p_seed, p_idx),
        'geo',      fake.generate_coordinates(p_seed, p_idx),
        'physical', fake.generate_physical_attributes(p_locale, p_seed, p_idx),
        'phone',    fake.generate_phone(p_locale, p_seed, p_idx),
        'email',    fake.generate_email(p_locale, p_seed, p_idx)
    );
END;
$$ LANGUAGE plpgsql STABLE STRICT;


-- ────────────────────────────────────────────────────────────
-- §12  generate_users  (primary batch entry point)
-- ────────────────────────────────────────────────────────────

-- fake.generate_users(locale, seed, batch_index, batch_size) → TABLE
--
-- Returns batch_size rows. Global row index:
--   idx = batch_index × batch_size + position   (position ∈ [1, batch_size])
--
-- This mapping is the only coupling between batches; every row is
-- independently deterministic once its global idx is known.
--
-- Examples:
--   SELECT * FROM fake.generate_users('en-US', 42, 0, 10);  -- rows 1–10
--   SELECT * FROM fake.generate_users('en-US', 42, 1, 10);  -- rows 11–20
--   SELECT * FROM fake.generate_users('de-DE', 99, 0, 25);  -- different seed
--   SELECT * FROM fake.generate_users('en-US', 1,  0, 100); -- large batch
--
-- Scale: calling with batch_index 0–99999 and batch_size 10
--        generates 1,000,000 unique user records.
CREATE OR REPLACE FUNCTION fake.generate_users(
    p_locale      TEXT,
    p_seed        INT,
    p_batch_index INT,
    p_batch_size  INT DEFAULT 10
) RETURNS TABLE(pos INT, user_data JSONB) AS $$
    SELECT
        i::INT                                                                    AS pos,
        fake.generate_user(p_locale, p_seed, p_batch_index * p_batch_size + i)   AS user_data
    FROM generate_series(1, p_batch_size) AS i;
$$ LANGUAGE SQL STABLE;


-- ────────────────────────────────────────────────────────────
-- §13  benchmark
-- ────────────────────────────────────────────────────────────

-- fake.benchmark(locale, seed, n_batches) → float8  (users/second)
--
-- Generates n_batches × 10 users (discarding results) and measures
-- end-to-end throughput including all SQL stored-procedure overhead.
CREATE OR REPLACE FUNCTION fake.benchmark(
    p_locale    TEXT    DEFAULT 'en-US',
    p_seed      INT     DEFAULT 42,
    p_n_batches INT     DEFAULT 100
) RETURNS FLOAT8 AS $$
DECLARE
    t0    TIMESTAMPTZ := clock_timestamp();
    dummy JSONB;
    i     INT;
    j     INT;
BEGIN
    FOR i IN 0..(p_n_batches - 1) LOOP
        FOR j IN 1..10 LOOP
            dummy := fake.generate_user(p_locale, p_seed, i * 10 + j);
        END LOOP;
    END LOOP;
    RETURN (p_n_batches * 10)::FLOAT8
           / EXTRACT(EPOCH FROM (clock_timestamp() - t0));
END;
$$ LANGUAGE plpgsql VOLATILE;


-- ────────────────────────────────────────────────────────────
-- §14  backward-compatibility alias
-- ────────────────────────────────────────────────────────────

-- fake.gen_batch stays as an alias so existing client code keeps working.
CREATE OR REPLACE FUNCTION fake.gen_batch(
    p_locale TEXT,
    p_seed   INT,
    p_batch  INT
) RETURNS TABLE(pos INT, user_data JSONB) AS $$
    SELECT * FROM fake.generate_users(p_locale, p_seed, p_batch, 10);
$$ LANGUAGE SQL STABLE;
