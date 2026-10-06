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


def numbers(value):
    return Counter(re.findall(r'(?<![A-Za-z])\d+(?:\.\d+)?', str(value)))


def audit():
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
    reports = {}
    for lang in ('CN', 'EN'):
        stem = f'SDTwin_Thermal_Test_Report_{lang}'
        docx_path, pdf_path = [THERMAL / (stem + ext) for ext in ('.docx', '.pdf')]
        doc = Document(docx_path)
        reader = PdfReader(pdf_path)
        texts = [page.extract_text() or '' for page in reader.pages]
        full = '\n'.join(texts)
        assert len(doc.inline_shapes) == 3, (lang, 'expected 3 scientific figures')
        assert '\ufffd' not in full, (lang, 'replacement glyph in PDF text')
        assert not re.search(r'English result text pending|\bPending\b|\bNaN\b', full, re.I), lang
        for cid in reviewed_results.ORDER:
            assert cid in full, (lang, cid, 'missing from PDF')
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
