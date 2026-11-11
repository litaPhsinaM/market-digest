-- Quant games: server-verified streaks, daily portfolio snapshots (risk-adjusted skill + max drawdown), "did you beat
-- the market?" (alpha vs a shadow S&P 500 portfolio), and the daily 90% range game (interval scoring). Safe to re-run.

-- ---------------------------------------------------------------------------------------------------------------
-- 1. Cheat-proof streaks: active days are recorded by the server when progress syncs, not taken from the phone.
-- ---------------------------------------------------------------------------------------------------------------
create table if not exists public.activity_days (
  user_id uuid not null references public.profiles (id) on delete cascade,
  day     date not null,
  primary key (user_id, day)
);
alter table public.activity_days enable row level security;
drop policy if exists "own activity" on public.activity_days;
create policy "own activity" on public.activity_days for select to authenticated using ((select auth.uid()) = user_id);

-- One-time seed from what was synced so far (only 2 test users existed when this shipped).
insert into public.activity_days (user_id, day)
select s.user_id, x::date from public.user_state s, jsonb_array_elements_text(coalesce(s.state->'days', '[]'::jsonb)) x
where x ~ '^\d{4}-\d{2}-\d{2}$' and x::date <= current_date and exists (select 1 from public.profiles p where p.id = s.user_id)
on conflict do nothing;

create or replace function public.refresh_profile_stats() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  today date := (now() at time zone 'America/New_York')::date;
  d date; prev date; run int := 0; best int := 0; cur int := 0; n int := 0;
  reads int := 0; qz int := 0;
begin
  insert into public.profiles (id) values (new.user_id) on conflict do nothing;
  insert into public.activity_days (user_id, day) values (new.user_id, today) on conflict do nothing;
  for d in select day from public.activity_days where user_id = new.user_id order by day loop
    if prev is not null and d = prev + 1 then run := run + 1; else run := 1; end if;
    best := greatest(best, run); prev := d; n := n + 1;
  end loop;
  cur := case when prev >= today - 1 then run else 0 end;

  select coalesce(sum(jsonb_array_length(v)), 0) into reads
  from jsonb_each(new.state) e(k, v) where k like 'read:%' and jsonb_typeof(v) = 'array';
  select count(*) into qz from jsonb_each(new.state) e(k, v) where k like 'quiz:%';

  update public.profiles set streak = cur, best_streak = greatest(best_streak, best), days_active = n,
    stories_read = reads, quizzes = qz, last_active = prev, updated_at = now()
  where id = new.user_id;
  return new;
end $$;

-- ---------------------------------------------------------------------------------------------------------------
-- Helpers: prices at a moment.
-- ---------------------------------------------------------------------------------------------------------------
create or replace function public.price_at(p_symbol text, p_ts timestamptz) returns numeric
language sql stable security definer set search_path = public as $$
  select coalesce(
    (select price from public.prices where symbol = p_symbol and as_of <= p_ts order by as_of desc limit 1),
    (select price from public.prices where symbol = p_symbol order by as_of limit 1))
$$;

create or replace function public.portfolio_value(p_user uuid) returns numeric
language sql stable security definer set search_path = public as $$
  with pos as (
    select symbol, sum(case when side = 'buy' then qty else -qty end) q
    from public.orders where user_id = p_user and status = 'filled' group by 1
  )
  select pf.cash + coalesce((select sum(pos.q * lp.price) from pos join public.latest_prices lp using (symbol) where pos.q > 0), 0)
  from public.portfolios pf where pf.user_id = p_user
$$;

-- ---------------------------------------------------------------------------------------------------------------
-- 2. Did you beat the market? Every filled trade is mirrored, dollar for dollar at the same moment, into SPY
--    (an S&P 500 fund). Alpha = your trading profit minus what the same money would have made in the index.
-- ---------------------------------------------------------------------------------------------------------------
create or replace function public.market_compare(p_user uuid) returns table (invested numeric, my_pnl numeric, spy_pnl numeric, alpha_pct numeric, trades bigint)
language sql stable security definer set search_path = public as $$
  with o as (
    select side, qty * fill_price as dollars, public.price_at('SPY', filled_at) as spy_then, symbol, qty
    from public.orders where user_id = p_user and status = 'filled'
  ), pos as (
    select symbol, sum(case when side = 'buy' then qty else -qty end) q from o group by 1
  ), agg as (
    select
      coalesce(sum(case when side = 'buy' then dollars end), 0) as bought,
      coalesce(sum(case when side = 'buy' then -dollars else dollars end), 0) as net_cash,          -- sale proceeds - purchases
      coalesce(sum(case when side = 'buy' then dollars else -dollars end / nullif(spy_then, 0)), 0) as spy_units,
      count(*) as n
    from o
  )
  select round(a.bought, 2),
         round(a.net_cash + coalesce((select sum(pos.q * lp.price) from pos join public.latest_prices lp using (symbol) where pos.q > 0), 0), 2),
         round(a.net_cash + a.spy_units * (select price from public.latest_prices where symbol = 'SPY'), 2),
         case when a.bought > 0 then round(100 * (
           (a.net_cash + coalesce((select sum(pos.q * lp.price) from pos join public.latest_prices lp using (symbol) where pos.q > 0), 0))
           - (a.net_cash + a.spy_units * (select price from public.latest_prices where symbol = 'SPY'))) / a.bought, 2) end,
         a.n
  from agg a
$$;

create or replace function public.my_market_compare() returns table (invested numeric, my_pnl numeric, spy_pnl numeric, alpha_pct numeric, trades bigint)
language sql stable security definer set search_path = public as $$ select * from public.market_compare((select auth.uid())) $$;

-- ---------------------------------------------------------------------------------------------------------------
-- 3. Daily snapshots after the close → risk-adjusted skill (Sharpe-style) and max drawdown.
--    Daily return strips out rewards (new money isn't skill): r = (V_t - (D_t - D_t-1)) / V_t-1 - 1.
-- ---------------------------------------------------------------------------------------------------------------
create table if not exists public.portfolio_daily (
  user_id  uuid not null references public.profiles (id) on delete cascade,
  day      date not null,
  value    numeric(16, 4) not null,
  deposits numeric(16, 4) not null,
  primary key (user_id, day)
);
alter table public.portfolio_daily enable row level security;
drop policy if exists "own snapshots" on public.portfolio_daily;
create policy "own snapshots" on public.portfolio_daily for select to authenticated using ((select auth.uid()) = user_id);

create or replace function public.skill_stats(p_user uuid) returns table (days bigint, total_return_pct numeric, sharpe numeric, max_drawdown_pct numeric)
language sql stable security definer set search_path = public as $$
  with s as (
    select day, value, deposits, lag(value) over w as pv, deposits - lag(deposits) over w as flow
    from public.portfolio_daily where user_id = p_user window w as (order by day)
  ), r as (
    select day, (value - flow) / nullif(pv, 0) - 1 as ret from s where pv is not null
  ), idx as (  -- growth of $1, compounding the flow-adjusted returns, to measure drawdowns
    select day, exp(sum(ln(greatest(1 + ret, 1e-9))) over (order by day)) as g from r
  ), dd as (
    select g / max(g) over (order by day rows between unbounded preceding and current row) - 1 as drawdown from idx
  )
  select (select count(*) from r),
         round(100 * ((select exp(sum(ln(greatest(1 + ret, 1e-9)))) from r) - 1), 2),
         case when (select count(*) from r) >= 5 and (select stddev_samp(ret) from r) > 0
              then round((select avg(ret) / stddev_samp(ret) * sqrt(252::numeric) from r), 2) end,
         round(100 * least(coalesce((select min(drawdown) from dd), 0), 0), 2)
$$;

create or replace function public.my_skill() returns table (days bigint, total_return_pct numeric, sharpe numeric, max_drawdown_pct numeric)
language sql stable security definer set search_path = public as $$ select * from public.skill_stats((select auth.uid())) $$;

-- Public "Skill" leaderboard: risk-adjusted return and beat-the-market for everyone with a username.
create or replace function public.leaderboard_skill() returns table (id uuid, username citext, display_name text, sharpe numeric, max_drawdown_pct numeric, days bigint, alpha_pct numeric, trades bigint)
language sql stable security definer set search_path = public as $$
  select pr.id, pr.username, pr.display_name, s.sharpe, s.max_drawdown_pct, s.days, m.alpha_pct, m.trades
  from public.profiles pr
  cross join lateral public.skill_stats(pr.id) s
  cross join lateral public.market_compare(pr.id) m
  where pr.username is not null and m.trades > 0
$$;

-- ---------------------------------------------------------------------------------------------------------------
-- 4. The daily 90% range game: "Where will the S&P 500 close?" Give a range you're 90% sure of.
--    Interval score (Gneiting & Raftery): S = width + (2/α)·miss, α = 0.1. Points = 100·max(0, 1 − S / 5% of the close):
--    a tight range that catches the close scores high; missing costs 20× the miss distance.
-- ---------------------------------------------------------------------------------------------------------------
create table if not exists public.range_calls (
  user_id    uuid not null references public.profiles (id) on delete cascade,
  day        date not null,               -- the trading day whose close is being called
  symbol     text not null default '^GSPC',
  low        numeric(16, 4) not null,
  high       numeric(16, 4) not null,
  ref_price  numeric(16, 4) not null,     -- price when the call was made
  made_at    timestamptz not null default now(),
  close      numeric(16, 4),
  points     int,
  hit        boolean,
  primary key (user_id, day, symbol),
  check (high > low)
);
alter table public.range_calls enable row level security;
drop policy if exists "own ranges" on public.range_calls;
create policy "own ranges" on public.range_calls for select to authenticated using ((select auth.uid()) = user_id);

-- The trading day a call made now is about: today if before 3:30 pm ET on a trading day, else the next trading day.
create or replace function public.range_target_day(p_ts timestamptz default now()) returns date
language plpgsql stable set search_path = public as $$
declare
  ny timestamp := p_ts at time zone 'America/New_York';
  d date := ny::date;
begin
  if not (public.us_market_open((d + time '12:00') at time zone 'America/New_York') and ny::time < time '15:30') then
    d := d + 1;
    while not public.us_market_open((d + time '12:00') at time zone 'America/New_York') loop d := d + 1; end loop;
  end if;
  return d;
end $$;

create or replace function public.make_range(p_low numeric, p_high numeric) returns public.range_calls
language plpgsql security definer set search_path = public as $$
declare
  me uuid := auth.uid();
  ref numeric := (select price from public.latest_prices where symbol = '^GSPC');
  r public.range_calls;
begin
  if me is null then raise exception 'Sign in to play'; end if;
  if p_low is null or p_high is null or p_high <= p_low then raise exception 'The high end must be above the low end'; end if;
  if p_low < ref * 0.8 or p_high > ref * 1.2 then raise exception 'Keep the range within 20%% of today''s price'; end if;
  insert into public.range_calls (user_id, day, low, high, ref_price)
  values (me, public.range_target_day(), round(p_low, 2), round(p_high, 2), ref)
  on conflict (user_id, day, symbol) do update set low = excluded.low, high = excluded.high, ref_price = excluded.ref_price, made_at = now()
    where range_calls.close is null
  returning * into r;
  if r is null then raise exception 'That day is already scored'; end if;
  return r;
end $$;

create or replace function public.my_ranges(p_limit int default 20) returns setof public.range_calls
language sql stable security definer set search_path = public as $$
  select * from public.range_calls where user_id = (select auth.uid()) order by day desc limit p_limit
$$;

create or replace function public.range_question() returns table (day date, price numeric, as_of timestamptz, prev_close numeric)
language sql stable security definer set search_path = public as $$
  select public.range_target_day(), lp.price, lp.as_of,
         (select price from public.prices where symbol = '^GSPC'
            and (as_of at time zone 'America/New_York')::date < (lp.as_of at time zone 'America/New_York')::date
          order by as_of desc limit 1)
  from public.latest_prices lp where lp.symbol = '^GSPC'
$$;

-- Score every unscored call whose day has closed (needs a price from 3:59 pm ET or later that day).
create or replace function public.settle_ranges() returns int
language plpgsql security definer set search_path = public as $$
declare
  c record; px numeric; s numeric; pts int; n int := 0;
begin
  for c in select * from public.range_calls where close is null and day <= (now() at time zone 'America/New_York')::date loop
    select price into px from public.prices
     where symbol = c.symbol and (as_of at time zone 'America/New_York')::date = c.day
       and (as_of at time zone 'America/New_York')::time >= time '15:59'
     order by as_of desc limit 1;
    if px is null then continue; end if;
    s := (c.high - c.low) + 20 * greatest(c.low - px, 0) + 20 * greatest(px - c.high, 0);
    pts := greatest(0, round(100 * (1 - s / (0.05 * px))))::int;
    update public.range_calls set close = px, points = pts, hit = px between c.low and c.high
     where user_id = c.user_id and day = c.day and symbol = c.symbol;
    if pts > 0 then
      perform public.give_reward(c.user_id, format('range:%s', c.day), pts * 2, format('Range call: %s points', pts));
    end if;
    n := n + 1;
  end loop;
  return n;
end $$;

create or replace function public.my_range_stats() returns table (calls bigint, scored bigint, hit_rate numeric, avg_points numeric)
language sql stable security definer set search_path = public as $$
  select count(*), count(close), round(100.0 * avg(hit::int) filter (where close is not null), 0), round(avg(points) filter (where close is not null), 0)
  from public.range_calls where user_id = (select auth.uid())
$$;

create or replace function public.leaderboard_ranges() returns table (id uuid, username citext, display_name text, scored bigint, avg_points numeric, hit_rate numeric)
language sql stable security definer set search_path = public as $$
  select pr.id, pr.username, pr.display_name, count(*), round(avg(rc.points), 0), round(100.0 * avg(rc.hit::int), 0)
  from public.range_calls rc join public.profiles pr on pr.id = rc.user_id
  where rc.close is not null and pr.username is not null group by 1, 2, 3
$$;

-- ---------------------------------------------------------------------------------------------------------------
-- After the close each trading day: snapshot every portfolio, then settle the range game.
-- ---------------------------------------------------------------------------------------------------------------
create or replace function public.after_close() returns void
language plpgsql security definer set search_path = public as $$
declare d date := (now() at time zone 'America/New_York')::date;
begin
  perform public.settle_ranges();   -- also catches up on any earlier unscored days
  if not public.us_market_open((d + time '12:00') at time zone 'America/New_York') then return; end if;
  insert into public.portfolio_daily (user_id, day, value, deposits)
  select pf.user_id, d, public.portfolio_value(pf.user_id), pf.deposits from public.portfolios pf
  on conflict (user_id, day) do update set value = excluded.value, deposits = excluded.deposits;
end $$;

select cron.unschedule(jobid) from cron.job where jobname = 'after-close';
-- 21:25 and 22:25 UTC = 4:25/5:25 pm New York in winter, 5:25/6:25 pm in summer: always after the last price update.
select cron.schedule('after-close', '25 21,22 * * 1-5', 'select public.after_close()');

-- ---------------------------------------------------------------------------------------------------------------
-- Access: helpers and jobs are server-only; the "my_" functions need sign-in; leaderboards are public.
-- ---------------------------------------------------------------------------------------------------------------
revoke execute on function public.price_at(text, timestamptz), public.portfolio_value(uuid), public.market_compare(uuid),
  public.skill_stats(uuid), public.settle_ranges(), public.after_close(), public.range_target_day(timestamptz) from public, anon, authenticated;
revoke execute on function public.my_market_compare(), public.my_skill(), public.make_range(numeric, numeric), public.my_ranges(int),
  public.my_range_stats() from public, anon;
grant execute on function public.my_market_compare(), public.my_skill(), public.make_range(numeric, numeric), public.my_ranges(int),
  public.my_range_stats() to authenticated;
revoke execute on function public.leaderboard_skill(), public.leaderboard_ranges(), public.range_question() from public;
grant execute on function public.leaderboard_skill(), public.leaderboard_ranges(), public.range_question() to anon, authenticated;
