"""Factory-development test suite (not installed to a target machine).

`__init__.py` is required: bare `python3 -m unittest` from the repository root
discovers via the standard package machinery, and a `tests/` directory without it
is skipped — discovery reports "NO TESTS RAN" rather than failing loudly.
"""
