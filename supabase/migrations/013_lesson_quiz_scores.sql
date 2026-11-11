-- The Quiz leaderboard also counts correct answers in the course's lesson quizzes, checked against the real answers.
create table if not exists public.lesson_keys (lesson text not null, q smallint not null, answer smallint not null, primary key (lesson, q));
alter table public.lesson_keys enable row level security;  -- no policies: nobody can read the answers through the API
insert into public.lesson_keys (lesson, q, answer) values
  ('l01', 0, 1),
  ('l01', 1, 3),
  ('l01', 2, 3),
  ('l02', 0, 2),
  ('l02', 1, 1),
  ('l02', 2, 3),
  ('l03', 0, 3),
  ('l03', 1, 1),
  ('l03', 2, 2),
  ('l04', 0, 1),
  ('l04', 1, 2),
  ('l04', 2, 3),
  ('l05', 0, 1),
  ('l05', 1, 3),
  ('l05', 2, 0),
  ('l06', 0, 1),
  ('l06', 1, 2),
  ('l06', 2, 0),
  ('l07', 0, 0),
  ('l07', 1, 1),
  ('l07', 2, 3),
  ('l08', 0, 1),
  ('l08', 1, 2),
  ('l08', 2, 0),
  ('l09', 0, 1),
  ('l09', 1, 2),
  ('l09', 2, 3),
  ('l10', 0, 1),
  ('l10', 1, 3),
  ('l10', 2, 2),
  ('l11', 0, 1),
  ('l11', 1, 0),
  ('l11', 2, 3),
  ('l12', 0, 2),
  ('l12', 1, 0),
  ('l12', 2, 3),
  ('l13', 0, 1),
  ('l13', 1, 2),
  ('l13', 2, 0),
  ('l14', 0, 2),
  ('l14', 1, 0),
  ('l14', 2, 1),
  ('l15', 0, 3),
  ('l15', 1, 1),
  ('l15', 2, 0),
  ('l16', 0, 1),
  ('l16', 1, 2),
  ('l16', 2, 0),
  ('l17', 0, 2),
  ('l17', 1, 0),
  ('l17', 2, 1),
  ('l18', 0, 1),
  ('l18', 1, 2),
  ('l18', 2, 0),
  ('l19', 0, 3),
  ('l19', 1, 2),
  ('l19', 2, 0),
  ('l20', 0, 1),
  ('l20', 1, 2),
  ('l20', 2, 0),
  ('l21', 0, 0),
  ('l21', 1, 2),
  ('l21', 2, 1),
  ('l22', 0, 1),
  ('l22', 1, 3),
  ('l22', 2, 0),
  ('l23', 0, 1),
  ('l23', 1, 0),
  ('l23', 2, 2),
  ('l24', 0, 1),
  ('l24', 1, 2),
  ('l24', 2, 0)
on conflict (lesson, q) do update set answer = excluded.answer;

create or replace function public.refresh_quiz_score() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  update public.profiles p set quiz_correct = (
    select count(*) from jsonb_each(new.state) e(k, v)
    cross join lateral jsonb_each_text(v) a(q, pick)
    join public.quiz_keys qk on qk.day = substring(e.k from 6)::date and qk.q = a.q::smallint and qk.answer = a.pick::smallint
    where e.k ~ '^quiz:\d{4}-\d{2}-\d{2}$' and jsonb_typeof(v) = 'object' and a.q ~ '^\d+$' and a.pick ~ '^\d+$'
  ) + (
    -- plus correct answers in the Start here course quizzes
    select count(*) from jsonb_each(new.state) e(k, v)
    cross join lateral jsonb_each_text(coalesce(v->'quiz', '{}'::jsonb)) a(q, pick)
    join public.lesson_keys lk on lk.lesson = substring(e.k from 8) and lk.q = a.q::smallint and lk.answer = a.pick::smallint
    where e.k ~ '^lesson:l\d{2}$' and jsonb_typeof(v) = 'object' and a.q ~ '^\d+$' and a.pick ~ '^\d+$'
  ) where p.id = new.user_id;
  return new;
end $$;

update public.user_state set updated_at = now();  -- recount for everyone
