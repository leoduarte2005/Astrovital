"""Behavioral checks for operational migrations, clinical fixtures and read-only access."""
import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from database.tools import generate_intelligence_seeds as generator
from database.tools import operational
from database.tools.clinical_repository import ClinicalRepository

ROOT=Path(__file__).resolve().parents[2]


class OperationalTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='edgespace-operational-')
        self.addCleanup(temp.cleanup)
        self.directory=Path(temp.name)
        self.path=self.directory/'operational.db'
        operational.migrate(self.path)
        self.writer=sqlite3.connect(self.path)
        self.writer.execute('PRAGMA foreign_keys=ON')
        self.addCleanup(self.writer.close)

    def test_clean_database_passes_entire_acceptance_checklist(self):
        result=operational.validate(self.path)
        self.assertTrue(result['passed'],result)
        self.assertEqual(result['counts']['clinical_reports'],28)
        self.assertEqual(result['counts']['causal_conditions'],26)
        self.assertEqual(result['golden_cases']['passed'],25)
        self.assertEqual(self.writer.execute('PRAGMA journal_mode').fetchone()[0],'wal')

    def test_migrations_run_once_without_changing_existing_records(self):
        self.writer.execute("UPDATE crew_profiles SET name='User edited name' WHERE crew_id='crew_001'")
        self.writer.commit()
        self.assertEqual(operational.migrate(self.path),[])
        self.assertEqual(self.writer.execute('SELECT COUNT(*) FROM schema_version').fetchone()[0],4)
        self.assertEqual(self.writer.execute("SELECT name FROM crew_profiles WHERE crew_id='crew_001'").fetchone()[0],'User edited name')

    def test_failed_migration_rolls_back_ddl_and_ledger(self):
        folder=self.directory/'invalid'
        folder.mkdir()
        (folder/'0005_invalid.sql').write_text('CREATE TABLE must_rollback(value);\nINSERT INTO unknown_table VALUES (1);\n')
        with self.assertRaises(sqlite3.OperationalError):
            operational.migrate(self.path,folder)
        self.assertIsNone(self.writer.execute("SELECT name FROM sqlite_master WHERE name='must_rollback'").fetchone())
        self.assertEqual(self.writer.execute('SELECT COUNT(*) FROM schema_version').fetchone()[0],4)

    def test_fts_insert_update_delete_and_ranked_search(self):
        with ClinicalRepository(self.path) as repo:
            rows=repo.search_reports('cefaleia OR SANS OR CO2')
            self.assertTrue(rows)
            self.assertEqual([r['rank'] for r in rows],sorted(r['rank'] for r in rows))
        self.writer.execute("UPDATE clinical_reports SET symptoms_text='uniquefirsttoken' WHERE report_id='sans_viip'")
        self.assertEqual(self.writer.execute("SELECT count(*) FROM clinical_reports_fts WHERE clinical_reports_fts MATCH 'uniquefirsttoken'").fetchone()[0],1)
        self.writer.execute("UPDATE clinical_reports SET symptoms_text='uniquesecondtoken' WHERE report_id='sans_viip'")
        self.assertEqual(self.writer.execute("SELECT count(*) FROM clinical_reports_fts WHERE clinical_reports_fts MATCH 'uniquefirsttoken'").fetchone()[0],0)
        self.writer.execute("INSERT INTO protocols(protocol_id,name,description) VALUES ('test-protocol','uniquethirdtoken','sample')")
        self.assertEqual(self.writer.execute("SELECT count(*) FROM protocols_fts WHERE protocols_fts MATCH 'uniquethirdtoken'").fetchone()[0],1)
        self.writer.execute("UPDATE protocols SET rich_steps_json='[\"uniquefourthtoken\"]' WHERE protocol_id='test-protocol'")
        self.assertEqual(self.writer.execute("SELECT count(*) FROM protocols_fts WHERE protocols_fts MATCH 'uniquefourthtoken'").fetchone()[0],1)
        self.writer.execute("DELETE FROM protocols WHERE protocol_id='test-protocol'")
        self.assertEqual(self.writer.execute("SELECT count(*) FROM protocols_fts WHERE protocols_fts MATCH 'uniquefourthtoken'").fetchone()[0],0)

    def test_upgrade_rebuilds_fts_for_existing_rows(self):
        with sqlite3.connect(self.directory/'upgrade.db') as c:
            c.execute('PRAGMA foreign_keys=ON')
            for name in ('0001_operational_schema.sql','0002_operational_seeds.sql'):
                c.executescript((operational.MIGRATIONS/name).read_text())
            c.execute("INSERT INTO clinical_reports VALUES ('test','test','Gravity Fields','PHYSIOLOGICAL','CARDIOVASCULAR_FLUIDS','existingtoken','description','symptoms','countermeasures','LOCAL','content')")
            c.execute("INSERT INTO protocols(protocol_id,name,description) VALUES ('test','existingtoken','description')")
            c.commit()
            c.executescript((operational.MIGRATIONS/'0003_intelligence_and_longitudinal.sql').read_text())
            for table in ('clinical_reports_fts','protocols_fts'):
                self.assertEqual(c.execute(f"SELECT count(*) FROM {table} WHERE {table} MATCH 'existingtoken'").fetchone()[0],1)

    def test_baseline_vector_and_single_active_constraints(self):
        for column,value in [('mean_json','[1]'),('std_json',json.dumps([0.0]*64)),('mean_json',json.dumps(['invalid']*64))]:
            with self.subTest(column=column,value=value[:20]):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.writer.execute(f"UPDATE individual_baselines SET {column}=? WHERE crew_id='crew_001'",(value,))
                self.writer.rollback()
        columns=[r[1] for r in self.writer.execute('PRAGMA table_info(individual_baselines)')]
        row=list(self.writer.execute("SELECT * FROM individual_baselines WHERE crew_id='crew_001'").fetchone())
        row[columns.index('baseline_id')]='second-active'
        row[columns.index('version')]=2
        with self.assertRaises(sqlite3.IntegrityError):
            self.writer.execute('INSERT INTO individual_baselines VALUES ('+','.join('?' for _ in row)+')',row)

    def test_memory_uniqueness_and_foreign_keys(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.writer.execute("INSERT INTO crew_clinical_memory VALUES ('duplicate','crew_001','PREFERENCE','preferred_language','en',1,'user',1,1,1,'REAL')")
        self.writer.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.writer.execute("INSERT INTO audit_log(ts_us,crew_id,event_type,details) VALUES (1,'unknown','event','{}')")

    def test_read_only_repository_and_longitudinal_windows(self):
        with ClinicalRepository(self.path) as repo:
            with self.assertRaises(sqlite3.OperationalError):
                repo.connection.execute("UPDATE crew_profiles SET name='not allowed'")
            for days,count in [(3,3),(7,7),(30,7)]:
                self.assertEqual(len(repo.rollups('crew_001',days)),count)
            self.assertEqual(len(repo.protocol('amsler_grid')['rich_steps']),3)
            with self.assertRaises(ValueError):
                repo.assess_fixture('crew_001',{})

    def test_personal_baselines_exercise_context_and_unknown_are_distinct(self):
        with ClinicalRepository(self.path) as repo:
            metrics={'heart_rate_bpm':105,'exercise_recent':0}
            first=repo.assess_fixture('crew_001',metrics,allow_engineering=True)
            second=repo.assess_fixture('crew_002',metrics,allow_engineering=True)
            self.assertEqual([m['condition_id'] for m in first['matches']],['CARDIOVASCULAR_DECONDITIONING'])
            self.assertEqual(second['matches'],[])
            missing=repo.assess_fixture('crew_001',{'spo2_pct':None},allow_engineering=True)
            self.assertIn('HYPOXIA',missing['unknown_conditions'])
            self.assertEqual(missing['matches'],[])

    def test_answered_questions_survive_reopening(self):
        self.writer.execute("INSERT INTO crew_clinical_memory VALUES ('answered','crew_001','ANSWERED_TOPIC','SANS-Q1','yes',1,'user',1,1,1,'REAL')")
        self.writer.commit()
        with ClinicalRepository(self.path) as repo:
            result=repo.assess_fixture('crew_001',{'amsler_abnormal':1},allow_engineering=True)
            self.assertEqual(result['matches'][0]['questions'],[])

    def test_dataset_synchronization_missingness_and_reproducibility(self):
        for path,content in generator.build_outputs().items():
            self.assertEqual((ROOT/path).read_bytes(),content.encode('utf-8'),path)
        csi=[json.loads(line) for line in (ROOT/'knowledge-base/datasets/synthetic_csi/samples.jsonl').read_text().splitlines()]
        with (ROOT/'knowledge-base/datasets/synthetic_peripherals/samples.csv').open() as stream:
            peripherals=list(csv.DictReader(stream))
        self.assertEqual(len(csi),1080)
        self.assertEqual({(r['crew_id'],r['ts_us']) for r in csi},{(r['crew_id'],int(r['ts_us'])) for r in peripherals})
        self.assertEqual({r['posture'] for r in csi},set(generator.POSTURES))
        self.assertEqual(sum(r['features'] is None for r in csi),342)
        self.assertEqual(sum(r['spo2_pct']=='' for r in peripherals),18)
        self.assertTrue(all(r['data_class']=='SYNTHETIC' for r in csi+peripherals))

    def test_research_snapshot_is_explicitly_protected(self):
        with self.assertRaisesRegex(ValueError,'research snapshot'):
            operational.migrate(operational.RESEARCH)


if __name__=='__main__':
    unittest.main()
