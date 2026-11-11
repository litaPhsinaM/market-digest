-- One-time fresh start on the new money rules: cancels every paper order and resets every portfolio to $10,000,
-- then pays out rewards for lessons/quizzes/streaks already completed. Only test accounts existed when this was written.
-- Fresh start for everyone on the new rules (only test accounts exist so far), then pay out what they've already earned.
delete from public.orders;
update public.portfolios set cash = 10000, deposits = 10000;
delete from public.rewards;
update public.user_state set updated_at = now();   -- re-runs the reward trigger for lessons/quizzes/streaks already done
