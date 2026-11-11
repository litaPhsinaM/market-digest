-- The database starts the daily AI run too (.github/workflows/daily.yml), the same way 015 starts the price job:
-- pg_cron asks GitHub to dispatch the workflow, with the token stored in Supabase Vault as 'github_dispatch_token'
-- (scripts/set-dispatch-token.py). Without the token the timer does nothing. GitHub's own schedule in daily.yml is
-- only a backup and skips itself once today's digest exists.
-- Pending: rename to 016_daily_timer.sql and run `python migrate.py` once the cloud run should replace the Mac's.
create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Once each weekday at 5:30 am New York time. pg_cron runs in UTC, so it fires at both 09:30 UTC (5:30 am in summer
-- time, EDT) and 10:30 UTC (5:30 am in winter time, EST), and only the run that lands on 5 am New York time dispatches.
create or replace function public.dispatch_daily_job() returns void
language plpgsql security definer set search_path = public, vault, net as $$
declare tok text;
begin
  if extract(hour from now() at time zone 'America/New_York') <> 5 then return; end if;
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'github_dispatch_token';
  if tok is null then return; end if;
  perform net.http_post(
    url := 'https://api.github.com/repos/litaPhsinaM/market-digest/actions/workflows/daily.yml/dispatches',
    headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                  'X-GitHub-Api-Version', '2022-11-28', 'User-Agent', 'market-digest-timer'),
    body := '{"ref":"main"}'::jsonb);
end $$;
revoke execute on function public.dispatch_daily_job() from public, anon, authenticated;

select cron.unschedule(jobid) from cron.job where jobname = 'daily-digest';
select cron.schedule('daily-digest', '30 9,10 * * 1-5', 'select public.dispatch_daily_job()');
