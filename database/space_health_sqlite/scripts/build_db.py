#!/usr/bin/env python3
"""Build a provenance-first SQLite database from NASA public telemetry and references."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import re
import sqlite3
import urllib.request
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "space_health.db"
EDA_URL = "https://visualization.osdr.nasa.gov/eda/data_tables"
RADLAB_URL = "https://visualization.osdr.nasa.gov/radlab/api/"
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
SEED = 20261114

SOURCES = [
    ("NASA Environmental Data App", "NASA Ames / OSDR", "https://visualization.osdr.nasa.gov/eda/", "public downloadable tables", "NASA EDA states that raw and summary mission data tables are available for download. EDA telemetry includes ISS hardware and ground-control experiment conditions; do not treat it as astronaut clinical telemetry."),
    ("NASA RadLab API", "NASA OSDR / RadLab", "https://visualization.osdr.nasa.gov/radlab/gui/data-api/", "public REST-like GET API", "Instrumented spacecraft radiation measurements; API documentation defines units and query behavior."),
    ("NASA Human Research Program", "NASA", "https://www.nasa.gov/hrp/risks/", "public scientific reference", "Official risk taxonomy and concise descriptions; not a clinical treatment protocol."),
    ("NASA Five Hazards of Human Spaceflight", "NASA HRP", "https://www.nasa.gov/hrp/hazards/", "public scientific reference", "Official five-hazard framing for human spaceflight."),
    ("VitalDB", "Seoul National University Hospital / PhysioNet", "https://physionet.org/content/vitaldb/1.0.0/", "public clinical dataset landing page; data use terms apply", "Perioperative terrestrial patient biosignals. Not spaceflight or astronaut data; not imported into this prototype."),
    ("NASA OSDR", "NASA", "https://osdr.nasa.gov/", "public repository; dataset-specific conditions apply", "Catalog of life-science datasets. Individual studies may require their own review and can contain non-tabular or modality-specific data."),
    ("ESA Human and Robotic Exploration Data Archive (HREDA)", "European Space Agency", "https://hreda.esac.esa.int/hreda/", "public study catalog; dataset-level access terms apply", "ISS human physiology investigations are discoverable through HREDA; the verified DOI records in this build provide study metadata, not individual numerical observations."),
]

DATASETS = [
    ("EDA-TELEMETRY", "NASA EDA downloadable telemetry tables, missions in source snapshot", "REAL", "NASA spaceflight experimental hardware and ground-control environmental series; not astronaut cabin/clinical measurements.", "Embedded JSON in EDA data_tables page; fields labeled GMT, °C, %RH, ppm CO2.", "NOT_IMPORTED", "Public page with NASA terms; source-page snapshot and hash retained in DB."),
    ("EDA-RADIATION", "NASA EDA mission radiation dose tables", "REAL", "Mission-level daily GCR, SAA, total, accumulated dose values associated with experiments.", "Embedded JSON in EDA data_tables page; NASA labels radiation values mGy/day.", "NOT_IMPORTED", "Public page with NASA terms; retain NASA labels and attribution."),
    ("RADLAB-DOSTEL-2022-04-01", "NASA RadLab ISS DosTel instrument radiation readings for 2022-04-01 UTC date window", "REAL", "ISS instrument readings; 24-hour query window, records as returned by API.", "CSV from documented public API; dose rate µGy/hour, flux cm^-2 sr^-1 s^-1, altitude km; source timestamps preserved.", "NOT_IMPORTED", "Public API; dataset-specific terms apply; no astronaut identity/clinical diagnosis."),
    ("NASA-HRP-RISKS", "NASA Human Research Program spaceflight risk catalog", "CATALOG", "Structured official risk descriptions linked to five hazards.", "HTML reference metadata curated into relational rows; no invented thresholds or treatment instructions.", "IMPORTED", "NASA public reference, cited per risk."),
    ("NASA-OSDR-CATALOG", "NASA Open Science Data Repository", "REFERENCE", "Repository candidate for future study-level biological datasets.", "Repository landing page only; no individual-study measurements imported in this build.", "METADATA_ONLY", "Each dataset must be reviewed for modality, reuse terms, and relevance."),
    ("VITALDB-CATALOG", "VitalDB public perioperative biosignal dataset", "REFERENCE", "Terrestrial high-resolution vital signs, useful for software/data-model research only.", "Landing-page metadata only; raw clinical records not imported.", "METADATA_ONLY", "Not astronaut data; dataset access and citation terms must be followed."),
    ("SYNTHETIC-CHECKINS-V1", "Synthetic daily avatar check-in fixtures", "SYNTHETIC", "Fictional subjects, daily self-report scores, deterministic examples for app integration.", "Generated in Python with fixed seed; scales are interface test scales, not validated clinical instruments.", "GENERATED", "Never use for clinical inference or present as observations."),
    ("OSD-53", "Spaceflight Modulates Gene Expression in Astronauts (OSD-53 / E-GEOD-47126)", "REAL", "Public processed microarray sample values and published preflight/postflight summary statistics; anonymized subject aliases and grouped controls, whole blood.", "NASA OSDR processed microarray ZIP files; sample metadata from the public OSDR API.", "NOT_IMPORTED", "Processed public data imported. Do not attempt to identify subjects. Recheck dataset terms and cite OSDR."),
    ("HREDA-BMI-ISS", "BMI - Blood Pressure Circadian Rhythms in Weightlessness", "CATALOG", "ESA HREDA ISS human-research study catalog entry; no subject-level numeric values imported.", "ESA HREDA DOI metadata record.", "METADATA_ONLY", "Catalog metadata only; verify files and current terms in HREDA before importing measurements."),
    ("HREDA-CIRCA-ISS", "CIRCA - One-day (24-hour) Pattern of Blood Pressure and Heart Rate in Weightlessness", "CATALOG", "ESA HREDA ISS human-research study catalog entry; no subject-level numeric values imported.", "ESA HREDA DOI metadata record.", "METADATA_ONLY", "Catalog metadata only; verify files and current terms in HREDA before importing measurements."),
    ("HREDA-AORTA-ISS", "AORTA - Physiological Parameters that predict Orthostatic Intolerance after Spaceflight", "CATALOG", "ESA HREDA ISS human-research study catalog entry; no subject-level numeric values imported.", "ESA HREDA DOI metadata record.", "METADATA_ONLY", "Catalog metadata only; verify files and current terms in HREDA before importing measurements."),
    ("HREDA-CARDIOCOG1-ISS", "Cardiocog 1 - Cognitive Cardiovascular Experiment 1", "CATALOG", "ESA HREDA ISS human-research study catalog entry; no subject-level numeric values imported.", "ESA HREDA DOI metadata record.", "METADATA_ONLY", "Catalog metadata only; verify files and current terms in HREDA before importing measurements."),
    ("HREDA-BONEHEALTH-ISS", "Bone Health - Post reambulatory bone loss after short duration mission", "CATALOG", "ESA HREDA ISS human-research study catalog entry; no subject-level numeric values imported.", "ESA HREDA DOI metadata record.", "METADATA_ONLY", "Catalog metadata only; verify files and current terms in HREDA before importing measurements."),
]

REFERENCES = [
    ("NASA Human Research Program. Risks of Human Spaceflight.", "https://www.nasa.gov/hrp/risks/", "risk definitions from NASA HRP; descriptive overview, not an operational medical protocol."),
    ("NASA Human Research Program. Five Hazards of Human Spaceflight.", "https://www.nasa.gov/hrp/hazards/", "five-hazard taxonomy: radiation, isolation/confinement, distance from Earth, gravity fields, hostile/closed environments."),
    ("NASA OSDR Environmental Data App (EDA). Data Tables.", "https://visualization.osdr.nasa.gov/eda/data_tables", "primary data source for mission telemetry and dose tables; source snapshot and SHA-256 stored in source_snapshots."),
    ("NASA OSDR RadLab. Data API documentation.", "https://visualization.osdr.nasa.gov/radlab/gui/data-api/", "primary API specification; defines absorbed dose rate in µGy/hour and other field units."),
    ("Lee HC et al. VitalDB, a high-fidelity multi-parameter vital signs database in surgical patients.", "https://physionet.org/content/vitaldb/1.0.0/", "terrestrial perioperative biosignal dataset, recorded here as candidate/reference only; not extrapolated to astronauts."),
    ("NASA Open Science Data Repository.", "https://osdr.nasa.gov/", "repository catalog; no dataset-level measurements imported from the landing page."),
    ("NASA OSDR. Spaceflight Modulates Gene Expression in Astronauts (OSD-53, version 3; E-GEOD-47126).", "https://osdr.nasa.gov/bio/repo/data/studies/OSD-53", "public processed microarray sample data and aggregate preflight/postflight analysis; sample aliases retained as published, not identified."),
    ("ESA HREDA. BMI - Blood Pressure Circadian Rhythms in Weightlessness.", "https://doi.org/10.57780/esa-dlsnsg8", "ISS study discovery metadata: blood-pressure circadian rhythms; no numerical observation file imported."),
    ("ESA HREDA. CIRCA - One-day (24-hour) Pattern of Blood Pressure and Heart Rate in Weightlessness.", "https://doi.org/10.57780/esa-vbr5rqz", "ISS study discovery metadata: blood pressure and heart rate; no numerical observation file imported."),
    ("ESA HREDA. AORTA - Physiological Parameters that predict Orthostatic Intolerance after Spaceflight.", "https://doi.org/10.57780/esa-a3chhec", "ISS study discovery metadata: orthostatic intolerance physiology; no numerical observation file imported."),
    ("ESA HREDA. Cardiocog 1 - Cognitive Cardiovascular Experiment 1.", "https://doi.org/10.57780/esa-elwh15i", "ISS cardiovascular human-research study discovery metadata; no numerical observation file imported."),
    ("ESA HREDA. Bone Health - Post reambulatory bone loss after short duration mission.", "https://doi.org/10.57780/esa-87ofc3h", "ISS human-research study discovery metadata; no numerical observation file imported."),
]

RISKS = [
    ("Space Radiation", "Radiation-induced cancer risk", "Space radiation exposure may increase cancer risk.", "Human spaceflight risk described by NASA HRP.", "Link available dose/context records to mission and time; never infer individual medical risk from instrument data alone.", "Dosimetry is environmental/instrument evidence, not diagnosis or personal dose unless a validated personal dosimeter record is provided."),
    ("Space Radiation", "Central nervous system and performance effects", "NASA identifies potential CNS, cognitive, motor, and behavioral effects associated with radiation exposure.", "Human spaceflight risk described by NASA HRP.", "Contextualize mission radiation series and self-reports for review.", "The data in this DB do not establish causal or individual clinical effects."),
    ("Isolation and Confinement", "Behavioral health and psychiatric risk", "Isolation and confinement can affect behavioral health and crew functioning.", "Human spaceflight risk described by NASA HRP.", "Optional self-report trend summaries and supportive, non-clinical check-ins.", "Synthetic check-ins are fictitious; no screening, diagnosis, or replacement for human support."),
    ("Isolation and Confinement", "Inadequate teamwork", "NASA HRP identifies teamwork and communication as mission-relevant risks.", "Human spaceflight risk described by NASA HRP.", "May motivate consent-based team-level context in a future design.", "No team-level or individual conclusions are supported by the mock data."),
    ("Isolation and Confinement", "Inadequate sleep and irregular schedules", "Space crews face sleep loss, work demands, and circadian schedule disruption.", "Human spaceflight risk described by NASA HRP.", "Self-report sleep trends can be represented as observations when collected by an authorized protocol.", "No real astronaut sleep records are imported here; synthetic scores are interface fixtures."),
    ("Distance from Earth", "Earth-independent human-system operations", "Distance can constrain timely communication, supplies, and medical support.", "Human spaceflight hazard framing from NASA HRP.", "Supports offline-first storage, provenance, and retrieval of pre-approved information.", "This database does not provide autonomous medical decisions or flight procedures."),
    ("Gravity Fields", "Reduced cardiorespiratory and musculoskeletal fitness", "NASA describes reduced bone, muscle, and cardiovascular fitness as risks requiring monitoring and countermeasures.", "Human spaceflight risk described by NASA HRP.", "Can organize authorized observations, exercise records, and reference literature.", "No clinical or exercise prescriptions are encoded."),
    ("Gravity Fields", "Spaceflight-associated neuro-ocular syndrome (SANS)", "NASA describes structural changes involving eyes and brain associated with spaceflight.", "Human spaceflight risk described by NASA HRP.", "Could index authorized clinical examinations and patient-reported symptoms.", "Generic ESP32/Wi-Fi measurements cannot confirm SANS; requires clinical evaluation and validated examinations."),
    ("Gravity Fields", "Spaceflight-induced bone changes", "NASA describes bone breakdown and increased brittleness in microgravity.", "Human spaceflight risk described by NASA HRP.", "Could link longitudinal validated bone assessments and mission context.", "No bone density measurement is available in imported data; no diagnosis or treatment guidance."),
    ("Gravity Fields", "Altered immune system responses", "Spaceflight stressors may alter immune responses and can be associated with reactivation of latent viruses.", "Human spaceflight risk described by NASA HRP.", "Index laboratory results only if public, appropriately licensed, and clearly scoped.", "No astronaut immune test values imported in this build."),
    ("Hostile/Closed Environments", "Hypoxia and low oxygen", "NASA identifies hypoxia as a human spaceflight risk, including in some exploration and EVA contexts.", "Human spaceflight risk described by NASA HRP.", "Environmental O2 and validated physiological SpO2 are distinct data streams.", "EDA rows here contain temperature, humidity, CO2; no oxygen or SpO2 values."),
    ("Hostile/Closed Environments", "High carbon dioxide and air quality", "NASA HRP identifies atmospheric and closed-environment factors as mission concerns.", "Human spaceflight risk described by NASA HRP.", "EDA CO2 data can support environmental time-series exploration for experiment hardware.", "These CO2 measurements are not astronaut cabin values and cannot diagnose symptom causes."),
    ("Hostile/Closed Environments", "Inadequate food and nutrition", "NASA identifies nutrition and food-system adequacy as health and performance concerns.", "Human spaceflight risk described by NASA HRP.", "Future datasets could store nutrition logs, food system characteristics, and published outcomes.", "No nutrition records or supplementation advice are imported."),
    ("Hostile/Closed Environments", "Host-microorganism interactions", "NASA notes that skin and gut microbiomes may change in space and can be relevant to illness risk.", "Human spaceflight risk described by NASA HRP.", "Potential future link to OSDR omics study metadata and files.", "No microbiome results imported."),
    ("Hostile/Closed Environments", "Decompression sickness and spacewalk injury", "NASA identifies decompression and spacewalk-related injury/performance risks.", "Human spaceflight risk described by NASA HRP.", "Could store mission/EVA context and cited protocol metadata in a future extension.", "No diagnosis or treatment procedures are provided."),
]


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def fetch(url: str, timeout=120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "SpaceHealthSQLite/1.0 (research prototype; contact: none)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} for {url}")
        return resp.read()

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None

def connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript((ROOT / "schema.sql").read_text())
    return con

def seed_catalog(con):
    for name, org, url, mode, note in SOURCES:
        con.execute("INSERT OR IGNORE INTO data_sources(name,organization,url,accessed_at,access_mode,license_note,scope_note) VALUES(?,?,?,?,?,?,?)",
                    (name, org, url, NOW, mode, "Source-specific terms apply; dataset-level reuse terms were not asserted unless listed by source.", note))
    for source_code, title, kind, scope, fmt, status, license_note in DATASETS:
        source_name = {
            "EDA-TELEMETRY":"NASA Environmental Data App", "EDA-RADIATION":"NASA Environmental Data App",
            "RADLAB-DOSTEL-2022-04-01":"NASA RadLab API", "NASA-HRP-RISKS":"NASA Human Research Program",
            "NASA-OSDR-CATALOG":"NASA OSDR", "VITALDB-CATALOG":"VitalDB", "SYNTHETIC-CHECKINS-V1":"NASA Human Research Program", "OSD-53":"NASA OSDR",
            "HREDA-BMI-ISS":"ESA Human and Robotic Exploration Data Archive (HREDA)", "HREDA-CIRCA-ISS":"ESA Human and Robotic Exploration Data Archive (HREDA)",
            "HREDA-AORTA-ISS":"ESA Human and Robotic Exploration Data Archive (HREDA)", "HREDA-CARDIOCOG1-ISS":"ESA Human and Robotic Exploration Data Archive (HREDA)",
            "HREDA-BONEHEALTH-ISS":"ESA Human and Robotic Exploration Data Archive (HREDA)"
        }[source_code]
        sid = con.execute("SELECT source_id FROM data_sources WHERE name=?", (source_name,)).fetchone()[0]
        con.execute("INSERT OR IGNORE INTO datasets(source_id,accession,title,data_kind,scope_note,format_note,status,license_note) VALUES(?,?,?,?,?,?,?,?)",
                    (sid, source_code, title, kind, scope, fmt, status, license_note))
    hreda_entries = [
        ("HREDA-BMI-ISS", "ISS", "European Space Agency", "BMI", "Blood pressure circadian rhythms", "2001-12-08/2004-04-21", "https://doi.org/10.57780/esa-dlsnsg8", "https://esdcdoi.esac.esa.int/doi/html/data/hre/hreda/c5d04e3f-9985-4e90-9a7c-725dd51dd07f.html"),
        ("HREDA-CIRCA-ISS", "ISS", "European Space Agency", "CIRCA", "Blood pressure; heart rate; 24-hour pattern", "2004-04-22/2004-10-16", "https://doi.org/10.57780/esa-vbr5rqz", "https://esdcdoi.esac.esa.int/doi/html/data/hre/hreda/e1b61d96-0a8e-497f-a925-5703fc02ecd9.html"),
        ("HREDA-AORTA-ISS", "ISS", "European Space Agency", "AORTA", "Physiological parameters; orthostatic intolerance", "2002-06-08/2004-04-21", "https://doi.org/10.57780/esa-a3chhec", "https://esdcdoi.esac.esa.int/doi/html/data/hre/hreda/cfe36a76-5c47-4d38-af7e-1efdcab8773f.html"),
        ("HREDA-CARDIOCOG1-ISS", "ISS", "European Space Agency", "Cardiocog 1", "Cognitive cardiovascular experiment", "2002-06-08/2005-04-17", "https://doi.org/10.57780/esa-elwh15i", "https://esdcdoi.esac.esa.int/doi/html/data/hre/hreda/f10a25b5-0499-49ff-be1b-33edf0ba2159.html"),
        ("HREDA-BONEHEALTH-ISS", "ISS", "European Space Agency", "Bone Health", "Postflight bone loss", "2023-09-21/2024-03-30", "https://doi.org/10.57780/esa-87ofc3h", "https://esdcdoi.esac.esa.int/doi/html/data/hre/hreda/b148b51a-e7dc-49ae-b722-a22147423a3d.html"),
    ]
    for accession, platform, agency, investigation, modalities, coverage, doi, source_url in hreda_entries:
        did = get_dataset_id(con, accession)
        access_note = "The cited ESA DOI record documents the study but does not provide subject-level numeric observations in the inspected record; do not interpret this catalog row as a measurement. Recheck HREDA for files and current access terms."
        if accession == "HREDA-CIRCA-ISS":
            access_note += " The cited publication reports measurements from two ESA astronauts and says the data must be limited to protect subject privacy."
        con.execute("""INSERT INTO iss_physiology_study_catalog
          (dataset_id,platform,contributing_agency,investigation_code,modalities,temporal_coverage,doi,source_url,observation_access_status,access_note,subject_nationality_status)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(dataset_id) DO UPDATE SET
            platform=excluded.platform, contributing_agency=excluded.contributing_agency,
            investigation_code=excluded.investigation_code, modalities=excluded.modalities,
            temporal_coverage=excluded.temporal_coverage, doi=excluded.doi,
            source_url=excluded.source_url, observation_access_status=excluded.observation_access_status,
            access_note=excluded.access_note, subject_nationality_status=excluded.subject_nationality_status""",
          (did, platform, agency, investigation, modalities, coverage, doi, source_url, "METADATA_ONLY",
           access_note, "NOT_REPORTED_IN_SOURCE"))
    field_definitions = [
        ("EDA-TELEMETRY","temperature_ground","ground_control_temperature","numeric","°C","NASA EDA experiment hardware / ground-control telemetry","sensor model/accuracy not supplied in imported table","Original EDA header Temp_degC_Ground; context is not astronaut cabin or body temperature."),
        ("EDA-TELEMETRY","temperature_iss","iss_hardware_temperature","numeric","°C","NASA EDA ISS experiment hardware telemetry","sensor model/accuracy not supplied in imported table","Original EDA header Temp_degC_ISS; not astronaut body temperature."),
        ("EDA-TELEMETRY","rh_ground","ground_control_relative_humidity","numeric","percent","NASA EDA experiment hardware / ground-control telemetry","sensor model/accuracy not supplied in imported table","Original EDA header RH_percent_Ground."),
        ("EDA-TELEMETRY","rh_iss","iss_hardware_relative_humidity","numeric","percent","NASA EDA ISS experiment hardware telemetry","sensor model/accuracy not supplied in imported table","Original EDA header RH_percent_ISS."),
        ("EDA-TELEMETRY","co2_ground","ground_control_carbon_dioxide","numeric","ppm","NASA EDA experiment hardware / ground-control telemetry","sensor model/accuracy not supplied in imported table","Original EDA header CO2_ppm_Ground."),
        ("EDA-TELEMETRY","co2_iss","iss_hardware_carbon_dioxide","numeric","ppm","NASA EDA ISS experiment hardware telemetry","sensor model/accuracy not supplied in imported table","Original EDA header CO2_ppm_ISS."),
        ("EDA-RADIATION","gcr","galactic_cosmic_ray_dose","numeric","mGy/day","NASA EDA mission radiation series","instrument specification not supplied in imported table","NASA EDA interface label Radiation GCR [mGy/day]."),
        ("EDA-RADIATION","saa","south_atlantic_anomaly_dose","numeric","mGy/day","NASA EDA mission radiation series","instrument specification not supplied in imported table","NASA EDA interface label Radiation SAA [mGy/day]."),
        ("EDA-RADIATION","total","total_radiation_dose","numeric","mGy/day","NASA EDA mission radiation series","instrument specification not supplied in imported table","NASA EDA interface label Radiation Total [mGy/day]."),
        ("EDA-RADIATION","accumulated","accumulated_radiation_dose","numeric","mGy/day","NASA EDA mission radiation series","instrument specification not supplied in imported table","NASA EDA interface label Radiation Accumulated [mGy/day]; preserve source label."),
        ("RADLAB-DOSTEL-2022-04-01","absorbed_dose_rate","absorbed_dose_rate","numeric","µGy/hour","ISS DosTel instruments","DosTel family ID present; precision/calibration not in API fields","NASA RadLab API defines the field and unit."),
        ("RADLAB-DOSTEL-2022-04-01","dose_equivalent_rate","dose_equivalent_rate","numeric","µSv/hour","ISS DosTel instruments","DosTel family ID present; precision/calibration not in API fields","Field defined by API; values were empty in this imported time window."),
        ("RADLAB-DOSTEL-2022-04-01","flux","particle_flux","numeric","cm^-2 sr^-1 s^-1","ISS DosTel instruments","DosTel family ID present; precision/calibration not in API fields","NASA RadLab API defines the field and unit."),
        ("RADLAB-DOSTEL-2022-04-01","latitude","spacecraft_latitude","numeric","degrees","ISS position at recorded time","Source field availability varies","NASA API says position fields are currently available for ISS."),
        ("RADLAB-DOSTEL-2022-04-01","longitude","spacecraft_longitude","numeric","degrees","ISS position at recorded time","Source field availability varies","NASA API says position fields are currently available for ISS."),
        ("RADLAB-DOSTEL-2022-04-01","altitude","spacecraft_altitude","numeric","km","ISS position at recorded time","Source field availability varies","NASA API says position fields are currently available for ISS."),
        ("RADLAB-DOSTEL-2022-04-01","b","magnetic_field_B","numeric","nT","Spacecraft location context","Source field availability varies","NASA API field B."),
        ("RADLAB-DOSTEL-2022-04-01","l","magnetic_coordinate_L","numeric","unitless","Spacecraft location context","Source field availability varies","NASA API field L."),
        ("OSD-53","reported_value","microarray_reported_value","numeric","source-defined scale (unspecified in downloaded sample tables)","Whole-blood sample microarray, source sample accessions","Platform and source value semantics should be read with the OSDR study metadata","NASA OSDR processed sample tables; blanks retained as NULL."),
        ("OSD-53","mean_preflight","mean_expression_preflight","numeric","source-defined scale","NASA OSDR fold-change summary","Source summary field","Published file header says Average PREFLIGHT."),
        ("OSD-53","mean_postflight","mean_expression_postflight","numeric","source-defined scale","NASA OSDR fold-change summary","Source summary field","Published file header says Average POSTFLIGHT."),
        ("OSD-53","fold_change_ratio","fold_change_ratio","numeric","ratio","NASA OSDR fold-change summary","Source summary field","Imported as supplied."),
        ("OSD-53","log2_ratio","log2_fold_change","numeric","log2 ratio","NASA OSDR fold-change summary","Source summary field","Imported as supplied."),
        ("OSD-53","f_test","f_test_statistic","numeric","source statistic","NASA OSDR fold-change summary","Source summary field","Imported as supplied."),
        ("OSD-53","p_value","p_value","numeric","dimensionless","NASA OSDR fold-change summary","Source summary field","Imported as supplied; no threshold-based diagnosis."),
        ("OSD-53","adjusted_p_value","adjusted_p_value","numeric","dimensionless","NASA OSDR fold-change summary","Source summary field","Imported as supplied."),
    ]
    for accession, source_field, canonical, value_type, unit, context, status, notes in field_definitions:
        did=get_dataset_id(con,accession)
        con.execute("INSERT OR IGNORE INTO dataset_fields(dataset_id,source_field,canonical_name,value_type,unit,measurement_context,specification_status,notes) VALUES(?,?,?,?,?,?,?,?)",
                    (did,source_field,canonical,value_type,unit,context,status,notes))
    for cite, url, scope in REFERENCES:
        src_name = "NASA RadLab API" if "RadLab" in cite else "NASA Environmental Data App" if "Environmental Data App" in cite else "VitalDB" if "VitalDB" in cite else "ESA Human and Robotic Exploration Data Archive (HREDA)" if cite.startswith("ESA HREDA") else "NASA Human Research Program" if "Human Research Program" in cite or "NASA HRP" in cite else "NASA OSDR"
        sid = con.execute("SELECT source_id FROM data_sources WHERE name=?", (src_name,)).fetchone()[0]
        con.execute("INSERT OR IGNORE INTO scientific_references(source_id,citation,url,accessed_at,evidence_scope,notes) VALUES(?,?,?,?,?,?)",
                    (sid, cite, url, NOW, scope, "Public source inspected on 2026-11-14."))
    hrp_ref = con.execute("SELECT reference_id FROM scientific_references WHERE citation LIKE 'NASA Human Research Program. Risks%' LIMIT 1").fetchone()[0]
    hazard_ref = con.execute("SELECT reference_id FROM scientific_references WHERE citation LIKE 'NASA Human Research Program. Five Hazards%' LIMIT 1").fetchone()[0]
    for hazard, risk, desc, scope, relevance, limitation in RISKS:
        refid = hazard_ref if risk == "Earth-independent human-system operations" else hrp_ref
        con.execute("INSERT OR IGNORE INTO risk_catalog(hazard,risk_name,description,scope_note,monitoring_relevance,limitation,reference_id) VALUES(?,?,?,?,?,?,?)",
                    (hazard, risk, desc, scope, relevance, limitation, refid))
    con.commit()

def get_dataset_id(con, accession):
    return con.execute("SELECT dataset_id FROM datasets WHERE accession=?", (accession,)).fetchone()[0]

def make_batch(con, dataset_id, started, status="PARTIAL"):
    cur = con.execute("INSERT INTO import_batches(dataset_id,started_at,completed_at,status,details) VALUES(?,?,?,?,?)",
                      (dataset_id, started, utcnow(), status, "Import in progress"))
    return cur.lastrowid

def finish_batch(con, batch_id, status, seen, inserted, skipped, digest, details):
    con.execute("UPDATE import_batches SET completed_at=?,status=?,source_records=?,inserted_records=?,skipped_records=?,sha256=?,details=? WHERE batch_id=?",
                (utcnow(), status, seen, inserted, skipped, digest, details, batch_id))

def mission_row(con, code, program="NASA EDA"):
    con.execute("INSERT OR IGNORE INTO missions(mission_code,mission_name,program,context_note) VALUES(?,?,?,?)",
                (code, code, program, "NASA EDA source mission label. Environmental values may describe experiment hardware/cages and matched ground controls; they are not astronaut clinical measurements."))
    return con.execute("SELECT mission_id FROM missions WHERE mission_code=?", (code,)).fetchone()[0]

def import_eda(con):
    started = utcnow()
    body = fetch(EDA_URL)
    digest = sha(body)
    text = body.decode("utf-8")
    match = re.search(r'<script id="data" type="application/json">(.*?)</script>', text, re.S)
    if not match:
        raise RuntimeError("NASA EDA data_tables response has no embedded data JSON")
    wrapper = json.loads(match.group(1))
    telemetry = json.loads(wrapper["telemetry_data"])
    radiation = json.loads(wrapper["radiation_data"])
    tid = get_dataset_id(con, "EDA-TELEMETRY")
    rid = get_dataset_id(con, "EDA-RADIATION")
    tb, rb = make_batch(con, tid, started), make_batch(con, rid, started)
    con.execute("INSERT INTO source_snapshots(dataset_id,batch_id,source_url,retrieved_at,media_type,sha256,content_gzip,byte_count) VALUES(?,?,?,?,?,?,?,?)",
                (tid, tb, EDA_URL, utcnow(), "text/html; charset=utf-8", digest, gzip.compress(body, mtime=0), len(body)))
    con.execute("UPDATE datasets SET sha256=?,status='IMPORTED' WHERE dataset_id IN (?,?)", (digest, tid, rid))
    env_seen = env_inserted = env_skipped = env_duplicates = 0
    for key, timestamps in telemetry.items():
        if not key.startswith("time_"):
            continue
        mission = key[5:]
        mid = mission_row(con, mission)
        arrays = {field: telemetry.get(f"{field}_{mission}", []) for field in (
            "temperature_ground", "temperature_iss", "rh_ground", "rh_iss", "co2_ground", "co2_iss")}
        for i, raw_ts in enumerate(timestamps):
            env_seen += 2
            ts = str(raw_ts)
            # EDA table labels Controller_Time_GMT; append Z only to ISO-like source values.
            ts_utc = ts.replace(" ", "T") + ("Z" if not ts.endswith("Z") else "")
            for zone, suffix in (("GROUND_CONTROL", "ground"), ("ISS_HARDWARE", "iss")):
                vals = [finite_number(arrays[f"temperature_{suffix}"][i]) if i < len(arrays[f"temperature_{suffix}"]) else None,
                        finite_number(arrays[f"rh_{suffix}"][i]) if i < len(arrays[f"rh_{suffix}"]) else None,
                        finite_number(arrays[f"co2_{suffix}"][i]) if i < len(arrays[f"co2_{suffix}"]) else None]
                if all(v is None for v in vals):
                    env_skipped += 1
                    continue
                flags=[]
                if any(i >= len(arrays[f"{f}_{suffix}"]) for f in ("temperature", "rh", "co2")):
                    flags.append("SOURCE_ARRAY_SHORT")
                if vals[1] is not None and not 0 <= vals[1] <= 100:
                    flags.append("SOURCE_VALUE_OUTSIDE_0_100_PERCENT_PRESERVED")
                try:
                    con.execute("""INSERT OR IGNORE INTO environmental_measurements
                      (dataset_id,batch_id,mission_id,timestamp_raw,timestamp_utc,zone,temperature_c,relative_humidity_percent,carbon_dioxide_ppm,source_record_ref,quality_flags)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                      (tid,tb,mid,ts,ts_utc,zone,*vals,f"{mission}:{i}:{suffix}",";".join(flags) or None))
                    changes=con.execute("SELECT changes()").fetchone()[0]
                    env_inserted += changes
                    env_duplicates += 1-changes
                except sqlite3.IntegrityError:
                    env_skipped += 1
    finish_batch(con,tb,"SUCCESS",env_seen,env_inserted,env_skipped+env_duplicates,digest,
                 f"Fetched complete EDA data_tables HTML snapshot. Rows with no usable numeric values skipped: {env_skipped}; duplicate dataset/source-record keys ignored: {env_duplicates}. Timestamps retain source text; timestamp_utc is normalized from the EDA GMT label. Missing source values remain NULL; out-of-range RH is preserved and flagged.")

    rad_seen = rad_inserted = 0
    mission_codes = sorted({k[5:] for k in radiation if k.startswith("time_")})
    for code in mission_codes:
        ts_list = radiation.get("time_"+code, [])
        mid = mission_row(con,code)
        arrays = {f:radiation.get(f+"_"+code,[]) for f in ("gcr","saa","total","accumulated")}
        for i, raw_ts in enumerate(ts_list):
            ts=str(raw_ts); ts_utc=ts+"T00:00:00Z" if re.fullmatch(r"\d{4}-\d{2}-\d{2}",ts) else ts
            for metric, arr in arrays.items():
                rad_seen += 1
                val=finite_number(arr[i]) if i < len(arr) else None
                if val is None:
                    continue
                con.execute("""INSERT OR IGNORE INTO radiation_measurements
                  (dataset_id,batch_id,mission_id,timestamp_raw,timestamp_utc,instrument_id,spacecraft,radiation_metric,value,unit,source_record_ref)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                  (rid,rb,mid,ts,ts_utc,None,"ISS",metric.upper(),val,"mGy/day",f"EDA:{code}:{i}:{metric}"))
                rad_inserted += con.execute("SELECT changes()").fetchone()[0]
    finish_batch(con,rb,"SUCCESS",rad_seen,rad_inserted,rad_seen-rad_inserted,digest,
                 "Daily mission radiation series from EDA; NASA interface labels columns mGy/day. Values retained as published, including any unusual source values.")
    con.commit()
    return {"eda_telemetry_source_rows":env_seen,"eda_telemetry_inserted":env_inserted,"eda_telemetry_skipped_no_usable_values":env_skipped,"eda_telemetry_duplicate_keys":env_duplicates,
            "eda_radiation_source_values":rad_seen,"eda_radiation_inserted":rad_inserted,"eda_sha256":digest,"eda_bytes":len(body)}

def import_radlab(con):
    started=utcnow()
    query=("spacecraft=ISS&instrument=DosTel&timestamp%3E=2022-04-01&timestamp%3C2022-04-02&"
           "timestamp&instrument_id&absorbed_dose_rate&dose_equivalent_rate&flux&latitude&longitude&altitude&B&L&format=csv")
    url=RADLAB_URL+"?"+query
    body=fetch(url)
    digest=sha(body)
    did=get_dataset_id(con,"RADLAB-DOSTEL-2022-04-01")
    batch=make_batch(con,did,started)
    con.execute("INSERT INTO source_snapshots(dataset_id,batch_id,source_url,retrieved_at,media_type,sha256,content_gzip,byte_count) VALUES(?,?,?,?,?,?,?,?)",
                (did,batch,url,utcnow(),"text/csv",digest,gzip.compress(body,mtime=0),len(body)))
    con.execute("UPDATE datasets SET sha256=?,status='IMPORTED' WHERE dataset_id=?",(digest,did))
    reader=csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    inserted=0; seen=0
    for row in reader:
        seen+=1
        timestamp=row.get("timestamp","")
        instrument=row.get("instrument_id") or row.get("instrument")
        metric_fields=(("absorbed_dose_rate","ABSORBED_DOSE_RATE","µGy/hour"),
                       ("dose_equivalent_rate","DOSE_EQUIVALENT_RATE","µSv/hour"),
                       ("flux","PARTICLE_FLUX","cm^-2 sr^-1 s^-1"))
        coords={"latitude_deg":finite_number(row.get("latitude")),"longitude_deg":finite_number(row.get("longitude")),"altitude_km":finite_number(row.get("altitude")),"magnetic_b_nt":finite_number(row.get("b")),"magnetic_l":finite_number(row.get("l"))}
        for field,metric,unit in metric_fields:
            val=finite_number(row.get(field))
            if val is None: continue
            con.execute("""INSERT OR IGNORE INTO radiation_measurements
              (dataset_id,batch_id,timestamp_raw,timestamp_utc,instrument_id,spacecraft,radiation_metric,value,unit,latitude_deg,longitude_deg,altitude_km,magnetic_b_nt,magnetic_l,source_record_ref)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (did,batch,timestamp,timestamp,instrument,row.get("spacecraft"),metric,val,unit,coords["latitude_deg"],coords["longitude_deg"],coords["altitude_km"],coords["magnetic_b_nt"],coords["magnetic_l"],f"RADLAB:{seen}:{field}"))
            inserted+=con.execute("SELECT changes()").fetchone()[0]
    finish_batch(con,batch,"SUCCESS",seen,inserted,seen*3-inserted,digest,
                 "24-hour ISS DosTel API window 2022-04-01 <= timestamp < 2022-04-02. Empty fields are not converted to zero. Source timestamps preserved as returned.")
    con.commit()
    return {"radlab_source_rows":seen,"radlab_measurements_inserted":inserted,"radlab_sha256":digest,"radlab_bytes":len(body)}

def import_osd53(con):
    """Import public processed NASA OSDR OSD-53 microarray tables and summary."""
    started=utcnow(); did=get_dataset_id(con,"OSD-53")
    files_url="https://osdr.nasa.gov/osdr/data/osd/files/53"
    metadata_url="https://osdr.nasa.gov/osdr/data/osd/meta/53"
    files_body=fetch(files_url); metadata_body=fetch(metadata_url)
    files_json=json.loads(files_body); metadata=json.loads(metadata_body)
    file_list=files_json["studies"]["OSD-53"]["study_files"]
    wanted={f["file_name"]:f for f in file_list if f["file_name"].endswith(("processed.zip","additional.zip"))}
    proc_name=next(n for n in wanted if n.endswith("processed.zip"))
    add_name=next(n for n in wanted if n.endswith("additional.zip"))
    proc_url="https://osdr.nasa.gov"+wanted[proc_name]["remote_url"]
    add_url="https://osdr.nasa.gov"+wanted[add_name]["remote_url"]
    proc_body=fetch(proc_url); add_body=fetch(add_url)
    hashes=[sha(x) for x in (files_body,metadata_body,proc_body,add_body)]
    combined=sha("".join(hashes).encode())
    con.execute("UPDATE datasets SET sha256=?,status='IMPORTED' WHERE dataset_id=?",(combined,did))
    batch=make_batch(con,did,started)
    for url,body,kind in ((files_url,files_body,"application/json"),(metadata_url,metadata_body,"application/json"),
                          (proc_url,proc_body,"application/zip"),(add_url,add_body,"application/zip")):
        con.execute("INSERT INTO source_snapshots(dataset_id,batch_id,source_url,retrieved_at,media_type,sha256,content_gzip,byte_count) VALUES(?,?,?,?,?,?,?,?)",
                    (did,batch,url,utcnow(),kind,sha(body),gzip.compress(body,mtime=0),len(body)))
    study=metadata.get("study",{}).get("OSD-53",{}).get("studies",[])
    if not study:
        raise RuntimeError("NASA OSDR OSD-53 metadata did not contain a study object")
    assay=study[0].get("assays",[])[0]
    cat_names={x.get("@id"):x.get("characteristicType",{}).get("annotationValue") for x in study[0].get("characteristicCategories",[])}
    factor_names={x.get("@id"):x.get("factorName") for x in study[0].get("factors",[])}
    sample_map={}; sample_rows=0
    for sample in assay.get("materials",{}).get("samples",[]):
        accession=sample.get("name")
        chars={cat_names.get(ch.get("category",{}).get("@id")):ch.get("value",{}).get("annotationValue") for ch in sample.get("characteristics",[])}
        factors={factor_names.get(fv.get("category",{}).get("@id")):fv.get("value",{}).get("annotationValue") for fv in sample.get("factorValues",[])}
        subject=chars.get("Study Subject")
        factor=factors.get("Spaceflight")
        cur=con.execute("""INSERT OR IGNORE INTO biomedical_samples
          (dataset_id,sample_accession,subject_label,organism,tissue,study_factor,source_record_ref)
          VALUES(?,?,?,?,?,?,?)""", (did,accession,subject,chars.get("Organism"),chars.get("Material Type"),factor,f"OSD-53:sample-metadata:{accession}"))
        sample_rows+=con.execute("SELECT changes()").fetchone()[0]
        sid=con.execute("SELECT sample_id FROM biomedical_samples WHERE dataset_id=? AND sample_accession=?",(did,accession)).fetchone()[0]
        sample_map[accession]=sid
    expression_seen=expression_rows=summary_seen=summary_rows=0
    proc=zipfile.ZipFile(io.BytesIO(proc_body))
    for member in proc.namelist():
        match=re.search(r"(GSM\d+)_sample_table\.txt$",member)
        if not match: continue
        accession=match.group(1)
        if accession not in sample_map: continue
        raw=proc.read(member).decode("utf-8-sig")
        for row in csv.DictReader(io.StringIO(raw),delimiter="\t"):
            feature=(row.get("Reporter Identifier") or "").strip()
            if not feature: continue
            expression_seen+=1
            value=finite_number((row.get("VALUE") or "").strip())
            con.execute("""INSERT OR IGNORE INTO gene_expression_measurements
              (dataset_id,batch_id,sample_id,feature_id,reported_value,value_scale,source_record_ref)
              VALUES(?,?,?,?,?,?,?)""", (did,batch,sample_map[accession],feature,value,"as provided by NASA OSDR processed sample table",f"OSD-53:{accession}:{feature}"))
            expression_rows+=con.execute("SELECT changes()").fetchone()[0]
            sample_rows=len(sample_map)
    additional=zipfile.ZipFile(io.BytesIO(add_body))
    fold_member=next(n for n in additional.namelist() if n.endswith("GSE47126_Fold_change_data.txt"))
    fold_rows=csv.reader(io.StringIO(additional.read(fold_member).decode("utf-8-sig")),delimiter="\t")
    for ix,row in enumerate(fold_rows):
        if ix<4 or not row or not row[0].strip(): continue
        summary_seen+=1
        row=row+([""]*max(0,21-len(row)))
        feature=row[0].strip(); annotation=row[1].strip() or None
        nums=[finite_number(x.strip()) for x in row[14:21]]
        con.execute("""INSERT OR IGNORE INTO differential_expression_results
          (dataset_id,batch_id,feature_id,annotation_accession,mean_preflight,mean_postflight,fold_change_ratio,log2_ratio,f_test,p_value,adjusted_p_value,comparison,source_record_ref)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (did,batch,feature,annotation,*nums,"preflight_vs_postflight","OSD-53:fold-change:"+feature))
        summary_rows+=con.execute("SELECT changes()").fetchone()[0]
    total=sample_rows+expression_rows+summary_rows
    source_total=len(sample_map)+expression_seen+summary_seen
    finish_batch(con,batch,"SUCCESS",source_total,total,source_total-total,combined,
                 f"Imported {sample_rows} sample metadata rows, {expression_rows} sample-level feature values (blank source values retained as NULL), and {summary_rows} aggregate preflight/postflight differential-expression rows. Used public processed files only; no controlled-access sequence data.")
    con.commit()
    return {"osd53_samples":sample_rows,"osd53_sample_feature_rows":expression_rows,"osd53_fold_change_rows":summary_rows,
            "osd53_source_hashes":hashes,"osd53_dataset_sha256":combined}

def generate_checkins(con):
    started=utcnow(); did=get_dataset_id(con,"SYNTHETIC-CHECKINS-V1"); batch=make_batch(con,did,started)
    seed=SEED
    # Deterministic, fictional self-report fixtures, not a validated psychometric or clinical instrument.
    subjects=[("SIM-CREW-01","Fictional avatar profile for app integration"),
              ("SIM-CREW-02","Fictional avatar profile for app integration"),
              ("SIM-CREW-03","Fictional avatar profile for app integration")]
    for code,desc in subjects:
        con.execute("INSERT OR IGNORE INTO synthetic_subjects(subject_code,description,dataset_id) VALUES(?,?,?)",(code,desc,did))
    from random import Random
    rng=Random(seed); inserted=0; start=datetime(2026,10,1,tzinfo=timezone.utc)
    for idx,(code,_) in enumerate(subjects):
        sid=con.execute("SELECT synthetic_subject_id FROM synthetic_subjects WHERE subject_code=?",(code,)).fetchone()[0]
        for day in range(30):
            # Quietly vary scores to exercise trend and filter queries; no diagnostic threshold is implied.
            fatigue=max(1,min(5,2 + (1 if 18 <= day <= 22 else 0) + rng.choice([-1,0,0,1])))
            sleep=max(1,min(5,4 - (1 if 18 <= day <= 22 else 0) + rng.choice([-1,0,0,1])))
            mood=max(1,min(5,3 + rng.choice([-1,0,0,1])))
            pain=max(0,min(10,(1 if idx==1 and day in (6,7) else 0)+rng.choice([0,0,0,1])))
            scenario="synthetic_schedule_disruption" if 18<=day<=22 else "synthetic_baseline"
            stamp=(start+timedelta(days=day)).isoformat(timespec="seconds")
            con.execute("""INSERT OR IGNORE INTO synthetic_checkins
              (dataset_id,batch_id,synthetic_subject_id,timestamp_utc,sleep_quality_1_5,fatigue_1_5,mood_1_5,pain_0_10,scenario,generation_seed,limitation)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              (did,batch,sid,stamp,sleep,fatigue,mood,pain,scenario,seed,"Fictitious software test data. Ordinal scales are interface fixtures only; not clinically validated and not astronaut observations."))
            inserted+=con.execute("SELECT changes()").fetchone()[0]
    finish_batch(con,batch,"SUCCESS",len(subjects)*30,inserted,0,None,"30 daily records per synthetic profile; fixed seed; no real personal data.")
    con.commit()
    return {"synthetic_checkins_inserted":inserted,"synthetic_subjects":len(subjects),"seed":seed}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",type=Path,default=DEFAULT_DB)
    p.add_argument("--skip-network",action="store_true",help="Do not fetch NASA public data; only seed metadata and synthetic fixtures.")
    args=p.parse_args()
    con=connect(args.db)
    seed_catalog(con)
    report={}
    if not args.skip_network:
        report.update(import_eda(con))
        report.update(import_radlab(con))
        report.update(import_osd53(con))
    report.update(generate_checkins(con))
    con.execute("PRAGMA optimize")
    report["db_path"]=str(args.db)
    report["build_time_utc"]=utcnow()
    print(json.dumps(report,indent=2))
    con.close()

if __name__=="__main__":
    main()
