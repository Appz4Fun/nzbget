"""Synthetic offline contract tests; these are not native coverage evidence."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'assess.py'


class CoverageContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.src = self.root / 'source'
        (self.src / 'rust/src').mkdir(parents=True)
        (self.src / 'daemon').mkdir()
        (self.src / 'rust/src/port.rs').write_text('pub fn port() {}\n')
        (self.src / 'daemon/caller.cpp').write_text('void caller() {}\n')
        self.export = {'type': 'llvm.coverage.json.export', 'version': '2.0.1', 'data': [{
            'files': [{'filename': 'rust/src/port.rs', 'summary': {'lines': {'count': 100, 'covered': 71}}}],
            'functions': [{'name': 'port', 'count': 1, 'filenames': ['rust/src/port.rs']},
                          {'name': 'caller', 'count': 1, 'filenames': ['daemon/caller.cpp']}]}]}
        self.scope = {'schema_version': 1, 'scope_id': 'synthetic-port',
                      'source_files': [self.replacement('rust/src/port.rs', 'port')],
                      'caller_files': [{'path': 'daemon/caller.cpp', 'sha256': self.digest('daemon/caller.cpp')}],
                      'capture': {'variant':'rust_candidate', 'mode': 'production_caller', 'production_only': True, 'test_cfg_enabled': False,
                                  'completion': {'state': 'EXITED', 'exit_code': 0}, 'export_sha256': '0'*64,
                                  'binary_sha256': '1'*64, 'profile_sha256': '2'*64},
                      'required_boundaries': [{'id': 'port-call', 'rust_file': 'rust/src/port.rs', 'rust_function': 'port',
                                               'caller_file': 'daemon/caller.cpp', 'caller_function': 'caller'}],
                      'exclusions': []}

    def replacement(self, path, symbol, kind='direct_boundary'):
        sha=self.digest(path)
        return {'path':path,'sha256':sha,'cpp_origin':{'path':'daemon/retired.cpp','symbols':['original_cpp'],'sha256':'5'*64,'applicability':'baseline_metadata_only'},
                'production_symbols':[symbol], 'activation_predicate':'NZBGET_USE_RUST',
                'applicability':{'variant':'rust_candidate','kind':kind,'boundary_ids':['port-call'],'review_sha256':'3'*64,'source_sha256':sha}}

    def digest(self, path):
        return hashlib.sha256((self.src / path).read_bytes()).hexdigest()

    def run_assess(self, change=None, export_raw=None, scope_raw=None, output=None, control_setup=None, runner=None):
        if change:
            change(self.scope, self.export)
        raw = export_raw if export_raw is not None else json.dumps(self.export).encode()
        self.scope['capture']['export_sha256'] = hashlib.sha256(raw).hexdigest()
        export = self.root / 'export.json'
        scope = self.root / 'scope.json'
        export.write_bytes(raw)
        scope.write_bytes(scope_raw if scope_raw is not None else json.dumps(self.scope).encode())
        if control_setup:
            control_setup(scope, export)
        dest = output or self.root / 'result'
        launch = [str(runner), str(SCRIPT)] if runner is not None else [str(SCRIPT)]
        run = subprocess.run([sys.executable, '-I', *launch, '--scope', str(scope), '--export', str(export),
                              '--source-root', str(self.src), '--output-dir', str(dest)],
                             capture_output=True, timeout=4)
        try:
            result = json.loads((dest / 'coverage-assessment.json').read_bytes())
        except (OSError, json.JSONDecodeError):
            result = None
        return run, result, dest

    def test_expected_metrics_are_parsed_without_claiming_execution_proof(self):
        run, result, dest = self.run_assess()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(result['evidence_status'], 'VALID_STRUCTURE')
        self.assertEqual(result['files'][0]['covered_lines'], 71)
        self.assertEqual(result['target_status'], 'ABOVE_70_ALL_EXPECTED_FILES')
        self.assertFalse(result['execution_verified'])
        self.assertEqual(result['caller_reach_status'], 'COUNTERS_PRESENT_REVIEW_REQUIRED')
        self.assertEqual(result['speed_qualification'], 'NOT_ASSESSED')

    def test_exact_70_is_valid_low(self):
        run, result, _ = self.run_assess(lambda s,e: e['data'][0]['files'][0]['summary']['lines'].update(covered=70))
        self.assertEqual(run.returncode, 0)
        self.assertEqual(result['target_status'], 'LOW')

    def test_low_file_cannot_be_hidden_by_high_aggregate(self):
        (self.src / 'rust/src/other.rs').write_text('pub fn other() {}\n')
        self.scope['source_files'].append(self.replacement('rust/src/other.rs','other','helper'))
        self.export['data'][0]['functions'].append({'name':'other','count':0,'filenames':['rust/src/other.rs']})
        self.export['data'][0]['files'][0]['summary']['lines'].update(count=1000, covered=1000)
        self.export['data'][0]['files'].append({'filename': 'rust/src/other.rs', 'summary': {'lines': {'count':100,'covered':20}}})
        run, result, _ = self.run_assess()
        self.assertEqual(run.returncode, 0)
        self.assertEqual(result['aggregate']['covered_lines'], 1020)
        self.assertEqual(result['target_status'], 'LOW')

    def assert_hold(self, change=None, **kwargs):
        run, result, _ = self.run_assess(change, **kwargs)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertIsNotNone(result)
        self.assertEqual(result['evidence_status'], 'HOLD')
        self.assertEqual(result['target_status'], 'NOT_MEASURED')
        self.assertIsNone(result['aggregate'])
        self.assertFalse(result['execution_verified'])

    def test_missing_file_is_hold(self):
        self.assert_hold(lambda s,e: e['data'][0].update(files=[]))

    def test_zero_denominator_is_hold(self):
        self.assert_hold(lambda s,e: e['data'][0]['files'][0]['summary'].update(lines={'count':0,'covered':0}))

    def test_bool_count_is_hold(self):
        self.assert_hold(lambda s,e: e['data'][0]['files'][0]['summary']['lines'].update(covered=True))

    def test_float_count_is_hold(self):
        self.assert_hold(lambda s,e: e['data'][0]['files'][0]['summary']['lines'].update(count=100.0))

    def test_negative_count_is_hold(self):
        self.assert_hold(lambda s,e: e['data'][0]['files'][0]['summary']['lines'].update(covered=-1))

    def test_covered_above_total_is_hold(self):
        self.assert_hold(lambda s,e: e['data'][0]['files'][0]['summary']['lines'].update(covered=101))

    def test_duplicate_file_is_hold(self):
        self.assert_hold(lambda s,e: e['data'][0]['files'].append(copy.deepcopy(e['data'][0]['files'][0])))

    def test_duplicate_key_is_hold(self):
        self.assert_hold(export_raw=b'{"type":"a","type":"b"}')

    def test_nonfinite_export_is_hold(self):
        self.assert_hold(export_raw=b'{"data": NaN}')

    def test_malformed_export_is_hold(self):
        self.assert_hold(export_raw=b'{broken')

    def test_bad_schema_is_hold(self):
        self.assert_hold(lambda s,e: e.update(version='3.0.0'))

    def test_wrong_source_hash_is_hold(self):
        self.assert_hold(lambda s,e: s['source_files'][0].update(sha256='f'*64))

    def test_failed_capture_is_hold(self):
        self.assert_hold(lambda s,e: s['capture']['completion'].update(exit_code=1))

    def test_timeout_capture_is_hold(self):
        self.assert_hold(lambda s,e: s['capture']['completion'].update(state='TIMEOUT', exit_code=None))

    def test_caller_missing_is_hold(self):
        self.assert_hold(lambda s,e: e['data'][0].update(functions=[e['data'][0]['functions'][0]]))

    def test_zero_rust_boundary_is_hold(self):
        self.assert_hold(lambda s,e: e['data'][0]['functions'][0].update(count=0))

    def test_bool_boundary_count_is_hold(self):
        self.assert_hold(lambda s,e: e['data'][0]['functions'][0].update(count=True))

    def test_unit_mode_cannot_satisfy_production_target(self):
        run,result,_ = self.run_assess(lambda s,e: s['capture'].update(mode='unit_diagnostic', production_only=False,test_cfg_enabled=True))
        self.assertEqual(run.returncode,0)
        self.assertEqual(result['target_status'],'NOT_MEASURED')
        self.assertEqual(result['caller_reach_status'],'UNKNOWN')
        self.assertEqual(result['files'][0]['covered_lines'],71)

    def test_inline_test_capture_is_hold_for_production(self):
        self.assert_hold(lambda s,e: s['capture'].update(test_cfg_enabled=True))

    def test_path_alias_is_hold(self):
        self.assert_hold(lambda s,e: s['source_files'][0].update(path='rust/src/../src/port.rs'))

    def test_symlink_source_is_hold(self):
        source=self.src/'rust/src/port.rs'; source.rename(source.with_suffix('.real'));source.symlink_to('port.real')
        self.assert_hold()

    def test_symlink_source_ancestor_is_hold(self):
        original=self.src/'rust/src'; original.rename(self.src/'rust/real');original.symlink_to('real',target_is_directory=True)
        self.assert_hold()

    def test_hardlink_sources_are_hold(self):
        import os
        os.link(self.src/'rust/src/port.rs',self.src/'rust/src/alias.rs')
        self.scope['source_files'].append(self.replacement('rust/src/alias.rs','alias','helper'))
        self.export['data'][0]['files'].append({'filename':'rust/src/alias.rs','summary':{'lines':{'count':100,'covered':71}}})
        self.export['data'][0]['functions'].append({'name':'alias','count':1,'filenames':['rust/src/alias.rs']})
        run,result,_=self.run_assess()
        self.assertEqual(run.returncode,2)
        self.assertEqual(result['evidence_status'],'HOLD')
        self.assertIn('source/input hardlink alias',result['reasons'])

    def test_existing_output_is_untouched(self):
        dest=self.root/'result';dest.mkdir(); sentinel=dest/'coverage-assessment.json';sentinel.write_bytes(b'keep')
        run,_,_=self.run_assess(output=dest)
        self.assertEqual(run.returncode,2)
        self.assertEqual(sentinel.read_bytes(),b'keep')

    def test_unexpected_files_are_visible_not_used_in_denominator(self):
        self.export['data'][0]['files'].append({'filename':'rust/src/unrelated.rs','summary':{'lines':{'count':10000,'covered':10000}}})
        run,result,_=self.run_assess()
        self.assertEqual(run.returncode,0)
        self.assertEqual(result['aggregate']['line_count'],100)
        self.assertIn('rust/src/unrelated.rs',result['unexpected_report_files'])

    def test_production_source_cannot_be_excluded(self):
        self.assert_hold(lambda s,e:s['exclusions'].append({'path':'rust/src/port.rs','kind':'generated','sha256':self.digest('rust/src/port.rs'),'reason':'skip','review_sha256':'3'*64}))

    def test_duplicate_boundary_is_hold(self):
        self.assert_hold(lambda s,e:s['required_boundaries'].append(copy.deepcopy(s['required_boundaries'][0])))

    def test_unknown_scope_fields_are_hold(self):
        self.assert_hold(lambda s,e:s.update(caller_coverage_verified=True))

    def test_duplicate_function_record_is_hold(self):
        self.assert_hold(lambda s,e:e['data'][0]['functions'].append(copy.deepcopy(e['data'][0]['functions'][0])))

    def test_integer_parse_limit_retains_hold_and_raw(self):
        self.assert_hold(export_raw=b'{"data":'+b'9'*5000+b'}')

    def test_overflow_float_anywhere_in_export_is_hold(self):
        raw=json.dumps(self.export).encode()[:-1]+b',"unused":1e999}'
        self.assert_hold(export_raw=raw)

    def test_out_of_range_count_is_hold(self):
        self.assert_hold(lambda s,e:e['data'][0]['files'][0]['summary']['lines'].update(count=1 << 63))

    def test_bad_export_digest_is_hold(self):
        raw=json.dumps(self.export).encode()
        self.scope['capture']['export_sha256']='f'*64
        self.assert_hold(export_raw=raw, scope_raw=json.dumps(self.scope).encode())

    def test_bool_exit_code_is_hold(self):
        self.assert_hold(lambda s,e:s['capture']['completion'].update(exit_code=False))

    def test_empty_boundaries_cannot_claim_caller_view(self):
        self.assert_hold(lambda s,e:s.update(required_boundaries=[]))

    def test_function_from_wrong_file_is_not_a_boundary_hit(self):
        self.assert_hold(lambda s,e:e['data'][0]['functions'][0].update(filenames=['rust/src/unrelated.rs']))

    def test_absolute_mapped_source_path_is_accepted(self):
        self.export['data'][0]['files'][0]['filename']=str(self.src/'rust/src/port.rs')
        run,result,_=self.run_assess()
        self.assertEqual(run.returncode,0)
        self.assertEqual(len(result['files']),1)
        self.assertEqual(result['files'][0]['path'],'rust/src/port.rs')

    def test_absolute_alias_cannot_double_count(self):
        duplicate=copy.deepcopy(self.export['data'][0]['files'][0])
        duplicate['filename']=str(self.src/'rust/src/port.rs')
        self.export['data'][0]['files'].append(duplicate)
        self.assert_hold()

    def test_foreign_absolute_path_cannot_match_expected_file(self):
        self.assert_hold(lambda s,e:e['data'][0]['files'][0].update(filename='/foreign/rust/src/port.rs'))

    def test_unknown_asserted_lineage_fields_do_not_verify_execution(self):
        self.assert_hold(lambda s,e:s['capture'].update(execution_verified=True))

    def test_partial_scope_is_not_silently_accepted(self):
        self.assert_hold(lambda s,e:s['source_files'][0].update(lines=[1]))

    def test_unit_mode_need_not_have_caller_functions(self):
        self.scope['capture'].update(mode='unit_diagnostic',production_only=False,test_cfg_enabled=True)
        self.export['data'][0]['functions']=[{'name':'port','count':0,'filenames':['rust/src/port.rs']}]
        run,result,_=self.run_assess()
        self.assertEqual(run.returncode,0)
        self.assertEqual(result['caller_reach_status'],'UNKNOWN')
        self.assertEqual(result['target_status'],'NOT_MEASURED')
        self.assertFalse(result['execution_verified'])

    def test_raw_invalid_export_is_retained_unchanged(self):
        raw=b'{broken\xff'
        run,result,dest=self.run_assess(export_raw=raw)
        self.assertEqual(run.returncode,2)
        self.assertEqual((dest/'export.raw').read_bytes(),raw)
        self.assertEqual(result['input_hashes']['export_sha256'],hashlib.sha256(raw).hexdigest())

    def test_bad_configuration_flag_is_hold(self):
        self.assert_hold(lambda s,e:s['capture'].update(production_only=1))

    def test_caller_source_hash_is_required(self):
        self.assert_hold(lambda s,e:s['caller_files'][0].update(sha256='f'*64))

    def test_symlink_output_ancestor_is_rejected_without_writes(self):
        original=self.root/'destination';original.mkdir()
        alias=self.root/'alias';alias.symlink_to('destination',target_is_directory=True)
        run,result,_=self.run_assess(output=alias/'result')
        self.assertEqual(run.returncode,2)
        self.assertIsNone(result)
        self.assertEqual(list(original.iterdir()),[])

    def test_output_input_collision_does_not_modify_scope(self):
        run,result,_=self.run_assess(output=self.root/'scope.json')
        self.assertEqual(run.returncode,2)
        self.assertIsNone(result)
        self.assertTrue((self.root/'scope.json').is_file())

    def test_sources_recover_after_original_changes(self):
        original=(self.src/'rust/src/port.rs').read_bytes()
        run,result,dest=self.run_assess()
        self.assertEqual(run.returncode,0)
        (self.src/'rust/src/port.rs').write_bytes(b'changed')
        row=next(r for r in result['source_custody'] if r['path']=='rust/src/port.rs')
        self.assertEqual((dest/row['raw_path']).read_bytes(),original)
        self.assertEqual(row['observed_sha256'],hashlib.sha256(original).hexdigest())

    def test_source_mismatch_retains_actual_bytes_hash_and_expected_row(self):
        original=(self.src/'rust/src/port.rs').read_bytes()
        run,result,dest=self.run_assess(lambda s,e:s['source_files'][0].update(sha256='f'*64))
        self.assertEqual(run.returncode,2)
        row=next(r for r in result['source_custody'] if r['path']=='rust/src/port.rs')
        self.assertEqual((dest/row['raw_path']).read_bytes(),original)
        self.assertEqual(row['observed_sha256'],hashlib.sha256(original).hexdigest())
        self.assertEqual(row['declared_sha256'],'f'*64)
        self.assertEqual(len(result['files']),1)
        self.assertEqual(result['files'][0]['path'],'rust/src/port.rs')
        self.assertIsNone(result['files'][0]['covered_lines'])

    def test_hold_keeps_all_declared_expected_rows_and_missing_identity(self):
        (self.src/'rust/src/other.rs').write_bytes(b'pub fn other() {}')
        self.scope['source_files'].append(self.replacement('rust/src/other.rs','other','helper'))
        run,result,_=self.run_assess()
        self.assertEqual(run.returncode,2)
        self.assertEqual([r['path'] for r in result['files']],['rust/src/port.rs','rust/src/other.rs'])
        self.assertIn('rust/src/other.rs',result['missing_expected_files'])
        self.assertTrue(all(r['line_count'] is None and r['status']=='UNKNOWN' for r in result['files']))

    def test_hold_retains_excluded_source_custody(self):
        (self.src/'test.rs').write_bytes(b'synthetic test')
        self.scope['exclusions']=[{'path':'test.rs','sha256':self.digest('test.rs'),'kind':'test','reason':'test-only','review_sha256':'4'*64}]
        run,result,dest=self.run_assess(lambda s,e:e['data'][0].update(files=[]))
        self.assertEqual(run.returncode,2)
        self.assertEqual(result['exclusions'],self.scope['exclusions'])
        self.assertTrue(any(r['path']=='test.rs' and (dest/r['raw_path']).exists() for r in result['source_custody']))

    def test_missing_production_symbol_is_hold_even_with_high_file_average(self):
        self.assert_hold(lambda s,e:s['source_files'][0]['production_symbols'].append('unmapped'))

    def test_zero_nonboundary_production_symbol_is_uncovered_not_missing(self):
        self.scope['source_files'][0]['production_symbols'].append('unused')
        self.export['data'][0]['functions'].append({'name':'unused','count':0,'filenames':['rust/src/port.rs']})
        run,result,_=self.run_assess()
        self.assertEqual(run.returncode,0)
        self.assertIn({'name':'unused','count':0},result['files'][0]['production_symbols'])

    def test_missing_source_applicability_is_hold(self):
        self.assert_hold(lambda s,e:s['source_files'][0].pop('applicability'))

    def test_source_bound_review_mismatch_is_hold(self):
        self.assert_hold(lambda s,e:s['source_files'][0]['applicability'].update(source_sha256='f'*64))

    def test_helper_relationship_needs_declared_active_boundary(self):
        self.assert_hold(lambda s,e:s['source_files'][0]['applicability'].update(kind='helper',boundary_ids=['absent']))

    def test_llvm22_faithful_export_is_accepted_without_execution_claim(self):
        self.export['version']='3.1.0'
        summary={'lines':{'count':100,'covered':71,'percent':71.0},'functions':{'count':1,'covered':1,'percent':100.0},
                 'instantiations':{'count':1,'covered':1,'percent':100.0},'regions':{'count':1,'covered':1,'notcovered':0,'percent':100.0},
                 'branches':{'count':0,'covered':0,'notcovered':0,'percent':0.0},'mcdc':{'count':0,'covered':0,'notcovered':0,'percent':0.0}}
        self.export['data'][0]['files'][0].update(summary=summary,segments=[[1,1,1,True,True,False],[2,1,0,False,False,False]],branches=[],mcdc_records=[],expansions=[])
        self.export['data'][0]['totals']=copy.deepcopy(summary)
        for function in self.export['data'][0]['functions']:
            function.update(regions=[[1,1,1,17,1,0,0,0]],branches=[],mcdc_records=[])
        run,result,_=self.run_assess()
        self.assertEqual(run.returncode,0)
        self.assertFalse(result['execution_verified'])
        self.assertEqual(result['producer_export_version'],'3.1.0')

    def test_original_cpp_may_be_retired_without_native_counter(self):
        run,result,_=self.run_assess()
        self.assertEqual(run.returncode,0)
        self.assertEqual(result['files'][0]['cpp_origin']['symbols'],['original_cpp'])
        self.assertEqual(result['files'][0]['cpp_origin']['applicability'],'baseline_metadata_only')

    def test_variant_mismatch_is_hold(self):
        self.assert_hold(lambda s,e:s['source_files'][0]['applicability'].update(variant='rust_current'))

    def test_aggregate_snapshot_budget_preserves_partial_custody(self):
        body=b'x'*(2*1024*1024)
        for index in range(16):
            path='rust/src/budget'+str(index)+'.rs'
            (self.src/path).write_bytes(body)
            self.scope['source_files'].append(self.replacement(path,'budget'+str(index),'helper'))
        run,result,dest=self.run_assess()
        self.assertEqual(run.returncode,2)
        self.assertLessEqual(result['source_capture_bytes'],32*1024*1024)
        self.assertGreater(result['source_capture_bytes'],0)
        self.assertEqual(len(result['files']),17)
        self.assertTrue(all(row['line_count'] is None for row in result['files']))
        self.assertTrue(any(row['status']=='UNAVAILABLE' for row in result['source_custody']))
        self.assertTrue((dest/'source-custody.json').exists())

    def test_unavailable_source_root_still_retains_expected_inventory(self):
        self.src.rename(self.root/'hidden-source')
        run,result,_=self.run_assess()
        self.assertEqual(run.returncode,2)
        self.assertEqual(len(result['files']),1)
        self.assertEqual(result['files'][0]['path'],'rust/src/port.rs')
        self.assertIsNone(result['files'][0]['line_count'])

    def test_malformed_declared_row_keeps_safe_unknown_inventory(self):
        self.assert_hold(lambda s,e:s['source_files'].append(17))

    def assert_export_read_hold_inventory(self, setup):
        (self.src/'rust/src/helper.rs').write_bytes(b'pub fn helper() {}')
        self.scope['source_files'].append(self.replacement('rust/src/helper.rs','helper','helper'))
        (self.src/'test.rs').write_bytes(b'test only')
        self.scope['exclusions']=[{'path':'test.rs','sha256':self.digest('test.rs'),'kind':'test','reason':'test-only','review_sha256':'4'*64}]
        run,result,dest=self.run_assess(control_setup=setup)
        self.assertEqual(run.returncode,2,run.stderr)
        self.assertEqual(result['evidence_status'],'HOLD')
        self.assertEqual([r['path'] for r in result['files']],['rust/src/port.rs','rust/src/helper.rs'])
        self.assertTrue(all(r['status']=='UNKNOWN' and r['line_count'] is None and r['covered_lines'] is None for r in result['files']))
        self.assertEqual(result['declared_caller_files'][0]['path'],'daemon/caller.cpp')
        self.assertEqual(result['exclusions'],self.scope['exclusions'])
        self.assertEqual(result['source_custody'],[])
        self.assertTrue(result['reasons'])
        self.assertFalse(result['execution_verified'])
        self.assertEqual((dest/'scope.raw').read_bytes(),(self.root/'scope.json').read_bytes())
        self.assertEqual(result['input_hashes']['scope_sha256'],hashlib.sha256((dest/'scope.raw').read_bytes()).hexdigest())

    def test_missing_export_retains_readable_scope_inventory(self):
        self.assert_export_read_hold_inventory(lambda scope,export:export.unlink())

    def test_symlink_export_retains_readable_scope_inventory(self):
        def setup(scope,export):
            export.rename(self.root/'actual-export.json');export.symlink_to('actual-export.json')
        self.assert_export_read_hold_inventory(setup)

    def test_directory_export_retains_readable_scope_inventory(self):
        def setup(scope,export):
            export.unlink();export.mkdir()
        self.assert_export_read_hold_inventory(setup)

    def test_fifo_export_retains_scope_without_blocking(self):
        import os
        def setup(scope,export):
            export.unlink();os.mkfifo(export)
        self.assert_export_read_hold_inventory(setup)

    def test_oversized_export_retains_readable_scope_inventory(self):
        self.assert_export_read_hold_inventory(lambda scope,export:export.write_bytes(b' '*(8*1024*1024+1)))

    def test_aliased_export_retains_readable_scope_inventory(self):
        import os
        def setup(scope,export):
            export.unlink();os.link(scope,export)
        self.assert_export_read_hold_inventory(setup)

    def test_malformed_scope_does_not_prevent_readable_export_raw_capture(self):
        raw=b'{broken scope'
        run,result,dest=self.run_assess(scope_raw=raw)
        self.assertEqual(run.returncode,2)
        self.assertEqual((dest/'scope.raw').read_bytes(),raw)
        self.assertEqual((dest/'export.raw').read_bytes(),(self.root/'export.json').read_bytes())
        self.assertEqual(result['files'],[])
        self.assertFalse(result['execution_verified'])

    def test_lone_json_surrogate_path_completes_hold_with_custody_and_report(self):
        self.scope['source_files'][0]['path']='rust/src/bad'+chr(0xD800)+'.rs'
        run,result,dest=self.run_assess()
        self.assertEqual(run.returncode,2,run.stderr)
        self.assertEqual(result['evidence_status'],'HOLD')
        self.assertIsNone(result['files'][0]['path'])
        self.assertTrue((dest/'source-custody.json').exists())
        self.assertTrue((dest/'coverage-report.md').exists())
        self.assertTrue(result['reasons'])
        self.assertEqual((dest/'scope.raw').read_bytes(),(self.root/'scope.json').read_bytes())

    def test_surrogateescape_filesystem_name_is_rejected_not_opened(self):
        import os
        bad=os.fsdecode(b'bad\xff.rs')
        self.scope['source_files'][0]['path']='rust/src/'+bad
        run,result,_=self.run_assess()
        self.assertEqual(run.returncode,2)
        self.assertEqual(result['evidence_status'],'HOLD')
        self.assertEqual(result['source_custody'],[])
        self.assertIsNone(result['files'][0]['path'])

    def test_one_multifile_record_cannot_supply_both_boundary_sides(self):
        self.scope['required_boundaries'][0].update(rust_function='shared',caller_function='shared')
        self.scope['source_files'][0]['production_symbols']=['shared']
        self.export['data'][0]['functions']=[{'name':'shared','count':1,'filenames':['rust/src/port.rs','daemon/caller.cpp']}]
        self.assert_hold()

    def test_legitimate_multifile_record_with_distinct_caller_remains_valid(self):
        self.export['data'][0]['functions'][0]['filenames'].append('include/shared.h')
        run,result,_=self.run_assess()
        self.assertEqual(run.returncode,0)
        boundary=result['boundaries'][0]
        self.assertIn('rust_record_id',boundary)
        self.assertIn('caller_record_id',boundary)
        self.assertNotEqual(boundary['rust_record_id'],boundary['caller_record_id'])
        self.assertFalse(boundary['execution_verified'])

    def test_unit_export_requires_all_declared_rust_symbols(self):
        self.scope['capture'].update(mode='unit_diagnostic',production_only=False,test_cfg_enabled=True)
        self.export['data'][0]['functions']=[]
        self.assert_hold()

    def test_foreign_absolute_paths_are_opaque_only_in_derived_metadata(self):
        foreign='/Users/private-person/private-build/dependency.rs'
        self.export['data'][0]['files'].append({'filename':foreign,'summary':{'lines':{'count':100,'covered':90}}})
        self.export['data'][0]['functions'][0]['filenames'].append(foreign)
        run,result,dest=self.run_assess()
        self.assertEqual(run.returncode,0)
        derived=(dest/'coverage-assessment.json').read_text()
        self.assertNotIn(foreign,derived)
        self.assertIn(foreign,(dest/'export.raw').read_text())
        self.assertEqual(result['unexpected_report_files'],['EXTERNAL_ABSOLUTE_SHA256:'+hashlib.sha256(foreign.encode()).hexdigest()])

    def test_opaque_external_namespace_cannot_match_declared_scope(self):
        foreign='/private/foreign-caller.cpp'
        token='EXTERNAL_ABSOLUTE_SHA256:'+hashlib.sha256(foreign.encode()).hexdigest()
        (self.src/token).write_bytes(b'not a caller')
        self.scope['caller_files'][0].update(path=token,sha256=self.digest(token))
        self.scope['required_boundaries'][0]['caller_file']=token
        self.export['data'][0]['functions'][1]['filenames']=[foreign]
        self.assert_hold()

    def test_hold_does_not_publish_invalid_absolute_declared_paths(self):
        foreign='/Users/private-person/private-build/invalid.rs'
        self.scope['source_files'][0]['path']=foreign
        self.scope['source_files'][0]['cpp_origin']['path']=foreign
        self.scope['exclusions']=[{'path':foreign,'sha256':'0'*64,'kind':'test','reason':'invalid','review_sha256':'1'*64}]
        run,result,dest=self.run_assess()
        self.assertEqual(run.returncode,2)
        self.assertNotIn(foreign,(dest/'coverage-assessment.json').read_text())
        self.assertIsNone(result['files'][0]['path'])
        self.assertIn(foreign,(dest/'scope.raw').read_text())

    def test_filesystem_failure_paths_stay_in_private_raw_only(self):
        run,result,dest=self.run_assess(control_setup=lambda scope,export:export.unlink())
        self.assertEqual(run.returncode,2)
        self.assertNotIn(str(self.root),(dest/'coverage-assessment.json').read_text())
        self.assertNotIn(str(self.root),(dest/'coverage-report.md').read_text())
        self.assertTrue((dest/'failure.raw').exists())
        self.assertIn('export.json',(dest/'failure.raw').read_text())

    def test_foreign_function_names_are_private_in_valid_derived_metadata(self):
        foreign='/private/build/generated_function'
        self.scope['source_files'][0]['production_symbols']=[foreign]
        self.scope['required_boundaries'][0]['rust_function']=foreign
        self.export['data'][0]['functions'][0]['name']=foreign
        run,result,dest=self.run_assess()
        self.assertEqual(run.returncode,0)
        self.assertNotIn(foreign,(dest/'coverage-assessment.json').read_text())
        self.assertIn(foreign,(dest/'export.raw').read_text())

    def test_foreign_symbol_in_hold_reason_is_private(self):
        foreign='/private/build/missing_function'
        self.scope['source_files'][0]['production_symbols'].append(foreign)
        run,result,dest=self.run_assess()
        self.assertEqual(run.returncode,2)
        self.assertNotIn(foreign,(dest/'coverage-assessment.json').read_text())
        self.assertNotIn(foreign,(dest/'coverage-report.md').read_text())

    def test_duplicate_foreign_export_identity_still_rejects(self):
        foreign='/private/build/dependency.rs'
        row={'filename':foreign,'summary':{'lines':{'count':1,'covered':1}}}
        self.export['data'][0]['files'].extend([row,copy.deepcopy(row)])
        self.assert_hold()

    def test_distinct_foreign_paths_keep_distinct_derived_identities(self):
        paths=['/private/a/dependency.rs','/private/b/dependency.rs']
        self.export['data'][0]['files'].extend({'filename':path,'summary':{'lines':{'count':1,'covered':1}}} for path in paths)
        run,result,_=self.run_assess()
        self.assertEqual(run.returncode,0)
        self.assertEqual(result['unexpected_report_files'],sorted('EXTERNAL_ABSOLUTE_SHA256:'+hashlib.sha256(path.encode()).hexdigest() for path in paths))

    def test_windows_absolute_export_is_opaque_and_never_a_scope_match(self):
        foreign='C:/Users/private-person/build/dependency.rs'
        self.export['data'][0]['files'].append({'filename':foreign,'summary':{'lines':{'count':1,'covered':1}}})
        run,result,dest=self.run_assess()
        self.assertEqual(run.returncode,0)
        self.assertNotIn(foreign,(dest/'coverage-assessment.json').read_text())
        self.assertEqual(result['unexpected_report_files'],['EXTERNAL_ABSOLUTE_SHA256:'+hashlib.sha256(foreign.encode()).hexdigest()])

    def test_windows_absolute_scope_path_is_unknown_and_private(self):
        foreign='C:/Users/private-person/build/port.rs'
        self.scope['source_files'][0]['path']=foreign
        self.scope['source_files'][0]['cpp_origin']['path']=foreign
        run,result,dest=self.run_assess()
        self.assertEqual(run.returncode,2)
        self.assertIsNone(result['files'][0]['path'])
        self.assertNotIn(foreign,(dest/'coverage-assessment.json').read_text())

    def test_windows_foreign_label_cannot_supply_declared_caller(self):
        foreign='C:/Users/private-person/caller.cpp'
        token='EXTERNAL_ABSOLUTE_SHA256:'+hashlib.sha256(foreign.encode()).hexdigest()
        (self.src/token).write_bytes(b'not a caller')
        self.scope['caller_files'][0].update(path=token,sha256=self.digest(token))
        self.scope['required_boundaries'][0]['caller_file']=token
        self.export['data'][0]['functions'][1]['filenames']=[foreign]
        self.assert_hold()

    def test_unc_declared_mapping_is_private_on_hold(self):
        foreign=chr(92)*2+'private-server'+chr(92)+'share'+chr(92)+'port.cpp'
        self.scope['source_files'][0]['cpp_origin']['path']=foreign
        run,result,dest=self.run_assess()
        self.assertEqual(run.returncode,2)
        self.assertNotIn(foreign,json.loads((dest/'coverage-assessment.json').read_text())['files'][0]['declared_mapping']['cpp_origin']['path'])

    def test_surrogate_function_name_completes_hold(self):
        self.export['data'][0]['functions'][0]['name']='bad'+chr(0xD800)
        self.assert_hold()

    def assert_failure_sink_fault_is_closed_output_failure(self, stage):
        # Inject only the actual private failure sink boundary. All other file I/O is real.
        harness=self.root/'sink-fault.py'
        harness.write_text('''import errno, importlib.util, json, os, sys, traceback
script=sys.argv[1];sys.argv=[script]+sys.argv[2:]
spec=importlib.util.spec_from_file_location('assessor',script)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
real_open,real_fsync=os.open,os.fsync
output_fd=None;failure_fd=None
stage='''+repr(stage)+'''
def fault_open(path,flags,*args,**kwargs):
    global output_fd,failure_fd
    if path=='failure.raw' and stage=='open':
        raise OSError(errno.ENOSPC,'injected failure sink open')
    fd=real_open(path,flags,*args,**kwargs)
    if path=='result' and flags & os.O_DIRECTORY:output_fd=fd
    if path=='failure.raw':failure_fd=fd
    return fd
def fault_fsync(fd):
    if fd==failure_fd and stage=='fsync':
        raise OSError(errno.ENOSPC,'injected failure sink fsync')
    return real_fsync(fd)
os.open=fault_open;os.fsync=fault_fsync
try:
    code=module.main()
except BaseException:
    traceback.print_exc();code=1
finally:
    os.open=real_open;os.fsync=real_fsync
closed=False
if output_fd is not None:
    try:os.fstat(output_fd)
    except OSError as error:closed=error.errno==errno.EBADF
print(json.dumps({'output_descriptor_closed':closed}))
sys.exit(code)
''')
        run,result,dest=self.run_assess(scope_raw=b'{broken',runner=harness)
        self.assertEqual(run.returncode,2,run.stderr+run.stdout)
        self.assertTrue(json.loads(run.stdout)['output_descriptor_closed'])
        self.assertIn(b'incomplete attempt retained',run.stderr)
        self.assertEqual((dest/'scope.raw').read_bytes(),b'{broken')
        self.assertEqual((dest/'export.raw').read_bytes(),(self.root/'export.json').read_bytes())
        self.assertIsNone(result)
        if stage=='fsync':
            self.assertIn(b'malformed JSON',(dest/'failure.raw').read_bytes())

    def test_failure_sink_open_error_exits_two_and_closes_output_descriptor(self):
        self.assert_failure_sink_fault_is_closed_output_failure('open')

    def test_failure_sink_fsync_error_exits_two_and_closes_output_descriptor(self):
        self.assert_failure_sink_fault_is_closed_output_failure('fsync')

    def test_deep_malformed_mapping_retains_hold_inventory_and_private_scope(self):
        nested=0
        for _ in range(600):nested=[nested]
        self.scope['source_files'][0]['cpp_origin']=nested
        run,result,dest=self.run_assess()
        self.assertEqual(run.returncode,2,run.stderr)
        self.assertEqual(result['evidence_status'],'HOLD')
        self.assertEqual(result['files'][0]['path'],'rust/src/port.rs')
        self.assertEqual(result['files'][0]['status'],'UNKNOWN')
        self.assertIsNone(result['files'][0]['line_count'])
        self.assertFalse(result['execution_verified'])
        self.assertTrue(result['reasons'])
        self.assertTrue((dest/'source-custody.json').exists())
        self.assertTrue((dest/'coverage-report.md').exists())
        self.assertEqual((dest/'scope.raw').read_bytes(),(self.root/'scope.json').read_bytes())
        self.assertIn('OMITTED_DEPTH_LIMIT',(dest/'coverage-assessment.json').read_text())

    def test_near_limit_raw_malformed_mapping_retains_unknown_inventory(self):
        raw_export=json.dumps(self.export).encode()
        self.scope['capture']['export_sha256']=hashlib.sha256(raw_export).hexdigest()
        origin=json.dumps(self.scope['source_files'][0]['cpp_origin']).encode()
        raw_scope=json.dumps(self.scope).encode().replace(origin,b'['*985+b'0'+b']'*985,1)
        run,result,dest=self.run_assess(export_raw=raw_export,scope_raw=raw_scope)
        self.assertEqual(run.returncode,2,run.stderr)
        self.assertEqual(result['evidence_status'],'HOLD')
        self.assertEqual(result['files'][0]['path'],'rust/src/port.rs')
        self.assertEqual(result['files'][0]['status'],'UNKNOWN')
        self.assertIsNone(result['files'][0]['line_count'])
        self.assertFalse(result['execution_verified'])
        self.assertEqual((dest/'scope.raw').read_bytes(),raw_scope)
        self.assertTrue((dest/'coverage-report.md').exists())

    def test_raw_994_mapping_completes_hold_with_unknown_inventory(self):
        raw_export=json.dumps(self.export).encode()
        self.scope['capture']['export_sha256']=hashlib.sha256(raw_export).hexdigest()
        origin=json.dumps(self.scope['source_files'][0]['cpp_origin']).encode()
        raw_scope=json.dumps(self.scope).encode().replace(origin,b'['*994+b'0'+b']'*994,1)
        run,result,dest=self.run_assess(export_raw=raw_export,scope_raw=raw_scope)
        self.assertEqual(run.returncode,2,run.stderr)
        self.assertEqual(result['files'][0]['status'],'UNKNOWN')
        self.assertEqual(result['files'][0]['path'],'rust/src/port.rs')
        self.assertIsNone(result['files'][0]['line_count'])
        self.assertEqual(result['evidence_status'],'HOLD')
        self.assertFalse(result['execution_verified'])
        self.assertEqual((dest/'scope.raw').read_bytes(),raw_scope)
        self.assertTrue((dest/'source-custody.json').exists())
        self.assertTrue((dest/'coverage-report.md').exists())

    def test_unit_applicability_cannot_reference_absent_boundary(self):
        self.scope['capture'].update(mode='unit_diagnostic',production_only=False,test_cfg_enabled=True)
        self.scope['required_boundaries']=[];self.scope['caller_files']=[]
        self.export['data'][0]['functions']=[{'name':'port','count':0,'filenames':['rust/src/port.rs']}]
        self.assert_hold()

    def test_unit_helper_applicability_cannot_reference_absent_boundary(self):
        self.scope['capture'].update(mode='unit_diagnostic',production_only=False,test_cfg_enabled=True)
        self.scope['source_files'][0]['applicability']['kind']='helper'
        self.scope['source_files'][0]['applicability']['boundary_ids']=['missing']
        self.assert_hold()

    def test_unit_direct_source_needs_its_own_declared_boundary(self):
        (self.src/'rust/src/other.rs').write_text('pub fn other() {}\n')
        self.scope['source_files'].append(self.replacement('rust/src/other.rs','other'))
        self.export['data'][0]['files'].append({'filename':'rust/src/other.rs','summary':{'lines':{'count':1,'covered':0}}})
        self.export['data'][0]['functions'].append({'name':'other','count':0,'filenames':['rust/src/other.rs']})
        self.scope['capture'].update(mode='unit_diagnostic',production_only=False,test_cfg_enabled=True)
        self.assert_hold()

    def directory_sync_harness(self, fault=None):
        harness=self.root/'directory-sync.py'
        harness.write_text('''import errno, importlib.util, json, os, stat, sys, traceback
script=sys.argv[1];sys.argv=[script]+sys.argv[2:]
spec=importlib.util.spec_from_file_location('assessor',script)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
real_open,real_mkdir,real_fsync=os.open,os.mkdir,os.fsync
names={};directories=set();output_fd=None;parent_fd=None;last_file=None;events=[]
fault='''+repr(fault)+'''
def traced_open(path,flags,*args,**kwargs):
    global output_fd
    fd=real_open(path,flags,*args,**kwargs);names[fd]=str(path)
    if stat.S_ISDIR(os.fstat(fd).st_mode):directories.add(fd)
    if path=='result' and flags & os.O_DIRECTORY:output_fd=fd
    return fd
def traced_mkdir(path,*args,**kwargs):
    global parent_fd
    result=real_mkdir(path,*args,**kwargs)
    if path=='result':parent_fd=kwargs['dir_fd'];events.append('mkdir:output')
    return result
def traced_fsync(fd):
    global last_file
    if stat.S_ISDIR(os.fstat(fd).st_mode):
        if fd==output_fd:
            event='dir:output:'+str(last_file)
            fail=fault=='output' or (fault=='receipt' and last_file=='source-0000.raw.json')
        elif fd==parent_fd:event='dir:parent';fail=fault=='parent'
        else:event='dir:other';fail=False
        events.append(event)
        if fail:raise OSError(errno.EINVAL,'injected unsupported directory sync')
    else:
        last_file=names[fd];events.append('file:'+last_file)
    return real_fsync(fd)
os.open=traced_open;os.mkdir=traced_mkdir;os.fsync=traced_fsync
try:code=module.main()
except BaseException:traceback.print_exc();code=1
finally:os.open=real_open;os.mkdir=real_mkdir;os.fsync=real_fsync
opened=[]
for fd in directories:
    try:
        if stat.S_ISDIR(os.fstat(fd).st_mode):opened.append(fd)
    except OSError:pass
print(json.dumps({'events':events,'open_directory_descriptors':opened}))
sys.exit(code)
''')
        return harness

    def test_directory_sync_orders_parent_and_each_artifact_before_interpretation(self):
        self.scope['source_files'][0]['sha256']='f'*64
        run,result,_=self.run_assess(runner=self.directory_sync_harness())
        self.assertEqual(run.returncode,2,run.stderr)
        receipt=json.loads(run.stdout);events=receipt['events']
        print(json.dumps({'fixture':'directory-sync-order','exit_code':run.returncode,'receipt':receipt}))
        self.assertEqual(receipt['open_directory_descriptors'],[])
        self.assertIn('dir:parent',events)
        self.assertLess(events.index('dir:parent'),events.index('file:scope.raw'))
        for i,event in enumerate(events):
            if event.startswith('file:'):
                self.assertEqual(events[i+1],'dir:output:'+event[5:])
        self.assertLess(events.index('dir:output:source-0000.raw.json'),events.index('file:failure.raw'))
        self.assertIn('source hash mismatch: rust/src/port.rs',result['reasons'])

    def test_parent_directory_sync_failure_exits_two_and_closes_directories(self):
        run,result,dest=self.run_assess(runner=self.directory_sync_harness('parent'))
        print(json.dumps({'fixture':'parent-directory-sync-fault','exit_code':run.returncode,'receipt':json.loads(run.stdout)}))
        self.assertEqual(run.returncode,2,run.stderr+run.stdout)
        self.assertEqual(json.loads(run.stdout)['open_directory_descriptors'],[])
        self.assertIsNone(result)
        self.assertTrue(dest.exists())

    def test_output_directory_sync_failure_retains_partial_bytes_and_closes(self):
        run,result,dest=self.run_assess(runner=self.directory_sync_harness('output'))
        print(json.dumps({'fixture':'output-directory-sync-fault','exit_code':run.returncode,'receipt':json.loads(run.stdout)}))
        self.assertEqual(run.returncode,2,run.stderr+run.stdout)
        self.assertEqual(json.loads(run.stdout)['open_directory_descriptors'],[])
        self.assertIsNone(result)
        self.assertEqual((dest/'scope.raw').read_bytes(),(self.root/'scope.json').read_bytes())

    def test_source_receipt_directory_sync_failure_does_not_reach_hash_comparison(self):
        self.scope['source_files'][0]['sha256']='f'*64
        run,result,dest=self.run_assess(runner=self.directory_sync_harness('receipt'))
        print(json.dumps({'fixture':'receipt-directory-sync-fault','exit_code':run.returncode,'receipt':json.loads(run.stdout)}))
        self.assertEqual(run.returncode,2,run.stderr+run.stdout)
        self.assertEqual(json.loads(run.stdout)['open_directory_descriptors'],[])
        self.assertEqual(result['evidence_status'],'HOLD')
        self.assertEqual(result['files'][0]['status'],'UNKNOWN')
        self.assertNotIn('source hash mismatch: rust/src/port.rs',result['reasons'])
        self.assertTrue((dest/'source-0000.raw.json').exists())

if __name__ == '__main__':
    unittest.main()
