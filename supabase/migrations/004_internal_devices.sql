-- Keep the team's own devices (and test browsers) out of the insights. Safe to re-run.

create table if not exists public.internal_devices (
  device   text primary key,
  added_at timestamptz not null default now()
);
alter table public.internal_devices enable row level security;  -- managed only through mark_internal_device()

-- Called by the insights page: whoever opens it as an admin has their device excluded from the stats.
create or replace function public.mark_internal_device(p_device text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then return; end if;
  insert into public.internal_devices (device) values (left(p_device, 40)) on conflict do nothing;
end $$;
grant execute on function public.mark_internal_device(text) to authenticated;

-- Everything recorded before launch was testing.
insert into public.internal_devices (device)
select distinct device from public.events where device is not null on conflict do nothing;

-- Same insights as before, but only counting real users' devices.
create or replace view public.real_events with (security_invoker = true) as
select e.* from public.events e where e.device is null or e.device not in (select device from public.internal_devices);
