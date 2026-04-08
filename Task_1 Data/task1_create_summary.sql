use books_db

IF OBJECT_ID('dbo.yearly_summary', 'U') IS NOT NULL
    DROP TABLE dbo.yearly_summary;
GO

SELECT
    year AS publication_year,
    COUNT(*) AS book_count,
    CAST(
        ROUND(
            AVG(
                CASE
                    WHEN currency_symbol = '$' THEN price_numeric
                    WHEN currency_symbol = N'€' THEN price_numeric * 1.2
                END
            ),
            2
        ) AS DECIMAL(10,2)
    ) AS average_price_usd
INTO dbo.yearly_summary
FROM dbo.books_raw
GROUP BY year;
GO

SELECT *
FROM dbo.yearly_summary
ORDER BY publication_year;
GO

SELECT COUNT(*) AS raw_row_count FROM dbo.books_raw;

SELECT COUNT(*) AS summary_row_count FROM dbo.yearly_summary;

SELECT COUNT(*) AS summary_row_count FROM dbo.yearly_summary;





