-- =====================================================================
-- PAKWATAN SECURITY ERP PORTAL — CHUNK 10: SALARY ADVANCE AUDIT TRAIL
-- Run in: Supabase Dashboard -> SQL Editor -> New Query
-- =====================================================================

-- Link an advance to the exact payroll run that deducted it (audit trail).
-- Without this, once is_deducted flips to true, there's no way to trace
-- *which* payslip absorbed a given advance.
alter table public.salary_advances
    add column if not exists deducted_in_payroll_id uuid references public.payroll(id) on delete set null;

-- Break out how much of a payslip's "deductions" total came specifically
-- from salary advances vs other deductions (fines, tax, etc.) — keeps
-- the payslip PDF/CSV transparent instead of lumping everything together.
alter table public.payroll
    add column if not exists advance_deduction numeric(12,2) not null default 0.00;

create index if not exists idx_advances_deducted_in_payroll
    on public.salary_advances (deducted_in_payroll_id);

notify pgrst, 'reload schema';