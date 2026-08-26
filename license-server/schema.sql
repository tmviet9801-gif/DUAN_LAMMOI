-- AutoTool License Server — Schema cho Supabase (PostgreSQL)
-- Chạy trong Supabase SQL Editor trước khi dùng server.
-- Service role key bypass RLS, nên RLS chỉ là lớp bảo vệ thêm.

create extension if not exists "pgcrypto";

create table if not exists public.plans (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  max_tabs int not null default 10,
  features text not null default 'game',
  price numeric not null default 0,
  duration_days int not null default 30,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.licenses (
  id uuid primary key default gen_random_uuid(),
  key text not null unique,
  machine_id text not null,
  customer_name text not null default '',
  contact text not null default '',
  plan_id uuid references public.plans(id) on delete set null,
  plan_name text not null default '',
  max_tabs int not null default 10,
  features text not null default 'game',
  price numeric not null default 0,
  status text not null default 'active',
  issued_at timestamptz not null default now(),
  expires_at timestamptz not null,
  last_active_at timestamptz,
  note text not null default '',
  created_at timestamptz not null default now()
);

create index if not exists idx_licenses_machine on public.licenses(machine_id);
create index if not exists idx_licenses_status on public.licenses(status);
create index if not exists idx_licenses_expires on public.licenses(expires_at);
create index if not exists idx_licenses_key on public.licenses(key);

create table if not exists public.license_events (
  id uuid primary key default gen_random_uuid(),
  license_id uuid references public.licenses(id) on delete cascade,
  action text not null,
  detail text not null default '',
  created_at timestamptz not null default now()
);

create index if not exists idx_events_license on public.license_events(license_id);

alter table public.plans enable row level security;
alter table public.licenses enable row level security;
alter table public.license_events enable row level security;