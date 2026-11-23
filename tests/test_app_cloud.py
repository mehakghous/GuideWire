"""The online accounts: the Supabase client (against a mocked HTTP transport) and how Accounts uses it. No network is ever touched."""
import json

import httpx
import pytest

from app.accounts import BAD_LOGIN, AccountError, AccountNotice, Accounts
from app.cloud import CloudAuthError, CloudSession, CloudUnavailable, NullCloud, SupabaseCloud
from app.db import Database

URL, KEY = "https://proj.supabase.co", "anon-key-123"


def make(handler):
    return SupabaseCloud(URL, KEY, client=httpx.Client(transport=httpx.MockTransport(handler)))


def ok_session(email="a@x.com", name="Ann"):
    return {"access_token": "AT", "refresh_token": "RT", "user": {"id": "uuid-1", "email": email, "user_metadata": {"display_name": name}}}


# ---------------------------------------------------------------- the Supabase client
def test_sign_in_sends_the_password_grant_with_the_anon_key_and_returns_a_session():
    seen = {}

    def handler(req):
        seen.update(url=str(req.url), headers=dict(req.headers), body=json.loads(req.content))
        return httpx.Response(200, json=ok_session())
    s = make(handler).sign_in("a@x.com", "pw-secret-1")
    assert seen["url"] == f"{URL}/auth/v1/token?grant_type=password" and seen["headers"]["apikey"] == KEY and seen["body"] == {"email": "a@x.com", "password": "pw-secret-1"}
    assert s == CloudSession("uuid-1", "a@x.com", "Ann", "AT", "RT")


def test_wrong_password_unconfirmed_email_and_rate_limit_have_clear_safe_messages():
    def with_status(code, body):
        return make(lambda req: httpx.Response(code, json=body))
    with pytest.raises(CloudAuthError, match="Incorrect email or password"):
        with_status(400, {"error_description": "Invalid login credentials"}).sign_in("a@x.com", "pw-secret-1")
    with pytest.raises(CloudAuthError, match="Confirm your email"):
        with_status(400, {"error_description": "Email not confirmed"}).sign_in("a@x.com", "pw-secret-1")
    with pytest.raises(CloudAuthError, match="Too many"):
        with_status(429, {}).sign_in("a@x.com", "pw-secret-1")


def test_a_dead_connection_or_a_server_error_is_unavailable_and_never_leaks_the_password():
    def boom(req):
        raise httpx.ConnectError("no route to " + req.url.host + " pw-secret-1")
    with pytest.raises(CloudUnavailable) as e:
        make(boom).sign_in("a@x.com", "pw-secret-1")
    assert "pw-secret-1" not in str(e.value)
    with pytest.raises(CloudUnavailable):
        make(lambda req: httpx.Response(503)).sign_in("a@x.com", "pw-secret-1")


def test_sign_up_returns_a_session_or_none_when_the_email_must_be_confirmed_and_reports_duplicates():
    assert make(lambda req: httpx.Response(200, json=ok_session())).sign_up("a@x.com", "pw-secret-1", "Ann").user_id == "uuid-1"
    assert make(lambda req: httpx.Response(200, json={"id": "uuid-1", "email": "a@x.com"})).sign_up("a@x.com", "pw-secret-1", "Ann") is None
    with pytest.raises(CloudAuthError, match="already exists"):
        make(lambda req: httpx.Response(422, json={"msg": "User already registered"})).sign_up("a@x.com", "pw-secret-1", "Ann")


def test_password_reset_asks_for_a_code_then_verifies_it_and_sets_the_new_password():
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path, json.loads(req.content) if req.content else None, req.headers.get("authorization")))
        if req.url.path == "/auth/v1/verify":
            return httpx.Response(200, json=ok_session())
        return httpx.Response(200, json={})
    c = make(handler)
    c.request_reset("a@x.com")
    s = c.finish_reset("a@x.com", " 123456 ", "new-password-9")
    assert calls[0][:3] == ("POST", "/auth/v1/recover", {"email": "a@x.com"})
    assert calls[1][:3] == ("POST", "/auth/v1/verify", {"type": "recovery", "email": "a@x.com", "token": "123456"})
    assert calls[2][:3] == ("PUT", "/auth/v1/user", {"password": "new-password-9"}) and calls[2][3] == "Bearer AT" and s.access_token == "AT"
    with pytest.raises(CloudAuthError, match="wrong or has expired"):
        make(lambda req: httpx.Response(401, json={"msg": "Token has expired or is invalid"})).finish_reset("a@x.com", "000000", "new-password-9")


def test_push_upserts_rows_for_the_token_owner_and_fetch_uses_the_server_cursor():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, dict(req.url.params), dict(req.headers), json.loads(req.content) if req.content else None))
        return httpx.Response(200, json=[{"kind": "tutorial", "id": "t1", "data": {}, "updated_at": "x", "deleted": False, "synced_at": "2026-11-23T10:00:01+00:00"}])
    c = make(handler)
    s = CloudSession("uuid-1", "a@x.com", "Ann", "AT", "RT")
    c.push_items(s, [{"kind": "tutorial", "id": "t1", "data": {"title": "T"}, "updated_at": "2026-11-23T10:00:00+00:00", "deleted": False}])
    got = c.fetch_items(s, "2026-11-23T09:00:00+00:00")
    method, path, params, headers, body = seen[0]
    assert (method, path) == ("POST", "/rest/v1/sync_item") and params["on_conflict"] == "user_id,kind,id" and "merge-duplicates" in headers["prefer"]
    assert body[0]["user_id"] == "uuid-1" and headers["authorization"] == "Bearer AT"
    assert seen[1][2]["synced_at"] == "gt.2026-11-23T09:00:00+00:00" and seen[1][2]["order"] == "synced_at.asc" and got[0]["id"] == "t1"
    c.push_items(s, [])
    assert len(seen) == 2                                                          # nothing to send: no request


def test_an_expired_token_on_the_data_table_asks_to_log_in_again():
    c = make(lambda req: httpx.Response(401, json={"message": "JWT expired"}))
    s = CloudSession("uuid-1", "a@x.com", "Ann", "AT", "RT")
    with pytest.raises(CloudAuthError):
        c.fetch_items(s, None)


def test_from_env_is_the_real_service_only_when_both_values_are_set(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    assert isinstance(SupabaseCloud.from_env(), NullCloud)
    monkeypatch.setenv("SUPABASE_URL", URL + "/")
    assert isinstance(SupabaseCloud.from_env(), NullCloud)
    monkeypatch.setenv("SUPABASE_ANON_KEY", KEY)
    real = SupabaseCloud.from_env()
    assert isinstance(real, SupabaseCloud) and real.url == URL and real.configured


# ---------------------------------------------------------------- Accounts with the online service
class FakeAuth:
    configured = True

    def __init__(self):
        self.users = {}                                  # email -> [password, uuid]
        self.online = True
        self.confirm_email = False
        self.codes = {}
        self.changed = []

    def _need_online(self):
        if not self.online:
            raise CloudUnavailable("offline")

    def sign_up(self, email, password, display_name):
        self._need_online()
        if email in self.users:
            raise CloudAuthError("An account with this email already exists.")
        self.users[email] = [password, f"uuid-{len(self.users) + 1}"]
        return None if self.confirm_email else CloudSession(self.users[email][1], email, display_name, "AT", "RT")

    def sign_in(self, email, password):
        self._need_online()
        if email not in self.users or self.users[email][0] != password:
            raise CloudAuthError("Incorrect email or password.")
        return CloudSession(self.users[email][1], email, "Ann", "AT", "RT")

    def request_reset(self, email):
        self._need_online()
        self.codes[email] = "246810"

    def finish_reset(self, email, code, new_password):
        self._need_online()
        if self.codes.get(email) != code.strip():
            raise CloudAuthError("That code is wrong or has expired. Ask for a new one.")
        self.users[email][0] = new_password
        return CloudSession(self.users[email][1], email, "Ann", "AT", "RT")

    def change_password(self, session, new_password):
        self._need_online()
        self.users[session.email][0] = new_password
        self.changed.append(new_password)


@pytest.fixture
def acc():
    db = Database(":memory:")
    cloud = FakeAuth()
    yield Accounts(db, cloud), cloud, db
    db.close()


def test_sign_up_creates_the_online_account_and_a_local_copy_and_keeps_the_session(acc):
    a, cloud, db = acc
    u = a.register("a@x.com", "correct horse", "Ann")
    assert u.email == "a@x.com" and "a@x.com" in cloud.users and a.cloud_session.access_token == "AT"
    assert db.get_user(u.id)["remote_id"] == "uuid-1"


def test_sign_up_waits_for_the_confirmation_email_when_the_project_requires_it(acc):
    a, cloud, db = acc
    cloud.confirm_email = True
    with pytest.raises(AccountNotice, match="Check your email"):
        a.register("a@x.com", "correct horse", "Ann")
    assert db.get_user_by_email("a@x.com") is None                    # nothing local until the account is confirmed and logged into


def test_sign_up_needs_a_connection_and_local_rules_still_apply_first(acc):
    a, cloud, _ = acc
    with pytest.raises(AccountError, match="at least 8"):
        a.register("a@x.com", "short", "Ann")
    cloud.online = False
    with pytest.raises(AccountError, match="needs an internet connection"):
        a.register("a@x.com", "correct horse", "Ann")


def test_login_goes_online_then_works_offline_with_the_local_copy(acc):
    a, cloud, db = acc
    a.register("a@x.com", "correct horse", "Ann")
    a.sign_out()
    assert a.login("a@x.com", "correct horse").email == "a@x.com" and not a.offline_login and a.cloud_session is not None
    a.sign_out()
    cloud.online = False
    u = a.login("a@x.com", "correct horse")
    assert u.email == "a@x.com" and a.offline_login and a.cloud_session is None
    with pytest.raises(AccountError, match=BAD_LOGIN):
        a.login("a@x.com", "wrong password")                           # offline: the local copy still checks the password
    with pytest.raises(AccountError, match="not on this computer yet"):
        a.login("new@x.com", "correct horse")


def test_a_wrong_online_password_is_the_usual_message_even_if_a_local_copy_exists(acc):
    a, cloud, _ = acc
    a.register("a@x.com", "correct horse", "Ann")
    with pytest.raises(AccountError, match=BAD_LOGIN):
        a.login("a@x.com", "wrong password")


def test_a_password_changed_elsewhere_refreshes_the_local_copy_at_the_next_online_login(acc):
    a, cloud, db = acc
    a.register("a@x.com", "correct horse", "Ann")
    cloud.users["a@x.com"][0] = "changed on the phone"
    a.login("a@x.com", "changed on the phone")
    cloud.online = False
    assert a.login("a@x.com", "changed on the phone").email == "a@x.com"
    with pytest.raises(AccountError):
        a.login("a@x.com", "correct horse")


def test_forgotten_password_flow_sets_the_new_password_online_and_here_and_signs_in(acc):
    a, cloud, _ = acc
    a.register("a@x.com", "correct horse", "Ann")
    a.sign_out()
    a.request_password_reset("a@x.com")
    with pytest.raises(AccountError, match="wrong or has expired"):
        a.finish_password_reset("a@x.com", "000000", "brand new password")
    with pytest.raises(AccountError, match="at least 8"):
        a.finish_password_reset("a@x.com", "246810", "short")
    with pytest.raises(AccountError, match="Enter the code"):
        a.finish_password_reset("a@x.com", "  ", "brand new password")
    u = a.finish_password_reset("a@x.com", "246810", "brand new password")
    assert u.email == "a@x.com" and cloud.users["a@x.com"][0] == "brand new password" and a.cloud_session is not None
    cloud.online = False
    a.sign_out()
    assert a.login("a@x.com", "brand new password").email == "a@x.com"      # the local copy has the new password too


def test_reset_needs_the_service_and_a_connection_and_a_valid_email():
    local = Accounts(Database(":memory:"))
    with pytest.raises(AccountError, match="not set up"):
        local.request_password_reset("a@x.com")
    with pytest.raises(AccountError, match="not set up"):
        local.finish_password_reset("a@x.com", "123456", "brand new password")
    db = Database(":memory:")
    cloud = FakeAuth()
    a = Accounts(db, cloud)
    with pytest.raises(AccountError, match="Enter the email"):
        a.request_password_reset("nonsense")
    cloud.online = False
    with pytest.raises(AccountError, match="needs an internet connection"):
        a.request_password_reset("a@x.com")


def test_changing_the_password_updates_the_online_account_too_and_needs_a_connection(acc):
    a, cloud, _ = acc
    u = a.register("a@x.com", "correct horse", "Ann")
    a.change_password(u.id, "correct horse", "another password")
    assert cloud.changed == ["another password"]
    cloud.online = False
    with pytest.raises(AccountError, match="needs an internet connection"):
        a.change_password(u.id, "another password", "third password")
    a.sign_out()
    cloud.online = True
    with pytest.raises(AccountError, match="Log in while online"):
        a.change_password(u.id, "another password", "third password")      # no online session after a sign out


def test_without_the_service_everything_is_local_as_before():
    a = Accounts(Database(":memory:"))
    assert not a.online_enabled
    u = a.register("a@x.com", "correct horse", "Ann")
    assert a.login("a@x.com", "correct horse").id == u.id and a.cloud_session is None and not a.offline_login
    a.change_password(u.id, "correct horse", "another password")


def test_a_publishable_key_goes_in_apikey_alone_and_an_anon_jwt_also_as_bearer_before_login():
    seen = []

    def handler(req):
        seen.append(dict(req.headers))
        return httpx.Response(200, json=ok_session())
    new = SupabaseCloud(URL, "sb_publishable_abc", client=httpx.Client(transport=httpx.MockTransport(handler)))
    new.sign_in("a@x.com", "pw-secret-1")
    assert seen[0]["apikey"] == "sb_publishable_abc" and "authorization" not in seen[0]
    old = SupabaseCloud(URL, "eyJhbGciOi.payload.sig", client=httpx.Client(transport=httpx.MockTransport(handler)))
    old.sign_in("a@x.com", "pw-secret-1")
    assert seen[1]["authorization"] == "Bearer eyJhbGciOi.payload.sig"
    new.fetch_items(CloudSession("uuid-1", "a@x.com", "Ann", "AT", "RT"), None)
    assert seen[2]["authorization"] == "Bearer AT" and seen[2]["apikey"] == "sb_publishable_abc"      # once logged in, always the learner's token
