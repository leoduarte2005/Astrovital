-- 0002_operational_seeds.sql
-- EdgeSpace Phase 2: crew profiles, protocols and clinical knowledge base (FTS5 via triggers).
-- Applied by central/internal/store/migrate.go inside tx.Begin()/tx.Commit().
-- Idempotent. No PRAGMA, no explicit BEGIN/COMMIT.
-- Requires 0001_operational_schema.sql.
--
-- Quantitative ISS references come from the published aggregates transcribed in
-- database/space_health_sqlite/scripts/import_published_physiology.py (group-level
-- aggregates, not individual data). Records without a cited number carry no invented value.

-- ---------------------------------------------------------------------------
-- crew_profiles
-- INSERT OR IGNORE: never overwrite baseline_path / mission_day already updated by calibration.
-- crew_003 keeps baseline_path = '' so Central reports calibration_required=true.
-- thresholds_json keys follow contracts.Threshold JSON tags (metric_name, *_high, *_low).
-- ---------------------------------------------------------------------------

INSERT OR IGNORE INTO crew_profiles
    (crew_id, name, role, mission_day, age, baseline_path, thresholds_json)
VALUES
    ('crew_001', 'Cmdr. Silva', 'Commander', 42, 41,
     'models/profiles/baseline_crew_001.json',
     '{"co2_ppm":{"metric_name":"co2_ppm","yellow_high":1000,"red_high":3500},"spo2_pct":{"metric_name":"spo2_pct","yellow_high":0,"red_high":0,"yellow_low":94,"red_low":90},"heart_rate_bpm":{"metric_name":"heart_rate_bpm","yellow_high":110,"red_high":140,"yellow_low":45,"red_low":38}}'),
    ('crew_002', 'Dr. Costa', 'Flight Surgeon', 42, 38,
     'models/profiles/baseline_crew_002.json',
     '{"co2_ppm":{"metric_name":"co2_ppm","yellow_high":1000,"red_high":3500},"spo2_pct":{"metric_name":"spo2_pct","yellow_high":0,"red_high":0,"yellow_low":94,"red_low":90},"heart_rate_bpm":{"metric_name":"heart_rate_bpm","yellow_high":110,"red_high":140,"yellow_low":45,"red_low":38}}'),
    ('crew_003', 'Eng. Sato', 'Flight Engineer', 42, 35,
     '',
     '{"co2_ppm":{"metric_name":"co2_ppm","yellow_high":1000,"red_high":3500},"spo2_pct":{"metric_name":"spo2_pct","yellow_high":0,"red_high":0,"yellow_low":94,"red_low":90},"heart_rate_bpm":{"metric_name":"heart_rate_bpm","yellow_high":110,"red_high":140,"yellow_low":45,"red_low":38}}');

-- ---------------------------------------------------------------------------
-- protocols (reference content: upsert so richer text wins on re-run)
-- ---------------------------------------------------------------------------

INSERT INTO protocols (protocol_id, name, subsystems_json, description, steps_json)
VALUES
    ('amsler_grid',
     'Amsler Grid Ocular Self-Exam (SANS/VIIP)',
     '["NEURO_OCULAR_SANS"]',
     'Visual screening for metamorphopsia or scotoma associated with Spaceflight Associated Neuro-ocular Syndrome.',
     '["Position Amsler grid at 30 cm under uniform cabin lighting.","Cover left eye and fixate on central black dot with right eye.","Note any wavy, blurred, distorted, or missing grid lines.","Repeat with left eye and record result via SELF_EXAM.","Escalate to Flight Surgeon if new distortion persists on two consecutive days."]'),
    ('capillary_blood',
     'Capillary Blood Micro-Sample',
     '["IMMUNE_HEMATO_NUTRITION"]',
     'Fingerstick capillary sample for hematocrit, lactate, and immune markers.',
     '["Warm fingertip and disinfect with alcohol swab.","Perform lateral fingerstick with sterile safety lancet.","Wipe first drop, fill microcuvette, and apply sterile gauze.","Dispose of lancet in sharps container and log sample time via SELF_EXAM."]'),
    ('ultrasound_onsd',
     'Ocular Ultrasound Optic Nerve Sheath Diameter (ONSD)',
     '["NEURO_OCULAR_SANS"]',
     'B-mode ultrasound measurement 3 mm posterior to globe to screen elevated ICP.',
     '["Apply sterile acoustic gel over closed upper eyelid.","Acquire transverse and sagittal globe views with linear probe.","Measure optic nerve sheath diameter 3 mm behind retina (alert if > 5.0 mm).","Repeat on the contralateral eye and record both values via SELF_EXAM."]'),
    ('blood_pressure',
     'Resting & Orthostatic Blood Pressure Check',
     '["CARDIOVASCULAR_FLUIDS"]',
     'Cuff blood pressure measurement for fluid-shift and orthostatic evaluation. ISS reference (wearable cohort, n=17): median SBP 127 mmHg preflight vs 116-117 mmHg in flight; DBP 87 vs 72 mmHg.',
     '["Rest quietly for 5 minutes with cuff at heart level.","Record systolic/diastolic pressure and resting heart rate.","Repeat after lower-body negative pressure or thigh-cuff change if indicated.","Log values via SELF_EXAM and flag a fall in pulse pressure with a heart-rate rise of 30 bpm or more."]'),
    ('temperature',
     'Core / Tympanic Temperature Measurement',
     '["IMMUNE_HEMATO_NUTRITION"]',
     'Core temperature check for fever, thermal stress, or circadian shift.',
     '["Ensure probe cover is clean and intact.","Measure tympanic or oral temperature and wait for steady tone.","Log reading via SELF_EXAM if >= 37.8 C or <= 35.5 C.","Repeat after 15 minutes if a borderline reading follows exercise."]')
ON CONFLICT(protocol_id) DO UPDATE SET
    name            = excluded.name,
    subsystems_json = excluded.subsystems_json,
    description     = excluded.description,
    steps_json      = excluded.steps_json;

-- ---------------------------------------------------------------------------
-- clinical_reports: 5 hazards + 11 physiological risks + 8 behavioral/biochemical risks.
-- Upsert fires clinical_reports_au, which refreshes clinical_reports_fts.
-- FTS indexes: id, source_id, title, subsystem, description, content.
-- ---------------------------------------------------------------------------

-- ===== 5 HAZARDS (Perigos NASA HRP) =====
INSERT INTO clinical_reports
    (id, source_id, hazard, category, subsystem, title, description, symptoms_text, countermeasures_text, escalation, content)
VALUES
    ('hazard_space_radiation', 'NASA-HRP-HAZ-RADIATION', 'Space Radiation', 'HAZARD', 'NEUROBEHAVIORAL_RADIATION',
     'Perigo: Radiação Espacial / Space Radiation (SPE, GCR)',
     'Exposição a eventos de partículas solares (SPE) e raios cósmicos galácticos (GCR) fora da proteção magnética terrestre. NASA HRP associa radiação a risco de câncer, efeitos no sistema nervoso central e estresse oxidativo. Dosimetria é evidência ambiental, não diagnóstico individual.',
     'náusea, nausea, vômito, vomiting, fadiga, fatigue, mal-estar, malaise, dor de cabeça, cefaleia, headache, tontura, dizziness, visão turva, blurred vision, radiação, radiation, SPE, GCR',
     'Abrigo de maior blindagem (storm shelter, water wall); verificar dosímetros pessoais; confirmar alerta SPE com a Central; hidratação e antiemético se náusea prodrômica; monitorar sinais vitais.',
     'STORE_AND_FORWARD',
     'Perigo / Hazard: radiação, radiation, SPE, GCR, solar particle event, dosímetro, dosimeter, storm shelter, MODE_RADIATION_ALERT. Sintomas / symptoms: náusea, fadiga, fatigue, cefaleia, dor de cabeça, headache, tontura. Condições relacionadas: radiation_ros, cns_radiation_effects, radiation_cancer_risk. Referência quantitativa ISS: nenhum valor individual de dose é inferido neste banco; HRV <= 30 ms é usado só como sinal autonômico auxiliar.'),
    ('hazard_isolation_confinement', 'NASA-HRP-HAZ-ISOLATION', 'Isolation and Confinement', 'HAZARD', 'NEUROBEHAVIORAL_RADIATION',
     'Perigo: Isolamento e Confinamento / Isolation and Confinement',
     'Isolamento, confinamento e rotinas restritas afetam saúde comportamental, sono, coesão de equipe e desempenho da tripulação em missões longas.',
     'insônia, insomnia, fadiga, fatigue, irritabilidade, irritability, humor deprimido, low mood, ansiedade, anxiety, conflito de equipe, team conflict, sono ruim, poor sleep',
     'Check-ins de autorrelato, higiene do sono, luz circadiana, contato de apoio com solo, revisão de carga de trabalho.',
     'LOCAL',
     'Perigo / Hazard: isolamento, confinamento, isolation, confinement, saúde comportamental, behavioral health, insônia, insomnia, fadiga, fatigue. Condições relacionadas: behavioral_health_psychiatric, inadequate_teamwork, sleep_immune_deprivation. Referência: HRV e FC basal servem só como tendência; check-ins sintéticos não substituem apoio humano.'),
    ('hazard_distance_from_earth', 'NASA-HRP-HAZ-DISTANCE', 'Distance from Earth', 'HAZARD', 'IMMUNE_HEMATO_NUTRITION',
     'Perigo: Distância da Terra / Distance from Earth (autonomia médica)',
     'Distância limita comunicação, reabastecimento e evacuação médica. Operação independente da Terra exige armazenamento local, protocolos pré-aprovados e fila store-and-forward para o Flight Surgeon.',
     'atraso de comunicação, communication delay, falta de suprimento, supply shortage, sem evacuação, no evacuation, estresse, stress',
     'Operar offline-first; usar protocolos pré-aprovados; enfileirar relatórios em store_and_forward_outbox; priorizar autoexame guiado.',
     'STORE_AND_FORWARD',
     'Perigo / Hazard: distância, distance, Earth-independent, autonomia médica, store-and-forward, outbox, offline-first, communication delay, atraso. Condição relacionada: earth_independent_operations. Referência: este banco não oferece decisão médica autônoma nem procedimento de voo.')
ON CONFLICT(id) DO UPDATE SET
    source_id = excluded.source_id, hazard = excluded.hazard, category = excluded.category,
    subsystem = excluded.subsystem, title = excluded.title, description = excluded.description,
    symptoms_text = excluded.symptoms_text, countermeasures_text = excluded.countermeasures_text,
    escalation = excluded.escalation, content = excluded.content;

INSERT INTO clinical_reports
    (id, source_id, hazard, category, subsystem, title, description, symptoms_text, countermeasures_text, escalation, content)
VALUES
    ('hazard_gravity_fields', 'NASA-HRP-HAZ-GRAVITY', 'Gravity Fields', 'HAZARD', 'CARDIOVASCULAR_FLUIDS',
     'Perigo: Campos Gravitacionais / Gravity Fields (microgravidade)',
     'Microgravidade causa redistribuição cefálica de fluidos, adaptação cardiovascular, perda óssea e muscular e SANS/VIIP. ISS (coorte wearable, n=17): FC mediana 66 bpm pré-voo e 61 bpm no dia 6 de voo; PAS mediana 127 mmHg pré-voo e 116-117 mmHg em voo.',
     'cefaleia, dor de cabeça, headache, visão turva, blurred vision, SANS, VIIP, congestão nasal, nasal congestion, face inchada, facial puffiness, tontura ortostática, orthostatic dizziness, fluid shift',
     'Thigh cuffs / Braslet, LBNP, Grade de Amsler, ARED, monitorar PA e FC em repouso e ortostase.',
     'CREW',
     'Perigo / Hazard: microgravidade, microgravity, gravity, fluid shift, SANS, VIIP, cefaleia, dor de cabeça, headache, visão turva, blurred vision. Referência ISS (PMC12484674, n=17): FC 66 bpm BDC, 61 bpm FD6, 62 bpm FD37, 61 bpm FD159, 79 bpm R+3; PAS 127, 121, 116, 117 e 131 mmHg; PAD 87, 78, 72, 72 e 88 mmHg. Condições relacionadas: sans_viip, cv_fluid_shift_orthostatic, reduced_cardiorespiratory_fitness, bone_loss_renal_stone, altered_immune_responses.'),
    ('hazard_hostile_closed_environments', 'NASA-HRP-HAZ-ENVIRONMENT', 'Hostile/Closed Environments', 'HAZARD', 'RESPIRATORY_ATMOSPHERE',
     'Perigo: Ambientes Hostis e Fechados / Hostile-Closed Environments',
     'Habitat fechado expõe a tripulação a CO2 elevado, hipóxia, qualidade do ar, microbioma alterado, nutrição limitada e risco de doença descompressiva em EVA.',
     'dor de cabeça, headache, cefaleia, falta de ar, dyspnea, hipercapnia, hypercapnia, hipóxia, hypoxia, CO2, confusão, confusion, tontura, dizziness, cianose, cyanosis',
     'Verificar sensor SCD40, CDRA e vedação; oxigênio suplementar se SpO2 <= 92%; ventilação local; repressurização em suspeita de DCS.',
     'CREW',
     'Perigo / Hazard: ambiente fechado, closed environment, CO2, hipercapnia, hypercapnia, hipóxia, hypoxia, DCS, microbioma, nutrição. Limiares do grafo: CO2 >= 1500 ppm indício, >= 3000 ppm crítico; SpO2 <= 94% e pressão <= 750 hPa para hipóxia. Condições relacionadas: hypercapnia_co2, hypoxia, dcs_post_eva, host_microorganism_interactions, inadequate_nutrition.')
ON CONFLICT(id) DO UPDATE SET
    source_id = excluded.source_id, hazard = excluded.hazard, category = excluded.category,
    subsystem = excluded.subsystem, title = excluded.title, description = excluded.description,
    symptoms_text = excluded.symptoms_text, countermeasures_text = excluded.countermeasures_text,
    escalation = excluded.escalation, content = excluded.content;

-- ===== 11 PHYSIOLOGICAL RISKS =====
INSERT INTO clinical_reports
    (id, source_id, hazard, category, subsystem, title, description, symptoms_text, countermeasures_text, escalation, content)
VALUES
    ('sans_viip', 'NASA-HRP-SANS', 'Gravity Fields', 'PHYSIOLOGICAL', 'NEURO_OCULAR_SANS',
     'SANS / VIIP (Fluid Shift Cefálico) - Spaceflight Associated Neuro-ocular Syndrome',
     'Alterações estruturais de olho e cérebro associadas ao voo espacial, ligadas ao deslocamento cefálico de fluidos. Quadro típico: cefaleia, visão turva, pressão ocular, papiledema. Sensores genéricos ESP32/Wi-Fi não confirmam SANS; exige avaliação clínica validada. Grade de Amsler e ultrassom ONSD (> 5.0 mm) são triagem a bordo.',
     'cefaleia, dor de cabeça, headache, visão turva, blurred vision, SANS, VIIP, pressão ocular, eye pressure, papiledema, papilledema, congestão nasal, nasal congestion, face inchada, facial puffiness, fluid shift',
     '1. Grade de Amsler (Amsler Grid). 2. Thigh Cuffs (Braslet) ou LBNP para reduzir fluid shift cefálico. 3. Complexo B (folato, B6, B12) conforme protocolo NASA-HRP-SANS. 4. Registrar SELF_EXAM e encaminhar ao Flight Surgeon (Store-and-Forward).',
     'CREW',
     'SANS, VIIP, headache, cefaleia, dor de cabeça, blurred vision, visão turva, papiledema, fluid shift, Amsler Grid, ONSD, ultrassom ocular, Thigh Cuffs, Braslet, LBNP. Regras do grafo: CO2 < 1500 ppm (LR 1.6), postura supine/prone (LR 1.8), mission_day >= 7 (LR 2.1), anomaly_score >= 0.40 (LR 1.5). Referência ISS (JAMA Netw Open 2019, n=11): volume sistólico sentado 86 mL (dia 50) e 85 mL (dia 150) cai para 60 e 57 mL com LBNP; FC 60 e 59 bpm sobe para 70 e 72 bpm. Protocolos: amsler_grid, ultrasound_onsd.'),
    ('hypercapnia_co2', 'NASA-HRP-CO2', 'Hostile/Closed Environments', 'PHYSIOLOGICAL', 'RESPIRATORY_ATMOSPHERE',
     'Hipercapnia por CO2 / High Carbon Dioxide and Air Quality',
     'CO2 elevado em habitat fechado causa cefaleia, tontura, dispneia, fadiga e confusão. Limiares do sistema: >= 1500 ppm suspeita, >= 3000 ppm crítico (SCD40). Dados de CO2 do banco são ambientais e não provam a causa de sintomas.',
     'dor de cabeça, cefaleia, headache, tontura, dizziness, fadiga, fatigue, falta de ar, dyspnea, confusão, confusion, náusea, nausea, pele corada, flushed skin, CO2, hipercapnia, hypercapnia',
     '1. Verificar SCD40 e depuradores CDRA / cartuchos LiOH. 2. Aumentar ventilação local. 3. Reduzir esforço até CO2 < 1000 ppm. 4. Se CO2 >= 3000 ppm ou confusão, usar máscara de O2 e alertar a tripulação.',
     'CREW',
     'CO2, hipercapnia, hypercapnia, ppm, SCD40, CDRA, LiOH, scrubber, dor de cabeça, cefaleia, headache, dyspnea, falta de ar, dizziness. Regras do grafo: co2_ppm >= 1500 (LR 5.5), >= 3000 (LR 8.5), respiration_hz >= 0.32 (LR 2.2), heart_rate_bpm >= 85 (LR 1.5). Limiares de crew_profiles: CO2 amarelo 1000 ppm, vermelho 3500 ppm.'),
    ('hypoxia', 'NASA-HRP-HYPOXIA', 'Hostile/Closed Environments', 'PHYSIOLOGICAL', 'RESPIRATORY_ATMOSPHERE',
     'Hipóxia de Cabine / Hypoxia and Low Oxygen',
     'Queda de O2 ou da pressão de cabine reduz a saturação arterial. Sinais: dispneia, tontura, confusão, cianose. SpO2 fisiológica (MAX30102) e O2 ambiental são fluxos distintos.',
     'hipóxia, hypoxia, falta de ar, dyspnea, tontura, dizziness, confusão, confusion, cianose, cyanosis, dor de cabeça, headache, fadiga, fatigue, SpO2, dessaturação',
     '1. Confirmar SpO2 (MAX30102) e pressão (BME280). 2. Inspecionar suprimento de O2 e vedação. 3. O2 suplementar se SpO2 <= 92%. 4. Escalonar STORE_AND_FORWARD.',
     'STORE_AND_FORWARD',
     'hipóxia, hypoxia, SpO2, MAX30102, BME280, pressão de cabine, cabin pressure, cianose, cyanosis, dessaturação. Regras do grafo: spo2_pct <= 94 (LR 6.5), pressure_hpa <= 750 (LR 4.5), respiration_hz >= 0.35 (LR 2.0), heart_rate_bpm >= 95 (LR 1.8). Limiares de crew_profiles: SpO2 amarelo 94%, vermelho 90%.')
ON CONFLICT(id) DO UPDATE SET
    source_id = excluded.source_id, hazard = excluded.hazard, category = excluded.category,
    subsystem = excluded.subsystem, title = excluded.title, description = excluded.description,
    symptoms_text = excluded.symptoms_text, countermeasures_text = excluded.countermeasures_text,
    escalation = excluded.escalation, content = excluded.content;

INSERT INTO clinical_reports
    (id, source_id, hazard, category, subsystem, title, description, symptoms_text, countermeasures_text, escalation, content)
VALUES
    ('bone_loss_renal_stone', 'NASA-HRP-BONE-RENAL', 'Gravity Fields', 'PHYSIOLOGICAL', 'MUSCULOSKELETAL_POSTURE',
     'Perda Óssea / Risco de Cálculo Renal - Spaceflight-induced Bone Changes',
     'Reabsorção óssea e hipercalciúria crescem em microgravidade e elevam o risco de cálculo renal. ISS (n=51, DXA lombar): sem ARED a BMD caiu 0,047 g/cm² (-0,75 %/mês); com ARED caiu 0,021 g/cm² (-0,35 %/mês); com ARED + bisfosfonato subiu 0,028 g/cm² (+0,57 %/mês). Os valores não prescrevem tratamento.',
     'dor no flanco, flank pain, dor lombar, back pain, hematúria, hematuria, disúria, dysuria, náusea, nausea, dor óssea, bone pain, cálculo renal, kidney stone',
     '1. Hidratação oral > 2,5 L/dia. 2. Fita urinária (hematúria/pH) e ultrassom renal a bordo. 3. Revisar adesão a ARED e citrato de potássio. 4. Dor intensa ou febre: analgesia protocolada e notificar Flight Surgeon.',
     'CREW',
     'perda óssea, bone loss, BMD, DXA, ARED, bisfosfonato, bisphosphonate, cálculo renal, kidney stone, flank pain, hematúria, dor lombar. Regras do grafo: mission_day >= 14 (LR 2.0), heart_rate_bpm >= 90 (LR 1.7). Referência ISS (Osteoporos Int 2025, Table 2, n=24/20/7): BMD lombar pré-voo 1,070 / 1,092 / 1,040 g/cm² e pós-voo 1,023 / 1,071 / 1,067 g/cm² para Pre-ARED / ARED / ARED + bisfosfonato. Revisão sistemática (npj Microgravity 2020, ~189 viajantes) e coorte T-score n=94: recuperação incompleta em 1 ano; FRAX quadril 10 anos 0,09 % pré-voo e 0,11 % 1 ano pós-missão. Tíbia distal (n=17): -4,3 a -2,9 % de resistência óssea.'),
    ('cv_fluid_shift_orthostatic', 'NASA-HRP-CV-FLUID', 'Gravity Fields', 'PHYSIOLOGICAL', 'CARDIOVASCULAR_FLUIDS',
     'Fluid Shift Cardiovascular e Intolerância Ortostática / Cardiovascular Adaptation',
     'Em voo a pressão arterial cai e o volume sistólico sobe; no pouso há risco de intolerância ortostática. ISS (n=8): FC 24 h 64 bpm pré-voo e 63 bpm em voo; volume sistólico +35 ± 10 %, débito cardíaco +41 ± 9 %, resistência vascular sistêmica -39 ± 4 %, PA ambulatorial -8 a -10 mmHg. Pós-voo imediato (supino): VS 104,4 para 87,4 mL; RPT 15,8 para 20,8 mmHg·min/L (p<0,05).',
     'tontura ao levantar, orthostatic dizziness, pré-síncope, presyncope, palpitação, palpitations, pressão baixa, hypotension, taquicardia, tachycardia, fadiga, fatigue, desmaio, fainting',
     'Thigh cuffs, LBNP, hidratação e sal conforme protocolo, PA e FC em repouso e ortostase (protocolo blood_pressure), monitorar pulso de chegada e FC em postura.',
     'CREW',
     'ortostase, orthostatic intolerance, LBNP, thigh cuffs, leg cuff, pressão arterial, blood pressure, FC, heart rate, volume sistólico, stroke volume, débito cardíaco, cardiac output, hipotensão. Referência ISS: coorte wearable (n=17) PAS 127 mmHg pré-voo para 116 mmHg no dia 37 e 131 mmHg em R+3; FC 66 para 79 bpm em R+3. Cosmonautas (n=5): 2 com aumento de FC ≈ 30 bpm ao ficar de pé e queda de pressão de pulso. Pulse arrival time: FC +≈10 bpm pós-voo (p<0,05). Teste inflight leg cuff (n=8) não prevê hipotensão ortostática pós-voo.'),
    ('dcs_post_eva', 'NASA-HRP-DCS', 'Hostile/Closed Environments', 'PHYSIOLOGICAL', 'CARDIOVASCULAR_FLUIDS',
     'Doença Descompressiva pós-EVA (DCS) / Decompression Sickness',
     'Bolhas de gás após despressurização em EVA causam dor articular, dispneia, parestesia e confusão. Reconhecer em tempo hábil muda o desfecho; este banco não fornece diagnóstico nem procedimento de tratamento.',
     'dor articular, joint pain, parestesia, paresthesia, formigamento, tingling, dor no peito, chest pain, falta de ar, dyspnea, tontura, dizziness, confusão, confusion, chokes, DCS, EVA',
     '1. O2 100% em máscara de alta vazão. 2. Imobilizar membro e avaliar déficit neurológico. 3. Repressurização em traje ou câmara hiperbárica de bordo. 4. Escalonar alerta médico (STORE_AND_FORWARD).',
     'STORE_AND_FORWARD',
     'DCS, decompression sickness, doença descompressiva, EVA, extraveicular, spacewalk, parestesia, paresthesia, chokes, dor articular, joint pain, oxigênio 100%. Regras do grafo: eva_context = 1 (LR 6.0), spo2_pct <= 94 (LR 2.5), heart_rate_bpm >= 95 (LR 1.8). Sem valor quantitativo ISS transcrito para DCS neste banco.')
ON CONFLICT(id) DO UPDATE SET
    source_id = excluded.source_id, hazard = excluded.hazard, category = excluded.category,
    subsystem = excluded.subsystem, title = excluded.title, description = excluded.description,
    symptoms_text = excluded.symptoms_text, countermeasures_text = excluded.countermeasures_text,
    escalation = excluded.escalation, content = excluded.content;

INSERT INTO clinical_reports
    (id, source_id, hazard, category, subsystem, title, description, symptoms_text, countermeasures_text, escalation, content)
VALUES
    ('radiation_ros', 'NASA-HRP-RADIATION', 'Space Radiation', 'PHYSIOLOGICAL', 'NEUROBEHAVIORAL_RADIATION',
     'Exposição à Radiação / Estresse Oxidativo (SPE/GCR)',
     'Eventos de partículas solares (SPE) e raios cósmicos (GCR) causam estresse oxidativo e sintomas prodrômicos: náusea, fadiga, mal-estar, cefaleia. Queda de HRV (<= 30 ms) é sinal autonômico auxiliar.',
     'náusea, nausea, fadiga, fatigue, cefaleia, dor de cabeça, headache, mal-estar, malaise, tontura, dizziness, visão turva, blurred vision, radiação, radiation, SPE',
     '1. Abrigo de maior blindagem (storm shelter / water wall). 2. Verificar dosímetros e confirmar SPE com a Central. 3. Hidratação e protocolo antioxidante/antiemético se náusea prodrômica. 4. Monitorar sinais vitais.',
     'STORE_AND_FORWARD',
     'radiação, radiation, SPE, GCR, solar particle event, estresse oxidativo, oxidative stress, dosímetro, náusea, fadiga, cefaleia, dor de cabeça, headache, MODE_RADIATION_ALERT, storm shelter. Regras do grafo: radiation_context = 1 (LR 6.0), hrv_ms <= 30 (LR 1.8). Sem dose individual transcrita neste banco.'),
    ('radiation_cancer_risk', 'NASA-HRP-RAD-CANCER', 'Space Radiation', 'PHYSIOLOGICAL', 'NEUROBEHAVIORAL_RADIATION',
     'Risco de Câncer por Radiação / Radiation-induced Cancer Risk',
     'Exposição à radiação espacial pode aumentar o risco de câncer a longo prazo. Dosimetria é instrumental e ambiental, não dose pessoal, salvo dosímetro pessoal validado.',
     'sem sintomas agudos, no acute symptoms, radiação, radiation, câncer, cancer, dose acumulada, cumulative dose',
     'Vincular séries de dose à missão e ao tempo; nunca inferir risco médico individual só a partir de dados de instrumento.',
     'LOCAL',
     'câncer, cancer, radiação, radiation, dose acumulada, cumulative dose, dosímetro, dosimeter, risco de longo prazo, long-term risk. Limitação: este banco não estabelece efeito clínico individual nem causalidade.'),
    ('reduced_cardiorespiratory_fitness', 'NASA-HRP-FITNESS', 'Gravity Fields', 'PHYSIOLOGICAL', 'MUSCULOSKELETAL_POSTURE',
     'Condicionamento Cardiorrespiratório e Musculoesquelético Reduzido / Reduced Fitness',
     'Perda de massa óssea, força muscular e capacidade cardiovascular requer exercício e monitoramento. ISS (wearable, n=17): volume sistólico relativo ao pré-voo 1,36 (dia 6), 1,15 (dia 37) e 1,26 (dia 159); débito cardíaco relativo 1,27, 1,09 e 1,16. DXA quadril: T-score -0,31 do pré-voo a 5 dias pós-missão (n=94).',
     'fadiga, fatigue, fraqueza muscular, muscle weakness, dor muscular, muscle pain, intolerância ao exercício, exercise intolerance, falta de ar ao esforço, exertional dyspnea',
     'Exercício resistivo e aeróbico (ARED, esteira), registro de sessões, monitorar FC e recuperação, revisão por Flight Surgeon.',
     'LOCAL',
     'condicionamento, fitness, ARED, exercício, exercise, atrofia muscular, muscle atrophy, volume sistólico, stroke volume, débito cardíaco, cardiac output, fadiga, fatigue, FC, heart rate. Sem prescrição de exercício codificada neste banco.'),
    ('altered_immune_responses', 'NASA-HRP-IMMUNE', 'Gravity Fields', 'PHYSIOLOGICAL', 'IMMUNE_HEMATO_NUTRITION',
     'Resposta Imune Alterada / Altered Immune System Responses',
     'Estresse de voo pode alterar a resposta imune e reativar vírus latentes. Sinais: febre, lesão cutânea, mal-estar. Protocolos de apoio: temperature e capillary_blood.',
     'febre, fever, lesão de pele, rash, erupção cutânea, mal-estar, malaise, fadiga, fatigue, infecção, infection, reativação viral, viral reactivation',
     'Medir temperatura (protocolo temperature), micro-amostra capilar (capillary_blood), registrar SELF_EXAM e enviar ao Flight Surgeon.',
     'STORE_AND_FORWARD',
     'imunidade, immune, febre, fever, rash, reativação viral, viral reactivation, temperatura, temperature, capillary blood, hematócrito. Regra do grafo (sleep_immune_deprivation): temp_c >= 37,5 (LR 2.2). Sem valores imunológicos de astronautas importados neste banco.'),
    ('host_microorganism_interactions', 'NASA-HRP-MICROBIOME', 'Hostile/Closed Environments', 'PHYSIOLOGICAL', 'IMMUNE_HEMATO_NUTRITION',
     'Interações Hospedeiro-Microrganismo / Host-Microorganism Interactions',
     'Microbiomas de pele e intestino mudam em voo e podem modificar o risco de doença infecciosa em habitat fechado.',
     'diarreia, diarrhea, dor abdominal, abdominal pain, infecção de pele, skin infection, febre, fever, rash',
     'Higiene de habitat, monitorar sintomas, registrar SELF_EXAM, enviar relatório ao Flight Surgeon.',
     'LOCAL',
     'microbioma, microbiome, microrganismo, microorganism, infecção, infection, pele, skin, intestino, gut, OSDR. Limitação: nenhum resultado de microbioma importado neste banco.')
ON CONFLICT(id) DO UPDATE SET
    source_id = excluded.source_id, hazard = excluded.hazard, category = excluded.category,
    subsystem = excluded.subsystem, title = excluded.title, description = excluded.description,
    symptoms_text = excluded.symptoms_text, countermeasures_text = excluded.countermeasures_text,
    escalation = excluded.escalation, content = excluded.content;

-- ===== 8 BEHAVIORAL / BIOCHEMICAL RISKS =====
INSERT INTO clinical_reports
    (id, source_id, hazard, category, subsystem, title, description, symptoms_text, countermeasures_text, escalation, content)
VALUES
    ('sleep_immune_deprivation', 'NASA-HRP-BMed-IMMUNE', 'Isolation and Confinement', 'BEHAVIORAL', 'IMMUNE_HEMATO_NUTRITION',
     'Privação de Sono / Desregulação Circadiana e Imune / Inadequate Sleep',
     'Perda de sono, carga de trabalho e horários irregulares rompem o ritmo circadiano e reduzem o desempenho. HRV <= 30 ms (RMSSD) e temperatura >= 37,5 C indicam estresse autonômico/imune. Escores sintéticos são só fixtures de interface.',
     'insônia, insomnia, fadiga, fatigue, sonolência, sleepiness, sono ruim, poor sleep, cefaleia, dor de cabeça, headache, confusão, confusion, mal-estar, malaise',
     '1. Revisar sono nas últimas 24 h e tendência de HRV. 2. Ajustar iluminação circadiana (menos luz azul 2 h antes). 3. Suspender estimulantes 6 h antes do sono e reduzir carga. 4. Registrar SELF_EXAM se houver febre ou lesão cutânea.',
     'LOCAL',
     'insônia, insomnia, fadiga, fatigue, sono, sleep, circadiano, circadian, HRV, RMSSD, luz azul, blue light, ritmo, schedule. Regras do grafo: hrv_ms <= 30 (LR 2.6), temp_c >= 37,5 (LR 2.2), heart_rate_bpm >= 78 (LR 1.4).'),
    ('behavioral_health_psychiatric', 'NASA-HRP-BHP', 'Isolation and Confinement', 'BEHAVIORAL', 'NEUROBEHAVIORAL_RADIATION',
     'Saúde Comportamental e Psiquiátrica / Behavioral Health and Psychiatric Risk',
     'Isolamento e confinamento afetam humor, ansiedade e funcionamento da tripulação. Apoio é não clínico: tendências de autorrelato, sem triagem diagnóstica nem substituição de suporte humano.',
     'ansiedade, anxiety, humor deprimido, low mood, irritabilidade, irritability, insônia, insomnia, fadiga, fatigue, isolamento, isolation, desmotivação, low motivation',
     'Check-ins de autorrelato de apoio, contato com solo e Flight Surgeon, rotina de sono e exercício, revisão de carga de trabalho.',
     'CREW',
     'saúde comportamental, behavioral health, ansiedade, anxiety, depressão, depression, humor, mood, isolamento, isolation, confinamento, confinement, estresse, stress. Limitação: check-ins sintéticos são fictícios e não fazem diagnóstico.'),
    ('inadequate_teamwork', 'NASA-HRP-TEAM', 'Isolation and Confinement', 'BEHAVIORAL', 'NEUROBEHAVIORAL_RADIATION',
     'Trabalho em Equipe e Comunicação Inadequados / Inadequate Teamwork',
     'Falhas de comunicação e coesão afetam segurança e desempenho da missão. Dados de equipe só entram com consentimento; sem conclusões individuais a partir de dados sintéticos.',
     'conflito, conflict, falha de comunicação, miscommunication, tensão na equipe, team tension, irritabilidade, irritability, estresse, stress',
     'Briefings estruturados, mediação do comandante, canal de feedback, apoio do solo.',
     'LOCAL',
     'teamwork, trabalho em equipe, comunicação, communication, coesão, cohesion, conflito, conflict, comandante, commander. Limitação: sem conclusões individuais.'),
    ('earth_independent_operations', 'NASA-HRP-EARTH-INDEP', 'Distance from Earth', 'BEHAVIORAL', 'IMMUNE_HEMATO_NUTRITION',
     'Operações Independentes da Terra / Earth-independent Operations',
     'Distância limita comunicação, suprimentos e apoio médico em tempo hábil. Sistema deve funcionar offline, preservar procedência e recuperar protocolos aprovados; não toma decisão médica autônoma.',
     'atraso de comunicação, communication delay, estresse, stress, ansiedade, anxiety, incerteza, uncertainty',
     'Offline-first, fila store-and-forward, protocolos aprovados, autoexame guiado, relatório periódico ao Flight Surgeon.',
     'STORE_AND_FORWARD',
     'distância, distance, offline-first, store-and-forward, outbox, atraso, delay, autonomia, autonomy, Earth-independent, protocolo, protocol.')
ON CONFLICT(id) DO UPDATE SET
    source_id = excluded.source_id, hazard = excluded.hazard, category = excluded.category,
    subsystem = excluded.subsystem, title = excluded.title, description = excluded.description,
    symptoms_text = excluded.symptoms_text, countermeasures_text = excluded.countermeasures_text,
    escalation = excluded.escalation, content = excluded.content;

INSERT INTO clinical_reports
    (id, source_id, hazard, category, subsystem, title, description, symptoms_text, countermeasures_text, escalation, content)
VALUES
    ('iron_overload', 'NASA-HRP-IRON-HEMATO', 'Gravity Fields', 'BIOCHEMICAL', 'IMMUNE_HEMATO_NUTRITION',
     'Sobrecarga de Ferro / Hemoconcentração / Iron Overload',
     'Acúmulo progressivo de ferro em missões prolongadas (>= 21 dias) pode causar fadiga, artralgia e desconforto abdominal. Desvio persistente em relação ao baseline individual reforça a suspeita.',
     'fadiga, fatigue, dor articular, joint pain, dor abdominal, abdominal pain, mal-estar, malaise, tontura, dizziness',
     '1. Revisar cardápio e reduzir alimentos fortificados com ferro. 2. Verificar hematologia/ferritina no kit laboratorial. 3. Manter hidratação e registrar artralgia. 4. Enviar resumo clínico periódico ao Flight Surgeon.',
     'LOCAL',
     'ferro, iron, ferritina, ferritin, hemoconcentração, hemoconcentration, hematócrito, hematocrit, artralgia, joint pain, capillary blood. Regras do grafo: mission_day >= 21 (LR 2.0), anomaly_score >= 0.40 (LR 1.4). Protocolo: capillary_blood.'),
    ('inadequate_nutrition', 'NASA-HRP-NUTRITION', 'Hostile/Closed Environments', 'BIOCHEMICAL', 'IMMUNE_HEMATO_NUTRITION',
     'Nutrição e Alimentação Inadequadas / Inadequate Food and Nutrition',
     'Adequação do sistema alimentar afeta saúde, desempenho e massa óssea e muscular. Futuros registros de nutrição e suplementos podem ser armazenados; este banco não prescreve suplementação.',
     'fadiga, fatigue, perda de peso, weight loss, fraqueza, weakness, tontura, dizziness, apetite reduzido, low appetite',
     'Revisar registro alimentar, hidratação, vitamina D e proteína conforme protocolo de bordo, relatório ao Flight Surgeon.',
     'LOCAL',
     'nutrição, nutrition, alimentação, food, vitamina D, vitamin D, proteína, protein, perda de peso, weight loss, hidratação, hydration, fadiga, fatigue. Limitação: sem registros nutricionais importados.'),
    ('cns_radiation_effects', 'NASA-HRP-RAD-CNS', 'Space Radiation', 'BEHAVIORAL', 'NEUROBEHAVIORAL_RADIATION',
     'Efeitos da Radiação no SNC e no Desempenho / CNS and Performance Effects',
     'NASA aponta possíveis efeitos cognitivos, motores e comportamentais da radiação. Séries de radiação da missão são só contexto; este banco não estabelece efeito clínico individual.',
     'lapso de atenção, attention lapse, lentidão cognitiva, slowed cognition, cefaleia, dor de cabeça, headache, fadiga, fatigue, tontura, dizziness, radiação, radiation',
     'Contextualizar séries de radiação e autorrelatos; revisão por Flight Surgeon; reduzir tarefas críticas em fadiga.',
     'STORE_AND_FORWARD',
     'SNC, CNS, cognição, cognition, desempenho, performance, radiação, radiation, SPE, GCR, atenção, attention, fadiga, fatigue, dor de cabeça, headache.'),
    ('one_carbon_b_vitamins', 'NASA-HRP-ONE-CARBON', 'Gravity Fields', 'BIOCHEMICAL', 'NEURO_OCULAR_SANS',
     'Metabolismo de Um Carbono e Vitaminas B / One-carbon Metabolism (SANS)',
     'Alterações no metabolismo de um carbono (folato, B6, B12) são associadas a SANS. Protocolo NASA-HRP-SANS prevê Complexo B como contramedida bioquímica; não substitui avaliação oftalmológica.',
     'visão turva, blurred vision, cefaleia, dor de cabeça, headache, fadiga, fatigue, formigamento, tingling, SANS, VIIP',
     'Complexo B (folato, B6, B12) conforme protocolo; amostra capilar (capillary_blood); Grade de Amsler; relatório ao Flight Surgeon.',
     'CREW',
     'folato, folate, B6, B12, homocisteína, homocysteine, um carbono, one-carbon, SANS, VIIP, visão turva, blurred vision, Complexo B, B-complex. Protocolos: amsler_grid, capillary_blood. Sem valor quantitativo ISS transcrito para estes marcadores.')
ON CONFLICT(id) DO UPDATE SET
    source_id = excluded.source_id, hazard = excluded.hazard, category = excluded.category,
    subsystem = excluded.subsystem, title = excluded.title, description = excluded.description,
    symptoms_text = excluded.symptoms_text, countermeasures_text = excluded.countermeasures_text,
    escalation = excluded.escalation, content = excluded.content;
