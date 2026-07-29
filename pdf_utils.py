"""
pdf_utils.py
------------
Shared server-side PDF generation for exportable ledgers (Payroll,
Invoices, etc). Built on reportlab (pure-Python, no native system
libraries) so it runs cleanly on Vercel's @vercel/python serverless
runtime — unlike weasyprint, which needs Cairo/Pango/GDK-Pixbuf that
aren't available there.
"""

from io import BytesIO
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

BRAND_AMBER = colors.HexColor("#e8a33d")
BRAND_DARK = colors.HexColor("#181c24")
BRAND_TEXT = colors.HexColor("#12151b")
ROW_ALT = colors.HexColor("#f4f4f4")


def build_ledger_pdf(title, subtitle, columns, rows, generated_by=None):
    """
    Render a simple, professional tabular PDF report.

    columns: list of header strings
    rows:    list of row lists/tuples, values already formatted as display
              strings (e.g. "Rs. 30,000.00")

    Returns a BytesIO buffer positioned at 0, ready to stream as a Flask
    Response with mimetype='application/pdf'.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        topMargin=18 * mm, bottomMargin=16 * mm,
        leftMargin=14 * mm, rightMargin=14 * mm,
        title=title,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("PWTitle", parent=styles["Heading1"], fontSize=17, textColor=BRAND_TEXT, spaceAfter=2)
    section_style = ParagraphStyle("PWSection", parent=styles["Heading2"], fontSize=12.5, textColor=BRAND_AMBER)
    subtitle_style = ParagraphStyle("PWSubtitle", parent=styles["Normal"], fontSize=9.5, textColor=colors.HexColor("#555a63"))
    meta_style = ParagraphStyle("PWMeta", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#8a8f99"), spaceBefore=4)

    elements = [
        Paragraph("PAKWATAN SECURITY", title_style),
        Paragraph(title, section_style),
        Paragraph(subtitle, subtitle_style),
        Paragraph(
            f"Generated {datetime.now().strftime('%d %b %Y, %I:%M %p')}"
            + (f" by {generated_by}" if generated_by else ""),
            meta_style,
        ),
        Spacer(1, 10),
    ]

    table_data = [columns] + [list(r) for r in rows]
    table = Table(table_data, repeatRows=1)

    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6d8dc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for row_index in range(1, len(table_data)):
        if row_index % 2 == 0:
            style_commands.append(("BACKGROUND", (0, row_index), (-1, row_index), ROW_ALT))
    table.setStyle(TableStyle(style_commands))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return buffer

def build_payslip_pdf(guard_name, guard_code, cnic, phone, month_label,
                       base_salary, bonus, deductions, net_salary, status,
                       pending_advances=None, generated_by=None):
    """
    Formal, single-page payslip for one guard / one payroll month —
    company header, employee & period details, itemized earnings and
    deductions, net payable highlight, and signature lines.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=20 * mm, bottomMargin=20 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm,
        title=f"Payslip - {guard_name} - {month_label}",
    )

    styles = getSampleStyleSheet()
    company_style = ParagraphStyle("PWCompany", parent=styles["Heading1"], fontSize=18, textColor=BRAND_TEXT)
    tagline_style = ParagraphStyle("PWTagline", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#8a8f99"), spaceAfter=10)
    doc_title_style = ParagraphStyle("PWDocTitle", parent=styles["Heading2"], fontSize=13, textColor=BRAND_AMBER, spaceAfter=12)
    label_style = ParagraphStyle("PWLabel", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#555a63"))

    elements = [
        Paragraph("PAKWATAN SECURITY", company_style),
        Paragraph("Guard Force Deployment &amp; Security Services", tagline_style),
        Paragraph(f"Salary Payslip — {month_label}", doc_title_style),
    ]

    emp_data = [
        ["Guard Name:", guard_name, "Guard ID:", guard_code],
        ["CNIC:", cnic, "Phone:", phone],
        ["Pay Period:", month_label, "Payment Status:", status],
    ]
    emp_table = Table(emp_data, colWidths=[28 * mm, 62 * mm, 28 * mm, 52 * mm])
    emp_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#8a8f99")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#8a8f99")),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#d6d8dc")),
    ]))
    elements += [emp_table, Spacer(1, 16)]

    advances_total = sum(float(a.get("amount") or 0) for a in (pending_advances or []))
    earnings_data = [
        ["Earnings", "Amount (PKR)", "Deductions", "Amount (PKR)"],
        ["Base Salary", f"{base_salary:,.2f}", "Advances / Other", f"{deductions:,.2f}"],
        ["Bonus / Overtime", f"{bonus:,.2f}", "", ""],
        ["", "", "", ""],
        ["Gross Earnings", f"{(base_salary + bonus):,.2f}", "Total Deductions", f"{deductions:,.2f}"],
    ]
    earn_table = Table(earnings_data, colWidths=[42.5 * mm] * 4)
    earn_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.HexColor("#3a4353")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6d8dc")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements += [earn_table, Spacer(1, 10)]

    if pending_advances:
        elements.append(Paragraph(
            f"Note: {len(pending_advances)} salary advance(s) totalling Rs. {advances_total:,.2f} "
            "remain unapplied on this guard's account and are not reflected above unless already "
            "included in the Deductions figure.",
            label_style,
        ))
        elements.append(Spacer(1, 10))

    net_table = Table([["NET PAYABLE", f"Rs. {net_salary:,.2f}"]], colWidths=[85 * mm, 85 * mm])
    net_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef7f5")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1c6b5c")),
        ("FONTSIZE", (0, 0), (-1, -1), 13),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#4fb6a6")),
    ]))
    elements += [net_table, Spacer(1, 40)]

    sig_data = [
        ["____________________________", "____________________________"],
        ["Authorized Signatory (Management)", "Employee Acknowledgement"],
    ]
    sig_table = Table(sig_data, colWidths=[85 * mm, 85 * mm])
    sig_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, 0), 11),
        ("FONTSIZE", (0, 1), (-1, 1), 8.5),
        ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#8a8f99")),
        ("TOPPADDING", (0, 1), (-1, 1), 4),
    ]))
    elements += [sig_table, Spacer(1, 16)]

    elements.append(Paragraph(
        f"Generated {datetime.now().strftime('%d %b %Y, %I:%M %p')}"
        + (f" by {generated_by}" if generated_by else "")
        + " · This is a system-generated payslip.",
        label_style,
    ))

    doc.build(elements)
    buffer.seek(0)
    return buffer