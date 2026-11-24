"""Generate the 12-Slide Apex Margin Advisor Executive Presentation Kit:
  1. `presentation_kit/Apex_Margin_Advisor_Executive_Presentation.pptx`
     Native 16:9 widescreen PowerPoint with embedded 1080p MP4 demo chapters, poster frames,
     companion screenshots, 9-view architecture diagrams, persona workflows, and speaker notes.
  2. `presentation_kit/Apex_Margin_Advisor_Executive_Deck.html`
     Standalone interactive widescreen HTML5 deck (`ArrowLeft` / `ArrowRight`) embedding all 5
     1080p H.264 MP4 demo videos directly inside Slides 5–9.

Usage:
    uv run python scripts/build_executive_deck.py
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "presentation_kit"
VID = KIT / "videos"
IMG = KIT / "screenshots"
OUT_PPTX = KIT / "Apex_Margin_Advisor_Executive_Presentation.pptx"
OUT_HTML = KIT / "Apex_Margin_Advisor_Executive_Deck.html"

# Executive Emerald / Royal / Navy Palette
NAVY = RGBColor(0x0B, 0x1F, 0x3A)
EMERALD = RGBColor(0x06, 0x5F, 0x46)
EMERALD_BG = RGBColor(0xEC, 0xFD, 0xF5)
ROYAL = RGBColor(0x1E, 0x3A, 0x8A)
ROYAL_BG = RGBColor(0xEF, 0xF6, 0xFF)
CRIMSON = RGBColor(0xB9, 0x1C, 0x1C)
CRIMSON_BG = RGBColor(0xFE, 0xF2, 0xF2)
AMBER = RGBColor(0xB4, 0x53, 0x09)
AMBER_BG = RGBColor(0xFE, 0xF3, 0xC7)
SLATE = RGBColor(0x47, 0x55, 0x69)
SLATE_BG = RGBColor(0xF1, 0xF5, 0xF9)
BORDER = RGBColor(0xCB, 0xD5, 0xE1)
BG = RGBColor(0xF8, 0xFA, 0xFC)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
MINT = RGBColor(0x6E, 0xE7, 0xB7)


def set_bg(slide, color: RGBColor) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_box(slide, x, y, w, h, fill_rgb=WHITE, line_rgb=BORDER, line_pt=1.0, radius=True):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    sh = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    if radius and len(sh.adjustments) > 0:
        sh.adjustments[0] = 0.04
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill_rgb
    if line_rgb is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line_rgb
        sh.line.width = Pt(line_pt)
    return sh


def add_text(slide, x, y, w, h, text, size=14, bold=False, color=NAVY, align=PP_ALIGN.LEFT):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Pt(4)
    tf.margin_top = tf.margin_bottom = Pt(2)
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = text.replace("`", "")
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    r.font.name = "Calibri"
    return tb


def add_bullets(slide, x, y, w, h, items: list[tuple[str, str]], size=11.8, space_after=6):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, (lead, rest) in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(space_after)
        r1 = p.add_run()
        r1.text = f"• {lead.replace('`', '')}: " if lead else "• "
        r1.font.size = Pt(size)
        r1.font.bold = True
        r1.font.color.rgb = NAVY
        r1.font.name = "Calibri"
        r2 = p.add_run()
        r2.text = rest.replace("`", "")
        r2.font.size = Pt(size)
        r2.font.bold = False
        r2.font.color.rgb = SLATE
        r2.font.name = "Calibri"
    return tb


def slide_header(slide, kicker: str, title: str, badge: str, num: int) -> None:
    set_bg(slide, BG)
    add_text(slide, 0.55, 0.30, 9.5, 0.28, kicker.upper(), size=10.5, bold=True, color=EMERALD)
    add_text(slide, 0.55, 0.55, 10.1, 0.54, title, size=22.0, bold=True, color=NAVY)
    b = add_box(slide, 10.75, 0.44, 2.02, 0.38, fill_rgb=ROYAL_BG, line_rgb=ROYAL, line_pt=0.8)
    p = b.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = badge
    r.font.size = Pt(9.6)
    r.font.bold = True
    r.font.color.rgb = ROYAL
    r.font.name = "Calibri"
    add_box(slide, 0.55, 1.15, 12.22, 0.02, fill_rgb=BORDER, line_rgb=None, radius=False)
    add_text(
        slide, 0.55, 7.12, 9.8, 0.25,
        "Apex Margin Advisor · TIC Portfolio Margin Intelligence, Multi-Persona RLS & Governed CAT Write-Back",
        size=9, color=SLATE,
    )
    add_text(slide, 11.5, 7.12, 1.25, 0.25, f"{num} / 12", size=9.5, bold=True, color=SLATE, align=PP_ALIGN.RIGHT)


def add_callout(slide, y: float, text: str) -> None:
    add_box(slide, 0.55, y, 12.22, 0.56, fill_rgb=EMERALD_BG, line_rgb=EMERALD, line_pt=1.2)
    add_text(slide, 0.72, y + 0.10, 11.9, 0.38, text, size=11.6, bold=True, color=NAVY)


def add_video_slide(
    prs, num: int, kicker: str, title: str, badge: str,
    mp4_name: str, poster_name: str, card_title: str,
    bullets: list[tuple[str, str]], thumb1: str, thumb2: str,
    accent: RGBColor, notes: str,
) -> None:
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    slide_header(sl, kicker, title, badge, num)
    add_box(sl, 0.53, 1.36, 7.58, 4.62, fill_rgb=NAVY, line_rgb=BORDER, line_pt=1.2)
    add_text(
        sl, 0.68, 1.42, 7.25, 0.28,
        f"▶  {mp4_name}  (Click video in slideshow mode to play 1080p clip)",
        size=9.8, bold=True, color=WHITE,
    )
    mp4_path = VID / mp4_name
    poster_path = IMG / poster_name
    if mp4_path.exists() and poster_path.exists():
        sl.shapes.add_movie(
            str(mp4_path),
            Inches(0.56), Inches(1.73), Inches(7.52), Inches(4.23),
            poster_frame_image=str(poster_path),
            mime_type="video/mp4",
        )
    elif poster_path.exists():
        sl.shapes.add_picture(str(poster_path), Inches(0.56), Inches(1.73), width=Inches(7.52))

    if (IMG / thumb1).exists():
        sl.shapes.add_picture(str(IMG / thumb1), Inches(0.55), Inches(6.06), width=Inches(3.68))
    if (IMG / thumb2).exists():
        sl.shapes.add_picture(str(IMG / thumb2), Inches(4.40), Inches(6.06), width=Inches(3.68))

    add_box(sl, 8.30, 1.36, 4.47, 5.62, fill_rgb=WHITE, line_rgb=accent, line_pt=1.5)
    add_box(sl, 8.30, 1.36, 4.47, 0.08, fill_rgb=accent, line_rgb=None, radius=False)
    add_text(sl, 8.48, 1.54, 4.1, 0.42, card_title, size=14.5, bold=True, color=NAVY)
    add_bullets(sl, 8.45, 2.02, 4.18, 4.82, bullets, size=11.5, space_after=8)
    sl.notes_slide.notes_text_frame.text = notes


def build_pptx() -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    # ------------------------------------------------------------------
    # SLIDE 1: HERO & TIC MARGIN GOVERNANCE STACK
    # ------------------------------------------------------------------
    s1 = prs.slides.add_slide(blank)
    set_bg(s1, NAVY)
    add_box(s1, 0.55, 0.50, 5.65, 0.36, fill_rgb=EMERALD, line_rgb=None)
    add_text(s1, 0.68, 0.54, 5.45, 0.28, "TIC PORTFOLIO MARGIN & EXCEPTION INTELLIGENCE", size=9.6, bold=True, color=WHITE)
    add_text(s1, 0.55, 1.02, 7.15, 1.40, "Apex Margin Advisor:\nManagement by Exception\n& Live CAT Write-Back", size=28.5, bold=True, color=WHITE)
    add_text(
        s1, 0.55, 2.58, 7.05, 1.32,
        "An executive conversational assistant for Testing, Inspection & Certification (TIC) portfolios. "
        "Autonomously isolates runaway burn, utilization gaps, and ERP ledger mismatches across 9 governed views — "
        "and lets BU Managers, PMs, and Contract Admins write field clarifications, N-1 instructions, task assignments, "
        "and leadership decisions directly back into the database.",
        size=13.5, color=RGBColor(0xE2, 0xE8, 0xF0),
    )

    hero_kpis = [
        ("20 Contracts · 10 BUs", "9 governed views across OWMS, EFL, GTE, CRC & CAT"),
        ("24/24 Verified Eval", "0.018 s deterministic baseline + LiteLLM support"),
        ("Live DB Write-Back", "4 CAT tables for notes, N-1 plans, tasks & decisions"),
    ]
    for i, (kv, kl) in enumerate(hero_kpis):
        bx = 0.55 + i * 2.38
        add_box(s1, bx, 4.22, 2.24, 1.50, fill_rgb=RGBColor(0x12, 0x2D, 0x52), line_rgb=EMERALD, line_pt=1.3)
        add_text(s1, bx + 0.12, 4.36, 2.0, 0.42, kv, size=14.2, bold=True, color=MINT)
        add_text(s1, bx + 0.12, 4.82, 2.0, 0.78, kl, size=10.0, color=WHITE)

    add_box(s1, 0.55, 6.02, 7.02, 0.68, fill_rgb=RGBColor(0x1E, 0x29, 0x3B), line_rgb=RGBColor(0xF5, 0x9E, 0x0B), line_pt=1.0)
    add_text(
        s1, 0.70, 6.14, 6.72, 0.44,
        "Synthetic TIC benchmark dataset — prototype for demonstration only. Fictional contracts, people, and figures.",
        size=10.5, bold=True, color=RGBColor(0xFD, 0xE6, 0x8A),
    )

    # Right Stack Diagram
    add_box(s1, 7.95, 0.50, 4.82, 6.44, fill_rgb=WHITE, line_rgb=EMERALD, line_pt=2.0)
    add_text(s1, 8.15, 0.66, 4.4, 0.32, "CLOSED-LOOP MARGIN INTELLIGENCE STACK", size=11.0, bold=True, color=EMERALD, align=PP_ALIGN.CENTER)
    add_box(s1, 8.20, 1.06, 4.32, 1.18, fill_rgb=ROYAL_BG, line_rgb=ROYAL, line_pt=1.2)
    add_text(s1, 8.32, 1.12, 4.1, 0.24, "INTERACTIVE UX · 3 PERSONAS · 8 SLASH COMMANDS", size=8.8, bold=True, color=ROYAL)
    add_box(s1, 8.32, 1.41, 2.02, 0.68, fill_rgb=ROYAL, line_rgb=None)
    add_text(s1, 8.36, 1.48, 1.94, 0.56, "Chat + Inline Write-Back\nException Triage Hub", size=9.2, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    add_box(s1, 10.40, 1.41, 2.00, 0.68, fill_rgb=WHITE, line_rgb=ROYAL, line_pt=1.0)
    add_text(s1, 10.44, 1.48, 1.92, 0.56, "Weekly/Monthly Plan\n9-View Data Catalog", size=9.2, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
    add_text(s1, 8.20, 2.34, 4.32, 0.26, "─── GOVERNED SEMANTIC & WRITE-BACK ENGINE ───", size=8.8, bold=True, color=EMERALD, align=PP_ALIGN.CENTER)
    layers = [
        ("14 Governed MCP Tools & Guardrails", "Zero LLM math · Special Purpose N/A · RLS & RBAC", EMERALD_BG, EMERALD),
        ("Persistent CAT Write-Back DB (4 Tables)", "Comments · N-1 Action Plans · Tasks · Leader Decisions", AMBER_BG, AMBER),
        ("9 Governed Relational Views (vwm.*)", "Strict LEFT JOINs · Trimmed EFL keys · $120k Overhead", ROYAL_BG, ROYAL),
        ("5 TIC Modules (VWM / VDM Mapped)", "OWMS (CORE) · EFL (JDE) · GTE · CRC · CAT (SharePoint)", SLATE_BG, SLATE),
    ]
    for idx_l, (lt, ld, lbg, lbd) in enumerate(layers):
        ly = 2.68 + idx_l * 1.00
        add_box(s1, 8.20, ly, 4.32, 0.86, fill_rgb=lbg, line_rgb=lbd, line_pt=1.1)
        add_text(s1, 8.34, ly + 0.08, 4.05, 0.28, lt, size=10.3, bold=True, color=NAVY)
        add_text(s1, 8.34, ly + 0.38, 4.05, 0.38, ld, size=9.3, color=SLATE)
    s1.notes_slide.notes_text_frame.text = (
        "Introduce Apex Margin Advisor as the third sibling in our governed conversational BI suite alongside IRIS (Finance) and CORE Pulse (Adoption), "
        "now extending read-only analytics into closed-loop Management by Exception with structured CAT database write-back."
    )

    # ------------------------------------------------------------------
    # SLIDE 2: WHY TIC PORTFOLIO MARGINS ERODE
    # ------------------------------------------------------------------
    s2 = prs.slides.add_slide(blank)
    slide_header(s2, "Executive Context", "Why TIC Contract Margins Erode Before Leaders Can Intervene", "Problem → Solution", 2)
    traps = [
        ("1. Manual Auditing of Healthy Contracts", "Regional leaders waste hours scanning spreadsheets across dozens of healthy contracts. Apex Margin Advisor ranks only active exceptions on a 0–100 Priority Score (Materiality 45 + Urgency 25 + Deterioration 15 + Latency 15).", CRIMSON_BG, CRIMSON),
        ("2. Mixing Fixed-Scope & T&M Economics", "Fixed-Scope contracts bleed margin dollar-for-dollar when hours overrun (>115% alert, >150% accrual block), while T&M loses revenue when billable utilization drops below 80% or unapproved timesheets lag >7 days.", AMBER_BG, AMBER),
        ("3. ERP Link Gaps & Misleading Margin Ratios", "Naive reports print 100% margin on rebate contracts, -100% on internal calibration pools, or $0 labor on unmapped rate cards. Our engine enforces strict N/A rules, unvalued exposure alerts, and LEFT JOIN EFL checks.", ROYAL_BG, ROYAL),
        ("4. Read-Only Dashboards Lose Field Context", "A red variance cell never explains a 4-day winter storm, underestimated bid scope, or unassigned task — and cannot assign N-1 actions. Built-in CAT write-back closes the loop from insight to weekly/monthly execution.", EMERALD_BG, EMERALD),
    ]
    for i, (tt, td, bgc, bdc) in enumerate(traps):
        cx = 0.55 + (i % 2) * 6.22
        cy = 1.40 + (i // 2) * 2.15
        add_box(s2, cx, cy, 5.98, 1.92, fill_rgb=bgc, line_rgb=bdc, line_pt=1.4)
        add_text(s2, cx + 0.20, cy + 0.16, 5.58, 0.36, tt, size=14.8, bold=True, color=NAVY)
        add_text(s2, cx + 0.20, cy + 0.58, 5.58, 1.18, td, size=11.8, color=SLATE)
    add_callout(s2, 5.88, "Core Shift: Move from passive month-end P&L postmortems to proactive weekly exception triage with live N-1 accountability.")
    s2.notes_slide.notes_text_frame.text = (
        "Highlight the four pain points heard directly from TIC BU Directors and PMs — especially #4: operational context like severe weather, "
        "underestimated cost, and unassigned tasks must be captured right where issues are found and turned into next week's action plan."
    )

    # ------------------------------------------------------------------
    # SLIDE 3: 9-VIEW DATA ARCHITECTURE & VWM / VDM MAPPING
    # ------------------------------------------------------------------
    s3 = prs.slides.add_slide(blank)
    slide_header(s3, "9-View Relational Foundation", "Five TIC Modules Mapped to Enterprise VWM / VDM Sources", "9 Views + CAT", 3)
    modules = [
        ("OWMS", "Operations Work Mgmt", ["Dim_Contracts", "Dim_Services (orphan filter)", "Dim_Tasks (date check)", "CORE Project.* & Admin.*"], "project_uuid spine", EMERALD_BG, EMERALD),
        ("GTE", "Global Time & Expense", ["Fact_Timesheets", "Approved vs >7d Pending", "Billable pay flags", "CORE Timecard / F06116Z1"], "task_uuid & work_date", ROYAL_BG, ROYAL),
        ("CRC", "Commercial Rate Catalog", ["Dim_RateCatalog", "Cost ($52–$145/hr)", "Sell ($85–$275/hr)", "Missing rates = unvalued"], "discipline_id + year", SLATE_BG, SLATE),
        ("EFL", "Enterprise Financial GL", ["Fact_GeneralLedger", "Fact_SharedOverhead ($120k)", "Cat-1/2 rev, 7x, 8000/9000", "JDE F5201 / F0911 / F0901"], "LEFT JOIN trimmed ID", AMBER_BG, AMBER),
        ("CAT", "Collaborative Action DB", ["Fact_Exceptions (0–100)", "Fact_ActionLog (N-1 plan)", "Comments · Tasks · Decisions", "SharePoint / SQLite store"], "Business-key write-back", EMERALD_BG, ROYAL),
    ]
    for idx_m, (pill, sh_t, bul, foot, bgc, bdc) in enumerate(modules):
        sx = 0.55 + idx_m * 2.48
        add_box(s3, sx, 1.40, 2.34, 4.30, fill_rgb=WHITE, line_rgb=bdc, line_pt=1.5)
        add_box(s3, sx + 0.12, 1.54, 2.10, 0.32, fill_rgb=bgc, line_rgb=bdc, line_pt=0.8)
        add_text(s3, sx + 0.14, 1.57, 2.06, 0.26, pill, size=10.2, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
        add_text(s3, sx + 0.12, 1.96, 2.10, 0.34, sh_t, size=12.6, bold=True, color=NAVY)
        add_bullets(s3, sx + 0.08, 2.36, 2.18, 2.70, [("", b) for b in bul], size=10.2, space_after=5)
        add_text(s3, sx + 0.12, 5.26, 2.10, 0.30, foot, size=10.2, bold=True, color=EMERALD)
    add_callout(s3, 5.92, "VWM Join Hygiene: Strict LEFT JOINs surface unmatched EFL IDs and unmapped CRC rates openly — fixing legacy INNER JOIN silent drops.")
    s3.notes_slide.notes_text_frame.text = (
        "Point out how our synthetic 9-view architecture aligns directly with the real VWM Data Analyst Guide and unpacked Tableau Prep VDM FLOW, "
        "specifically correcting legacy INNER JOINs on F5201/F4211 to LEFT JOINs so unmatched records trigger auditable Setup Exceptions."
    )

    # ------------------------------------------------------------------
    # SLIDE 4: MULTI-PERSONA ADAPTATION & RBAC WRITE-BACK MATRIX
    # ------------------------------------------------------------------
    s4 = prs.slides.add_slide(blank)
    slide_header(s4, "Multi-Persona Governance", "One Assistant, Three Role-Tailored Workspaces & Write-Back RBAC", "3 Personas · RLS", 4)
    personas = [
        (
            "Operations Portfolio Director (BU Manager)",
            "All 10 Business Units · 20 Portfolio Contracts",
            [
                ("KPI Focus", "MTD revenue gap (-$308k), commercial provisional margin (59.9%), $120k Indirect Lab Burden → 52.2% Net Operating Margin."),
                ("Triage Lens", "Bottom-performing contracts, cross-BU capacity balancing, and portfolio-wide priority queue."),
                ("Write-Back Powers", "Full access: delegate N-1 weekly/monthly directives, assign tasks, add comments, AND record official Leadership Decisions (/decide)."),
            ],
            EMERALD, EMERALD_BG,
        ),
        (
            "Project Delivery Manager (PM)",
            "Assigned Delivery Scope · 6 Active Field/Lab Contracts",
            [
                ("KPI Focus", "Milestone completion, actual vs. planned hour burn (FS-AERO-104 at 168%), overdue tasks, and pending timesheets."),
                ("RLS Isolation", "Strictly scoped to Jordan Vance's 6 contracts; cross-portfolio contracts (FS-AUTO-305) and BU lab overhead return clean access refusals."),
                ("Write-Back Powers", "Log field context clarifications (e.g., severe storm delays, scope underestimation), update task assignments, and manage N-1 action items."),
            ],
            ROYAL, ROYAL_BG,
        ),
        (
            "Commercial Contract Administrator",
            "Cross-BU Commercial & EFL Reconciliation · All 20 Contracts",
            [
                ("KPI Focus", "Unbilled WIP ($7,020 >7d lag), Milestone-to-GL variance (-$31,500 on FS-INFRA-111), Cat-7x review lines, and orphaned fees."),
                ("Integrity Focus", "Surfaces FS-AUTO-305 (Disconnected from EFL), TM-RENEW-202 (48h unmapped DISC-SPECIALIST-9), and SP-REV/SP-COST N/A bridges."),
                ("Write-Back Powers", "Record CRC/EFL remediation commitments (/log), add commercial clarifications (/comment), and coordinate billing cleanups."),
            ],
            AMBER, AMBER_BG,
        ),
    ]
    for i, (pname, pscope, pbuls, acc, bgc) in enumerate(personas):
        px = 0.55 + i * 4.14
        add_box(s4, px, 1.40, 3.94, 4.34, fill_rgb=WHITE, line_rgb=acc, line_pt=1.6)
        add_box(s4, px, 1.40, 3.94, 0.10, fill_rgb=acc, line_rgb=None, radius=False)
        add_text(s4, px + 0.16, 1.56, 3.62, 0.52, pname, size=13.5, bold=True, color=NAVY)
        add_box(s4, px + 0.16, 2.12, 3.62, 0.42, fill_rgb=bgc, line_rgb=acc, line_pt=0.6)
        add_text(s4, px + 0.22, 2.18, 3.50, 0.30, pscope, size=9.6, bold=True, color=NAVY)
        add_bullets(s4, px + 0.14, 2.66, 3.66, 2.98, pbuls, size=10.6, space_after=6)
    add_callout(s4, 5.92, "VWM Section 7 Governance: Formal Leadership Decisions (/decide) are RBAC-gated exclusively to BU Managers; ERP actuals remain immutable.")
    s4.notes_slide.notes_text_frame.text = (
        "Walk through the three personas directly requested: BU Manager, Project Delivery Manager, and Commercial Contract Administrator, "
        "emphasizing how KPI cards, RLS row visibility, and write-back permissions adapt dynamically."
    )

    # ------------------------------------------------------------------
    # SLIDES 5–9: FIVE EMBEDDED 1080P LIVE DEMO CHAPTERS
    # ------------------------------------------------------------------
    add_video_slide(
        prs, 5,
        "Live Use Case · Chapter 1 (BU Manager)",
        "BU Manager Walkthrough: Portfolio Summary, Priority Triage & Runaway Burn",
        "1080p Demo 01",
        "01_bu_manager_summary_and_triage.mp4",
        "04_bu_exceptions_priority_queue.png",
        "BU Director Triage Flow",
        [
            ("Sign-In & Persona KPIs", "BU Manager Elena Vance signs in and immediately sees $1,297,980 MTD revenue vs. $1,606,100 target, 59.9% provisional / 52.2% net margin, and 9 active exceptions."),
            ("/summary Rollup", "Generates BU-level recognized vs. target revenue chart and Indirect Lab Burden ($120k) net operating margin bridge."),
            ("/exceptions Top-5 Queue", "Isolates EXC-101 on FS-AERO-104 at #1 (Priority Score 100.0/100) with stacked Materiality + Urgency + Deterioration + Latency breakdown."),
            ("/trace FS-AERO-104", "5-point audit proves 168.0% burn (420 vs. 250 hrs), blocked revenue accrual, and full 9-view SQL lineage."),
        ],
        "01_signin_gate.png",
        "05_trace_fs_aero_104_and_sql.png",
        EMERALD,
        "Play Chapter 1: Show how a Business Unit Director goes from portfolio-wide KPIs to the #1 margin leak (FS-AERO-104) in under 30 seconds.",
    )

    add_video_slide(
        prs, 6,
        "Live Use Case · Chapter 2 (Project Manager + Write-Back)",
        "PM Walkthrough: Scoped RLS & Field Weather Clarification Write-Back",
        "1080p Demo 02",
        "02_pm_persona_rls_and_weather_comment.mp4",
        "08_pm_weather_comment_writeback.png",
        "Field Context → Database",
        [
            ("Dynamic Persona RLS", "Switching to PM Jordan Vance immediately scopes KPI cards and queries to his 6 assigned contracts."),
            ("Fail-Closed Scope Isolation", "Attempting /trace FS-AUTO-305 (outside PM scope) returns a clean Row-Level Security refusal."),
            ("Real-World Weather Write-Back", "PM logs a severe North Sea winter storm delay (+40 hrs, $9,600 standby cost) on FS-OFFSHORE-108 directly via /comment — persisted to cat_contract_comments."),
            ("Instant Audit Integration", "Re-running /trace FS-OFFSHORE-108 immediately displays the storm root-cause note alongside live financial actuals."),
        ],
        "07_pm_rls_scope_refusal.png",
        "09_trace_surfaces_weather_note.png",
        ROYAL,
        "Play Chapter 2: Demonstrates the exact real-world scenario — a PM explaining why a contract overran due to severe weather and writing that clarification straight into the database from chat.",
    )

    add_video_slide(
        prs, 7,
        "Live Use Case · Chapter 3 (Closed-Loop Write-Back & Action Plan)",
        "N-1 Reportee Delegation, Task Assignment, Decisions & Action Plan Hub",
        "1080p Demo 03",
        "03_writeback_n1_action_plan_and_decisions.mp4",
        "11_action_plan_hub_weekly.png",
        "Closed-Loop Execution",
        [
            ("N-1 Directive in Chat", "BU Manager runs /assign FS-AERO-104 to Jordan Vance next week to freeze overtime and submit a client change order — persisted to fact_action_log."),
            ("Open Task Assignment", "Assigns overdue unassigned task TSK-0112-1 to EMC engineer T. Sato for Next Week (written to cat_task_assignments & Action Plan)."),
            ("Business Leader Decision", "Executes /decide FS-OFFSHORE-108 approving a 15% storm contingency buffer through Dec 5 (RBAC-enforced for BU Manager)."),
            ("Action Plan & Notes Hub", "Dedicated 4-tab workspace filters Next Week / Next Month deliverables, contract comments, task ownership, and decisions with live status updates."),
        ],
        "10_writeback_n1_and_decision_chat.png",
        "13_action_plan_leadership_decisions.png",
        AMBER,
        "Play Chapter 3: Showcases the complete write-back workflow — delegating instructions to N-1 reportees, assigning open tasks, approving a weather buffer, and tracking everything on the Action Plan & Notes board.",
    )

    add_video_slide(
        prs, 8,
        "Live Use Case · Chapter 4 (Commercial Contract Admin)",
        "Commercial Integrity: Missing CRC Rates, Unmatched EFL & $120k Overhead",
        "1080p Demo 04",
        "04_commercial_anomalies_and_overhead.mp4",
        "17_shared_overhead_waterfall.png",
        "Accounting & Ledger Rigor",
        [
            ("Missing CRC Rate Exposure", "/trace TM-RENEW-202 flags 48 approved hours under unmapped DISC-SPECIALIST-9 as unvalued exposure — never defaulted to $0 cost."),
            ("Unmatched EFL Link", "/trace FS-AUTO-305 preserves $185k operational progress while flagging Disconnected from Financial Ledger (unmatched_efl_record)."),
            ("Special Purpose N/A Rules", "SP-REV-901 ($45k rebate, $0 cost) and SP-COST-902 ($28.5k lab pool, $0 rev) strictly display N/A — never 100% or -100%."),
            ("$120k Shared Lab Overhead", "Portfolio & Overhead tab deducts Cat-8000 ($78k) + Cat-9000 ($42k) as Indirect Laboratory Burden across all 10 BUs."),
        ],
        "14_commercial_missing_crc_rate.png",
        "16_special_purpose_na_margin.png",
        EMERALD,
        "Play Chapter 4: Highlights financial integrity guarantees for Commercial Contract Administrators and Finance controllers.",
    )

    add_video_slide(
        prs, 9,
        "Live Walkthrough · Chapter 5 (Governance & Self-Service Catalog)",
        "Exception Triage Board, 9-View Data Catalog, Integrity Audit & Security",
        "1080p Demo 05",
        "05_data_catalog_integrity_and_guardrails.mp4",
        "19_catalog_9view_schema_vdm.png",
        "Full Transparency & Safety",
        [
            ("Exception Triage Command Center", "Interactive family filters, stacked 0–100 Priority Score chart, 1-click trace buttons, and inline CAT logging."),
            ("9-View Schema & VWM Mapping", "Documents exact join keys and enterprise CORE / FLEX / JDE table lineage right inside the app."),
            ("Live Master Data Integrity Audit", "Surfaces unmatched EFL IDs, missing CRC rates, quarantined orphaned fee line SVC-ORPHAN-999 ($18,500), and Cat-7x review rows."),
            ("Fail-Closed Security Guardrail", "Blocks prompt injection and mutating SQL (DROP TABLE / raw SELECT) while permitting only governed CAT write-back tools."),
        ],
        "18_exception_triage_board.png",
        "21_guardrail_injection_blocked.png",
        ROYAL,
        "Play Chapter 5: Closes the live walkthrough with Exception Triage, Data Catalog transparency, and prompt-injection defense.",
    )

    # ------------------------------------------------------------------
    # SLIDE 10: GOVERNED MCP SEMANTIC LAYER & SAFE WRITE-BACK ARCHITECTURE
    # ------------------------------------------------------------------
    s10 = prs.slides.add_slide(blank)
    slide_header(s10, "Technical Architecture", "Governed MCP Tool Layer & Safe Write-Back Isolation", "14 MCP Tools", 10)
    add_box(s10, 0.55, 1.40, 5.98, 4.35, fill_rgb=WHITE, line_rgb=EMERALD, line_pt=1.5)
    add_text(s10, 0.75, 1.56, 5.55, 0.36, "1. Read-Only Analytical Intelligence (10 Tools)", size=14.8, bold=True, color=NAVY)
    add_bullets(s10, 0.72, 2.00, 5.58, 3.60, [
        ("Zero AI Calculation", "Every revenue, margin, burn %, utilization %, and priority score is computed deterministically in SQL/Python over the 9 vwm.* views."),
        ("Anomaly & Numeric Guardrails", "Blocks hallucinated numbers and rejects any LLM text claiming 100% margin on SP-REV-901, -100% on SP-COST-902, or $0 on unmapped CRC rates."),
        ("Flexible LLM or Zero-LLM Runtime", "Instant 0.018 s deterministic rules engine built in, plus plug-and-play LiteLLM support for local Ollama (Apache 2.0), Gemini, or OpenAI."),
        ("Standard MCP Interface", "Exposes all 14 tools and 5 metadata resources over JSON-RPC 2.0 stdio so external agents can reuse the exact same governance."),
    ], size=11.3, space_after=7)

    add_box(s10, 6.80, 1.40, 5.97, 4.35, fill_rgb=WHITE, line_rgb=ROYAL, line_pt=1.5)
    add_text(s10, 7.00, 1.56, 5.55, 0.36, "2. Governed CAT Write-Back Isolation (4 Tools)", size=14.8, bold=True, color=NAVY)
    add_bullets(s10, 6.97, 2.00, 5.58, 3.60, [
        ("Zero ERP Mutation", "Write-backs never alter OWMS, GTE, CRC, or EFL actuals; all human context lives in 4 isolated CAT tables linked by business keys."),
        ("Multi-Modal Capture", "Users write back via slash commands (/comment, /assign, /decide, /log), plain English, the inline Chat drawer, or the Action Plan Hub."),
        ("RBAC & RLS Enforced on Writes", "PMs can comment/assign only within their 6 contracts; official Business Leader Decisions (/decide) require the BU Manager persona."),
        ("Refresh-Proof Audit History", "Because records link via contract_id, project_uuid, task_uuid, and exception_id, daily warehouse refreshes never orphan action plans."),
    ], size=11.3, space_after=7)
    add_callout(s10, 5.92, "Design Principle: Separate immutable financial truth (9 read-only views) from collaborative management accountability (4 CAT write-back tables).")
    s10.notes_slide.notes_text_frame.text = (
        "Reassure IT, Finance, and Audit stakeholders that giving chatbot users database write-back never compromises general ledger integrity: "
        "writes target strictly isolated CAT tables with RBAC, RLS, user attribution, and baseline financial snapshots."
    )

    # ------------------------------------------------------------------
    # SLIDE 11: MEASURED VERIFICATION & BENCHMARK RESULTS
    # ------------------------------------------------------------------
    s11 = prs.slides.add_slide(blank)
    slide_header(s11, "Measured Verification", "Automated Testing, Golden Evaluation & Portfolio Benchmarks", "100% Measured", 11)
    add_box(s11, 0.55, 1.40, 5.95, 4.35, fill_rgb=WHITE, line_rgb=EMERALD, line_pt=1.5)
    add_text(s11, 0.75, 1.56, 5.5, 0.36, "Automated Quality & Evaluation Results", size=14.8, bold=True, color=NAVY)
    add_bullets(s11, 0.72, 2.00, 5.55, 3.60, [
        ("24/24 Golden Evaluation (rules mode)", "100% Status Match (24/24), MCP Tool Match (24/24), Grounded Fact Match (24/24), and Guardrail Pass (24/24) at 0.018 s median / 0.038 s P95 latency."),
        ("19/19 Pytest & Headless UI Checks", "Verifies all 9 views, Priority Score math, all 5 injected TIC anomalies, all 4 CAT write-back tables, RBAC/RLS denials, JSON-RPC 2.0 MCP, and all 7 Streamlit pages."),
        ("Zero Silent Data Loss", "1 unmatched EFL contract, 48 unmapped CRC hours, 1 orphaned fee line ($18.5k), and 1 Cat-7x suspense line ($4.2k) all surfaced cleanly."),
        ("Full Audit Reproducibility", "Raw outputs stored in results/eval/eval_report.md and evaluation_summary.json."),
    ], size=11.2, space_after=7)

    add_box(s11, 6.75, 1.40, 6.02, 4.35, fill_rgb=WHITE, line_rgb=ROYAL, line_pt=1.5)
    add_text(s11, 6.95, 1.56, 5.6, 0.36, "Synthetic TIC Benchmark Portfolio (As-of Nov 20, 2026)", size=14.8, bold=True, color=NAVY)
    add_bullets(s11, 6.92, 2.00, 5.65, 3.60, [
        ("Portfolio Scale", "10 Business Units (BU-RENEW-01 .. BU-CONSUM-10), 20 contracts (12 FS, 6 T&M, 1 SP-REV-901, 1 SP-COST-902)."),
        ("MTD Commercial Revenue", "$1,297,980 recognized vs. $1,606,100 target (-$308,120 gap); 59.9% commercial provisional margin on complete-rate linked contracts."),
        ("Net Operating Margin Bridge", "After +$45,000 SP-REV-901, -$28,500 SP-COST-902, and -$120,000 Indirect Lab Burden → $700,743 (52.2% Net Operating Margin)."),
        ("Priority Queue & Compliance", "9 active exceptions led by FS-AERO-104 (100.0/100); 36h ($7,020) unbilled WIP >7d lag; TM-ENV-401 flagged at 64.0% utilization."),
    ], size=11.2, space_after=7)
    add_callout(s11, 5.92, "Proven Reusable Blueprint: Finance (IRIS) + Rollout Adoption (CORE Pulse) + Margin & Write-Back Triage (Apex Margin Advisor).")
    s11.notes_slide.notes_text_frame.text = (
        "Every number on this slide is 100% measured directly from our live DuckDB warehouse, pytest suite, and 24-question Golden Evaluation."
    )

    # ------------------------------------------------------------------
    # SLIDE 12: ENTERPRISE PRODUCTION LIFT ROADMAP
    # ------------------------------------------------------------------
    s12 = prs.slides.add_slide(blank)
    slide_header(s12, "Enterprise Production Path", "Connecting Live VWM Data (CORE / FLEX / JDE) & SharePoint CAT", "Roadmap", 12)
    phases = [
        ("Phase 1 · Ready Now", "Synthetic Benchmark & UX", "9 governed views, 14 MCP tools, 3 personas, 4-table CAT write-back, and verified 24/24 Golden Eval.", EMERALD_BG, EMERALD),
        ("Phase 2 · Data Bind", "Live CORE / FLEX / JDE Views", "Point vwm.* views to production SQL Server replicas (Project.*, F5201, F4211, F0911, F0901, F06116Z1) with LEFT JOIN rules.", ROYAL_BG, ROYAL),
        ("Phase 3 · Enterprise Auth", "SSO, RLS & SharePoint CAT", "Bind Microsoft Entra ID to SQL Server SESSION_CONTEXT RLS and connect CAT write-back to SharePoint VWM lists or enterprise SQL.", AMBER_BG, AMBER),
        ("Phase 4 · Scale & Alerts", "Automated Weekly Triage", "Schedule weekly exception scorecards, Teams/email digests for N-1 overdue actions, and Finance reconciliation workflows.", SLATE_BG, SLATE),
    ]
    for idx_r, (r_tag, r_dom, r_desc, bgc, bdc) in enumerate(phases):
        rx = 0.55 + idx_r * 3.10
        add_box(s12, rx, 1.40, 2.92, 2.55, fill_rgb=bgc, line_rgb=bdc, line_pt=1.4)
        add_text(s12, rx + 0.14, 1.54, 2.64, 0.28, r_tag, size=10.2, bold=True, color=bdc)
        add_text(s12, rx + 0.14, 1.86, 2.64, 0.36, r_dom, size=13.0, bold=True, color=NAVY)
        add_text(s12, rx + 0.14, 2.28, 2.64, 1.52, r_desc, size=10.8, color=SLATE)

    add_box(s12, 0.55, 4.18, 12.22, 1.55, fill_rgb=WHITE, line_rgb=NAVY, line_pt=1.3)
    add_text(s12, 0.75, 4.30, 11.8, 0.32, "3 Immediate Actions to Go Live on Pilot Business Unit (Zero UI Rewrite)", size=13.5, bold=True, color=NAVY)
    add_bullets(s12, 0.72, 4.65, 11.8, 1.0, [
        ("1. Upgrade VDM FLOW Joins to LEFT JOIN", "Replace legacy INNER JOINs on FLEX F5201/F4211 with LEFT JOINs so unmatched contracts surface instead of disappearing."),
        ("2. Confirm Effective-Dated Rate History & Cat-7x Rules", "Validate 2025–2026 discipline charge/sell rate history and Finance review policy for Category 7x suspense lines."),
        ("3. Bind CAT Write-Back Store", "Point ActionTrackerStore to enterprise SQL or SharePoint VWM lists so live comments and N-1 action plans sync across teams."),
    ], size=10.8, space_after=3)
    add_callout(s12, 5.92, "Ready for Pilot Rollout: Swap the data source connection string — the UI, MCP tools, guardrails, and CAT write-back workflow stay intact.")
    s12.notes_slide.notes_text_frame.text = (
        "Close with concrete, practical enterprise next steps directly tied to the real VWM Data Analyst Guide open points and VDM FLOW audit."
    )

    OUT_PPTX.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT_PPTX))
    print(f"Saved PowerPoint deck: {OUT_PPTX} ({OUT_PPTX.stat().st_size // 1024} KB)")


def build_html() -> None:
    html_doc = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Apex Margin Advisor — Executive Presentation &amp; Live Demo Deck</title>
<style>
  :root {
    --navy: #0B1F3A; --emerald: #065F46; --emerald-light: #ECFDF5;
    --royal: #1E3A8A; --royal-light: #EFF6FF;
    --amber: #B45309; --amber-light: #FEF3C7;
    --crimson: #B91C1C; --crimson-light: #FEF2F2;
    --slate: #475569; --border: #E2E8F0; --bg: #F8FAFC; --card: #FFFFFF;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body {
    width: 100%; height: 100%; overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif;
    background: #071324; color: var(--navy);
  }
  .deck-shell { width: 100vw; height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center; }
  .slide-viewport {
    position: relative; width: min(96vw, calc((100vh - 64px) * 16 / 9)); aspect-ratio: 16 / 9;
    background: var(--bg); border-radius: 16px; box-shadow: 0 28px 80px rgba(0,0,0,0.55); overflow: hidden;
  }
  .slide { position: absolute; inset: 0; display: none; flex-direction: column; padding: 32px 44px 24px; background: var(--bg); }
  .slide.active { display: flex; }
  .slide.hero { background: linear-gradient(135deg, #081A33 0%, #065F46 58%, #1E3A8A 100%); color: #FFF; }
  .s-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 15px; border-bottom: 2px solid var(--border); padding-bottom: 10px; }
  .kicker { font-size: 0.74rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--emerald); margin-bottom: 3px; }
  .s-title { font-size: clamp(1.26rem, 1.95vw, 1.82rem); font-weight: 800; color: var(--navy); line-height: 1.18; }
  .s-badge { background: var(--royal-light); color: var(--royal); font-size: 0.74rem; font-weight: 700; padding: 5px 12px; border-radius: 999px; white-space: nowrap; border: 1px solid #BFDBFE; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; flex: 1; min-height: 0; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; flex: 1; min-height: 0; }
  .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; flex: 1; min-height: 0; }
  .grid-5 { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; flex: 1; min-height: 0; }
  .grid-video { display: grid; grid-template-columns: 1.52fr 1fr; gap: 18px; flex: 1; min-height: 0; align-items: stretch; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; display: flex; flex-direction: column; gap: 7px; min-height: 0; }
  .card.emerald { border-top: 4px solid var(--emerald); }
  .card.royal { border-top: 4px solid var(--royal); }
  .card.amber { border-top: 4px solid var(--amber); }
  .card.crimson { border-top: 4px solid var(--crimson); background: #FFFDFD; }
  .card h3 { font-size: 0.98rem; font-weight: 700; color: var(--navy); }
  .card p, .card li { font-size: 0.82rem; line-height: 1.43; color: var(--slate); }
  .card ul { padding-left: 18px; display: flex; flex-direction: column; gap: 5px; }
  .card li strong { color: var(--navy); }
  .pill { display: inline-block; font-size: 0.72rem; font-weight: 700; padding: 3px 9px; border-radius: 6px; margin-bottom: 2px; }
  .pill.e { background: var(--emerald-light); color: var(--emerald); }
  .pill.r { background: var(--royal-light); color: var(--royal); }
  .pill.a { background: var(--amber-light); color: var(--amber); }
  code { background: #EFF6FF; color: #1E3A8A; padding: 1px 6px; border-radius: 5px; font-family: ui-monospace, Menlo, monospace; font-size: 0.86em; font-weight: 600; }
  .callout { background: linear-gradient(90deg, var(--emerald-light) 0%, var(--royal-light) 100%); border-left: 5px solid var(--emerald); border-radius: 10px; padding: 10px 15px; font-size: 0.84rem; color: var(--navy); font-weight: 600; margin-top: 12px; }
  .vid-col { display: flex; flex-direction: column; justify-content: center; gap: 10px; min-height: 0; }
  .vid-frame { background: #0B1628; border-radius: 12px; overflow: hidden; border: 2px solid #CBD5E1; box-shadow: 0 10px 28px rgba(11,31,58,0.12); }
  .vid-bar { background: #0F172A; color: #E2E8F0; font-size: 0.74rem; font-weight: 600; padding: 6px 12px; display: flex; justify-content: space-between; }
  .vid-frame video { width: 100%; aspect-ratio: 16 / 9; object-fit: contain; background: #0F172A; display: block; }
  .thumb-block { margin-top: auto; padding-top: 8px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 6px; }
  .thumb-label { font-size: 0.70rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--slate); }
  .thumb-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .thumb-row img { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; object-position: top left; border-radius: 7px; border: 1px solid #CBD5E1; background: #FFF; }
  .nav-bar { display: flex; align-items: center; gap: 14px; margin-top: 10px; color: #CBD5E1; font-size: 0.84rem; }
  .nav-bar button { background: #1E293B; color: #FFF; border: 1px solid #334155; border-radius: 8px; padding: 6px 14px; cursor: pointer; font-weight: 600; }
  .nav-bar button:hover { background: var(--emerald); border-color: var(--emerald); }
</style>
</head>
<body>
<div class="deck-shell">
  <div class="slide-viewport">

    <!-- Slide 1 -->
    <section class="slide hero active">
      <div style="display:grid; grid-template-columns: 1.35fr 1fr; gap: 24px; flex:1; align-items:center;">
        <div style="display:flex; flex-direction:column; gap:14px;">
          <span style="background:rgba(255,255,255,0.16); width:fit-content; padding:5px 12px; border-radius:999px; font-size:0.75rem; font-weight:700; letter-spacing:0.08em;">TIC PORTFOLIO MARGIN &amp; EXCEPTION INTELLIGENCE</span>
          <h1 style="font-size:clamp(1.85rem, 2.9vw, 2.65rem); font-weight:800; line-height:1.12;">Apex Margin Advisor: Management by Exception &amp; Live CAT Write-Back</h1>
          <p style="font-size:0.94rem; line-height:1.48; color:#E2E8F0;">Autonomously isolates runaway burn, utilization gaps, and ERP ledger mismatches across 9 governed views &mdash; and enables BU Managers, Project Managers, and Contract Admins to write field clarifications, N-1 instructions, task assignments, and leadership decisions directly back into the database.</p>
          <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:11px; margin-top:2px;">
            <div style="background:rgba(15,23,42,0.55); border:1px solid #6EE7B7; border-radius:10px; padding:11px;">
              <div style="font-size:1.15rem; font-weight:800; color:#6EE7B7;">20 Contracts &middot; 10 BUs</div>
              <div style="font-size:0.76rem; color:#E2E8F0; margin-top:4px;">9 governed views across OWMS, EFL, GTE, CRC &amp; CAT</div>
            </div>
            <div style="background:rgba(15,23,42,0.55); border:1px solid #6EE7B7; border-radius:10px; padding:11px;">
              <div style="font-size:1.15rem; font-weight:800; color:#6EE7B7;">24/24 Verified Eval</div>
              <div style="font-size:0.76rem; color:#E2E8F0; margin-top:4px;">0.018 s deterministic baseline + LiteLLM support</div>
            </div>
            <div style="background:rgba(15,23,42,0.55); border:1px solid #6EE7B7; border-radius:10px; padding:11px;">
              <div style="font-size:1.15rem; font-weight:800; color:#6EE7B7;">Live DB Write-Back</div>
              <div style="font-size:0.76rem; color:#E2E8F0; margin-top:4px;">4 CAT tables for notes, N-1 plans, tasks &amp; decisions</div>
            </div>
          </div>
          <div style="background:rgba(245,158,11,0.18); border:1px solid #FBBF24; border-radius:8px; padding:8px 12px; font-size:0.80rem; color:#FEF3C7;">
            <b>Synthetic TIC benchmark dataset &mdash; prototype for demonstration only.</b> Fictional contracts, people, and figures.
          </div>
        </div>
        <div class="card emerald" style="color:var(--navy); gap:9px;">
          <h3 style="color:var(--emerald); text-transform:uppercase; font-size:0.80rem; letter-spacing:0.08em;">Closed-Loop Margin Intelligence Stack</h3>
          <div style="background:var(--royal-light); border:1px solid var(--royal); border-radius:8px; padding:9px;">
            <div style="font-size:0.70rem; font-weight:800; color:var(--royal);">INTERACTIVE UX &middot; 3 PERSONAS &middot; 8 SLASH COMMANDS</div>
            <div style="font-size:0.82rem; font-weight:700; margin-top:3px;">Chat + Inline Write-Back &middot; Exception Triage &middot; Weekly/Monthly Plan</div>
          </div>
          <div style="text-align:center; font-size:0.70rem; font-weight:800; color:var(--emerald);">&mdash;&mdash; GOVERNED SEMANTIC &amp; WRITE-BACK ENGINE &mdash;&mdash;</div>
          <div style="background:#ECFDF5; border-left:4px solid #065F46; padding:7px 10px; border-radius:6px; font-size:0.79rem;"><b>14 Governed MCP Tools:</b> Zero LLM math &middot; Special Purpose N/A &middot; RLS/RBAC</div>
          <div style="background:#FEF3C7; border-left:4px solid #B45309; padding:7px 10px; border-radius:6px; font-size:0.79rem;"><b>Persistent CAT Write-Back DB:</b> Comments &middot; N-1 Plans &middot; Tasks &middot; Decisions</div>
          <div style="background:#EFF6FF; border-left:4px solid #1E3A8A; padding:7px 10px; border-radius:6px; font-size:0.79rem;"><b>9 Governed Views (<code>vwm.*</code>):</b> LEFT JOINs &middot; Trimmed EFL keys &middot; $120k Overhead</div>
          <div style="background:#F1F5F9; border-left:4px solid #475569; padding:7px 10px; border-radius:6px; font-size:0.79rem;"><b>5 TIC Modules (VWM/VDM):</b> OWMS (CORE) &middot; EFL (JDE) &middot; GTE &middot; CRC &middot; CAT</div>
        </div>
      </div>
    </section>

    <!-- Slide 2 -->
    <section class="slide">
      <div class="s-top"><div><div class="kicker">Executive Context</div><div class="s-title">Why TIC Contract Margins Erode Before Leaders Can Intervene</div></div><span class="s-badge">Problem &rarr; Solution</span></div>
      <div class="grid-2">
        <div class="card crimson"><h3>1. Manual Auditing of Healthy Contracts</h3><p>Regional leaders lose hours scanning spreadsheets across healthy contracts. Apex Margin Advisor ranks only active exceptions on a 0&ndash;100 Priority Score (Materiality 45 + Urgency 25 + Deterioration 15 + Latency 15).</p></div>
        <div class="card amber"><h3>2. Mixing Fixed-Scope &amp; T&amp;M Economics</h3><p>Fixed-Scope contracts bleed margin dollar-for-dollar when hours overrun (&gt;115% alert, &gt;150% accrual block), while T&amp;M leaks revenue when utilization drops below 80% or unapproved timesheets lag &gt;7 days.</p></div>
        <div class="card royal"><h3>3. ERP Link Gaps &amp; Misleading Margin Ratios</h3><p>Naive reports print 100% margin on rebate contracts, -100% on internal calibration pools, or $0 labor on unmapped rates. Our engine enforces strict <code>N/A</code> rules, unvalued exposure alerts, and LEFT JOIN EFL checks.</p></div>
        <div class="card emerald"><h3>4. Read-Only Dashboards Lose Field Context</h3><p>A red variance cell never explains a 4-day winter storm, underestimated bid scope, or unassigned task &mdash; and cannot delegate N-1 actions. Built-in CAT write-back closes the loop from insight to weekly/monthly execution.</p></div>
      </div>
      <div class="callout">Core Shift: Move from passive month-end P&amp;L postmortems to proactive weekly exception triage with live N-1 accountability.</div>
    </section>

    <!-- Slide 3 -->
    <section class="slide">
      <div class="s-top"><div><div class="kicker">9-View Relational Foundation</div><div class="s-title">Five TIC Modules Mapped to Enterprise VWM / VDM Sources</div></div><span class="s-badge">9 Views + CAT</span></div>
      <div class="grid-5">
        <div class="card emerald"><span class="pill e">OWMS</span><h3>Operations Work Mgmt</h3><ul><li><code>Dim_Contracts</code></li><li><code>Dim_Services</code> (orphan filter)</li><li><code>Dim_Tasks</code> (date check)</li><li>CORE <code>Project.*</code> &amp; <code>Admin.*</code></li></ul></div>
        <div class="card royal"><span class="pill r">GTE</span><h3>Global Time &amp; Expense</h3><ul><li><code>Fact_Timesheets</code></li><li>Approved vs &gt;7d Pending</li><li>Billable pay flags</li><li>CORE Timecard / <code>F06116Z1</code></li></ul></div>
        <div class="card"><span class="pill e">CRC</span><h3>Commercial Rate Catalog</h3><ul><li><code>Dim_RateCatalog</code></li><li>Cost ($52&ndash;$145/hr)</li><li>Sell ($85&ndash;$275/hr)</li><li>Missing rates = unvalued</li></ul></div>
        <div class="card amber"><span class="pill a">EFL</span><h3>Enterprise Financial GL</h3><ul><li><code>Fact_GeneralLedger</code></li><li><code>Fact_SharedOverhead</code> ($120k)</li><li>Cat-1/2 rev, 7x, 8000/9000</li><li>JDE <code>F5201</code> / <code>F0911</code> / <code>F0901</code></li></ul></div>
        <div class="card royal"><span class="pill r">CAT</span><h3>Collaborative Action DB</h3><ul><li><code>Fact_Exceptions</code> (0&ndash;100)</li><li><code>Fact_ActionLog</code> (N-1 plan)</li><li>Comments &middot; Tasks &middot; Decisions</li><li>SharePoint / SQLite store</li></ul></div>
      </div>
      <div class="callout">VWM Join Hygiene: Strict LEFT JOINs surface unmatched EFL IDs and unmapped CRC rates openly &mdash; fixing legacy INNER JOIN silent drops.</div>
    </section>

    <!-- Slide 4 -->
    <section class="slide">
      <div class="s-top"><div><div class="kicker">Multi-Persona Governance</div><div class="s-title">One Assistant, Three Role-Tailored Workspaces &amp; Write-Back RBAC</div></div><span class="s-badge">3 Personas &middot; RLS</span></div>
      <div class="grid-3">
        <div class="card emerald"><h3>Operations Portfolio Director (BU Manager)</h3><span class="pill e">All 10 BUs &middot; 20 Contracts</span><ul>
          <li><strong>KPI Focus:</strong> MTD revenue gap (-$308k), commercial provisional margin (59.9%), $120k Indirect Lab Burden &rarr; 52.2% Net Operating Margin.</li>
          <li><strong>Triage Lens:</strong> Bottom-performing contracts, cross-BU capacity balancing, and portfolio priority queue.</li>
          <li><strong>Write-Back Powers:</strong> Full access: delegate N-1 weekly/monthly directives, assign tasks, add comments, AND record official Leadership Decisions (<code>/decide</code>).</li>
        </ul></div>
        <div class="card royal"><h3>Project Delivery Manager (PM)</h3><span class="pill r">6 Assigned Field/Lab Contracts</span><ul>
          <li><strong>KPI Focus:</strong> Milestone completion, actual vs. planned hour burn (<code>FS-AERO-104</code> at 168%), overdue tasks, and pending timesheets.</li>
          <li><strong>RLS Isolation:</strong> Scoped strictly to Jordan Vance's 6 contracts; cross-portfolio contracts (<code>FS-AUTO-305</code>) and BU overhead return clean refusals.</li>
          <li><strong>Write-Back Powers:</strong> Log field clarifications (weather delays, underestimated scope), assign tasks, and update N-1 action items.</li>
        </ul></div>
        <div class="card amber"><h3>Commercial Contract Administrator</h3><span class="pill a">Cross-BU Ledger &middot; All 20</span><ul>
          <li><strong>KPI Focus:</strong> Unbilled WIP ($7,020 &gt;7d lag), Milestone-to-GL variance (-$31,500 on <code>FS-INFRA-111</code>), Cat-7x review lines, and orphaned fees.</li>
          <li><strong>Integrity Focus:</strong> Surfaces <code>FS-AUTO-305</code> (Disconnected from EFL), <code>TM-RENEW-202</code> (48h unmapped rate), and <code>SP-REV</code>/<code>SP-COST</code> N/A bridges.</li>
          <li><strong>Write-Back Powers:</strong> Record CRC/EFL remediation commitments (<code>/log</code>), add commercial clarifications (<code>/comment</code>), and track cleanups.</li>
        </ul></div>
      </div>
      <div class="callout">VWM Section 7 Governance: Formal Leadership Decisions (<code>/decide</code>) are RBAC-gated exclusively to BU Managers; ERP actuals remain immutable.</div>
    </section>

    <!-- Slide 5 -->
    <section class="slide">
      <div class="s-top"><div><div class="kicker">Live Use Case &middot; Chapter 1 (BU Manager)</div><div class="s-title">BU Manager Walkthrough: Portfolio Summary, Priority Triage &amp; Runaway Burn</div></div><span class="s-badge">1080p Demo 01</span></div>
      <div class="grid-video">
        <div class="vid-col">
          <div class="vid-frame"><div class="vid-bar"><span>&#9654; 01_bu_manager_summary_and_triage.mp4</span><span>1080p H.264</span></div><video controls preload="metadata" poster="screenshots/04_bu_exceptions_priority_queue.png" src="videos/01_bu_manager_summary_and_triage.mp4"></video></div>
        </div>
        <div class="card emerald"><h3>BU Director Triage Flow</h3><ul>
          <li><strong>Sign-In &amp; Persona KPIs:</strong> BU Manager Elena Vance sees <b>$1,297,980</b> MTD rev vs. $1,606,100 target, <b>59.9%</b> provisional / <b>52.2%</b> net margin, and 9 exceptions.</li>
          <li><strong><code>/summary</code> Rollup:</strong> BU recognized vs. target revenue chart and Indirect Lab Burden ($120k) net operating margin bridge.</li>
          <li><strong><code>/exceptions</code> Queue:</strong> Isolates <code>EXC-101</code> on <code>FS-AERO-104</code> at #1 (Priority Score <b>100.0/100</b>) with stacked score breakdown.</li>
          <li><strong><code>/trace FS-AERO-104</code>:</strong> 5-point audit proves <b>168.0%</b> burn (420 vs. 250 hrs), blocked revenue accrual, and 9-view SQL lineage.</li>
        </ul>
        <div class="thumb-block"><div class="thumb-label">Key Companion Screens</div><div class="thumb-row"><img src="screenshots/01_signin_gate.png" alt="Sign in" /><img src="screenshots/05_trace_fs_aero_104_and_sql.png" alt="Trace FS-AERO-104" /></div></div></div>
      </div>
    </section>

    <!-- Slide 6 -->
    <section class="slide">
      <div class="s-top"><div><div class="kicker">Live Use Case &middot; Chapter 2 (Project Manager + Write-Back)</div><div class="s-title">PM Walkthrough: Scoped RLS &amp; Field Weather Clarification Write-Back</div></div><span class="s-badge">1080p Demo 02</span></div>
      <div class="grid-video">
        <div class="vid-col">
          <div class="vid-frame"><div class="vid-bar"><span>&#9654; 02_pm_persona_rls_and_weather_comment.mp4</span><span>1080p H.264</span></div><video controls preload="metadata" poster="screenshots/08_pm_weather_comment_writeback.png" src="videos/02_pm_persona_rls_and_weather_comment.mp4"></video></div>
        </div>
        <div class="card royal"><h3>Field Context &rarr; Database</h3><ul>
          <li><strong>Dynamic Persona RLS:</strong> Switching to PM Jordan Vance immediately scopes KPI cards and queries to his <b>6 assigned contracts</b>.</li>
          <li><strong>Fail-Closed Isolation:</strong> Attempting <code>/trace FS-AUTO-305</code> (outside PM scope) returns a clean Row-Level Security refusal.</li>
          <li><strong>Real-World Weather Write-Back:</strong> PM logs a severe North Sea winter storm delay (+40 hrs, $9,600 standby cost) on <code>FS-OFFSHORE-108</code> directly via <code>/comment</code> &mdash; persisted to <code>cat_contract_comments</code>.</li>
          <li><strong>Instant Audit Integration:</strong> Re-running <code>/trace FS-OFFSHORE-108</code> surfaces the storm root-cause note right beside financial actuals.</li>
        </ul>
        <div class="thumb-block"><div class="thumb-label">Key Companion Screens</div><div class="thumb-row"><img src="screenshots/07_pm_rls_scope_refusal.png" alt="PM RLS refusal" /><img src="screenshots/09_trace_surfaces_weather_note.png" alt="Trace surfaces note" /></div></div></div>
      </div>
    </section>

    <!-- Slide 7 -->
    <section class="slide">
      <div class="s-top"><div><div class="kicker">Live Use Case &middot; Chapter 3 (Closed-Loop Write-Back &amp; Action Plan)</div><div class="s-title">N-1 Reportee Delegation, Task Assignment, Decisions &amp; Action Plan Hub</div></div><span class="s-badge">1080p Demo 03</span></div>
      <div class="grid-video">
        <div class="vid-col">
          <div class="vid-frame"><div class="vid-bar"><span>&#9654; 03_writeback_n1_action_plan_and_decisions.mp4</span><span>1080p H.264</span></div><video controls preload="metadata" poster="screenshots/11_action_plan_hub_weekly.png" src="videos/03_writeback_n1_action_plan_and_decisions.mp4"></video></div>
        </div>
        <div class="card amber"><h3>Closed-Loop Execution</h3><ul>
          <li><strong>N-1 Directive in Chat:</strong> BU Manager delegates <code>/assign FS-AERO-104 to Jordan Vance next week</code> to freeze overtime &amp; submit client change order.</li>
          <li><strong>Open Task Assignment:</strong> Assigns overdue unassigned task <code>TSK-0112-1</code> to <b>T. Sato</b> for Next Week (<code>cat_task_assignments</code> + Action Plan).</li>
          <li><strong>Business Leader Decision:</strong> Executes <code>/decide FS-OFFSHORE-108</code> approving a 15% storm contingency buffer through Dec 5 (BU Manager RBAC).</li>
          <li><strong>Action Plan &amp; Notes Hub:</strong> 4-tab workspace filters Next Week / Next Month deliverables, contract notes, tasks, and decisions with live status updates.</li>
        </ul>
        <div class="thumb-block"><div class="thumb-label">Key Companion Screens</div><div class="thumb-row"><img src="screenshots/10_writeback_n1_and_decision_chat.png" alt="N-1 chat writeback" /><img src="screenshots/13_action_plan_leadership_decisions.png" alt="Decisions hub" /></div></div></div>
      </div>
    </section>

    <!-- Slide 8 -->
    <section class="slide">
      <div class="s-top"><div><div class="kicker">Live Use Case &middot; Chapter 4 (Commercial Contract Admin)</div><div class="s-title">Commercial Integrity: Missing CRC Rates, Unmatched EFL &amp; $120k Overhead</div></div><span class="s-badge">1080p Demo 04</span></div>
      <div class="grid-video">
        <div class="vid-col">
          <div class="vid-frame"><div class="vid-bar"><span>&#9654; 04_commercial_anomalies_and_overhead.mp4</span><span>1080p H.264</span></div><video controls preload="metadata" poster="screenshots/17_shared_overhead_waterfall.png" src="videos/04_commercial_anomalies_and_overhead.mp4"></video></div>
        </div>
        <div class="card emerald"><h3>Accounting &amp; Ledger Rigor</h3><ul>
          <li><strong>Missing CRC Rate Exposure:</strong> <code>/trace TM-RENEW-202</code> flags <b>48 approved hours</b> under unmapped <code>DISC-SPECIALIST-9</code> as unvalued exposure &mdash; never $0.</li>
          <li><strong>Unmatched EFL Link:</strong> <code>/trace FS-AUTO-305</code> keeps $185k operational progress intact while flagging <code>Disconnected from Financial Ledger</code>.</li>
          <li><strong>Special Purpose N/A Rules:</strong> <code>SP-REV-901</code> ($45k rebate, $0 cost) and <code>SP-COST-902</code> ($28.5k lab pool, $0 rev) strictly display <code>N/A</code> &mdash; never 100% / -100%.</li>
          <li><strong>$120k Shared Lab Overhead:</strong> Portfolio &amp; Overhead tab deducts <code>Cat-8000</code> ($78k) + <code>Cat-9000</code> ($42k) as Indirect Lab Burden across all 10 BUs.</li>
        </ul>
        <div class="thumb-block"><div class="thumb-label">Key Companion Screens</div><div class="thumb-row"><img src="screenshots/14_commercial_missing_crc_rate.png" alt="Missing CRC rate" /><img src="screenshots/16_special_purpose_na_margin.png" alt="Special purpose N/A" /></div></div></div>
      </div>
    </section>

    <!-- Slide 9 -->
    <section class="slide">
      <div class="s-top"><div><div class="kicker">Live Walkthrough &middot; Chapter 5 (Governance &amp; Self-Service Catalog)</div><div class="s-title">Exception Triage Board, 9-View Data Catalog, Integrity Audit &amp; Security</div></div><span class="s-badge">1080p Demo 05</span></div>
      <div class="grid-video">
        <div class="vid-col">
          <div class="vid-frame"><div class="vid-bar"><span>&#9654; 05_data_catalog_integrity_and_guardrails.mp4</span><span>1080p H.264</span></div><video controls preload="metadata" poster="screenshots/19_catalog_9view_schema_vdm.png" src="videos/05_data_catalog_integrity_and_guardrails.mp4"></video></div>
        </div>
        <div class="card royal"><h3>Full Transparency &amp; Safety</h3><ul>
          <li><strong>Exception Triage Board:</strong> Interactive family filters, stacked 0&ndash;100 Priority Score chart, 1-click trace buttons, and inline CAT logging.</li>
          <li><strong>9-View Schema &amp; VWM Mapping:</strong> Documents exact join keys and enterprise CORE / FLEX / JDE table lineage right inside the app.</li>
          <li><strong>Live Integrity Audit:</strong> Surfaces unmatched EFL IDs, missing CRC rates, quarantined orphaned fee <code>SVC-ORPHAN-999</code> ($18,500), and Cat-7x review lines.</li>
          <li><strong>Fail-Closed Security Guardrail:</strong> Blocks prompt injection and mutating SQL (<code>DROP TABLE</code> / raw <code>SELECT</code>) while permitting only governed CAT write-back tools.</li>
        </ul>
        <div class="thumb-block"><div class="thumb-label">Key Companion Screens</div><div class="thumb-row"><img src="screenshots/18_exception_triage_board.png" alt="Triage board" /><img src="screenshots/21_guardrail_injection_blocked.png" alt="Guardrail blocked" /></div></div></div>
      </div>
    </section>

    <!-- Slide 10 -->
    <section class="slide">
      <div class="s-top"><div><div class="kicker">Technical Architecture</div><div class="s-title">Governed MCP Tool Layer &amp; Safe Write-Back Isolation</div></div><span class="s-badge">14 MCP Tools</span></div>
      <div class="grid-2">
        <div class="card emerald"><h3>1. Read-Only Analytical Intelligence (10 Tools)</h3><ul>
          <li><strong>Zero AI Calculation:</strong> Every revenue, margin, burn %, utilization %, and priority score is computed deterministically in SQL/Python over the 9 <code>vwm.*</code> views.</li>
          <li><strong>Anomaly &amp; Numeric Guardrails:</strong> Blocks hallucinated numbers and rejects any LLM text claiming 100% on <code>SP-REV-901</code>, -100% on <code>SP-COST-902</code>, or $0 on unmapped rates.</li>
          <li><strong>Flexible LLM or Zero-LLM Runtime:</strong> Instant <code>0.018 s</code> deterministic engine built in, plus plug-and-play LiteLLM for local Ollama (Apache 2.0), Gemini, or OpenAI.</li>
          <li><strong>Standard MCP Interface:</strong> Exposes all 14 tools and 5 metadata resources over JSON-RPC 2.0 stdio for reuse by external agents.</li>
        </ul></div>
        <div class="card royal"><h3>2. Governed CAT Write-Back Isolation (4 Tools)</h3><ul>
          <li><strong>Zero ERP Mutation:</strong> Write-backs never alter OWMS, GTE, CRC, or EFL actuals; all human context lives in 4 isolated CAT tables linked by business keys.</li>
          <li><strong>Multi-Modal Capture:</strong> Users write back via slash commands (<code>/comment</code>, <code>/assign</code>, <code>/decide</code>, <code>/log</code>), plain English, the inline Chat drawer, or Action Plan Hub.</li>
          <li><strong>RBAC &amp; RLS on Writes:</strong> PMs can comment/assign only within their 6 contracts; official Business Leader Decisions (<code>/decide</code>) require the BU Manager persona.</li>
          <li><strong>Refresh-Proof Audit History:</strong> Linking via <code>contract_id</code>, <code>project_uuid</code>, <code>task_uuid</code>, and <code>exception_id</code> ensures daily warehouse refreshes never orphan records.</li>
        </ul></div>
      </div>
      <div class="callout">Design Principle: Separate immutable financial truth (9 read-only views) from collaborative management accountability (4 CAT write-back tables).</div>
    </section>

    <!-- Slide 11 -->
    <section class="slide">
      <div class="s-top"><div><div class="kicker">Measured Verification</div><div class="s-title">Automated Testing, Golden Evaluation &amp; Portfolio Benchmarks</div></div><span class="s-badge">100% Measured</span></div>
      <div class="grid-2">
        <div class="card emerald"><h3>Automated Quality &amp; Evaluation Results</h3><ul>
          <li><strong>24/24 Golden Evaluation (<code>rules</code>):</strong> 100% Status Match (<b>24/24</b>), MCP Tool Match (<b>24/24</b>), Grounded Fact Match (<b>24/24</b>), and Guardrail Pass (<b>24/24</b>) at <b>0.018 s</b> median / 0.038 s P95.</li>
          <li><strong>19/19 Pytest &amp; Headless UI Checks:</strong> Verifies all 9 views, Priority Score math, all 5 injected anomalies, all 4 CAT write-back tables, RBAC/RLS denials, JSON-RPC 2.0 MCP, and all 7 Streamlit pages.</li>
          <li><strong>Zero Silent Data Loss:</strong> 1 unmatched EFL contract, 48 unmapped CRC hours, 1 orphaned fee line ($18.5k), and 1 Cat-7x suspense line ($4.2k) surfaced cleanly.</li>
          <li><strong>Full Audit Reproducibility:</strong> Raw records saved in <code>results/eval/eval_report.md</code> and <code>evaluation_summary.json</code>.</li>
        </ul></div>
        <div class="card royal"><h3>Synthetic TIC Benchmark Portfolio (As-of Nov 20, 2026)</h3><ul>
          <li><strong>Portfolio Scale:</strong> 10 Business Units (<code>BU-RENEW-01</code> .. <code>BU-CONSUM-10</code>), 20 contracts (12 FS, 6 T&amp;M, 1 <code>SP-REV-901</code>, 1 <code>SP-COST-902</code>).</li>
          <li><strong>MTD Commercial Revenue:</strong> <b>$1,297,980</b> recognized vs. $1,606,100 target (-$308,120 gap); <b>59.9%</b> commercial provisional margin on complete-rate linked contracts.</li>
          <li><strong>Net Operating Margin Bridge:</strong> After +$45,000 <code>SP-REV-901</code>, -$28,500 <code>SP-COST-902</code>, and -$120,000 Indirect Lab Burden &rarr; <b>$700,743 (52.2%)</b>.</li>
          <li><strong>Priority Queue &amp; Compliance:</strong> 9 active exceptions led by <code>FS-AERO-104</code> (100.0/100); 36h ($7,020) unbilled WIP &gt;7d lag; <code>TM-ENV-401</code> flagged at 64.0% util.</li>
        </ul></div>
      </div>
      <div class="callout">Proven Reusable Blueprint: Finance (IRIS) + Rollout Adoption (CORE Pulse) + Margin &amp; Write-Back Triage (Apex Margin Advisor).</div>
    </section>

    <!-- Slide 12 -->
    <section class="slide">
      <div class="s-top"><div><div class="kicker">Enterprise Production Path</div><div class="s-title">Connecting Live VWM Data (CORE / FLEX / JDE) &amp; SharePoint CAT</div></div><span class="s-badge">Roadmap</span></div>
      <div class="grid-4">
        <div class="card emerald"><span class="pill e">Phase 1 &middot; Ready Now</span><h3>Synthetic Benchmark &amp; UX</h3><p>9 governed views, 14 MCP tools, 3 personas, 4-table CAT write-back, and verified 24/24 Golden Eval.</p></div>
        <div class="card royal"><span class="pill r">Phase 2 &middot; Data Bind</span><h3>Live CORE / FLEX / JDE</h3><p>Point <code>vwm.*</code> views to production SQL Server replicas (<code>Project.*</code>, <code>F5201</code>, <code>F4211</code>, <code>F0911</code>, <code>F0901</code>, <code>F06116Z1</code>) with LEFT JOIN rules.</p></div>
        <div class="card amber"><span class="pill a">Phase 3 &middot; Enterprise Auth</span><h3>SSO, RLS &amp; SharePoint CAT</h3><p>Bind Microsoft Entra ID to SQL Server <code>SESSION_CONTEXT</code> RLS and connect CAT write-back to SharePoint VWM lists or enterprise SQL.</p></div>
        <div class="card"><span class="pill e">Phase 4 &middot; Scale</span><h3>Automated Weekly Triage</h3><p>Schedule weekly exception scorecards, Teams/email digests for overdue N-1 actions, and Finance reconciliation workflows.</p></div>
      </div>
      <div class="card" style="margin-top:12px;">
        <h3>3 Immediate Actions to Go Live on Pilot Business Unit (Zero UI Rewrite)</h3>
        <p><b>1. Upgrade VDM FLOW Joins to LEFT JOIN:</b> Replace legacy INNER JOINs on FLEX <code>F5201</code>/<code>F4211</code> so unmatched contracts surface instead of disappearing &nbsp;|&nbsp; <b>2. Confirm Rate History &amp; Cat-7x Rules:</b> Validate discipline charge/sell history and Finance suspense review &nbsp;|&nbsp; <b>3. Bind CAT Write-Back Store:</b> Point <code>ActionTrackerStore</code> to enterprise SQL or SharePoint VWM lists.</p>
      </div>
    </section>

  </div>
  <div class="nav-bar">
    <button onclick="go(-1)">&larr; Prev</button>
    <span id="counter">Slide 1 / 12</span>
    <button onclick="go(1)">Next &rarr;</button>
  </div>
</div>
<script>
  const slides = Array.from(document.querySelectorAll('.slide'));
  let idx = 0;
  function show(n) {
    slides.forEach(s => { s.classList.remove('active'); s.querySelectorAll('video').forEach(v => v.pause()); });
    idx = (n + slides.length) % slides.length;
    slides[idx].classList.add('active');
    document.getElementById('counter').textContent = 'Slide ' + (idx + 1) + ' / ' + slides.length;
  }
  function go(d) { show(idx + d); }
  document.addEventListener('keydown', e => {
    if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') go(1);
    if (e.key === 'ArrowLeft' || e.key === 'PageUp') go(-1);
  });
</script>
</body>
</html>
"""
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html_doc, encoding="utf-8")
    print(f"Saved HTML5 deck: {OUT_HTML} ({OUT_HTML.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build_pptx()
    build_html()
