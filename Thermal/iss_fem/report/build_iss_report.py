# -*- coding: utf-8 -*-
"""Build the ISS FE thermal modelling and analysis report (Chinese): Word (via report/docx_helpers.py)
and a Markdown twin in docs/REPORT.md. All result numbers come from iss_results.py.

    python build_iss_report.py [--cases cold0,hot75,nom0]
then  powershell -File finalize.ps1   (Word: update fields, export PDF)
"""
import argparse, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # Thermal/iss_fem
REPO = os.path.dirname(os.path.dirname(ROOT))       # repo root
sys.path.insert(0, os.path.join(REPO, 'report'))
sys.path.insert(0, os.path.join(ROOT, 'model'))
sys.path.insert(0, HERE)
from docx_helpers import Report
import iss_results as R
import iss_spec as S

FIG = os.path.join(ROOT, 'out', 'figures')
CASE_LABEL = {'cold0': '设计冷工况', 'hot75': '设计热工况', 'nom0': '平均环境工况'}


class Dual:
    """Writes the same content to a Word Report and to Markdown."""
    def __init__(self):
        self.r = Report('zh'); self.md = []; self.fig = 0; self.tab = 0

    def h(self, level, text):
        self.r.h(level, text); self.md.append('\n' + '#' * (level + 1) + ' ' + text + '\n')

    def p(self, text):
        self.r.p(text); self.md.append(self._md_marks(text) + '\n')

    @staticmethod
    def _md_marks(text):
        out, i = '', 0
        while i < len(text):
            if text.startswith('_{', i) or text.startswith('^{', i):
                tag = 'sub' if text[i] == '_' else 'sup'
                k = text.index('}', i)
                out += f'<{tag}>{text[i + 2:k]}</{tag}>'; i = k + 1
            else:
                out += text[i]; i += 1
        return out

    def items(self, rows):
        for lab, txt in rows:
            self.r.item(lab, txt); self.md.append(f'{lab}{self._md_marks(txt)}\n')

    def formula(self, text):
        self.r.formula(text); self.md.append('\n' + self._md_marks(text) + '\n')

    def figure(self, path, caption, width_cm=15.5):
        if not os.path.exists(path):
            self.r.p(f'图缺失：{os.path.basename(path)}'); self.md.append(f'图缺失：{os.path.basename(path)}\n'); return
        self.r.figure(path, caption, width_cm); self.fig += 1
        rel = os.path.relpath(path, os.path.join(ROOT, 'docs')).replace('\\', '/')
        self.md.append(f'\n![图 {self.fig} {caption}]({rel})\n\n图 {self.fig}  {caption}\n')

    def table(self, caption, header, rows, widths=None):
        self.r.table(caption, header, rows, widths_cm=widths); self.tab += 1
        self.md.append(f'\n表 {self.tab}  {caption}\n\n| ' + ' | '.join(header) + ' |\n|' + '---|' * len(header) + '\n')
        for row in rows:
            self.md.append('| ' + ' | '.join(self._md_marks(str(x)).replace('\n', '<br>') for x in row) + ' |\n')
        self.md.append('\n')

    def page_break(self):
        self.r.page_break()


def f1(x): return f'{x:.1f}'
def f0(x): return f'{x:.0f}'
def kw(x): return f'{x / 1e3:.1f}'


def cover(D):
    r = D.r
    for _ in range(6): r.doc.add_paragraph()
    para = r.doc.add_paragraph(); para.alignment = 1
    from docx_helpers import set_font
    run = para.add_run('国际空间站有限元热建模与分析报告'); set_font(run, cn='黑体', size=24, bold=True)
    for _ in range(3): r.doc.add_paragraph()
    r.kv_table([('模型工具', 'COMSOL Multiphysics 6.3 传热模块，由 Python 的 MPh 库驱动'), ('分析对象', '国际空间站 2019 年构型全站'),
                ('分析工况', '设计冷工况、设计热工况、平均环境工况'), ('编制日期', '2026 年 9 月 30 日')])
    r.page_break(); r.toc(); r.page_break()
    D.md.append('# 国际空间站有限元热建模与分析报告\n\n本报告编制于 2026 年 9 月 30 日，模型用 COMSOL Multiphysics 6.3 传热模块建立，由 Python 的 MPh 库驱动。\n')


ABBR = [
    ('EATCS', 'External Active Thermal Control System', '舱外主动热控系统'),
    ('IATCS', 'Internal Active Thermal Control System', '舱内主动热控系统'),
    ('PVTCS', 'Photovoltaic Thermal Control System', '光伏热控系统'),
    ('PVR', 'Photovoltaic Radiator', '光伏散热器'),
    ('ORU', 'Orbital Replacement Unit', '在轨可更换单元'),
    ('IEA', 'Integrated Equipment Assembly', '综合设备组件'),
    ('IFHX', 'Interface Heat Exchanger', '界面换热器'),
    ('FCV', 'Flow Control Valve', '流量控制阀'),
    ('SARJ', 'Solar Alpha Rotary Joint', '太阳翼阿尔法旋转关节'),
    ('BGA', 'Beta Gimbal Assembly', '贝塔万向组件'),
    ('TRRJ', 'Thermal Radiator Rotary Joint', '散热器旋转关节'),
    ('RGAC', 'Radiator Goal Angle Calculation', '散热器目标转角计算'),
    ('MBSU', 'Main Bus Switching Unit', '主母线开关单元'),
    ('DDCU', 'DC-to-DC Converter Unit', '直流变换单元'),
    ('ATA、PM、NTA', 'Ammonia Tank Assembly、Pump Module、Nitrogen Tank Assembly', '氨罐组件、泵模块、氮罐组件'),
    ('ELC', 'ExPRESS Logistics Carrier', 'ExPRESS 后勤托架'),
    ('AMS-02', 'Alpha Magnetic Spectrometer', '阿尔法磁谱仪'),
    ('JEM-EF', 'Japanese Experiment Module Exposed Facility', '日本实验舱暴露平台'),
    ('PMM、PMA、BEAM', 'Permanent Multipurpose Module、Pressurized Mating Adapter、Bigelow Expandable Activity Module', '永久多用途舱、加压对接适配器、可扩展活动舱'),
    ('+XVV', '+X Velocity Vector', '+X 轴沿速度矢量的对地定向姿态'),
    ('BDF', 'Backward Differentiation Formula', '后向差分公式'),
]


def build(cases):
    D = Dual()
    cover(D)
    tagmap = {}
    for i, c in enumerate(list(cases)):
        if ':' in c:
            tg, cs = c.split(':'); tagmap[cs] = tg; cases[i] = cs
    C = {c: R.load_case(tagmap.get(c, c)) for c in cases}
    LT = {c: R.loop_table(C[c]) for c in cases}
    CT = {c: R.class_table(C[c]) for c in cases}
    PER = {c: R.periodicity(C[c]) for c in cases}
    IT = {c: R.items_by_kind(C[c]) for c in cases}
    t_end = float(C[cases[0]]['t'][-1]); per0 = C[cases[0]]['per']

    # ------------------------------------------------------------------ 1
    D.h(1, '1 概述')
    D.p('本报告记录国际空间站有限元热模型的建立过程与轨道热分析结果。模型在 COMSOL Multiphysics 6.3 中由 Python 脚本建立，'
        '几何、材料、表面性质与热负荷依据文献 A、B、C 三份热控文献、NASA 公开三维模型、SSP 30219 坐标系规范与公开工程资料确定，'
        '每个取值都注明了文献、公开资料或模型取定依据。舱内机柜、舱外电子设备与舱外载荷简化为方块热源。机柜与舱外电子设备的热量经冷板进入冷却回路，'
        '由散热器面板向深空辐射；舱外载荷不接冷板，由方块外表面直接向空间辐射。分析覆盖设计冷工况、设计热工况与平均环境工况，'
        f'每个工况由当地正午起连续计算 {t_end:.0f} s，即 {t_end / per0:.2f} 个轨道周期，统计取最后一个轨道周期，文中称第三圈。'
        '另建散热器排热能力子模型，求 EATCS 散热器在三个工况下的排热能力。')
    D.h(2, '1.1 主要结论')
    D.items(conclusions(C, LT, CT, PER))
    D.h(2, '1.2 缩略语')
    D.table('缩略语', ['缩略语', '英文全称', '中文名称'], [list(r) for r in ABBR], widths=[3.0, 7.4, 5.4])

    # ------------------------------------------------------------------ 2
    D.h(1, '2 依据资料')
    D.p('模型参数分三个层次取得。第一层是任务提供的三份热控文献，即表 2 中的文献 A、B、C，给出主动热控系统的组成、散热器与设备尺寸、回路流量与控制设定值。'
        '第二层是公开工程资料，补全全站几何、表面光学性质、材料热物性、热负荷与空间热环境。第三层是模型取定值，用于公开资料没有覆盖的参数，'
        'model/iss_spec.py 中标为 D 的条目逐项给出取值与推算方法，主要项列于第 3.9 节。')
    D.p('公开资料按舱段布局、桁架与转动部件、三维模型、表面光学性质与材料、热负荷与空间环境五个方向收集。除三维模型外的四个方向另做了一轮独立核验检索，'
        '逐项对照原文复查对模型影响最大的 147 个数值；三维模型方向只做了单位、坐标轴与总长的自检。核验建议中没有被模型采用的条目列于第 3.9 节。')
    D.table('依据资料与用途，代号沿用 docs 目录资料文档中的编号', ['代号', '资料', '用途'], [
        ['A', 'Active Thermal Control System ATCS Overview，Boeing', 'EATCS 与 PVTCS 组成、散热器与设备尺寸、流量、供液设定点、舱内水回路温度'],
        ['B', 'ICES-2019-31 P1 EATCS Ammonia Leak，NASA JSC', '散热器布置、回路与桁架段关系'],
        ['C', '05ICES-279 IATCS Coolant Remediation，Boeing 与 NASA', '舱内水回路控温范围的旁证'],
        ['G3D', 'NASA 3D Resources IGOAL 模型，JSC', '桁架段、散热器、PVR 纵向范围、太阳翼 BGA 转轴、舱外载荷以及 Destiny、Unity、Harmony、Zarya、Zvezda 与三个 PMA 的位置'],
        ['T2', 'NASA 与 TopCoder ISS 官方坐标模型', '太阳翼毯面尺寸、间隙与翼根起点，PVR 横向位置'],
        ['W1', 'SSP 30219 Rev F 空间站坐标系规范', '坐标系、SARJ、BGA、TRRJ 转轴与零位定义'],
        ['JSC 26557', 'ISS On-Orbit Assembly, Modeling and Mass Properties Data Book', '舱段质心与外包络'],
        ['RG', 'Reference Guide to the ISS 2010 与 ESA、JAXA 舱段简介资料', '舱段长度与直径'],
        ['D2', 'NASA/TM-2001-211221 近地轨道航天器设计热环境参数选取指南', '反照率整轨平均修正'],
        ['D3', 'NASA TFAWS 2015 国际空间站载荷热环境课程', 'SSP 41000 设计验证环境、舱外活动热数据库平均环境'],
        ['D4', 'TD9702A International Space Station Familiarization，NASA JSC', 'EATCS 排热能力与设计流量'],
        ['D5', 'NASA/SP-2000-6109 ISS Evolution Data Book Volume I', 'EATCS 排热能力、热负荷分配、β 角范围'],
        ['D13', 'SSP 57000 Rev E 加压载荷接口要求', '机柜前面板平均温度限值'],
        ['D15', 'Wise 与 Holt，TFAWS 2001 Tranquility 节点舱再生换热器分析', 'Tranquility 节点舱舱壁环境热负荷'],
        ['D16', 'ICES-2022-145 Coolant Leak from ISS EATCS，Cowan 与 Bond', '散热器回流接头与 P1 散热器在轨温度'],
        ['D17', 'TFAWS18-AT-01 Ammonia Vent of the EATCS Radiator，Cowan', '散热器流路在轨温度极值'],
        ['D18', 'NASA/TM-2005-213988 美国太阳翼地影工况性能，Kerslake 与 Scheiman', '太阳翼毯面光学性质与地影温度'],
        ['D19', 'NASA CR-2006-213693 生命保障基线值文件', '乘员代谢热'],
        ['O 系列', '热控涂层与材料文献，MIL-HDBK-5J，NIST；其中 O14、O17 为太阳翼在轨温度，O25 为 BEAM 热分析', '表面光学性质、材料热物性与太阳翼温度'],
        ['V1', 'Finckenor 等，MISSE 6 空间站材料分析', '国际空间站专用批次镀铝 beta 布光学性质'],
    ], widths=[2.0, 7.4, 6.4])
    D.p('各方向的原始记录与核验记录保存在 docs 目录。模型采用的最终取值以 model/iss_spec.py 为准，docs/ISS_SPEC.md 记录各取值的来源与理由。'
        '核验取得 SSP 30219 修订版 F，该规范图 4.0-8 规定 TRRJ 绕 X 轴转动，图 5.0-10 给出零位时三个散热器 ORU 沿 Z 叠放、面板平面法向沿 Y 轴，'
        '转过 90° 后面板平躺，为正面对地姿态；图 4.0-8 续页另有一句把零位写作散热器梁位于 x-y 平面，与图 5.0-10 矛盾，模型按图 5.0-10 取零位。')

    # ------------------------------------------------------------------ 3
    D.h(1, '3 有限元模型')
    D.h(2, '3.1 坐标系、构型与姿态')
    D.p('坐标系为空间站分析坐标系：原点在 S0 桁架段几何中心，+X 平行美国段舱段轴线指向飞行方向，+Y 指向右舷，+Z 指向天底。'
        '构型取 2019 年状态：永久多用途舱 PMM 位于 Tranquility 节点舱前向口，加压对接适配器 PMA-3 位于 Harmony 节点舱天顶口，'
        'Pirs 对接舱位于 Zvezda 服务舱天底口，BEAM 可扩展舱位于 Tranquility 节点舱后向口。姿态为 +XVV 对地定向，即 +X 轴沿速度矢量、+Z 轴始终指向天底，'
        '力矩平衡姿态相对该姿态的小角度偏置不计。'
        f'轨道高度 {S.ORBIT["alt_m"] / 1e3:.0f} km，倾角 {S.ORBIT["incl_deg"]}°，周期 {per0:.1f} s。')
    D.h(2, '3.2 几何模型')
    D.p('几何全部由 COMSOL 的基本几何体生成。加压舱为先建实体圆柱再转换得到的封闭曲面，赋壳单元；桁架段、舱外设备、IEA、舱外载荷与舱内机柜为实体方块；'
        'EATCS 散热器、PVR 与太阳翼毯面为工作平面上的矩形曲面，赋壳单元。部件之间留 5 cm 间隙，几何经自动包围盒检查无相交。')
    D.table('几何模型组成', ['部件类别', '数量', '单元类型', '说明'], [
        ['加压舱', '20', '壳', '19 个舱段，美国段 14 个，俄罗斯段 5 个；Zvezda 服务舱按小直径段与大直径段建为 2 个圆柱，均含端盖'],
        ['桁架段', '12', '实体', 'Z1、S0、S1、S3 至 S6、P1、P3 至 P6，空间站没有 S2 与 P2 段'],
        ['冷板设备', '10', '实体', 'MBSU 4 台，DDCU 6 台'],
        ['EATCS 不发热设备', '6', '实体', '氨罐组件、泵模块、氮罐组件各 2 台，不计泵电机热量'],
        ['IEA 电子设备', '4', '实体', 'P4、P6、S4、S6 各 1 台'],
        ['舱外载荷', '6', '实体', 'ELC 4 个、AMS-02、JEM-EF'],
        ['舱内机柜', '88', '实体', 'Destiny 24、Harmony 8、Tranquility 16、Columbus 16、Kibo 24'],
        ['EATCS 散热器面板', '48', '壳', '6 个 ORU，每个 8 块面板'],
        ['PVR 面板', '28', '壳', '4 台 PVR，每台 7 块面板'],
        ['太阳翼毯面', '18', '壳', '美国太阳翼 16 块，服务舱太阳翼 2 块'],
    ], widths=[3.6, 1.6, 2.0, 8.6])
    D.figure(os.path.join(FIG, 'iss_nom0_geom_iso_legend.png'), '全站几何模型，按部件类别着色')
    D.figure(os.path.join(FIG, 'iss_nom0_geom_top_legend.png'), '全站几何模型天顶视图，图中上方为飞行方向')
    D.figure(os.path.join(FIG, 'iss_nom0_geom_core_legend.png'), '中央桁架、散热器翼与加压舱局部')
    D.h(2, '3.3 网格')
    m = C[cases[0]]['summ'].get('mesh', {})
    D.p('壳面用自由三角形单元，实体用自由四面体单元，最大单元尺寸按部件类别设定：美国太阳翼 3.0 m，服务舱太阳翼 2.0 m，桁架 2.2 m，舱体 1.4 m 至 1.6 m，'
        f'散热器与 PVR 面板 1.2 m 至 1.4 m，舱外载荷 1.2 m，舱外设备 0.6 m，机柜 0.7 m，其余部位 2.0 m。全模型共 {m.get("tri", 0)} 个三角形边界单元，'
        f'含壳单元与实体表面单元，另有 {m.get("tet", 0)} 个四面体单元。轨道温度研究步求解 82145 个自由度，含实体与壳的温度、四个辐射组的表面辐射度与 88 个回路未知量。')
    D.figure(os.path.join(FIG, 'iss_nom0_mesh_iso.png'), '全站表面网格')

    D.h(2, '3.4 表面光学性质与材料')
    O = S.OPTICS
    D.table('表面光学性质', ['类别', '太阳吸收率', '红外发射率', '依据'], [
        ['EATCS 散热器与 PVR，Z-93', f"{O['z93']['alpha']:.2f}", f"{O['z93']['eps']:.2f}",
         '平均环境工况取名义值；冷工况取寿命初期 0.15 与 0.91，热工况取污染与紫外老化后的名义值 0.24 与 0.90，文献 O2 的 30 年末期包络为 0.36 与 0.90'],
        ['美国段舱体防护屏', f"{O['skin_usos']['alpha']:.2f}", f"{O['skin_usos']['eps']:.2f}", '铬酸阳极化铝，只有外侧参与辐射'],
        ['俄罗斯段舱体外表面', f"{O['skin_rus']['alpha']:.2f}", f"{O['skin_rus']['eps']:.2f}", '检索中没有找到公开值，取国际空间站专用批次镀铝 beta 布的寿命初期值'],
        ['桁架', f"{O['truss']['alpha']:.2f}", f"{O['truss']['eps']:.2f}", '硫酸阳极化'],
        ['舱外设备与 IEA', f"{O['box']['alpha']:.3f}", f"{O['box']['eps']:.2f}", '多层隔热包覆，有效发射率 0.03 为模型取定值，公开资料只有文献 O25 的工程估计 0.05'],
        ['舱外载荷', f"{O['payload']['alpha']:.2f}", f"{O['payload']['eps']:.2f}", '国际空间站专用批次镀铝 beta 布，文献 V1'],
        ['太阳翼电池面', f"{O['saw_cells']['alpha']:.3f}", f"{O['saw_cells']['eps']:.2f}", '典型硅电池吸收率 0.72 扣除发电份额 0.073；文献 D18 的电池面值为 0.65 与 0.86'],
        ['太阳翼背面', f"{O['saw_back']['alpha']:.2f}", f"{O['saw_back']['eps']:.2f}", '文献 D18 图 27'],
    ], widths=[4.0, 2.0, 2.0, 7.8])
    M = S.MATERIALS
    rows = []
    for key, name in (('al_skin_usos', '美国段防护屏'), ('al_skin_rus', '俄罗斯段防护屏'), ('hrs_pan', 'EATCS 散热器面板'), ('pvr_pan', 'PVR 面板'),
                      ('saw_blk', '太阳翼毯面'), ('truss_eq', '桁架包络'), ('oru_eq', '舱外设备与 IEA'), ('pl_eq', '舱外载荷'), ('rack_eq', '舱内机柜')):
        mm = M[key]
        rows.append([name, ('%.1f mm' % (mm['t'] * 1e3)) if mm['kind'] == 'shell' else '实体', f"{mm['k']:g}", f"{mm['rho']:g}", f"{mm['cp']:g}"])
    D.table('材料与等效热物性，导热系数单位 W·m⁻¹·K⁻¹，密度 kg/m³，比热 J·kg⁻¹·K⁻¹', ['类别', '厚度', '导热系数', '密度', '比热'], rows, widths=[4.6, 2.2, 2.6, 2.6, 2.6])
    D.p('壳单元的厚度、密度与比热按面热容等效，导热系数按面内热导等效。散热器面板面密度取 8 kg/m²，按 ORU 外廓面积计的面密度为 14.2 kg/m²，其中包含展开机构。'
        '太阳翼毯面的面热容取 1.6 kJ·m⁻²·K⁻¹，按文献 O14 记录的出影后约 3 min 由 −80 °C 升到 0 °C 的升温过程估算，属于校准取值，计算的出影升温过程在第 5.5 节与该特征对比。'
        '桁架包络的等效密度由桁架段总质量扣除太阳翼、PVR、散热器与 IEA 后除以模型包络体积得到。')

    D.h(2, '3.5 传热与辐射')
    D.p('实体部件用固体传热接口求解温度 T，壳部件用壳传热接口求解温度 T_{2}。舱内机柜位于封闭舱体内，只与冷板和舱内空气换热，不参与辐射计算；'
        '其余实体部件与全部壳部件的外表面参与轨道热载荷计算。轨道热载荷接口按太阳与红外两个波段计算直接日照、地球反照与地球红外，'
        '用半立方体法计算部件之间的相互辐射与遮挡，半立方体分辨率取 128，视角系数更新容差取 0.02，地球按 2 圈、每圈 6 个点离散，'
        '反照率与地球红外在全球取均匀值，深空温度取 2.7 K。')
    D.p('本项目冒烟测试中用旋转域驱动面板转动，轨道位置由自定义函数给出，求解时轨道热载荷接口无法计算轨道速度变量，全站模型因此没有采用动网格。'
        '模型把全部部件按指向方式分为四个辐射组，每组一个轨道热载荷接口，各自设定指向规律，组内相互辐射与遮挡完整计算，组间不计。')
    D.p('指向规律中的术语定义如下。太阳 β 角为太阳方向与轨道面的夹角。轨道角自轨道正午点沿飞行方向起算，β 为 0 时地影中点位于轨道角 180°。'
        '侧边对日指太阳方向落在面板平面内，正面对地指面板法向指向天底，两者沿用文献 A 第 16 页的规定。参考姿态为建模时的几何姿态：'
        '散热器处于 TRRJ 零位，美国太阳翼毯面水平、电池面朝天顶。')
    D.table('辐射分组与指向规律', ['辐射组', '成员', '指向规律'], [
        ['机体组', '舱体、桁架与舱外方块', '+Z 指向天底，+X 指向速度方向'],
        ['散热器组', '6 个 EATCS 散热器 ORU', 'β 为 0 的工况在受晒段保持 TRRJ 零位，面板法向垂直于轨道面，任一轨道角都侧边对日；β 不为 0 的工况绕 X 轴转动，使太阳方向落在面板平面内；地影段面板法向转向天底'],
        ['SARJ 组', '4 台 PVR，服务舱太阳翼', '绕 Y 轴随太阳转动，PVR 侧边对日，服务舱太阳翼电池面对日；服务舱太阳翼由自身驱动机构转动，指向规律与 SARJ 相同，并入本组'],
        ['太阳翼组', '8 个美国太阳翼', '电池面法向始终指向太阳，长轴垂直于 Y 轴，对应 SARJ 与 BGA 的组合转动'],
    ], widths=[2.6, 4.2, 9.0])
    D.p('每个辐射组按一个刚体转动。散热器组的两个散热器翼零位时沿 Y 轴相距 29.4 m 相向布置，地影段与设计热工况中面板接近正面对地，'
        '模型中两翼沿天底方向上下相叠，上方翼朝地一侧的视场有一部分被下方翼占据；实际两翼各绕自身 TRRJ 转轴转动，正面对地时左右并排，相互没有遮挡。'
        '美国太阳翼组同样整体转动，高 β 时相邻太阳翼之间的遮挡没有计入。')

    D.h(2, '3.6 方块热源')
    D.p('发热部件简化为方块热源，热量按体积热源均匀施加。机柜、MBSU、DDCU 与 IEA 方块取一个面为冷板面，按对流边界与冷却液温度换热，'
        '其余表面按部件所处环境设置边界条件；舱外载荷方块不接冷板，外表面向空间辐射。')
    D.table('方块热源与冷却方式', ['类别', '热源', '冷却方式'], [
        ['舱内机柜', '机柜沿每舱四面舱壁布置，Destiny 24 × 500 W，Harmony 8 × 300 W，Tranquility 16 × 400 W，Columbus 16 × 600 W，Kibo 24 × 600 W，合计 44.8 kW',
         '机柜背面为冷板。三面舱壁的机柜接 17 °C 中温水回路，一面舱壁的机柜接 4 °C 低温水回路，水温取自文献 A 第 2 页，冷板换热系数 40 W·m⁻²·K⁻¹；'
         '机柜其余表面与 22 °C 舱内空气换热，换热系数 2 W·m⁻²·K⁻¹'],
        ['MBSU 与 DDCU', 'MBSU 4 × 495 W，DDCU 6 × 694 W，取冷板设计热负荷', '底面冷板接 2.8 °C 氨供液，冷板换热系数 60 W·m⁻²·K⁻¹；外表面按多层隔热有效发射率辐射'],
        ['IEA 电子设备', '4 × 6 kW，取 PVTCS 轨道平均散热能力', '冷板接各自 PVTCS 回路的 2.8 °C 供液；外表面按多层隔热有效发射率辐射'],
        ['舱外载荷', 'ELC 4 × 1 kW，AMS-02 2.5 kW，JEM-EF 3 kW', '不接冷板，外表面向空间辐射'],
        ['乘员代谢热', '6 × 136.8 W，文献 D19', '计入低温水回路，两个 EATCS 回路各 410 W'],
    ], widths=[2.8, 6.6, 6.4])
    D.p('全站方块热源与乘员热量合计 85.2 kW，其中机柜 44.8 kW，MBSU 与 DDCU 6.1 kW，IEA 24.0 kW，舱外载荷 9.5 kW，乘员 0.8 kW，'
        '与文献 D5 表 4.4-1 装配完成状态的平均可用功率 85.8 kW 在同一量级。')
    D.p('全部 20 个舱体圆柱的内侧都通过多层隔热与 22 °C 舱内空气换热，等效换热系数 0.08 W·m⁻²·K⁻¹，由文献 D15 中 Tranquility 节点舱舱壁环境热负荷 −720 W 推算。'
        'Destiny、Harmony、Tranquility、Columbus 与 Kibo 五个舱的机柜空气换热与舱体漏热计入各自的低温水回路；其余舱段的漏热由 22 °C 舱内空气边界吸收，'
        '不进入回路，俄罗斯段舱内没有热源与回路。')

    D.h(2, '3.7 冷却回路模型')
    D.p('EATCS 两个回路与四个 PVTCS 回路用全局方程描述。舱内主动热控系统 IATCS 设中温与低温两个水回路，机柜冷板的热量先进入水回路，再经界面换热器传给 EATCS 的氨回路。'
        '模型不建界面换热器与水回路，冷板一侧的冷却液温度取固定值：机柜冷板取 17 °C 与 4 °C 水温，MBSU、DDCU 与 IEA 冷板取 2.8 °C 氨供液设定点。'
        '回路收集的热量 Q_{c} 等于各冷板面与舱内空气换热面的热流积分之和，经 20 s 滞后进入回路。散热器入口温度按供液设定点加上收集热量引起的温升计算：')
    D.formula('ṁ c_{p} T_{ret} = ṁ c_{p} T_{set} + Q_{c}')
    D.p('式中 ṁ 为回路质量流量，c_{p} 为液氨比热，T_{ret} 为散热器入口温度，T_{set} 为供液设定点。每个 EATCS 回路的流量按三个散热器 ORU 均分，'
        '每个 ORU 的 8 块面板串联，每块面板对应一个氨温度节点。面板与氨之间的换热热流密度等于换热系数 g 乘以氨平均温度与面板温度之差，g 取 120 W·m⁻²·K⁻¹；'
        '面板两面线性化辐射换热系数在 −30 °C 至 7 °C 之间为 6 至 9 W·m⁻²·K⁻¹，g 为其 13 至 20 倍，氨与面板之间的温差远小于面板向空间辐射的等效温差。'
        '第 i 块面板对应氨节点的能量方程为：')
    D.formula('3 C_{f} dT_{i}/dt = f ṁ c_{p} ΔT_{i} − 3 ∫ g ΔT_{w} dA')
    D.p('式中 C_{f} 为氨节点热容，取 1 kJ/K；T_{i} 为第 i 个氨节点温度；f 为散热器分流比，即流经散热器的氨流量占回路总流量的比例；'
        '系数 3 对应同一回路的三个 ORU 均分流量；ΔT_{i} 为面板进出口氨温度差；ΔT_{w} 为氨平均温度与面板局部温度之差，积分遍及该面板。')
    D.p('散热器出口氨与旁路氨在泵模块的流量控制阀中混合后回到供液端，文献 A 第 10 页与第 11 页。模型按积分规律调节分流比，分流比的变化率等于混合供液温度与设定点之差'
        '除以积分时间系数 k_{c}，k_{c} 取 3000 K·s；按散热器进出口温差 25 K 估算，闭环时间常数约 2 min，温差增大时相应缩短。分流比设 0.02 的平滑下限，积分器带抗饱和处理，'
        '报告中的分流比取平滑限幅后的值。控制器要求的分流比超过 1 时，表示散热器全流量也不能把供液温度降到设定点，即散热能力不足。'
        '混合供液温度只用于分流比控制，不反馈到冷板，回路温度波动不改变设备温度。')
    D.table('回路参数', ['参数', '取值', '依据'], [
        ['回路 A 流量', '8200 lb/h，即 1.033 kg/s', '文献 A 第 10 页'], ['回路 B 流量', '8900 lb/h，即 1.121 kg/s', '文献 A 第 10 页'],
        ['供液设定点', '2.8 °C', '文献 A 第 6 页、第 11 页'],
        ['液氨比热', '4610 J·kg⁻¹·K⁻¹', 'NIST 在 2.8 °C、300 psia 下为 4612.6 J·kg⁻¹·K⁻¹，取三位有效数字'],
        ['回路热量分配', 'Destiny 与 Kibo 的中温水回路热量进回路 B，Harmony、Tranquility 与 Columbus 的中温水回路热量进回路 A，低温水回路相反', '文献 A 第 5 页回路图'],
        ['PVTCS 流量与设定点', '0.5 kg/s，2.8 °C', '公开资料未给出，取定值'],
    ], widths=[3.4, 7.2, 5.2])

    D.h(2, '3.8 求解设置')
    D.p('每个工况先由轨道热载荷研究步计算全时段外热流，再由轨道温度研究步求解温度与回路。外热流与温度都按 120 s 间隔计算，计算由当地正午起算，'
        f'到 {t_end:.0f} s 结束，统计取最后 {per0:.1f} s。时间推进采用 BDF 法，步长手动取 120 s，求解日志显示起步与事件重启后的步为一阶，其余各步为二阶；'
        '进入与离开地影时求解器在事件时刻截断步长，之后继续以 120 s 推进，结果按 120 s 间隔插值输出。分离式求解器分六组：实体温度一组，'
        '壳温度与全部回路未知量一组，四个辐射组的表面辐射度各一组，每步最多 25 次分离迭代。')
    D.p('各类部件的初始温度按类别取一个估计值。中温水回路机柜取 500 W 机柜冷板面的平衡温度 297.5 K，低温水回路机柜取 284 K，舱外设备与 IEA 取 285 K，'
        '舱外载荷取 255 K，桁架取 253 K，舱体取 268 K，散热器与 PVR 取 262 K，太阳翼取 290 K。')
    D.p('建模中处理了五个数值问题。其一，COMSOL 曲面类型的圆柱没有端盖，舱体改为实体圆柱转换的封闭曲面，并令舱体只在外法向一侧辐射，消除舱内全反射空腔造成的矩阵奇异。'
        '其二，回路方程由代数方程改为常微分方程，避免求一致初值时出现非物理温度。其三，温度与回路未知量采用手动缩放，使各未知量量级接近。'
        '其四，收集热量设为独立未知量，避免氨节点方程直接依赖全部机柜的温度自由度。其五，自适应步长在外热流分段更新处反复失败，改为手动步长。')

    D.h(2, '3.9 模型取定值与主要简化')
    D.items([
        ('1．', '部件按指向方式分为四个辐射组，组间不计相互辐射与遮挡；每组按一个刚体转动，散热器两翼与美国太阳翼之间的相对位置按第 3.5 节处理。'),
        ('2．', '部件之间全部不计导热。桁架段之间、设备与桁架之间、舱段之间、舱段与桁架之间以及散热器、PVR、太阳翼与桁架之间只通过同组辐射换热，冷板设备只与固定温度的冷板换热。'),
        ('3．', '桁架以不透明实体包络表示，不计辐射穿过桁架杆件间隙的透射，计算得到的桁架温度为包络外表面温度，不代表单根杆件的温度。'),
        ('4．', 'P4 至 P6、S4 至 S6 桁架段与 IEA 实际随 SARJ 转动，模型放在机体组，按对地定向计算外热流。'),
        ('5．', '舱内空气温度取 22 °C 固定值；冷板一侧的冷却液温度取固定值，界面换热器与舱内水回路不建模，散热器入口温度按设定点计算。'),
        ('6．', '散热器面板内的换热按面板均布，不区分流管位置，相当于流管之间面板的翅片效率取 1。'),
        ('7．', '散热器指向采用理想的侧边对日与正面对地规律，没有模拟散热器目标转角计算 RGAC 对出口温度的约束，文献 A 第 16 页。'),
        ('8．', '模型取定值包括冷板换热系数 40 与 60 W·m⁻²·K⁻¹、氨与面板换热系数 120 W·m⁻²·K⁻¹、机柜对舱内空气换热系数 2 W·m⁻²·K⁻¹、多层隔热有效发射率 0.03、'
                '各方块等效导热系数与密度、IEA 与冷板设备的尺寸和位置、机柜尺寸与每舱一面接低温水回路、JEM-EF 按无冷板处理、乘员热量两回路均分，'
                '以及回路数值参数 20 s、1 kJ/K、3000 K·s 与 0.02。完整清单见 model/iss_spec.py 中标为 D 的条目。'),
        ('9．', 'IEA 取 PVTCS 轨道平均散热能力 6 kW，MBSU 与 DDCU 取冷板设计热负荷，均为设计上限值；舱内机柜功率按舱段平均分配，舱外载荷功率取量级值；'
                '俄罗斯段外表面涂层、PVTCS 流量与设定点在检索中没有找到公开值，采用典型值。实际 JEM-EF 有主动冷却，模型按无冷板处理。'),
        ('10．', '美国段各舱统一采用 Destiny 圆柱段 2.0 mm 铬酸阳极化铝防护屏，Unity 实际为 1.3 mm，Columbus 与 Kibo 的防护构成不同，BEAM 为柔性外壳；'
                 '俄罗斯段 AMG-6 防护屏的导热系数、密度与比热为模型取定值。'),
        ('11．', '附着舱段按母舱外壳半径加 5 cm 就位，Tranquility、Cupola、Columbus、Kibo、BEAM、Poisk、Pirs 与 Rassvet 等舱段中心与 IGOAL 模型或 JSC 26557 接口坐标相差 0.2 m 至 1.1 m；'
                 'MBSU、DDCU 与 IEA 的位置为模型取定。'),
        ('12．', '核验建议中没有采用的条目：铬酸阳极化铝的实测值 0.32 与 0.49、多层隔热有效发射率 0.05、文献 D18 的太阳翼电池面光学性质、上条所列舱段位置修正。'),
        ('13．', '文献 B 第 8 页至第 11 页记载，P1-3 散热器第 2 流路于 2017 年 5 月隔离并排空，翻修件 2019 年 4 月才上行，2019 年构型中回路 B 实际只有五条散热器流路工作；'
                 '本模型六个散热器 ORU 的两条流路全部工作。'),
    ])

    # ------------------------------------------------------------------ 4
    D.h(1, '4 分析工况')
    rows = []
    for c in cases:
        cc = S.CASES[c]; z = S.OPTICS_BY_CASE.get(c, {}).get('z93', S.OPTICS['z93'])
        ecl = C[c]['summ']['orbit'].get('eclipse_deg', 0.0)
        rows.append([CASE_LABEL[c], f"{cc['beta_deg']:.0f}°", f"{cc['S_sun']:.0f}", f"{cc['albedo']:.2f}", f"{cc['olr']:.0f}",
                     f"{ecl / 360 * C[c]['per'] / 60:.1f} min" if ecl else '全程受晒', f"{z['alpha']:.2f} 与 {z['eps']:.2f}"])
    D.table('分析工况，太阳常数与地球红外单位 W/m²', ['工况', 'β', '太阳常数', '反照率', '地球红外', '地影时长', 'Z-93 吸收率与发射率'], rows,
            widths=[2.8, 1.4, 2.0, 1.6, 2.0, 2.4, 3.6])
    D.p('设计冷工况与设计热工况的太阳常数、反照率与地球红外取 SSP 41000 设计验证值，数值引自文献 D3 第 40 页。该环境规定冷工况高度 270 nmi、热工况高度 150 nmi，'
        '本模型三个工况统一取 400 km，冷工况受到的地球红外与反照偏多，热工况偏少，两个设计工况都比规范原意温和。热工况 Z-93 取污染与紫外老化后的名义值，'
        '低于 30 年末期包络。平均环境工况的太阳常数与地球红外取文献 D3 第 51 页舱外活动热数据库平均值，反照率在平均值 0.27 上按文献 D2 表 4.2.1-1 中 β 为 0° 的整轨平均修正加 0.04，'
        '取 0.31；两个设计工况的反照率未作修正，按文献 D2，β 为 75° 时该修正约为 0.19。三个工况的舱内外设备热负荷相同。')

    # ------------------------------------------------------------------ 5
    results_section(D, cases, C, LT, CT, PER, IT)
    D.h(1, '6 结论与建议')
    D.items(final_remarks(C, LT, CT, PER))
    D.h(1, '附录 文件与复现')
    D.table('主要文件', ['文件', '内容'], [
        ['model/iss_spec.py', '全部模型参数与来源'], ['model/iss_layout.py', '几何布局、辐射分组、回路方程'],
        ['model/iss_build.py', '在 COMSOL 中建立几何、网格、物理场与研究'], ['model/iss_run.py', '载入模型、设置时间步并求解'],
        ['model/iss_solve.py', '结果探针、部件统计与回路热量来源分解'], ['model/post_all.py', '探针、时程图、云图与报告的批处理'],
        ['model/iss_capacity.py', '散热器排热能力子模型'],
        ['model/iss_render.py 与 iss_plots.py', '几何图、云图、时程图与排热能力图'],
        ['out 下各工况目录中的 series.csv、items.csv 与 loop_breakdown.csv', '时程、部件统计与回路热量来源'],
        ['out/capacity', '排热能力子模型的出口温度时程与统计'],
        ['docs/ISS_SPEC.md 与各资料文档', '参数来源与核验记录'],
    ], widths=[6.4, 9.4])
    D.p('复现步骤以平均环境工况 nom0 为例：在装有 MPh 的 Python 虚拟环境中依次运行 iss_build.py --case nom0 --no-solve 与 iss_run.py nom0 --orbits 3 --dt 120，'
        '再运行 post_all.py nom0，完成探针取值并生成时程图与温度云图，post_all.py 同时列出三个工况时生成本报告。几何与网格图由 iss_render.py 以 --what geom 生成，'
        '色标由 iss_plots.py --legend 加注。散热器排热能力子模型由 iss_capacity.py hot75 --q 35,60,85,110,135 计算，另两个工况把 hot75 换为 nom0 与 cold0，'
        '排热能力图由 iss_plots.py --capacity 生成；离散误差检验运行 iss_capacity.py hot75 --q 35 --dt 60 --suffix _dt60 与 iss_capacity.py hot75 --q 35 --hmax 0.8 --suffix _h08。')
    return D


def ncase(C):
    return '三个工况' if len(C) == 3 else f'{len(C)} 个工况'


def hot_capacity():
    """hot75 capacity summary: (rows at 35 kW, {loop: Q at max outlet = set point})."""
    import iss_results_ext as X
    cap = X.capacity()
    if not cap or 'hot75' not in cap['rows']:
        return [], {}
    r35 = [r for r in cap['rows']['hot75'] if abs(r['Qd_kW'] - 35.0) < 1e-6]
    mx = {L: v['Q_at_max_setpoint_kW'] for L, v in cap['summary']['hot75']['capacity'].items() if v['Q_at_max_setpoint_kW'] is not None}
    return r35, mx


def conclusions(C, LT, CT, PER):
    import numpy as np
    import iss_results_ext as X
    out = []
    n = [1]

    def add(t):
        out.append((f'{n[0]}．', t)); n[0] += 1
    add('在 COMSOL 中建立了国际空间站全站有限元热模型，包含 19 个加压舱段共 20 个舱体圆柱、12 个桁架段、6 个 EATCS 散热器 ORU、4 台 PVR、18 块太阳翼毯面、'
        '108 个方块热源与 6 个不发热的 EATCS 设备方块。几何、材料、表面性质与热负荷的每个取值都注明了文献、公开资料或模型取定依据，布局与 SSP 30219 的关节定义一致。')
    lts = [LT[c] for c in C if LT[c]]
    if lts:
        qa = [lt['A']['Q']['mean'] / 1e3 for lt in lts]; qb = [lt['B']['Q']['mean'] / 1e3 for lt in lts]
        fm = [v['f']['mean'] for lt in lts for v in lt.values()]; fx = max(v['f']['max'] for lt in lts for v in lt.values())
        tm = [v['Tmix'] for lt in lts for v in lt.values()]; to = [v['Tout'] for lt in lts for v in lt.values()]
        add(f'{ncase(C)}第三圈，回路 A 收集热量平均 {X.rng(min(qa), max(qa))} kW，回路 B 为 {X.rng(min(qb), max(qb))} kW；'
            f'散热器分流比平均 {X.rng(min(fm), max(fm), 2)}，最大 {X.num(fx, 2)}；混合供液温度保持在 {X.rngu(min(x["min"] for x in tm), max(x["max"] for x in tm))}，'
            f'散热器出口氨温度在 {X.rngu(min(x["min"] for x in to), max(x["max"] for x in to))} 之间。')
    rk = {c: X.rack_stats(C[c]) for c in C}
    tmax = max((v['Tmax'] for c in C for v in rk[c].values()), default=float('nan'))
    rmean = [float(np.mean([v['Tmean'] for v in rk[c].values()])) for c in C if rk[c]]
    if rmean:
        add(f'舱内机柜、MBSU、DDCU 与 IEA 等接冷板的方块，温度约等于冷却液温度加上功率与冷板换热系数之比，由取定的冷板参数决定，'
            f'{ncase(C)}的机柜平均温度相差 {X.num(max(rmean) - min(rmean), 2)} K，机柜最高温度 {X.num(tmax)} °C。模型用这些方块把热量按设定路径送入回路，'
            '方块温度不用于判断机柜是否满足文献 D13 前面板 37 °C 的限值。')
    ps = {c: [r['Tmean'] for r in X.payload_stats(C[c]).values()] for c in C}
    if ps.get('cold0') and ps.get('hot75'):
        add(f"舱外载荷不接冷板，第三圈平均温度在设计冷工况为 {X.rngu(min(ps['cold0']), max(ps['cold0']))}，在设计热工况为 "
            f"{X.rngu(min(ps['hot75']), max(ps['hot75']))}，是受轨道环境影响最大的方块热源。")
    r35, mx = hot_capacity()
    if r35:
        t35 = max(r['Tout_max_C'] for r in r35)
        txt = f'散热器排热能力子模型令全部氨流经散热器。设计热工况下单回路排热 35 kW 时，出口温度一圈内的最高值为 {X.num(t35)} °C，'
        txt += ('低于 2.8 °C 设定点，模型散热器满足单回路 35 kW 的排热要求。' if t35 < X.T_SET_C else '高于 2.8 °C 设定点。')
        if 'A' in mx and 'B' in mx:
            txt += f"出口温度一圈最高值达到 2.8 °C 时，回路 A 与回路 B 分别可排出 {X.num(mx['A'], 0)} kW 与 {X.num(mx['B'], 0)} kW"
            txt += ('，高于公开资料的估算值，差别来自入口温度随排热量升高与模型的理想化处理，该值应看作排热能力的上限。' if min(mx.values()) > 44 else '。')
        add(txt)
    return out


def final_remarks(C, LT, CT, PER):
    import iss_results_ext as X
    out = []
    n = [1]

    def add(t):
        out.append((f'{n[0]}．', t)); n[0] += 1
    fmax = max((v['f']['max'] for c in C for v in LT[c].values()), default=0)
    r35, mx = hot_capacity()
    qmax = max((v['Q']['mean'] for c in C for v in LT[c].values()), default=0) / 1e3
    add(f'在本模型 44.8 kW 舱内机柜热负荷与 6.1 kW EATCS 舱外冷板负荷下，{ncase(C)}的散热器分流比最大 {X.num(fmax, 2)}，'
        + ('EATCS 散热器仍有较大余量。' if fmax < 0.5 else ('EATCS 散热器余量有限。' if fmax < 1.0 else 'EATCS 散热器排热能力不足。'))
        + (f'散热器排热能力子模型给出设计热工况下单回路排热能力的上限 {X.num(min(mx.values()), 0)} kW，全站模型中单回路收集热量最大 {X.num(qmax)} kW。' if mx else '')
        + '舱内机柜增加功率时，应按单回路 35 kW 的设计排热能力核算余量。')
    tmin = min((v['Tout']['min'] for c in C for v in LT[c].values()), default=None)
    if tmin is not None:
        add('文献 A 第 16 页说明，RGAC 在受晒段令散热器侧边对日，在地影段令散热器正面对地，同时使散热器足够冷以排热、足够暖以防止氨冻结，出口温度目标为 −40 °C。'
            f'本模型没有模拟这一约束，组间辐射不计与面板换热均布又使散热器偏冷，计算的出口温度最低 {X.num(tmin)} °C；文献 D16 图 4 中 P1 散热器 2007 至 2010 年的在轨读数约为 −54 °C 至 +27 °C，'
            + ('计算最低值在该范围之内。' if tmin >= -54.0 else '计算最低值低于该范围。')
            + '后续可用在轨出口温度数据修正散热器与桁架、太阳翼之间的遮挡以及面板翅片效率，并为每个散热器翼单设辐射组，消除两翼整体转动造成的相互遮挡。')
    add('舱外载荷不接冷板，温度取决于外表面光学性质与自身功率；IEA 与冷板设备的温度主要由冷板决定，多层隔热有效发射率影响进入 PVTCS 的热量。'
        '工程应用时应以载荷的实测光学性质与热控设计替换本报告的典型值。')
    add('本模型已具备按工况批量计算的脚本流程，可直接求解舱外载荷在不同安装位置与不同功率下的温度及 EATCS 余量，也可把载荷方块替换为在轨计算设备的详细模型。')
    add('主要不确定性来自组间辐射不计、桁架按实体包络处理、散热器面板换热均布、机柜与 IEA 尚未完全达到周期稳态以及部分参数取模型取定值。'
        '机柜与 IEA 的储热影响见第 5.1 节，离散误差见第 5.7 节；本报告没有做参数敏感性计算，其余各项对部件温度与回路收集热量的影响需由后续敏感性工况确定。')
    return out


def results_section(D, cases, C, LT, CT, PER, IT):
    import numpy as np
    import iss_results_ext as X
    D.h(1, '5 分析结果')
    D.p('以下统计取每个工况最后一个轨道周期，即第三圈。热量与温度的时程由探针逐步输出，部件统计由有限元温度场在部件区域内求最小值、平均值与最大值。'
        '温度云图按参考姿态绘制部件，太阳翼、PVR 与散热器在轨的实际指向随轨道变化，其外热流按各自的指向规律计算；各云图色标范围统一取 −80 °C 至 80 °C。')

    # ------------------------------------------------ 5.1 EATCS
    D.h(2, '5.1 EATCS 回路')
    rows = []
    for c in cases:
        for L, v in LT[c].items():
            rows.append([CASE_LABEL[c], L, kw(v['Q']['mean']), kw(v['Qrad']['mean']), X.num(v['closure_pct']),
                         X.num(v['f']['mean'], 2), X.rng(v['f']['min'], v['f']['max'], 2), X.num(v['Tret']['mean']),
                         X.rng(v['Tout']['min'], v['Tout']['max']), X.rng(v['Tmix']['min'], v['Tmix']['max'])])
    D.table('EATCS 回路第三圈统计，热量单位 kW，温度单位 °C', ['工况', '回路', '收集热量', '散热器排热', '控制偏差 %', '分流比平均', '分流比范围',
            '散热器入口平均', '散热器出口范围', '混合供液范围'], rows, widths=[2.4, 1.1, 1.5, 1.6, 1.4, 1.5, 1.9, 1.5, 2.0, 1.9])
    D.p('两个回路的混合供液温度都保持在 2.8 °C 设定点附近，分流比控制正常。表中控制偏差为散热器排热与收集热量之差占收集热量的百分比。'
        '模型按设定点计算散热器入口温度，散热器排热与收集热量之差等于 ṁ c_{p} 乘以 T_{set} 与 T_{mix} 之差，控制偏差因此反映混合供液温度偏离设定点的程度，'
        '一圈平均偏差小说明混合供液温度的轨道平均值回到了设定点。散热器面板与氨节点的储热变化体现在散热器排热与面板净辐射散热之差中。')
    BD = {c: X.breakdown(C[c]) for c in cases}
    if any(BD.values()):
        rows = []
        for key, lab in X.BREAKDOWN_CN + [('total', '合计')]:
            row = [lab]
            for c in cases:
                for L in ('A', 'B'):
                    b = (BD[c] or {}).get(L, {})
                    v = sum(b.values()) if key == 'total' else b.get(key)
                    row.append(X.num(v / 1e3, 2) if v is not None and b else '')
            rows.append(row)
        D.table('EATCS 回路收集热量的来源，第三圈平均，单位 kW', ['来源'] + [f'{CASE_LABEL[c]}回路 {L}' for c in cases for L in ('A', 'B')], rows,
                widths=[3.8] + [12.0 / (2 * len(cases))] * (2 * len(cases)))
        b0 = BD[cases[0]] or {}
        if b0.get('A') and b0.get('B'):
            qa, qb = sum(b0['A'].values()), sum(b0['B'].values())
            hi, lo = ('B', 'A') if qb >= qa else ('A', 'B')
            D.p(f"{CASE_LABEL[cases[0]]}中回路 {hi} 收集的热量高于回路 {lo}"
                + ("，主要差别在接中温水回路的机柜：Destiny 与 Kibo 两个大舱的中温水回路热量进回路 B，" if hi == 'B' else "。Destiny 与 Kibo 两个大舱的中温水回路热量进回路 B，")
                + f"回路 B 的中温机柜热量为 {X.num(b0['B'].get('rack_MT', 0) / 1e3, 1)} kW，回路 A 为 {X.num(b0['A'].get('rack_MT', 0) / 1e3, 1)} kW。"
                '多层隔热漏热为负值，表示舱内空气经多层隔热向防护屏散失热量，舱内空调需要排出的热量相应减少，模型把这部分热量从对应舱段低温水回路的收集热量中扣除。')
        rack_W = sum(nb * 4 * w for nb, w in S.RACK_MODULES.values()); iea_W = len(S.IEA['units']) * S.IEA['Q']
        coll, colli = [], []
        for c in cases:
            b = BD[c] or {}
            if not b: continue
            coll.append(sum(v for L in ('A', 'B') for k, v in b.get(L, {}).items() if k in ('rack_MT', 'rack_LT', 'air')))
            colli.append(sum(v for L, d in b.items() if L.startswith('PV') for k, v in d.items() if k == 'iea'))
        if coll:
            dr = [rack_W - x for x in coll]; di = [iea_W - x for x in colli]
            txt = (f'舱内机柜共发热 {X.num(rack_W / 1e3, 1)} kW，第三圈经冷板与舱内空气进入回路的热量为 {X.rng(min(coll) / 1e3, max(coll) / 1e3)} kW；'
                   f'四台 IEA 共发热 {X.num(iea_W / 1e3, 1)} kW，第三圈进入 PVTCS 的热量为 {X.rng(min(colli) / 1e3, max(colli) / 1e3)} kW。')
            if all(x > 0 for x in dr):
                txt += f'机柜只通过冷板与舱内空气散热，两者之差 {X.rng(min(dr) / 1e3, max(dr) / 1e3, 2)} kW 为机柜内部仍在升温储存的热量，'
            elif all(x < 0 for x in dr):
                txt += f'机柜只通过冷板与舱内空气散热，进入回路的热量比发热量多 {X.rng(-max(dr) / 1e3, -min(dr) / 1e3, 2)} kW，为机柜初始储热的释放，'
            else:
                txt += '机柜只通过冷板与舱内空气散热，两者之差为机柜内部储热的变化，'
            txt += ('IEA 的差值中还包含经多层隔热向外辐射的热量。机柜初始温度按 500 W 机柜冷板面的平衡温度统一设定，功率较低的机柜初始偏热，功率较高的机柜初始偏冷，'
                    'IEA 初始温度同样取冷板面平衡温度的估计值；方块内部导热形成的温度梯度需要数小时才能建立，三个轨道周期内机柜与 IEA 尚未完全达到周期稳态，'
                    '达到稳态后回路收集热量将趋近发热量。')
            D.p(txt)
    if any(BD.values()):
        hand = {}
        for L in ('A', 'B'):
            rk = sum(nb * w * (3 if S.MODULE_LOOPS[m]['MT'] == L else 0) + nb * w * (1 if S.MODULE_LOOPS[m]['LT'] == L else 0)
                     for m, (nb, w) in S.RACK_MODULES.items())
            oru = sum(q for (nm, size, ctr, q, loop, face) in S.ORU_BOXES if loop == L)
            hand[L] = dict(rack=rk, oru=oru, crew=float(S.LOOPS['other_loads'][L].split('[')[0]))
        rows = []
        for c in cases:
            b = BD[c] or {}
            for L in ('A', 'B'):
                d = b.get(L, {})
                if not d: continue
                fe_r = sum(v for k, v in d.items() if k in ('rack_MT', 'rack_LT', 'air')); fe_o = d.get('oru', 0.0)
                rows.append([CASE_LABEL[c], L, X.num(hand[L]['rack'] / 1e3, 2), X.num(fe_r / 1e3, 2), X.num(hand[L]['oru'] / 1e3, 2), X.num(fe_o / 1e3, 2),
                             X.num(d.get('mli', 0.0) / 1e3, 2)])
        if rows:
            D.table('回路收集热量的手算校核，单位 kW', ['工况', '回路', '机柜发热，手算', '机柜进入回路，有限元', '冷板设备发热，手算', '冷板设备进入回路，有限元', '舱体漏热，有限元'],
                    rows, widths=[2.6, 1.1, 2.3, 2.5, 2.3, 2.6, 2.4])
            D.p('手算值为各方块的设定功率，周期稳态时进入回路的热量应等于该值；有限元值与手算值之差即为方块内部储热的变化，乘员热量两者相同，未列出。')
    for c in cases:
        D.figure(os.path.join(FIG, f'{c}_loops.png'), f'{CASE_LABEL[c]} EATCS 回路时程，灰色区域为地影', 15.5)

    # ------------------------------------------------ 5.2 radiators
    D.h(2, '5.2 散热器与 PVR')
    rows = []
    for c in cases:
        hrs, pvr = X.oru_stats(C[c])
        for nm in sorted(hrs):
            r = hrs[nm]; rows.append([CASE_LABEL[c], nm.replace('HRS_', ''), X.num(r['Tmin']), X.num(r['Tmean']), X.num(r['Tmax'])])
    D.table('EATCS 散热器 ORU 第三圈面板温度，单位 °C', ['工况', 'ORU', '最低', '平均', '最高'], rows, widths=[3.6, 2.4, 3.2, 3.2, 3.2])
    D.p('每个 ORU 的 8 块面板沿流向串联，入口面板温度最高，出口面板最低。回路 A 的三个 ORU 位于右舷，回路 B 的三个 ORU 位于左舷。'
        '同一翼的三个 ORU 在各种姿态下都位于同一平面内，相互之间没有辐射交换与遮挡，对地视角相同，流量均分，温度差别来自对面散热器翼的视角系数随 ORU 位置的变化；'
        '两个回路之间的差别来自流量、收集热量以及两翼整体转动造成的相互遮挡。')
    rows = []
    for c in cases:
        for u, v in X.pv_loops(C[c]).items():
            rows.append([CASE_LABEL[c], u, kw(v['Q']['mean']), X.num(v['f']['mean'], 2), X.rng(v['Tout']['min'], v['Tout']['max']), X.rng(v['Tmix']['min'], v['Tmix']['max'])])
    if rows:
        D.table('PVTCS 回路第三圈统计，热量单位 kW，温度单位 °C', ['工况', '光伏模块', '收集热量', '分流比平均', 'PVR 出口范围', '混合供液范围'], rows,
                widths=[3.2, 2.2, 2.4, 2.4, 2.8, 2.8])
    for c in cases:
        D.figure(os.path.join(FIG, f'{c}_orus.png'), f'{CASE_LABEL[c]}下六个 EATCS 散热器 ORU 面板平均温度时程', 15.5)
    for c in cases:
        path = os.path.join(FIG, f'{c}_T_hrs_noon_cb.png')
        if os.path.exists(path):
            D.figure(path, f'{CASE_LABEL[c]}第三圈正午右舷 EATCS 散热器翼的表面温度，自右舷方向观察', 15.5)

    # ------------------------------------------------ 5.3 classes
    D.h(2, '5.3 各类部件温度')
    rows = []
    names = {'hrs': 'EATCS 散热器面板', 'pvr': 'PVR 面板', 'saw': '美国太阳翼', 'rsa': '服务舱太阳翼', 'skin_usos': '美国段舱体防护屏',
             'skin_rus': '俄罗斯段舱体外表面', 'truss': '桁架包络', 'box': '舱外设备与 IEA', 'payload': '舱外载荷', 'rack': '舱内机柜'}
    for k, nm in names.items():
        row = [nm]
        for c in cases:
            v = CT[c].get(k)
            row.append(f"{X.num(v['min'])} / {X.num(v['mean'])} / {X.num(v['max'])}" if v else '')
        rows.append(row)
    D.table('各类部件第三圈温度，最低 / 平均 / 最高，单位 °C', ['部件类别'] + [CASE_LABEL[c] for c in cases], rows,
            widths=[4.0] + [11.8 / len(cases)] * len(cases))
    saw = [CT[c]['saw'] for c in cases if 'saw' in CT[c]]
    parts = []
    if saw:
        parts.append(f"美国太阳翼温度随日照变化最剧烈，第三圈在 {X.rngu(min(v['min'] for v in saw), max(v['max'] for v in saw))} 之间")
    for k, nm in (('skin_usos', '美国段舱体防护屏'), ('skin_rus', '俄罗斯段舱体外表面'), ('truss', '桁架包络')):
        if all(k in CT[c] for c in cases) and len(cases) > 1:
            parts.append(f"{nm}平均温度在{'、'.join(CASE_LABEL[c] for c in cases)}分别为 {'、'.join(X.num(CT[c][k]['mean']) for c in cases)} °C")
    if parts:
        txt = '；'.join(parts) + '。'
        if 'hot75' in cases and 'cold0' in cases and all(CT['hot75'][k]['mean'] > CT['cold0'][k]['mean'] for k in ('skin_usos', 'skin_rus', 'truss') if k in CT['hot75'] and k in CT['cold0']):
            txt += '设计热工况 β 为 75°，全程受晒，环境热流也取上限，舱体与桁架的平均温度都高于设计冷工况。'
        D.p(txt)
    for c in cases:
        D.figure(os.path.join(FIG, f'{c}_classes.png'), f'{CASE_LABEL[c]}各类部件温度时程', 15.5)
    for c in cases:
        for tag, lab in (('noon', '第三圈正午'), ('ecl', '第三圈地影中点'), ('q90', '第三圈轨道角 90°')):
            path = os.path.join(FIG, f'{c}_T_iso_{tag}_cb.png')
            if os.path.exists(path):
                D.figure(path, f'{CASE_LABEL[c]}{lab}的表面温度', 15.5)

    # ------------------------------------------------ 5.4 block heat sources
    D.h(2, '5.4 方块热源')
    rows = []
    for c in cases:
        for m, v in X.rack_stats(C[c]).items():
            rows.append([CASE_LABEL[c], X.MOD_CN[m], str(v['n']), X.num(v['Tmin']), X.num(v['Tmean']), X.num(v['Tmax'])])
    D.table('舱内机柜第三圈温度，单位 °C', ['工况', '舱段', '机柜数', '最低', '平均', '最高'], rows, widths=[3.4, 2.6, 1.8, 2.6, 2.6, 2.6])
    rows = []
    for c in cases:
        for g, v in X.box_stats(C[c]).items():
            rows.append([CASE_LABEL[c], g, str(v['n']), X.num(v['Tmin']), X.num(v['Tmean']), X.num(v['Tmax'])])
        for nm, r in X.payload_stats(C[c]).items():
            rows.append([CASE_LABEL[c], nm, '1', X.num(r['Tmin']), X.num(r['Tmean']), X.num(r['Tmax'])])
    D.table('舱外方块第三圈温度，ATA、PM、NTA 不发热，单位 °C', ['工况', '部件', '数量', '最低', '平均', '最高'], rows, widths=[3.4, 2.6, 1.8, 2.6, 2.6, 2.6])
    rk_mean, lt_gap = {}, []
    for c in cases:
        it = IT[c].get('rack', [])
        lt = [r['Tmean'] for r in it if r['name'].endswith(f'_{S.RACK_LT_WALL}')]
        mt = [r['Tmean'] for r in it if not r['name'].endswith(f'_{S.RACK_LT_WALL}')]
        if lt and mt:
            rk_mean[c] = float(np.mean([r['Tmean'] for r in it])); lt_gap.append(float(np.mean(mt) - np.mean(lt)))
    bs = {c: X.box_stats(C[c]) for c in cases}
    cp = [bs[c][g]['Tmean'] for c in cases for g in ('MBSU', 'DDCU') if g in bs[c]]
    iea = [bs[c]['IEA']['Tmean'] for c in cases if 'IEA' in bs[c]]
    ps = {c: [r['Tmean'] for r in X.payload_stats(C[c]).values()] for c in cases}
    txt = ''
    if rk_mean and lt_gap:
        txt += (f'舱内机柜温度由冷板水温、机柜功率与冷板换热系数决定，{ncase(C)}的机柜平均温度相差 {X.num(max(rk_mean.values()) - min(rk_mean.values()), 2)} K；'
                f'接低温水回路的机柜比接中温水回路的机柜平均低 {X.num(float(np.mean(lt_gap)))} K，'
                + ('与两个水回路 13 K 的温差一致。' if abs(float(np.mean(lt_gap)) - 13.0) < 0.5 else
                   ('小于两个水回路 13 K 的温差，原因是机柜其余表面与 22 °C 舱内空气换热，接低温水回路的机柜受舱内空气加热更多。' if float(np.mean(lt_gap)) < 13.0
                    else '大于两个水回路 13 K 的温差。')))
    if cp and iea:
        txt += (f'接氨冷板的 MBSU 与 DDCU 第三圈平均温度为 {X.rngu(min(cp), max(cp))}，IEA 为 {X.rngu(min(iea), max(iea))}，'
                '比 2.8 °C 冷板温度高出冷板温升，外表面包覆多层隔热，温度主要由冷板决定。')
    if ps.get('cold0') and ps.get('hot75'):
        txt += (f"无冷板的舱外载荷只能向空间辐射散热，第三圈平均温度在设计冷工况为 {X.rngu(min(ps['cold0']), max(ps['cold0']))}，"
                f"在设计热工况为 {X.rngu(min(ps['hot75']), max(ps['hot75']))}，受环境影响最大。")
    if txt:
        D.p(txt)

    # ------------------------------------------------ 5.5 checks
    D.h(2, '5.5 与规格和在轨数据对比')
    rows = []
    for c in cases:
        lt = LT[c]
        if not lt: continue
        tmix = [v['Tmix'] for v in lt.values()]; tout = [v['Tout'] for v in lt.values()]
        rows.append([CASE_LABEL[c], '氨供液温度', '设定 2.8 °C，控制带 ±1.1 °C，文献 A 第 11 页', X.rngu(min(x['min'] for x in tmix), max(x['max'] for x in tmix))])
        rows.append([CASE_LABEL[c], '散热器出口温度', '目标 −40 °C，文献 A 第 16 页；P1 散热器 2007 至 2010 年在轨读数约 −54 °C 至 +27 °C，文献 D16 图 4；'
                     '散热器流路两年内温度极值 −40 °C 至 13 °C，文献 D17', X.rngu(min(x['min'] for x in tout), max(x['max'] for x in tout))])
        se = X.saw_eclipse(C[c])
        if se:
            rows.append([CASE_LABEL[c], '太阳翼出影温度，标定项', '出影时约 −80 °C，约 3 min 升至 0 °C，文献 O14，毯面面热容按此取定',
                         f"{X.num(se['T_exit'])} °C，" + (f"约 {se['warm_min']:.0f} min 升至 0 °C，时间分辨率 2 min" if se['warm_min'] is not None else '')])
        saw = CT[c].get('saw')
        if saw:
            rows.append([CASE_LABEL[c], '太阳翼温度范围', '文献 O17 推算的飞行极值约 +60 °C 与 −80 °C', X.rngu(saw['min'], saw['max'])])
            if S.CASES[c]['beta_deg'] == 0:
                rows.append([CASE_LABEL[c], '太阳翼光照段最高温度', '文献 D18 图 27，寿命初期 β 为 0° 时约 +53 °C', X.num(saw['max']) + ' °C'])
        rows.append([CASE_LABEL[c], '散热器分流比', '单回路设计排热能力 35 kW，分流比达到 1 为能力上限，文献 A 第 5 页', f"最大 {X.num(max(v['f']['max'] for v in lt.values()), 2)}"])
    D.table('计算结果与规格、在轨数据对比', ['工况', '项目', '规格或在轨数据', '计算结果'], rows, widths=[2.8, 2.6, 6.0, 4.4])
    D.p('太阳翼出影温度一行是标定项，毯面面热容按该在轨特征取定，只说明标定已经实现；其余各行为独立对比。')
    rows = []
    for c in cases:
        lt = LT[c]
        if not lt: continue
        tmix_min = min(v['Tmix']['min'] for v in lt.values()); tmix_max = max(v['Tmix']['max'] for v in lt.values())
        tpan = CT[c].get('hrs', {}).get('min'); tout_min = min(v['Tout']['min'] for v in lt.values())
        pv = X.pv_loops(C[c]); pv_min = min((v['Tout']['min'] for v in pv.values()), default=None)
        if tpan is not None:
            rows.append([CASE_LABEL[c], '氨冻结', '冰点 −77 °C，文献 A 第 5 页', f'散热器面板最低 {X.num(tpan)} °C，出口最低 {X.num(tout_min)} °C',
                         X.num(min(tpan, tout_min) + 77.0) + ' K'])
        if pv_min is not None:
            rows.append([CASE_LABEL[c], 'PVR 氨冻结', '冰点 −77 °C，文献 A 第 5 页', f'PVR 出口最低 {X.num(pv_min)} °C', X.num(pv_min + 77.0) + ' K'])
        rows.append([CASE_LABEL[c], '界面换热器防冻', '供液低于 1.67 °C 时保护动作，文献 A 第 11 页', f'混合供液最低 {X.num(tmix_min)} °C', X.num(tmix_min - 1.67, 2) + ' K'])
        rows.append([CASE_LABEL[c], '泵控阀温控能力', '2.2 °C 至 6.1 °C，文献 A 第 11 页', f'混合供液 {X.rngu(tmix_min, tmix_max)}',
                     '在范围内' if tmix_min >= 2.2 and tmix_max <= 6.1 else '超出范围'])
    if rows:
        D.table('EATCS 与 PVTCS 温度限值核对', ['工况', '限值项目', '限值', '计算结果', '余量'], rows, widths=[2.6, 2.6, 4.2, 4.4, 2.0])
        D.p('冷板一侧的冷却液温度在模型中取固定值，混合供液温度偏低时界面换热器的保护动作与舱内回路的响应不在模型范围内，上表只核对氨温度本身。')

    capacity_section(D, cases, LT)

    # ------------------------------------------------ 5.7 numerics
    D.h(2, '5.7 周期性与离散误差')
    rows = []
    for c in cases:
        per = PER[c]
        for k, nm in (('hrs', 'EATCS 散热器'), ('pvr', 'PVR'), ('saw', '美国太阳翼'), ('skin_usos', '美国段舱体'), ('skin_rus', '俄罗斯段舱体'),
                      ('truss', '桁架'), ('rack', '舱内机柜'), ('box', '舱外设备与 IEA'), ('payload', '舱外载荷')):
            if k in per:
                rows.append([CASE_LABEL[c], nm, X.num(per[k], 2)])
        for L in ('A', 'B'):
            if f'Q_{L}_kW' in per:
                rows.append([CASE_LABEL[c], f'回路 {L} 收集热量，kW', X.num(per[f'Q_{L}_kW'], 2)])
    if rows:
        D.table('最后一圈与前一圈平均值之差，温度单位 K', ['工况', '项目', '差值'], rows, widths=[4.0, 6.8, 5.0])
    D.p('按面热容与线性化辐射换热系数估算，太阳翼的时间常数为数分钟，俄罗斯段舱体约 10 min，EATCS 散热器约 13 min 至 20 min，美国段舱体防护屏约 35 min 至 50 min，'
        '这些部件在第三圈已接近周期稳态。机柜与 IEA 的时间常数约 2 h，初始温度取冷板面平衡温度的估计值；桁架包络等效导热系数只有 1 W·m⁻¹·K⁻¹，'
        '内部扩散时间常数为 8 h 至 2 天，初始温度取整轨平均估计值 253 K。第三圈的残余漂移列于上表。')
    cap = X.capacity()
    if cap:
        base = {r['loop']: r for r in cap['rows'].get('hot75', []) if abs(r['Qd_kW'] - 35.0) < 1e-6}
        parts = []
        for k, lab in (('hot75_dt60', '时间步长由 120 s 减为 60 s'), ('hot75_h08', '散热器网格尺寸由 1.2 m 减为 0.8 m'),
                       ('nom0_dt60', '平均环境工况时间步长由 120 s 减为 60 s')):
            bb = base if not k.startswith('nom0') else {r['loop']: r for r in cap['rows'].get('nom0', []) if abs(r['Qd_kW'] - 35.0) < 1e-6}
            rr = {r['loop']: r for r in cap['rows'].get(k, []) if abs(r['Qd_kW'] - 35.0) < 1e-6}
            Ls = [L for L in rr if L in bb]
            if Ls:
                dm = max(abs(rr[L]['Tout_mean_C'] - bb[L]['Tout_mean_C']) for L in Ls)
                dx = max(abs(rr[L]['Tout_max_C'] - bb[L]['Tout_max_C']) for L in Ls)
                parts.append(f'{lab} 后，出口温度一圈平均值最多变化 {X.num(dm, 2)} K，一圈最高值最多变化 {X.num(dx, 2)} K')
        if parts:
            txt = '离散误差用散热器排热能力子模型检验，以单回路 35 kW 为基准：' + '；'.join(parts) + '。'
            if 'nom0_dt60' not in cap['rows']:
                txt += ('该检验只针对设计热工况，该工况全程受晒，没有进出地影与散热器姿态切换造成的热流突变，β 为 0 工况与全站模型的步长影响未经检验。')
            txt += '太阳翼的时间常数只有数分钟，120 s 步长只能把出影升温的时刻分辨到一个时间步，即 2 min。'
            D.p(txt)


def capacity_section(D, cases, LT):
    import iss_results_ext as X
    cap = X.capacity()
    D.h(2, '5.6 散热器排热能力')
    txt = ('全站模型中回路收集的热量低于单回路 35 kW 的设计排热能力，流量控制阀让大部分氨绕过散热器，分流比只说明当前负荷所需的散热器流量。'
           '为求散热器的排热能力，另建只含 48 块 EATCS 散热器面板的子模型。全站模型中散热器辐射组只与本组面板交换辐射，因此子模型沿用相同的面板几何、材料、涂层、'
           'TRRJ 指向规律与轨道环境后，面板所受外热流与全站模型一致。子模型令回路全部流量流经散热器，给定单回路排热量，散热器入口温度等于出口温度加上排热量引起的温升，'
           '散热器出口温度即为供液温度。')
    hist = X.capacity_history('hot75', 35)
    if hist:
        txt += (f"每个排热量由当地正午起计算 {hist['t_end']:.0f} s，统计取最后一个轨道周期；温度研究步沿用第一次计算存储的外热流。"
                f"设计热工况 35 kW 时，计算末时刻与前一轨道周期同一轨道位置的出口温度最多相差 {X.num(hist['drift'], 2)} K。")
    D.p(txt)
    if not cap or not cap['rows']:
        D.p('排热能力子模型的结果尚未生成。')
        return
    order = [c for c in ('hot75', 'nom0', 'cold0') if c in cap['rows']]
    qs = sorted({r['Qd_kW'] for c in order for r in cap['rows'][c]})
    rows = []
    for c in order:
        for L in ('A', 'B'):
            rr = {r['Qd_kW']: r for r in cap['rows'][c] if r['loop'] == L}
            rows.append([CASE_LABEL[c], L] + [f"{X.num(rr[q]['Tout_mean_C'])} / {X.num(rr[q]['Tout_max_C'])}" if q in rr else '' for q in qs])
    D.table('散热器全流量时的出口氨温度，一圈平均值 / 一圈最高值，单位 °C', ['工况', '回路'] + [f'{q:.0f} kW' for q in qs], rows,
            widths=[2.8, 1.2] + [11.8 / len(qs)] * len(qs))
    rows = []
    for c in order:
        res = cap['summary'][c]['capacity']
        for L in ('A', 'B'):
            m, x = res[L]['Q_at_mean_setpoint_kW'], res[L]['Q_at_max_setpoint_kW']
            r35 = next((r for r in cap['rows'][c] if r['loop'] == L and abs(r['Qd_kW'] - 35.0) < 1e-6), None)
            qmax_c = max(r['Qd_kW'] for r in cap['rows'][c])
            rows.append([CASE_LABEL[c], L, f"{X.num(r35['Tout_mean_C'])} / {X.num(r35['Tout_max_C'])}" if r35 else '',
                         X.num(x, 0) if x is not None else f'大于 {qmax_c:.0f}', X.num(X.T_SET_C + x * 1e3 / X.loop_mcp(L), 1) if x is not None else '',
                         X.num(m, 0) if m is not None else f'大于 {qmax_c:.0f}'])
    D.table('散热器全流量排热能力', ['工况', '回路', '排热 35 kW 时出口温度，一圈平均值 / 一圈最高值，°C', '出口温度一圈最高值达到 2.8 °C 时的排热量，kW',
            '该排热量下的散热器入口温度，°C', '出口温度一圈平均值达到 2.8 °C 时的排热量，kW'], rows, widths=[2.6, 1.1, 3.4, 3.0, 2.7, 3.0])
    D.figure(os.path.join(FIG, 'capacity_outlet.png'), '散热器全流量时出口氨温度与单回路排热量的关系', 15.5)
    r35, mx = hot_capacity()
    if r35:
        t35 = max(r['Tout_max_C'] for r in r35)
        txt = (f'设计热工况下，单回路排热 35 kW 时散热器全流量出口温度的一圈最高值为 {X.num(t35)} °C，'
               + (f'比 2.8 °C 设定点低 {X.num(X.T_SET_C - t35)} K，模型散热器满足单回路 35 kW 的排热要求。' if t35 < X.T_SET_C else f'比 2.8 °C 设定点高 {X.num(t35 - X.T_SET_C)} K。'))
        if 'A' in mx and 'B' in mx:
            txt += f"出口温度一圈最高值达到 2.8 °C 时，回路 A 与回路 B 分别可排出 {X.num(mx['A'], 0)} kW 与 {X.num(mx['B'], 0)} kW。"
        txt += ('公开资料给出三个参考值：文献 A 给出 EATCS 设计排热能力 70 kW，即单回路 35 kW，文献 D5 正文把 70 kW 称为规定的最低性能；'
                '文献 D4 与 D5 表 3.2-1 给出 75 kW；文献 D5 表 4.4-2 按解析方法估算装配完成状态的散热器能力为 87.9 kW，即单回路约 44 kW。')
        ra = next((r for r in r35 if r['loop'] == 'A'), None); rb = next((r for r in r35 if r['loop'] == 'B'), None)
        if ra and rb:
            dT = abs(rb['Tout_mean_C'] - ra['Tout_mean_C'])
            dflow = abs(35e3 / X.loop_mcp('A') - 35e3 / X.loop_mcp('B')) / 2
            txt += (f'同一排热量下两个回路出口温度的一圈平均值相差 {X.num(dT, 1)} K，两回路流量不同只能解释其中约 {X.num(dflow, 1)} K，'
                    '其余来自两翼整体转动后上下相叠造成的遮挡，见第 3.5 节；实际两翼并排，没有这一差别。')
        D.p(txt)
    sens = [(k, lab) for k, lab in (('hot75', '基准：g 为 120 W·m⁻²·K⁻¹，Z-93 吸收率 0.24'),
                                    ('hot75_g40', 'g 取 40 W·m⁻²·K⁻¹，相当于面板综合翅片效率约 0.8 至 0.9'),
                                    ('hot75_a36', 'Z-93 吸收率取 30 年末期包络 0.36')) if k in cap['rows']]
    if len(sens) > 1:
        rows = []
        for k, lab in sens:
            res = cap['summary'][k]['capacity']
            r35 = {r['loop']: r for r in cap['rows'][k] if abs(r['Qd_kW'] - 35.0) < 1e-6}
            qmax_k = max(r['Qd_kW'] for r in cap['rows'][k])
            cells = [lab]
            for L in ('A', 'B'):
                cells.append(X.num(r35[L]['Tout_max_C']) if L in r35 else '')
            for L in ('A', 'B'):
                x = res[L]['Q_at_max_setpoint_kW']
                cells.append(X.num(x, 0) if x is not None else f'大于 {qmax_k:.0f}')
            rows.append(cells)
        D.table('设计热工况散热器排热能力对理想化处理的敏感性', ['计算条件', '35 kW 时出口最高温度 A，°C', '35 kW 时出口最高温度 B，°C',
                '排热能力 A，kW', '排热能力 B，kW'], rows, widths=[5.2, 2.7, 2.7, 2.6, 2.6])
        D.p('表中排热能力指出口温度一圈最高值达到 2.8 °C 时的单回路排热量。面板与氨之间的换热系数 g 取 40 W·m⁻²·K⁻¹ 时，氨到面板的串联热阻使面板平均温度降低，'
            '按面板两面线性化辐射换热系数 6 至 9 W·m⁻²·K⁻¹ 计，效果相当于面板综合翅片效率约 0.8 至 0.9；吸收率取 0.36 考察涂层老化的影响。')
    if mx and min(mx.values()) > 44:
        qa, qb = (17 - X.T_SET_C) * X.loop_mcp('A') / 1e3, (17 - X.T_SET_C) * X.loop_mcp('B') / 1e3
        D.p('子模型求得的排热量高于参考值，原因有两方面。第一，排热量增大时散热器入口温度随之升高，散热器温度越高排热越多。'
            '舱内热量经界面换热器传给氨，氨出口温度受中温水回路回水温度限制，回水温度随舱内负荷变化，部分界面换热器串联；'
            f'若以中温水回路供水温度 17 °C 近似作为散热器入口温度上限，按模型流量计算，回路 A 与回路 B 的收集热量分别约为 {X.num(qa, 0)} kW 与 {X.num(qb, 0)} kW，'
            '更高入口温度对应的排热量需按界面换热器性能核算。第二，模型的理想化处理使散热器排热偏多：散热器与桁架、太阳翼、PVR 之间的遮挡和相互辐射按组间不计处理；'
            '面板与氨的换热在面板上均布，相当于流管之间面板的翅片效率取 1，实际面板靠两层 0.254 mm 铝蒙皮导热，远离流管处的面板温度低于氨温度；'
            '散热器指向按理想的侧边对日处理。子模型结果应看作排热能力的上限，核算载荷余量时以单回路 35 kW 的设计排热能力为准。')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--cases', default='cold0,hot75,nom0'); ap.add_argument('--out', default='国际空间站有限元热建模与分析报告.docx')
    a = ap.parse_args()
    cases = [c for c in a.cases.split(',') if c]
    D = build(cases)
    D.r.save(os.path.join(HERE, a.out))
    open(os.path.join(ROOT, 'docs', 'REPORT.md'), 'w', encoding='utf-8').write(''.join(D.md))
    fin = os.path.join(HERE, 'finalize.ps1')
    if not os.path.exists(fin):
        shutil.copy(os.path.join(REPO, 'report', 'finalize.ps1'), fin)
    print('wrote', os.path.join(HERE, a.out), 'and docs/REPORT.md')


if __name__ == '__main__':
    main()
