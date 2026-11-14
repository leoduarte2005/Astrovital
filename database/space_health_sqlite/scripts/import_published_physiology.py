#!/usr/bin/env python3
"""Import the supplied published physiology corpus offline in one transaction.

Values and article locators are retained from the supplied transcription.
Importing this module has no database side effects.
"""

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT.parents[1] / "var" / "space_health_demo.db"


def import_values(con):
    """Upsert the supplied corpus while preserving unrelated publications."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Each article is discoverable even when its full numeric tables were unavailable for structured transcription.
    pubs = [
    ('Evidence of effective cardiovascular countermeasures during spaceflights: insights from wearable monitoring','10.1038/s41526-025-00522-8','https://pmc.ncbi.nlm.nih.gov/articles/PMC12484674/','BP, HR, cardiac output and stroke volume at preflight, in-flight and recovery; n=17','AGGREGATES_IMPORTED','Tables 1-2; medians and quartiles transcribed; one cohort; published, non-individual aggregates.'),
    ('Fluid shifts, vasodilatation and ambulatory blood pressure reduction during long duration spaceflight','10.1113/jphysiol.2014.284869','https://pmc.ncbi.nlm.nih.gov/articles/PMC4324706/','24-hour ambulatory BP, HR, cardiac output, stroke volume and systemic vascular resistance; n=8','AGGREGATES_IMPORTED','Aggregate estimates were transcribed from the public abstract/text; not individual time-series.'),
    ('Assessment of Jugular Venous Blood Flow Stasis and Thrombosis During Spaceflight','10.1001/jamanetworkopen.2019.16565','https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2755307','Cardiovascular measures across posture, flight days 50/150, LBNP and postflight; n=11','AGGREGATES_IMPORTED','Full Table 2 values (means and 95% CI) transcribed.'),
    ('A systematic review and meta-analysis of bone loss in space travelers','10.1038/s41526-020-00111-x','https://pmc.ncbi.nlm.nih.gov/articles/PMC7200725/','Pooled regional bone-density changes; 25 articles, about 189 space travelers','AGGREGATES_IMPORTED','Pooled percent changes and 95% CI transcribed from Results.'),
    ('Bone Health in Space Flight: Incomplete Bone Mineral Density Convalescence at 1 Year Postmission Without Increased Fracture Risk','10.1007/s00223-025-01391-5','https://pmc.ncbi.nlm.nih.gov/articles/PMC12626757/','DXA BMD T-score change and recovery; n=94 astronauts','AGGREGATES_IMPORTED','Aggregate change from article Results; unit retained as T-score change, not g/cm2.'),
    ('The Effects of Spaceflight Countermeasures on Trabecular Bone Score of the Lumbar Spine','10.1007/s11657-025-01624-2','https://ntrs.nasa.gov/api/citations/20250001173/downloads/OSIN-D-25-00175_R2_TBS%20Resubmission.pdf?attachment=true','Lumbar BMD and TBS under Pre-ARED, ARED and ARED plus bisphosphonate groups; n=51','AGGREGATES_IMPORTED','Published table group means and SDs transcribed for lumbar BMD by countermeasure group.'),
    ('Lower body negative pressure identifies altered central vein characteristics without accompanying changes to baroreflexes in astronauts within hours of landing','10.1038/s41526-023-00325-9','https://pmc.ncbi.nlm.nih.gov/articles/PMC10786840/','Postflight supine hemodynamics and LBNP; aggregate results','AGGREGATES_IMPORTED','Explicit aggregate SV and TPR means ± SD and nonsignificant BP description; no individual values.'),
    ('Inflight leg cuff test does not identify the risk for orthostatic hypotension after long-duration spaceflight','10.1152/japplphysiol.00607.2019','https://pmc.ncbi.nlm.nih.gov/articles/PMC6789148/','Orthostatic test and continuous HR/BP; 8 astronauts','AGGREGATES_IMPORTED','Public abstract and results values transcribed, including MAP response to cuff deflation and a reported initial orthostatic hypotension case.'),
    ('Orthostatic blood pressure control before and after spaceflight, determined by time-domain baroreflex method','10.1152/japplphysiol.01219.2004','https://pubmed.ncbi.nlm.nih.gov/15649869/','Standing HR and pulse-pressure response after spaceflight; 5 cosmonauts','AGGREGATES_IMPORTED','Public abstract reports counts and approximate HR increase; no subject-level values.'),
    ('Impact of Prolonged Spaceflight on Orthostatic Tolerance During Ambulation and Blood Pressure Profiles in Astronauts','10.1152/japplphysiol.00442.2019','https://pubmed.ncbi.nlm.nih.gov/31319685/','Ambulatory BP and orthostatic tolerance','AGGREGATES_IMPORTED','Public abstract numeric values transcribed: 24-hour SBP, distribution statistics and zero orthostatic events during routine activities.'),
    ('Interrelationships between pulse arrival time and arterial blood pressure during postural transitions before and after spaceflight','10.1152/japplphysiol.00317.2019','https://pmc.ncbi.nlm.nih.gov/articles/PMC6850984/','Posture transition BP/HR and pulse-arrival time','AGGREGATES_IMPORTED','Abstract estimate of approximately 10 bpm postflight HR increase stored.'),
    ('Cortical and trabecular bone mineral loss from the spine and hip in long-duration spaceflight','10.1359/jbmr.2004.19.6.1006','https://pubmed.ncbi.nlm.nih.gov/15125798/','ISS DXA bone-density outcomes; n=14','PUBLIC_ARTICLE_NO_TRANSCRIBED_VALUES','Article catalogued; numeric full-text tables not transcribed in this pass.'),
    ('Pre-flight exercise and bone metabolism predict unloading-induced bone loss due to spaceflight','10.1136/bjsports-2020-103602','https://pmc.ncbi.nlm.nih.gov/articles/PMC8862023/','Tibial bone density, microarchitecture and strength; n=17','AGGREGATES_IMPORTED','Public abstract reports median percentage ranges; stored as ranges with endpoint values.'),
    ('Men and women in space: bone loss and kidney stone risk after long-duration spaceflight','10.1038/nature12975','https://pubmed.ncbi.nlm.nih.gov/24470067/','DXA and bone metabolism; n=42 ISS astronauts','PUBLIC_ARTICLE_NO_TRANSCRIBED_VALUES','Article catalogued; numeric tables not transcribed in this pass.'),
    ('Autonomic cardiovascular and respiratory control during prolonged spaceflights aboard the International Space Station','10.1152/japplphysiol.00137.2007','https://journals.physiology.org/doi/10.1152/japplphysiol.00137.2007','HR, HRV, SBP, DBP and orthostatic tests; n=8','PUBLIC_ARTICLE_NO_TRANSCRIBED_VALUES','Public article reviewed; detailed table not transcribed in this pass.'),
    ('Cardiac Effects of Long-Duration Space Flight','10.1016/j.jacc.2023.05.058','https://www.jacc.org/doi/10.1016/j.jacc.2023.05.058','24-hour BP, Holter, stroke volume and cardiac measures; n=10','AGGREGATES_IMPORTED','Public article table means ± SD transcribed for HR, stroke volume and BP; n=10 cohort.'),
    ('Adaptation of heart rate and blood pressure to short and long duration space missions','10.1016/j.jelectrocard.2009.07.011','https://pubmed.ncbi.nlm.nih.gov/19833299/','HR and arterial BP over nine ISS missions in 11 astronauts','PUBLIC_ARTICLE_NO_TRANSCRIBED_VALUES','Article catalogued; numerical tables not transcribed in this pass.'),
    ('A systematic review of cardiovascular adaptations of space travel','10.3389/fphys.2023.1187507','https://pmc.ncbi.nlm.nih.gov/articles/PMC10614241/','Review of spaceflight cardiovascular changes','PUBLIC_ARTICLE_NO_TRANSCRIBED_VALUES','Review catalogued; used for identifying cardiovascular endpoints and supporting studies.')
    ]
    for citation,doi,url,subject,status,note in pubs:
        con.execute('''INSERT INTO physiology_publications(citation,doi,article_url,subject,public_data_status,extraction_note,accessed_at)
                       VALUES(?,?,?,?,?,?,?) ON CONFLICT(citation) DO UPDATE SET doi=excluded.doi,article_url=excluded.article_url,subject=excluded.subject,public_data_status=excluded.public_data_status,extraction_note=excluded.extraction_note,accessed_at=excluded.accessed_at''', (citation,doi,url,subject,status,note,now))
    ids={row[0]:row[1] for row in con.execute('SELECT citation,publication_id FROM physiology_publications')}
    # tuples: citation, domain, code, label, value, unit, stat, disp type, low, high, n, cohort, phase, posture, intervention, locator, p, note
    rows=[]
    def add(c,domain,code,label,v,unit,stat,dt=None,lo=None,hi=None,n=None,cohort=None,phase=None,posture=None,intervention=None,loc='article result',p=None,note=None):
     dispval=lo if dt=='SD' else None
     if dt=='SD': lo=hi=None
     rows.append((ids[c],domain,code,label,v,unit,stat,dt,dispval,lo,hi,n,cohort,phase,posture,intervention,loc,p,note))
    W=pubs[0][0]
    # Wearable study, Table 1 HR and Table 2 BP/SV/CO. Timepoints preserve the paper's stated visits.
    for phase,n,val,q1,q3 in [('BDC',17,66,61,75),('FD6±2',17,61,56,67),('FD37±4',17,62,54,68),('FD159±4',17,61,60,69),('R+3',15,79,70,81),('R+8',17,71,67,76)]:
     add(W,'HEART_RATE','HR_BPM','Heart rate',val,'bpm','MEDIAN','IQR',q1,q3,n,'ISS cosmonaut cohort',phase,'wearable recording',None,'Table 1',note='Published median [Q1,Q3].')
    # Table 2 medians [Q1,Q3]
    for phase,n,sbp,s1,s3,dbp,d1,d3,sv,sv1,sv3,co,co1,co3 in [
     ('BDC',17,127,122,132,87,81,89,1.00,1.00,1.00,1.00,1.00,1.00),('FD6±2',17,121,117,128,78,67,82,1.36,.82,1.73,1.27,.75,1.58),('FD37±4',17,116,110,123,72,66,80,1.15,.85,1.52,1.09,.77,1.58),('FD159±4',17,117,109,122,72,68,79,1.26,.82,1.56,1.16,.79,1.46),('R+3',15,131,123,141,88,84,96,1.01,.90,1.27,1.25,1.00,1.48),('R+8',17,125,116,130,84,79,93,1.03,.81,1.29,1.11,.87,1.46)]:
     add(W,'BLOOD_PRESSURE','SBP_MMHG','Systolic blood pressure',sbp,'mmHg','MEDIAN','IQR',s1,s3,n,'ISS cosmonaut cohort',phase,'wearable recording',None,'Table 2')
     add(W,'BLOOD_PRESSURE','DBP_MMHG','Diastolic blood pressure',dbp,'mmHg','MEDIAN','IQR',d1,d3,n,'ISS cosmonaut cohort',phase,'wearable recording',None,'Table 2')
     add(W,'CARDIOVASCULAR_RESPONSE','STROKE_VOLUME_REL','Stroke volume, relative to BDC',sv,'ratio','MEDIAN','IQR',sv1,sv3,n,'ISS cosmonaut cohort',phase,'wearable recording',None,'Table 2',note='Relative value; BDC baseline normalized to 1.00.')
     add(W,'CARDIOVASCULAR_RESPONSE','CARDIAC_OUTPUT_REL','Cardiac output, relative to BDC',co,'ratio','MEDIAN','IQR',co1,co3,n,'ISS cosmonaut cohort',phase,'wearable recording',None,'Table 2',note='Relative value; BDC baseline normalized to 1.00.')
    # Ambulatory spaceflight study aggregates
    F=pubs[1][0]
    add(F,'HEART_RATE','HR_24H','24-hour heart rate',64,'bpm','MEAN','SD',2,2,8,'ISS astronauts','Preflight','ambulatory 24 h',None,'Abstract: key points')
    add(F,'HEART_RATE','HR_24H','24-hour heart rate',63,'bpm','MEAN','SD',2,2,8,'ISS astronauts','In-flight, days 85-192','ambulatory 24 h',None,'Abstract: key points')
    add(F,'CARDIOVASCULAR_RESPONSE','SV_CHANGE_PCT','Stroke volume change',35,'percent','MEAN','SD',10,10,8,'ISS astronauts','3-6 months in flight',None,None,'Abstract: key points',p='<0.001',note='Reported increase 35–41%; paper gives SV +35±10%.')
    add(F,'CARDIOVASCULAR_RESPONSE','CO_CHANGE_PCT','Cardiac output change',41,'percent','MEAN','SD',9,9,8,'ISS astronauts','3-6 months in flight',None,None,'Abstract: key points',p='<0.001')
    add(F,'BLOOD_PRESSURE','AMBULATORY_BP_CHANGE_MMHG','24-hour ambulatory brachial BP change',-9,'mmHg','RANGE',None,-10,-8,8,'ISS astronauts','3-6 months in flight','ambulatory 24 h',None,'Abstract: key points',note='Published as reduction of 8-10 mmHg; negative sign encodes decrease.')
    add(F,'CARDIOVASCULAR_RESPONSE','SVR_CHANGE_PCT','Systemic vascular resistance change',-39,'percent','MEAN','SD',-4,4,8,'ISS astronauts','3-6 months in flight',None,None,'Abstract: key points',p='<0.001')
    # JAMA open study table 2 means (95% CI): conditions in column order.
    J=pubs[2][0]
    conds=[('Preflight','seated'),('Preflight','supine'),('Preflight','head-down tilt'),('Flight day 50','seated'),('Flight day 50','seated + LBNP'),('Flight day 150','seated'),('Flight day 150','seated + LBNP'),('Postflight','seated'),('Postflight','supine'),('Postflight','head-down tilt')]
    metrics=[('SV_ML','Stroke volume','mL',[69,89,87,86,60,85,57,66,82,91],[(63,75),(82,95),(81,93),(80,92),(53,66),(79,92),(50,63),(60,73),(76,89),(84,97)]),('CO_LMIN','Cardiac output','L/min',[4.2,4.8,4.7,5.0,4.2,5.1,3.8,4,4.8,5.2],[(3.7,4.8),(4.2,5.4),(4.1,5.3),(4.4,5.5),(3.6,4.8),(4.5,5.7),(3.3,4.4),(3.4,4.6),(4.3,5.4),(4.6,5.7)]),('HR_BPM','Heart rate','bpm',[61,54,54,60,70,59,72,61,56,56],[(58,65),(51,58),(50,57),(57,64),(66,74),(55,62),(68,76),(57,64),(52,60),(52,60)]),('MAP_MMHG','Mean arterial pressure','mmHg',[91,87,88,94,80,90,80,89,85,87],[(85,97),(81,93),(82,94),(88,100),(74,86),(84,96),(74,87),(83,95),(79,91),(81,93)]),('SBP_MMHG','Systolic blood pressure','mmHg',[119,116,119,123,119,121,116,116,115,119],[(112,126),(109,122),(113,126),(116,130),(112,127),(114,127),(108,123),(109,123),(108,122),(112,126)]),('DBP_MMHG','Diastolic blood pressure','mmHg',[77,72,73,79,61,75,62,76,69,71],[(71,82),(67,78),(67,78),(73,84),(55,66),(69,81),(56,69),(70,82),(64,75),(65,77)])]
    for code,label,unit,vals,cis in metrics:
     domain='HEART_RATE' if code=='HR_BPM' else ('BLOOD_PRESSURE' if code in ('MAP_MMHG','SBP_MMHG','DBP_MMHG') else 'CARDIOVASCULAR_RESPONSE')
     for i,(phase,posture) in enumerate(conds):
      add(J,domain,code,label,vals[i],unit,'MEAN','95% CI',cis[i][0],cis[i][1],11,'ISS crew',phase,posture,'LBNP' if 'LBNP' in posture else None,'Table 2',note='Mean (95% CI); 95% CI endpoints stored in dispersion_low/high.')
    # Ambulatory BP profile and orthostatic tolerance, 12-astronaut cohort.
    A=pubs[9][0]
    for phase,val,sd in [('Preflight',120,10),('In-flight',106,9),('Postflight',122,13)]:
     add(A,'BLOOD_PRESSURE','SBP_24H_MMHG','24-hour systolic blood pressure',val,'mmHg','MEAN','SD',sd,None,12,'ISS astronauts',phase,'ambulatory 24 h',None,'Abstract: results',p='<0.01' if phase=='In-flight' else None)
    for phase,val,sd in [('Preflight',.74,.51),('In-flight',1.43,1.00),('Postflight',.51,.42)]:
     add(A,'BLOOD_PRESSURE','SBP_SKEWNESS','Systolic blood-pressure distribution skewness',val,'dimensionless','MEAN','SD',sd,None,12,'ISS astronauts',phase,'ambulatory 24 h',None,'Abstract: results',p='0.001' if phase=='In-flight' else None)
    for phase,val,sd in [('Preflight',5.01,7.67),('In-flight',11.10,11.79),('Postflight',2.21,2.56)]:
     add(A,'BLOOD_PRESSURE','SBP_KURTOSIS','Systolic blood-pressure distribution kurtosis',val,'dimensionless','MEAN','SD',sd,None,12,'ISS astronauts',phase,'ambulatory 24 h',None,'Abstract: results',p='0.010' if phase=='In-flight' else None)
    add(A,'ORTHOSTATIC_INTOLERANCE','OI_DAILY_ACTIVITY_CASES','Orthostatic intolerance/hypotension cases during daily activity',0,'people','COUNT',None,None,None,12,'ISS astronauts','preflight and postflight','activities of daily living',None,'Abstract: results',note='No astronaut experienced OI/hypotension during activities of daily living before or after flight.')
    C=pubs[7][0]
    for phase,val,sd in [('Preflight',-19,2),('In-flight',-18,5)]:
     add(C,'ORTHOSTATIC_INTOLERANCE','MAP_RESPONSE_CUFF_DEFLATION','Mean arterial pressure response to leg-cuff deflation',val,'mmHg','MEAN','SD',sd,None,8,'ISS astronaut cohort',phase,'supine leg-cuff test','thigh cuff deflation','Abstract',note='Negative value indicates a decrease.')
    add(C,'ORTHOSTATIC_INTOLERANCE','POSTFLIGHT_INITIAL_OH_CASES','Cases with initial orthostatic hypotension on postflight supine-to-seated transition',1,'people','COUNT',None,None,None,8,'ISS astronaut cohort','postflight','supine-to-seated transition',None,'Results: text',note='One astronaut showed a large seated BP drop consistent with initial orthostatic hypotension.')
    K=pubs[15][0]
    for code,label,unit,pre,pre_sd,flight,flight_sd,pval in [('HR_BPM','Heart rate','bpm',69,9,70,12,'.967'),('SV_ML','Stroke volume','mL',81,16,77,16,'.124'),('SBP_MMHG','Brachial systolic blood pressure','mmHg',122,8,111,14,'.026'),('DBP_MMHG','Brachial diastolic blood pressure','mmHg',66,6,62,6,'.205'),('MAP_MMHG','Brachial mean arterial pressure','mmHg',85,7,79,6,'.008'),('CENTRAL_MSBP_MMHG','Central mean systolic blood pressure','mmHg',97,7,89,7,'.053')]:
     domain='HEART_RATE' if code=='HR_BPM' else ('BLOOD_PRESSURE' if code in ('SBP_MMHG','DBP_MMHG','MAP_MMHG','CENTRAL_MSBP_MMHG') else 'CARDIOVASCULAR_RESPONSE')
     for phase,v,sd in [('Preflight (L-21 to L-7)',pre,pre_sd),('In-flight (R-15)',flight,flight_sd)]:
      add(K,domain,code,label,v,unit,'MEAN','SD',sd,None,10,'ISS astronauts',phase,'24-hour measurement',None,'Table: cardiovascular measurements',p=pval,note='Mean ± SD, paired comparison.')
    # Meta-analysis estimates are percent change and 95% CI
    B=pubs[3][0]
    for code,label,val,low,high,region in [('BMD_REGION1_PCT','Bone density change, skull/neck',2.2,1.1,3.3,'skull and neck'),('BMD_REGION2_PCT','Bone density change, upper body',-1.4,-2.1,-.6,'upper limbs and thorax'),('BMD_REGION3_PCT','Bone density change, spine/pelvis',-6.2,-6.7,-5.6,'lumbar spine and pelvis'),('BMD_REGION4_PCT','Bone density change, lower limbs',-4.9,-5.6,-4.2,'lower limbs'),('BMD_REGION2_LONG_PCT','Bone density change >28 d, upper body',-.7,-1.3,-.2,'upper limbs and thorax, missions >28 d'),('BMD_REGION4_LONG_PCT','Bone density change >28 d, lower limbs',-5.4,-6.0,-4.9,'lower limbs, missions >28 d')]:
     add(B,'BONE_HEALTH',code,label,val,'% preflight','POOLED_EFFECT','95% CI',low,high,189,'pooled space-traveler studies','postflight <7 days',region,None,'Results: skeletal-site changes',note='Approximate total N across meta-analysis; region-level N varies; about 189 participants overall.')
    add(B,'BONE_HEALTH','BMD_REGION2_RATE','Bone-density change rate, upper body',-.1,'%/month','POOLED_EFFECT','95% CI',-.2,0,189,'pooled space-traveler studies','missions >30 days','upper limbs and thorax',None,'Results: rate estimates',note='Approximate total N across meta-analysis; regional subset varies.')
    add(B,'BONE_HEALTH','BMD_REGION4_RATE','Bone-density change rate, lower limbs',-.8,'%/month','POOLED_EFFECT','95% CI',-1.1,-.5,189,'pooled space-traveler studies','missions >30 days','lower limbs',None,'Results: rate estimates',note='Approximate total N across meta-analysis; regional subset varies.')
    # Bone 94-cohort changes reported in DEXA T-score units.
    B94=pubs[4][0]
    for code,label,val,region in [('FOREARM_T_SCORE_DELTA', 'Forearm DXA T-score change',-.03,'forearm'),('SPINE_T_SCORE_DELTA','Spine DXA T-score change',-.28,'spine'),('FEMORAL_NECK_T_SCORE_DELTA','Femoral-neck DXA T-score change',-.27,'femoral neck'),('TROCHANTER_T_SCORE_DELTA','Greater-trochanter DXA T-score change',-.30,'greater trochanter'),('HIP_T_SCORE_DELTA','Hip DXA T-score change',-.31,'hip')]:
     add(B94,'BONE_HEALTH',code,label,val,'T-score units','MEAN',None,None,None,94,'astronaut cohort','preflight to 5 days postmission',region,None,'Results: BMD decline preflight versus 5 days postmission',note='The article reports these as declines in DEXA T-score; not areal BMD in g/cm².')
    add(B94,'BONE_HEALTH','FRAX_HIP_10Y','10-year osteoporotic hip-fracture risk',.09,'%','MEAN',None,None,None,94,'astronaut cohort','preflight','n/a',None,'Results: fracture-risk assessment')
    add(B94,'BONE_HEALTH','FRAX_HIP_10Y','10-year osteoporotic hip-fracture risk',.11,'%','MEAN',None,None,None,94,'astronaut cohort','1-year postmission','n/a',None,'Results: fracture-risk assessment')
    # ISS bone-health countermeasure study, reported BMD means and changes (g/cm²).
    T=pubs[5][0]
    for group,n,pre,pre_sd,post,post_sd,change,change_sd,rate,rate_sd in [
     ('Pre-ARED',24,1.070,.10,1.023,.09,-.047,.03,-.75,.49),
     ('ARED',20,1.092,.11,1.071,.11,-.021,.03,-.35,.54),
     ('ARED + bisphosphonate',7,1.040,.14,1.067,.14,.028,.04,.57,.86)]:
     for phase,val,sd in [('preflight',pre,pre_sd),('postflight',post,post_sd)]:
      add(T,'BONE_HEALTH','LUMBAR_BMD_GCM2','Lumbar spine BMD',val,'g/cm²','MEAN','SD',sd,sd,n,group,phase,'lumbar spine',group,'Table 2',note='Mean ± SD; group-level published aggregate.')
     add(T,'BONE_HEALTH','LUMBAR_BMD_CHANGE_GCM2','Lumbar spine BMD absolute change',change,'g/cm²','MEAN','SD',change_sd,change_sd,n,group,'preflight to postflight','lumbar spine',group,'Table 2',note='Mean ± SD; absolute change as reported.')
     add(T,'BONE_HEALTH','LUMBAR_BMD_CHANGE_PCT_MONTH','Lumbar spine BMD percent change per month',rate,'%/month','MEAN','SD',rate_sd,rate_sd,n,group,'per month of mission','lumbar spine',group,'Table 2',note='Mean ± SD; percent change per month as reported.')
    # Landing-day postflight hemodynamics, n not restated in accessible abstract.
    L=pubs[6][0]
    add(L,'CARDIOVASCULAR_RESPONSE','SV_ML','Stroke volume',104.4,'mL','MEAN','SD',16.7,16.7,None,'astronaut cohort','preflight','supine rest',None,'Abstract',note='Published preflight mean ± SD.')
    add(L,'CARDIOVASCULAR_RESPONSE','SV_ML','Stroke volume',87.4,'mL','MEAN','SD',11.5,11.5,None,'astronaut cohort','within hours of landing','supine rest',None,'Abstract',p='<0.05',note='Published postflight mean ± SD.')
    add(L,'CARDIOVASCULAR_RESPONSE','TPR','Total peripheral resistance',15.8,'mmHg min/L','MEAN','SD',4.6,4.6,None,'astronaut cohort','preflight','supine rest',None,'Abstract')
    add(L,'CARDIOVASCULAR_RESPONSE','TPR','Total peripheral resistance',20.8,'mmHg min/L','MEAN','SD',7.1,7.1,None,'astronaut cohort','within hours of landing','supine rest',None,'Abstract',p='<0.05')
    # Orthostatic response counts.
    O=pubs[8][0]
    add(O,'ORTHOSTATIC_INTOLERANCE','STANDING_HR_INCREASE_CASES','Cases with standing HR increase approximately >=30 bpm',2,'people','COUNT',None,None,None,5,'cosmonaut cohort','postflight','standing',None,'Abstract',note='2 of 5 had pulse-pressure reduction and HR rise of approximately 30 bpm or more.')
    add(O,'ORTHOSTATIC_INTOLERANCE','STANDING_HR_INCREASE_BPM','Standing HR increase in affected participants',30,'bpm','APPROXIMATE',None,None,None,2,'affected cosmonauts','postflight','standing',None,'Abstract',note='Abstract describes approximately 30 bpm or more; not a group mean.')
    # Posture transition publication estimates.
    P=pubs[10][0]
    add(P,'ORTHOSTATIC_INTOLERANCE','HR_POSTFLIGHT_DELTA','Heart-rate increase after spaceflight',10,'bpm','APPROXIMATE',None,None,None,None,'astronaut cohort','postflight vs preflight','supine and standing',None,'Abstract',p='<0.05',note='Abstract reports approximately 10 bpm average increase; exact CI/SD not available in this transcription.')
    # Bone microarchitecture abstract range endpoints; preserve as reported range.
    E=pubs[12][0]
    for code,label,low,high,unit in [('TIBIA_STRENGTH_PCT','Distal tibial bone strength cumulative change',-4.3,-2.9,'%'),('TIBIA_TOTAL_VBMD_PCT','Distal tibial total volumetric BMD cumulative change',-4.3,-2.9,'%'),('TIBIA_TRABECULAR_VBMD_PCT','Distal tibial trabecular vBMD cumulative change',-2.6,-.8,'%'),('TIBIA_BVTV_PCT','Distal tibial bone-volume fraction cumulative change',-2.6,-.8,'%'),('TIBIA_THICKNESS_PCT','Distal tibial trabecular thickness cumulative change',-2.6,-.8,'%'),('TIBIA_CORTICAL_VBMD_PCT','Distal tibial cortical vBMD cumulative change',-2.6,-.8,'%')]:
     add(E,'BONE_HEALTH',code,label,(low+high)/2,unit,'RANGE',None,low,high,17,'ISS astronauts','postflight cumulative','distal tibia',None,'Abstract: results',note='Abstract reports range; midpoint stored in value only for sorting, exact lower/upper endpoints preserved.')
    con.executemany('DELETE FROM published_physiology_aggregates WHERE publication_id=?', [(ids[publication[0]],) for publication in pubs])
    con.executemany('''INSERT INTO published_physiology_aggregates(publication_id,domain,metric_code,metric_label,value,unit,statistic,dispersion_type,dispersion_value,dispersion_low,dispersion_high,sample_size,cohort,phase,posture,intervention,source_locator,p_value,interpretation_note)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', rows)
    return {
        "source_publications": len(pubs),
        "source_aggregate_rows": len(rows),
        "total_publications": con.execute("SELECT COUNT(*) FROM physiology_publications").fetchone()[0],
        "total_aggregate_rows": con.execute("SELECT COUNT(*) FROM published_physiology_aggregates").fetchone()[0],
        "by_domain": dict(con.execute("SELECT domain,COUNT(*) FROM published_physiology_aggregates GROUP BY domain ORDER BY domain")),
    }


def import_database(path):
    """Apply shared schema and corpus atomically, including legacy SD columns."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=5000")
        con.executescript("BEGIN IMMEDIATE;\n" + (ROOT / "schema.sql").read_text(encoding="utf-8"))
        columns = {row[1] for row in con.execute("PRAGMA table_info(published_physiology_aggregates)")}
        if "dispersion_value" not in columns:
            con.execute("ALTER TABLE published_physiology_aggregates ADD COLUMN dispersion_value REAL")
        summary = import_values(con)
        con.execute("COMMIT")
        return summary
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", nargs="?", type=Path, help="Legacy positional database path.")
    parser.add_argument("--db", type=Path, help="Target database; defaults to var/space_health_demo.db in the project.")
    args = parser.parse_args()
    if args.database is not None and args.db is not None:
        parser.error("Use either --db or the positional database path.")
    path = args.db or args.database or DEFAULT_DB
    try:
        summary = import_database(path)
    except (OSError, sqlite3.Error) as error:
        parser.exit(1, f"Published physiology import failed: {error}\n")
    print(json.dumps({"database": str(path), **summary}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
