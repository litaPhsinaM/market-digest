-- Market Digest: profiles, friends, leaderboards, prediction game and paper trading.
-- Run once in Supabase → SQL Editor after 001_accounts_sync.sql. Safe to re-run.
--
-- Fairness: prices are written only by our pipeline (secret key), never by browsers. Orders and predictions are
-- settled by the database against the NEXT price update after they were placed, so nobody can trade on a stale price.

create extension if not exists citext;

-- ============ profiles ============
create table if not exists public.profiles (
  id            uuid primary key references auth.users (id) on delete cascade,
  username      citext unique check (username ~ '^[a-z0-9_]{3,20}$'),
  display_name  text check (char_length(display_name) between 1 and 40),
  streak        int not null default 0,
  best_streak   int not null default 0,
  days_active   int not null default 0,
  stories_read  int not null default 0,
  quizzes       int not null default 0,
  quiz_correct  int not null default 0,
  last_active   date,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
alter table public.profiles enable row level security;
drop policy if exists "profiles are public" on public.profiles;
drop policy if exists "create own profile" on public.profiles;
drop policy if exists "edit own profile" on public.profiles;
create policy "profiles are public" on public.profiles for select to anon, authenticated using (true);
create policy "create own profile"  on public.profiles for insert to authenticated with check ((select auth.uid()) = id);
create policy "edit own profile"    on public.profiles for update to authenticated using ((select auth.uid()) = id) with check ((select auth.uid()) = id);
-- Users may only change their name; stats are computed by the database from their synced progress.
revoke insert, update on public.profiles from authenticated;
grant insert (id, username, display_name) on public.profiles to authenticated;
grant update (username, display_name) on public.profiles to authenticated;

-- Recompute public stats whenever a user's synced progress changes.
create or replace function public.refresh_profile_stats() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  days date[];
  d date;
  run int := 0;
  best int := 0;
  cur int := 0;
  prev date;
  reads int := 0;
  qz int := 0;
  qok int := 0;
begin
  select coalesce(array_agg(x::date order by x::date), '{}') into days
  from jsonb_array_elements_text(coalesce(new.state->'days', '[]'::jsonb)) x
  where x ~ '^\d{4}-\d{2}-\d{2}$';

  foreach d in array days loop
    if prev is not null and d = prev + 1 then run := run + 1; else run := 1; end if;
    best := greatest(best, run);
    prev := d;
  end loop;
  -- current streak only counts if it reaches today or yesterday (UTC, with a day of slack for time zones)
  cur := case when prev is not null and prev >= current_date - 2 then run else 0 end;

  select coalesce(sum(jsonb_array_length(v)), 0) into reads
  from jsonb_each(new.state) e(k, v) where k like 'read:%' and jsonb_typeof(v) = 'array';
  select count(*) into qz from jsonb_each(new.state) e(k, v) where k like 'quiz:%';

  insert into public.profiles (id, streak, best_streak, days_active, stories_read, quizzes, last_active, updated_at)
  values (new.user_id, cur, best, coalesce(array_length(days, 1), 0), reads, qz, prev, now())
  on conflict (id) do update set streak = excluded.streak, best_streak = greatest(profiles.best_streak, excluded.best_streak),
    days_active = excluded.days_active, stories_read = excluded.stories_read, quizzes = excluded.quizzes,
    last_active = excluded.last_active, updated_at = now();
  return new;
end $$;
drop trigger if exists user_state_stats on public.user_state;
create trigger user_state_stats after insert or update on public.user_state for each row execute function public.refresh_profile_stats();

-- Quiz correctness is checked against the real answers (stored by the pipeline), not trusted from the browser.
create table if not exists public.quiz_keys (
  day     date not null,
  q       smallint not null,
  answer  smallint not null,
  primary key (day, q)
);
alter table public.quiz_keys enable row level security;  -- no policies: only the pipeline (secret key) writes; nobody reads

create or replace function public.refresh_quiz_score() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  update public.profiles p set quiz_correct = (
    select count(*) from jsonb_each(new.state) e(k, v)
    cross join lateral jsonb_each_text(v) a(q, pick)
    join public.quiz_keys qk on qk.day = substring(e.k from 6)::date and qk.q = a.q::smallint and qk.answer = a.pick::smallint
    where e.k ~ '^quiz:\d{4}-\d{2}-\d{2}$' and jsonb_typeof(v) = 'object' and a.q ~ '^\d+$' and a.pick ~ '^\d+$'
  ) where p.id = new.user_id;
  return new;
end $$;
drop trigger if exists user_state_quiz on public.user_state;
create trigger user_state_quiz after insert or update on public.user_state for each row execute function public.refresh_quiz_score();

-- ============ friends ============
create table if not exists public.follows (
  follower   uuid not null references public.profiles (id) on delete cascade,
  followee   uuid not null references public.profiles (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (follower, followee),
  check (follower <> followee)
);
alter table public.follows enable row level security;
drop policy if exists "see own follows" on public.follows;
drop policy if exists "follow" on public.follows;
drop policy if exists "unfollow" on public.follows;
create policy "see own follows" on public.follows for select to authenticated using ((select auth.uid()) in (follower, followee));
create policy "follow"   on public.follows for insert to authenticated with check ((select auth.uid()) = follower);
create policy "unfollow" on public.follows for delete to authenticated using ((select auth.uid()) = follower);

-- ============ prices (written only by the pipeline) ============
create table if not exists public.prices (
  symbol  text not null check (symbol ~ '^[A-Z0-9.^=\-]{1,12}$'),
  as_of   timestamptz not null,
  price   numeric(14, 4) not null check (price > 0),
  name    text,
  primary key (symbol, as_of)
);
alter table public.prices enable row level security;
drop policy if exists "prices are public" on public.prices;
create policy "prices are public" on public.prices for select to anon, authenticated using (true);

create or replace view public.latest_prices with (security_invoker = true) as
select distinct on (symbol) symbol, as_of, price, name from public.prices order by symbol, as_of desc;

-- ============ paper trading ============
create table if not exists public.portfolios (
  user_id    uuid primary key references public.profiles (id) on delete cascade,
  cash       numeric(16, 4) not null default 100000 check (cash >= 0),
  created_at timestamptz not null default now()
);
create table if not exists public.orders (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references public.profiles (id) on delete cascade,
  symbol      text not null,
  side        text not null check (side in ('buy', 'sell')),
  qty         numeric(16, 4) not null check (qty > 0 and qty <= 1000000),
  status      text not null default 'pending' check (status in ('pending', 'filled', 'rejected', 'cancelled')),
  placed_at   timestamptz not null default now(),
  filled_at   timestamptz,
  fill_price  numeric(14, 4),
  note        text
);
create index if not exists orders_pending on public.orders (symbol) where status = 'pending';
create index if not exists orders_user on public.orders (user_id, placed_at desc);
alter table public.portfolios enable row level security;
alter table public.orders enable row level security;
drop policy if exists "own portfolio" on public.portfolios;
drop policy if exists "own orders" on public.orders;
create policy "own portfolio" on public.portfolios for select to authenticated using ((select auth.uid()) = user_id);
create policy "own orders"    on public.orders    for select to authenticated using ((select auth.uid()) = user_id);
-- No insert/update policies: orders go through place_order(), fills happen in the price trigger.

create or replace function public.place_order(p_symbol text, p_side text, p_qty numeric) returns public.orders
language plpgsql security definer set search_path = public as $$
declare
  uid uuid := auth.uid();
  o public.orders;
begin
  if uid is null then raise exception 'Sign in to trade'; end if;
  if not exists (select 1 from public.profiles where id = uid and username is not null) then raise exception 'Pick a username first'; end if;
  if p_symbol like '^%' or not exists (select 1 from public.prices where symbol = upper(p_symbol)) then
    raise exception 'That symbol is not tradable here';
  end if;
  if (select count(*) from public.orders where user_id = uid and placed_at > now() - interval '1 day') >= 50 then
    raise exception 'Daily order limit reached';
  end if;
  insert into public.portfolios (user_id) values (uid) on conflict do nothing;
  insert into public.orders (user_id, symbol, side, qty) values (uid, upper(p_symbol), p_side, p_qty) returning * into o;
  return o;
end $$;

create or replace function public.cancel_order(p_id bigint) returns void
language sql security definer set search_path = public as $$
  update public.orders set status = 'cancelled' where id = p_id and user_id = auth.uid() and status = 'pending';
$$;

create or replace view public.positions with (security_invoker = true) as
select user_id, symbol,
       sum(case when side = 'buy' then qty else -qty end) as qty,
       sum(case when side = 'buy' then qty * fill_price else 0 end) / nullif(sum(case when side = 'buy' then qty else 0 end), 0) as avg_buy_price
from public.orders where status = 'filled'
group by user_id, symbol
having sum(case when side = 'buy' then qty else -qty end) > 0;

-- ============ prediction game ============
create table if not exists public.predictions (
  id            bigint generated always as identity primary key,
  user_id       uuid not null references public.profiles (id) on delete cascade,
  symbol        text not null,
  direction     text not null check (direction in ('up', 'down')),
  made_at       timestamptz not null default now(),
  base_price    numeric(14, 4),
  base_as_of    timestamptz,
  status        text not null default 'pending' check (status in ('pending', 'right', 'wrong', 'void')),
  settled_price numeric(14, 4),
  settled_at    timestamptz
);
create unique index if not exists one_open_prediction on public.predictions (user_id, symbol) where status = 'pending';
alter table public.predictions enable row level security;
drop policy if exists "predictions are public" on public.predictions;
create policy "predictions are public" on public.predictions for select to anon, authenticated using (true);

create or replace function public.predict(p_symbol text, p_direction text) returns public.predictions
language plpgsql security definer set search_path = public as $$
declare
  uid uuid := auth.uid();
  lp record;
  pr public.predictions;
begin
  if uid is null then raise exception 'Sign in to play'; end if;
  if not exists (select 1 from public.profiles where id = uid and username is not null) then raise exception 'Pick a username first'; end if;
  select * into lp from public.latest_prices where symbol = upper(p_symbol);
  if lp is null then raise exception 'No price for that symbol'; end if;
  insert into public.predictions (user_id, symbol, direction, base_price, base_as_of)
  values (uid, upper(p_symbol), p_direction, lp.price, lp.as_of) returning * into pr;
  return pr;
exception when unique_violation then
  raise exception 'You already have an open call on %', upper(p_symbol);
end $$;

-- ============ settle orders + predictions when a new price arrives ============
create or replace function public.on_new_price() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  o record;
  held numeric;
  cash_now numeric;
begin
  -- Orders placed before this price update fill at this price.
  for o in select * from public.orders where symbol = new.symbol and status = 'pending' and placed_at < new.as_of order by placed_at for update loop
    select cash into cash_now from public.portfolios where user_id = o.user_id for update;
    if o.side = 'buy' then
      if cash_now >= o.qty * new.price then
        update public.portfolios set cash = cash - o.qty * new.price where user_id = o.user_id;
        update public.orders set status = 'filled', fill_price = new.price, filled_at = new.as_of where id = o.id;
      else
        update public.orders set status = 'rejected', note = 'Not enough cash at fill price', filled_at = new.as_of where id = o.id;
      end if;
    else
      select coalesce(sum(case when side = 'buy' then qty else -qty end), 0) into held
      from public.orders where user_id = o.user_id and symbol = o.symbol and status = 'filled';
      if held >= o.qty then
        update public.portfolios set cash = cash + o.qty * new.price where user_id = o.user_id;
        update public.orders set status = 'filled', fill_price = new.price, filled_at = new.as_of where id = o.id;
      else
        update public.orders set status = 'rejected', note = 'You don''t own that many shares', filled_at = new.as_of where id = o.id;
      end if;
    end if;
  end loop;

  -- Predictions settle at the first price update at least 20 hours after they were made ("by tomorrow's update").
  update public.predictions p
     set status = case when new.price = p.base_price then 'void'
                       when (new.price > p.base_price) = (p.direction = 'up') then 'right' else 'wrong' end,
         settled_price = new.price, settled_at = new.as_of
   where p.symbol = new.symbol and p.status = 'pending' and new.as_of >= p.made_at + interval '20 hours';
  return new;
end $$;
drop trigger if exists prices_settle on public.prices;
create trigger prices_settle after insert on public.prices for each row execute function public.on_new_price();

-- ============ leaderboards (public: usernames + stats only) ============
create or replace view public.leaderboard_learning with (security_invoker = true) as
select id, username, display_name, streak, best_streak, days_active, stories_read, quizzes, quiz_correct, last_active
from public.profiles where username is not null;

create or replace function public.leaderboard_predictions() returns table (id uuid, username citext, display_name text, calls bigint, right_calls bigint, accuracy numeric)
language sql stable security definer set search_path = public as $$
  select pr.id, pr.username, pr.display_name, count(*) as calls, count(*) filter (where p.status = 'right') as right_calls,
         round(100.0 * count(*) filter (where p.status = 'right') / nullif(count(*) filter (where p.status in ('right', 'wrong')), 0), 1) as accuracy
  from public.predictions p join public.profiles pr on pr.id = p.user_id
  where pr.username is not null and p.made_at > now() - interval '30 days'
  group by pr.id, pr.username, pr.display_name;
$$;

create or replace function public.leaderboard_portfolios() returns table (id uuid, username citext, display_name text, value numeric, return_pct numeric, holdings bigint)
language sql stable security definer set search_path = public as $$
  with pos as (
    select o.user_id, o.symbol, sum(case when side = 'buy' then qty else -qty end) as qty
    from public.orders o where status = 'filled' group by 1, 2
  ), val as (
    select pf.user_id, pf.cash + coalesce(sum(pos.qty * lp.price), 0) as value, count(pos.symbol) filter (where pos.qty > 0) as holdings
    from public.portfolios pf
    left join pos on pos.user_id = pf.user_id and pos.qty > 0
    left join public.latest_prices lp on lp.symbol = pos.symbol
    group by pf.user_id, pf.cash
  )
  select pr.id, pr.username, pr.display_name, round(v.value, 2), round((v.value / 100000 - 1) * 100, 2), v.holdings
  from val v join public.profiles pr on pr.id = v.user_id where pr.username is not null;
$$;

grant execute on function public.place_order(text, text, numeric), public.cancel_order(bigint), public.predict(text, text) to authenticated;
grant execute on function public.leaderboard_predictions(), public.leaderboard_portfolios() to anon, authenticated;
revoke execute on function public.place_order(text, text, numeric), public.cancel_order(bigint), public.predict(text, text) from anon;

-- Live updates for fills and settlements.
do $$ begin alter publication supabase_realtime add table public.orders; exception when duplicate_object then null; end $$;
do $$ begin alter publication supabase_realtime add table public.predictions; exception when duplicate_object then null; end $$;
