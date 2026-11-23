"""Live check of the Supabase setup (docs/supabase.md): sign up or log in, push one test row, read it back, mark it deleted.

    python scripts/cloud_check.py you@example.com "a password"

Needs SUPABASE_URL and SUPABASE_ANON_KEY in the environment or .env. Creates the account if it does not exist (if the project requires email confirmation,
confirm it and run again). Leaves only one row marked deleted in your sync_item table. Never prints the password or a token.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cloud import CloudAuthError, CloudError, CloudUnavailable, SupabaseCloud  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    email, password = sys.argv[1], sys.argv[2]
    cloud = SupabaseCloud.from_env()
    if not cloud.configured:
        print("SUPABASE_URL and SUPABASE_ANON_KEY are not set (see docs/supabase.md).")
        return 2
    try:
        try:
            session = cloud.sign_in(email, password)
            print("1. logged in to the existing account")
        except CloudAuthError:
            session = cloud.sign_up(email, password, "Check")
            if session is None:
                print("1. account created; the project wants the email confirmed first. Confirm it, then run this again.")
                return 0
            print("1. account created and logged in")
        item = {"kind": "pref", "id": "cloud-check", "data": {"hello": "world"}, "updated_at": "2026-01-01T00:00:00+00:00", "deleted": False}
        cloud.push_items(session, [item])
        print("2. pushed one row")
        rows = [r for r in cloud.fetch_items(session, None) if r["id"] == "cloud-check"]
        assert rows and rows[0]["data"] == {"hello": "world"} and rows[0]["synced_at"], "the row did not come back"
        print("3. read it back (server time stamp:", rows[0]["synced_at"] + ")")
        cloud.push_items(session, [{**item, "deleted": True, "updated_at": "2026-01-02T00:00:00+00:00"}])
        print("4. marked it deleted. Row level security works if another account cannot see it (try with a second account).")
        return 0
    except CloudUnavailable as e:
        print("No connection:", e)
        return 1
    except CloudAuthError as e:
        print("The service said no:", e)
        return 1
    except CloudError as e:
        print("Problem:", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
