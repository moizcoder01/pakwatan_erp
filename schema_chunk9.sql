-- =====================================================================
-- PAKWATAN SECURITY ERP PORTAL — CHUNK 9: WEAPON LICENSE EXPIRY
-- Database: Supabase (PostgreSQL)
-- Run this in: Supabase Dashboard -> SQL Editor -> New Query
-- =====================================================================

-- 1. Add license expiry tracking to weapons inventory
do $$
begin
    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'weapons' and column_name = 'license_expiry'
    ) then
        alter table public.weapons add column license_expiry date;
    end if;
end $$;

-- 2. Index for dashboard compliance alerts and armory filters
create index if not exists idx_weapons_license_expiry on public.weapons (license_expiry);

-- 3. Reload PostgREST schema cache
notify pgrst, 'reload schema';
