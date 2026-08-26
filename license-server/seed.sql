-- Plans mẫu — chạy sau schema.sql
insert into public.plans (name, max_tabs, features, price, duration_days, active) values
  ('Dùng thử', 3, 'game', 0, 7, true),
  ('Cơ bản 10 tab', 10, 'game', 200000, 30, true),
  ('Pro 20 tab', 20, 'game', 350000, 30, true),
  ('Vô hạn 50 tab', 50, 'game', 600000, 30, true)
on conflict (name) do nothing;