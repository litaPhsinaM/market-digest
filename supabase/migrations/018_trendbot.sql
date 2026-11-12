-- TrendBot: a robot player that paper-trades with the 100-point technical checklist from ZhuLinsen/daily_stock_analysis
-- (digest/trendbot.py). It competes on the normal leaderboards with the same $10,000, the same order engine (fills at
-- the next real price) and no learning rewards. Every decision is logged publicly with its reasons. Safe to re-run.

-- The bot needs an account like any player, but one nobody can sign in to: no password, an unroutable email, banned.
insert into auth.users (instance_id, id, aud, role, email, encrypted_password, raw_app_meta_data, raw_user_meta_data,
                        created_at, updated_at, banned_until)
values ('00000000-0000-0000-0000-000000000000', 'b07b07b0-7000-4000-8000-00000000b07b', 'authenticated', 'authenticated',
        'trendbot@bots.invalid', '', '{"provider": "bot"}', '{"bot": true}', now(), now(), '2999-01-01')
on conflict (id) do nothing;

insert into public.profiles (id, username, display_name)
values ('b07b07b0-7000-4000-8000-00000000b07b', 'trendbot', '🤖 TrendBot')
on conflict (id) do update set username = excluded.username, display_name = excluded.display_name;

insert into public.portfolios (user_id) values ('b07b07b0-7000-4000-8000-00000000b07b') on conflict do nothing;

-- Every daily decision, with the checklist numbers behind it. Public: the point is that anyone can see why.
create table if not exists public.bot_decisions (
  day          date not null,
  symbol       text not null,
  action       text not null check (action in ('buy', 'sell', 'hold')),
  score        int not null,
  signal       text not null,          -- upstream label: STRONG_BUY / BUY / WAIT / SELL / STRONG_SELL ...
  trend        text,                   -- e.g. BULL (MA5 > MA10 > MA20)
  bias_pct     numeric(8, 2),          -- % above (or below) the 5-day average
  volume_ratio numeric(8, 2),          -- today's volume vs the 5-day average
  macd         text,
  rsi          numeric(6, 1),
  qty          numeric(18, 6),
  price        numeric(16, 4),
  created_at   timestamptz not null default now(),
  primary key (day, symbol)
);
alter table public.bot_decisions enable row level security;
drop policy if exists "bot decisions are public" on public.bot_decisions;
create policy "bot decisions are public" on public.bot_decisions for select to anon, authenticated using (true);

-- Public summary for the Play page: value, cash, holdings, and the latest decisions.
create or replace function public.trendbot_status() returns jsonb
language sql stable security definer set search_path = public as $$
  with me as (select 'b07b07b0-7000-4000-8000-00000000b07b'::uuid as id),
  pos as (
    select o.symbol, sum(case when o.side = 'buy' then o.qty else -o.qty end) as qty
    from public.orders o, me where o.user_id = me.id and o.status = 'filled' group by 1
  ),
  h as (
    select pos.symbol, pos.qty, lp.price, pos.qty * lp.price as value
    from pos join public.latest_prices lp using (symbol) where pos.qty > 0.000001
  )
  select jsonb_build_object(
    'cash', (select round(cash, 2) from public.portfolios, me where user_id = me.id),
    'value', (select round(pf.cash + coalesce((select sum(value) from h), 0), 2) from public.portfolios pf, me where pf.user_id = me.id),
    'start', 10000,
    'pending', (select count(*) from public.orders, me where user_id = me.id and status = 'pending'),
    'holdings', coalesce((select jsonb_agg(jsonb_build_object('symbol', symbol, 'qty', round(qty, 4), 'price', round(price, 2),
                          'value', round(value, 2)) order by value desc) from h), '[]'::jsonb),
    'decisions', coalesce((select jsonb_agg(to_jsonb(d) - 'created_at' order by d.day desc, d.action, d.score desc)
                           from (select * from public.bot_decisions
                                 where day >= (select max(day) from public.bot_decisions) - 6) d), '[]'::jsonb),
    'last_day', (select max(day) from public.bot_decisions)
  )
$$;
revoke execute on function public.trendbot_status() from public;
grant execute on function public.trendbot_status() to anon, authenticated;
