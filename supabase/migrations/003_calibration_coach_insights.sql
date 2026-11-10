-- Market Digest: calibrated predictions (Brier score), behavioural coach, and private insights for the team.
-- Run after 002_social.sql in Supabase → SQL Editor. Safe to re-run.

-- ============ calibrated predictions ============
-- Users say how sure they are (50-99%). Scored with the Brier score: (confidence - outcome)^2, lower is better.
-- A coin-flip guesser at 50% scores 0.25; a well-calibrated forecaster beats that consistently.
alter table public.predictions add column if not exists confidence numeric(3, 2) not null default 0.60 check (confidence between 0.50 and 0.99);
alter table public.predictions add column if not exists brier numeric(6, 4);

drop function if exists public.predict(text, text);
create or replace function public.predict(p_symbol text, p_direction text, p_confidence numeric default 0.60) returns public.predictions
language plpgsql security definer set search_path = public as $$
declare
  uid uuid := auth.uid();
  lp record;
  pr public.predictions;
begin
  if uid is null then raise exception 'Sign in to play'; end if;
  if not exists (select 1 from public.profiles where id = uid and username is not null) then raise exception 'Pick a username first'; end if;
  if p_confidence < 0.50 or p_confidence > 0.99 then raise exception 'Confidence must be between 50%% and 99%%'; end if;
  select * into lp from public.latest_prices where symbol = upper(p_symbol);
  if lp is null then raise exception 'No price for that symbol'; end if;
  insert into public.predictions (user_id, symbol, direction, base_price, base_as_of, confidence)
  values (uid, upper(p_symbol), p_direction, lp.price, lp.as_of, round(p_confidence, 2)) returning * into pr;
  return pr;
exception when unique_violation then
  raise exception 'You already have an open call on %', upper(p_symbol);
end $$;
grant execute on function public.predict(text, text, numeric) to authenticated;
revoke execute on function public.predict(text, text, numeric) from anon;

-- Fill in the Brier score whenever a prediction is settled (the price trigger sets status).
create or replace function public.score_prediction() returns trigger
language plpgsql as $$
begin
  if new.status in ('right', 'wrong') and (old.status is distinct from new.status) then
    new.brier := power(new.confidence - case when new.status = 'right' then 1 else 0 end, 2);
  end if;
  return new;
end $$;
drop trigger if exists predictions_brier on public.predictions;
create trigger predictions_brier before update on public.predictions for each row execute function public.score_prediction();

drop function if exists public.leaderboard_predictions();
create or replace function public.leaderboard_predictions() returns table (id uuid, username citext, display_name text, calls bigint, right_calls bigint, accuracy numeric, brier numeric, skill numeric)
language sql stable security definer set search_path = public as $$
  -- skill = how much better than always saying "50%" (Brier 0.25); ranked by skill, with at least 5 scored calls
  select pr.id, pr.username, pr.display_name, count(*) as calls,
         count(*) filter (where p.status = 'right') as right_calls,
         round(100.0 * count(*) filter (where p.status = 'right') / nullif(count(*) filter (where p.status in ('right', 'wrong')), 0), 1) as accuracy,
         round(avg(p.brier), 4) as brier,
         round((0.25 - avg(p.brier)) / 0.25 * 100, 1) as skill
  from public.predictions p join public.profiles pr on pr.id = p.user_id
  where pr.username is not null and p.made_at > now() - interval '60 days'
  group by pr.id, pr.username, pr.display_name;
$$;
grant execute on function public.leaderboard_predictions() to anon, authenticated;

-- Personal calibration: for each confidence bucket, how often the user was actually right.
create or replace function public.my_calibration() returns table (bucket int, calls bigint, hit_rate numeric)
language sql stable security definer set search_path = public as $$
  select (floor(confidence * 10) * 10)::int as bucket, count(*), round(avg(case when status = 'right' then 1.0 else 0 end) * 100, 1)
  from public.predictions where user_id = auth.uid() and status in ('right', 'wrong')
  group by 1 order by 1;
$$;
grant execute on function public.my_calibration() to authenticated;

-- ============ behavioural coach ============
-- Looks at the signed-in user's own paper trades and points out classic investor mistakes, each linked to a lesson.
create or replace function public.coach() returns table (kind text, severity text, message text, lesson text)
language plpgsql stable security definer set search_path = public as $$
declare
  uid uuid := auth.uid();
  total numeric; top_val numeric; top_sym text; cash numeric; n_week int; started timestamptz;
  r record;
begin
  if uid is null then return; end if;
  select pf.cash, pf.created_at into cash, started from public.portfolios pf where pf.user_id = uid;
  if cash is null then return; end if;

  with pos as (
    select o.symbol, sum(case when side = 'buy' then qty else -qty end) as qty from public.orders o
    where o.user_id = uid and status = 'filled' group by 1 having sum(case when side = 'buy' then qty else -qty end) > 0
  )
  select coalesce(sum(pos.qty * lp.price), 0), max(pos.qty * lp.price) into total, top_val
  from pos join public.latest_prices lp using (symbol);
  select pos_sym into top_sym from (
    select o.symbol as pos_sym, sum(case when side = 'buy' then qty else -qty end) * max(lp.price) as v
    from public.orders o join public.latest_prices lp on lp.symbol = o.symbol
    where o.user_id = uid and status = 'filled' group by 1 order by 2 desc limit 1) t;
  total := total + cash;

  if top_val is not null and top_sym not in ('SPY', 'VTI', 'QQQ') and top_val / total > 0.5 then
    return query select 'concentration', 'warn',
      format('%s%% of your portfolio is in %s. One bad day for a single company can sink the whole thing.', round(top_val / total * 100), top_sym),
      'l14';
  end if;

  select count(*) into n_week from public.orders where user_id = uid and status = 'filled' and filled_at > now() - interval '7 days';
  if n_week >= 10 then
    return query select 'overtrading', 'warn',
      format('You made %s trades this week. Frequent trading usually lowers returns (costs, taxes, bad timing) for real investors.', n_week), 'l20';
  end if;

  -- panic selling: sold below the average buy price within 10 days of buying
  for r in
    select s.symbol, s.fill_price, b.avg_px, s.filled_at from public.orders s
    join lateral (select avg(fill_price) as avg_px, min(filled_at) as first_buy from public.orders b
                  where b.user_id = uid and b.symbol = s.symbol and b.side = 'buy' and b.status = 'filled' and b.filled_at < s.filled_at) b on true
    where s.user_id = uid and s.side = 'sell' and s.status = 'filled' and s.filled_at > now() - interval '30 days'
      and s.fill_price < b.avg_px * 0.97 and s.filled_at < b.first_buy + interval '10 days'
    order by s.filled_at desc limit 1
  loop
    return query select 'panic_sell', 'warn',
      format('You sold %s at %s, %s%% below what you paid, within days of buying. Selling after a drop locks in the loss.',
             r.symbol, to_char(r.fill_price, 'FM$999,990.00'), round((1 - r.fill_price / r.avg_px) * 100, 1)), 'l21';
  end loop;

  if cash / total > 0.9 and started < now() - interval '14 days' then
    return query select 'cash_drag', 'info',
      'Over 90% of your portfolio is still cash after two weeks. Practising is the point here, and there is nothing to lose.', 'l20';
  end if;

  if top_val is not null and exists (select 1 from public.orders where user_id = uid and symbol in ('SPY', 'VTI', 'QQQ') and status = 'filled' and side = 'buy') then
    return query select 'good_index', 'good', 'You own an index fund. That is how most professionals would tell a beginner to start.', 'l11';
  end if;
end $$;
grant execute on function public.coach() to authenticated;

-- ============ private insights for the team ============
create table if not exists public.admins (user_id uuid primary key references auth.users (id) on delete cascade);
alter table public.admins enable row level security;  -- no policies: managed in the SQL editor only

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.admins where user_id = auth.uid());
$$;
grant execute on function public.is_admin() to authenticated;

-- Everything the insights page shows, in one call. Only admins get data; everyone else gets null.
create or replace function public.admin_insights(p_days int default 30) returns jsonb
language plpgsql stable security definer set search_path = public, auth as $$
declare
  since timestamptz := now() - make_interval(days => least(greatest(p_days, 7), 365));
  out jsonb;
begin
  if not public.is_admin() then return null; end if;
  select jsonb_build_object(
    'daily', (select coalesce(jsonb_agg(d order by d.day), '[]') from (
        select created_at::date as day, count(distinct device) as devices,
               count(distinct device) filter (where signed_in) as signed_in,
               count(*) filter (where event = 'story_read') as reads,
               count(*) filter (where event in ('quiz_done', 'practice_done')) as quizzes,
               count(*) filter (where event = 'lesson_done') as lessons,
               count(*) filter (where event = 'listen') as listens
        from public.events where created_at >= since group by 1) d),
    'features', (select coalesce(jsonb_object_agg(event, n), '{}') from (
        select event, count(*) as n from public.events where created_at >= since group by 1) f),
    'platforms', (select coalesce(jsonb_object_agg(platform, n), '{}') from (
        select coalesce(platform, 'unknown') as platform, count(distinct device) as n from public.events where created_at >= since group by 1) p),
    'signups', (select coalesce(jsonb_agg(s order by s.day), '[]') from (
        select created_at::date as day, count(*) as n from auth.users where created_at >= since group by 1) s),
    'totals', jsonb_build_object(
        'users', (select count(*) from auth.users),
        'profiles', (select count(*) from public.profiles where username is not null),
        'devices_7d', (select count(distinct device) from public.events where created_at > now() - interval '7 days'),
        'devices_30d', (select count(distinct device) from public.events where created_at > now() - interval '30 days'),
        'portfolios', (select count(*) from public.portfolios),
        'predictions', (select count(*) from public.predictions),
        'follows', (select count(*) from public.follows)),
    -- Week-1 retention: of devices first seen in each week, how many came back on a later day within 7 days.
    'retention', (select coalesce(jsonb_agg(r order by r.cohort), '[]') from (
        select date_trunc('week', first_seen)::date as cohort, count(*) as devices,
               round(100.0 * count(*) filter (where returned) / count(*), 1) as d7_return_pct
        from (select device, min(created_at) as first_seen,
                     bool_or(created_at::date > (select min(e2.created_at)::date from public.events e2 where e2.device = e.device)
                             and created_at < (select min(e2.created_at) from public.events e2 where e2.device = e.device) + interval '7 days') as returned
              from public.events e where device is not null group by device) firsts
        where first_seen >= since group by 1) r),
    -- Which lessons people finish, and which practice levels they attempt.
    'lessons', (select coalesce(jsonb_object_agg(lesson, n), '{}') from (
        select props->>'id' as lesson, count(distinct device) as n from public.events
        where event = 'lesson_done' and created_at >= since group by 1) l),
    'practice', (select coalesce(jsonb_agg(x), '[]') from (
        select props->>'level' as level, count(*) as rounds, round(avg((props->>'right')::numeric), 1) as avg_score
        from public.events where event = 'practice_done' and created_at >= since group by 1) x)
  ) into out;
  return out;
end $$;
grant execute on function public.admin_insights(int) to authenticated;
revoke execute on function public.admin_insights(int) from anon;
