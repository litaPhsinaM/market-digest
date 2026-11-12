-- Answer keys for Learn unit 6, "How traders think (and why it's hard)" (lessons l25 to l29), so its quizzes count toward
-- lesson rewards and the Quiz leaderboard like the rest of the course. Safe to re-run.
insert into public.lesson_keys (lesson, q, answer) values
  ('l25', 0, 1), ('l25', 1, 1), ('l25', 2, 0),
  ('l26', 0, 1), ('l26', 1, 0), ('l26', 2, 2),
  ('l27', 0, 0), ('l27', 1, 1), ('l27', 2, 1),
  ('l28', 0, 0), ('l28', 1, 1), ('l28', 2, 1),
  ('l29', 0, 0), ('l29', 1, 1), ('l29', 2, 1)
on conflict (lesson, q) do update set answer = excluded.answer;
