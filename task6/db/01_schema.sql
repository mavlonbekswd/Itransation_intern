-- ============================================================
-- Fake Data Generator – Schema
-- ============================================================
CREATE SCHEMA IF NOT EXISTS fake;

-- Universal lookup table.
-- locale: 'en-US' | 'de-DE' | 'any'
-- category: 'first_male' | 'first_female' | 'last' | 'middle_male'
--           | 'middle_female' | 'title_male' | 'title_female'
--           | 'street_name' | 'street_suffix' | 'city' | 'state'
--           | 'eye_color' | 'email_domain'
CREATE TABLE IF NOT EXISTS fake.lookup (
    id       SERIAL       PRIMARY KEY,
    locale   VARCHAR(10)  NOT NULL,
    category VARCHAR(50)  NOT NULL,
    value    TEXT         NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lookup_lc    ON fake.lookup (locale, category);
-- Covering index enables efficient OFFSET-based row access in fake.pick()
CREATE INDEX IF NOT EXISTS idx_lookup_lc_id ON fake.lookup (locale, category, id);

-- City rows also carry extra data (state/region, zip pattern).
-- Stored as JSON inside the value column for city rows,
-- plain text for everything else.
-- city value format: {"city":"Berlin","state":"Berlin","zip":"#####"}
