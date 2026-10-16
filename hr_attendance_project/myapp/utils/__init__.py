def parse_teachers_from_html(*args, **kwargs):
    # Keep the old public import without forcing the optional BeautifulSoup
    # dependency into every unrelated myapp.utils import.
    from myapp.utils.parse_teachers import parse_teachers_from_html as parser

    return parser(*args, **kwargs)
