-- Orders fill and predictions are scored only on prices from US market hours (Mon-Fri 9:30-16:00 New York).
create or replace function public.on_new_price() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  o record;
  held numeric;
  cash_now numeric;
begin
  -- Only prices from while the US market is open fill orders and score predictions. Prices pushed at night or on
  -- weekends just update what people see; orders stay pending until the market opens.
  if extract(isodow from new.as_of at time zone 'America/New_York') > 5
     or (new.as_of at time zone 'America/New_York')::time not between time '09:30' and time '16:00' then
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
