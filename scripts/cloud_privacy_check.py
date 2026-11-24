"""Privacy check of the Supabase setup (docs/supabase.md): can one account see or change another account's data?

    python scripts/cloud_privacy_check.py a@mail.com "password A" b@mail.com "password B"

Uses two accounts (created if they do not exist; with "Confirm email" on, confirm them first). It then:
  1. saves a marker row as account A and checks A can read it back;
  2. checks account B cannot see A's row;
  3. checks B cannot write a row that claims to belong to A (a forged user id);
  4. checks B cannot change A's row;
  5. checks that someone with only the public key (not logged in) sees nothing.
Finally A's marker row is marked deleted. Prints PASS or FAIL for each check and never prints a password or a token.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cloud import CloudAuthError, CloudError, CloudSession, CloudUnavailable, SupabaseCloud  # noqa: E402

RESULTS: list[bool] = []


def check(ok: bool, text: str) -> None:
    RESULTS.append(ok)
    print(("PASS  " if ok else "FAIL  ") + text)


def login(cloud: SupabaseCloud, email: str, password: str) -> CloudSession:
    try:
        return cloud.sign_in(email, password)
    except CloudAuthError:
        session = cloud.sign_up(email, password, "Privacy check")
        if session is None:
            raise SystemExit(f"{email}: the account was created but needs its email confirmed first. Confirm it, then run this again.")
        return session


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    cloud = SupabaseCloud.from_env()
    if not cloud.configured:
        print("SUPABASE_URL and SUPABASE_ANON_KEY are not set (see docs/supabase.md).")
        return 2
    try:
        a = login(cloud, sys.argv[1], sys.argv[2])
        b = login(cloud, sys.argv[3], sys.argv[4])
        if a.user_id == b.user_id:
            print("Use two DIFFERENT accounts.")
            return 2
        marker = f"privacy-check-{uuid.uuid4().hex[:8]}"
        row = {"kind": "pref", "id": marker, "data": {"secret": "only for A"}, "updated_at": "2026-01-01T00:00:00+00:00", "deleted": False}

        cloud.push_items(a, [row])
        check(any(r["id"] == marker for r in cloud.fetch_items(a, None)), "A can read A's own row")

        check(not any(r["id"] == marker for r in cloud.fetch_items(b, None)), "B cannot see A's row")

        # B tries to write a row that says it belongs to A (the app never does this; an attacker would)
        forged = [{"user_id": a.user_id, "kind": "pref", "id": marker + "-forged", "data": {}, "updated_at": "2026-01-02T00:00:00+00:00", "deleted": False}]
        r = cloud._send("POST", "/rest/v1/sync_item", session=b, json=forged, params={"on_conflict": "user_id,kind,id"}, extra={"Prefer": "resolution=merge-duplicates,return=minimal"})
        check(r.status_code >= 400, f"B cannot write a row claiming to be A's (answer {r.status_code})")

        # B tries to overwrite A's real row
        r = cloud._send("PATCH", "/rest/v1/sync_item", session=b, json={"data": {"secret": "changed by B"}}, params={"user_id": f"eq.{a.user_id}", "id": f"eq.{marker}"},
                        extra={"Prefer": "return=representation"})
        changed_by_b = r.status_code < 300 and bool(r.json())
        still_a = [x for x in cloud.fetch_items(a, None) if x["id"] == marker]
        check(not changed_by_b and bool(still_a) and still_a[0]["data"] == {"secret": "only for A"}, "B cannot change A's row")

        # not logged in: only the public key
        r = cloud._send("GET", "/rest/v1/sync_item", params={"select": "id", "limit": "5"})
        seen = r.json() if r.status_code < 300 else []
        check(r.status_code >= 400 or seen == [], f"someone not logged in sees nothing (answer {r.status_code}, {len(seen)} rows)")

        cloud.push_items(a, [{**row, "deleted": True, "updated_at": "2026-01-03T00:00:00+00:00"}])
    except CloudUnavailable as e:
        print("No connection:", e)
        return 1
    except CloudError as e:
        print("Problem:", e)
        return 1
    print()
    print("ALL PASSED: each account only sees its own data." if all(RESULTS) else "SOMETHING FAILED: do not use this setup for real users until it is fixed (re-run the SQL in docs/supabase.md).")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
