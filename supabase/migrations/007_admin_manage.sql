-- Developer tools: manage people (ban, clear username, admin rights, delete). Admin-only. Safe to re-run.

drop function if exists public.admin_people(int);
create or replace function public.admin_people(p_limit int default 100) returns table (
  id uuid, email text, joined timestamptz, last_sign_in timestamptz, confirmed boolean, banned boolean, is_admin boolean,
  device text, username citext, streak int, stories_read int, quizzes int, quiz_correct int, last_active date,
  trades bigint, predictions bigint, following bigint)
language plpgsql stable security definer set search_path = public, auth as $$
begin
  if not public.is_admin() then return; end if;
  return query
  select u.id, u.email::text, u.created_at, u.last_sign_in_at, u.email_confirmed_at is not null,
         coalesce(u.banned_until > now(), false), exists (select 1 from public.admins a where a.user_id = u.id),
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

create or replace function public.admin_user_action(p_user uuid, p_action text) returns text
language plpgsql security definer set search_path = public, auth as $$
declare
  me uuid := auth.uid();
begin
  if not public.is_admin() then raise exception 'Admins only'; end if;
  if p_user = me and p_action in ('ban', 'remove_admin', 'delete') then raise exception 'You can''t do that to your own account'; end if;
  if not exists (select 1 from auth.users where id = p_user) then raise exception 'No such user'; end if;
  case p_action
    when 'ban' then
      update auth.users set banned_until = now() + interval '100 years' where id = p_user;
      delete from auth.sessions where user_id = p_user;   -- signs them out everywhere
      return 'Banned and signed out';
    when 'unban' then
      update auth.users set banned_until = null where id = p_user;
      return 'Unbanned';
    when 'clear_username' then
      update public.profiles set username = null where id = p_user;
      return 'Username cleared';
    when 'make_admin' then
      insert into public.admins (user_id) values (p_user) on conflict do nothing;
      return 'Now an admin';
    when 'remove_admin' then
      delete from public.admins where user_id = p_user;
      return 'Admin rights removed';
    when 'delete' then
      delete from auth.users where id = p_user;            -- cascades to their progress, profile, games
      return 'Account deleted';
    else
      raise exception 'Unknown action %', p_action;
  end case;
end $$;
grant execute on function public.admin_user_action(uuid, text) to authenticated;
revoke execute on function public.admin_user_action(uuid, text) from anon;
