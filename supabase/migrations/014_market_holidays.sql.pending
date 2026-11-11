-- NOT APPLIED YET. Review, then rename to 014_market_holidays.sql and run `python migrate.py`.
--
-- Why: 012 treats every weekday 9:30-16:00 New York time as "market open". On an NYSE holiday (e.g. Thanksgiving,
-- 2026-11-26) or after a 1 pm early close (2026-11-27, 2026-12-24) any price pushed in that window still fills
-- pending orders and scores predictions, at a price that is really the last close: people can trade after the bell at
-- a known price, and Today's calls get "scored" on a day the market never moved. The pipeline now refuses to send
-- such prices (digest/supa.py push_prices), so this is defence in depth for anything else that writes prices.
-- Keep the dates in sync with digest/hours.py and templates/features.js.

create or replace function public.us_market_open(ts timestamptz) returns boolean
language sql immutable set search_path = public as $$
  select extract(isodow from ts at time zone 'America/New_York') <= 5
     and (ts at time zone 'America/New_York')::date <> all (array[
           '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07',
           '2026-11-26', '2026-12-25',
           '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06',
           '2027-11-25', '2027-12-24']::date[])
     and (ts at time zone 'America/New_York')::time between time '09:30' and
         case when (ts at time zone 'America/New_York')::date = any (array['2026-11-27', '2026-12-24', '2027-11-26']::date[])
              then time '13:00' else time '16:00' end
$$;
revoke execute on function public.us_market_open(timestamptz) from public, anon, authenticated;

-- Same as 012, with the open/closed test replaced by us_market_open().
create or replace function public.on_new_price() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  o record;
  held numeric;
  cash_now numeric;
begin
  -- Only prices from while the US market is open fill orders and score predictions. Prices pushed at night, on
  -- weekends or holidays just update what people see; orders stay pending until the market opens.
  if not public.us_market_open(new.as_of) then
    return new;
  end if;
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
