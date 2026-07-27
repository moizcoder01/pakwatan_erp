-- =====================================================================
-- PAKWATAN SECURITY ERP PORTAL — CHUNK 4: CLIENTS MANAGEMENT SCHEMA
-- Database: Supabase (PostgreSQL)
-- Run this in: Supabase Dashboard -> SQL Editor -> New Query
-- =====================================================================

-- 1. Create or ensure `public.clients` table exists with all Chunk 4 fields
create table if not exists public.clients (
    id                   uuid primary key default gen_random_uuid(),
    client_name          varchar(255) not null,
    company_name         varchar(255),
    contact_person       varchar(255),
    phone                varchar(50),
    email                varchar(255),
    address              text,
    contract_start       date,
    contract_end         date,
    monthly_billing_rate numeric(12,2) default 0.00,
    status               varchar(50) default 'Active' check (status in ('Active', 'Inactive', 'Terminated')),
    created_at           timestamptz not null default now()
);

-- 2. Migration block to alter existing table from earlier Phase 1 schema if needed
do $$
begin
    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='clients' and column_name='company_name') then
        alter table public.clients add column company_name varchar(255);
    end if;

    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='clients' and column_name='contract_start') then
        alter table public.clients add column contract_start date;
    end if;

    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='clients' and column_name='contract_end') then
        alter table public.clients add column contract_end date;
    end if;

    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='clients' and column_name='monthly_billing_rate') then
        alter table public.clients add column monthly_billing_rate numeric(12,2) default 0.00;
    end if;

    -- Ensure legacy columns are optional to prevent NOT NULL constraint errors
    if exists (select 1 from information_schema.columns where table_schema='public' and table_name='clients' and column_name='contract_start_date') then
        alter table public.clients alter column contract_start_date drop not null;
    end if;

    if exists (select 1 from information_schema.columns where table_schema='public' and table_name='clients' and column_name='rate_per_guard') then
        alter table public.clients alter column rate_per_guard drop not null;
    end if;
end $$;


-- 3. Copy legacy Phase 1 column values if present
do $$
begin
    if exists (select 1 from information_schema.columns where table_schema='public' and table_name='clients' and column_name='contract_start_date') then
        update public.clients set contract_start = contract_start_date where contract_start is null and contract_start_date is not null;
    end if;

    if exists (select 1 from information_schema.columns where table_schema='public' and table_name='clients' and column_name='contract_end_date') then
        update public.clients set contract_end = contract_end_date where contract_end is null and contract_end_date is not null;
    end if;

    if exists (select 1 from information_schema.columns where table_schema='public' and table_name='clients' and column_name='rate_per_guard') then
        update public.clients set monthly_billing_rate = rate_per_guard where (monthly_billing_rate is null or monthly_billing_rate = 0) and rate_per_guard is not null;
    end if;
end $$;

-- 4. Enable Row Level Security (RLS) & Policies
alter table public.clients enable row level security;

drop policy if exists "Enable read access for authenticated users" on public.clients;
drop policy if exists "Enable insert access for authenticated users" on public.clients;
drop policy if exists "Enable update access for authenticated users" on public.clients;
drop policy if exists "Enable all access for clients table" on public.clients;

create policy "Enable all access for clients table" on public.clients
    for all using (auth.role() = 'authenticated' or auth.role() = 'anon');

-- 5. Seed Data for local / testing environments
insert into public.clients (id, client_name, company_name, contact_person, phone, email, address, contract_start, contract_end, monthly_billing_rate, status)
values
  ('11111111-1111-1111-1111-111111111111', 'Bahria Town Head Office', 'Bahria Town (Pvt) Ltd', 'Mr. Tariq Mehmood', '0300-1234567', 'ops@bahriatown.example', 'Bahria Town Phase 7, Lahore', '2025-01-01', null, 450000.00, 'Active'),
  ('22222222-2222-2222-2222-222222222222', 'Fortress Stadium Mall', 'Fortress Retail Corp', 'Ms. Ayesha Khan', '0321-9876543', 'security@fortress.example', 'Fortress Stadium, Lahore Cantt', '2025-03-15', '2026-03-14', 320000.00, 'Active'),
  ('33333333-3333-3333-3333-333333333333', 'Al-Hafeez Textile Mills', 'Al-Hafeez Group', 'Mr. Usman Ali', '0333-4455667', 'admin@alhafeez.example', 'Industrial Estate, Faisalabad', '2024-11-01', null, 280000.00, 'Active')
on conflict (id) do nothing;

-- 6. Reload schema cache for PostgREST
notify pgrst, 'reload schema';
