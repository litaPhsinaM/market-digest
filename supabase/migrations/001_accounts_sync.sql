-- Market Digest: account sync + anonymous usage events.
-- Run once in Supabase → SQL Editor. Safe to re-run.

-- One row per signed-in user holding their progress (stories read, quiz answers, streak days, watchlist, theme).
-- The browser merges local + server copies, so a single JSON document keeps sync simple and conflict-free.
create table if not exists public.user_state (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  state      jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  constraint state_size check (pg_column_size(state) < 200000)
);

alter table public.user_state enable row level security;

drop policy if exists "own state: read" on public.user_state;
drop policy if exists "own state: insert" on public.user_state;
drop policy if exists "own state: update" on public.user_state;
drop policy if exists "own state: delete" on public.user_state;
create policy "own state: read"   on public.user_state for select to authenticated using ((select auth.uid()) = user_id);
create policy "own state: insert" on public.user_state for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "own state: update" on public.user_state for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "own state: delete" on public.user_state for delete to authenticated using ((select auth.uid()) = user_id);

-- Live sync between a user's open devices.
do $$ begin
  alter publication supabase_realtime add table public.user_state;
exception when duplicate_object then null; end $$;

-- Anonymous usage events ("quiz_done", "listen", "stories_open", ...). Write-only from the site;
-- nobody can read them with the public key — view them in the dashboard.
create table if not exists public.events (
  id         bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  event      text not null check (event ~ '^[a-z_]{2,40}$'),
  day        date,
  device     text check (char_length(device) <= 40),
  platform   text check (platform in ('web', 'pwa', 'android', 'ios')),
  signed_in  boolean not null default false,
  props      jsonb not null default '{}'::jsonb check (pg_column_size(props) < 2000)
);

alter table public.events enable row level security;
drop policy if exists "anyone can log an event" on public.events;
create policy "anyone can log an event" on public.events for insert to anon, authenticated with check (true);

create index if not exists events_created_at on public.events (created_at desc);
create index if not exists events_event_day on public.events (event, day);

-- Handy dashboard view: daily active devices and feature use.
create or replace view public.daily_usage with (security_invoker = true) as
select date_trunc('day', created_at)::date as day,
       count(distinct device)                                as active_devices,
       count(*) filter (where event = 'open')                as opens,
       count(*) filter (where event = 'story_read')          as stories_read,
       count(*) filter (where event = 'quiz_done')           as quizzes_done,
       count(*) filter (where event = 'listen')              as listens,
       count(*) filter (where event = 'stories_open')        as stories_opened,
       count(distinct device) filter (where signed_in)       as signed_in_devices
from public.events
group by 1
order by 1 desc;
