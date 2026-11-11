-- Friends' moves: recent predictions and paper trades of people you follow AND who follow you back.
-- (Trades are otherwise private; mutual follows is the line we draw.) Safe to re-run.

create or replace function public.friend_feed(p_limit int default 30) returns table (
  at timestamptz, kind text, username citext, display_name text, symbol text, detail text, status text)
language sql stable security definer set search_path = public as $$
  with mutual as (
    select f.followee as id from public.follows f
    join public.follows back on back.follower = f.followee and back.followee = f.follower
    where f.follower = auth.uid()
  )
  select * from (
    select p.made_at, 'prediction', pr.username, pr.display_name, p.symbol,
           format('%s %s%% sure, from %s', case when p.direction = 'up' then '▲ higher' else '▼ lower' end,
                  round(p.confidence * 100), to_char(p.base_price, 'FM$999,990.00')),
           p.status
    from public.predictions p join mutual m on m.id = p.user_id join public.profiles pr on pr.id = p.user_id
    union all
    select o.placed_at, 'trade', pr.username, pr.display_name, o.symbol,
           format('%s %s shares%s', case when o.side = 'buy' then 'bought' else 'sold' end, trim(to_char(o.qty, 'FM999,990.####')),
                  case when o.fill_price is not null then ' at ' || to_char(o.fill_price, 'FM$999,990.00') else '' end),
           o.status
    from public.orders o join mutual m on m.id = o.user_id join public.profiles pr on pr.id = o.user_id
    where o.status <> 'cancelled'
  ) feed (at, kind, username, display_name, symbol, detail, status)
  order by at desc
  limit least(greatest(p_limit, 1), 100);
$$;
revoke execute on function public.friend_feed(int) from public, anon;
grant execute on function public.friend_feed(int) to authenticated;
