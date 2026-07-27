-- =====================================================================
-- PAKWATAN SECURITY ERP PORTAL — PHASE 1
-- Database: Supabase (PostgreSQL)
-- Scope   : Guards & Waiting List | Attendance | Clients & Profitability
--           Financials & Advances | Weapons & Tactical Inventory
--           Client Complaints Ticket System
-- Run this entire file in: Supabase Dashboard -> SQL Editor -> New Query
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0. EXTENSIONS
-- ---------------------------------------------------------------------
create extension if not exists "pgcrypto";   -- gen_random_uuid()
create extension if not exists "pg_trgm";    -- fast fuzzy/partial text search (name, CNIC, etc.)

-- ---------------------------------------------------------------------
-- 0.1 SHARED TRIGGER FUNCTION: auto-update "updated_at" columns
-- ---------------------------------------------------------------------
create or replace function trigger_set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;


-- =====================================================================
-- 1. CLIENTS
-- =====================================================================
create table clients (
    id                   uuid primary key default gen_random_uuid(),
    client_name          text not null,
    contact_person       text,
    phone                text,
    email                text,
    city                 text,
    address              text,
    contract_start_date  date not null,
    contract_end_date    date,
    rate_per_guard       numeric(12,2) not null check (rate_per_guard >= 0), -- amount client PAYS per guard/month
    status               text not null default 'Active'
                         check (status in ('Active','Inactive','Terminated')),
    notes                text,
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now(),

    constraint chk_contract_dates check (contract_end_date is null or contract_end_date >= contract_start_date)
);

create trigger trg_clients_updated_at
before update on clients
for each row execute function trigger_set_updated_at();

create index idx_clients_name_trgm on clients using gin (client_name gin_trgm_ops);
create index idx_clients_status on clients (status);


-- =====================================================================
-- 2. GUARDS  (Active Guards Roster)
-- =====================================================================
create table guards (
    id                       uuid primary key default gen_random_uuid(),
    full_name                text not null,
    cnic                     varchar(15) not null unique,          -- format: 12345-1234567-1
    phone                    text not null,
    emergency_contact_name   text,
    emergency_contact_phone  text,
    photo_url                text,
    city                     text,
    address                  text,
    base_salary              numeric(12,2) not null check (base_salary >= 0),  -- what Pakwatan PAYS the guard
    assigned_client_id       uuid references clients(id) on delete set null,
    duty_status              text not null default 'Off Duty'
                              check (duty_status in ('On Duty','Off Duty','On Leave','Terminated')),
    date_joined              date not null default current_date,
    is_active                boolean not null default true,
    created_at               timestamptz not null default now(),
    updated_at               timestamptz not null default now(),

    constraint chk_guard_cnic_format check (cnic ~ '^[0-9]{5}-[0-9]{7}-[0-9]{1}$')
);

create trigger trg_guards_updated_at
before update on guards
for each row execute function trigger_set_updated_at();

create index idx_guards_cnic on guards (cnic);
create index idx_guards_name_trgm on guards using gin (full_name gin_trgm_ops);
create index idx_guards_client on guards (assigned_client_id);
create index idx_guards_duty_status on guards (duty_status);


-- =====================================================================
-- 3. WAITING LIST (Talent Pool — not yet hired)
-- =====================================================================
create table waiting_list (
    id                uuid primary key default gen_random_uuid(),
    full_name         text not null,
    cnic              varchar(15) unique,
    phone             text,
    city              text,
    address           text,
    experience_years  int check (experience_years >= 0),
    expected_salary   numeric(12,2),
    notes             text,
    applied_date      date not null default current_date,
    status            text not null default 'Pending'
                       check (status in ('Pending','Shortlisted','Rejected','Hired')),
    created_at        timestamptz not null default now(),

    constraint chk_waiting_cnic_format check (cnic is null or cnic ~ '^[0-9]{5}-[0-9]{7}-[0-9]{1}$')
);

create index idx_waiting_cnic on waiting_list (cnic);
create index idx_waiting_status on waiting_list (status);
create index idx_waiting_name_trgm on waiting_list using gin (full_name gin_trgm_ops);


-- =====================================================================
-- 4. ATTENDANCE & ABSENCE LOGS
-- =====================================================================
create table attendance (
    id                     uuid primary key default gen_random_uuid(),
    guard_id               uuid not null references guards(id) on delete cascade,
    attendance_date        date not null,
    status                 text not null
                            check (status in ('Present','On Duty','Absent','On Leave')),
    reason_for_absence     text,
    replacement_guard_id   uuid references guards(id) on delete set null,
    recorded_at            timestamptz not null default now(),

    unique (guard_id, attendance_date),

    -- Mandatory reason whenever the guard is Absent or On Leave
    constraint chk_reason_required check (
        status not in ('Absent','On Leave') or reason_for_absence is not null
    ),
    -- A guard cannot be their own replacement
    constraint chk_replacement_not_self check (
        replacement_guard_id is null or replacement_guard_id <> guard_id
    )
);

create index idx_attendance_guard on attendance (guard_id);
create index idx_attendance_date on attendance (attendance_date);
create index idx_attendance_status on attendance (status);


-- =====================================================================
-- 5. SALARY ADVANCES LEDGER
-- =====================================================================
create table salary_advances (
    id                       uuid primary key default gen_random_uuid(),
    guard_id                 uuid not null references guards(id) on delete cascade,
    amount                   numeric(12,2) not null check (amount > 0),
    reason                   text not null,
    advance_date             date not null default current_date,
    auto_deduct_next_month   boolean not null default true,
    is_deducted              boolean not null default false,
    deducted_on              date,
    created_at               timestamptz not null default now()
);

create index idx_advances_guard on salary_advances (guard_id);
create index idx_advances_pending on salary_advances (is_deducted) where is_deducted = false;


-- =====================================================================
-- 6. EXPENSES (Uniform / Gear Log)
-- =====================================================================
create table expenses (
    id             uuid primary key default gen_random_uuid(),
    guard_id       uuid references guards(id) on delete set null, -- null = bulk/general purchase
    item_type      text not null
                    check (item_type in ('Cap','Belt','Shoes','Uniform','Jacket','Torch','Other')),
    description    text,
    quantity       int not null default 1 check (quantity > 0),
    amount         numeric(12,2) not null check (amount >= 0),
    expense_date   date not null default current_date,
    created_at     timestamptz not null default now()
);

create index idx_expenses_guard on expenses (guard_id);
create index idx_expenses_date on expenses (expense_date);


-- =====================================================================
-- 7. WEAPONS & TACTICAL INVENTORY
-- =====================================================================
create table weapons (
    id                   uuid primary key default gen_random_uuid(),
    weapon_type          text not null,          -- e.g. 'Shotgun 12-Bore', 'Pistol 30-Bore'
    serial_number        text not null unique,
    license_number       text not null,
    city                 text,
    storage_address      text,
    assigned_guard_id    uuid references guards(id) on delete set null,
    status               text not null default 'In Storage'
                          check (status in ('In Storage','Assigned','Under Repair','Decommissioned')),
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now()
);

create trigger trg_weapons_updated_at
before update on weapons
for each row execute function trigger_set_updated_at();

create index idx_weapons_serial on weapons (serial_number);
create index idx_weapons_guard on weapons (assigned_guard_id);
create index idx_weapons_status on weapons (status);


-- =====================================================================
-- 7.1 WEAPON PURCHASES (Capital Expenditure Log)
-- =====================================================================
create table weapon_purchases (
    id                  uuid primary key default gen_random_uuid(),
    weapon_id           uuid references weapons(id) on delete set null,
    vendor_name         text,
    purchase_cost       numeric(12,2) not null check (purchase_cost >= 0),
    purchase_date       date not null default current_date,
    invoice_reference   text,
    notes               text,
    created_at          timestamptz not null default now()
);

create index idx_weapon_purchases_weapon on weapon_purchases (weapon_id);
create index idx_weapon_purchases_date on weapon_purchases (purchase_date);


-- =====================================================================
-- 8. CLIENT COMPLAINTS TICKET SYSTEM
-- =====================================================================
create table complaints (
    id                  uuid primary key default gen_random_uuid(),
    client_id           uuid not null references clients(id) on delete cascade,
    guard_id            uuid references guards(id) on delete set null,  -- optional, if about a specific guard
    complaint_details   text not null,
    logged_at           timestamptz not null default now(),
    resolution_status   text not null default 'Unresolved'
                         check (resolution_status in ('Resolved','Unresolved')),
    resolved_at         timestamptz,
    resolution_notes    text,

    constraint chk_resolved_at check (
        (resolution_status = 'Resolved' and resolved_at is not null)
        or (resolution_status = 'Unresolved')
    )
);

create index idx_complaints_client on complaints (client_id);
create index idx_complaints_status on complaints (resolution_status);


-- =====================================================================
-- 9. VIEWS — Fast Search & Profitability Reporting
-- =====================================================================

-- 9.1 Global quick-search view (name / CNIC / phone) across guards + waiting list
create or replace view v_personnel_search as
select
    'Active Guard'::text as source,
    id, full_name, cnic, phone, city, duty_status as status
from guards
union all
select
    'Waiting List'::text as source,
    id, full_name, cnic, phone, city, status
from waiting_list;

-- 9.2 Client profitability: revenue vs guard salary cost per client
create or replace view v_client_profitability as
select
    c.id                                as client_id,
    c.client_name,
    c.rate_per_guard,
    count(g.id) filter (where g.is_active)                     as active_guard_count,
    (c.rate_per_guard * count(g.id) filter (where g.is_active)) as total_monthly_revenue,
    coalesce(sum(g.base_salary) filter (where g.is_active), 0)  as total_monthly_guard_cost,
    (c.rate_per_guard * count(g.id) filter (where g.is_active))
        - coalesce(sum(g.base_salary) filter (where g.is_active), 0) as monthly_profit_margin
from clients c
left join guards g on g.assigned_client_id = c.id
group by c.id, c.client_name, c.rate_per_guard;

-- 9.3 Pending salary deductions due next payroll cycle
create or replace view v_pending_salary_deductions as
select sa.id, sa.guard_id, g.full_name, sa.amount, sa.advance_date, sa.reason
from salary_advances sa
join guards g on g.id = sa.guard_id
where sa.auto_deduct_next_month = true and sa.is_deducted = false;

-- 9.4 Weapons currently unassigned (in storage) — quick armory check
create or replace view v_unassigned_weapons as
select id, weapon_type, serial_number, license_number, city, storage_address
from weapons
where status = 'In Storage';

-- 9.5 Open (unresolved) complaints with client + guard context
create or replace view v_open_complaints as
select
    cp.id, cp.logged_at, c.client_name, g.full_name as guard_name,
    cp.complaint_details, cp.resolution_status
from complaints cp
join clients c on c.id = cp.client_id
left join guards g on g.id = cp.guard_id
where cp.resolution_status = 'Unresolved'
order by cp.logged_at desc;


-- =====================================================================
-- 10. MOCK SEED DATA (for local/dev testing only)
-- =====================================================================

-- 10.1 Clients
insert into clients (id, client_name, contact_person, phone, email, city, address, contract_start_date, contract_end_date, rate_per_guard, status)
values
 ('11111111-1111-1111-1111-111111111111','Bahria Town Head Office','Mr. Tariq Mehmood','0300-1234567','ops@bahriatown.example','Lahore','Bahria Town Phase 7, Lahore','2025-01-01', null, 45000.00,'Active'),
 ('22222222-2222-2222-2222-222222222222','Fortress Stadium Mall','Ms. Ayesha Khan','0321-9876543','security@fortress.example','Lahore','Fortress Stadium, Lahore Cantt','2025-03-15','2026-03-14', 42000.00,'Active'),
 ('33333333-3333-3333-3333-333333333333','Al-Hafeez Textile Mills','Mr. Usman Ali','0333-4455667','admin@alhafeez.example','Faisalabad','Industrial Estate, Faisalabad','2024-11-01', null, 38000.00,'Active');

-- 10.2 Guards
insert into guards (id, full_name, cnic, phone, emergency_contact_name, emergency_contact_phone, photo_url, city, address, base_salary, assigned_client_id, duty_status, date_joined, is_active)
values
 ('a1111111-0000-0000-0000-000000000001','Muhammad Imran','35201-1234567-1','0301-1112222','Bilal Imran','0301-9998888',null,'Lahore','Street 4, Model Town','32000.00','11111111-1111-1111-1111-111111111111','On Duty','2025-01-05', true),
 ('a1111111-0000-0000-0000-000000000002','Shahid Mehmood','35202-2345678-2','0302-2223333','Nasreen Bibi','0302-8887777',null,'Lahore','Township, Lahore','32000.00','11111111-1111-1111-1111-111111111111','On Duty','2025-01-10', true),
 ('a1111111-0000-0000-0000-000000000003','Kashif Raza','35203-3456789-3','0303-3334444','Farida Raza','0303-7776666',null,'Lahore','Johar Town, Lahore','30000.00','22222222-2222-2222-2222-222222222222','Off Duty','2025-04-01', true),
 ('a1111111-0000-0000-0000-000000000004','Zeeshan Ahmed','35204-4567890-4','0304-4445555','Saima Ahmed','0304-6665555',null,'Faisalabad','Peoples Colony, Faisalabad','29000.00','33333333-3333-3333-3333-333333333333','On Duty','2024-11-15', true),
 ('a1111111-0000-0000-0000-000000000005','Adnan Yousaf','35205-5678901-5','0305-5556666',null,null,null,'Lahore','Township, Lahore','30000.00', null,'Off Duty','2025-06-01', true);

-- 10.3 Waiting List
insert into waiting_list (full_name, cnic, phone, city, address, experience_years, expected_salary, notes, status)
values
 ('Rashid Latif','35206-6789012-6','0306-6667777','Lahore','Gulberg, Lahore', 3, 30000.00,'Ex-Army, good references','Shortlisted'),
 ('Naveed Iqbal','35207-7890123-7','0307-7778888','Lahore','Samanabad, Lahore', 1, 27000.00,'First-time applicant','Pending'),
 ('Waqas Sarwar','35208-8901234-8','0308-8889999','Faisalabad','D-Ground, Faisalabad', 5, 33000.00,'Prior mall security experience','Pending');

-- 10.4 Attendance
insert into attendance (guard_id, attendance_date, status, reason_for_absence, replacement_guard_id)
values
 ('a1111111-0000-0000-0000-000000000001','2026-07-25','On Duty', null, null),
 ('a1111111-0000-0000-0000-000000000002','2026-07-25','Absent','Fever, submitted medical slip','a1111111-0000-0000-0000-000000000005'),
 ('a1111111-0000-0000-0000-000000000003','2026-07-25','On Leave','Approved annual leave', null),
 ('a1111111-0000-0000-0000-000000000004','2026-07-25','Present', null, null),
 ('a1111111-0000-0000-0000-000000000001','2026-07-26','On Duty', null, null),
 ('a1111111-0000-0000-0000-000000000002','2026-07-26','Present', null, null);

-- 10.5 Salary Advances
insert into salary_advances (guard_id, amount, reason, advance_date, auto_deduct_next_month, is_deducted)
values
 ('a1111111-0000-0000-0000-000000000001', 5000.00,'Family medical emergency','2026-07-10', true, false),
 ('a1111111-0000-0000-0000-000000000004', 3000.00,'Advance for Eid expenses','2026-06-20', true, true);

-- 10.6 Expenses (Uniform / Gear)
insert into expenses (guard_id, item_type, description, quantity, amount, expense_date)
values
 ('a1111111-0000-0000-0000-000000000001','Uniform','Winter uniform set', 1, 3500.00,'2026-01-15'),
 ('a1111111-0000-0000-0000-000000000002','Shoes','Steel-toe patrol boots', 1, 2800.00,'2026-02-01'),
 (null,'Cap','Bulk order - 20 caps for new hires', 20, 6000.00,'2026-03-05');

-- 10.7 Weapons
insert into weapons (id, weapon_type, serial_number, license_number, city, storage_address, assigned_guard_id, status)
values
 ('w1111111-0000-0000-0000-000000000001','Shotgun 12-Bore','SG-2024-00123','LHR-LIC-4521','Lahore','Main Armory, Township Office','a1111111-0000-0000-0000-000000000001','Assigned'),
 ('w1111111-0000-0000-0000-000000000002','Pistol 30-Bore','PS-2024-00456','LHR-LIC-4522','Lahore','Main Armory, Township Office', null,'In Storage'),
 ('w1111111-0000-0000-0000-000000000003','Shotgun 12-Bore','SG-2024-00789','FSD-LIC-1187','Faisalabad','Faisalabad Branch Store','a1111111-0000-0000-0000-000000000004','Assigned');

-- 10.8 Weapon Purchases (CapEx Log)
insert into weapon_purchases (weapon_id, vendor_name, purchase_cost, purchase_date, invoice_reference, notes)
values
 ('w1111111-0000-0000-0000-000000000001','Askari Arms & Ammo','48000.00','2024-12-01','INV-8891','Initial procurement batch'),
 ('w1111111-0000-0000-0000-000000000002','Askari Arms & Ammo','35000.00','2024-12-01','INV-8892','Initial procurement batch'),
 ('w1111111-0000-0000-0000-000000000003','Punjab Arms Traders','47000.00','2025-01-10','INV-9010','Faisalabad branch expansion');

-- 10.9 Complaints
insert into complaints (client_id, guard_id, complaint_details, logged_at, resolution_status, resolved_at, resolution_notes)
values
 ('11111111-1111-1111-1111-111111111111','a1111111-0000-0000-0000-000000000002','Guard was 30 minutes late for morning shift.','2026-07-20 09:15:00+05', 'Resolved','2026-07-21 10:00:00+05','Verbal warning issued; guard counselled on punctuality.'),
 ('22222222-2222-2222-2222-222222222222', null,'Requesting an additional guard for weekend mall rush.','2026-07-24 14:00:00+05', 'Unresolved', null, null);

-- =====================================================================
-- END OF PHASE 1 SCHEMA
-- =====================================================================
