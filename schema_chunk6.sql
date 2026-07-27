-- =====================================================================
-- PAKWATAN SECURITY ERP PORTAL — CHUNK 6: ATTENDANCE & PAYROLL SCHEMA
-- Database: Supabase (PostgreSQL)
-- Run this in: Supabase Dashboard -> SQL Editor -> New Query
-- =====================================================================

-- 1. Create `public.attendance` table
create table if not exists public.attendance (
    id             uuid primary key default gen_random_uuid(),
    guard_id       uuid references public.guards(id) on delete cascade,
    date           date not null default current_date,
    status         text default 'Present' check (status in ('Present', 'Absent', 'Leave')),
    overtime_hours numeric(4,2) default 0.00,
    created_at     timestamptz not null default now()
);

-- 2. Create `public.payroll` table
create table if not exists public.payroll (
    id             uuid primary key default gen_random_uuid(),
    guard_id       uuid references public.guards(id) on delete cascade,
    month          varchar(50) not null,                             -- e.g. "July 2026"
    base_salary    numeric(12,2) default 0.00,
    bonus          numeric(12,2) default 0.00,
    deductions     numeric(12,2) default 0.00,
    net_salary     numeric(12,2) default 0.00,
    status         text default 'Pending' check (status in ('Pending', 'Paid')),
    created_at     timestamptz not null default now()
);

-- 3. Migration checks if columns were added earlier
do $$
begin
    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='payroll' and column_name='net_salary') then
        alter table public.payroll add column net_salary numeric(12,2) default 0.00;
    end if;
end $$;

-- 4. Enable Row Level Security (RLS) & Policies for attendance
alter table public.attendance enable row level security;

drop policy if exists "Enable all access for attendance table" on public.attendance;
create policy "Enable all access for attendance table" on public.attendance
    for all using (auth.role() = 'authenticated' or auth.role() = 'anon');

-- 5. Enable Row Level Security (RLS) & Policies for payroll
alter table public.payroll enable row level security;

drop policy if exists "Enable all access for payroll table" on public.payroll;
create policy "Enable all access for payroll table" on public.payroll
    for all using (auth.role() = 'authenticated' or auth.role() = 'anon');

-- 6. Reload schema cache for PostgREST
notify pgrst, 'reload schema';
