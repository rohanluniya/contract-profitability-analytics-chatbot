"""Deterministic 9-view TIC synthetic benchmark warehouse builder for Apex Margin Advisor.

Builds base operational/financial tables across the five synthetic TIC modules:
  * OWMS (Operations Work Management System)
  * EFL  (Enterprise Financial Ledger)
  * GTE  (Global Time & Expense Engine)
  * CRC  (Commercial Rate Catalog)
  * CAT  (Collaborative Action Tracker)

And exposes the governed 9-view relational model in schema `vwm`:
  1. vwm.Dim_Contracts
  2. vwm.Dim_Services
  3. vwm.Dim_Tasks
  4. vwm.Fact_Timesheets
  5. vwm.Dim_RateCatalog
  6. vwm.Fact_GeneralLedger
  7. vwm.Fact_SharedOverheadAllocation
  8. vwm.Fact_Exceptions
  9. vwm.Fact_ActionLog

Every formula, anomaly rule, and injected benchmark scenario follows the Apex Margin Advisor
specification and honors VWM Data Analyst Guide LEFT JOIN integrity rules.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.cat.store import ActionTrackerStore

# ---------------------------------------------------------------------------
# Section 8A: 10 Synthetic TIC Business Units & Monthly Shared Lab Overhead
# ---------------------------------------------------------------------------
BUSINESS_UNITS: list[dict[str, Any]] = [
    {"operating_unit_id": "BU-RENEW-01", "bu_name": "Renewable Energy Testing", "region": "AMER", "allocation_factor": 0.13},
    {"operating_unit_id": "BU-AERO-02", "bu_name": "Aerospace Materials & Metallurgy", "region": "AMER", "allocation_factor": 0.15},
    {"operating_unit_id": "BU-ELEC-03", "bu_name": "Semiconductor & Electronics Verification", "region": "APAC", "allocation_factor": 0.12},
    {"operating_unit_id": "BU-ENV-04", "bu_name": "Environmental & Soil Toxicology", "region": "AMER", "allocation_factor": 0.08},
    {"operating_unit_id": "BU-PHARM-05", "bu_name": "Biopharma & Medical Devices", "region": "EMEA", "allocation_factor": 0.12},
    {"operating_unit_id": "BU-OFFSHORE-06", "bu_name": "Marine & Pipeline Non-Destructive Testing", "region": "EMEA", "allocation_factor": 0.10},
    {"operating_unit_id": "BU-AGRI-07", "bu_name": "Food Safety & Chemical Residue", "region": "EMEA", "allocation_factor": 0.06},
    {"operating_unit_id": "BU-AUTO-08", "bu_name": "Automotive Battery & Crash Testing", "region": "EMEA", "allocation_factor": 0.11},
    {"operating_unit_id": "BU-INFRA-09", "bu_name": "Civil Infrastructure & Structural Monitoring", "region": "AMER", "allocation_factor": 0.07},
    {"operating_unit_id": "BU-CONSUM-10", "bu_name": "Consumer Electronics & EMC Testing", "region": "APAC", "allocation_factor": 0.06},
]

BU_LOOKUP = {b["operating_unit_id"]: b for b in BUSINESS_UNITS}

SHARED_OVERHEAD_TOTAL = 120_000.0
SHARED_OVERHEAD_CAT8000 = 78_000.0  # Fixed Facility Lease & Utilities
SHARED_OVERHEAD_CAT9000 = 42_000.0  # Calibration & Lab Equipment Depreciation

# ---------------------------------------------------------------------------
# Commercial Rate Catalog (CRC) — Sell rates $85/hr to $275/hr
# Note: DISC-SPECIALIST-9 is deliberately omitted to exercise `task_missing_rate_link`
# ---------------------------------------------------------------------------
RATE_CATALOG: list[dict[str, Any]] = [
    {"discipline_id": "DISC-JR-INSP", "discipline_name": "Junior Field Inspector", "certification_level": "Level 1", "region": "GLOBAL", "effective_year": 2026, "hourly_cost_rate": 52.0, "billable_sell_rate": 85.0},
    {"discipline_id": "DISC-ENV-TECH", "discipline_name": "Environmental Toxicology Analyst", "certification_level": "Level 2", "region": "AMER", "effective_year": 2026, "hourly_cost_rate": 68.0, "billable_sell_rate": 125.0},
    {"discipline_id": "DISC-NDT-L2", "discipline_name": "NDT Ultrasonic Technician", "certification_level": "Level 2", "region": "EMEA", "effective_year": 2026, "hourly_cost_rate": 82.0, "billable_sell_rate": 155.0},
    {"discipline_id": "DISC-RENEW-ENG", "discipline_name": "Renewable Grid Cert Engineer", "certification_level": "Level 3", "region": "AMER", "effective_year": 2026, "hourly_cost_rate": 96.0, "billable_sell_rate": 180.0},
    {"discipline_id": "DISC-EMC-ENG", "discipline_name": "Semiconductor & EMC Engineer", "certification_level": "Level 3", "region": "APAC", "effective_year": 2026, "hourly_cost_rate": 104.0, "billable_sell_rate": 195.0},
    {"discipline_id": "DISC-PHARM-QA", "discipline_name": "Biopharma Validation Specialist", "certification_level": "Level 3", "region": "EMEA", "effective_year": 2026, "hourly_cost_rate": 112.0, "billable_sell_rate": 215.0},
    {"discipline_id": "DISC-AUTO-BATT", "discipline_name": "EV Battery Safety Lead", "certification_level": "Level 4", "region": "EMEA", "effective_year": 2026, "hourly_cost_rate": 122.0, "billable_sell_rate": 235.0},
    {"discipline_id": "DISC-AERO-MET", "discipline_name": "Principal Metallurgist", "certification_level": "Level 4", "region": "AMER", "effective_year": 2026, "hourly_cost_rate": 145.0, "billable_sell_rate": 275.0},
]

RATE_LOOKUP = {r["discipline_id"]: r for r in RATE_CATALOG}


def compute_priority_score(
    *,
    capital_at_risk: float,
    days_until_due: int | None,
    hour_burn_pct: float | None,
    days_open: int,
) -> dict[str, float]:
    """Exact Section 6 Multi-Factor Priority Scoring Formula (0 to 100 Points)."""
    cap = max(0.0, float(capital_at_risk))
    materiality = min(45.0, 45.0 * math.log10((cap / 5000.0) + 1.0))

    if days_until_due is None:
        urgency = 0.0
    elif days_until_due <= 3:
        urgency = 25.0
    elif days_until_due <= 7:
        urgency = 15.0
    elif days_until_due <= 30:
        urgency = 5.0
    else:
        urgency = 0.0

    burn = float(hour_burn_pct or 0.0)
    if burn > 150.0:
        deterioration = 15.0
    elif burn >= 120.0:
        deterioration = 10.0
    elif burn >= 100.0:
        deterioration = 5.0
    else:
        deterioration = 0.0

    if days_open > 14:
        latency = 15.0
    elif days_open >= 7:
        latency = 10.0
    else:
        latency = 3.0

    total = min(100.0, round(materiality + urgency + deterioration + latency, 1))
    return {
        "materiality_score": round(materiality, 1),
        "urgency_score": round(urgency, 1),
        "deterioration_score": round(deterioration, 1),
        "action_latency_score": round(latency, 1),
        "priority_score": total,
    }


def _build_synthetic_tables(as_of: date) -> dict[str, pd.DataFrame]:
    """Generate the exact 20-contract, 10-BU TIC benchmark dataset with all 5 injected scenarios."""
    fiscal_month = as_of.strftime("%Y-%m")

    # ------------------------------------------------------------------
    # 1. Contracts (12 FS, 6 T&M, 1 SP-REV-901, 1 SP-COST-902 = 20)
    # Leading zeroes on efl_contract_id verify normalized key join!
    # ------------------------------------------------------------------
    contracts_spec = [
        # --- 12 Fixed-Scope Contracts ($15,000 to $250,000) ---
        {
            "project_uuid": "PRJ-0104", "contract_id": "FS-AERO-104",
            "contract_name": "Turbine Blade Fatigue & Metallurgy Cert",
            "operating_unit_id": "BU-AERO-02", "contract_type": "FS", "project_status": "Active",
            "efl_contract_id": "0004104", "pm_user_id": "pm_delivery", "pm_name": "Jordan Vance",
            "client_name": "SkyForge Propulsion Corp", "start_date": "2026-08-01", "end_date": "2026-12-15",
            "services": [
                ("SVC-0104-A", "Metallurgical Creep & Fatigue Lab", 95000.0, 0.0, 1),
                ("SVC-0104-B", "Airworthiness Certification Dossier", 70000.0, 0.0, 1),
            ],
            # Injected Scenario #1: 420 hrs actual vs 250 hrs plan = 168.0% (>150% Runaway Cost Alert)
            "tasks": [
                ("TSK-0104-1", "SVC-0104-A", "High-Cycle Blade Fatigue Testing", "DISC-AERO-MET", 150.0, "2026-09-01", "2026-11-22", None, 60.0, "In Progress", 0),
                ("TSK-0104-2", "SVC-0104-B", "Fractography & Cert Sign-Off", "DISC-AERO-MET", 100.0, "2026-10-15", "2026-12-10", None, 0.0, "Ready", 0),
            ],
            "timesheets": [
                ("TSK-0104-1", "EMP-401", "Dr. A. Kovacs", "DISC-AERO-MET", "2026-11-04", 210.0, 1, "P", "Approved", "2026-11-05", 0, 1),
                ("TSK-0104-1", "EMP-402", "R. Lindqvist", "DISC-AERO-MET", "2026-11-14", 160.0, 1, "P", "Approved", "2026-11-15", 0, 1),
                ("TSK-0104-2", "EMP-401", "Dr. A. Kovacs", "DISC-AERO-MET", "2026-11-18", 50.0, 1, "P", "Approved", "2026-11-18", 0, 1),
            ],
            # Revenue recognized capped at $57,000 ($95k * 60%) while labor = 420 * $145 = $60,900 + $8,400 direct expense -> negative margin -$12,300
            "gl": [
                ("4104", "2026-11-15", "4010", "1", "Milestone Billing Revenue", -57000.0, 0.0),
                ("4104", "2026-11-16", "5210", "8000", "Subcontract Cryo Fixture Expense", 8400.0, 8400.0),
            ],
        },
        {
            "project_uuid": "PRJ-0305", "contract_id": "FS-AUTO-305",
            "contract_name": "EV Thermal Runaway Pack Homologation",
            "operating_unit_id": "BU-AUTO-08", "contract_type": "FS", "project_status": "Active",
            "efl_contract_id": "0009305", "pm_user_id": "pm_elena", "pm_name": "Elena Rostova",
            "client_name": "VoltDrive Mobility GmbH", "start_date": "2026-09-01", "end_date": "2026-12-20",
            "services": [
                ("SVC-0305-A", "UN38.3 Thermal Propagation Blast Tests", 115000.0, 0.0, 1),
                ("SVC-0305-B", "ECE R100 Homologation Report", 70000.0, 0.0, 1),
            ],
            # Injected Scenario #3: Active in OWMS, MISSING in EFL (`unmatched_efl_record`)
            "tasks": [
                ("TSK-0305-1", "SVC-0305-A", "Battery Cell Nail Penetration Series", "DISC-AUTO-BATT", 180.0, "2026-09-10", "2026-11-18", "2026-11-16", 100.0, "Completed", 0),
                ("TSK-0305-2", "SVC-0305-B", "Homologation Witness Sign-Off", "DISC-AUTO-BATT", 110.0, "2026-11-01", "2026-11-26", None, 40.0, "In Progress", 0),
            ],
            "timesheets": [
                ("TSK-0305-1", "EMP-501", "M. Weber", "DISC-AUTO-BATT", "2026-11-10", 172.0, 1, "P", "Approved", "2026-11-11", 0, 1),
                ("TSK-0305-2", "EMP-501", "M. Weber", "DISC-AUTO-BATT", "2026-11-17", 44.0, 1, "P", "Approved", "2026-11-18", 0, 1),
            ],
            "gl": [],  # Deliberately empty -> Disconnected from Financial Ledger (`unmatched_efl_record`)
        },
        {
            "project_uuid": "PRJ-0108", "contract_id": "FS-OFFSHORE-108",
            "contract_name": "Subsea Riser Weld NDT Inspection",
            "operating_unit_id": "BU-OFFSHORE-06", "contract_type": "FS", "project_status": "Active",
            "efl_contract_id": "0004108", "pm_user_id": "pm_delivery", "pm_name": "Jordan Vance",
            "client_name": "NorthSea Subsea Energy", "start_date": "2026-09-15", "end_date": "2026-12-05",
            "services": [
                ("SVC-0108-A", "Phased Array Ultrasonic Weld Campaign", 140000.0, 0.0, 1),
            ],
            # Task Hour Burn Alert (>115% and <=150%): 256 hrs / 200 hrs = 128.0%
            "tasks": [
                ("TSK-0108-1", "SVC-0108-A", "Offshore Platform Riser PAUT Scans", "DISC-NDT-L2", 200.0, "2026-10-01", "2026-11-26", None, 70.0, "In Progress", 0),
            ],
            "timesheets": [
                ("TSK-0108-1", "EMP-601", "L. Hansen", "DISC-NDT-L2", "2026-11-05", 148.0, 1, "P", "Approved", "2026-11-06", 0, 1),
                ("TSK-0108-1", "EMP-602", "K. Solberg", "DISC-NDT-L2", "2026-11-16", 108.0, 1, "P", "Approved", "2026-11-17", 0, 1),
            ],
            "gl": [
                ("4108", "2026-11-15", "4010", "1", "Milestone Billing Revenue", -98000.0, 0.0),
                ("4108", "2026-11-16", "5220", "8000", "Offshore Vessel Mobilization", 11200.0, 11200.0),
            ],
        },
        {
            "project_uuid": "PRJ-0111", "contract_id": "FS-INFRA-111",
            "contract_name": "Suspension Bridge Cable Load Monitoring",
            "operating_unit_id": "BU-INFRA-09", "contract_type": "FS", "project_status": "Active",
            "efl_contract_id": "0004111", "pm_user_id": "pm_marcus", "pm_name": "Marcus Thorne",
            "client_name": "Pacific Transit Authority", "start_date": "2026-07-01", "end_date": "2026-12-31",
            "services": [
                ("SVC-0111-A", "Main Cable Acoustic Sensor Array", 150000.0, 0.0, 1),
                ("SVC-0111-B", "Structural Load Verification Report", 100000.0, 0.0, 1),
            ],
            # Milestone-to-GL variance > $10,000 ($112,500 milestone recognized vs $144,000 posted in EFL -> -$31,500 variance) + Cat 7x GL review item
            "tasks": [
                ("TSK-0111-1", "SVC-0111-A", "Tower Sensor Calibration & Install", "DISC-RENEW-ENG", 320.0, "2026-08-01", "2026-11-28", None, 75.0, "In Progress", 0),
                ("TSK-0111-2", "SVC-0111-B", "Annual Load Stress Certification", "DISC-RENEW-ENG", 180.0, "2026-11-15", "2026-12-28", None, 0.0, "Ready", 0),
            ],
            "timesheets": [
                ("TSK-0111-1", "EMP-701", "D. Cho", "DISC-RENEW-ENG", "2026-11-08", 290.0, 1, "P", "Approved", "2026-11-09", 0, 1),
            ],
            "gl": [
                ("4111", "2026-11-12", "4010", "1", "Advance Milestone Billing Revenue", -136000.0, 0.0),
                ("4111", "2026-11-14", "4090", "2", "Finance Revenue Accrual Adjustment", -8000.0, 0.0),
                ("4111", "2026-11-15", "7045", "7x", "Unclassified Suspense Cost - Review Required", 4200.0, 0.0),
            ],
        },
        {
            "project_uuid": "PRJ-0107", "contract_id": "FS-PHARM-107",
            "contract_name": "ISO-13485 Sterile Barrier Validation",
            "operating_unit_id": "BU-PHARM-05", "contract_type": "FS", "project_status": "Active",
            "efl_contract_id": "0004107", "pm_user_id": "pm_priya", "pm_name": "Priya Nair",
            "client_name": "Helios BioMed AG", "start_date": "2026-09-01", "end_date": "2026-12-15",
            "services": [
                ("SVC-0107-A", "Accelerated Aging & Seal Integrity", 125000.0, 0.0, 1),
            ],
            "tasks": [
                ("TSK-0107-1", "SVC-0107-A", "ASTM F1980 Chamber Qualification", "DISC-PHARM-QA", 260.0, "2026-09-15", "2026-11-29", None, 80.0, "In Progress", 0),
            ],
            "timesheets": [
                ("TSK-0107-1", "EMP-801", "S. Moreau", "DISC-PHARM-QA", "2026-11-12", 215.0, 1, "P", "Approved", "2026-11-13", 0, 1),
            ],
            "gl": [
                ("4107", "2026-11-15", "4010", "1", "Milestone Billing Revenue", -100000.0, 0.0),
                ("4107", "2026-11-16", "5230", "8000", "Sterile Media Consumables", 6800.0, 6800.0),
            ],
        },
        {
            "project_uuid": "PRJ-0112", "contract_id": "FS-CONSUM-112",
            "contract_name": "Consumer Wearable SAR & EMC Compliance",
            "operating_unit_id": "BU-CONSUM-10", "contract_type": "FS", "project_status": "Active",
            "efl_contract_id": "0004112", "pm_user_id": "pm_elena", "pm_name": "Elena Rostova",
            "client_name": "Lumina Wearables Inc", "start_date": "2026-10-01", "end_date": "2026-11-30",
            "services": [
                ("SVC-0112-A", "FCC Part 15 & SAR Chamber Suite", 48000.0, 0.0, 1),
            ],
            # Operational Delivery Risk: overdue task due 2026-11-12 at 0% + inverted dates task
            "tasks": [
                ("TSK-0112-1", "SVC-0112-A", "Radiated Emissions Pre-Scan", "DISC-EMC-ENG", 90.0, "2026-10-05", "2026-11-12", None, 0.0, "Not Ready", 0),
                ("TSK-0112-2", "SVC-0112-A", "SAR Specific Absorption Report", "DISC-EMC-ENG", 60.0, "2026-11-28", "2026-11-24", None, 50.0, "In Progress", 1),
            ],
            "timesheets": [
                ("TSK-0112-2", "EMP-901", "T. Sato", "DISC-EMC-ENG", "2026-11-15", 52.0, 1, "P", "Approved", "2026-11-16", 0, 1),
            ],
            "gl": [
                ("4112", "2026-11-15", "4010", "1", "Milestone Billing Revenue", -24000.0, 0.0),
            ],
        },
        # --- 6 Healthy Fixed-Scope Contracts ---
        {
            "project_uuid": "PRJ-0101", "contract_id": "FS-RENEW-101",
            "contract_name": "Offshore Wind Blade Static Load Cert",
            "operating_unit_id": "BU-RENEW-01", "contract_type": "FS", "project_status": "Active",
            "efl_contract_id": "0004101", "pm_user_id": "pm_delivery", "pm_name": "Jordan Vance",
            "client_name": "VentoGrid Renewables", "start_date": "2026-08-15", "end_date": "2026-12-10",
            "services": [("SVC-0101-A", "IEC 61400 Full-Scale Blade Testing", 210000.0, 0.0, 1)],
            "tasks": [
                ("TSK-0101-1", "SVC-0101-A", "Static Flapwise & Edgewise Bending", "DISC-RENEW-ENG", 420.0, "2026-08-20", "2026-11-15", "2026-11-14", 100.0, "Completed", 0),
                ("TSK-0101-2", "SVC-0101-A", "Type Certificate Issuance", "DISC-RENEW-ENG", 180.0, "2026-11-01", "2026-12-08", None, 50.0, "In Progress", 0),
            ],
            "timesheets": [
                ("TSK-0101-1", "EMP-101", "C. Delgado", "DISC-RENEW-ENG", "2026-11-06", 390.0, 1, "P", "Approved", "2026-11-07", 0, 1),
                ("TSK-0101-2", "EMP-101", "C. Delgado", "DISC-RENEW-ENG", "2026-11-17", 85.0, 1, "P", "Approved", "2026-11-18", 0, 1),
            ],
            "gl": [
                ("4101", "2026-11-15", "4010", "1", "Milestone Billing Revenue", -178500.0, 0.0),
                ("4101", "2026-11-16", "5210", "8000", "Strain Gauge Consumables", 9500.0, 9500.0),
            ],
        },
        {
            "project_uuid": "PRJ-0102", "contract_id": "FS-AERO-102",
            "contract_name": "Composite Wing Spar Ultrasonic Cert",
            "operating_unit_id": "BU-AERO-02", "contract_type": "FS", "project_status": "Active",
            "efl_contract_id": "0004102", "pm_user_id": "pm_marcus", "pm_name": "Marcus Thorne",
            "client_name": "AeroStruct Dynamics", "start_date": "2026-09-01", "end_date": "2026-12-20",
            "services": [("SVC-0102-A", "CFRP Laminate Delamination Inspection", 190000.0, 0.0, 1)],
            "tasks": [
                ("TSK-0102-1", "SVC-0102-A", "C-Scan Immersion Array Tests", "DISC-AERO-MET", 360.0, "2026-09-05", "2026-11-28", None, 80.0, "In Progress", 0),
            ],
            "timesheets": [
                ("TSK-0102-1", "EMP-403", "H. Patel", "DISC-AERO-MET", "2026-11-12", 295.0, 1, "P", "Approved", "2026-11-13", 0, 1),
            ],
            "gl": [
                ("4102", "2026-11-15", "4010", "1", "Milestone Billing Revenue", -152000.0, 0.0),
                ("4102", "2026-11-16", "5210", "8000", "Couplant & Reference Blocks", 5200.0, 5200.0),
            ],
        },
        {
            "project_uuid": "PRJ-0103", "contract_id": "FS-ELEC-103",
            "contract_name": "SiC Power Module Burn-In Qualification",
            "operating_unit_id": "BU-ELEC-03", "contract_type": "FS", "project_status": "Active",
            "efl_contract_id": "0004103", "pm_user_id": "pm_priya", "pm_name": "Priya Nair",
            "client_name": "Kestrel Microelectronics", "start_date": "2026-09-01", "end_date": "2026-12-12",
            "services": [("SVC-0103-A", "AQG-324 Power Cycling & HTRB", 135000.0, 0.0, 1)],
            "tasks": [
                ("TSK-0103-1", "SVC-0103-A", "1000-Hr High-Temp Reverse Bias", "DISC-EMC-ENG", 340.0, "2026-09-10", "2026-11-25", None, 85.0, "In Progress", 0),
            ],
            "timesheets": [
                ("TSK-0103-1", "EMP-301", "Y. Lin", "DISC-EMC-ENG", "2026-11-14", 295.0, 1, "P", "Approved", "2026-11-15", 0, 1),
            ],
            "gl": [
                ("4103", "2026-11-15", "4010", "1", "Milestone Billing Revenue", -114750.0, 0.0),
                ("4103", "2026-11-16", "5210", "8000", "Burn-In Socket Tooling", 4500.0, 4500.0),
            ],
        },
        {
            "project_uuid": "PRJ-0105", "contract_id": "FS-ENV-105",
            "contract_name": "Industrial Brownfield Soil Tox Baseline",
            "operating_unit_id": "BU-ENV-04", "contract_type": "FS", "project_status": "Complete",
            "efl_contract_id": "0004105", "pm_user_id": "pm_elena", "pm_name": "Elena Rostova",
            "client_name": "Meridian Land Reclamation", "start_date": "2026-09-10", "end_date": "2026-11-14",
            "services": [("SVC-0105-A", "EPA 8270 SVOC & Heavy Metals Panel", 62000.0, 0.0, 1)],
            "tasks": [
                ("TSK-0105-1", "SVC-0105-A", "Core Sampling & GC-MS Analysis", "DISC-ENV-TECH", 260.0, "2026-09-15", "2026-11-14", "2026-11-13", 100.0, "Completed", 0),
            ],
            "timesheets": [
                ("TSK-0105-1", "EMP-201", "N. Brooks", "DISC-ENV-TECH", "2026-11-10", 235.0, 1, "P", "Approved", "2026-11-11", 0, 1),
            ],
            "gl": [
                ("4105", "2026-11-14", "4010", "1", "Milestone Billing Revenue", -62000.0, 0.0),
                ("4105", "2026-11-14", "5210", "8000", "Reagent & Sample Transport", 3100.0, 3100.0),
            ],
        },
        {
            "project_uuid": "PRJ-0106", "contract_id": "FS-AGRI-106",
            "contract_name": "Export Grain Pesticide Residue Panel",
            "operating_unit_id": "BU-AGRI-07", "contract_type": "FS", "project_status": "Complete",
            "efl_contract_id": "0004106", "pm_user_id": "pm_priya", "pm_name": "Priya Nair",
            "client_name": "Heartland Grain Exports", "start_date": "2026-10-10", "end_date": "2026-11-18",
            "services": [("SVC-0106-A", "LC-MS/MS Multi-Residue Cert", 15000.0, 0.0, 1)],
            "tasks": [
                ("TSK-0106-1", "SVC-0106-A", "Silo Composite Extraction & Cert", "DISC-ENV-TECH", 95.0, "2026-10-15", "2026-11-18", "2026-11-17", 100.0, "Completed", 0),
            ],
            "timesheets": [
                ("TSK-0106-1", "EMP-202", "P. Alvarez", "DISC-ENV-TECH", "2026-11-14", 82.0, 1, "P", "Approved", "2026-11-15", 0, 1),
            ],
            "gl": [
                ("4106", "2026-11-18", "4010", "1", "Milestone Billing Revenue", -15000.0, 0.0),
                ("4106", "2026-11-18", "5210", "8000", "Chromatography Columns", 900.0, 900.0),
            ],
        },
        {
            "project_uuid": "PRJ-0109", "contract_id": "FS-AUTO-109",
            "contract_name": "Autonomous Lidar Environmental Ingress",
            "operating_unit_id": "BU-AUTO-08", "contract_type": "FS", "project_status": "Active",
            "efl_contract_id": "0004109", "pm_user_id": "pm_marcus", "pm_name": "Marcus Thorne",
            "client_name": "OptiDrive Robotics", "start_date": "2026-09-20", "end_date": "2026-12-18",
            "services": [("SVC-0109-A", "IP6K9K Dust, Salt Fog & Vibration", 98000.0, 0.0, 1)],
            "tasks": [
                ("TSK-0109-1", "SVC-0109-A", "ISO 16750 Thermal Shock & Vibration", "DISC-AUTO-BATT", 240.0, "2026-10-01", "2026-11-29", None, 75.0, "In Progress", 0),
            ],
            "timesheets": [
                ("TSK-0109-1", "EMP-502", "J. Richter", "DISC-AUTO-BATT", "2026-11-13", 185.0, 1, "P", "Approved", "2026-11-14", 0, 1),
            ],
            "gl": [
                ("4109", "2026-11-15", "4010", "1", "Milestone Billing Revenue", -73500.0, 0.0),
                ("4109", "2026-11-16", "5210", "8000", "Vibration Jig Fabrication", 3800.0, 3800.0),
            ],
        },
        # --- 6 Time & Materials Contracts ($85/hr to $275/hr) ---
        {
            "project_uuid": "PRJ-0202", "contract_id": "TM-RENEW-202",
            "contract_name": "Grid-Scale BESS Commissioning Support",
            "operating_unit_id": "BU-RENEW-01", "contract_type": "TM", "project_status": "Active",
            "efl_contract_id": "0005202", "pm_user_id": "pm_delivery", "pm_name": "Jordan Vance",
            "client_name": "Solstice Grid Storage", "start_date": "2026-09-01", "end_date": "2026-12-31",
            "services": [("SVC-0202-A", "Field Commissioning T&M Retainer", 0.0, 0.0, 1)],
            # Injected Scenario #2: 48 hrs logged under unmapped `DISC-SPECIALIST-9` (`task_missing_rate_link`)
            "tasks": [
                ("TSK-0202-1", "SVC-0202-A", "Inverter Grid-Code Witness Testing", "DISC-RENEW-ENG", 200.0, "2026-11-01", "2026-11-30", None, 80.0, "In Progress", 0),
                ("TSK-0202-2", "SVC-0202-A", "High-Voltage Arc-Flash Specialist Audit", "DISC-SPECIALIST-9", 60.0, "2026-11-01", "2026-11-25", None, 70.0, "In Progress", 0),
            ],
            "timesheets": [
                ("TSK-0202-1", "EMP-102", "A. Okafor", "DISC-RENEW-ENG", "2026-11-12", 180.0, 1, "P", "Approved", "2026-11-13", 0, 1),
                ("TSK-0202-2", "EMP-109", "S. Varma", "DISC-SPECIALIST-9", "2026-11-15", 48.0, 1, "P", "Approved", "2026-11-16", 0, 1),
            ],
            "gl": [
                ("5202", "2026-11-16", "4020", "1", "T&M Time Billing Revenue", -32400.0, 0.0),
            ],
        },
        {
            "project_uuid": "PRJ-0401", "contract_id": "TM-ENV-401",
            "contract_name": "Groundwater Remediation Field Sampling",
            "operating_unit_id": "BU-ENV-04", "contract_type": "TM", "project_status": "Active",
            "efl_contract_id": "0005401", "pm_user_id": "pm_delivery", "pm_name": "Jordan Vance",
            "client_name": "Cascade Municipal Water", "start_date": "2026-08-01", "end_date": "2026-12-31",
            "services": [("SVC-0401-A", "Monthly Well Sampling T&M", 0.0, 0.0, 1)],
            # Injected Scenario #4: Billable utilization at exactly 64.0% (128 billable / 200 total hrs, below 80% threshold!)
            "tasks": [
                ("TSK-0401-1", "SVC-0401-A", "Field Well Sampling & Lab Chain", "DISC-ENV-TECH", 200.0, "2026-11-01", "2026-11-30", None, 64.0, "In Progress", 0),
            ],
            "timesheets": [
                ("TSK-0401-1", "EMP-205", "E. Gallagher", "DISC-ENV-TECH", "2026-11-12", 128.0, 1, "P", "Approved", "2026-11-13", 0, 1),
                ("TSK-0401-1", "EMP-205", "E. Gallagher", "DISC-ENV-TECH", "2026-11-14", 72.0, 0, "N", "Approved", "2026-11-15", 0, 1),
            ],
            "gl": [
                ("5401", "2026-11-16", "4020", "1", "T&M Time Billing Revenue", -16000.0, 0.0),
            ],
        },
        {
            "project_uuid": "PRJ-0204", "contract_id": "TM-ELEC-204",
            "contract_name": "Wafer Fab Contamination Audit Support",
            "operating_unit_id": "BU-ELEC-03", "contract_type": "TM", "project_status": "Active",
            "efl_contract_id": "0005204", "pm_user_id": "pm_delivery", "pm_name": "Jordan Vance",
            "client_name": "Apex Silicon Foundry", "start_date": "2026-09-01", "end_date": "2026-12-31",
            "services": [("SVC-0204-A", "Cleanroom Particle & AMC T&M", 0.0, 0.0, 1)],
            # Unapproved Billing Lag (> 7 business days): 36 hrs submitted 11 business days ago!
            "tasks": [
                ("TSK-0204-1", "SVC-0204-A", "ISO Class 3 Wafer Fab Audits", "DISC-EMC-ENG", 210.0, "2026-11-01", "2026-11-30", None, 85.0, "In Progress", 0),
            ],
            "timesheets": [
                ("TSK-0204-1", "EMP-305", "D. Park", "DISC-EMC-ENG", "2026-11-04", 160.0, 1, "P", "Approved", "2026-11-05", 0, 1),
                ("TSK-0204-1", "EMP-306", "J. Wu", "DISC-EMC-ENG", "2026-11-05", 36.0, 1, "P", "Submitted", "2026-11-05", 11, 1),
            ],
            "gl": [
                ("5204", "2026-11-15", "4020", "1", "T&M Time Billing Revenue", -31200.0, 0.0),
            ],
        },
        {
            "project_uuid": "PRJ-0205", "contract_id": "TM-PHARM-205",
            "contract_name": "GMP Cleanroom Bioburden Monitoring",
            "operating_unit_id": "BU-PHARM-05", "contract_type": "TM", "project_status": "Active",
            "efl_contract_id": "0005205", "pm_user_id": "pm_priya", "pm_name": "Priya Nair",
            "client_name": "Nordic BioTherapeutics", "start_date": "2026-07-01", "end_date": "2026-12-31",
            "services": [("SVC-0205-A", "Weekly Bioburden & Endotoxin T&M", 0.0, 0.0, 1)],
            "tasks": [
                ("TSK-0205-1", "SVC-0205-A", "Grade A/B Cleanroom Sampling", "DISC-PHARM-QA", 220.0, "2026-11-01", "2026-11-30", None, 90.0, "In Progress", 0),
            ],
            "timesheets": [
                ("TSK-0205-1", "EMP-802", "C. Dubois", "DISC-PHARM-QA", "2026-11-14", 200.0, 1, "P", "Approved", "2026-11-15", 0, 1),
                ("TSK-0205-1", "EMP-802", "C. Dubois", "DISC-PHARM-QA", "2026-11-15", 20.0, 0, "N", "Approved", "2026-11-16", 0, 1),
            ],
            "gl": [
                ("5205", "2026-11-16", "4020", "1", "T&M Time Billing Revenue", -43000.0, 0.0),
            ],
        },
        {
            "project_uuid": "PRJ-0206", "contract_id": "TM-OFFSHORE-206",
            "contract_name": "Offshore Rig Inspection Call-Off",
            "operating_unit_id": "BU-OFFSHORE-06", "contract_type": "TM", "project_status": "Active",
            "efl_contract_id": "0005206", "pm_user_id": "pm_marcus", "pm_name": "Marcus Thorne",
            "client_name": "Fjord Maritime Services", "start_date": "2026-08-01", "end_date": "2026-12-31",
            "services": [("SVC-0206-A", "Hull & Crane NDT Call-Off T&M", 0.0, 0.0, 1)],
            "tasks": [
                ("TSK-0206-1", "SVC-0206-A", "Senior NDT Weld Inspections", "DISC-NDT-L2", 150.0, "2026-11-01", "2026-11-30", None, 85.0, "In Progress", 0),
                ("TSK-0206-2", "SVC-0206-A", "Visual Coating Thickness Checks", "DISC-JR-INSP", 100.0, "2026-11-01", "2026-11-30", None, 88.0, "In Progress", 0),
            ],
            "timesheets": [
                ("TSK-0206-1", "EMP-605", "O. Berg", "DISC-NDT-L2", "2026-11-12", 132.0, 1, "P", "Approved", "2026-11-13", 0, 1),
                ("TSK-0206-2", "EMP-606", "M. Lind", "DISC-JR-INSP", "2026-11-13", 88.0, 1, "P", "Approved", "2026-11-14", 0, 1),
                ("TSK-0206-2", "EMP-606", "M. Lind", "DISC-JR-INSP", "2026-11-14", 30.0, 0, "N", "Approved", "2026-11-15", 0, 1),
            ],
            "gl": [
                ("5206", "2026-11-16", "4020", "1", "T&M Time Billing Revenue", -27940.0, 0.0),
            ],
        },
        {
            "project_uuid": "PRJ-0207", "contract_id": "TM-CONSUM-207",
            "contract_name": "Anechoic Chamber EMC Testing Retainer",
            "operating_unit_id": "BU-CONSUM-10", "contract_type": "TM", "project_status": "Active",
            "efl_contract_id": "0005207", "pm_user_id": "pm_elena", "pm_name": "Elena Rostova",
            "client_name": "Zenith Audio Systems", "start_date": "2026-09-01", "end_date": "2026-12-31",
            "services": [("SVC-0207-A", "EMC Chamber Hourly Retainer", 0.0, 0.0, 1)],
            "tasks": [
                ("TSK-0207-1", "SVC-0207-A", "CISPR-32 Radiated & Conducted Sweeps", "DISC-EMC-ENG", 180.0, "2026-11-01", "2026-11-30", None, 90.0, "In Progress", 0),
            ],
            "timesheets": [
                ("TSK-0207-1", "EMP-902", "K. Tanaka", "DISC-EMC-ENG", "2026-11-14", 162.0, 1, "P", "Approved", "2026-11-15", 0, 1),
                ("TSK-0207-1", "EMP-902", "K. Tanaka", "DISC-EMC-ENG", "2026-11-15", 18.0, 0, "N", "Approved", "2026-11-16", 0, 1),
            ],
            "gl": [
                ("5207", "2026-11-16", "4020", "1", "T&M Time Billing Revenue", -31590.0, 0.0),
            ],
        },
        # --- 2 Special Purpose Contracts (Section 8B & Section 4A) ---
        {
            "project_uuid": "PRJ-0901", "contract_id": "SP-REV-901",
            "contract_name": "Global Client Annual Volume Rebate Adjustment",
            "operating_unit_id": "BU-RENEW-01", "contract_type": "SP-REV", "project_status": "Active",
            "efl_contract_id": "0009901", "pm_user_id": "commercial_admin", "pm_name": "Commercial Ops",
            "client_name": "VentoGrid Renewables (Master Rebate)", "start_date": "2026-01-01", "end_date": "2026-12-31",
            "services": [("SVC-0901-A", "Annual Volume Commercial Rebate", 45000.0, 0.0, 1)],
            "tasks": [],
            "timesheets": [],
            "gl": [
                ("9901", "2026-11-15", "4095", "2", "Commercial Volume Rebate Revenue Adjustment", -45000.0, 0.0),
            ],
        },
        {
            "project_uuid": "PRJ-0902", "contract_id": "SP-COST-902",
            "contract_name": "Central Calibration Maintenance Lab Pool",
            "operating_unit_id": "BU-AERO-02", "contract_type": "SP-COST", "project_status": "Active",
            "efl_contract_id": "0009902", "pm_user_id": "bu_director", "pm_name": "Lab Operations",
            "client_name": "Internal Calibration Holding Pool", "start_date": "2026-01-01", "end_date": "2026-12-31",
            "services": [("SVC-0902-A", "Internal Equipment Recalibration Pool", 0.0, 0.0, 0)],
            "tasks": [
                ("TSK-0902-1", "SVC-0902-A", "ISO-17025 Master Gage Recalibration", "DISC-AERO-MET", 200.0, "2026-11-01", "2026-11-30", None, 95.0, "In Progress", 0),
            ],
            "timesheets": [],  # Labor expense $28,500 booked directly via EFL / holding pool
            "gl": [
                ("9902", "2026-11-15", "5100", "8000", "Calibration Maintenance Labor Holding Cost", 28500.0, 28500.0),
            ],
        },
    ]

    dim_contracts_rows: list[dict] = []
    dim_services_rows: list[dict] = []
    dim_tasks_rows: list[dict] = []
    fact_timesheets_rows: list[dict] = []
    fact_gl_rows: list[dict] = []

    ts_seq = 1
    gl_seq = 1
    for c in contracts_spec:
        bu = BU_LOOKUP[c["operating_unit_id"]]
        dim_contracts_rows.append({
            "project_uuid": c["project_uuid"],
            "contract_id": c["contract_id"],
            "contract_name": c["contract_name"],
            "operating_unit_id": c["operating_unit_id"],
            "bu_name": bu["bu_name"],
            "region": bu["region"],
            "contract_type": c["contract_type"],
            "project_status": c["project_status"],
            "efl_contract_id": c["efl_contract_id"],
            "pm_user_id": c["pm_user_id"],
            "pm_name": c["pm_name"],
            "client_name": c["client_name"],
            "start_date": c["start_date"],
            "end_date": c["end_date"],
            "currency": "USD",
        })
        for svc_uuid, svc_name, ms_fee, oth_fee, is_bill in c["services"]:
            dim_services_rows.append({
                "service_uuid": svc_uuid,
                "project_uuid": c["project_uuid"],
                "service_name": svc_name,
                "milestone_fee": ms_fee,
                "other_billable_fee": oth_fee,
                "total_service_fee": ms_fee + oth_fee,
                "is_billable": is_bill,
                "is_orphaned": 0,
            })
        for t in c["tasks"]:
            dim_tasks_rows.append({
                "task_uuid": t[0],
                "service_uuid": t[1],
                "project_uuid": c["project_uuid"],
                "task_name": t[2],
                "discipline_id": t[3],
                "planned_hours": t[4],
                "start_date": t[5],
                "due_date": t[6],
                "completed_date": t[7],
                "completion_pct": t[8],
                "task_status": t[9],
                "invalid_dates_flag": t[10],
            })
        for ts in c["timesheets"]:
            fact_timesheets_rows.append({
                "timesheet_uuid": f"TS-{ts_seq:04d}",
                "task_uuid": ts[0],
                "project_uuid": c["project_uuid"],
                "employee_id": ts[1],
                "employee_name": ts[2],
                "discipline_id": ts[3],
                "work_date": ts[4],
                "effective_year": int(ts[4][:4]),
                "hours_logged": ts[5],
                "is_billable_pay_type": ts[6],
                "pay_category": ts[7],
                "approval_status": ts[8],
                "submitted_date": ts[9],
                "pending_business_days": ts[10],
                "has_header": ts[11],
            })
            ts_seq += 1
        for gl in c["gl"]:
            cat = gl[3]
            raw_amt = float(gl[5])
            rec_rev = -raw_amt if cat in ("1", "2") else 0.0
            dir_exp = float(gl[6])
            fact_gl_rows.append({
                "gl_line_id": f"GL-{gl_seq:05d}",
                "efl_contract_id": gl[0],
                "operating_unit_id": c["operating_unit_id"],
                "posting_date": gl[1],
                "account_code": gl[2],
                "account_category": cat,
                "account_description": gl[4],
                "raw_amount": raw_amt,
                "recognized_amount": rec_rev,
                "direct_expense_amount": dir_exp,
                "currency": "USD",
                "gl_post_status": "P",
            })
            gl_seq += 1

    # Add 1 quarantined orphaned fee line item (Section 4C: `orphaned_fee_structure`)
    dim_services_rows.append({
        "service_uuid": "SVC-ORPHAN-999",
        "project_uuid": "PRJ-DECOMM-000",
        "service_name": "Legacy Decommissioned Sterility Addendum (Quarantined)",
        "milestone_fee": 18500.0,
        "other_billable_fee": 0.0,
        "total_service_fee": 18500.0,
        "is_billable": 1,
        "is_orphaned": 1,
    })

    # Add centralized Shared Laboratory Overhead GL postings (Cat-8000 & Cat-9000 = $120,000)
    fact_gl_rows.append({
        "gl_line_id": f"GL-{gl_seq:05d}",
        "efl_contract_id": "SHARED-LAB-POOL",
        "operating_unit_id": "CORP-LAB",
        "posting_date": as_of.isoformat(),
        "account_code": "8000",
        "account_category": "8000",
        "account_description": "Cat-8000 Fixed Facility Lease, Blast Chambers & Utilities",
        "raw_amount": SHARED_OVERHEAD_CAT8000,
        "recognized_amount": 0.0,
        "direct_expense_amount": SHARED_OVERHEAD_CAT8000,
        "currency": "USD",
        "gl_post_status": "P",
    })
    gl_seq += 1
    fact_gl_rows.append({
        "gl_line_id": f"GL-{gl_seq:05d}",
        "efl_contract_id": "SHARED-LAB-POOL",
        "operating_unit_id": "CORP-LAB",
        "posting_date": as_of.isoformat(),
        "account_code": "9000",
        "account_category": "9000",
        "account_description": "Cat-9000 Cleanroom & EMC Equipment Depreciation",
        "raw_amount": SHARED_OVERHEAD_CAT9000,
        "recognized_amount": 0.0,
        "direct_expense_amount": SHARED_OVERHEAD_CAT9000,
        "currency": "USD",
        "gl_post_status": "P",
    })

    # ------------------------------------------------------------------
    # 2. Shared Overhead Allocation Matrix ($120,000 across 10 BUs)
    # ------------------------------------------------------------------
    overhead_rows = []
    for i, bu in enumerate(BUSINESS_UNITS, start=1):
        f = bu["allocation_factor"]
        overhead_rows.append({
            "allocation_id": f"OVH-202611-{i:02d}",
            "operating_unit_id": bu["operating_unit_id"],
            "bu_name": bu["bu_name"],
            "fiscal_month": fiscal_month,
            "facility_gl_cat8000": round(SHARED_OVERHEAD_CAT8000 * f, 2),
            "depreciation_gl_cat9000": round(SHARED_OVERHEAD_CAT9000 * f, 2),
            "total_monthly_facility_pool": SHARED_OVERHEAD_TOTAL,
            "bu_allocation_factor": f,
            "allocated_bu_overhead": round(SHARED_OVERHEAD_TOTAL * f, 2),
        })

    # ------------------------------------------------------------------
    # 3. Exceptions Engine Output (`Fact_Exceptions`) with exact Section 6 scores
    # ------------------------------------------------------------------
    raw_exceptions = [
        {
            "exception_uuid": "EXU-0104-RUNAWAY",
            "exception_id": "EXC-101",
            "project_uuid": "PRJ-0104",
            "contract_id": "FS-AERO-104",
            "operating_unit_id": "BU-AERO-02",
            "exception_family": "Financial & Margin Decay",
            "rule_code": "runaway_cost_alert",
            "severity": "Critical",
            "summary": "Actual logged hours reached 168.0% of plan (420 hrs vs. 250 hrs); automated revenue accrual blocked until re-planned and provisional margin is negative (-21.6%).",
            "capital_at_risk": 48600.0,
            "days_until_due": 2,
            "hour_burn_pct": 168.0,
            "days_open": 18,
            "status": "Open",
            "owner_persona": "Project Delivery Manager (PM)",
            "recommended_action": "Freeze non-essential overtime, initiate formal client scope change order, and re-baseline TSK-0104-1 before resuming revenue accrual.",
        },
        {
            "exception_uuid": "EXU-0305-EFL",
            "exception_id": "EXC-102",
            "project_uuid": "PRJ-0305",
            "contract_id": "FS-AUTO-305",
            "operating_unit_id": "BU-AUTO-08",
            "exception_family": "Setup & Integration Gaps",
            "rule_code": "unmatched_efl_record",
            "severity": "Critical",
            "summary": "Active OWMS contract ($185,000 value, 216 hrs logged) has no matching EFL ledger record for ID 0009305; marked Disconnected from Financial Ledger.",
            "capital_at_risk": 143000.0,
            "days_until_due": 6,
            "hour_burn_pct": 74.5,
            "days_open": 15,
            "status": "Open",
            "owner_persona": "Commercial Contract Administrator",
            "recommended_action": "Provision EFL contract master ID 9305 in General Ledger and post retroactive milestone revenue for completed task TSK-0305-1 ($115,000).",
        },
        {
            "exception_uuid": "EXU-0111-GLVAR",
            "exception_id": "EXC-103",
            "project_uuid": "PRJ-0111",
            "contract_id": "FS-INFRA-111",
            "operating_unit_id": "BU-INFRA-09",
            "exception_family": "Financial & Margin Decay",
            "rule_code": "milestone_gl_revenue_variance",
            "severity": "High",
            "summary": "Milestone completion recognizes $112,500 vs. $144,000 booked in EFL (variance -$31,500, exceeding $10,000 threshold); also includes $4,200 Category 7x suspense line.",
            "capital_at_risk": 35700.0,
            "days_until_due": 8,
            "hour_burn_pct": 90.6,
            "days_open": 11,
            "status": "Open",
            "owner_persona": "Commercial Contract Administrator",
            "recommended_action": "Reconcile -$31,500 advance billing differential with Finance and reclassify $4,200 Category 7x suspense journal line GL-00010.",
        },
        {
            "exception_uuid": "EXU-0108-BURN",
            "exception_id": "EXC-104",
            "project_uuid": "PRJ-0108",
            "contract_id": "FS-OFFSHORE-108",
            "operating_unit_id": "BU-OFFSHORE-06",
            "exception_family": "Financial & Margin Decay",
            "rule_code": "task_hour_burn_alert",
            "severity": "High",
            "summary": "Task TSK-0108-1 actual hours at 128.0% of plan (256 hrs vs. 200 hrs), exceeding the 115% Task Hour Burn warning threshold with 30% scope remaining.",
            "capital_at_risk": 14800.0,
            "days_until_due": 6,
            "hour_burn_pct": 128.0,
            "days_open": 9,
            "status": "Open",
            "owner_persona": "Project Delivery Manager (PM)",
            "recommended_action": "Audit offshore NDT shift productivity, cap weekend mobilization hours, and validate remaining 30% deliverable effort.",
        },
        {
            "exception_uuid": "EXU-0202-RATE",
            "exception_id": "EXC-105",
            "project_uuid": "PRJ-0202",
            "contract_id": "TM-RENEW-202",
            "operating_unit_id": "BU-RENEW-01",
            "exception_family": "Setup & Integration Gaps",
            "rule_code": "task_missing_rate_link",
            "severity": "High",
            "summary": "48.0 approved hours logged under Discipline DISC-SPECIALIST-9 have no matching CRC rate mapping (unvalued cost/sell exposure; never defaulted to $0).",
            "capital_at_risk": 12480.0,
            "days_until_due": 5,
            "hour_burn_pct": 87.7,
            "days_open": 8,
            "status": "Open",
            "owner_persona": "Commercial Contract Administrator",
            "recommended_action": "Add 2026 cost and billable sell rates for DISC-SPECIALIST-9 in Commercial Rate Catalog (CRC) and re-run valuation.",
        },
        {
            "exception_uuid": "EXU-0112-OVERDUE",
            "exception_id": "EXC-106",
            "project_uuid": "PRJ-0112",
            "contract_id": "FS-CONSUM-112",
            "operating_unit_id": "BU-CONSUM-10",
            "exception_family": "Operational Delivery Risks",
            "rule_code": "overdue_task_and_invalid_dates",
            "severity": "High",
            "summary": "Inspection task TSK-0112-1 is 8 days overdue with 0% progress, and task TSK-0112-2 has inverted dates (start 2026-11-28 > due 2026-11-24).",
            "capital_at_risk": 24000.0,
            "days_until_due": -8,
            "hour_burn_pct": 34.7,
            "days_open": 8,
            "status": "Open",
            "owner_persona": "Project Delivery Manager (PM)",
            "recommended_action": "Expedite EMC chamber slot for TSK-0112-1 and correct inverted schedule dates on TSK-0112-2 in OWMS.",
        },
        {
            "exception_uuid": "EXU-0401-UTIL",
            "exception_id": "EXC-107",
            "project_uuid": "PRJ-0401",
            "contract_id": "TM-ENV-401",
            "operating_unit_id": "BU-ENV-04",
            "exception_family": "Labor & Timesheet Compliance",
            "rule_code": "tm_under_utilization",
            "severity": "High",
            "summary": "T&M billable utilization dropped to 64.0% (128 billable hrs vs. 200 logged capacity hrs), breaching the 80% minimum threshold by 16.0 points.",
            "capital_at_risk": 9000.0,
            "days_until_due": 10,
            "hour_burn_pct": 100.0,
            "days_open": 12,
            "status": "Open",
            "owner_persona": "Operations Portfolio Director (BU Manager)",
            "recommended_action": "Reallocate idle field sampling capacity (72 non-billable hrs) to billable environmental panels or adjust dispatch routing.",
        },
        {
            "exception_uuid": "EXU-0204-UNAPP",
            "exception_id": "EXC-108",
            "project_uuid": "PRJ-0204",
            "contract_id": "TM-ELEC-204",
            "operating_unit_id": "BU-ELEC-03",
            "exception_family": "Labor & Timesheet Compliance",
            "rule_code": "unapproved_billing_lag",
            "severity": "Medium",
            "summary": "36.0 billable hours ($7,020 unbilled WIP) submitted by J. Wu have remained pending approval for 11 business days (> 7-day billing lag threshold).",
            "capital_at_risk": 7020.0,
            "days_until_due": 10,
            "hour_burn_pct": 93.3,
            "days_open": 11,
            "status": "Open",
            "owner_persona": "Project Delivery Manager (PM)",
            "recommended_action": "Approve pending GTE timesheet TS-0018 immediately to release $7,020 of unbilled WIP into November invoicing.",
        },
        {
            "exception_uuid": "EXU-0107-ORPHAN",
            "exception_id": "EXC-109",
            "project_uuid": "PRJ-0107",
            "contract_id": "FS-PHARM-107",
            "operating_unit_id": "BU-PHARM-05",
            "exception_family": "Setup & Integration Gaps",
            "rule_code": "orphaned_fee_structure",
            "severity": "Medium",
            "summary": "Quarantined orphaned milestone fee line SVC-ORPHAN-999 ($18,500) referencing decommissioned project_uuid PRJ-DECOMM-000; excluded from contract totals.",
            "capital_at_risk": 18500.0,
            "days_until_due": 9,
            "hour_burn_pct": 82.7,
            "days_open": 6,
            "status": "Open",
            "owner_persona": "Commercial Contract Administrator",
            "recommended_action": "Verify whether $18,500 addendum belongs to PRJ-0107 or should be retired in OWMS master fee table.",
        },
    ]

    fact_exceptions_rows = []
    for ex in raw_exceptions:
        sc = compute_priority_score(
            capital_at_risk=ex["capital_at_risk"],
            days_until_due=ex["days_until_due"],
            hour_burn_pct=ex["hour_burn_pct"],
            days_open=ex["days_open"],
        )
        detected = (as_of - timedelta(days=ex["days_open"])).isoformat()
        fact_exceptions_rows.append({
            "exception_uuid": ex["exception_uuid"],
            "exception_id": ex["exception_id"],
            "project_uuid": ex["project_uuid"],
            "contract_id": ex["contract_id"],
            "operating_unit_id": ex["operating_unit_id"],
            "exception_family": ex["exception_family"],
            "rule_code": ex["rule_code"],
            "severity": ex["severity"],
            "summary": ex["summary"],
            "capital_at_risk": ex["capital_at_risk"],
            "materiality_score": sc["materiality_score"],
            "urgency_score": sc["urgency_score"],
            "deterioration_score": sc["deterioration_score"],
            "action_latency_score": sc["action_latency_score"],
            "priority_score": sc["priority_score"],
            "days_open": ex["days_open"],
            "status": ex["status"],
            "detected_date": detected,
            "owner_persona": ex["owner_persona"],
            "recommended_action": ex["recommended_action"],
        })

    # Seed realistic baseline CAT write-back records (actions, comments, task assignments, decisions)
    seed_actions = [
        {
            "action_uuid": "ACT-SEED0001",
            "exception_uuid": "EXU-0104-RUNAWAY",
            "exception_id": "EXC-101",
            "contract_id": "FS-AERO-104",
            "bu_id": "BU-AERO-02",
            "entry_type": "N-1 Instruction",
            "user_id": "bu_director",
            "user_name": "Elena Vance (BU Director)",
            "persona": "Operations Portfolio Director (BU Manager)",
            "assigned_to": "Jordan Vance",
            "plan_horizon": "Next Week",
            "task_id": "TSK-0104-1",
            "status": "In Progress",
            "timestamp": datetime(2026, 11, 18, 9, 30, 0),
            "target_resolution_date": "2026-11-24",
            "remediation_comment": "N-1 Directive to PM Jordan Vance: Freeze weekend overtime on blade fatigue rig and present formal SkyForge change-order quote by Tuesday.",
            "baseline_snapshot_json": json.dumps({"burn_pct": 168.0, "actual_hours": 420.0, "planned_hours": 250.0, "priority_score": fact_exceptions_rows[0]["priority_score"]}),
        },
        {
            "action_uuid": "ACT-SEED0002",
            "exception_uuid": "EXU-0202-RATE",
            "exception_id": "EXC-105",
            "contract_id": "TM-RENEW-202",
            "bu_id": "BU-RENEW-01",
            "entry_type": "Remediation Action",
            "user_id": "commercial_admin",
            "user_name": "Claire Bennett (Contract Admin)",
            "persona": "Commercial Contract Administrator",
            "assigned_to": "Claire Bennett",
            "plan_horizon": "This Week",
            "task_id": "TSK-0202-2",
            "status": "Open",
            "timestamp": datetime(2026, 11, 19, 14, 15, 0),
            "target_resolution_date": "2026-11-23",
            "remediation_comment": "Submitted CRC rate ticket #CRC-4412 to map DISC-SPECIALIST-9 at $130/hr cost / $240/hr sell for 2026.",
            "baseline_snapshot_json": json.dumps({"unvalued_hours": 48.0, "discipline_id": "DISC-SPECIALIST-9"}),
        },
        {
            "action_uuid": "ACT-SEED0003",
            "exception_uuid": "EXU-0401-UTIL",
            "exception_id": "EXC-107",
            "contract_id": "TM-ENV-401",
            "bu_id": "BU-ENV-04",
            "entry_type": "Resource Reallocation",
            "user_id": "bu_director",
            "user_name": "Elena Vance (BU Director)",
            "persona": "Operations Portfolio Director (BU Manager)",
            "assigned_to": "Jordan Vance",
            "plan_horizon": "Next Month",
            "task_id": "TSK-0401-1",
            "status": "Open",
            "timestamp": datetime(2026, 11, 19, 16, 40, 0),
            "target_resolution_date": "2026-12-04",
            "remediation_comment": "Rebalance 40 hrs/month of non-billable sampling capacity in BU-ENV-04 to December billable groundwater panels to restore utilization above 85%.",
            "baseline_snapshot_json": json.dumps({"utilization_pct": 64.0, "non_billable_hours": 72.0}),
        },
    ]

    seed_comments = [
        {
            "comment_uuid": "CMT-SEED0001",
            "contract_id": "FS-OFFSHORE-108",
            "project_uuid": "PRJ-0108",
            "bu_id": "BU-OFFSHORE-06",
            "category": "Weather / Natural Event",
            "author_id": "pm_delivery",
            "author_name": "Jordan Vance",
            "author_persona": "Project Delivery Manager (PM)",
            "comment_text": "Severe North Sea gale halted offshore riser vessel standby for 3 days, adding 56 unplanned PAUT shift hours and $11,200 vessel mobilization; original effort estimate did not include winter weather contingency.",
            "impact_hours": 56.0,
            "impact_usd": 11200.0,
            "created_at": datetime(2026, 11, 18, 11, 20, 0),
        },
        {
            "comment_uuid": "CMT-SEED0002",
            "contract_id": "FS-AERO-104",
            "project_uuid": "PRJ-0104",
            "bu_id": "BU-AERO-02",
            "category": "Cost / Scope Clarification",
            "author_id": "pm_delivery",
            "author_name": "Jordan Vance",
            "author_persona": "Project Delivery Manager (PM)",
            "comment_text": "Client supplied 2 additional alloy heat lots mid-campaign requiring extra high-cycle fatigue runs (+170 hrs above initial 250h bid); commercial change order required before next milestone sign-off.",
            "impact_hours": 170.0,
            "impact_usd": 24650.0,
            "created_at": datetime(2026, 11, 19, 10, 5, 0),
        },
    ]

    seed_assignments = [
        {
            "assignment_uuid": "ASN-SEED0001",
            "contract_id": "FS-CONSUM-112",
            "task_uuid": "TSK-0112-1",
            "task_name": "Radiated Emissions Pre-Scan",
            "assignee_name": "T. Sato",
            "previous_assignee": "Unassigned",
            "plan_horizon": "Next Week",
            "reallocated_hours": 32.0,
            "assigned_by": "Elena Rostova",
            "assigned_by_persona": "Project Delivery Manager (PM)",
            "note": "Task was open without an owner; assigned to T. Sato for Chamber B slot next Monday to clear 8-day overdue backlog.",
            "status": "Assigned",
            "created_at": datetime(2026, 11, 19, 15, 0, 0),
        },
    ]

    seed_decisions = [
        {
            "decision_uuid": "DEC-SEED0001",
            "contract_id": "FS-OFFSHORE-108",
            "exception_id": "EXC-104",
            "decision_type": "Approve Cost / Weather Buffer",
            "decided_by": "Elena Vance (BU Director)",
            "decided_by_persona": "Operations Portfolio Director (BU Manager)",
            "rationale": "Approved weather-related mobilization overhead buffer for November review while PM negotiates shared standby recovery with NorthSea Subsea Energy.",
            "effective_until": "2026-12-05",
            "created_at": datetime(2026, 11, 19, 17, 10, 0),
        },
    ]

    return {
        "contracts": pd.DataFrame(dim_contracts_rows),
        "services": pd.DataFrame(dim_services_rows),
        "tasks": pd.DataFrame(dim_tasks_rows),
        "timesheets": pd.DataFrame(fact_timesheets_rows),
        "rates": pd.DataFrame(RATE_CATALOG),
        "gl": pd.DataFrame(fact_gl_rows),
        "overhead": pd.DataFrame(overhead_rows),
        "exceptions": pd.DataFrame(fact_exceptions_rows),
        "actions": pd.DataFrame(seed_actions),
        "seed_actions_list": seed_actions,
        "seed_comments_list": seed_comments,
        "seed_assignments_list": seed_assignments,
        "seed_decisions_list": seed_decisions,
    }


def build_warehouse(eng: Engine, as_of: date, reset_cat: bool = True) -> dict[str, Any]:
    """Create the 5 TIC module schemas + 9 governed `vwm.*` relational views in DuckDB (or SQL Server)."""
    data = _build_synthetic_tables(as_of)

    with eng.begin() as conn:
        for schema in ("owms", "efl", "gte", "crc", "cat", "vwm"):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))

    # Load base module tables
    data["contracts"].to_sql("contracts", eng, schema="owms", if_exists="replace", index=False)
    data["services"].to_sql("services", eng, schema="owms", if_exists="replace", index=False)
    data["tasks"].to_sql("tasks", eng, schema="owms", if_exists="replace", index=False)
    data["timesheets"].to_sql("timesheets", eng, schema="gte", if_exists="replace", index=False)
    data["rates"].to_sql("rate_catalog", eng, schema="crc", if_exists="replace", index=False)
    data["gl"].to_sql("general_ledger", eng, schema="efl", if_exists="replace", index=False)
    data["overhead"].to_sql("shared_overhead_allocation", eng, schema="efl", if_exists="replace", index=False)
    data["exceptions"].to_sql("exceptions", eng, schema="cat", if_exists="replace", index=False)
    data["actions"].to_sql("action_log", eng, schema="cat", if_exists="replace", index=False)

    # Create the exact 9 Relational Views in `vwm` enforcing Section 5 join keys
    view_ddls = [
        """
        CREATE OR REPLACE VIEW vwm.Dim_Contracts AS
        SELECT
            c.project_uuid,
            c.contract_id,
            c.contract_name,
            c.operating_unit_id,
            c.bu_name,
            c.region,
            c.contract_type,
            c.project_status,
            c.efl_contract_id,
            LTRIM(TRIM(c.efl_contract_id), '0') AS efl_contract_key_norm,
            c.pm_user_id,
            c.pm_name,
            c.client_name,
            c.start_date,
            c.end_date,
            c.currency,
            CASE WHEN EXISTS (
                SELECT 1 FROM efl.general_ledger g
                WHERE LTRIM(TRIM(g.efl_contract_id), '0') = LTRIM(TRIM(c.efl_contract_id), '0')
            ) THEN 1 ELSE 0 END AS efl_matched
        FROM owms.contracts c
        """,
        """
        CREATE OR REPLACE VIEW vwm.Dim_Services AS
        SELECT
            s.service_uuid,
            s.project_uuid,
            s.service_name,
            s.milestone_fee,
            s.other_billable_fee,
            s.total_service_fee,
            s.is_billable,
            s.is_orphaned
        FROM owms.services s
        """,
        """
        CREATE OR REPLACE VIEW vwm.Dim_Tasks AS
        SELECT
            t.task_uuid,
            t.service_uuid,
            t.project_uuid,
            t.task_name,
            t.discipline_id,
            t.planned_hours,
            t.start_date,
            t.due_date,
            t.completed_date,
            t.completion_pct,
            t.task_status,
            t.invalid_dates_flag
        FROM owms.tasks t
        """,
        """
        CREATE OR REPLACE VIEW vwm.Fact_Timesheets AS
        SELECT
            ts.timesheet_uuid,
            ts.task_uuid,
            ts.project_uuid,
            ts.employee_id,
            ts.employee_name,
            ts.discipline_id,
            ts.work_date,
            ts.effective_year,
            ts.hours_logged,
            ts.is_billable_pay_type,
            ts.pay_category,
            ts.approval_status,
            ts.submitted_date,
            ts.pending_business_days,
            ts.has_header
        FROM gte.timesheets ts
        """,
        """
        CREATE OR REPLACE VIEW vwm.Dim_RateCatalog AS
        SELECT
            r.discipline_id,
            r.discipline_name,
            r.certification_level,
            r.region,
            r.effective_year,
            r.hourly_cost_rate,
            r.billable_sell_rate
        FROM crc.rate_catalog r
        """,
        """
        CREATE OR REPLACE VIEW vwm.Fact_GeneralLedger AS
        SELECT
            g.gl_line_id,
            g.efl_contract_id,
            LTRIM(TRIM(g.efl_contract_id), '0') AS efl_contract_key_norm,
            g.operating_unit_id,
            g.posting_date,
            g.account_code,
            g.account_category,
            g.account_description,
            g.raw_amount,
            g.recognized_amount,
            g.direct_expense_amount,
            g.currency,
            g.gl_post_status
        FROM efl.general_ledger g
        WHERE g.gl_post_status = 'P'
        """,
        """
        CREATE OR REPLACE VIEW vwm.Fact_SharedOverheadAllocation AS
        SELECT
            o.allocation_id,
            o.operating_unit_id,
            o.bu_name,
            o.fiscal_month,
            o.facility_gl_cat8000,
            o.depreciation_gl_cat9000,
            o.total_monthly_facility_pool,
            o.bu_allocation_factor,
            o.allocated_bu_overhead
        FROM efl.shared_overhead_allocation o
        """,
        """
        CREATE OR REPLACE VIEW vwm.Fact_Exceptions AS
        SELECT
            e.exception_uuid,
            e.exception_id,
            e.project_uuid,
            e.contract_id,
            e.operating_unit_id,
            e.exception_family,
            e.rule_code,
            e.severity,
            e.summary,
            e.capital_at_risk,
            e.materiality_score,
            e.urgency_score,
            e.deterioration_score,
            e.action_latency_score,
            e.priority_score,
            e.days_open,
            e.status,
            e.detected_date,
            e.owner_persona,
            e.recommended_action
        FROM cat.exceptions e
        """,
        """
        CREATE OR REPLACE VIEW vwm.Fact_ActionLog AS
        SELECT
            a.action_uuid,
            a.exception_uuid,
            a.exception_id,
            a.contract_id,
            a.bu_id,
            a.entry_type,
            a.user_id,
            a.user_name,
            a.persona,
            a.assigned_to,
            a.plan_horizon,
            a.task_id,
            a.status,
            a.timestamp,
            a.target_resolution_date,
            a.remediation_comment,
            a.baseline_snapshot_json
        FROM cat.action_log a
        """,
    ]

    with eng.begin() as conn:
        for ddl in view_ddls:
            conn.execute(text(ddl))

    seeded_cat = {"actions": 0, "comments": 0, "assignments": 0, "decisions": 0}
    if reset_cat:
        cat_store = ActionTrackerStore()
        seeded_cat = cat_store.reset_and_seed(
            data["seed_actions_list"],
            data["seed_comments_list"],
            data["seed_assignments_list"],
            data["seed_decisions_list"],
        )

    return {
        "as_of_date": as_of.isoformat(),
        "business_units": len(BUSINESS_UNITS),
        "contracts": len(data["contracts"]),
        "fs_contracts": int((data["contracts"]["contract_type"] == "FS").sum()),
        "tm_contracts": int((data["contracts"]["contract_type"] == "TM").sum()),
        "sp_rev_contracts": int((data["contracts"]["contract_type"] == "SP-REV").sum()),
        "sp_cost_contracts": int((data["contracts"]["contract_type"] == "SP-COST").sum()),
        "services": len(data["services"]),
        "tasks": len(data["tasks"]),
        "timesheets": len(data["timesheets"]),
        "rate_catalog_rows": len(data["rates"]),
        "gl_lines": len(data["gl"]),
        "shared_overhead_total": SHARED_OVERHEAD_TOTAL,
        "exceptions": len(data["exceptions"]),
        "seeded_cat_actions": seeded_cat["actions"],
        "seeded_cat_comments": seeded_cat["comments"],
        "seeded_cat_assignments": seeded_cat["assignments"],
        "seeded_cat_decisions": seeded_cat["decisions"],
        "views_created": 9,
    }
