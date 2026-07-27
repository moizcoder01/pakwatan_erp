-- =====================================================================
-- PAKWATAN SECURITY ERP PORTAL — CHUNK 6: ATTENDANCE & PAYROLL SCHEMA
-- Database: Supabase (PostgreSQL)
-- Run this in: Supabase Dashboard -> SQL Editor -> New Query
--
-- IMPORTANT: Phase 1 already created `public.attendance` with different
-- columns (attendance_date, no overtime_hours). CREATE TABLE IF NOT EXISTS
-- is a no-op on that table — this script ALTERs it safely for Chunk 6.
-- =====================================================================

-- 1. Ensure `public.attendance` exists (fresh projects only)
create table if not exists public.attendance (
    id             uuid primary key default gen_random_uuid(),
    guard_id       uuid not null references public.guards(id) on delete cascade,
    date           date not null default current_date,
    status         varchar(20) not null default 'Present',
    overtime_hours numeric(6,2) not null default 0.00,
    created_at     timestamptz not null default now()
);

-- 2. Migrate Phase-1 attendance columns → Chunk 6 shape
alter table public.attendance
    add column if not exists date date,
    add column if not exists overtime_hours numeric(6,2) default 0.00,
    add column if not exists created_at timestamptz default now(),
    add column if not exists attendance_date date,
    add column if not exists reason_for_absence text,
    add column if not exists recorded_at timestamptz default now();

-- Keep date / attendance_date in sync (Phase 1 used attendance_date)
update public.attendance
set date = coalesce(date, attendance_date, current_date)
where date is null;

update public.attendance
set attendance_date = coalesce(attendance_date, date, current_date)
where attendance_date is null;

update public.attendance
set overtime_hours = 0.00
where overtime_hours is null;

update public.attendance
set created_at = coalesce(created_at, recorded_at, now())
where created_at is null;

-- Soften Phase-1 constraints that block Chunk 6 inserts
alter table public.attendance drop constraint if exists chk_reason_required;
alter table public.attendance drop constraint if exists attendance_status_check;

-- Allow Chunk 6 statuses + keep Phase-1 legacy values
alter table public.attendance
    add constraint attendance_status_check
    check (status in ('Present', 'Absent', 'Leave', 'On Duty', 'On Leave'));

-- Map legacy "On Leave" → "Leave" for UI consistency (optional, non-destructive)
-- update public.attendance set status = 'Leave' where status = 'On Leave';

-- 3. Create `public.payroll` table
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

do $$
begin
    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'payroll' and column_name = 'net_salary'
    ) then
        alter table public.payroll add column net_salary numeric(12,2) not null default 0.00;
    end if;
end $$;

-- 4. Indexes
create index if not exists idx_attendance_guard_date on public.attendance (guard_id, date);
create index if not exists idx_attendance_date_col on public.attendance (date desc);
create index if not exists idx_payroll_guard_month on public.payroll (guard_id, month);
create index if not exists idx_payroll_status on public.payroll (status);
create index if not exists idx_payroll_created_at on public.payroll (created_at desc);

-- 5. RLS — attendance
alter table public.attendance enable row level security;

drop policy if exists "Enable all access for attendance table" on public.attendance;
drop policy if exists "Authenticated users can manage attendance" on public.attendance;

create policy "Authenticated users can manage attendance" on public.attendance
    for all
    using (auth.role() = 'authenticated' or auth.role() = 'anon')
    with check (auth.role() = 'authenticated' or auth.role() = 'anon');

-- 6. RLS — payroll
alter table public.payroll enable row level security;

drop policy if exists "Enable all access for payroll table" on public.payroll;
drop policy if exists "Authenticated users can manage payroll" on public.payroll;

create policy "Authenticated users can manage payroll" on public.payroll
    for all
    using (auth.role() = 'authenticated' or auth.role() = 'anon')
    with check (auth.role() = 'authenticated' or auth.role() = 'anon');

-- 7. Reload PostgREST schema cache (required after ALTER COLUMN)
notify pgrst, 'reload schema';
