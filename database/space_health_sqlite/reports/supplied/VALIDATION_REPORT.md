# SQLite build validation report

Generated (UTC): 2026-11-14T19:33:04+00:00
Database: `space_health.db` (496,971,776 bytes)

## Integrity checks

- SQLite integrity: **ok**
- Foreign key violations: **0**
- Environmental source-reference duplicates: **0**
- Radiation source-reference duplicates: **0**
- Invalid or mislabeled synthetic check-ins: **0**
- Real measurements missing provenance fields: **0**

## Row counts

- `data_sources`: 8
- `datasets`: 13
- `dataset_fields`: 26
- `import_batches`: 5
- `missions`: 22
- `scientific_references`: 12
- `risk_catalog`: 15
- `environmental_measurements`: 1,269,126
- `radiation_measurements`: 6,342
- `biomedical_samples`: 13
- `gene_expression_measurements`: 3,159
- `differential_expression_results`: 243
- `synthetic_subjects`: 3
- `synthetic_checkins`: 90
- `reference_parameters`: 0
- `source_snapshots`: 6
- `iss_physiology_study_catalog`: 5
- `physiology_publications`: 18
- `published_physiology_aggregates`: 161
- `missing_reason_codes`: 7
- `field_quality_events`: 781,198
- `dataset_field_completeness`: 124
- `source_row_exclusions`: 0
- `field_availability_registry`: 10
- `temporal_coverage_summary`: 44
- `field_transformation_registry`: 3

## Imported datasets

| Accession | Category | Status | Environmental rows | Radiation rows | Gene-expression rows | Differential-expression rows | Synthetic rows |
|---|---:|---|---:|---:|---:|---:|---:|
| EDA-TELEMETRY | REAL | IMPORTED | 1,269,126 | 0 | 0 | 0 | 0 |
| EDA-RADIATION | REAL | IMPORTED | 0 | 1,564 | 0 | 0 | 0 |
| RADLAB-DOSTEL-2022-04-01 | REAL | IMPORTED | 0 | 4,778 | 0 | 0 | 0 |
| NASA-HRP-RISKS | CATALOG | IMPORTED | 0 | 0 | 0 | 0 | 0 |
| NASA-OSDR-CATALOG | REFERENCE | METADATA_ONLY | 0 | 0 | 0 | 0 | 0 |
| VITALDB-CATALOG | REFERENCE | METADATA_ONLY | 0 | 0 | 0 | 0 | 0 |
| SYNTHETIC-CHECKINS-V1 | SYNTHETIC | GENERATED | 0 | 0 | 0 | 0 | 90 |
| OSD-53 | REAL | IMPORTED | 0 | 0 | 3,159 | 243 | 0 |
| HREDA-BMI-ISS | CATALOG | METADATA_ONLY | 0 | 0 | 0 | 0 | 0 |
| HREDA-CIRCA-ISS | CATALOG | METADATA_ONLY | 0 | 0 | 0 | 0 | 0 |
| HREDA-AORTA-ISS | CATALOG | METADATA_ONLY | 0 | 0 | 0 | 0 | 0 |
| HREDA-CARDIOCOG1-ISS | CATALOG | METADATA_ONLY | 0 | 0 | 0 | 0 | 0 |
| HREDA-BONEHEALTH-ISS | CATALOG | METADATA_ONLY | 0 | 0 | 0 | 0 | 0 |

## ISS physiology study catalog

- ESA HREDA discovery records: 5; invalid metadata/measurement classification rows: 0.
- Article inventory: 18 publications; numeric aggregate records: 161; orphan aggregate rows: 0.

| Domain | Aggregate records |
|---|---:|
| BLOOD_PRESSURE | 60 |
| BONE_HEALTH | 33 |
| CARDIOVASCULAR_RESPONSE | 41 |
| HEART_RATE | 20 |
| ORTHOSTATIC_INTOLERANCE | 7 |

## Missingness, completeness and temporal coverage

- Field-level missing-value events: 781,198; documented omitted source rows: 0 in 0 exclusion group(s).
- Dataset-variable completeness summaries: 124; temporal series audited: 44. No expected sample count is inferred without documented sampling frequency.
- Imputed values: 0; values remain REAL, DERIVED or SYNTHETIC as sourced/labeled.

## Environmental coverage

- Rows: 1,269,126; missions: 19; source timestamp span: 2014-04-18 00:15 to 2024-05-06 13:16.
- Non-null temperature values: 1,115,360; relative humidity values: 1,115,360; CO₂ values: 817,859.
- Relative-humidity values outside 0–100% preserved and flagged: 1,434.

| Zone | Rows |
|---|---:|
| GROUND_CONTROL | 634,563 |
| ISS_HARDWARE | 634,563 |

## Environmental rows by mission

| Mission | Rows | First source timestamp | Last source timestamp | Temp values | RH values | CO₂ values |
|---|---:|---|---|---:|---:|---:|
| APEX-03-1 | 5,434 | 2015-01-10 00:10 | 2015-01-28 23:50 | 5,434 | 5,434 | 0 |
| APEX-03-2 | 4,860 | 2015-01-26 00:20 | 2015-02-11 23:50 | 4,860 | 4,860 | 0 |
| APEX-04 | 7,082 | 2017-02-26 00:00 | 2017-03-22 13:28 | 7,073 | 7,073 | 0 |
| RR-1 | 24,174 | 2014-09-20 03:59 | 2014-11-01 03:54 | 24,174 | 24,174 | 24,174 |
| RR-10 | 86,206 | 2020-12-04 07:30 | 2021-01-13 00:00 | 84,502 | 84,502 | 74,637 |
| RR-12 | 23,570 | 2019-04-17 19:19 | 2019-05-28 18:19 | 23,570 | 23,570 | 23,570 |
| RR-18 | 201,602 | 2021-12-20 00:01 | 2022-08-20 00:00 | 100,800 | 100,800 | 0 |
| RR-19 | 20,388 | 2019-12-03 10:24 | 2020-01-07 20:10 | 20,386 | 20,386 | 20,386 |
| RR-20 | 135,952 | 2023-11-10 00:00 | 2024-04-30 00:00 | 129,270 | 129,270 | 129,270 |
| RR-23 | 105,200 | 2020-12-06 00:00 | 2021-01-15 00:22 | 100,956 | 100,956 | 91,141 |
| RR-25 | 187,526 | 2022-11-29 09:15 | 2023-02-02 11:57 | 165,419 | 165,419 | 165,419 |
| RR-28 | 122,976 | 2024-03-21 00:00 | 2024-05-06 13:16 | 122,974 | 122,974 | 122,974 |
| RR-3 | 28,770 | 2016-04-08 04:00 | 2016-05-28 03:55 | 28,770 | 28,770 | 28,770 |
| RR-5 | 38,320 | 2017-06-01 05:00 | 2017-08-08 12:57 | 38,320 | 38,320 | 38,320 |
| RR-6 | 35,144 | 2017-12-06 15:06 | 2018-02-06 14:39 | 35,144 | 35,144 | 35,144 |
| RR-7 | 43,898 | 2018-06-29 00:00 | 2018-09-18 13:58 | 43,896 | 43,896 | 43,896 |
| RR-9 | 20,158 | 2018-08-14 04:53 | 2018-09-18 04:48 | 20,158 | 20,158 | 20,158 |
| VEG-01A | 17,090 | 2014-04-18 00:15 | 2014-06-11 23:50 | 8,545 | 8,545 | 0 |
| VEG-01C | 160,776 | 2015-11-12 08:52 | 2016-01-31 23:55 | 151,109 | 151,109 | 0 |

## Import batches

| Batch | Dataset | Status | Source rows/values | Inserted | Skipped |
|---:|---|---|---:|---:|---:|
| 1 | EDA-TELEMETRY | SUCCESS | 1,269,126 | 1,269,126 | 0 |
| 2 | EDA-RADIATION | SUCCESS | 1,564 | 1,564 | 0 |
| 3 | RADLAB-DOSTEL-2022-04-01 | SUCCESS | 2,389 | 4,778 | 2,389 |
| 4 | SYNTHETIC-CHECKINS-V1 | SUCCESS | 90 | 90 | 0 |
| 5 | OSD-53 | SUCCESS | 3,415 | 3,415 | 0 |

## Interpretation limits

- NASA EDA environmental rows are experiment hardware/cage and ground-control telemetry; they are not astronaut clinical or personal data.
- NASA RadLab readings are instrument measurements, not individual dosimeter records or clinical outcomes.
- Missing numeric values are stored as NULL and classified in field_quality_events; no automatic statistical imputation has been applied. Completeness percentages for source tables use returned rows plus documented all-empty excluded rows; they do not imply time-series schedule coverage. Temporal gaps are summarized, but expected sample counts remain NULL because no validated sampling schedule was established. Sensor-failure and below-detection-limit codes are available but are not assigned without source evidence.
- Physiology article values are public study/group aggregates, not astronaut-level records. Five catalogued public articles did not have their numeric tables transcribed in this pass; this publication inventory is a research snapshot and not a claim of exhaustive discovery worldwide. OSD-53 is molecular gene-expression research data. ESA HREDA entries in iss_physiology_study_catalog are discovery metadata. Synthetic check-ins are fictional fixtures, not validated scales.
- The NASA EDA page labels time Controller_Time_GMT; source timestamps are retained and normalized to UTC form. Other source timestamps remain as returned.
- Dataset-specific reuse terms must be rechecked before redistribution or operational use.
