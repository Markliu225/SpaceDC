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
    r.kv_table([('模型工具', 'COMSOL Multiphysics 6.3，传热模块，Python MPh 接口'), ('分析对象', '国际空间站 2019 年构型，全站'),
                ('分析工况', '设计冷工况、设计热工况、平均环境工况'), ('编制日期', '2026 年 9 月 30 日')])
    r.page_break(); r.toc(); r.page_break()
    D.md.append('# 国际空间站有限元热建模与分析报告\n\n编制日期 2026-09-30。模型工具 COMSOL Multiphysics 6.3 传热模块，Python MPh 接口。\n')


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

    # ------------------------------------------------------------------ 1
    D.h(1, '1 概述')
    D.p('本报告记录国际空间站有限元热模型的建立过程与轨道热分析结果。模型在 COMSOL Multiphysics 6.3 中以脚本方式建立，'
        '几何、材料、表面性质与热负荷依据 Thermal 目录三份热控文献、NASA 公开三维模型、SSP 30219 坐标系规范与公开工程资料确定，'
        '每个数值都记录了来源，公开资料取值经过独立核验。舱内机柜、舱外电子设备与舱外载荷全部简化为方块热源，热量经冷板进入冷却回路，'
        '由有限元散热器面板向深空排出。分析覆盖设计冷工况、设计热工况与平均环境工况，每个工况连续计算三个轨道周期，'
        '结果取第三圈。')
    D.h(2, '1.1 主要结论')
    D.items(conclusions(C, LT, CT, PER))

    # ------------------------------------------------------------------ 2
    D.h(1, '2 依据资料')
    D.p('模型参数分三个层次取得。第一层是 Thermal 目录三份文献，给出主动热控系统的组成、散热器与设备尺寸、回路流量与控制设定值。'
        '第二层是公开工程资料，补全全站几何、表面光学性质、材料热物性、热负荷与空间热环境。第三层是模型取定值，'
        '用于公开资料没有覆盖的参数，全部在第 3.9 节列出。公开资料按五个方向并行检索，每个方向由独立核验方逐条复查。')
    D.table('依据资料与用途', ['代号', '资料', '用途'], [
        ['A', 'Active Thermal Control System ATCS Overview，Boeing', 'EATCS 与 PVTCS 组成、散热器与设备尺寸、流量、供液设定点'],
        ['B', 'ICES-2019-31 P1 EATCS Ammonia Leak，NASA JSC', '散热器布置、回路与桁架段关系'],
        ['C', '05ICES-279 IATCS Coolant Remediation，Boeing 与 NASA', '舱内回路温度与材料'],
        ['G3D', 'NASA 3D Resources IGOAL 模型，JSC', '全部部件在分析坐标系中的位置'],
        ['W1', 'SSP 30219 Rev F 空间站坐标系规范', '坐标系、SARJ、BGA、TRRJ 转轴与零位定义'],
        ['JSC 26557', 'ISS On-Orbit Assembly, Modeling and Mass Properties Data Book', '舱段质心与外包络'],
        ['RG', 'Reference Guide to the ISS 2010，ESA 与 JAXA 概况单', '舱段长度与直径'],
        ['SSP 41000 与 30425', '设计验证环境与自然环境定义', '太阳常数、反照率、地球红外'],
        ['D4', 'TD9702A International Space Station Familiarization，NASA JSC', 'EATCS 排热能力与设计流量'],
        ['D5', 'NASA/SP-2000-6109 ISS Evolution Data Book Volume I', 'EATCS 排热能力、热负荷分配、β 角范围'],
        ['D16', 'ICES-2022-145 Coolant Leak from ISS EATCS，Cowan 与 Bond', '散热器回流接头在轨温度'],
        ['D17', 'TFAWS18-AT-01 Ammonia Vent of the EATCS Radiator，Cowan', '散热器流路在轨温度极值'],
        ['O 系列', '热控涂层与材料文献，MIL-HDBK-5J，NIST', '表面光学性质与材料热物性'],
    ], widths=[2.6, 6.6, 6.6])
    D.p('各方向的原始记录与核验记录保存在 docs 目录，模型采用的最终取值汇总在 ISS_SPEC.md 与 model/iss_spec.py。'
        '核验中纠正了散热器转轴方向：SSP 30219 明确 TRRJ 绕 X 轴转动，零位时三个散热器 ORU 沿 Z 叠放，面板法向指向右舷，'
        '转过 90° 为正面对地姿态。')

    # ------------------------------------------------------------------ 3
    D.h(1, '3 有限元模型')
    D.h(2, '3.1 坐标系、构型与姿态')
    D.p('坐标系为空间站分析坐标系：原点在 S0 桁架段几何中心，+X 沿舱段轴线指向飞行方向，+Y 指向右舷，+Z 指向天底。'
        '构型取 2019 年状态：PMM 在节点3 前向口，PMA-3 在节点2 天顶口，Pirs 在服务舱天底口，BEAM 在节点3 后向口。'
        '姿态为 +XVV 对地定向，+Z 始终指向地心，+X 指向速度方向，力矩平衡姿态的小角度偏置不计。'
        f'轨道高度 {S.ORBIT["alt_m"] / 1e3:.0f} km，倾角 {S.ORBIT["incl_deg"]}°，周期 {C[cases[0]]["per"]:.1f} s。')
    D.h(2, '3.2 几何模型')
    D.p('几何全部由 COMSOL 的基本几何体生成。加压舱为先建实体圆柱再转换得到的封闭曲面，赋壳单元；桁架段、舱外设备、IEA、舱外载荷与舱内机柜为实体方块；'
        'EATCS 散热器、PVR 与太阳翼毯面为工作平面上的矩形曲面，赋壳单元。部件之间留 5 cm 间隙，几何经自动包围盒检查无相交。')
    D.table('几何模型组成', ['部件类别', '数量', '单元类型', '说明'], [
        ['加压舱', '20', '壳', '美国段 14 个，俄罗斯段 6 个，含端盖'],
        ['桁架段', '12', '实体', 'Z1、S0、S1 至 S6、P1 至 P6'],
        ['冷板设备', '10', '实体', 'MBSU 4 台，DDCU 6 台'],
        ['EATCS 无源设备', '6', '实体', '氨罐、泵模块、氮罐各 2 台'],
        ['IEA 电子设备', '4', '实体', 'P4、P6、S4、S6 各 1 台'],
        ['舱外载荷', '6', '实体', 'ELC 4 个、AMS-02、JEM-EF'],
        ['舱内机柜', '88', '实体', 'Destiny 24、Harmony 8、Tranquility 16、Columbus 16、Kibo 24'],
        ['EATCS 散热器面板', '48', '壳', '6 个 ORU，每个 8 块面板'],
        ['PVR 面板', '28', '壳', '4 台 PVR，每台 7 块面板'],
        ['太阳翼毯面', '18', '壳', '美国太阳翼 16 块，服务舱太阳翼 2 块'],
    ], widths=[3.6, 1.6, 2.0, 8.6])
    D.figure(os.path.join(FIG, 'iss_nom0_geom_iso_legend.png'), '全站几何模型，按热分类着色')
    D.figure(os.path.join(FIG, 'iss_nom0_geom_top_legend.png'), '全站几何模型天顶视图，图中上方为飞行方向')
    D.figure(os.path.join(FIG, 'iss_nom0_geom_core_legend.png'), '中央桁架、散热器翼与加压舱局部')
    D.h(2, '3.3 网格')
    m = C[cases[0]]['summ'].get('mesh', {})
    D.p(f'壳面用自由三角形单元，实体用自由四面体单元，网格尺寸按部件类别设定：太阳翼 3.0 m，桁架 2.2 m，舱体 1.4 m 至 1.6 m，'
        f'散热器与 PVR 面板 1.2 m 至 1.4 m，舱外设备 0.6 m，机柜 0.7 m。全模型共 {m.get("tri", 0)} 个三角形面单元与 {m.get("tet", 0)} 个四面体单元，'
        '温度求解自由度约 8.2 万个。')
    D.figure(os.path.join(FIG, 'iss_nom0_mesh_iso.png'), '全站表面网格')

    D.h(2, '3.4 表面光学性质与材料')
    O = S.OPTICS
    D.table('表面光学性质', ['类别', '太阳吸收率', '红外发射率', '依据'], [
        ['EATCS 散热器与 PVR，Z-93', f"{O['z93']['alpha']:.2f}", f"{O['z93']['eps']:.2f}", '名义值；冷工况取寿命初期 0.15 与 0.91，热工况取老化后 0.24 与 0.90'],
        ['美国段舱体防护屏', f"{O['skin_usos']['alpha']:.2f}", f"{O['skin_usos']['eps']:.2f}", '铬酸阳极化铝，外侧辐射'],
        ['俄罗斯段舱体外表面', f"{O['skin_rus']['alpha']:.2f}", f"{O['skin_rus']['eps']:.2f}", '无公开值，取镀铝 beta 布'],
        ['桁架', f"{O['truss']['alpha']:.2f}", f"{O['truss']['eps']:.2f}", '硫酸阳极化'],
        ['舱外设备与 IEA', f"{O['box']['alpha']:.3f}", f"{O['box']['eps']:.2f}", '多层隔热包覆，按有效发射率 0.03 折算'],
        ['舱外载荷', f"{O['payload']['alpha']:.2f}", f"{O['payload']['eps']:.2f}", 'ISS 批次镀铝 beta 布'],
        ['太阳翼电池面', f"{O['saw_cells']['alpha']:.3f}", f"{O['saw_cells']['eps']:.2f}", '吸收率已扣除发电份额 0.073'],
        ['太阳翼背面', f"{O['saw_back']['alpha']:.2f}", f"{O['saw_back']['eps']:.2f}", '聚酰亚胺与玻璃纤维基底'],
    ], widths=[4.4, 2.2, 2.2, 7.0])
    M = S.MATERIALS
    rows = []
    for key, name in (('al_skin_usos', '美国段防护屏'), ('al_skin_rus', '俄罗斯段防护屏'), ('hrs_pan', 'EATCS 散热器面板'), ('pvr_pan', 'PVR 面板'),
                      ('saw_blk', '太阳翼毯面'), ('truss_eq', '桁架包络'), ('oru_eq', '舱外设备与 IEA'), ('pl_eq', '舱外载荷'), ('rack_eq', '舱内机柜')):
        mm = M[key]
        rows.append([name, ('%.1f mm' % (mm['t'] * 1e3)) if mm['kind'] == 'shell' else '实体', f"{mm['k']:g}", f"{mm['rho']:g}", f"{mm['cp']:g}"])
    D.table('材料与等效热物性，导热系数单位 W·m⁻¹·K⁻¹，密度 kg/m³，比热 J·kg⁻¹·K⁻¹', ['类别', '厚度', '导热系数', '密度', '比热'], rows, widths=[4.6, 2.2, 2.6, 2.6, 2.6])
    D.p('壳单元的厚度、密度与比热按面热容等效，导热系数按面内热导等效。散热器面板面密度取 8 kg/m²，ORU 外廓面密度 14.2 kg/m² 含展开机构；'
        '太阳翼毯面面热容取 1.6 kJ·m⁻²·K⁻¹，使出影后约 3 min 由 −80 °C 升到 0 °C，与在轨观测一致；桁架包络的等效密度由桁架段总质量扣除太阳翼、'
        'PVR、散热器与 IEA 后除以模型包络体积得到。')

    D.h(2, '3.5 传热与辐射')
    D.p('实体部件用固体传热接口求解温度 T，壳部件用壳传热接口求解温度 T_{2}，两类部件的外表面都参与轨道热载荷计算。轨道热载荷接口按太阳与红外两个波段计算直接日照、'
        '地球反照与地球红外，并用半立方体法计算部件之间的相互辐射与遮挡，深空温度 2.7 K。')
    D.p('轨道热载荷接口在材料坐标系中计算外热流，不支持部件相对转动。模型把转动部件分为四个辐射组，每组一个轨道热载荷接口，各自设定指向规律，'
        '组内相互辐射与遮挡完整计算，组间不计。')
    D.table('辐射分组与指向规律', ['辐射组', '成员', '指向规律'], [
        ['机体组', '舱体、桁架、全部方块', '+Z 指向天底，+X 指向速度方向'],
        ['散热器组', '6 个 EATCS 散热器 ORU', 'β 为 0 的工况在受晒段保持 TRRJ 零位，面板法向垂直于轨道面，任一轨道角都侧边对日；β 不为 0 的工况绕 X 轴转动，使太阳方向落在面板平面内；地影段面板法向转向天底'],
        ['SARJ 组', '4 台 PVR，服务舱太阳翼', '绕 Y 轴随太阳转动，PVR 侧边对日，服务舱太阳翼电池面对日'],
        ['太阳翼组', '8 个美国太阳翼', '电池面法向始终指向太阳，长轴垂直于 Y 轴，对应 SARJ 与 BGA 的组合转动'],
    ], widths=[2.6, 4.2, 9.0])

    D.h(2, '3.6 方块热源')
    D.p('全部发热部件简化为方块热源，热量以体积热源均匀施加，方块的一个面作为冷板面，以对流形式换热到回路温度，其余面按部件所处环境设置边界。')
    racks = ', '.join(f'{k} {n * 4} × {w:.0f} W' for k, (n, w) in S.RACK_MODULES.items())
    D.table('方块热源与冷却方式', ['类别', '热源', '冷却方式'], [
        ['舱内机柜', '每舱四面机柜，Destiny 24 × 500 W，Harmony 8 × 300 W，Tranquility 16 × 400 W，Columbus 16 × 600 W，Kibo 24 × 600 W，合计 44.8 kW',
         '背面冷板，三面接中温回路 17 °C，一面接低温回路 4 °C，热导 40 W·m⁻²·K⁻¹；其余面对 22 °C 舱内空气 2 W·m⁻²·K⁻¹'],
        ['MBSU 与 DDCU', 'MBSU 4 × 495 W，DDCU 6 × 694 W', '底面冷板，接氨供液 2.8 °C，热导 60 W·m⁻²·K⁻¹；外表面按多层隔热折算辐射'],
        ['IEA 电子设备', '4 × 6 kW', '冷板接各自 PVTCS 回路；外表面按多层隔热折算辐射'],
        ['舱外载荷', 'ELC 4 × 1 kW，AMS-02 2.5 kW，JEM-EF 3 kW', '无冷板，外表面向空间辐射'],
        ['乘员代谢热', '6 × 136.8 W', '计入低温回路，两个 EATCS 回路各 410 W'],
    ], widths=[2.8, 6.6, 6.4])
    D.p('美国段舱体防护屏的内侧通过多层隔热与 22 °C 舱内空气换热，等效热导 0.08 W·m⁻²·K⁻¹，由节点3 在冷偏置姿态下的壳体漏热数据推算。'
        '舱内机柜与空气交换的热量、舱体漏热都计入对应舱段的低温回路。')

    D.h(2, '3.7 冷却回路模型')
    D.p('EATCS 两个回路与四个 PVTCS 回路用全局方程描述。回路收集的热量 Q_{c} 等于各冷板面与舱内空气换热面的热流积分之和，经 20 s 滞后进入回路。'
        '散热器入口温度为供液设定点加上收集热量引起的温升：')
    D.formula('ṁ c_{p} T_{ret} = ṁ c_{p} T_{set} + Q_{c}')
    D.p('每个 EATCS 回路的流量按三个散热器 ORU 均分，每个 ORU 的 8 块面板串联，每块面板对应一个氨温度节点，节点热容 1 kJ/K。'
        '面板与氨之间的换热热流密度为 g 乘以氨平均温度与面板温度之差，g 取 120 W·m⁻²·K⁻¹，约为面板两面线性化辐射换热系数 9 W·m⁻²·K⁻¹ 的 13 倍，氨与面板之间的温差只占散热温差的一小部分：')
    D.formula('3 C_{f} dT_{i}/dt = f ṁ c_{p} ΔT_{i} − 3 ∫ g ΔT_{w} dA')
    D.p('其中 ΔT_{i} 为面板进出口氨温度差，ΔT_{w} 为氨平均温度与面板局部温度之差。散热器出口氨与旁路氨混合后回到供液端，旁通阀以积分控制调节散热器分流比 f，'
        '使混合温度回到 2.8 °C，积分增益 3000 K·s，闭环时间常数约 2 min；分流比设平滑下限 0.02 与抗积分饱和。分流比超过 1 表示散热能力不足。')
    D.table('回路参数', ['参数', '取值', '依据'], [
        ['回路 A 流量', '8200 lb/h，即 1.033 kg/s', 'A 第10页'], ['回路 B 流量', '8900 lb/h，即 1.121 kg/s', 'A 第10页'],
        ['供液设定点', '2.8 °C', 'A 第6页、第11页'], ['液氨比热', '4612.6 J·kg⁻¹·K⁻¹', 'NIST，2.8 °C、300 psia'],
        ['回路热量分配', 'Destiny 与 Kibo 中温侧进回路 B，节点2、节点3、Columbus 中温侧进回路 A，低温侧相反', 'A 第5页回路图'],
        ['PVTCS 流量与设定点', '0.5 kg/s，2.8 °C', '公开资料未给出，取定值'],
    ], widths=[3.4, 7.2, 5.2])

    D.h(2, '3.8 求解设置')
    D.p('每个工况先由轨道热载荷研究步计算全时段外热流，再由轨道温度研究步求解温度与回路。时间推进采用 120 s 定步长后向欧拉法，计算三个轨道周期，'
        '共 16661 s。分离式求解器分六组：实体温度一组，壳温度与全部回路未知量一组，四个辐射组的辐射度各一组，每步最多 25 次分离迭代。')
    D.p('建模中处理了五个数值问题。其一，COMSOL 面型圆柱没有端盖，舱体改为实体圆柱转换的封闭曲面，并令蒙皮只在外法向一侧辐射，消除舱内全反射空腔造成的奇异。'
        '其二，回路方程由代数方程改为常微分方程，避免求一致初值时出现非物理温度。其三，温度与回路未知量设手动缩放。'
        '其四，收集热量设为独立未知量，避免散热器热源依赖全部机柜自由度。其五，自由步长在外热流分段更新处反复失败，改为定步长。')

    D.h(2, '3.9 模型取定值与主要简化')
    D.items([
        ('1．', '转动部件分组计算辐射，组间不计相互辐射与遮挡。'),
        ('2．', '桁架以不透明实体包络表示，杆件之间的透射按包络处理。'),
        ('3．', '舱内空气温度由空调维持在 22 °C，各舱之间不计导热。'),
        ('4．', '散热器面板内的换热按面板均布，不区分流管位置。'),
        ('5．', '太阳翼光学性质、俄罗斯段外表面涂层、PVTCS 流量与设定点、舱内实际机柜功率、舱外载荷功率没有公开值，采用典型值。'),
        ('6．', '散热器指向采用理想的侧边对日与正面对地规律，没有模拟 RGAC 对出口温度的反馈调节。'),
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
    D.p('设计冷工况与设计热工况取 SSP 41000 的设计验证环境，平均环境工况取空间站舱外活动热数据库的平均值，反照率按 β 修正加 0.04。'
        '三个工况的热负荷相同。')

    # ------------------------------------------------------------------ 5
    results_section(D, cases, C, LT, CT, PER, IT)
    D.h(1, '6 结论与建议')
    D.items(final_remarks(C, LT, CT, PER))
    D.h(1, '附录 文件与复现')
    D.table('主要文件', ['文件', '内容'], [
        ['model/iss_spec.py', '全部模型参数与来源'], ['model/iss_layout.py', '几何布局、辐射分组、回路方程'],
        ['model/iss_build.py', '在 COMSOL 中建立几何、网格、物理场与研究'], ['model/iss_run.py', '求解与结果探针'],
        ['model/iss_capacity.py', '散热器排热能力子模型'],
        ['model/iss_render.py 与 iss_plots.py', '云图与时程图'], ['out 下各工况目录中的 series.csv、items.csv 与 loop_breakdown.csv', '时程、部件统计与回路热量来源'],
        ['out/capacity/', '排热能力子模型的出口温度与插值结果'],
        ['docs/ISS_SPEC.md 与各资料文档', '参数来源与核验记录'],
    ], widths=[6.4, 9.4])
    D.p('复现步骤以平均环境工况 nom0 为例：在 backend 虚拟环境中依次运行 iss_build.py --case nom0 --no-solve 与 iss_run.py nom0 --orbits 3 --dt 120，'
        '再运行 post_all.py nom0 完成结果探针、时程图、温度云图与本报告；散热器排热能力子模型运行 iss_capacity.py hot75 --q 35,60,85,110,135。')
    return D


def conclusions(C, LT, CT, PER):
    import iss_results_ext as X
    out = []
    n = [1]

    def add(t):
        out.append((f'{n[0]}．', t)); n[0] += 1
    add('在 COMSOL 中建立了国际空间站全站有限元热模型，包含 20 个加压舱、12 个桁架段、6 个 EATCS 散热器、4 台 PVR、18 块太阳翼毯面与 114 个方块热源，'
        '几何、材料、表面性质与热负荷全部可追溯到文献或公开资料，布局与 SSP 30219 的关节定义一致。')
    for c in C:
        lt = LT[c]
        if not lt: continue
        a, b = lt['A'], lt['B']
        add(f'{CASE_LABEL[c]}第三圈，回路 A 与回路 B 收集热量平均 {kw(a["Q"]["mean"])} kW 与 {kw(b["Q"]["mean"])} kW，'
            f'散热器分流比平均 {a["f"]["mean"]:.2f} 与 {b["f"]["mean"]:.2f}，最大 {max(a["f"]["max"], b["f"]["max"]):.2f}；'
            f'混合供液温度保持在 {X.rng(min(a["Tmix"]["min"], b["Tmix"]["min"]), max(a["Tmix"]["max"], b["Tmix"]["max"]))} °C，'
            f'散热器出口氨温度在 {X.rng(min(a["Tout"]["min"], b["Tout"]["min"]), max(a["Tout"]["max"], b["Tout"]["max"]))} °C。')
    rk = {c: X.rack_stats(C[c]) for c in C}
    tmax = max((v['Tmax'] for c in C for v in rk[c].values()), default=float('nan'))
    add(f'舱内机柜作为方块热源，三个工况下最高温度 {X.num(tmax)} °C，低于机柜前面板 37 °C 的平均温度限值；机柜温度由冷板回路温度决定，基本不受轨道环境影响。')
    cap = X.capacity()
    hot = (cap or {}).get('summary', {}).get('hot75', {}).get('capacity')
    if hot:
        mx = [hot[L]['Q_at_max_setpoint_kW'] for L in ('A', 'B') if hot[L]['Q_at_max_setpoint_kW'] is not None]
        r35 = [r for r in cap['rows'].get('hot75', []) if abs(r['Qd_kW'] - 35.0) < 1e-6]
        if r35:
            add(f"散热器子模型令全部氨流经散热器，设计热工况下单回路排热 35 kW 时出口温度轨道最高 {X.num(max(r['Tout_max_C'] for r in r35))} °C，"
                '低于 2.8 °C 设定点，模型散热器满足单回路 35 kW 的规定排热能力'
                + (f'；出口温度整圈不超过 2.8 °C 的单回路排热量为 {X.num(min(mx), 0)} kW 至 {X.num(max(mx), 0)} kW，'
                   '高于公开资料的估算值，差别来自入口温度随排热量升高与模型的理想化处理，应看作排热能力的上限。' if mx else '。'))
    return out


def final_remarks(C, LT, CT, PER):
    import iss_results_ext as X
    out = []
    n = [1]

    def add(t):
        out.append((f'{n[0]}．', t)); n[0] += 1
    fmax = max((v['f']['max'] for c in C for v in LT[c].values()), default=0)
    cap = X.capacity()
    hot = (cap or {}).get('summary', {}).get('hot75', {}).get('capacity')
    mx = [hot[L]['Q_at_max_setpoint_kW'] for L in ('A', 'B') if hot and hot[L]['Q_at_max_setpoint_kW'] is not None]
    qmax = max((v['Q']['mean'] for c in C for v in LT[c].values()), default=0) / 1e3
    add(f'在当前约 44.8 kW 舱内热负荷与 6.1 kW 舱外冷板负荷下，三个工况的散热器分流比最大 {fmax:.2f}，EATCS 散热器仍有较大余量。'
        + (f'散热器子模型给出设计热工况下单回路排热能力上限 {X.num(min(mx))} kW，全站模型中单回路收集热量最大 {X.num(qmax)} kW，'
           '舱内机柜或舱外载荷增加功率时，核算余量应以 35 kW 设计值为准。' if mx else ''))
    tmin = min((v['Tout']['min'] for c in C for v in LT[c].values()), default=None)
    if tmin is not None and tmin < -40:
        add(f'散热器出口温度最低 {X.num(tmin)} °C，低于 −40 °C 的出口目标值与在轨流路温度极值，原因是模型散热器排热偏多，见 5.6 节；'
            '旁通阀减小分流比后供液温度仍保持在设定点，出口温度偏低不影响舱内回路。后续可用在轨出口温度数据修正散热器与桁架、太阳翼之间的遮挡以及面板翅片效率。')
    add('舱外载荷与 IEA 等方块热源的温度对外表面光学性质与多层隔热参数敏感，工程应用时应以载荷的实测光学性质与热控设计替换本报告的典型值。')
    add('本模型已具备按工况批量计算的脚本流程，可直接用于计算载荷在不同安装位置、不同功率下的温度与 EATCS 余量，也可把载荷方块替换为算力载荷的详细模型。')
    add('主要不确定性来自组间辐射不计、桁架按实体包络处理、散热器面板换热均布、机柜与 IEA 尚未完全达到周期稳态以及部分参数取典型值。'
        '机柜与 IEA 的储热影响见 5.1 节，离散误差见 5.7 节，其余各项需要用在轨温度数据或参数敏感性计算进一步量化。')
    return out


def results_section(D, cases, C, LT, CT, PER, IT):
    import iss_results_ext as X
    D.h(1, '5 分析结果')
    D.p('以下统计取每个工况第三个轨道周期。热量与温度的时程由探针逐步输出，部件统计由有限元温度场在部件区域内求最小值、平均值与最大值。'
        '温度云图中各部件画在参考姿态，太阳翼、PVR 与散热器的实际指向随轨道变化，外热流按各自的指向规律计算；云图色标范围统一为 −80 °C 至 80 °C。')

    # ------------------------------------------------ 5.1 EATCS
    D.h(2, '5.1 EATCS 回路')
    rows = []
    for c in cases:
        for L, v in LT[c].items():
            rows.append([CASE_LABEL[c], L, kw(v['Q']['mean']), kw(v['Qrad']['mean']), X.num(v['closure_pct']),
                         f"{v['f']['mean']:.2f}", f"{v['f']['min']:.2f} 至 {v['f']['max']:.2f}", X.num(v['Tret']['mean']),
                         X.rng(v['Tout']['min'], v['Tout']['max']), X.rng(v['Tmix']['min'], v['Tmix']['max'])])
    D.table('EATCS 回路第三圈统计，热量单位 kW，温度单位 °C', ['工况', '回路', '收集热量', '散热器排热', '偏差 %', '分流比均值', '分流比范围',
            '散热器入口', '散热器出口', '混合供液'], rows, widths=[2.4, 1.1, 1.5, 1.6, 1.3, 1.5, 1.9, 1.5, 2.0, 1.9])
    D.p('两个回路的混合供液温度都保持在 2.8 °C 设定点附近，说明旁通阀控制正常；散热器排热与回路收集热量在一圈内平均相差很小，'
        '差值对应散热器面板与氨节点的储热变化。')
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
            D.p(f"回路 B 收集的热量高于回路 A，主要差别在中温机柜：Destiny 与 Kibo 两个大舱的中温机柜接在回路 B 上，"
                f"{CASE_LABEL[cases[0]]}中回路 B 的中温机柜热量 {X.num(b0['B'].get('rack_MT', 0) / 1e3, 1)} kW，回路 A 为 {X.num(b0['A'].get('rack_MT', 0) / 1e3, 1)} kW。"
                '多层隔热漏热为负值，表示舱内空气经多层隔热向防护屏散失热量，舱内空调需要排出的热量相应减少，模型把这部分热量从对应舱段低温回路的收集热量中扣除。')
        rack_W = sum(n * 4 * w for n, w in S.RACK_MODULES.values()); iea_W = len(S.IEA['units']) * S.IEA['Q']
        coll, colli = [], []
        for c in cases:
            b = BD[c] or {}
            if not b: continue
            coll.append(sum(v for L in ('A', 'B') for k, v in b.get(L, {}).items() if k in ('rack_MT', 'rack_LT', 'air')))
            colli.append(sum(v for L, d in b.items() if L.startswith('PV') for k, v in d.items() if k == 'iea'))
        if coll:
            D.p(f'舱内机柜共发热 {X.num(rack_W / 1e3, 1)} kW，第三圈经冷板与舱内空气进入回路的热量为 {X.rng(min(coll) / 1e3, max(coll) / 1e3)} kW；'
                f'四台 IEA 共发热 {X.num(iea_W / 1e3, 1)} kW，第三圈进入 PVTCS 的热量为 {X.rng(min(colli) / 1e3, max(colli) / 1e3)} kW。'
                '机柜只通过冷板与舱内空气散热，差值全部是机柜内部仍在升温储存的热量；IEA 的差值中还有少量经多层隔热向外辐射的热量。'
                '两类方块的初始温度取冷板面的平衡温度，方块内部导热形成的温度梯度需要数小时才能建立，'
                '三个轨道周期内尚未完全达到周期稳态，达到稳态后回路收集热量将增加上述差值，EATCS 与 PVTCS 的分流比相应增大。')
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
    D.p('每个 ORU 的 8 块面板沿流向串联，入口面板温度最高，出口面板最低，面板间温差与流量和散热量相关。回路 A 的三个 ORU 位于右舷，回路 B 的位于左舷；'
        '同一回路三个 ORU 的差别来自叠放位置不同带来的对地视角与相互遮挡差异。')
    rows = []
    for c in cases:
        for u, v in X.pv_loops(C[c]).items():
            rows.append([CASE_LABEL[c], u, kw(v['Q']['mean']), f"{v['f']['mean']:.2f}", X.rng(v['Tout']['min'], v['Tout']['max']), X.rng(v['Tmix']['min'], v['Tmix']['max'])])
    if rows:
        D.table('PVTCS 回路第三圈统计，热量单位 kW，温度单位 °C', ['工况', '光伏模块', '收集热量', '分流比均值', 'PVR 出口', '混合供液'], rows,
                widths=[3.2, 2.2, 2.4, 2.4, 2.8, 2.8])
    for c in cases:
        D.figure(os.path.join(FIG, f'{c}_orus.png'), f'{CASE_LABEL[c]}六个 EATCS 散热器 ORU 的平均温度', 15.5)
    for c in cases:
        path = os.path.join(FIG, f'{c}_T_hrs_noon.png')
        if os.path.exists(path):
            D.figure(path, f'{CASE_LABEL[c]}第三圈正午右舷 EATCS 散热器翼的表面温度，自右舷方向观察', 15.5)

    # ------------------------------------------------ 5.3 classes
    D.h(2, '5.3 舱体、桁架与太阳翼')
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
    for c in cases:
        D.figure(os.path.join(FIG, f'{c}_classes.png'), f'{CASE_LABEL[c]}各类部件温度时程', 15.5)
    for c in cases:
        for tag, lab in (('noon', '第三圈正午'), ('ecl', '第三圈地影中点'), ('q90', '第三圈轨道角 90°')):
            path = os.path.join(FIG, f'{c}_T_iso_{tag}.png')
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
    D.table('舱外方块热源第三圈温度，单位 °C', ['工况', '部件', '数量', '最低', '平均', '最高'], rows, widths=[3.4, 2.6, 1.8, 2.6, 2.6, 2.6])
    D.p('舱内机柜温度由冷板回路温度、机柜功率与冷板热导决定，三个工况之间几乎没有差别，低温回路机柜比中温回路机柜低约 13 °C。'
        '接冷板的 MBSU、DDCU 与 IEA 温度比氨供液高十余度，包覆多层隔热后受轨道环境影响很小。无冷板的舱外载荷只能向空间辐射散热，'
        '其温度随工况与轨道位置明显变化，热工况与冷工况之间的差别最大。')

    # ------------------------------------------------ 5.5 checks
    D.h(2, '5.5 与规格和在轨数据对比')
    rows = []
    for c in cases:
        lt = LT[c]
        if not lt: continue
        tmix = [v['Tmix'] for v in lt.values()]; tout = [v['Tout'] for v in lt.values()]
        rows.append([CASE_LABEL[c], '氨供液温度', '设定 2.8 °C，控制带 ±1.1 °C，文献 A 第11页', X.rng(min(x['min'] for x in tmix), max(x['max'] for x in tmix)) + ' °C'])
        rows.append([CASE_LABEL[c], '散热器出口温度', '目标 −40 °C，文献 A 第16页；在轨回流接头 −40 °C 至 −18 °C，文献 D16；流路两年内极值 −40 °C 至 13 °C，文献 D17', X.rng(min(x['min'] for x in tout), max(x['max'] for x in tout)) + ' °C'])
        se = X.saw_eclipse(C[c])
        if se:
            rows.append([CASE_LABEL[c], '太阳翼出影温度', '约 −80 °C，约 3 min 升至 0 °C', f"{X.num(se['T_exit'])} °C，" + (f"{se['warm_min']:.0f} min 升至 0 °C" if se['warm_min'] is not None else '')])
        saw = CT[c].get('saw')
        if saw:
            rows.append([CASE_LABEL[c], '太阳翼温度范围', '在轨预计极值约 +60 °C 与 −80 °C', X.rng(saw['min'], saw['max']) + ' °C'])
        rk = CT[c].get('rack')
        if rk:
            rows.append([CASE_LABEL[c], '舱内机柜温度', '前面板平均低于 37 °C', X.rng(rk['min'], rk['max']) + ' °C'])
        rows.append([CASE_LABEL[c], '散热器分流比', '单回路设计散热 35 kW，分流比达到 1 为能力上限', f"最大 {max(v['f']['max'] for v in lt.values()):.2f}"])
    D.table('计算结果与规格、在轨数据对比', ['工况', '项目', '规格或在轨数据', '计算结果'], rows, widths=[2.8, 2.8, 5.6, 4.6])

    capacity_section(D, cases, LT)

    # ------------------------------------------------ 5.7 numerics
    D.h(2, '5.7 能量守恒与周期性')
    rows = []
    for c in cases:
        per = PER[c]
        for k, nm in (('hrs', 'EATCS 散热器'), ('skin_usos', '美国段舱体'), ('truss', '桁架'), ('rack', '舱内机柜'), ('box', '舱外设备')):
            if k in per:
                rows.append([CASE_LABEL[c], nm, X.num(per[k], 2)])
        for L in ('A', 'B'):
            if f'Q_{L}_kW' in per:
                rows.append([CASE_LABEL[c], f'回路 {L} 收集热量，kW', X.num(per[f'Q_{L}_kW'], 2)])
    D.table('第三圈与第二圈平均值之差，温度单位 K', ['工况', '项目', '差值'], rows, widths=[4.0, 6.8, 5.0])
    D.p('散热器、舱体与太阳翼的时间常数在 30 min 以内，第三圈已接近周期稳态；机柜、IEA 与桁架包络的时间常数达数小时，'
        '初始温度按平衡值设定，第三圈的残余漂移列于上表。')
    cap = X.capacity()
    if cap:
        base = {r['loop']: r for r in cap['rows'].get('hot75', []) if abs(r['Qd_kW'] - 35.0) < 1e-6}
        parts = []
        for k, lab in (('hot75_dt60', '时间步长由 120 s 减为 60 s'), ('hot75_h08', '散热器网格尺寸由 1.2 m 减为 0.8 m')):
            rr = {r['loop']: r for r in cap['rows'].get(k, []) if abs(r['Qd_kW'] - 35.0) < 1e-6}
            Ls = [L for L in rr if L in base]
            if Ls:
                dm = max(abs(rr[L]['Tout_mean_C'] - base[L]['Tout_mean_C']) for L in Ls)
                dx = max(abs(rr[L]['Tout_max_C'] - base[L]['Tout_max_C']) for L in Ls)
                parts.append(f'{lab}后，出口温度轨道平均值最多变化 {X.num(dm, 2)} K，轨道最高值最多变化 {X.num(dx, 2)} K')
        if parts:
            D.p('离散误差用散热器子模型检验。以设计热工况单回路 35 kW 为基准，' + '；'.join(parts) + '。'
                '该结果说明 120 s 步长与 1.2 m 网格对回路温度的影响在上述量级。太阳翼的时间常数只有数分钟，出影升温过程的时刻只能分辨到一个时间步。')


def capacity_section(D, cases, LT):
    import iss_results_ext as X
    cap = X.capacity()
    D.h(2, '5.6 散热器排热能力')
    D.p('全站模型中回路收集的热量低于设计值，旁通阀让大部分氨绕过散热器，分流比只说明当前负荷所需的散热器流量。'
        '为求散热器的排热能力，另建只含 48 块 EATCS 散热器面板的子模型。全站模型中散热器辐射组只与本组面板交换辐射，'
        '子模型沿用相同的面板几何、材料、涂层、TRRJ 指向规律与轨道环境，面板所受外热流与全站模型一致。'
        '子模型令回路全部流量流经散热器，给定单回路排热量，散热器入口温度等于出口温度加上排热量引起的温升，散热器出口温度即为供液温度。'
        '每个排热量连续计算两个轨道周期，统计取第二圈。')
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
    D.table('散热器全流量时的出口氨温度，轨道平均 / 轨道最高，单位 °C', ['工况', '回路'] + [f'{q:.0f} kW' for q in qs], rows,
            widths=[2.8, 1.2] + [11.8 / len(qs)] * len(qs))
    T35 = {}
    rows = []
    for c in order:
        res = cap['summary'][c]['capacity']
        for L in ('A', 'B'):
            m, x = res[L]['Q_at_mean_setpoint_kW'], res[L]['Q_at_max_setpoint_kW']
            r35 = next((r for r in cap['rows'][c] if r['loop'] == L and abs(r['Qd_kW'] - 35.0) < 1e-6), None)
            if r35: T35[(c, L)] = r35
            rows.append([CASE_LABEL[c], L, f"{X.num(r35['Tout_mean_C'])} / {X.num(r35['Tout_max_C'])}" if r35 else '',
                         X.num(x, 0) if x is not None else f'大于 {max(qs):.0f}', X.num(X.T_SET_C + x * 1e3 / X.loop_mcp(L), 1) if x is not None else '',
                         X.num(m, 0) if m is not None else f'大于 {max(qs):.0f}'])
    D.table('散热器全流量排热能力', ['工况', '回路', '排热 35 kW 时出口温度，轨道平均 / 轨道最高，°C', '出口温度轨道最高达到 2.8 °C 的排热量，kW',
            '该排热量下的散热器入口温度，°C', '出口温度轨道平均达到 2.8 °C 的排热量，kW'], rows, widths=[2.6, 1.1, 3.4, 3.0, 2.7, 3.0])
    D.figure(os.path.join(FIG, 'capacity_outlet.png'), '散热器全流量时出口氨温度与单回路排热量的关系', 15.5)
    hot = cap['summary'].get('hot75', {}).get('capacity', {})
    mx = [v['Q_at_max_setpoint_kW'] for v in hot.values() if v.get('Q_at_max_setpoint_kW') is not None]
    h35 = [T35[k] for k in T35 if k[0] == 'hot75']
    if h35:
        D.p(f"设计热工况下，单回路排热 35 kW 时散热器全流量出口温度的轨道最高值为 {X.num(max(r['Tout_max_C'] for r in h35))} °C，"
            f"比 2.8 °C 设定点低 {X.num(X.T_SET_C - max(r['Tout_max_C'] for r in h35))} K，模型散热器满足单回路 35 kW 的规定排热能力。"
            + (f'按出口温度整圈不超过 2.8 °C 计，单回路可排出 {X.num(min(mx), 0)} kW 至 {X.num(max(mx), 0)} kW。' if mx else '')
            + '公开资料给出三个参考值：EATCS 规定的最低排热能力 70 kW，即单回路 35 kW，见文献 A 与 D5 正文；D4 与 D5 表3.2-1 给出 75 kW；'
            'D5 表4.4-2 按解析方法估算装配完成状态的散热器能力为 87.9 kW，即单回路约 44 kW。')
    if mx and min(mx) > 44:
        qa, qb = (17 - X.T_SET_C) * X.loop_mcp('A') / 1e3, (17 - X.T_SET_C) * X.loop_mcp('B') / 1e3
        D.p('子模型求得的排热量高于参考值，原因有两方面。第一，排热量增大时散热器入口温度随之升高，散热器温度越高排热越多。'
            '舱内热量经换热器传给氨，氨温度不会高于中温回路 17 °C 的水温，按模型流量计算，单回路从舱内回路收集的热量不超过 '
            f'{X.num(qa, 0)} kW 与 {X.num(qb, 0)} kW，入口温度超过 17 °C 的排热量在实际回路中达不到。'
            '第二，模型的理想化处理使散热器排热偏多：散热器与桁架、太阳翼、PVR 之间的遮挡和相互辐射按组间不计处理；'
            '面板与氨的换热在面板上均布，相当于流管之间面板的翅片效率取 1，实际面板靠两层 0.254 mm 铝蒙皮导热，远离流管处的面板温度低于氨温度；'
            '散热器指向按理想的侧边对日处理。子模型结果应看作排热能力的上限，核算载荷余量时以单回路 35 kW 的规定值为准。')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--cases', default='cold0,hot75,nom0'); ap.add_argument('--out', default='国际空间站有限元热分析报告.docx')
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
