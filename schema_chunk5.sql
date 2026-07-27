-- =====================================================================
-- PAKWATAN SECURITY ERP PORTAL — CHUNK 5: DEPLOYMENTS & SHIFTS SCHEMA
-- Database: Supabase (PostgreSQL)
-- Run this in: Supabase Dashboard -> SQL Editor -> New Query
-- =====================================================================

-- 1. Create or ensure `public.deployments` table exists with all Chunk 5 fields
create table if not exists public.deployments (
    id           uuid primary key default gen_random_uuid(),
    guard_id     uuid references public.guards(id) on delete cascade,
    client_id    uuid references public.clients(id) on delete cascade,
    shift_type   text default 'Day' check (shift_type in ('Day', 'Night')),
    start_date   date not null default current_date,
    end_date     date,
    status       text default 'Active' check (status in ('Active', 'Completed', 'Reassigned')),
    created_at   timestamptz not null default now()
);

-- 2. Migration block if column adjustments are needed
do $$
begin
    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='deployments' and column_name='shift_type') then
        alter table public.deployments add column shift_type text default 'Day' check (shift_type in ('Day', 'Night'));
    end if;
end $$;

-- 3. Row Level Security (RLS) & Policies
alter table public.deployments enable row level security;

drop policy if exists "Enable read access for authenticated users" on public.deployments;
drop policy if exists "Enable insert access for authenticated users" on public.deployments;
drop policy if exists "Enable update access for authenticated users" on public.deployments;
drop policy if exists "Enable all access for deployments table" on public.deployments;

create policy "Enable all access for deployments table" on public.deployments
    for all using (auth.role() = 'authenticated' or auth.role() = 'anon');

-- 4. Reload schema cache for PostgREST
notify pgrst, 'reload schema';
