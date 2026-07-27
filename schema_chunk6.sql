-- =====================================================================
-- PAKWATAN SECURITY ERP PORTAL — CHUNK 6: ATTENDANCE & PAYROLL SCHEMA
-- Database: Supabase (PostgreSQL)
-- Run this in: Supabase Dashboard -> SQL Editor -> New Query
-- =====================================================================

-- 1. Create `public.attendance` table
create table if not exists public.attendance (
    id             uuid primary key default gen_random_uuid(),
    guard_id       uuid not null references public.guards(id) on delete cascade,
    date           date not null default current_date,
    status         varchar(20) not null default 'Present'
                   check (status in ('Present', 'Absent', 'Leave')),
    overtime_hours numeric(6,2) not null default 0.00,
    created_at     timestamptz not null default now()
);

-- 2. Create `public.payroll` table
create table if not exists public.payroll (
    id             uuid primary key default gen_random_uuid(),
    guard_id       uuid not null references public.guards(id) on delete cascade,
    month          varchar(50) not null,                             -- e.g. "July 2026"
    base_salary    numeric(12,2) not null default 0.00,
    bonus          numeric(12,2) not null default 0.00,
    deductions     numeric(12,2) not null default 0.00,
    net_salary     numeric(12,2) not null default 0.00,
    status         varchar(20) not null default 'Pending'
                   check (status in ('Pending', 'Paid')),
    created_at     timestamptz not null default now()
);

-- 3. Helpful indexes for ledger & daily attendance lookups
create index if not exists idx_attendance_guard_date on public.attendance (guard_id, date);
create index if not exists idx_attendance_date on public.attendance (date desc);
create index if not exists idx_payroll_guard_month on public.payroll (guard_id, month);
create index if not exists idx_payroll_status on public.payroll (status);
create index if not exists idx_payroll_created_at on public.payroll (created_at desc);

-- 4. Migration checks if columns were added earlier
do $$
begin
    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'payroll' and column_name = 'net_salary'
    ) then
        alter table public.payroll add column net_salary numeric(12,2) not null default 0.00;
    end if;
end $$;

-- 5. Enable Row Level Security (RLS) & Policies for attendance
alter table public.attendance enable row level security;

drop policy if exists "Enable all access for attendance table" on public.attendance;
drop policy if exists "Authenticated users can manage attendance" on public.attendance;

create policy "Authenticated users can manage attendance" on public.attendance
    for all
    using (auth.role() = 'authenticated' or auth.role() = 'anon')
    with check (auth.role() = 'authenticated' or auth.role() = 'anon');

-- 6. Enable Row Level Security (RLS) & Policies for payroll
alter table public.payroll enable row level security;

drop policy if exists "Enable all access for payroll table" on public.payroll;
drop policy if exists "Authenticated users can manage payroll" on public.payroll;

create policy "Authenticated users can manage payroll" on public.payroll
    for all
    using (auth.role() = 'authenticated' or auth.role() = 'anon')
    with check (auth.role() = 'authenticated' or auth.role() = 'anon');

-- 7. Reload schema cache for PostgREST
notify pgrst, 'reload schema';
