"""Date-based preview releases, with ordering for earlier milestone builds."""
from datetime import date
import re


def version_key(value):
    if re.fullmatch(r'M[1-9][0-9]?', value):
        return (0, int(value[1:]))
    if not re.fullmatch(r'[0-9]{2}\.[0-9]{2}\.[0-9]{2}', value):
        raise ValueError('Use a date version in YY.MM.DD format or a legacy milestone identifier.')
    year, month, day = map(int, value.split('.'))
    date(2000 + year, month, day)  # Refuse invalid calendar dates.
    return (1, year, month, day)
