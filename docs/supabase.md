# Online accounts and sync (Supabase)

GuideWire works fully on one computer with no setup. When a Supabase project is configured, the same app also gets **online accounts** (sign up, log in, forgot password) and **offline-first sync** of tutorials, session progress and preferences between computers.

The code: `app/cloud.py` (the Supabase client), `app/accounts.py` (accounts), `app/sync.py` (sync), `app/ui/main_window.py` (Connection card, background sync). Tests use fakes and a mocked HTTP transport, so no test touches the network.

## Set it up (once, by whoever owns the Supabase project)
1. Create a project at supabase.com. Note the **Project URL** and the **anon (public) key** (Project settings, API).
2. **Never** put the `service_role` key in the app or in `.env`: it bypasses the security rules below.
3. In **Authentication, Providers**, keep Email enabled. In **Authentication, Policies** set the minimum password length to 8 (the app also checks 8).
4. In **Authentication, Email templates, Reset Password**, make the message contain the one-time code, because the desktop app has no web page to open:

   ```
   <h2>Reset your GuideWire password</h2>
   <p>Your code is: <b>{{ .Token }}</b></p>
   ```
5. Decide on **Confirm email**. If it is on, a new learner must click the link in the email before logging in; the app tells them so ("Check your email ...").
6. Open the **SQL editor** and run the script below.
7. Put the two values in `.env` (copy `.env.example`; `.env` is never committed):

   ```
   SUPABASE_URL=https://YOUR-PROJECT.supabase.co
   SUPABASE_ANON_KEY=YOUR-ANON-KEY
   ```
8. Check it end to end: `python scripts/cloud_check.py you@example.com "a password"` (creates the account if it does not exist, pushes one test item, reads it back and deletes it).

Without those two values the app says "Saved on this computer" in the Connection card and nothing leaves the computer.

## The SQL (one table, row level security)
```sql
create table public.sync_item (
  user_id    uuid not null references auth.users (id) on delete cascade,
  kind       text not null check (kind in ('tutorial', 'session', 'pref')),
  id         text not null,
  data       jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null,                    -- when the learner made the change (their clock)
  deleted    boolean not null default false,          -- a delete is a row that says so, so other computers hear about it
  synced_at  timestamptz not null default now(),      -- when the SERVER received it: the cursor other computers fetch by
  primary key (user_id, kind, id)
);

create index sync_item_cursor on public.sync_item (user_id, synced_at);

create function public.stamp_synced_at() returns trigger language plpgsql as $$
begin
  new.synced_at := now();
  return new;
end $$;

create trigger sync_item_stamp before insert or update on public.sync_item
  for each row execute function public.stamp_synced_at();

alter table public.sync_item enable row level security;

create policy "read own rows"   on public.sync_item for select using (auth.uid() = user_id);
create policy "insert own rows" on public.sync_item for insert with check (auth.uid() = user_id);
create policy "update own rows" on public.sync_item for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
-- no delete policy on purpose: rows are never removed by the app, they are marked `deleted`

-- logged-in learners may use the table (newer Supabase projects do not grant this by default; without it the app gets "permission denied")
grant usage on schema public to authenticated;
grant select, insert, update on public.sync_item to authenticated;
```
Every request carries the learner's own token, so these policies are what keep one learner from reading or writing another's rows. The app never sends a user id it trusts: the policy compares it with the token.

## What is stored online, and what is not
| Kept online | Never sent |
|---|---|
| Account email and display name (Supabase Auth), a hash of the password (Supabase's, not ours) | The password in plain text (the app keeps only a bcrypt hash locally; Supabase hashes its own) |
| Tutorials (title, application, source link, every step) | Anything from the screen: screen guidance reads the application window on the computer only |
| Sessions: state, current step, the status of every step | The database file itself |
| Preferences (theme, switches) | |

The learner can switch syncing off (Privacy screen); then nothing is sent. `app/ui/onboarding.py` holds the wording the learner sees; keep it true when this changes.

## How it behaves
- **Offline first.** The app only ever reads and writes the local database. Each change leaves a note in the local `outbox` table; a sync sends the notes and fetches news. With no connection the notes wait, and the Connection card says "Offline ... will sync when you are back online".
- **When it syncs:** right after login, every minute, when a session is left, when steps are saved, and from the "Sync now" button.
- **Conflicts.** The newest `updated_at` wins; a delete wins over an older edit. Tutorials and sessions have random ids (`sync_id`), so two computers never clash on a number.
- **Logging in offline.** After a first online login the account is also kept on the computer (email, name, bcrypt hash). With no connection the learner can still log in with it; syncing starts at the next online login.
- **Password reset.** The learner types their email, gets a 6-digit code by email, types it with a new password. The online account and the local copy both change.

## Not done yet (open items)
- Deleting an online account from inside the app (the Privacy screen says so). Today it is done in the Supabase dashboard.
- Remembering the online sign-in between runs (the learner logs in each time the app starts; their work is already on the computer).
- Merging two edits of the same tutorial step by step: the newer whole tutorial wins.
