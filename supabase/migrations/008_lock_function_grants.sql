-- Defence in depth: Postgres lets PUBLIC execute new functions by default. Every function below already checks who is
-- calling, but signed-out visitors shouldn't be able to call them at all. Safe to re-run.

do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as sig, p.proname
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.prosecdef and p.prorettype <> 'trigger'::regtype
  loop
    execute format('revoke execute on function %s from public, anon', f.sig);
    execute format('grant execute on function %s to authenticated', f.sig);
  end loop;
end $$;

-- Leaderboards are meant to be public.
grant execute on function public.leaderboard_portfolios(), public.leaderboard_predictions() to anon;

-- Future functions in this schema: no automatic access for signed-out visitors.
alter default privileges in schema public revoke execute on functions from public, anon;
