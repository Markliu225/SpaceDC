"""Build reviewable figures and a six-page Chinese result preview from saved evidence."""
import json
import math
import re
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak

HERE=Path(__file__).resolve().parent
OUT=HERE/'results';FIG=HERE/'figures';FIG.mkdir(exist_ok=True)
S=json.loads((OUT/'summary.json').read_text(encoding='utf-8'));C=S['contract']
BLUE='#2364aa';GREEN='#26834a';RED='#d05b31';GRAY='#555555'
plt.rcParams.update({'font.family':'Microsoft YaHei','font.size':10,'axes.unicode_minus':True,
                     'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.22})


def raw(cid,name):
    return np.genfromtxt(OUT/f'{cid}_{name}.csv',delimiter=',',names=True)


def figures():
    for r in S['cases']:
        cid=r['id'];p=raw(cid,'python');s=raw(cid,'simulink');a=raw(cid,'analytic');t=p['time_s']/60
        f,axs=plt.subplots(2,2,figsize=(8.3,5.45),layout='constrained')
        ax=axs[0,0];ax.plot(t,p['current_A'],color=GRAY,lw=1.8)
        ax.axhline(0,color='black',lw=.7);ax.set_title('a  输入电流');ax.set_ylabel('单节电流 / A')
        ax=axs[0,1];ax.plot(t,p['voltage_V'],color=BLUE,lw=1.7,label='现有模型')
        ax.plot(t,a['voltage_series_V'],color=GREEN,lw=1.6,ls='--',label='球形扩散解析解')
        ax.plot(t,s['voltage_V'],color=RED,ls='none',marker='o',mfc='none',ms=3,markevery=max(1,len(t)//28),label='Simulink 同方程')
        ax.set_title('b  输出端电压');ax.set_ylabel('单节电压 / V');ax.legend(fontsize=8,loc='best')
        ax=axs[1,0];ax.plot(t,100*p['soc'],color=BLUE,lw=1.8,label='现有模型积分')
        ax.plot(t,100*a['soc'],ls='none',color='black',marker='o',mfc='none',ms=3,markevery=max(1,len(t)//23),label='独立库仑计数')
        ax.set_title('c  输出荷电状态');ax.set_ylabel('SOC / %');ax.legend(fontsize=8,loc='best')
        ax=axs[1,1];ax.plot(t,p['heat_W']*1000,color='black',label='总发热',lw=1.7)
        ax.plot(t,(p['heat_reaction_W']+p['heat_ohmic_W'])*1000,color=RED,label='反应与欧姆热',lw=1.2)
        ax.plot(t,p['heat_reversible_W']*1000,color=GREEN,label='可逆热',ls='--',lw=1.2)
        ax.axhline(0,color=GRAY,lw=.6);ax.set_title('d  模型输出发热');ax.set_ylabel('单节热功率 / mW');ax.legend(fontsize=8,loc='best')
        for ax in axs.flat:
            ax.set_xlabel('时间 / min');ax.set_xlim(t[0],t[-1]);ax.tick_params(labelsize=9)
        f.savefig(FIG/f'{cid}.png',dpi=190);f.savefig(FIG/f'{cid}.svg');plt.close(f)
    p=raw('BAT-T04','python');a=raw('BAT-T04','analytic');mask=p['segment']==2
    elapsed=p['time_s'][mask]-360
    f,axs=plt.subplots(1,2,figsize=(8.3,3),layout='constrained')
    axs[0].plot(elapsed,p['voltage_V'][mask],color=BLUE,label='现有模型',lw=2)
    axs[0].plot(elapsed,a['voltage_series_V'][mask],color=GREEN,label='球形扩散解析解',lw=2)
    axs[0].set_ylabel('断流后的端电压 / V');axs[0].legend(fontsize=9)
    axs[1].plot(elapsed,1000*(p['voltage_V'][mask]-a['voltage_series_V'][mask]),color='#7044a0',lw=2)
    axs[1].set_ylabel('模型电压 − 扩散参考电压 / mV')
    for ax in axs:ax.set_xlabel('从断流开始的时间 / s');ax.set_xlim(0,1200)
    f.savefig(FIG/'rest_recovery.png',dpi=190);f.savefig(FIG/'rest_recovery.svg');plt.close(f)


pdfmetrics.registerFont(TTFont('Song','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('Hei','C:/Windows/Fonts/simhei.ttf'))
pdfmetrics.registerFont(TTFont('Latin',str(Path(matplotlib.get_data_path())/'fonts/ttf/DejaVuSans.ttf')))
ST={
 'body':ParagraphStyle('body',fontName='Song',fontSize=10,leading=15,spaceAfter=7,wordWrap='CJK'),
 'small':ParagraphStyle('small',fontName='Song',fontSize=8.8,leading=12.5,spaceAfter=5,wordWrap='CJK'),
 'title':ParagraphStyle('title',fontName='Hei',fontSize=19,leading=26,spaceAfter=11),
 'h':ParagraphStyle('h',fontName='Hei',fontSize=13,leading=18,spaceBefore=8,spaceAfter=7),
 'cell':ParagraphStyle('cell',fontName='Song',fontSize=9,leading=12,wordWrap='CJK'),
 'head':ParagraphStyle('head',fontName='Hei',fontSize=9,leading=12,wordWrap='CJK'),
 'caption':ParagraphStyle('caption',fontName='Song',fontSize=9,leading=13,spaceAfter=6,wordWrap='CJK'),
}
W=A4[0]-96


def para(t,style='body'):
    # SimSun lacks the mathematical minus and several Unicode superscript glyphs.
    # Preserve mathematical signs visibly rather than silently embedding blank glyphs.
    t=t.replace('−','<font name="Latin">−</font>')
    sup=str.maketrans('⁰¹²³⁴⁵⁶⁷⁸⁹⁻','0123456789−')
    t=re.sub('[⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+',lambda m:'<super><font name="Latin">'+m.group().translate(sup)+'</font></super>',t)
    return Paragraph(t,ST[style])


def table(rows,widths):
    cells=[[para(str(v),'head' if j==0 else 'cell') for v in row] for j,row in enumerate(rows)]
    t=Table(cells,colWidths=[W*x/sum(widths) for x in widths],repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#ededed')),
        ('GRID',(0,0),(-1,-1),.4,colors.HexColor('#bfc5cb')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6)]))
    return t


def image(path,ratio):return Image(str(path),width=W,height=W*ratio)


def header(canvas,doc):
    canvas.setFont('Song',8)
    canvas.drawString(48,A4[1]-30,'SDTwin Power 电池专项测试结果预览')
    canvas.drawRightString(A4[0]-48,28,f'2026年10月8日    {doc.page}')


PURPOSE={
 'BAT-T01':('确认恒流充电期间的电量增量和电压方向，直接回应原图 3 的疑问。','充电电流接入时端电压升高；随后电压随 SOC 增加而上升。'),
 'BAT-T02':('确认恒流放电期间的电量消耗、端电压方向和发热符号。','放电电流接入时端电压下降；随后电压随 SOC 减少而下降。'),
 'BAT-T03':('检验状态在充电、静置、放电和再次静置间连续传递，并核对闭合循环的电量与能量。','充入和放出的电量相等，最终 SOC 回到 50%。相同物理状态和温度下，总能量账应闭合。'),
 'BAT-T04':('检验短时负载撤去后是否保留颗粒内浓度梯度，以及电压是否继续缓慢恢复。','断流瞬间反应与欧姆压降消失；内部浓度梯度随后逐渐消退，电压继续恢复。'),
}


def verdict(r):
    if r['id']=='BAT-T01':
        return '实际结果：充电接入后电压由 3.78784 V 升至 3.81561 V，再连续升至 3.88959 V；SOC 升至 59.04209%。恒流充电期间没有出现电压下降。接入瞬间与扩散解析解仍相差 5.83 mV。'
    if r['id']=='BAT-T02':
        return '实际结果：接入放电后电压由 3.78784 V 降至 3.76002 V，再连续降至 3.67447 V；SOC 降至 40.95791%。电量、方向和代数计算核对通过。接入瞬间与扩散解析解仍相差 5.88 mV。'
    if r['id']=='BAT-T03':
        return '实际结果：充入与放出均为 0.125 Ah，SOC 回到 50%。但净输入电能 24.88591 J，总发热 19.81064 J，差额 5.07527 J。电量核对通过，按现有状态定义的闭环能量核算未闭合；静置恢复也未被描述。'
    return '实际结果：放出 0.083333 Ah，SOC 降至 46.98597%。断流后扩散参考电压从 3.74919 V 缓慢恢复到 3.76090 V，恢复量 11.71254 mV；现有模型立即跳至 3.76090 V，此后恢复量为 0。静置扩散恢复能力不满足本用例目标。'


def build_pdf():
    story=[para('电池时域测试结果预览','title'),
        para('本次先检查四个单节电池案例。电量积分与充放电方向正确，但已发现两项模型问题：断流后的扩散恢复缺失；等电量闭合循环的电能与发热相差 5.07527 J。因此不能把 Python 与 Simulink 一致解释为电池模型已经验证正确。'),
        para('1 测试对象和环境','h'),
        table([['项目','明确设置'],
            ['对象','仓库 Power 电池方程，改为一串联一并联的单节测试；原实现文件未修改'],
            ['初始状态',f"SOC 50%；负极平均锂占比 {C['initial']['xn']:.6f}，正极 {C['initial']['xp']:.9f}；扩散参考内部浓度均匀"],
            ['环境','电池温度恒定 25°C，由理想恒温边界维持；不涉及轨道、冷热环境或热惯性'],
            ['容量与阻抗',f"可用容量 {C['capacity_Ah']:.9f} Ah；欧姆内阻 0.025 Ω；参数来自仓库示例，未经实物电芯标定"],
            ['输入','单节外部电流随时间的分段函数；正号为放电，负号为充电；开始均静置 60 s'],
            ['输出','端电压、SOC、功率、热功率和能量积分；热功率仅为模型预测，不参与本次恒温状态更新']],[1,4]),
        para('2 时间推进和比较含义','h'),
        para('Python 使用 DOP853，Simulink 使用 ode45，均连续积分两极平均锂占比、端口能量和热量积分。最大内部步长 2 s，相对容差 10⁻⁹，绝对容差 10⁻¹¹。每秒导出一次结果，电流切换时保留同一时刻的左右值，状态接续且不重置。','small'),
        para('Simulink 执行的是独立 MATLAB 编写的同一组方程，可检查实现一致性。球形扩散参考保留颗粒浓度分布，用 200 项特征函数解析解计算表面浓度，并以 128 和 256 层有限体积网格复核。它检验的是表面浓度近似；两者都不是实测电芯数据，也不是 Simscape Battery 标准库电芯。','small'),
        para('3 原图 3 为什么会误导','h'),
        para('原 BT-002 前四点保持温度 0°C、两极平均锂占比 0.6 和 0.458686 不变，依次改变电流。它是独立静态工况扫描，不是充电时间曲线。将这些点连线放进动态验证叙述，不能证明充电过程正确。此前 DY 类案例确有状态积分，不能将其与这张静态图混为一谈。','small'),
        table([['独立点','电流 A','原图电池组电压 V'],['1','−1','32.089386'],['2','−0.5','31.700407'],['3','0','31.295597'],['4','0.5','30.891219']],[1,1,2]),
        para('此处原图使用八串联电池组；后面四项新测试全部为单节电池。','small')]
    for idx,r in enumerate(S['cases'],1):
        cid=r['id'];purpose,expected=PURPOSE[cid]
        story += [PageBreak(),para(f'{cid}  {r["title"]}','title'),
            para('测试目的：'+purpose),para('前置条件：沿用第 1 页统一条件；本案例从初始 SOC 50% 独立开始。','small'),
            para('输入和实际输出如下。起点电压指该段电流已施加后的右侧值；上一段终值保留切换前的左侧值。','small')]
        rows=[['时间 s','输入电流 A','起点电压 V','终点电压 V','终点 SOC %']]
        for seg in r['segments']:
            rows.append([f"{seg['start_s']} 至 {seg['end_s']}",str(seg['current_A']).replace('-','−'),
                         f"{seg['voltage_start_V']:.5f}",f"{seg['voltage_end_V']:.5f}",f"{seg['soc_end']*100:.5f}"])
        story += [table(rows,[1.4,1.1,1.2,1.2,1.3]),Spacer(1,6),
            image(FIG/f'{cid}.png',5.45/8.3),
            para(f'图 {idx}  横轴均为真实仿真时间。a 为输入，b 为三种计算的电压，c 为模型 SOC 与库仑计数，d 为现有模型的热量分解。红圈仅稀疏显示 Simulink 标记，计算使用完整时间序列。','caption'),
            para('预期结果：'+expected,'small'),para(verdict(r),'body'),
            para(f"执行记录：Python 接受 {r['python_accepted_steps']} 个内部积分步，调用导数 {r['python_derivative_evaluations']} 次；Simulink 调用导数 {r['simulink_derivative_evaluations']} 次。该案例导出 {r['output_rows']} 行，包含切换左右值。",'small')]
    maxerr=lambda name:max(x['value'] for x in S['checks'] if x['check']==name)
    story += [PageBreak(),para('核算结果和需要修正的问题','title'),
        para('数值检查通过不等于物理完整性通过。按固定数值容差执行的积分、库仑计数、锂守恒、代数分解、Simulink 对照和扩散基准精度检查共 85 项，全部通过。循环能量闭合属于随后增加的物理诊断，单独列出，不并入这 85 项。'),
        table([['核查项目','四项案例中的最大误差','判据'],
            ['SOC 与库仑计数',f"{maxerr('analytic SOC'):.3g}",'≤ 10⁻⁹'],
            ['总锂库存相对误差',f"{maxerr('lithium inventory relative'):.3g}",'≤ 10⁻¹⁰'],
            ['Python 与 Simulink 电压',f"{maxerr('Simulink voltage V'):.3g} V",'≤ 10⁻⁶ V'],
            ['端口能量与独立积分',f"{maxerr('port energy independent quadrature J'):.3g} J",'≤ 10⁻⁵ J'],
            ['扩散参考网格加密变化',f"{max(r['mesh_change_mV'] for r in S['cases']):.5f} mV",'≤ 0.1 mV'],
            ['256 层网格与解析解',f"{maxerr('FV versus exact sphere series V')*1000:.5f} mV",'≤ 0.1 mV']],[2.5,2.3,1.3]),
        para('问题一  断流后没有扩散恢复','h'),
        para('现有模型只保存平均锂占比，表面锂占比由当前电流代数求得。电流变为零时，表面值立即等于平均值，浓度梯度的历史被丢弃。下面只放大 BAT-T04 的静置段，右图严格由左图两条曲线逐点相减。','small'),
        image(FIG/'rest_recovery.png',3/8.3),
        para('问题二  现有状态定义下的循环能量未闭合','h'),
        para('BAT-T03 返回相同的两极平均锂占比和温度，故现有模型所声明的物理状态闭合。输入电能 1725.66540 J，输出电能 1700.77949 J，净输入 24.88591 J；热量输出只有 19.81064 J，残差为 5.07527 J。该残差远高于独立积分误差。','small'),
        para('从现有公式可进一步核算：平均浓度与表面浓度之间的电势差对应积分 5.15795 J，可逆热的全循环积分为 0.08268 J，两者相减正好给出上述残差。这说明目前电压和热源公式未形成完整能量账；不能直接把差额全部加到热源后宣称修复。需要先统一扩散状态、储能和热源的热力学定义。','small'),
        para('复核材料：results/contract.json 固定输入与判据；各 CSV 保存原始轨迹；accepted_steps 与 simulink_derivatives 保存步进证据；summary.json 保存逐项结果。复现入口及全部材料参数见本目录 README.md。原模型和原报告未修改。','small'),
        para('参考：MathWorks Battery Single Particle 文档说明球形颗粒扩散方程及表面浓度求解；Examine Effects of Diffusion Coefficient and Volume Fraction 文档说明负载撤去后的扩散恢复。这里只借用对应物理定义，不将本计算冒充官方标准电芯运行结果。','small')]
    doc=SimpleDocTemplate(str(HERE/'Battery_Time_Domain_Preview_CN.pdf'),pagesize=A4,
        leftMargin=48,rightMargin=48,topMargin=48,bottomMargin=43,title='电池时域测试结果预览',author='SDTwin Power verification')
    doc.build(story,onFirstPage=header,onLaterPages=header)


def markdown():
    lines=['# 电池专项时域测试','',
      '本次只做四项电池案例，原模型和原报告保留。结果显示：电量积分和充放电方向符合预期，但现有模型缺少断流后的扩散恢复，而且等电量闭合循环的能量账不闭合。Python 与 Simulink 一致不能证明这些物理能力已经验证。','',
      '[六页结果预览](Battery_Time_Domain_Preview_CN.pdf)','',
      '## 共同设置','',
      f"单节电池，一串联一并联。电池温度固定 298.15 K，即 25°C，理想恒温边界维持温度。初始 SOC 50%，负极平均锂占比 {C['initial']['xn']:.12g}，正极 {C['initial']['xp']:.12g}。扩散参考以均匀浓度开始。电流正号表示放电，负号表示充电。所有场景开始先静置 60 s。",
      f"可用容量为 {C['capacity_Ah']:.12g} Ah，来自 Qn × 0.87 / 3600。Qn 为 {C['electrode_capacity_C']['n']:.12g} C，Qp 为 {C['electrode_capacity_C']['p']:.12g} C，单节欧姆内阻为 0.025 Ω。材料参数沿用仓库示例，未标定到真实电芯。本测试不含充电器、太阳阵、PDU 或轨道。",'',
      '输入为每段外部指定电流和持续时间。输出为单节端电压、SOC、功率、发热、端口电能和热量积分。正端口功率表示电池对外供电；正热功率表示发热，负可逆热表示吸热。恒温测试中的热量是输出，不用于推进温度。', '',
      '## 三种计算的职责','',
      '1. 仓库模型：调用 `Thermal/sdtwin_sim/power_stand_in.py:battery_response`，由 SciPy DOP853 连续积分两极平均锂占比、端口能量和热量积分。',
      '2. Simulink：真实运行 `matlab/sdtwin_battery_time_validation.slx`，ode45 连续积分同四个状态；独立 MATLAB 方程不调用 Python。它检验同方程实现的一致性，不是 Simscape Battery 官方电芯模型。',
      '3. 扩散参考：求解球形颗粒 Fick 扩散，保留内部浓度状态。采用特征函数解析解和独立的径向有限体积方法相互核对；它沿用相同 OCP 和反应动力学参数，仅增加固相扩散记忆，不包含完整电解液模型或实物测量。','',
      '最大积分步长 2 s，rtol = 1e-9，atol = 1e-11，结果每 1 s 导出。积分器内部实际步长和导数调用单独保存，导出点不等于积分步。只在预定电流切换处分段；每段用上一段的终值继续，切换时保留时间相同但电流不同的左右两行。','',
      '## 案例和实际结果','',
      '| 案例 | 电流时序 | 最终 SOC | 主要结果 |','|---|---|---:|---|',
      '| BAT-T01 | 0 至 60 s 为 0 A；60 至 1860 s 为 −0.5 A | 59.04209% | 充电接入后电压升至 3.81561 V，再升至 3.88959 V |',
      '| BAT-T02 | 0 至 60 s 为 0 A；60 至 1860 s 为 +0.5 A | 40.95791% | 放电接入后电压降至 3.76002 V，再降至 3.67447 V |',
      '| BAT-T03 | 0 至 60 s 静置；60 至 960 s 为 −0.5 A；960 至 1260 s 静置；1260 至 2160 s 为 +0.5 A；2160 至 3060 s 静置 | 50.00000% | 充放电各 0.125 Ah；能量残差 5.07527 J |',
      '| BAT-T04 | 0 至 60 s 静置；60 至 360 s 为 +1 A；360 至 1560 s 静置 | 46.98597% | 断流后的扩散参考恢复 11.71254 mV，现有模型恢复 0 mV |','']
    for r in S['cases']:
        cid=r['id'];lines += [f"### {cid} {r['title']}",'',f'测试目的：{PURPOSE[cid][0]}',f'预期：{PURPOSE[cid][1]}','',
            f'![{cid} 电流 电压 SOC 热功率](figures/{cid}.png)','',
            '图中 a 为输入电流，b 为电压输出，c 为 SOC 输出与独立库仑计数，d 为模型热源分解。蓝线为仓库模型，红色圆圈为 Simulink 同方程结果，绿虚线为球形扩散解析解。只对显示标记稀疏抽取，数值比较采用全部输出时刻。电压与热功率在切换时可跳变，平均锂占比和 SOC 连续。','',
            verdict(r),'',
            f"端口输入电能 {r['energy_input_Wh']:.8f} Wh，输出电能 {r['energy_output_Wh']:.8f} Wh；模型热量积分 {r['heat_integral_J']:.8f} J。Python 接受 {r['python_accepted_steps']} 个内部步，导数调用 {r['python_derivative_evaluations']} 次；Simulink 导数调用 {r['simulink_derivative_evaluations']} 次。",'']
    lines+=['## 物理核算','',
      '库仑计数：`SOC(t) = 0.5 − ∫I dt / (3600 × capacity_Ah)`。总锂库存 `Qn xn + Qp xp` 必须恒定。状态变化率为 `dxn/dt = −I/Qn` 和 `dxp/dt = I/Qp`。',
      '端电压分解：`V = Up(surface) − Un(surface) − activation − I R`。热量分解：`q = I × activation + I² R − I T beta`。反应热和欧姆热均应非负，可逆热允许正负。独立自适应积分核算端口电能和热量，不把分解恒等式误称为热力学能量守恒。','',
      '等电量循环回到相同平均锂占比和温度，现有模型没有其他物理储能状态。净电输入为 24.88591096 J，报告发热为 19.81064049 J，残差 5.07527047 J。进一步分解得到 `∫I[Umean − Usurface]dt = 5.15795419 J`，`∫qrev dt = 0.08268372 J`，相减等于该残差。循环能量账没有闭合。该诊断是执行后追加的物理检查，不混入预先冻结的 85 项数值检查，也不通过改阈值将其判成通过。','',
      '脉冲断流后，现有模型将表面浓度立即设为平均浓度，失去扩散历史。参考模型保持浓度分布，因此电压有 11.71254 mV 的慢恢复。这是动态能力缺失，不能由同一方程的 Simulink 对照消除。','',
      '![静置恢复电压及逐点差值](figures/rest_recovery.png)','',
      '此图右侧是左侧现有模型电压减去扩散解析电压，同一时间轴和同一数据，不使用不同工况或不同采样点。','',
      '## 扩散参考的独立核对','',
      '球形扩散方程为 `∂x/∂t = (D/R²) ρ⁻² ∂ρ(ρ² ∂ρx)`，中心导数为零，表面导数为 `m R²/(3D)`，其中 m 为该极平均锂占比变化率。对均匀初值和单位 m 阶跃，表面增量为 `h(t) = t + 1/(15a) − 2/(3a) Σ exp(−a λk² t)/λk²`，`a = D/R²`，`tan λk = λk`。采用前 200 个非零根，t = 0 使用精确极限 0，各电流阶跃按线性叠加计算。',
      '有限体积独立计算使用 128 和 256 层球壳，对通量和球壳体积守恒离散，分段常电流下采用矩阵指数精确时间推进。表面值由最外两层体积平均值和表面通量二次重建。网格加密的最大电压变化 0.079244 mV，256 层与解析解最大差 0.079403 mV，均满足执行前固定的 0.1 mV 精度要求。与 11.71 mV 的缺失恢复相比，该误差很小。','',
      '[MathWorks 球形单颗粒扩散模型定义](https://www.mathworks.com/help/simscape-battery/ref/batterysingleparticle.html)；[MathWorks 扩散与电压恢复示例](https://www.mathworks.com/help/simscape-battery/ug/examine-effect-diffusion-coefficient-and-volume-fraction-on-terminal-voltage.html)。解析展开和有限体积代码是本仓库的独立计算，不宣称运行了官方电芯组件。','',
      '## 材料参数','',
      '| 参数 | 负极 | 正极 |','|---|---:|---:|']
    es=C['parameters']['battery']['electrodes']
    for key in ['D_ref_m2_s','radius_m','I0_ref_A','active_fraction','electrode_area_m2','thickness_m','c_max_mol_m3','E_D_J_mol','E_I_J_mol','b_V','d_V_K']:
        lines.append(f"| {key} | {es['n'][key]} | {es['p'][key]} |")
    lines+=['','OCP 多项式和温度系数均按常数项在前排列；本次 T = Tref，温度激活因子为 1。材料参数、运行界限、初值、全部输入和判据保存在 contract.json，测试不拟合或修改这些参数。','',
      '## 复现和数据','',
      '在仓库根目录执行：','',
      '```powershell',
      '& ./Thermal/.venv/Scripts/python.exe Power/battery_validation/run_battery.py',
      '& "C:/Program Files/MATLAB/R2026b/bin/matlab.exe" -batch "addpath(\'C:/Workspace/SpaceDC/Power/battery_validation/matlab\'); run_battery_simulink"',
      '& ./Thermal/.venv/Scripts/python.exe Power/battery_validation/analyze.py',
      '```','',
      '图和 PDF 由 `build_preview.py` 从原始结果生成，需要 matplotlib 和 reportlab。执行环境见 python_execution.json 与 simulink_execution.json。保存的 SLX 默认展示从 50% SOC 直接施加 −0.5 A 的单段检查；完整四案例含初始静置的时序由 run_battery_simulink.m 驱动。','',
      '| 文件 | 内容 |','|---|---|',
      '| results/contract.json | 执行前冻结的参数、输入时序和数值判据 |',
      '| results/BAT-T0x_python.csv | 模型全部输出，含电压和热源各分量 |',
      '| results/BAT-T0x_simulink.csv | Simulink 独立积分结果 |',
      '| results/BAT-T0x_accepted_steps.csv | Python 实际接受的内部步时刻及积分状态 |',
      '| results/BAT-T0x_simulink_derivatives.csv | Simulink 导数求值时刻，可重复或回退，不冒充接受步 |',
      '| results/BAT-T0x_diffusion_128.csv 和 diffusion_256.csv | 两种网格的独立扩散求解 |',
      '| results/BAT-T0x_analytic.csv | 精确库仑计数和球形扩散解析参考 |',
      '| results/summary.json | 85 项数值检查、各段结果和两个物理问题 |','',
      '原图 3 数据审计：BT-002 前几项在 0°C 和固定平均锂占比下改变电流，不是时间推进。八串联电池组电压依次为 32.089386、31.700407、31.295597、30.891219 V，对应电流 −1、−0.5、0、0.5 A。原报告 DY 类用例确有积分，但该静态图不能用于证明恒流充电过程正确。','']
    (HERE/'README.md').write_text('\n'.join(lines),encoding='utf-8')


if __name__=='__main__':
    figures();build_pdf();markdown();print('Preview and figures written.')
