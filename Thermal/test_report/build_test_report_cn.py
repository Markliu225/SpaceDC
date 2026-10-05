# -*- coding: utf-8 -*-
"""Build the Chinese SDTwin thermal module test report on top of the design report template.

The cover, version record, contents, headers, footers, page setup and styles are reused from
SDTwin_Thermal_Design_Report_CN.docx; the body is replaced. Chapter layout follows the Orbit
module test report. Run fe_compare.py and figures.py first, then finalize.ps1 to refresh the
table of contents and export a PDF.
"""
import json
import re
from pathlib import Path

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm

HERE = Path(__file__).resolve().parent
THERMAL = HERE.parent
TEMPLATE = THERMAL / 'SDTwin_Thermal_Design_Report_CN.docx'
OUT_DOCX = THERMAL / 'SDTwin_Thermal_Test_Report_CN.docx'
RES = json.loads((HERE / 'out' / 'fe_compare.json').read_text(encoding='utf-8'))

M_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
DATE_CN = '2026年10月5日'
DATE_ISO = '2026-10-05'
LABEL_FILL = 'E7E6E6'
CASE_W = [1560, 2450, 1500, 2799]          # portrait text width 8309 twips


def fmt(v, nd=1):
    s = f'{v:.{nd}f}'
    return s.replace('-', '−')


# =============================================================== low-level XML helpers
def w_el(tag, **attrs):
    el = OxmlElement(tag)
    for k, v in attrs.items():
        el.set(qn('w:' + k), str(v))
    return el


def m_el(tag):
    return OxmlElement('m:' + tag)


def run_props(bold=False, italic=False, size=None, color=None, superscript=False):
    rpr = w_el('w:rPr')
    rpr.append(w_el('w:rFonts', eastAsia='SimSun'))
    if bold:
        rpr.append(w_el('w:b'))
    if italic:
        rpr.append(w_el('w:i'))
    if color:
        rpr.append(w_el('w:color', val=color))
    if size:
        rpr.append(w_el('w:sz', val=size))
    if superscript:
        rpr.append(w_el('w:vertAlign', val='superscript'))
    rpr.append(w_el('w:lang', eastAsia='zh-CN'))
    return rpr


def text_run(text, **kw):
    r = w_el('w:r')
    r.append(run_props(**kw))
    t = w_el('w:t')
    t.text = text
    t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    r.append(t)
    return r


def math_run(text, upright=False):
    r = m_el('r')
    if upright:
        mrpr = m_el('rPr')
        sty = m_el('sty')
        sty.set(qn('m:val'), 'p')
        mrpr.append(sty)
        r.append(mrpr)
    rpr = w_el('w:rPr')
    rpr.append(w_el('w:rFonts', ascii='Cambria Math', hAnsi='Cambria Math'))
    r.append(rpr)
    t = m_el('t')
    t.text = text
    r.append(t)
    return r


def omath(token):
    """'S' -> italic S; 'R_JC' -> R with subscript JC; lower-case subscript words stay upright."""
    om = m_el('oMath')
    if '_' not in token:
        om.append(math_run(token))
        return om
    base, sub = token.split('_', 1)
    ssub = m_el('sSub')
    pr = m_el('sSubPr')
    ctrl = m_el('ctrlPr')
    ctrl.append(w_el('w:rPr'))
    ctrl[0].append(w_el('w:rFonts', ascii='Cambria Math', hAnsi='Cambria Math'))
    pr.append(ctrl)
    ssub.append(pr)
    e = m_el('e')
    e.append(math_run(base))
    ssub.append(e)
    s = m_el('sub')
    for piece in re.findall(r'[a-z]+|[A-Z0-9]+|[^A-Za-z0-9]+', sub):
        s.append(math_run(piece, upright=not piece[0].isupper()))
    ssub.append(s)
    om.append(ssub)
    return om


TOKEN = re.compile(r'(\$[^$]+\$|\^\{[^}]+\}|\*\*[^*]+\*\*)')


def fill(p_el, text, bold=False, size=None):
    """Append runs to a w:p, handling $math$, ^{superscript} and **bold** markup."""
    for part in TOKEN.split(text):
        if not part:
            continue
        if part.startswith('$'):
            p_el.append(omath(part[1:-1]))
        elif part.startswith('^{'):
            p_el.append(text_run(part[2:-1], bold=bold, size=size, superscript=True))
        elif part.startswith('**'):
            p_el.append(text_run(part[2:-2], bold=True, size=size))
        else:
            p_el.append(text_run(part, bold=bold, size=size))


def ppr(p_el):
    pr = p_el.find(qn('w:pPr'))
    if pr is None:
        pr = w_el('w:pPr')
        p_el.insert(0, pr)
    return pr


# =============================================================== document writer
class Writer:
    def __init__(self, doc):
        self.d = doc
        self.anchor = None
        self.tab = 0
        self.fig = 0

    def _place(self, el):
        self.anchor.addprevious(el)
        return el

    # ---- paragraphs
    def heading(self, level, text):
        p = w_el('w:p')
        ppr(p).append(w_el('w:pStyle', val={1: '1', 2: '21', 3: '31'}[level]))
        fill(p, text)
        return self._place(p)

    def appendix_heading(self, text):
        p = w_el('w:p')
        ppr(p).append(w_el('w:pStyle', val='AppendixHeading'))
        fill(p, text)
        return self._place(p)

    def para(self, text, indent=True, jc=None, keep_next=False, before=None):
        p = w_el('w:p')
        if not indent or jc or keep_next or before:
            pr = ppr(p)
            if keep_next:
                pr.append(w_el('w:keepNext'))
            if before:
                pr.append(w_el('w:spacing', before=before))
            if not indent:
                pr.append(w_el('w:ind', firstLine=0))
            if jc:
                pr.append(w_el('w:jc', val=jc))
        fill(p, text)
        return self._place(p)

    def field(self, label, text):
        p = w_el('w:p')
        p.append(text_run(label, bold=True))
        fill(p, text)
        return self._place(p)

    def bullet(self, text):
        p = w_el('w:p')
        pr = ppr(p)
        pr.append(w_el('w:spacing', after=60))
        pr.append(w_el('w:ind', left=600, hanging=240))
        fill(p, '• ' + text)
        return self._place(p)

    def caption(self, title, kind='表'):
        if kind == '表':
            self.tab += 1
            n = self.tab
        else:
            self.fig += 1
            n = self.fig
        p = w_el('w:p')
        pr = ppr(p)
        pr.append(w_el('w:pStyle', val='EngineeringCaption'))
        if kind == '表':
            pr.append(w_el('w:keepNext'))
        p.append(text_run(kind))
        p.append(text_run(f' {n} '))
        fill(p, title)
        return self._place(p)

    def picture(self, path, width_cm):
        p = self.d.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0)
        p.alignment = 1
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(str(path), width=Cm(width_cm))
        return self._place(p._p)

    def page_break(self):
        p = w_el('w:p')
        r = w_el('w:r')
        r.append(w_el('w:br', type='page'))
        p.append(r)
        return self._place(p)

    # ---- tables
    def _new_table(self, n_rows, widths):
        t = self.d.add_table(rows=n_rows, cols=len(widths))
        t.style = self.d.styles['Table Grid']
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        tblpr = t._tbl.tblPr
        for old in tblpr.findall(qn('w:tblW')):
            tblpr.remove(old)
        style_el = tblpr.find(qn('w:tblStyle'))
        tblpr.insert(0 if style_el is None else list(tblpr).index(style_el) + 1, w_el('w:tblW', w=sum(widths), type='dxa'))
        grid = t._tbl.tblGrid
        for gc, wd in zip(grid.findall(qn('w:gridCol')), widths):
            gc.set(qn('w:w'), str(wd))
        for row in t.rows:
            trpr = row._tr.get_or_add_trPr()
            trpr.append(w_el('w:cantSplit'))
            trpr.append(w_el('w:jc', val='center'))
        return t

    @staticmethod
    def _cell_fmt(cell, width, fill_hex=None):
        tcpr = cell._tc.get_or_add_tcPr()
        for old in tcpr.findall(qn('w:tcW')):
            tcpr.remove(old)
        tcpr.insert(0, w_el('w:tcW', w=width, type='dxa'))
        if fill_hex:
            tcpr.append(w_el('w:shd', val='clear', color='auto', fill=fill_hex))
        mar = w_el('w:tcMar')
        for side, v in (('top', 90), ('left', 120), ('bottom', 90), ('right', 120)):
            mar.append(w_el('w:' + side, w=v, type='dxa'))
        tcpr.append(mar)
        tcpr.append(w_el('w:vAlign', val='center'))

    @staticmethod
    def _cell_text(cell, lines, bold=False, center=False, keep_next=False, kind='plain'):
        """lines: str or list of str. kind 'bullet' prefixes •, 'steps' prefixes 1．"""
        for p in cell.paragraphs[1:]:
            p._p.getparent().remove(p._p)
        if isinstance(lines, str):
            lines = [lines]
        first = True
        for i, line in enumerate(lines):
            p_el = cell.paragraphs[0]._p if first else cell.add_paragraph()._p
            first = False
            for r in p_el.findall(qn('w:r')):
                p_el.remove(r)
            pr = ppr(p_el)
            for old in list(pr):
                pr.remove(old)
            pr.append(w_el('w:pStyle', val='EngineeringTableText'))
            if keep_next:
                pr.append(w_el('w:keepNext'))
            if kind in ('bullet', 'steps'):
                pr.append(w_el('w:ind', left=230, hanging=230))
            if center:
                pr.append(w_el('w:jc', val='center'))
            prefix = '• ' if kind == 'bullet' else (f'{i + 1}．' if kind == 'steps' else '')
            fill(p_el, prefix + line, bold=bold)

    def table(self, headers, rows, widths, center_cols=()):
        t = self._new_table(1 + len(rows), widths)
        hdr = t.rows[0]
        trpr = hdr._tr.get_or_add_trPr()
        trpr.insert(list(trpr).index(trpr.find(qn('w:jc'))), w_el('w:tblHeader'))
        for j, h in enumerate(headers):
            c = hdr.cells[j]
            self._cell_fmt(c, widths[j], LABEL_FILL)
            self._cell_text(c, h, bold=True, center=True, keep_next=True)
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                c = t.rows[i + 1].cells[j]
                self._cell_fmt(c, widths[j])
                self._cell_text(c, val, center=j in center_cols)
        return self._place(t._tbl)

    def case_table(self, c):
        t = self._new_table(12, CASE_W)
        full = sum(CASE_W[1:])

        def label(r, col, text):
            cell = t.rows[r].cells[col]
            self._cell_fmt(cell, CASE_W[col], LABEL_FILL)
            self._cell_text(cell, text, bold=True, center=True)

        def wide(r, lines, kind='plain'):
            cell = t.cell(r, 1).merge(t.cell(r, 3))
            self._cell_fmt(cell, full)
            self._cell_text(cell, lines, kind=kind)

        def short(r, col, text, bold=False, center=False):
            cell = t.rows[r].cells[col]
            self._cell_fmt(cell, CASE_W[col])
            self._cell_text(cell, text, bold=bold, center=center)

        label(0, 0, '用例编号'); short(0, 1, c['id'], bold=True, center=True)
        label(0, 2, '用例名称'); short(0, 3, c['name'], bold=True)
        rows = (('测试目的', 'goal', 'plain'), ('设计依据', 'basis', 'plain'), ('前置条件', 'pre', 'bullet'),
                ('输入数据', 'input', 'bullet'), ('测试步骤', 'steps', 'steps'), ('预期结果', 'expect', 'bullet'),
                ('验收判据', 'accept', 'plain'))
        for r, (lab, key, kind) in enumerate(rows, start=1):
            label(r, 0, lab)
            wide(r, c[key], kind)
        label(8, 0, '用例设计'); short(8, 1, ''); label(8, 2, '执行人与日期'); short(8, 3, '')
        label(9, 0, '实际结果'); wide(9, c.get('actual', '未执行。正式执行时附运行清单、输入散列值、输出文件、对比报告与日志摘录。'))
        label(10, 0, '记录人'); short(10, 1, ''); label(10, 2, '测试结论'); short(10, 3, '☐ 通过  ☐ 不通过  ☒ 未执行')
        label(11, 0, '异常记录'); wide(11, c.get('anomaly', '无，用例未执行。'))
        return self._place(t._tbl)


# =============================================================== template surgery
def set_runs(p, texts):
    """Keep the formatting of the first runs, replace their texts, drop the rest."""
    runs = p.runs
    for r, txt in zip(runs, texts):
        r.text = txt
    for r in runs[len(texts):]:
        r._r.getparent().remove(r._r)


def set_cell(cell, text):
    p = cell.paragraphs[0]
    if p.runs:
        set_runs(p, [text])
    else:
        p._p.append(text_run(text, color='000000', size=18))


def prepare(doc):
    body = doc.element.body
    kids = list(body)
    # cover
    paras = {i: docx.text.paragraph.Paragraph(kids[i], doc) for i in (6, 7)}
    set_runs(paras[6], ['软件模块测试报告'])
    set_runs(paras[7], ['测试用例', ' • ', '有限元对标', ' • ', '验收判据'])
    cover_tbl = docx.table.Table(kids[8], doc)
    set_cell(cover_tbl.rows[3].cells[1], DATE_CN)
    # version record
    vt = docx.table.Table(kids[12], doc)
    set_cell(vt.rows[0].cells[1], '本报告按《SDTwin 热模块软件模块设计报告》规定热模块的测试范围、测试用例、参照数据与验收判据，并记录用国际空间站有限元结果对设计报告公式所做的原型对比。热模块尚未实现，全部正式用例的状态为未执行。')
    set_cell(vt.rows[1].cells[1], '集总热网络; 有限元对标; 测试用例')
    for cell, txt in zip(vt.rows[4].cells, ['1.0', '初稿', DATE_ISO, '', '测试框架与对比方案初稿']):
        set_cell(cell, txt)
    # body anchors: first Heading 1 .. section breaks
    first = next(i for i, el in enumerate(kids) if el.tag == qn('w:p') and el.find('.//' + qn('w:pStyle')) is not None
                 and el.find('.//' + qn('w:pStyle')).get(qn('w:val')) == '1')
    breaks = [i for i, el in enumerate(kids) if i > first and el.tag == qn('w:p') and el.find('.//' + qn('w:sectPr')) is not None]
    sec_body_end, sec_land_end = breaks[0], breaks[1]
    final = kids[-1]
    for el in kids[first:sec_body_end] + kids[sec_body_end + 1:sec_land_end] + kids[sec_land_end + 1:-1]:
        body.remove(el)
    # running headers of the landscape and appendix sections
    for sec in doc.sections[4:]:
        for p in sec.header.paragraphs:
            for r in p.runs:
                r.text = r.text.replace('设计报告', '测试报告')
    doc.core_properties.title = 'SDTwin 热模块软件模块测试报告'
    return kids[sec_body_end], kids[sec_land_end], final


# =============================================================== content
# Every case follows the design report wording; the basis field names the design sections it verifies.
GROUPS = [
    ('公共数据与参数装配', ['DM-001', 'PA-001']),
    ('表面环境与辐射', ['EN-001', 'EN-002', 'EN-003']),
    ('组件传热与温度导数', ['HT-001', 'HT-002', 'HT-003']),
    ('电热耦合', ['EC-001']),
    ('有限元对标', ['FE-001', 'FE-002', 'FE-003', 'FE-004']),
    ('数值计算与端到端运行', ['NI-001', 'NI-002', 'NI-003']),
]
CASE_NAMES = {'cold0': '设计冷工况', 'nom0': '平均环境工况', 'hot75': '设计热工况'}


def fe_numbers():
    cs = RES['cases']
    s_diff = max(abs(a - b) for c in cs.values() for a, b in zip(c['S']['fem'], c['S']['lumped']))
    no_earth_max = [c['S']['lumped'][2] - c['S']['no_earth'][2] for c in cs.values()]
    no_earth_min = [c['S']['lumped'][0] - c['S']['no_earth'][0] for c in cs.values() if c['eclipse_s']]
    no_pv = [c['S']['no_pv'][2] - c['S']['lumped'][2] for c in cs.values()]
    r_diff = [abs(round(c['R'][lp]['lumped'][1], 1) - round(c['R'][lp]['fem'][1], 1)) for c in cs.values() for lp in ('A', 'B')]
    cold = [c['R_spread']['mean_same_instant_C'] - c['R_spread']['coldest_C'] for c in cs.values()]
    spread = [c['R_spread']['max_minus_min_K'][1] for c in cs.values()]
    jc = RES['jc']['rows']
    hot = cs['hot75']['R']
    return dict(
        s_diff=s_diff, no_earth_max=(min(no_earth_max), max(no_earth_max)), no_earth_min=(min(no_earth_min), max(no_earth_min)),
        no_pv=(min(no_pv), max(no_pv)), r_diff=(min(r_diff), max(r_diff)), cold=(min(cold), max(cold)),
        spread=(min(spread), max(spread)),
        jc_diff=max(abs(round(r['lumped_C'], 1) - round(r['fem_C'], 1)) for r in jc),
        jc_all=(min(r['lumped_all_heat_C'] - r['fem_C'] for r in jc), max(r['lumped_all_heat_C'] - r['fem_C'] for r in jc)),
        hot_ab_fem=round(hot['B']['fem'][1], 1) - round(hot['A']['fem'][1], 1),
        hot_ab_lumped=round(hot['B']['lumped'][1], 1) - round(hot['A']['lumped'][1], 1),
        nadir=RES['nadir_view_factor']['numeric'], share=RES['jc']['cold_plate_share'])


N = fe_numbers()


def rng(pair, nd=1):
    a, b = pair
    return f'{fmt(a, nd)} 至 {fmt(b, nd)}'


ENV_LINES = ['设计冷工况：β 角 0°，太阳常数 1321 W/m²，反照率 0.20，地球红外 206 W/m²。',
             '平均环境工况：β 角 0°，太阳常数 1371 W/m²，反照率 0.31，地球红外 241 W/m²。',
             '设计热工况：β 角 75°，太阳常数 1423 W/m²，反照率 0.40，地球红外 286 W/m²。']

CASES = {
    'DM-001': dict(
        func='ThermalParameters、ThermalState、ThermalInputs、ThermalEvaluation', name='公共数据对象', req='TH-01、TH-02、TH-04',
        basis='第 3.2 节；第 5.1 节表 6；第 6.1 节；附录 A',
        intro='本项目验证设计报告第 5.1 节规定的四个公共数据对象，以及第 3.2 节的软件包导出。',
        goal='验证 ThermalParameters、ThermalState、ThermalInputs 与 ThermalEvaluation 的字段、数组维数、数组顺序与构造检查，并检查 thermal 包的公共导出。',
        pre=['四个数据对象已按设计报告表 6 实现，thermal 包已按第 3.2 节组织。'],
        input=['正常构造：C_J_K 为六个正值，R_K_W 为五个正值，temperature_K 为六个正值，ThermalInputs 的环境与四个功率取同一时刻。',
               'Q_B_W 分别取正值与负值。',
               '异常构造：数组维数不符、非有限值、热容或热阻非正、运行标识或时刻不一致。'],
        steps=['用正常输入构造四个对象，读取全部字段。',
               '检查温度顺序为 $S$、$J$、$C$、$B$、$D$、$R$，路径顺序为 SR、JC、CR、BR、DR，环境与辐射数组顺序为 $S$、$R$。',
               '检查 Q_B_W 保留符号。',
               '逐项注入异常构造，记录报错内容。',
               '运行开始后尝试修改 ThermalParameters，并检查试算状态与已接受状态使用独立记录。',
               '检查 __init__.py 导出附录 A 列出的四个数据类型与五个函数。'],
        expect=['字段、维数与顺序符合表 6。', '异常构造被拒绝，报错指出具体字段。', '参数对象在运行开始后只读，试算状态不会覆盖已接受状态。',
                '公共导出与附录 A 一致。'],
        accept='全部字段、维数与顺序与表 6 一致；全部异常构造给出确定的报错；只读、状态分离与公共导出检查全部通过。',
        focus='字段、维数、顺序、只读与状态分离'),
    'PA-001': dict(
        func='assemble_thermal_parameters', name='热容与热阻装配', req='TH-04',
        basis='第 4.5 节式 T5；第 5.2 节；第 9.4 节',
        intro='本项目验证热模块按式 T5 装配组件热容与连接热阻的功能。',
        goal='验证 assemble_thermal_parameters 由资产材料与连接按 T5 装配热容、热阻与表面参数，检查覆盖值优先级、材料重复归属、等效总热阻与数据来源记录。',
        pre=['components 含实例与温度节点对应、材料质量、比热与表面记录。',
             'connections 给出 SR、JC、CR、BR、DR 的长度、导热系数、截面积与接触热阻，或给出经试验确认的等效总热阻。',
             '按同一组输入编制的手算表已经审核。'],
        input=['设计报告第 4.5 节算例：质量 1 kg、比热 1000 J·kg^{−1}·K^{−1} 的材料。',
               '国际空间站模型参数表中的 MBSU 方块：0.94 m×0.84 m×0.51 m，密度 300 kg/m³，比热 900 J·kg^{−1}·K^{−1}；散热器面板面密度 8 kg/m²，比热 900 J·kg^{−1}·K^{−1}。',
               '一组 overrides，修改一个组件的材料质量与一条连接的接触热阻。',
               '异常输入：质量、比热、长度、导热系数或截面积为零或负值，接触热阻为负，同一份材料归入两个组件，重复表面，未定义连接，等效总热阻已含接触热阻又再给出接触热阻。'],
        steps=['调用 assemble_thermal_parameters，读取 C_J_K 与 R_K_W，与手算表逐项比较。',
               '加入 overrides 后重新装配，检查覆盖值优先于资产参数集。',
               '检查热管或液冷等效路径直接读取总热阻，没有再叠加已包含的接触热阻。',
               '逐项注入异常输入，记录报错内容。',
               '检查 ThermalParameters 记录了解析后的数值、单位、资产版本与数据来源，并检查函数没有创建或更新运行温度。'],
        expect=['热容与热阻与手算一致，覆盖值生效。', '每个异常输入都报出具体记录，不生成默认器件参数。', '函数不产生运行温度。'],
        accept='热容与热阻的相对误差不超过 1×10^{−12}；第 4.5 节算例热容为 1000 J/K，MBSU 方块热容为 108.7 kJ/K，散热器面板单位面积热容为 7.2 kJ·m^{−2}·K^{−1}；全部异常输入给出确定的报错。',
        focus='T5 热容与热阻、覆盖值、重复归属、数据来源'),
    'EN-001': dict(
        func='prepare_surface_environment', name='表面环境准备', req='TH-03',
        basis='第 5.3 节；第 6.1 节',
        intro='本项目验证热模块准备同一时刻表面环境输入的功能。',
        goal='验证 prepare_surface_environment 由同一时刻的轨道、姿态与表面记录得到各表面的 cos_incidence，并按资产表面顺序整理环境输入。',
        pre=['orbit_input 含 run_id、time_s、epoch、position_m、sun_position_m、frame、quaternion_xyzw 与 G_W_m2，卫星位置与地心至太阳向量已统一到 GCRS。',
             'earth_flux 与 orbit_input 带有相同的运行标识与时刻。',
             '独立的向量与四元数计算程序可用。'],
        input=['构造姿态：单位四元数，绕三个轴各转 90°，任意组合旋转。',
               '表面法向：星体六个面方向与一个任意方向。',
               '高度 400 km 圆轨道一整圈的 Orbit 输出，含日食段，G 由 sun_intensity 在 include_eclipse 为真时给出。',
               '异常输入：未归一的四元数或法向、卫星位置与太阳向量之差为零、未经转换的 TEME 位置、不支持的坐标系、表面编号错位、缺少 earth_flux 记录。'],
        steps=['用地心至太阳向量减卫星位置并归一，得到卫星指向太阳的方向；对构造姿态逐个计算 cos_incidence，与独立计算比较。',
               '计算一整圈，检查返回字典含 run_id、time_s、surface_ids、G_W_m2、cos_incidence、albedo_W_m2 与 infrared_W_m2，表面数组长度一致并按资产表面顺序排列。',
               '检查 G_W_m2 与 Orbit 输出逐点相同，没有再乘日食系数。',
               '逐项注入异常输入，记录处理结果。'],
        expect=['cos_incidence 与独立计算一致，背向太阳的表面得到负值。', '日食段 $G$ 为零，并且只由 Orbit 给出。',
                '函数不改变温度，异常输入被拒绝。'],
        accept='cos_incidence 误差不超过 1×10^{−12}；整圈 $G$ 与 Orbit 输出逐点相同；全部异常输入给出确定的报错。',
        focus='太阳方向、四元数旋转、入射余弦、日食只计入一次'),
    'EN-002': dict(
        func='calculate_surface_heat', name='表面吸热与辐射', req='TH-03',
        basis='第 4.4 节式 T4；第 5.4 节',
        intro='本项目验证热模块按式 T4 计算外露表面吸热与表面辐射的功能。',
        goal='验证 calculate_surface_heat 按 T4 逐表面计算直射、反照与红外吸热和表面辐射，按 $S$、$R$ 汇总为 Q_env_W 与 Q_emit_W，并给出 absorbed_solar_S_W。',
        pre=['表面面积、吸收率与发射率已装配。', 'EN-001 已通过。'],
        input=['设计报告第 4.4 节算例：面积 2 m²，直射辐照 1000 W/m²，吸收率 0.8。',
               '正对、侧对、背对太阳三种朝向；只有反照、只有红外两种环境。',
               '组件温度 200 K、300 K、400 K。',
               '异常输入：温度为零或负值、辐照度为负、运行标识或时刻不一致、温度超出材料参数适用温区。'],
        steps=['逐个算例计算 Q_env_W、Q_emit_W 与 absorbed_solar_S_W，与手算比较。',
               '检查直射辐照取 $G$ 乘非负入射余弦，直射与反照乘吸收率，红外乘发射率，面积不再重复投影。',
               '检查表面辐射按所属组件的绝对温度四次方计算。',
               '检查太阳能板正面与背面分别计算后再汇总，absorbed_solar_S_W 只含太阳能板吸收的直射太阳功率。',
               '逐项注入异常输入。'],
        expect=['第 4.4 节算例的吸热功率为 1600 W，背对太阳时直射吸热为零。', '温度超出材料适用温区时报告该限制。', '函数不修改状态。'],
        accept='与手算的相对误差不超过 1×10^{−12}；400 K 与 200 K 的辐射功率之比为 16；全部异常输入给出确定的处理结果。',
        focus='T4 直射、反照、红外吸热与表面辐射'),
    'EN-003': dict(
        func='earth_flux 环境输入', name='地球反照与红外输入', req='TH-03',
        basis='第 4.4 节表 5；第 5.3 节；第 9.4 节',
        intro='本项目验证提供给式 T4 的地球反照与红外输入。设计报告第 5.3 节规定这两项由新增环境数据提供，不能从 Orbit 的太阳辐照度推定，本项目检验该数据源。',
        goal='验证 earth_flux 按 surface_id 给出的 albedo_W_m2 与 infrared_W_m2，确认各表面的地球视角系数与反照计算正确。',
        pre=['earth_flux 已按第 5.3 节接入，带有与 orbit_input 相同的运行标识与时刻。'],
        input=['高度 400 km 圆轨道，β 角 0° 与 75°。',
               '反照率与地球红外取国际空间站设计工况值：冷工况 0.20 与 206 W/m²，平均工况 0.31 与 241 W/m²，热工况 0.40 与 286 W/m²。',
               '表面朝向：对地、背地、垂直于当地竖直方向、跟踪太阳。'],
        steps=['对地平板的视角系数与解析值比较，解析值等于地球半径与轨道半径之比的平方。',
               '其余朝向与可见地球表面的数值积分比较。',
               '从已求解的国际空间站有限元模型导出太阳翼与散热器的反照和红外热载荷，与 earth_flux 的计算结果比较。',
               '删去一条反照或红外记录，检查系统按第 9.4 节指出未配置字段，不把缺失值当作零。'],
        expect=['对地平板视角系数与解析值一致。', '各朝向的反照与红外辐照与数值积分一致。', '缺失记录时报出未配置字段。'],
        accept='400 km 对地平板视角系数为 0.8855，误差不超过 0.1%；其余朝向与数值积分相差不超过 1%；与有限元热载荷相差不超过 3%；缺失记录全部报出。',
        actual=f'原型程序用数值积分求得对地平板视角系数 {N["nadir"]:.4f}，与解析值一致。有限元热载荷尚未导出。正式用例未执行。',
        focus='对地视角系数、反照与红外辐照、缺失字段'),
    'HT-001': dict(
        func='calculate_heat_flows', name='组件传热计算', req='TH-01',
        basis='第 4.2 节式 T2；第 5.5 节',
        intro='本项目验证热模块按式 T2 计算连接热流的功能。',
        goal='验证 calculate_heat_flows 按 SR、JC、CR、BR、DR 的固定顺序执行 T2，返回有符号热流。',
        pre=['PA-001 已通过，五条连接的热阻已装配。'],
        input=['设计报告第 4.3 节电池算例：$T_B$ 为 303 K，$T_R$ 为 300 K，$R_BR$ 为 0.5 K/W。',
               '两端温度对调与两端温度相等的情形。',
               '异常输入：缺少节点、数组次序不符、热阻为零或负值、输入为非有限值。'],
        steps=['计算五条连接热流，与手算比较，检查返回字典含 run_id、time_s 与 q_W。',
               '对调两端温度，检查热流变号且大小不变。',
               '检查正值表示由路径名称第一个节点流向第二个节点。',
               '逐项注入异常输入。'],
        expect=['算例热流 $q_BR$ 为 6 W，对调后为 −6 W，等温时为零。', '每条路径只求值一次，函数没有状态更新。',
                '异常输入报告错误，不用零热阻或临时截断热流代替实际路径。'],
        accept='与手算的相对误差不超过 1×10^{−12}；全部异常输入给出确定的报错。',
        focus='T2 有符号热流、路径顺序'),
    'HT-002': dict(
        func='thermal_derivative', name='温度导数与整体热平衡', req='TH-01',
        basis='第 4.1 节式 T1；第 4.3 节式 T3；第 5.6 节',
        intro='本项目验证热模块按式 T3 组成温度导数，并检查式 T1 的整体热平衡。',
        goal='验证 thermal_derivative 按 T3 一次返回 $S$、$J$、$C$、$B$、$D$、$R$ 的温度导数与 ThermalEvaluation，并满足 T1。',
        pre=['EN-002 与 HT-001 已通过。'],
        input=['设计报告第 4.3 节电池算例：$C_B$ 为 1000 J/K，$T_B$ 为 303 K，$T_R$ 为 300 K，$R_BR$ 为 0.5 K/W，$Q_B$ 为 10 W。',
               '随机生成的 1000 组温度、四个功率与环境输入。'],
        steps=['计算电池算例的温升速度。',
               '对随机输入计算各组件热容与温度导数的乘积之和，与 T1 右侧比较。',
               '检查每条热流在流出端减去、在流入端加上。',
               '检查 ThermalEvaluation 含 dT_dt_K_s、q_W、Q_env_W、Q_emit_W、T_B_K 与 T_J_K，T_B_K 与 T_J_K 是本次输入温度的对应值，不是新的积分状态。'],
        expect=['电池算例的温升速度为 0.004 K/s。', '各组件储热之和等于 T1 右侧。'],
        accept='算例温升速度误差不超过 1×10^{−12} K/s；整体热平衡残差与输入总功率之比不超过 1×10^{−12}。',
        focus='T3 温度导数、T1 整体热平衡'),
    'HT-003': dict(
        func='thermal_derivative 与数值求解器', name='解析解对比', req='TH-01',
        basis='第 4.3 节式 T3；第 8 章表 8',
        intro='本项目用有解析解的算例验证温度积分结果。',
        goal='验证 thermal_derivative 与第 8 章的数值求解器组合后得到的温度随时间的变化。',
        pre=['HT-002 已通过。', '积分方法按第 8 章初选 RK45，容限与最大步长已配置。'],
        input=['单节点阶跃：冷板温度保持不变，计算节点的 $P_load$ 由零阶跃到 300 W，$C_J$ 为 500 J/K，$R_JC$ 为 0.1 K/W。',
               '串联稳态：计算节点经冷板连到温度保持不变的散热板，$P_load$ 为 300 W。',
               '辐射平衡：散热板只有固定输入功率与自身表面辐射。'],
        steps=['积分单节点阶跃，与指数解比较。',
               '积分串联算例到稳态，计算节点与散热板的温差应等于功率乘 $R_JC$ 与 $R_CR$ 之和。',
               '积分辐射平衡算例到稳态，稳态温度的四次方应等于输入功率除以发射率、斯忒藩玻尔兹曼常数与辐射面积的乘积。'],
        expect=['三个算例的数值解与解析解一致。'],
        accept='阶跃响应全程误差不超过 0.001 K；两个稳态算例的误差不超过 0.001 K。',
        focus='指数响应、串联热阻稳态、辐射平衡'),
    'EC-001': dict(
        func='ThermalInputs 与 thermal_derivative', name='电热耦合', req='TH-02',
        basis='第 4.1 节；第 4.3 节；第 5.6 节；第 6.1 节',
        intro='本项目验证热模块使用 Power 四个功率端口的功能。',
        goal='验证 P_pv_W、P_load_W、Q_B_W 与 Q_D_W 按 T3 进入对应组件，检查符号约束、光电输出上限、Power 结果有效性与电池温度的单一归属。',
        pre=['HT-002 已通过。', 'Power 的 solve_power_allocation 可用，或使用按 PowerResult 字段构造的输入。'],
        input=['$P_pv$ 在零与本次 absorbed_solar_S_W 之间取值；$P_load$ 在零与额定功率之间取值；$Q_B$ 取正值与负值；$Q_D$ 取正值。',
               '异常输入：P_pv_W、P_load_W 或 Q_D_W 为负，$P_pv$ 大于 absorbed_solar_S_W，valid 为假，event_required 为真。'],
        steps=['每次只改变一个功率，检查只有对应组件的导数变化，变化量等于功率变化除以该组件热容：$P_pv$ 只影响 $S$，$P_load$ 只影响 $J$，$Q_B$ 只影响 $B$，$Q_D$ 只影响 $D$。',
               '$Q_B$ 取负值，检查电池温度导数相应减小。',
               '降低 $P_pv$ 表示控制器限制发电，检查未输出的能量留在太阳能板的能量收支中。',
               '逐项注入异常输入。',
               '与 Power 联合运行一圈，确认电池温度只在热模块中更新，并作为 T_B_K 返回 Power。'],
        expect=['功率进入正确组件，符号保留。', '无效 Power 结果不进入热导数，热模块不修补无效电功率，也不决定负载重启。', '电池温度只更新一次。'],
        accept='导数变化与手算的相对误差不超过 1×10^{−12}；全部异常输入给出确定的处理结果；联合运行中电池温度只在热模块中更新。',
        actual=f'未执行。原型程序给出量级参考：太阳能板节点的 $P_pv$ 取零后，三个工况的最高温度升高 {rng(N["no_pv"])} K。',
        focus='四个功率端口、符号与上限、电池温度单一归属'),
    'FE-001': dict(
        func='太阳能板 $S$', name='太阳能板节点有限元对标', req='TH-01、TH-03',
        basis='第 4.3 节式 T3 第一行；第 4.4 节式 T4；第 4.5 节式 T5',
        intro='本项目用国际空间站美国太阳翼的有限元结果验证太阳能板节点。',
        goal='验证太阳能板按 T3 第一行与 T4 计算的温度，检查环境吸热、实际电输出的扣除与正反两面的表面辐射。',
        pre=['有限元三个工况的第三圈时程与模型参数表可用。',
             '姿态四元数使太阳能板正面法向始终指向太阳，对应有限元中太阳翼的对日规律。',
             '有限元不计太阳翼与散热器之间的导热，SR 连接取极大热阻表示不导热，并按第 9.4 节记录该测试配置。'],
        input=['正面吸收率 0.72、发射率 0.82，背面吸收率 0.55、发射率 0.85，面热容 1.6 kJ·m^{−2}·K^{−1}，均取自有限元模型参数表。',
               '$P_pv$ 取发电份额 0.073 乘太阳能板收到的直射功率，作为 Power 给出的实际电输出。'] + ENV_LINES +
              ['高度 400 km 圆轨道，周期 5553.6 s。'],
        steps=['按工况生成 orbit_input 与 earth_flux。',
               '按第 8 章的数值设置积分到逐圈重复，在日食边界分段，取最后一圈。',
               '与有限元太阳翼平均温度的第三圈比较最低、平均与最高温度。',
               '关闭反照与红外重算一次，按第 9.4 节记录该简化条件和温度差别。'],
        expect=['三个工况的温度曲线与有限元重合。', '关闭反照与红外后温度明显偏低。'],
        accept='三个工况的最低、平均与最高温度与有限元之差均不超过 3 K。',
        actual=(f'原型程序最大差 {fmt(N["s_diff"])} K，见第 7.1 节。关闭反照与红外后，最高温度低 {rng(N["no_earth_max"], 0)} K，'
                f'有日食工况的最低温度低 {rng(N["no_earth_min"], 0)} K。正式用例未执行。'),
        focus='环境吸热、实际电输出扣除、双面表面辐射'),
    'FE-002': dict(
        func='公共散热板 $R$', name='散热板节点有限元对标', req='TH-01、TH-03',
        basis='第 4.3 节式 T3 第六行；第 4.4 节式 T4；第 4.5 节式 T5；第 10 章',
        intro='本项目用国际空间站舱外主动热控系统散热器的有限元结果验证散热板节点。',
        goal='验证散热板按 T3 第六行与 T4 计算的温度，检查各支路进热、环境吸热、双面表面辐射与热容。',
        pre=['有限元每个回路的散热器进热量时程与三个散热器单元的面板平均温度可用。',
             '$q_SR$、$q_CR$、$q_BR$ 与 $q_DR$ 之和用有限元散热器进热量代替。',
             '姿态四元数按有限元散热器指向规律给出：受晒段侧边对日，日食段正面对地。'],
        input=[f'每个回路 24 块面板，单面面积 {RES["r_params"]["area_one_side_m2"]:.1f} m²；$C_R$ 按 T5 由面板质量与比热计算，再加液氨热容，共 {RES["r_params"]["capacity_J_K"] / 1e6:.2f} MJ/K。',
               'Z-93 白色涂层：冷工况吸收率 0.15，平均工况 0.20，热工况 0.24；发射率 0.90 至 0.91。'] + ENV_LINES,
        steps=['以有限元进热量时程驱动散热板节点，从有限元初始温度起算三圈，在日食边界分段积分。',
               '取第三圈，与三个散热器单元面板平均温度的平均值比较。',
               '记录同一时刻有限元最冷面板与平均温度之差。'],
        expect=['平均温度与有限元接近。',
                '残差来自两翼之间的辐射遮挡与面板沿流向的温差。设计报告第 4.4 节与第 10 章说明本版不计组件间相互遮挡、相互辐射与局部温差。'],
        accept='两个回路三个工况的第三圈平均温度差均不超过 5 K。',
        actual=(f'原型程序差 {rng(N["r_diff"])} K，见第 7.2 节。同一时刻有限元最冷面板比散热器平均温度低 {rng(N["cold"], 0)} K，'
                f'集总温度不能代替最冷点。正式用例未执行。'),
        focus='各支路进热、环境吸热、双面表面辐射、热容'),
    'FE-003': dict(
        func='计算节点 $J$ 与冷板 $C$', name='计算节点与冷板有限元对标', req='TH-01、TH-04',
        basis='第 4.3 节式 T3 第二、三行；第 4.5 节式 T5；第 10 章',
        intro='本项目用国际空间站冷板设备的有限元结果验证计算节点到冷板的传热计算。设计报告第 10 章规定安装路径难以确定时可用有限元识别等效热阻，本项目按此检验 JC 热阻的组成。',
        goal='验证 T3 第二行与 T5 第二行，确认均匀发热设备的平均温度可由 $R_JC$ 表示。',
        pre=['有限元平均环境工况的部件统计与回路热量分解可用。',
             '冷板热容取极大值并以冷却液温度为初温，CR 连接取极大热阻，使冷板温度保持为冷却液温度，对应有限元的冷板边界。'],
        input=['MBSU 495 W，冷板面 0.79 m²；DDCU 694 W，冷板面 0.56 m²；IEA 6000 W，冷板面 13.5 m²。',
               '冷板换热系数 60 W·m^{−2}·K^{−1}，设备等效导热系数 150 W·m^{−1}·K^{−1}，冷却液 2.8 °C。',
               f'$P_load$ 取有限元中经冷板排出的热量。有限元方块另有约 {fmt((1 - N["share"]) * 100)}% 的热量经多层隔热向外辐射，设计报告的计算节点不含这条路径。'],
        steps=['按 T5 第二行计算 $R_JC$：接触部分取冷板换热系数与冷板面积乘积的倒数；导热部分以设备厚度的三分之一为导热长度，这是热量在设备内均匀产生时平均温度对应的等效长度。',
               '积分到稳态，此时 $T_J$ 等于冷板温度加 $P_load$ 乘 $R_JC$。',
               '与有限元第三圈平均温度比较。'],
        expect=['三类设备的平均温度与有限元一致。'],
        accept='平均温度差不超过 1 K。',
        actual=f'原型程序差 {fmt(N["jc_diff"])} K 以内，见第 7.3 节。正式用例未执行。',
        focus='JC 热阻组成、均匀发热设备平均温度'),
    'FE-004': dict(
        func='计算节点、冷板与散热板链路', name='整星有限元链路对标', req='TH-01、TH-04',
        basis='第 3.1 节图 1；第 4.3 节式 T3；附录 B',
        intro='本项目用单颗卫星的有限元结果验证图 1 中计算节点经冷板到散热板的传热链路。',
        goal='检查 $J$、$C$、$R$ 三个组件与 JC、CR 两条连接能否表示计算设备到散热板的温降。',
        pre=['2026 年 8 月 30 日完成的整星 COMSOL 结果可用，包括 GPU 基板、机身与散热板温度时程。',
             '整星模型的导热垫与热管参数已按 T5 换算为 $R_JC$ 与 $R_CR$，并记录换算方法与来源。'],
        input=['两个算例：12 块 V100 与 12 块 A100。', '与有限元相同的轨道、姿态与负载功率时程。'],
        steps=['按整星模型参数装配 $J$、$C$、$R$ 三个组件。', '输入相同的功率时程，运行五圈。',
               '取第四、五圈，比较 GPU 基板平均温度与散热板平均温度。'],
        expect=['计算节点经冷板到散热板的链路能复现计算设备与散热板之间的温差。单节点模型在同一对比中比 GPU 基板低 12 至 15 °C。'],
        accept='第四、五圈 GPU 基板与散热板的平均温度差均不超过 5 K。',
        focus='计算设备到散热板的完整温降'),
    'NI-001': dict(
        func='数值求解器设置', name='数值计算与日食边界', req='TH-01',
        basis='第 8 章表 8；第 7 章',
        intro='本项目验证设计报告第 8 章的数值设置。',
        goal='检查自适应 ODE 方法、容限、最大步长、日食与启停边界处理以及输出采样。',
        pre=['FE-001 的平均环境工况可以运行。'],
        input=['积分方法 RK45 与 Radau。',
               '相对容限 1×10^{−6} 与 1×10^{−8}；温度绝对容限 1×10^{−6} K 与 1×10^{−8} K；最大步长 60 s 与 10 s。',
               '输出间隔 10 s 与 60 s；一个负载启停时刻；一个必被拒绝的积分步。'],
        steps=['每种组合各算一次，比较最后一圈温度。',
               '检查进出日食与负载启停时积分在边界处分段，没有跨越边界后平均。',
               '检查输出在已接受解上按所需时刻采样，与内部积分步长无关。',
               '检查被拒绝的积分步没有写入组件温度。'],
        expect=['结果随容限收紧而收敛，RK45 与 Radau 一致。', '边界处理与输出采样符合第 8 章。'],
        accept='容限收紧 100 倍后最后一圈温度变化不超过 0.01 K；RK45 与 Radau 相差不超过 0.01 K；日食进出时刻误差不超过 1 s；输出采样不随内部步长改变。',
        focus='容限收敛、方法一致、日食与启停边界、输出采样'),
    'NI-002': dict(
        func='联合运行与结果归档', name='端到端运行与结果归档', req='TH-01、TH-02',
        basis='第 3.3 节；第 6.3 节；第 7 章；第 9.4 节',
        intro='本项目按设计报告第 7 章的流程验证热模块与 Orbit、Power 的联合运行。',
        goal='检查同一时刻的输入、约束事件处理、温度端口、组件温度的单一归属与结果归档。',
        pre=['Orbit 与 Power 模块可用，资产版本、初值与环境数据已冻结。'],
        input=['一个 24 h 场景，含日食、负载启停与电池约束事件。',
               '一次 Power 返回 valid 为假的试算与一次返回 event_required 为真的试算。'],
        steps=['按第 6.3 节的调用顺序运行场景，保存全部输出。',
               '检查 Power 结果无效时报告错误并停止本次计算；event_required 为真时先回到约束边界，按已声明规则更新负载离散状态，再重新求功率与温度导数。',
               '检查只在积分步被接受后保存温度，计算域读取 $J$ 的温度，Power 下次试算读取 $B$ 的温度。',
               '检查启用热模块后 Orbit 的 power_considering_thermal 不再更新同一太阳能板温度，并检查热模块没有增加断电或降频规则。',
               '用相同输入重复运行，比较两次结果并检查归档字段，记录 Power 求根次数与试算拒绝次数。'],
        expect=['事件与无效结果按第 7 章处理。', '每个组件温度只有一个更新来源。', '两次运行结果相同，归档完整。'],
        accept='两次运行逐位相同，或差值不超过 1×10^{−12}；归档包含 run_id、UTC 起点、time_s、组件标识与状态顺序、温度、Power 四功率端口、热流、求解设置与参数版本；第 2 至 4 步的检查全部通过。',
        focus='事件处理、温度端口、单一温度来源、归档与复现'),
    'NI-003': dict(
        func='SimReady 资产与场景配置', name='资产与场景装配', req='TH-04',
        basis='第 9.3 节表 9；第 9.4 节',
        intro='本项目验证由 SimReady 资产与场景配置装配热模型的功能。',
        goal='检查表 9 的记录、实例对应、几何单位、覆盖值、共用温度节点、独立实例与质量只计一次。',
        pre=['Sat01 下七个实例的资产已登记 asset_id、asset_version、geometry_uri、domain、model_id、parameter_set、ports 与 provenance。'],
        input=['SolarArray01、Battery01、Controller01、PDU01、Compute01、ColdPlate01 与 Radiator01，几何路径位于 /World/Sat01 下并以实例标识命名。',
               '一个显示缩放后的资产；一组 parameter_overrides；同一资产建立的两个实例；一个 model_id 未登记的资产。'],
        steps=['装配场景，读取面积、质量与热容，与资产物理尺寸的手算结果比较。',
               '检查显示缩放后的包围盒没有被当作物理尺寸。',
               '检查 parameter_overrides 优先于资产参数集，材料、几何或安装方式改变后重新计算受影响的热容、面积与热阻。',
               '检查 Controller01 与 PDU01 共用 $D$，电池的热连接 BR 通往散热板，Power 与 Thermal 使用相同的组件实例标识，材料质量只计一次。',
               '检查两个实例各自具有独立温度与电池状态，未登记的 model_id 被拒绝，不从 USD 执行任意代码，并检查光电效率不超过同一表面的吸收率。'],
        expect=['物理参数只由物理尺寸、材料与安装方式决定。', '实例对应与共用温度节点正确。'],
        accept='面积与质量的相对误差不超过 0.1%；第 2 至 5 步的检查全部通过。',
        focus='表 9 记录、几何单位、覆盖值、共用节点、独立实例'),
}

SUMMARY_RESULT = {
    'EN-003': '数值积分原型完成，有限元热载荷待导出',
    'EC-001': f'原型量级参考：$P_pv$ 取零后最高温度升高 {rng(N["no_pv"])} K',
    'FE-001': f'原型对比最大差 {fmt(N["s_diff"])} K，见第 7.1 节',
    'FE-002': f'原型对比差 {rng(N["r_diff"])} K，见第 7.2 节',
    'FE-003': f'原型对比差 {fmt(N["jc_diff"])} K 以内，见第 7.3 节',
}


def build():
    doc = docx.Document(str(TEMPLATE))
    body_end, land_end, final = prepare(doc)
    w = Writer(doc)

    # ------------------------------------------------------------ 1 overview
    w.anchor = body_end
    w.heading(1, '概述')
    w.heading(2, '标识')
    w.field('平台名称：', 'SDTwin。')
    w.field('被测模块：', '热模块 Thermal。')
    w.field('文档名称：', 'SDTwin 热模块软件模块测试报告。')
    w.field('文档用途：', '按《SDTwin 热模块软件模块设计报告》规定热模块各项计算功能的测试方法、参照数据和验收判据，并记录已完成的有限元原型对比结果。')
    w.heading(2, '软件与文档概述')
    w.para('本报告面向热设计、供电与计算模块开发人员，系统测试人员，以及负责资产配置和模型集成的人员。被测对象是设计报告规定的集总热模型，包括太阳能板、计算节点、冷板、电池、'
           '电源设备和公共散热板六个温度节点，SR、JC、CR、BR、DR 五条传热连接，第 5.1 节的四个公共数据对象，以及第 5 章的五个函数：')
    for line in ['assemble_thermal_parameters：从资产与场景装配热容、热阻与表面参数。',
                 'prepare_surface_environment：准备同一时刻各表面的辐照输入。',
                 'calculate_surface_heat：按式 T4 计算太阳能板与散热板的环境吸热和表面辐射。',
                 'calculate_heat_flows：按式 T2 计算五条连接的有符号热流。',
                 'thermal_derivative：按式 T3 计算六个组件的温度导数。']:
        w.bullet(line)
    w.para('测试用例按设计报告第 4 章的式 T1 至 T5、第 5 章的数据对象与函数、第 7 章的运行流程、第 8 章的数值设置和第 9 章的资产装配要求编写，'
           '每个用例在设计依据栏注明对应的章节、公式与函数。热模块目前处于设计阶段，函数尚未实现。有限元对标用例已用按设计报告公式编写的原型程序与国际空间站有限元结果做过对比，'
           '结果记入第 7 章。模块实现后按同一组用例正式执行，因此全部用例的状态当前为未执行。')
    w.heading(2, '缩略语与约定')
    w.caption('缩略语与约定')
    w.table(['术语', '说明'], [
        ['设计报告', '《SDTwin 热模块软件模块设计报告》，2026 年 10 月 2 日版'],
        ['设计依据', '用例所验证的设计报告章节、公式与函数'],
        ['集总模型', '设计报告第 4 章的集总热 RC 模型，每个组件用一个温度代表'],
        ['有限元模型', '国际空间站全站 COMSOL 热模型，按网格计算部件表面与内部的温度分布'],
        ['原型程序', '按设计报告公式与数值设置编写的独立计算程序，用于在模块实现前检验公式与参数'],
        ['ISS', '国际空间站'],
        ['EATCS', '国际空间站舱外主动热控系统，用液氨回路把设备热量送到散热器'],
        ['MBSU、DDCU、IEA', '国际空间站的主母线开关单元、直流变换单元和综合设备组件，三者都装在液氨冷板上'],
        ['GPU', '图形处理器，本项目用作计算芯片'],
        ['第三圈', '有限元计算的最后一个轨道周期，全部统计取这一圈'],
        ['组件符号', '$S$、$J$、$C$、$B$、$D$、$R$ 依次表示太阳能板、计算节点、冷板、电池、电源设备和公共散热板，与设计报告一致'],
    ], [2000, 6309], center_cols=(0,))
    w.para('模块内部温度使用 K。第 7 章的有限元对比结果以 °C 给出温度、以 K 给出温度差，最低、平均与最高温度均为按精确轨道周期时间加权的统计值。')

    # ------------------------------------------------------------ 2 test content
    w.heading(1, '测试内容')
    w.para('测试范围覆盖设计报告第 11 章的四项需求 TH-01 至 TH-04，共 16 个用例，按设计报告的章节分为六组。每个用例对应一个被测函数、数据对象或一项系统级对比，并在第 8 章汇总。')
    for g, ids in GROUPS:
        w.bullet(f'{g}：{"、".join(ids)}。')
    w.caption('功能需求与测试用例追踪')
    rows = []
    k = 0
    for _, ids in GROUPS:
        for cid in ids:
            k += 1
            c = CASES[cid]
            rows.append([str(k), cid, c['func'], c['name'], c['req'], '未执行'])
    w.table(['序号', '用例编号', '被测函数或对象', '测试名称', '对应需求', '状态'], rows,
            [650, 1000, 2750, 1850, 1159, 900], center_cols=(0, 1, 4, 5))
    t_cov = w.tab + 1
    w.para(f'表 {t_cov} 给出设计报告各章节与测试用例的对应关系。每个用例的设计依据栏列出它所验证的章节、公式与函数。')
    w.caption('设计报告章节与测试用例对应')
    w.table(['设计报告章节', '验证内容', '测试用例'], [
        ['2 需求与设计目标', '场景模型组装与组件仿真需求', 'PA-001、NI-003、HT-002、FE-001 至 FE-004'],
        ['3.1 系统架构', '图 1 的组件与传热连接', 'HT-002、FE-004'],
        ['3.2 软件包结构', 'thermal 包的文件与导出', 'DM-001'],
        ['3.3 仿真流程', '图 2 的计算顺序与温度端口', 'NI-002'],
        ['4.1 整体热平衡', '式 T1', 'HT-002'],
        ['4.2 组件间传热', '式 T2', 'HT-001'],
        ['4.3 组件温度变化', '式 T3 与电池算例', 'HT-002、HT-003、EC-001、FE-001 至 FE-004'],
        ['4.4 环境吸热与表面辐射', '式 T4 与表 5', 'EN-002、EN-003、FE-001、FE-002'],
        ['4.5 热容与热阻', '式 T5 与算例', 'PA-001、FE-002、FE-003'],
        ['5.1 公共数据模型', '表 6 的四个数据对象', 'DM-001'],
        ['5.2 热参数装配', 'assemble_thermal_parameters', 'PA-001'],
        ['5.3 表面环境准备', 'prepare_surface_environment 与 earth_flux', 'EN-001、EN-003'],
        ['5.4 表面吸热与辐射', 'calculate_surface_heat', 'EN-002'],
        ['5.5 组件传热计算', 'calculate_heat_flows', 'HT-001'],
        ['5.6 温度导数计算', 'thermal_derivative 与 Power 连接', 'HT-002、EC-001'],
        ['6.1 通用约定', '时间、数组顺序、功率与温度字段、Orbit 输出', 'DM-001、EN-001、EC-001'],
        ['6.2 主要调用接口', '表 7 的五个调用', 'PA-001、EN-001、EN-002、HT-001、HT-002'],
        ['6.3 最小端到端调用示例', '调用顺序与积分步接受', 'NI-002'],
        ['7 端到端运行流程', '联合试算、约束事件与温度端口', 'NI-002'],
        ['8 数值设计与性能', '表 8 的数值方法与控制参数', 'HT-003、NI-001'],
        ['9.1 运行环境、9.2 安装与解释器配置', '解释器、依赖与源代码版本', '第 5 章测试条件'],
        ['9.3 SimReady 资产与场景组装', '表 9 的记录与实例', 'NI-003'],
        ['9.4 参数设置与结果归档', '来源、初值、简化条件与归档', 'PA-001、EN-003、FE-001、NI-002'],
        ['10 限制与后续扩展', '集总温度、组件间辐射、等效热阻', 'FE-002、FE-003 记录限制的量级'],
        ['11 需求追踪矩阵', 'TH-01 至 TH-04', f'表 {t_cov - 1} 的全部用例'],
        ['附录 A 公共 API 清单', '拟议公开名称', 'DM-001'],
        ['附录 B 模型选择建议', '有限元识别等效参数与局部热点', 'FE-003、FE-004'],
    ], [2600, 3100, 2609], center_cols=())
    t3 = w.tab + 1
    w.para(f'表 {t3} 列出各项对比使用的参照和已有数据。参照分为设计报告算例、手算、解析解、独立数值计算和有限元结果五类。国际空间站有限元结果可直接用于 FE-001 至 FE-003 与 EN-003，'
           '整星有限元结果可用于 FE-004，其余用例使用设计报告算例、手算、解析解或独立数值计算。')
    w.caption('对比项与参照来源')
    w.table(['序号', '对比项', '参照', '已有数据', '当前状态'], [
        ['1', '数据对象的字段、维数与顺序', '设计报告表 6', '无', '待执行'],
        ['2', '热容与热阻', '手算', '设计报告第 4.5 节算例；国际空间站模型参数表', '待执行'],
        ['3', '入射余弦与日食', '独立向量计算；Orbit 输出', '无', '待执行'],
        ['4', '吸热与辐射功率', '手算', '设计报告第 4.4 节算例', '待执行'],
        ['5', '地球反照与红外辐照', '视角系数解析值；数值积分；有限元轨道热载荷', '数值积分程序已完成；有限元热载荷可从已求解模型导出', '部分完成'],
        ['6', '连接热流与温度导数', '手算；整体热平衡 T1', '设计报告第 4.3 节电池算例', '待执行'],
        ['7', '温度积分', '解析解', '无', '待执行'],
        ['8', '电热耦合', '构造算例', '原型程序中实际电输出对太阳能板温度的影响', '待执行'],
        ['9', '太阳能板温度', '国际空间站有限元，美国太阳翼', '三个工况第三圈结果', '原型已对比'],
        ['10', '散热板温度', '国际空间站有限元，EATCS 散热器', '三个工况两个回路第三圈结果', '原型已对比'],
        ['11', '计算节点温度', '国际空间站有限元，MBSU、DDCU、IEA', '平均环境工况第三圈结果', '原型已对比'],
        ['12', '计算节点到散热板的链路', '整星有限元', '两个算例五圈结果', '待执行'],
        ['13', '数值设置', '收紧容限后的自身结果；解析解', '无', '待执行'],
        ['14', '端到端流程与归档', '设计报告第 7 章流程；重复运行', '无', '待执行'],
        ['15', '资产与场景装配', '资产物理尺寸；设计报告表 9', '无', '待执行'],
    ], [620, 1900, 2250, 2400, 1139], center_cols=(0, 4))

    # ------------------------------------------------------------ 3 detailed test projects
    w.heading(1, '详细测试项目')
    w.para('以下用例采用统一的执行记录格式，设计依据栏注明用例所验证的设计报告内容。验收判据为本版默认门限，模块需求给出更严格的数值时以需求为准。'
           '有限元对标用例的实际结果栏记录原型程序的对比结果，正式执行时替换为模块输出的对比结果。')
    k = 0
    for g, ids in GROUPS:
        w.heading(2, g)
        if g == '有限元对标':
            w.para('本组用例把集总模型的计算结果与有限元结果比较。集总模型用一个温度代表一个组件，比较对象取有限元同一部件的平均温度。有限元结果文件见第 6 章。')
        for cid in ids:
            k += 1
            c = dict(CASES[cid], id=cid)
            w.heading(3, f'测试项目 {k}：{c["name"]}')
            w.para(c['intro'])
            w.caption(f'{cid} {c["name"]}测试用例')
            w.case_table(c)

    # ------------------------------------------------------------ 4 sufficiency
    w.heading(1, '测试内容充分性分析')
    w.para(f'16 个用例与设计报告逐章对应，对应关系见表 {t_cov}：式 T1 至 T5、第 5 章的四个数据对象与五个函数、第 6 章的接口约定、第 7 章的运行流程、'
           '第 8 章的数值设置和第 9 章的资产装配与结果归档都有对应用例，四项需求 TH-01 至 TH-04 也都有对应用例。')
    w.para('有限元对标覆盖太阳能板、公共散热板、计算节点与冷板，以及 JC 连接。电池与电源设备两个组件、SR、BR、DR 三条连接没有有限元参照，由设计报告算例、手算、解析解与整体热平衡检验。'
           '电池电化学模型由 Power 的测试报告覆盖。')
    w.para(f'国际空间站对比同时给出了设计报告第 10 章所列限制的量级：散热器同一时刻最冷面板比平均温度低约 {fmt(sum(N["cold"]) / 2, 0)} K，两翼之间的辐射遮挡造成约 3 K 的偏差，'
           '芯片热点不在组件温度中出现。这三项属于本版已说明的限制，测试中只作记录，不作为不通过的依据。')
    w.para('本框架覆盖测试规格，执行尚未开始。正式结论需要已实现的模块、冻结的配置与数据、独立的参照计算以及每个用例的审阅确认。')

    # ------------------------------------------------------------ 5 conditions
    w.heading(1, '测试条件与要求')
    for line in ['记录热模块源代码版本、Python 与依赖版本、操作系统与处理器，与设计报告第 9.1 节的运行环境一致。',
                 '记录 UTC 起点、坐标系与组件状态顺序；模块内部温度使用 K，时间使用 s，功率与传热使用 W。',
                 '按设计报告第 9.4 节，启动前保存解析后的参数、来源、初值与环境配置；关闭环境项的工况记录该简化条件。',
                 '冻结资产版本、参数集、环境工况与有限元参照文件，并记录散列值。',
                 '参照计算独立进行，设计报告算例、手算表、解析解与有限元结果不使用热模块代码。',
                 '有限元对比统一取第三圈，按精确轨道周期做时间加权统计，比较同一部件的平均温度。']:
        w.bullet(line)

    # ------------------------------------------------------------ 6 test data
    w.heading(1, '测试数据')
    w.para('全部测试数据应受版本控制，并记录来源、适用范围、时刻与坐标约定以及散列值。')
    w.caption('测试数据清单')
    w.table(['序号', '测试数据', '数据类型', '形式', '来源'], [
        ['1', 'SDTwin 热模块软件模块设计报告', '依据', 'DOCX', 'Thermal/SDTwin_Thermal_Design_Report_CN.docx'],
        ['2', '设计报告算例与手算表', '参照', 'XLSX、CSV', '测试人员按设计报告第 4 章编制'],
        ['3', '国际空间站模型参数', '输入', 'Python', 'Thermal/iss_fem/model/iss_spec.py'],
        ['4', '有限元三个工况时程', '参照', 'CSV', 'Thermal/iss_fem/out 下各工况目录的 series.csv'],
        ['5', '有限元部件统计与回路热量分解', '参照', 'CSV', '同上目录的 items.csv 与 loop_breakdown.csv'],
        ['6', '已求解的有限元模型', '参照', 'MPH', 'Thermal/iss_fem/out/comsol，用于导出表面热载荷'],
        ['7', '整星有限元结果', '参照', 'CSV、JSON', 'space-compute-demo/tools/comsol_benchmark/full_twin/out'],
        ['8', '原型对比程序与结果', '证据', 'Python、JSON、PNG', 'Thermal/test_report 下的 fe_compare.py、figures.py 与 out 目录'],
        ['9', '运行清单、模块输出、日志与对比报告', '证据', 'JSON、CSV、TXT', '正式执行时生成'],
    ], [650, 2000, 1000, 1100, 3559], center_cols=(0, 2, 3))

    # ------------------------------------------------------------ 7 FE prototype results
    w.heading(1, '有限元原型对比结果')
    w.para('本章记录原型程序与国际空间站有限元结果的对比。原型程序按设计报告第 4 章编写：太阳能板与公共散热板按式 T3 与式 T4 计算，热容与热阻按式 T5 计算，计算节点按式 T3 第二行计算；'
           '积分按第 8 章采用自适应 RK45，在日食边界分段，输出在已接受解上按 10 s 采样。参数全部取自有限元模型参数表，没有拟合任何参数。有限元统计取第三圈，按精确轨道周期时间加权。')

    w.heading(2, '太阳能板')
    t_s = w.tab + 1
    w.para('太阳能板按式 T3 第一行计算：$Q_env,S$ 按式 T4 由正面吸收率 0.72 与背面吸收率 0.55 计算，$P_pv$ 取发电份额 0.073 乘直射功率，$q_SR$ 为零，'
           f'$Q_emit,S$ 按正反两面的发射率计算。姿态使正面法向始终指向太阳。表 {t_s} 与图 {w.fig + 1} 给出三个工况第三圈的对比。')
    w.caption('太阳能板第三圈温度对比')
    rows = []
    for case in ('cold0', 'nom0', 'hot75'):
        s = RES['cases'][case]['S']
        rows.append([CASE_NAMES[case], ' / '.join(fmt(v) for v in s['fem']), ' / '.join(fmt(v) for v in s['lumped']),
                     fmt(max(abs(a - b) for a, b in zip(s['fem'], s['lumped'])))])
    w.table(['工况', '有限元 最低 / 平均 / 最高 °C', '集总模型 最低 / 平均 / 最高 °C', '最大差 K'], rows,
            [1700, 2600, 2600, 1409], center_cols=(0, 1, 2, 3))
    w.picture(HERE / 'out' / 'fig_solar_node.png', 14.6)
    w.caption('太阳能板第三圈温度对比', kind='图')
    w.para('图中蓝色实线为有限元太阳翼平均温度，橙色虚线为集总模型，灰色区域为日食。设计热工况全程受晒，纵轴范围单独设置。')
    w.para(f'三个工况的最大差为 {fmt(N["s_diff"])} K。按设计报告第 9.4 节记录简化条件后关闭反照与红外，最高温度低 {rng(N["no_earth_max"], 0)} K，'
           f'有日食工况的最低温度低 {rng(N["no_earth_min"], 0)} K，说明设计报告第 5.3 节要求补充的 earth_flux 不可缺少。$P_pv$ 取零相当于控制器把发电全部限掉，'
           f'最高温度升高 {rng(N["no_pv"])} K，这部分能量按设计报告第 4.3 节留在太阳能板的能量收支中。')

    w.heading(2, '公共散热板')
    t_r = w.tab + 1
    w.para('每个回路的三个散热器单元合为一个散热板组件，按式 T3 第六行计算：$q_SR$、$q_CR$、$q_BR$ 与 $q_DR$ 之和取有限元的散热器进热量，$Q_env,R$ 与 $Q_emit,R$ 按式 T4 由两面计算，'
           f'$C_R$ 按式 T5 由面板质量与比热计算。表 {t_r} 与图 {w.fig + 1} 给出对比。')
    w.caption('公共散热板第三圈平均温度对比')
    rows = []
    for case in ('cold0', 'nom0', 'hot75'):
        for lp in ('A', 'B'):
            r = RES['cases'][case]['R'][lp]
            rows.append([CASE_NAMES[case], f'回路 {lp}', fmt(r['q_in_kW']), fmt(r['fem'][1]), fmt(r['lumped'][1]),
                         fmt(round(r['lumped'][1], 1) - round(r['fem'][1], 1))])
    w.table(['工况', '回路', '进热量 kW', '有限元 °C', '集总模型 °C', '集总减有限元 K'], rows,
            [1700, 1100, 1300, 1400, 1500, 1309], center_cols=(0, 1, 2, 3, 4, 5))
    w.picture(HERE / 'out' / 'fig_radiator_node.png', 14.6)
    w.caption('公共散热板第三圈温度对比', kind='图')
    w.para('图中上排为回路 A，下排为回路 B，各分图纵轴范围单独设置，灰色区域为日食。')
    w.para(f'平均温度差为 {rng(N["r_diff"])} K。设计热工况中，有限元回路 B 比回路 A 高 {fmt(N["hot_ab_fem"])} K，集总模型只得到 {fmt(N["hot_ab_lumped"])} K，'
           '多出的约 3 K 来自两翼之间的遮挡。设计报告第 4.4 节说明本版不计组件间相互遮挡与相互辐射，有限元报告也说明这一遮挡来自两翼整体转动的建模简化。'
           f'同一时刻有限元最冷面板比散热器平均温度低 {rng(N["cold"], 0)} K，进口面板与出口面板最多相差 {rng(N["spread"], 0)} K。'
           '设计报告第 10 章说明散热板只用集总温度、不计算局部温差，防冻判断需要另算最冷点。')

    w.heading(2, '计算节点与冷板')
    t_b = w.tab + 1
    w.para('计算节点按式 T3 第二行在稳态下求温度，$T_J$ 等于冷板温度加 $P_load$ 乘 $R_JC$。$R_JC$ 按式 T5 第二行取导热部分与接触部分之和：接触部分取冷板面换热的热阻，'
           '导热部分以设备厚度的三分之一为导热长度。冷板温度保持为冷却液温度。'
           f'$P_load$ 取有限元中经冷板排出的热量；有限元方块另有约 {fmt((1 - N["share"]) * 100)}% 的热量经多层隔热向外辐射，设计报告的计算节点不含这条路径。表 {t_b} 给出平均环境工况的对比。')
    w.caption('计算节点平均温度对比')
    rows = []
    for r in RES['jc']['rows']:
        rows.append([r['name'], f'{r["P_load_W"]:.0f}', f'{r["A_m2"]:.2f}', f'{r["R_contact"]:.5f}', f'{r["R_cond"]:.5f}',
                     f'{r["R_JC"]:.5f}', fmt(r['lumped_C']), fmt(r['fem_C']), fmt(round(r['lumped_C'], 1) - round(r['fem_C'], 1))])
    w.table(['设备', '$P_load$ W', '冷板面积 m²', '接触部分 K/W', '导热部分 K/W', '$R_JC$ K/W', '集总模型 °C', '有限元 °C', '集总减有限元 K'], rows,
            [780, 820, 900, 950, 950, 950, 950, 900, 1109], center_cols=tuple(range(9)))
    w.para(f'三类设备的差在 {fmt(N["jc_diff"])} K 以内。$P_load$ 若取设备全部发热，差为 {rng(N["jc_all"])} K，多出的部分对应经多层隔热辐射的热量。'
           '均匀发热设备的平均温度可由式 T5 的 $R_JC$ 表示；真实计算板的热量集中在芯片上，按设计报告第 4.3 节仍需用整板功率与芯片测温标定。')

    w.heading(2, '小结')
    w.para(f'原型对比表明，参数取自同一来源时，设计报告的公式能复现有限元的部件平均温度：太阳能板差 {fmt(N["s_diff"])} K 以内，公共散热板差 '
           f'{fmt(N["r_diff"][1])} K 以内，计算节点差 {fmt(N["jc_diff"])} K 以内。对比同时给出了设计报告第 10 章所列限制的量级：散热板最冷点、组件间遮挡与芯片热点。'
           '热模块实现后按 FE-001 至 FE-003 正式执行，FE-004 与 EN-003 的有限元部分仍待完成。')

    # ------------------------------------------------------------ 8 summary, landscape section
    w.anchor = land_end
    w.heading(1, '测试总结')
    w.para('全部用例当前标记为未执行。按验收判据完成评价并保存执行证据后，再更新状态。')
    w.caption('热模块测试总结')
    rows = []
    k = 0
    for _, ids in GROUPS:
        for cid in ids:
            k += 1
            c = CASES[cid]
            rows.append([str(k), cid, c['func'], c['focus'], '未执行',
                         SUMMARY_RESULT.get(cid, '正式执行后附运行清单、输出、对比报告与日志')])
    w.table(['序号', '用例编号', '被测函数或对象', '验证重点', '状态', '结果与证据'], rows,
            [650, 1000, 3000, 3500, 800, 5004], center_cols=(0, 1, 4))
    w.para('总体结论：☐ 通过  ☐ 不通过  ☒ 未执行', indent=False, before=240)
    w.para('测试负责人签字：____________________　日期：____________', indent=False)

    # ------------------------------------------------------------ appendix, last section
    w.anchor = final
    w.appendix_heading('附录 A 参考资料')
    for ref in ['[1] 南洋理工大学计算与数据科学学院. SDTwin 热模块软件模块设计报告. 2026年10月2日.',
                '[2] NTU Space Dynamics. Test Report for Orbit Dynamics Module of SDCTwin. 2026年8月17日.',
                '[3] 南洋理工大学计算与数据科学学院. 国际空间站有限元热建模与分析报告. 2026年9月30日.',
                '[4] OrbitWiz 单节点热模型与 COMSOL 整星有限元对比报告. 2026年8月30日. space-compute-demo/tools/comsol_benchmark/full_twin/REPORT.md.',
                '[5] NASA. Guidelines for the Selection of Near-Earth Thermal Environment Parameters for Spacecraft Design. NASA/TM-2001-211221, 2001.',
                '[6] NASA. International Space Station Payload Thermal Environments, TFAWS 2015 short course. SSP 41000 设计验证热环境与空间站平均环境。']:
        w.para(ref)

    doc.save(str(OUT_DOCX))
    print('tables', w.tab, 'figures', w.fig, '->', OUT_DOCX)


if __name__ == '__main__':
    build()
