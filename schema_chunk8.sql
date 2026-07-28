-- =====================================================================
-- PAKWATAN SECURITY ERP PORTAL — CHUNK 8: EXPENSE MANAGEMENT TRACKER
-- Database: Supabase (PostgreSQL)
-- Run this in: Supabase Dashboard -> SQL Editor -> New Query
-- =====================================================================

-- 1. Manual operational expense ledger
create table if not exists public.manual_expenses (
    id                uuid primary key default gen_random_uuid(),
    category          varchar(60) not null
                      check (category in (
                          'Rent',
                          'Utility Bills',
                          'Weapon Purchase',
                          'Uniforms & Tactical Gear',
                          'Legal/Licensing Fees',
                          'Office Maintenance',
                          'Fuel & Transport',
                          'Miscellaneous'
                      )),
    description       text not null,
    amount            numeric(12,2) not null default 0.00 check (amount >= 0),
    expense_date      date not null default current_date,
    payment_method    varchar(20) not null
                      check (payment_method in ('Cash', 'Bank Transfer')),
    reference_number  text,
    notes             text,
    created_at        timestamptz not null default now()
);

-- 2. Backfill-safe migration for older/stub environments
do $$
begin
    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'manual_expenses' and column_name = 'category'
    ) then
        alter table public.manual_expenses add column category varchar(60);
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'manual_expenses' and column_name = 'description'
    ) then
        alter table public.manual_expenses add column description text;
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'manual_expenses' and column_name = 'amount'
    ) then
        alter table public.manual_expenses add column amount numeric(12,2) not null default 0.00;
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'manual_expenses' and column_name = 'expense_date'
    ) then
        alter table public.manual_expenses add column expense_date date not null default current_date;
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'manual_expenses' and column_name = 'payment_method'
    ) then
        alter table public.manual_expenses add column payment_method varchar(20);
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'manual_expenses' and column_name = 'reference_number'
    ) then
        alter table public.manual_expenses add column reference_number text;
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'manual_expenses' and column_name = 'notes'
    ) then
        alter table public.manual_expenses add column notes text;
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'manual_expenses' and column_name = 'created_at'
    ) then
        alter table public.manual_expenses add column created_at timestamptz not null default now();
    end if;
end $$;

alter table public.manual_expenses drop constraint if exists manual_expenses_category_check;
alter table public.manual_expenses drop constraint if exists manual_expenses_payment_method_check;

alter table public.manual_expenses
    add constraint manual_expenses_category_check
    check (category in (
        'Rent',
        'Utility Bills',
        'Weapon Purchase',
        'Uniforms & Tactical Gear',
        'Legal/Licensing Fees',
        'Office Maintenance',
        'Fuel & Transport',
        'Miscellaneous'
    ));

alter table public.manual_expenses
    add constraint manual_expenses_payment_method_check
    check (payment_method in ('Cash', 'Bank Transfer'));

-- 3. Useful indexes
create index if not exists idx_manual_expenses_date on public.manual_expenses (expense_date desc);
create index if not exists idx_manual_expenses_category on public.manual_expenses (category);
create index if not exists idx_manual_expenses_payment_method on public.manual_expenses (payment_method);
create index if not exists idx_manual_expenses_created_at on public.manual_expenses (created_at desc);

-- 4. RLS
alter table public.manual_expenses enable row level security;

drop policy if exists "Enable all access for manual expenses table" on public.manual_expenses;
drop policy if exists "Authenticated users can manage manual expenses" on public.manual_expenses;

create policy "Authenticated users can manage manual expenses" on public.manual_expenses
    for all
    using (auth.role() = 'authenticated' or auth.role() = 'anon')
    with check (auth.role() = 'authenticated' or auth.role() = 'anon');

-- 5. Reload PostgREST schema cache
notify pgrst, 'reload schema';
