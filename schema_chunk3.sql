-- =====================================================================
-- PAKWATAN SECURITY ERP PORTAL — CHUNK 3: GUARDS & WAITING LIST SCHEMA
-- Database: Supabase (PostgreSQL)
-- Run this in: Supabase Dashboard -> SQL Editor -> New Query
-- =====================================================================

-- 1. Create or ensure `public.guards` table exists with all Chunk 3 fields
create table if not exists public.guards (
    id                   uuid primary key default gen_random_uuid(),
    guard_id             varchar(50) unique,                            -- e.g. PK-G-1001
    full_name            text not null,
    cnic                 varchar(20),                                    -- format: 12345-1234567-1
    phone                text,
    gender               text check (gender in ('Male', 'Female', 'Other')),
    emergency_contact    text,
    address              text,
    blood_group          varchar(10),                                   -- e.g. A+, O+, B-
    verification_status  text default 'Pending'
                         check (verification_status in ('Pending', 'Verified', 'Rejected')),
    status               text default 'Active'
                         check (status in ('Active', 'Inactive', 'Suspended', 'Waiting List')),
    assigned_client_id   uuid references public.clients(id) on delete set null,
    created_at           timestamptz not null default now()
);

-- 2. Alter existing table if columns were missing from earlier schema versions
do $$
begin
    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='guards' and column_name='guard_id') then
        alter table public.guards add column guard_id varchar(50) unique;
    end if;

    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='guards' and column_name='gender') then
        alter table public.guards add column gender text check (gender in ('Male', 'Female', 'Other'));
    end if;

    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='guards' and column_name='emergency_contact') then
        alter table public.guards add column emergency_contact text;
    end if;

    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='guards' and column_name='blood_group') then
        alter table public.guards add column blood_group varchar(10);
    end if;

    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='guards' and column_name='verification_status') then
        alter table public.guards add column verification_status text default 'Pending' check (verification_status in ('Pending', 'Verified', 'Rejected'));
    end if;

    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='guards' and column_name='status') then
        alter table public.guards add column status text default 'Active' check (status in ('Active', 'Inactive', 'Suspended', 'Waiting List'));
    end if;

    -- Ensure base_salary has a default value so registration won't fail if left blank
    alter table public.guards alter column base_salary drop not null;
    alter table public.guards alter column base_salary set default 0.00;
end $$;


-- 3. Row Level Security (RLS) Policies
alter table public.guards enable row level security;

-- Drop existing policies if re-running
drop policy if exists "Enable read access for authenticated users" on public.guards;
drop policy if exists "Enable insert access for authenticated users" on public.guards;
drop policy if exists "Enable update access for authenticated users" on public.guards;

-- Create policies for authenticated users
create policy "Enable read access for authenticated users" on public.guards
    for select using (auth.role() = 'authenticated' or auth.role() = 'anon');

create policy "Enable insert access for authenticated users" on public.guards
    for insert with check (auth.role() = 'authenticated' or auth.role() = 'anon');

create policy "Enable update access for authenticated users" on public.guards
    for update using (auth.role() = 'authenticated' or auth.role() = 'anon');

-- 4. Sample Seed Data for testing
insert into public.guards (guard_id, full_name, cnic, phone, gender, emergency_contact, address, blood_group, verification_status, status)
values
  ('PK-G-1001', 'Tariq Mehmood', '35201-1111111-1', '0300-1112233', 'Male', '0300-9998877', 'Model Town, Lahore', 'B+', 'Verified', 'Active'),
  ('PK-G-1002', 'Usman Ghani', '35202-2222222-2', '0301-2223344', 'Male', '0301-8887766', 'Gulberg, Lahore', 'O+', 'Verified', 'Active'),
  ('PK-G-1003', 'Rashid Minhas', '35203-3333333-3', '0302-3334455', 'Male', '0302-7776655', 'Township, Lahore', 'A+', 'Pending', 'Waiting List'),
  ('PK-G-1004', 'Saima Bibi', '35204-4444444-4', '0303-4445566', 'Female', '0303-6665544', 'Johar Town, Lahore', 'AB+', 'Pending', 'Waiting List')
-- 5. Force PostgREST schema cache reload
notify pgrst, 'reload schema';

