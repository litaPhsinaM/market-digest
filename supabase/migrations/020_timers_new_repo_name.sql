-- The GitHub project was renamed market-digest → stocksplain (2026-11-12). The two timers that ask GitHub to start
-- the price job and the daily AI run now use the new name. GitHub redirects old API addresses, but pg_net does not
-- follow redirects, so without this the timers would quietly stop starting jobs. Same functions as 015/016; only the
-- URL (and User-Agent) change. Schedules are untouched.
create or replace function public.dispatch_price_job() returns void
language plpgsql security definer set search_path = public, vault, net as $$
declare tok text;
begin
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'github_dispatch_token';
  if tok is null then return; end if;
  perform net.http_post(
    url := 'https://api.github.com/repos/litaPhsinaM/stocksplain/actions/workflows/prices.yml/dispatches',
    headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                  'X-GitHub-Api-Version', '2022-11-28', 'User-Agent', 'stocksplain-timer'),
    body := '{"ref":"main"}'::jsonb);
end $$;
revoke execute on function public.dispatch_price_job() from public, anon, authenticated;

create or replace function public.dispatch_daily_job() returns void
language plpgsql security definer set search_path = public, vault, net as $$
declare tok text;
begin
  if extract(hour from now() at time zone 'America/New_York') <> 5 then return; end if;
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'github_dispatch_token';
  if tok is null then return; end if;
  perform net.http_post(
    url := 'https://api.github.com/repos/litaPhsinaM/stocksplain/actions/workflows/daily.yml/dispatches',
    headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                  'X-GitHub-Api-Version', '2022-11-28', 'User-Agent', 'stocksplain-timer'),
    body := '{"ref":"main"}'::jsonb);
end $$;
revoke execute on function public.dispatch_daily_job() from public, anon, authenticated;
