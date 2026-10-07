"""Content and bilingual checks supplement, but do not replace, page-image inspection."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re
import sys

from docx import Document
from pypdf import PdfReader

THERMAL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(THERMAL / 'test_report'))
import content_cn
import content_en
import reviewed_results
import case_evidence


def numbers(value):
    return Counter(re.findall(r'(?<![A-Za-z])\d+(?:\.\d+)?', str(value)))


def audit():
    for key in ('intro', 'rows', 'notes'):
        assert numbers(case_evidence.ENVIRONMENT['cn'][key]) == numbers(case_evidence.ENVIRONMENT['en'][key]), ('environment', key)
    cfg = json.loads((THERMAL / 'tests/data/fe_001/fe001_config.json').read_text(encoding='utf-8'))
    for row, cid in zip(case_evidence.ENVIRONMENT['en']['rows'], ('cold0', 'nom0', 'hot75')):
        actual = cfg['cases'][cid]
        assert [float(row[1].replace('°', '')), float(row[2]), float(row[3]), float(row[4])] == [actual[k] for k in ('beta_deg', 'solar_constant_W_m2', 'albedo', 'olr_W_m2')]
        shadow = json.loads((THERMAL / 'iss_fem/out' / cid / 'summary.json').read_text(encoding='utf-8'))['orbit']
        duration = shadow['eclipse_deg'] / 360 * shadow['period'] / 60
        assert abs(duration - (0 if cid == 'hot75' else 36.1)) < 0.05, cid
    cases = {}
    for cid in reviewed_results.ORDER:
        raw_path = THERMAL / 'tests' / 'results' / f'{cid}.json'
        raw = json.loads(raw_path.read_text(encoding='utf-8'))
        cn, en = reviewed_results.prose(cid, raw['metrics'])
        assert numbers(cn) == numbers(en), (cid, 'actual result numbers', numbers(cn) - numbers(en), numbers(en) - numbers(cn))
        for key, value in content_cn.CASES_CN[cid].items():
            a, b = numbers(value), numbers(content_en.CASES_EN[cid][key])
            if cid == 'FE-004' and key == 'pre':
                a.subtract({'8': 1})  # CN numeric month 8; EN spells August.
                a = +a
            assert a == b, (cid, key, 'contract numbers differ')
        cases[cid] = {'status': raw['status'], 'input_and_criteria_numbers_aligned': True,
                      'actual_result_numbers_aligned': True}
        assert numbers(case_evidence.scenario(cid, 'cn')) == numbers(case_evidence.scenario(cid, 'en')), (cid, 'scenario numbers')
        assert numbers(case_evidence.context(cid, 'cn')) == numbers(case_evidence.context(cid, 'en')), (cid, 'physical-context numbers')
        cn_table = case_evidence.table_spec(cid, 'cn', raw['metrics'])
        en_table = case_evidence.table_spec(cid, 'en', raw['metrics'])
        assert bool(cn_table) == bool(en_table), cid
        if cn_table:
            assert numbers(cn_table['rows']) == numbers(en_table['rows']), (cid, 'measured-table numbers')
        else:
            assert cid in ('EN-003', 'FE-001', 'FE-002', 'FE-003', 'FE-004'), (cid, 'missing result table')
        cases[cid]['scenario_explained'] = True
        cases[cid]['physical_context_defined'] = True
        cases[cid]['quantitative_result_table'] = True
    reports = {}
    for lang in ('CN', 'EN'):
        stem = f'SDTwin_Thermal_Test_Report_{lang}'
        docx_path, pdf_path = [THERMAL / (stem + ext) for ext in ('.docx', '.pdf')]
        doc = Document(docx_path)
        doc_text = ''.join(doc.element.body.itertext())
        reader = PdfReader(pdf_path)
        texts = [page.extract_text() or '' for page in reader.pages]
        full = '\n'.join(texts)
        assert len(doc.inline_shapes) == 6, (lang, 'expected 3 comparison plots and 3 ISS FE views')
        assert '\ufffd' not in full, (lang, 'replacement glyph in PDF text')
        assert not re.search(r'English result text pending|\bPending\b|\bNaN\b', full, re.I), lang
        assert case_evidence.ENVIRONMENT[lang.lower()]['caption'] in doc_text, (lang, 'environment definitions absent')
        for cid in reviewed_results.ORDER:
            assert cid in full, (lang, cid, 'missing from PDF')
            assert case_evidence.scenario(cid, lang.lower())[:28] in doc_text, (lang, cid, 'scenario missing from DOCX')
            assert case_evidence.context(cid, lang.lower())[:28] in doc_text, (lang, cid, 'physical context missing from DOCX')
            raw = json.loads((THERMAL / 'tests' / 'results' / f'{cid}.json').read_text(encoding='utf-8'))
            spec = case_evidence.table_spec(cid, lang.lower(), raw['metrics'])
            if spec:
                assert spec['caption'] in doc_text, (lang, cid, 'measured table missing from DOCX')
        assert len(doc.tables) == 46, (lang, 'expected 16 case records, environment definitions and quantitative tables')
        reports[lang] = {'pages': len(reader.pages), 'tables': len(doc.tables),
                         'figures': len(doc.inline_shapes), 'page_characters': [len(t) for t in texts],
                         'sha256': {ext: hashlib.sha256((THERMAL / (stem + '.' + ext)).read_bytes()).hexdigest()
                                    for ext in ('docx', 'pdf')}}
    assert reports['CN']['tables'] == reports['EN']['tables'], 'bilingual table counts differ'
    result = {'cases': cases, 'reports': reports,
              'visual_review': 'See rendered page images and separate visual inspection record.'}
    out = Path(__file__).with_name('report_content_audit.json')
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(reports, indent=2))


if __name__ == '__main__':
    audit()
