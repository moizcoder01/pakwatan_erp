-- =====================================================================
-- PAKWATAN SECURITY ERP — PHASE 2
-- Adds: role-based auth profile table + auto-provisioning trigger
--       + baseline Row Level Security
-- Run AFTER schema.sql (Phase 1), in Supabase SQL Editor.
--
-- IMPORTANT: This relies on Supabase's built-in `auth.users` table,
-- which already exists in every Supabase project — do NOT create it.
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- 1. PROFILES — one row per auth.users entry, carries the app role
-- ---------------------------------------------------------------------
create table if not exists profiles (
    id           uuid primary key references auth.users(id) on delete cascade,
    full_name    text not null,
    role         text not null default 'Ops' check (role in ('Admin','Ops','Client')),
    client_id    uuid references clients(id) on delete set null, -- set only when role = 'Client'
    is_active    boolean not null default true,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),

    constraint chk_client_role_has_client check (
        role <> 'Client' or client_id is not null
    )
);

create trigger trg_profiles_updated_at
before update on profiles
for each row execute function trigger_set_updated_at();

create index idx_profiles_role on profiles (role);
create index idx_profiles_client on profiles (client_id);

-- ---------------------------------------------------------------------
-- 2. AUTO-PROVISION A PROFILE ROW WHENEVER A NEW AUTH USER SIGNS UP
--    New users default to 'Ops' — an Admin promotes/reassigns roles
--    afterwards (see the manual promotion query at the bottom).
-- ---------------------------------------------------------------------
create or replace function handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, full_name, role)
  values (
    new.id,
    coalesce(new.raw_user_meta_data ->> 'full_name', new.email),
    'Ops'
  )
  on conflict (id) do nothing;
  return new;
end;
$$ language plpgsql security definer;

drop trigger if exists trg_on_auth_user_created on auth.users;
create trigger trg_on_auth_user_created
after insert on auth.users
for each row execute function handle_new_user();

-- ---------------------------------------------------------------------
-- 3. BASELINE ROW LEVEL SECURITY
--    (Guards/Clients/Complaints/Weapons keep using the Flask-layer role
--    checks in Phase 2 via the anon key. Full per-table RLS that scopes
--    Client-role rows at the DB layer is recommended hardening for
--    Phase 3, before any direct client-side Supabase calls are added.)
-- ---------------------------------------------------------------------
alter table profiles enable row level security;

create policy "Users can read their own profile"
on profiles for select
using (auth.uid() = id);

create policy "Admins can read every profile"
on profiles for select
using (
  exists (
    select 1 from profiles p
    where p.id = auth.uid() and p.role = 'Admin'
  )
);

create policy "Admins can update roles"
on profiles for update
using (
  exists (
    select 1 from profiles p
    where p.id = auth.uid() and p.role = 'Admin'
  )
);

-- ---------------------------------------------------------------------
-- 4. ONE-TIME MANUAL STEP — promote your first user to Admin
-- ---------------------------------------------------------------------
-- 1. Create a user: Supabase Dashboard -> Authentication -> Add user
--    (or let them sign up once a signup screen exists in a later phase).
-- 2. Run this once, with the real email:
--
--    update profiles set role = 'Admin'
--    where id = (select id from auth.users where email = 'admin@pakwatansecurity.com');
--
-- 3. To onboard a Client-role user (e.g. a client's ops contact), also set
--    their client_id so the ERP scopes their view to that client only:
--
--    update profiles set role = 'Client', client_id = '11111111-1111-1111-1111-111111111111'
--    where id = (select id from auth.users where email = 'client-contact@example.com');
-- =====================================================================
