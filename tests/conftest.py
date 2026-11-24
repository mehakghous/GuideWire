"""Shared test setup."""
import pytest


@pytest.fixture(autouse=True, scope="session")
def fast_password_hashing():
    """Every UI test registers an account. bcrypt is slow on purpose (rounds=12, about a quarter of a second per hash); the tests only need a valid hash, so they use the cheapest cost."""
    try:
        import bcrypt

        from app import accounts
    except Exception:                                   # bcrypt or the app is not installed (the lean CI install): nothing to speed up
        yield
        return
    original = accounts._hash
    accounts._hash = lambda password: bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=4))
    yield
    accounts._hash = original
