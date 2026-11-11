-- Insights count real users only: same as admin_insights in 003, reading real_events (excludes internal devices).
create or replace function public.admin_insights(p_days int default 30) returns jsonb
language plpgsql stable security definer set search_path = public, auth as $$
declare
  since timestamptz := now() - make_interval(days => least(greatest(p_days, 7), 365));
  out jsonb;
begin
  if not public.is_admin() then return null; end if;
  select jsonb_build_object(
    'daily', (select coalesce(jsonb_agg(d order by d.day), '[]') from (
        select created_at::date as day, count(distinct device) as devices,
               count(distinct device) filter (where signed_in) as signed_in,
               count(*) filter (where event = 'story_read') as reads,
               count(*) filter (where event in ('quiz_done', 'practice_done')) as quizzes,
               count(*) filter (where event = 'lesson_done') as lessons,
               count(*) filter (where event = 'listen') as listens
        from public.real_events where created_at >= since group by 1) d),
    'features', (select coalesce(jsonb_object_agg(event, n), '{}') from (
        select event, count(*) as n from public.real_events where created_at >= since group by 1) f),
    'platforms', (select coalesce(jsonb_object_agg(platform, n), '{}') from (
        select coalesce(platform, 'unknown') as platform, count(distinct device) as n from public.real_events where created_at >= since group by 1) p),
    'signups', (select coalesce(jsonb_agg(s order by s.day), '[]') from (
        select created_at::date as day, count(*) as n from auth.users where created_at >= since group by 1) s),
    'totals', jsonb_build_object(
        'internal_devices', (select count(*) from public.internal_devices),
        'users', (select count(*) from auth.users),
        'profiles', (select count(*) from public.profiles where username is not null),
        'devices_7d', (select count(distinct device) from public.real_events where created_at > now() - interval '7 days'),
        'devices_30d', (select count(distinct device) from public.real_events where created_at > now() - interval '30 days'),
        'portfolios', (select count(*) from public.portfolios),
        'predictions', (select count(*) from public.predictions),
        'follows', (select count(*) from public.follows)),
    -- Week-1 retention: of devices first seen in each week, how many came back on a later day within 7 days.
    'retention', (select coalesce(jsonb_agg(r order by r.cohort), '[]') from (
        select date_trunc('week', first_seen)::date as cohort, count(*) as devices,
               round(100.0 * count(*) filter (where returned) / count(*), 1) as d7_return_pct
        from (select device, min(created_at) as first_seen,
                     bool_or(created_at::date > (select min(e2.created_at)::date from public.real_events e2 where e2.device = e.device)
                             and created_at < (select min(e2.created_at) from public.real_events e2 where e2.device = e.device) + interval '7 days') as returned
              from public.real_events e where device is not null group by device) firsts
        where first_seen >= since group by 1) r),
    -- Which lessons people finish, and which practice levels they attempt.
    'lessons', (select coalesce(jsonb_object_agg(lesson, n), '{}') from (
        select props->>'id' as lesson, count(distinct device) as n from public.real_events
        where event = 'lesson_done' and created_at >= since group by 1) l),
    'practice', (select coalesce(jsonb_agg(x), '[]') from (
        select props->>'level' as level, count(*) as rounds, round(avg((props->>'right')::numeric), 1) as avg_score
        from public.real_events where event = 'practice_done' and created_at >= since group by 1) x)
  ) into out;
  return out;
end $$;
