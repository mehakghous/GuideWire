import pytest

from app.accounts import BAD_LOGIN, AccountError, Accounts
from app.db import Database


@pytest.fixture
def acc():
    d = Database(":memory:")
    yield Accounts(d)
    d.close()


def test_register_then_login(acc):
    u = acc.register("Mehak@x.com", "correct horse", "Mehak")
    assert acc.login("mehak@x.com", "correct horse").id == u.id


def test_password_is_hashed_not_stored(acc):
    acc.register("a@x.com", "correct horse")
    stored = bytes(acc.db.get_user_by_email("a@x.com")["password_hash"])
    assert b"correct horse" not in stored and stored.startswith(b"$2")


def test_wrong_password_is_rejected(acc):
    acc.register("a@x.com", "correct horse")
    with pytest.raises(AccountError, match="Incorrect email or password"):
        acc.login("a@x.com", "wrong password")


def test_unknown_email_gives_the_same_message(acc):
    with pytest.raises(AccountError) as e:
        acc.login("nobody@x.com", "whatever1")
    assert str(e.value) == BAD_LOGIN


def test_duplicate_email_is_rejected_case_insensitively(acc):
    acc.register("a@x.com", "correct horse")
    with pytest.raises(AccountError, match="already exists"):
        acc.register("A@X.com", "another pass1")


@pytest.mark.parametrize("email", ["", "no-at.com", "a@b", "a b@x.com"])
def test_bad_email_is_rejected(acc, email):
    with pytest.raises(AccountError, match="valid email"):
        acc.register(email, "correct horse")


def test_password_rules(acc):
    with pytest.raises(AccountError, match="at least"):
        acc.register("a@x.com", "short")
    with pytest.raises(AccountError, match="at most"):
        acc.register("a@x.com", "x" * 73)


def test_change_password(acc):
    u = acc.register("a@x.com", "correct horse")
    with pytest.raises(AccountError, match="Current password"):
        acc.change_password(u.id, "wrong", "new password1")
    acc.change_password(u.id, "correct horse", "new password1")
    with pytest.raises(AccountError):
        acc.login("a@x.com", "correct horse")
    assert acc.login("a@x.com", "new password1").id == u.id


def test_profile_and_preferences(acc):
    u = acc.register("a@x.com", "correct horse")
    assert acc.update_profile(u.id, "  Ayesha ").display_name == "Ayesha"
    assert acc.set_preferences(u.id, theme="dark") == {"theme": "dark"}
    assert acc.set_preferences(u.id, overlay=True) == {"theme": "dark", "overlay": True}
    assert acc.preferences(u.id) == {"theme": "dark", "overlay": True}
