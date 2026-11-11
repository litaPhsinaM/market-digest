-- GitHub's own scheduler skips the price job (it never fired on 2026-11-11), so the database is the timer instead:
-- every 15 minutes on weekdays pg_cron asks GitHub to start "Update prices" (prices.yml); the job itself checks the
-- NYSE calendar and exits early when the market is closed. Runs on Supabase, so no laptop is needed.
-- The GitHub token (fine-grained, this repo only, Actions: read & write) lives in Supabase Vault as
-- 'github_dispatch_token'; set it with scripts/set-dispatch-token.py. Without it, the timer does nothing.
create extension if not exists pg_cron;
create extension if not exists pg_net;

create or replace function public.dispatch_price_job() returns void
language plpgsql security definer set search_path = public, vault, net as $$
declare tok text;
begin
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'github_dispatch_token';
  if tok is null then return; end if;
  perform net.http_post(
    url := 'https://api.github.com/repos/litaPhsinaM/market-digest/actions/workflows/prices.yml/dispatches',
    headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                  'X-GitHub-Api-Version', '2022-11-28', 'User-Agent', 'market-digest-timer'),
    body := '{"ref":"main"}'::jsonb);
end $$;
revoke execute on function public.dispatch_price_job() from public, anon, authenticated;

select cron.unschedule(jobid) from cron.job where jobname = 'price-update';
-- 13:00–21:59 UTC covers 9:30 am–4:15 pm New York in both summer and winter time; the job skips closed times.
select cron.schedule('price-update', '2,17,32,47 13-21 * * 1-5', 'select public.dispatch_price_job()');
