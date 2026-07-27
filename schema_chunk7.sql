-- =====================================================================
-- PAKWATAN SECURITY ERP PORTAL — CHUNK 7: INVOICING & FINANCE SCHEMA
-- Database: Supabase (PostgreSQL)
-- Run this in: Supabase Dashboard -> SQL Editor -> New Query
-- =====================================================================

-- 1. Create `public.invoices` table
create table if not exists public.invoices (
    id             uuid primary key default gen_random_uuid(),
    client_id      uuid not null references public.clients(id) on delete cascade,
    invoice_number varchar(50) not null unique,                     -- e.g. INV-2026-001
    amount         numeric(12,2) not null default 0.00 check (amount >= 0),
    issue_date     date not null default current_date,
    due_date       date not null,
    status         varchar(20) not null default 'Unpaid'
                   check (status in ('Paid', 'Unpaid', 'Overdue')),
    created_at     timestamptz not null default now()
);

-- 2. Safe column migrations if an older invoices stub exists
do $$
begin
    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'invoices' and column_name = 'invoice_number'
    ) then
        alter table public.invoices add column invoice_number varchar(50);
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'invoices' and column_name = 'amount'
    ) then
        alter table public.invoices add column amount numeric(12,2) not null default 0.00;
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'invoices' and column_name = 'issue_date'
    ) then
        alter table public.invoices add column issue_date date not null default current_date;
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'invoices' and column_name = 'due_date'
    ) then
        alter table public.invoices add column due_date date;
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'invoices' and column_name = 'status'
    ) then
        alter table public.invoices add column status varchar(20) not null default 'Unpaid';
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'invoices' and column_name = 'created_at'
    ) then
        alter table public.invoices add column created_at timestamptz not null default now();
    end if;
end $$;

-- 3. Indexes for listing / status filters / uniqueness lookups
create index if not exists idx_invoices_client_id on public.invoices (client_id);
create index if not exists idx_invoices_status on public.invoices (status);
create index if not exists idx_invoices_due_date on public.invoices (due_date);
create index if not exists idx_invoices_created_at on public.invoices (created_at desc);
create unique index if not exists idx_invoices_invoice_number on public.invoices (invoice_number);

-- 4. RLS for authenticated (and anon session-key) access — matches prior chunks
alter table public.invoices enable row level security;

drop policy if exists "Enable all access for invoices table" on public.invoices;
drop policy if exists "Authenticated users can manage invoices" on public.invoices;

create policy "Authenticated users can manage invoices" on public.invoices
    for all
    using (auth.role() = 'authenticated' or auth.role() = 'anon')
    with check (auth.role() = 'authenticated' or auth.role() = 'anon');

-- 5. Reload PostgREST schema cache
notify pgrst, 'reload schema';
