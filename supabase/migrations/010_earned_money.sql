-- Earned money: start with $10,000 and earn more by learning and making good calls. Safe to re-run.
-- "deposits" = all the money a player has been given (start + rewards). Investment return is measured against it, so
-- rewards make you richer but don't fake investing skill.

alter table public.portfolios alter column cash set default 10000;
alter table public.portfolios add column if not exists deposits numeric(16, 4) not null default 10000;

create table if not exists public.rewards (
  user_id    uuid not null references public.profiles (id) on delete cascade,
  key        text not null,               -- unique per achievement, e.g. 'lesson:l03', 'quiz:2026-11-10:1', 'pred:42'
  amount     numeric(12, 2) not null,
  reason     text not null,
  created_at timestamptz not null default now(),
  primary key (user_id, key)
);
alter table public.rewards enable row level security;
drop policy if exists "own rewards" on public.rewards;
create policy "own rewards" on public.rewards for select to authenticated using ((select auth.uid()) = user_id);

-- Pay a reward once (the key makes it idempotent). Negative amounts are penalties, never taking cash below zero.
create or replace function public.give_reward(p_user uuid, p_key text, p_amount numeric, p_reason text) returns boolean
language plpgsql security definer set search_path = public as $$
declare
  amt numeric := p_amount;
  have numeric;
begin
  if not exists (select 1 from public.profiles where id = p_user) then return false; end if;
  insert into public.portfolios (user_id) values (p_user) on conflict do nothing;
  if amt < 0 then
    select cash into have from public.portfolios where user_id = p_user;
    amt := -least(-amt, have);
  end if;
  insert into public.rewards (user_id, key, amount, reason) values (p_user, p_key, amt, p_reason) on conflict do nothing;
  if not found then return false; end if;
  update public.portfolios set cash = cash + amt, deposits = deposits + amt where user_id = p_user;
  return true;
end $$;
revoke execute on function public.give_reward(uuid, text, numeric, text) from public, anon, authenticated;

-- Learning rewards, read from the synced progress whenever it changes: correct quiz answers (checked against the
-- real answer key), completed lessons, and 7-day streak milestones.
create or replace function public.reward_learning() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  r record;
  best int;
begin
  for r in
    select substring(e.k from 6)::date as day, a.q::smallint as q
    from jsonb_each(new.state) e(k, v)
    cross join lateral jsonb_each_text(v) a(q, pick)
    join public.quiz_keys qk on qk.day = substring(e.k from 6)::date and qk.q = a.q::smallint and qk.answer = a.pick::smallint
    where e.k ~ '^quiz:\d{4}-\d{2}-\d{2}$' and jsonb_typeof(v) = 'object' and a.q ~ '^\d+$' and a.pick ~ '^\d+$'
  loop
    perform public.give_reward(new.user_id, format('quiz:%s:%s', r.day, r.q), 100, 'Correct daily-quiz answer');
  end loop;

  for r in
    select substring(e.k from 8) as lesson from jsonb_each(new.state) e(k, v)
    where e.k ~ '^lesson:l\d{2}$' and jsonb_typeof(v) = 'object' and coalesce(v->>'done', 'false') not in ('false', '', 'null')
  loop
    perform public.give_reward(new.user_id, 'lesson:' || r.lesson, 500, 'Completed lesson ' || ltrim(substring(r.lesson from 2), '0'));
  end loop;

  select best_streak into best from public.profiles where id = new.user_id;
  for m in 1 .. coalesce(best, 0) / 7 loop
    perform public.give_reward(new.user_id, 'streak:' || (m * 7), 1000, format('%s-day streak', m * 7));
  end loop;
  return new;
end $$;
-- Named to run after user_state_stats (triggers fire alphabetically), so best_streak is already up to date.
drop trigger if exists user_state_zrewards on public.user_state;
create trigger user_state_zrewards after insert or update on public.user_state for each row execute function public.reward_learning();

-- Prediction rewards: right calls pay more the more confident you were; confident wrong calls cost a little.
create or replace function public.reward_prediction() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if old.status = 'pending' and new.status = 'right' then
    perform public.give_reward(new.user_id, 'pred:' || new.id, round(100 + 300 * (new.confidence - 0.5) / 0.49), format('Right call on %s', new.symbol));
  elsif old.status = 'pending' and new.status = 'wrong' and new.confidence >= 0.80 then
    perform public.give_reward(new.user_id, 'pred:' || new.id, -100, format('Confident miss on %s', new.symbol));
  end if;
  return new;
end $$;
drop trigger if exists predictions_reward on public.predictions;
create trigger predictions_reward after update on public.predictions for each row execute function public.reward_prediction();

-- Leaderboard: return is measured against everything you've been given (start + rewards).
drop function if exists public.leaderboard_portfolios();
create or replace function public.leaderboard_portfolios() returns table (id uuid, username citext, display_name text, value numeric, return_pct numeric, holdings bigint, deposits numeric)
language sql stable security definer set search_path = public as $$
  with pos as (
    select o.user_id, o.symbol, sum(case when side = 'buy' then qty else -qty end) as qty
    from public.orders o where status = 'filled' group by 1, 2
  ), val as (
    select pf.user_id, pf.deposits, pf.cash + coalesce(sum(pos.qty * lp.price), 0) as value, count(pos.symbol) filter (where pos.qty > 0) as holdings
    from public.portfolios pf
    left join pos on pos.user_id = pf.user_id and pos.qty > 0
    left join public.latest_prices lp on lp.symbol = pos.symbol
    group by pf.user_id, pf.cash, pf.deposits
  )
  select pr.id, pr.username, pr.display_name, round(v.value, 2), round((v.value / nullif(v.deposits, 0) - 1) * 100, 2), v.holdings, round(v.deposits, 2)
  from val v join public.profiles pr on pr.id = v.user_id where pr.username is not null;
$$;
revoke execute on function public.leaderboard_portfolios() from public;
grant execute on function public.leaderboard_portfolios() to anon, authenticated;
