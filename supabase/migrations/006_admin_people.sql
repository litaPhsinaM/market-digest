-- Team view of accounts and live activity. Admin-only; returns nothing to anyone else. Safe to re-run.

create or replace function public.admin_people(p_limit int default 100) returns table (
  email text, joined timestamptz, last_sign_in timestamptz, confirmed boolean, device text,
  username citext, streak int, stories_read int, quizzes int, quiz_correct int, last_active date,
  trades bigint, predictions bigint, following bigint)
language plpgsql stable security definer set search_path = public, auth as $$
begin
  if not public.is_admin() then return; end if;
  return query
  select u.email::text, u.created_at, u.last_sign_in_at, u.email_confirmed_at is not null,
         -- most recent session's browser/app, in plain words
         (select case
                   when s.user_agent ilike '%; wv)%' or s.user_agent ilike '%Android%Version/%Chrome%Mobile%' then 'Android app'
                   when s.user_agent ilike '%Android%' then 'Android browser'
                   when s.user_agent ilike '%iPhone%' or s.user_agent ilike '%iPad%' then 'iPhone/iPad'
                   when s.user_agent ilike '%Macintosh%' then 'Mac browser'
                   when s.user_agent ilike '%Windows%' then 'Windows browser'
                   else coalesce(left(s.user_agent, 30), 'unknown') end
            from auth.sessions s where s.user_id = u.id order by coalesce(s.updated_at, s.created_at) desc limit 1),
         p.username, p.streak, p.stories_read, p.quizzes, p.quiz_correct, p.last_active,
         (select count(*) from public.orders o where o.user_id = u.id),
         (select count(*) from public.predictions pr where pr.user_id = u.id),
         (select count(*) from public.follows f where f.follower = u.id)
  from auth.users u left join public.profiles p on p.id = u.id
  order by greatest(u.last_sign_in_at, u.created_at) desc nulls last
  limit least(greatest(p_limit, 1), 500);
end $$;
grant execute on function public.admin_people(int) to authenticated;
revoke execute on function public.admin_people(int) from anon;

-- Latest activity from real (non-team) devices, plus who is around right now.
create or replace function public.admin_live(p_limit int default 40) returns jsonb
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_admin() then return null; end if;
  return jsonb_build_object(
    'online_10m', (select count(distinct device) from public.real_events where created_at > now() - interval '10 minutes'),
    'online_1h', (select count(distinct device) from public.real_events where created_at > now() - interval '1 hour'),
    'feed', (select coalesce(jsonb_agg(e order by e.created_at desc), '[]') from (
      select created_at, event, platform, signed_in, left(device, 8) as device, props
      from public.real_events where event <> 'setup_check' order by created_at desc limit least(greatest(p_limit, 1), 200)) e));
end $$;
grant execute on function public.admin_live(int) to authenticated;
revoke execute on function public.admin_live(int) from anon;
