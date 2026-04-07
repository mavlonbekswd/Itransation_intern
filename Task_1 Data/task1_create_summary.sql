use books_db

Select TOP 5 *
From dbo.yearly_summary
order by average_price_usd desc;



Select TOP 1
    genre,
    COUNT(*) AS total_books
From dbo.books_raw
Group BY genre
Order BY total_books desc;

Select TOP 5
    author,
    COUNT(*) AS books_written
From dbo.books_raw
Group BY author
order BY books_written DESC;

select
    publication_year,
    book_count,
    book_count - LAG(book_count) over (ORDER BY publication_year) AS growth
from dbo.yearly_summary
ORDER BY publication_year;

SELECT TOP 1
    publication_year,
    book_count,
    book_count - LAG(book_count) OVER (ORDER BY publication_year) AS growth
FROM dbo.yearly_summary
ORDER BY growth DESC;