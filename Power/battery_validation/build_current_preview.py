"""Current full-cycle and second-scale deliverable; all content derived from saved evidence."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Image,Spacer,PageBreak

HERE=Path(__file__).resolve().parent;OUT=HERE/'results';FULL=OUT/'full_cycles';FIG=HERE/'figures'
S=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
F=json.loads((FULL/'summary.json').read_text(encoding='utf-8'));C=F['contract'];CY=F['cycles'][0]
BLUE='#245ca7';GREEN='#27814d';RED='#ce4d58'
plt.rcParams.update({'font.family':'Microsoft YaHei','font.size':10,'axes.unicode_minus':True,
 'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.2})
def read(path):return np.genfromtxt(path,delimiter=',',names=True)
def output(fig,name):
    fig.savefig(FIG/f'{name}.png',dpi=200);fig.savefig(FIG/f'{name}.svg');plt.close(fig)

def figures():
    FIG.mkdir(exist_ok=True)
    f,ax=plt.subplots(figsize=(8.7,4.75),layout='constrained')
    for k,color in enumerate(['#111111',RED,BLUE]):
        for j in [2*k+1,2*k+2]:
            d=read(FULL/f'segment_{j}_python.csv')
            ax.plot(d['capacity_Ah'],d['voltage_V'],color=color,lw=[2.7,1.8,1.1][k],
                ls=['-','--',':'][k],label=f'第 {k+1} 圈' if j%2 else None)
            if k<2:
                ix=np.arange(1500+1000*k,len(d),4500)
                ax.plot(d['capacity_Ah'][ix],d['voltage_V'][ix],ls='none',marker=['o','s'][k],
                    color=color,ms=4,mfc='white',mew=.8,zorder=5)
    ax.set_xlabel('每个充电或放电分支的累计容量 / Ah',fontsize=12)
    ax.set_ylabel('单节端电压 / V',fontsize=12);ax.set_xlim(0,C['capacity_Ah']*1.02)
    ax.set_ylim(3.0,4.25);ax.legend(loc='center right',fontsize=10)
    ax.text(.05,3.19,'充电起点');ax.text(.05,4.04,'放电起点')
    ax.text(1.45,3.20,'0.1C，25°C\n三圈曲线重合',fontsize=12)
    output(f,'full_voltage_capacity')
    f,axs=plt.subplots(3,1,figsize=(8.7,5.0),sharex=True,layout='constrained')
    for j in [1,2]:
        d=read(FULL/f'segment_{j}_python.csv');s=read(FULL/f'segment_{j}_simulink.csv')
        axs[0].plot(d['time_s'],d['current_A'],color='#555555',lw=1.6)
        axs[1].plot(d['time_s'],d['voltage_V'],color=BLUE,lw=1.6,label='现有模型' if j==1 else None)
        axs[1].plot(s['time_s'][::1600],s['voltage_V'][::1600],ls='none',marker='o',mfc='none',ms=3,color=RED,label='Simulink' if j==1 else None)
        axs[2].plot(d['time_s'],d['soc']*100,color=BLUE,lw=1.6)
    a=read(FULL/'segment_1_python.csv');b=read(FULL/'segment_2_python.csv')
    for j,field in enumerate(['current_A','voltage_V']):
        axs[j].plot([a['time_s'][-1],b['time_s'][0]],[a[field][-1],b[field][0]],color='#555555' if j==0 else BLUE,lw=1)
    for ax,label in zip(axs,['输入电流 / A','输出电压 / V','SOC / %']):ax.set_ylabel(label)
    axs[1].legend(fontsize=8);axs[2].set_xlabel('真实仿真时间 / s')
    axs[2].set_xticks([0,18000,36000,54000,72000]);axs[2].set_xlim(0,72000)
    output(f,'full_cycle_time_seconds')
    f,axs=plt.subplots(2,2,figsize=(8.7,5.3),layout='constrained')
    for r,ax in zip(S['cases'],axs.flat):
        d=read(OUT/f'{r["id"]}_python.csv');a=read(OUT/f'{r["id"]}_analytic.csv')
        ax.plot(d['time_s'],d['voltage_V'],color=BLUE,lw=1.5,label='现有模型')
        ax.plot(d['time_s'],a['voltage_series_V'],color=GREEN,lw=1.4,ls='--',label='球形扩散解析解')
        ax.set_title(r['id']+'  '+r['title'],fontsize=10);ax.set_xlabel('时间 / s');ax.set_ylabel('电压 / V')
        ax.set_xlim(0,30);ax.legend(fontsize=8)
    output(f,'second_scale_four_cases')
    d=read(OUT/'BAT-T04_python.csv');a=read(OUT/'BAT-T04_analytic.csv');mask=d['segment']==2;t=d['time_s'][mask]-7
    f,axs=plt.subplots(1,2,figsize=(8.7,2.85),layout='constrained')
    axs[0].plot(t,d['voltage_V'][mask],color=BLUE,label='现有模型',lw=1.7)
    axs[0].plot(t,a['voltage_series_V'][mask],color=GREEN,label='球形扩散解析解',lw=1.7)
    axs[0].set_ylabel('单节端电压 / V');axs[0].legend(fontsize=8)
    axs[1].plot(t,1000*(d['voltage_V'][mask]-a['voltage_series_V'][mask]),color='#714796',lw=1.7)
    axs[1].set_ylabel('模型电压 − 扩散参考电压 / mV')
    for ax in axs:ax.set_xlim(0,23);ax.set_xlabel('断流后的时间 / s')
    output(f,'rest_recovery_seconds')

pdfmetrics.registerFont(TTFont('Song','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('Hei','C:/Windows/Fonts/simhei.ttf'))
pdfmetrics.registerFont(TTFont('Latin',str(Path(matplotlib.get_data_path())/'fonts/ttf/DejaVuSans.ttf')))
ST={n:ParagraphStyle(n,fontName=font,fontSize=size,leading=lead,spaceAfter=space,wordWrap='CJK')
    for n,font,size,lead,space in [('body','Song',10,15,7),('small','Song',8.8,12.5,6),
        ('title','Hei',18,25,10),('h','Hei',12,17,7),('cell','Song',9,12,0),('head','Hei',9,12,0)]}
W=A4[0]-96
def p(text,style='body'):
    text=text.replace('−','<font name="Latin">−</font>')
    return Paragraph(text,ST[style])
def tab(rows,widths):
    t=Table([[p(str(v),'head' if i==0 else 'cell') for v in r] for i,r in enumerate(rows)],
        colWidths=[W*v/sum(widths) for v in widths],repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.HexColor('#bcc3ca')),
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eceff2')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]));return t
def pic(name,ratio):return Image(str(FIG/f'{name}.png'),width=W,height=W*ratio)
def footer(can,doc):
    can.setFont('Song',8);can.drawString(48,A4[1]-30,'SDTwin Power 电池充放电测试')
    can.drawRightString(A4[0]-48,27,f'2026年10月8日    {doc.page}')
SCHEDULES=[
 ['BAT-T01','0 至 2 s 静置；2 至 22 s 为 −0.5 A；22 至 30 s 静置'],
 ['BAT-T02','0 至 2 s 静置；2 至 22 s 为 +0.5 A；22 至 30 s 静置'],
 ['BAT-T03','0 至 2 s 静置；2 至 12 s 为 −0.5 A；12 至 15 s 静置；15 至 25 s 为 +0.5 A；25 至 30 s 静置'],
 ['BAT-T04','0 至 2 s 静置；2 至 7 s 为 +1 A；7 至 30 s 静置']]

def make_pdf():
    story=[p('电池完整充放电与秒级瞬态测试','title'),
        p('采用仓库现有参数，完成 0.1C 三个连续充放电循环，并补充四个 30 秒瞬态案例。主图按每个分支累计充入或放出的电量绘制。现有模型可以生成完整曲线，但三圈重合，且能量账没有闭合。'),
        tab([['条件','数值与含义'],
            ['电池与环境','单节电池，一串联一并联，温度恒定 25°C；使用示例材料参数，未经实测标定'],
            ['电流与容量',f"0.1C 对应 {C['current_magnitude_A']:.9f} A；可用容量 {C['capacity_Ah']:.9f} Ah"],
            ['时间推进','完整循环最大积分步长 1 s，每 1 s 输出；秒级瞬态最大步长和输出间隔均为 0.01 s'],
            ['初值与顺序','完整循环从 SOC 100% 开始，先放电再充电，连续执行三圈；只重置分支容量计数的原点'],
            ['停止条件','放电先到 SOC 0% 或 3.0 V 即停止；充电先到 SOC 100% 或 4.2 V 即停止。本参数下先到 SOC 边界']],[1,4]),Spacer(1,8),
        pic('full_voltage_capacity',4.75/8.7),
        p('图 1  完整恒流充放电曲线。上升分支为充电，下降分支为放电。横轴分别从各分支开始计量，所以相同横坐标通常不表示相同 SOC。三圈结果重合，以线型和稀疏标记区分，未人为添加首圈损失或偏移。','small'),
        p('横轴使用单节容量 Ah。材料活性质量未知，不能换算为 mAh/g。0.1C 每个完整分支持续约 36000 s；秒级指实际积分和输出分辨率。曲线形状由当前三次 OCP 多项式与极化公式决定，未标定到示例实验图中的平台或首圈变化。','small')]
    story += [PageBreak(),p('完整充电 放电与连续循环的结果','title'),
        tab([['案例','输入与初值','实际输出'],
            ['FC-01 恒流放电','SOC 100%；+0.276485 A，直到 SOC 0%',f"容量 {C['capacity_Ah']:.6f} Ah；端电压 4.14411 至 3.07355 V；输出 {CY['output_Wh']:.6f} Wh"],
            ['FC-02 恒流充电','接续前段 SOC 0%；−0.276485 A，直到 SOC 100%',f"容量 {C['capacity_Ah']:.6f} Ah；端电压 3.12257 至 4.17882 V；输入 {CY['input_Wh']:.6f} Wh"],
            ['FC-03 连续三圈','以上两分支连续执行三遍，物理状态和能量积分接续','三圈容量和电压曲线重合；返回同一 SOC 和温度，但总能量账不闭合']],[1.1,2,2.4]),Spacer(1,8),
        pic('full_cycle_time_seconds',5/8.7),
        p('图 2  第一圈的真实时间推进。上图为输入电流，中图为端电压，下图为 SOC。36000 s 处由放电切换为充电，电压立即上跳，SOC 连续。红圈为真正运行的 Simulink 结果，只有显示标记作了稀疏抽取。','small'),
        p('相同 SOC 下的充放电电压差','h'),
        p(f"SOC 50% 时，充电电压 {F['midpoint']['charge_voltage_V']:.6f} V，放电电压 {F['midpoint']['discharge_voltage_V']:.6f} V，相差 {F['midpoint']['gap_mV']:.5f} mV。其中欧姆项 {F['midpoint']['ohmic_gap_mV']:.5f} mV，反应项 {F['midpoint']['reaction_gap_mV']:.5f} mV，表面浓度对应电势差 {F['midpoint']['surface_ocp_gap_mV']:.5f} mV。这是电流引起的电压差，不代表模型已有滞回记忆。",'small'),
        p('判定：恒流方向、累计容量和连续状态推进核算通过；首圈差异不在现有模型能力内。测试驱动在 SOC 边界主动切换，本次不验证 PDU 满充禁止充电保护。','small')]
    story += [PageBreak(),p('秒级接入 切换与断流测试','title'),
        p('四项均独立从 SOC 50%、25°C 开始，观察电流接入和断流后的瞬态。输入由下表规定；输出为电压、SOC、热功率和能量积分。图中比较电压，完整输出保存在 CSV。'),
        tab([['案例','输入电流时序','最终 SOC']] + [[r[0],r[1],f"{S['cases'][i]['soc_final']*100:.6f}%"] for i,r in enumerate(SCHEDULES)],[1,4.2,1.3]),Spacer(1,8),
        pic('second_scale_four_cases',5.3/8.7),
        p('图 3  四项秒级电压响应，横轴均为秒。蓝线为现有模型，绿虚线为保留固相扩散状态的参考。最大积分步长 0.01 s，切换时保留左右值；两极平均锂占比没有重置。','small'),
        p('预期与实际','h'),
        p('充电和放电的电量变化符合库仑计数，接入后的电压方向正确。充放电各 10 s 后 SOC 返回 50%。但短时接入和断流阶段，代数表面浓度近似与扩散参考存在差异；静置段现有模型给出水平线，未描述扩散恢复。','small'),
        p('扩散参考共用材料参数、OCP 和反应动力学，仅扩散状态处理不同。采用 1000 项球形扩散解析展开，另用 128 和 256 层有限体积网格核对，不是实测数据。','small')]
    pulse=S['cases'][3]['rest_recovery'];vmax=max(r['simulink_max_voltage_error_V'] for r in F['segments'])
    mesh=max(x['value'] for x in S['checks'] if x['check']=='FV versus exact sphere series V')*1000
    story += [PageBreak(),p('查出的模型问题与核算证据','title'),
        p('问题一  电流撤去后缺少扩散恢复','h'),
        p(f"BAT-T04 在 7 s 断流。模型立即回到 {pulse['project_start_V']:.6f} V，此后不变；扩散参考从 {pulse['diffusion_start_V']:.6f} V 恢复到 {pulse['diffusion_end_V']:.6f} V，23 s 内恢复 {pulse['diffusion_mV']:.5f} mV，且尚未完全平衡。",'small'),
        pic('rest_recovery_seconds',2.85/8.7),
        p('图 4  放大断流后的 23 s。右图严格由左图蓝线减绿线，按同一时刻逐点计算。现有模型的表面浓度只依赖当前电流与平均浓度，断流时丢失梯度历史。','small'),
        p('问题二  完整闭合循环的能量账不闭合','h'),
        tab([['第一圈能量项','实际数值'],['外部输入电能',f"{CY['input_Wh']*3600:.6f} J"],
            ['对外输出电能',f"{CY['output_Wh']*3600:.6f} J"],['净输入电能',f"{CY['net_input_J']:.6f} J"],
            ['模型给出的总发热',f"{CY['heat_J']:.6f} J"],['未闭合差额',f"{CY['unclosed_energy_J']:.6f} J"]],[3,2]),Spacer(1,6),
        p('每圈结束时，两极平均锂占比和温度均返回初值，现有模型没有其他物理储能状态。按此状态定义，净输入电能应等于总热量；差额说明电压与热源公式未形成完整能量账。不能把差额直接补入热源后宣称完成修复。','small'),
        p('计算检查与结论边界','h'),
        p(f"完整循环 54 项数值检查和秒级案例 87 项数值检查均通过。完整循环 Python 与 Simulink 最大电压差 {vmax:.3g} V；扩散网格与解析解最大差 {mesh:.5f} mV。检查包括库仑计数、锂守恒、积分步长、状态接续和独立能量积分。",'small'),
        p('Simulink 使用真实连续 State-Space 和 Integrator 模块及独立搭建的材料方程，检验实现一致性，不是 Simscape Battery 官方电芯或实验标定。数值一致不能消除上述物理问题。参数、原始轨迹、积分步记录、SLX 和复现命令见 README.md。','small')]
    SimpleDocTemplate(str(HERE/'Battery_Time_Domain_Preview_CN.pdf'),pagesize=A4,leftMargin=48,rightMargin=48,topMargin=48,bottomMargin=43,
        title='电池完整充放电与秒级瞬态测试',author='SDTwin Power verification').build(story,onFirstPage=footer,onLaterPages=footer)

def make_readme():
    lines=['# 电池完整充放电与秒级瞬态测试','',
      '[四页结果预览](Battery_Time_Domain_Preview_CN.pdf)','',
      '主测试按用户参考图组织为电压与容量的完整恒流曲线。使用仓库现有参数查问题，没有拟合实验图或人为添加首圈损失。完整循环以最大 1 s 步长推进，同时补充最大 0.01 s 步长的四个 30 s 瞬态案例。原模型和原报告未修改；旧分钟级结果仅留在 minute_scale_archive 中。','',
      '## 完整循环输入与输出','',
      f"单节电池，一串联一并联，温度恒定 25°C。可用容量 {C['capacity_Ah']:.12g} Ah，0.1C 外加电流幅值 {C['current_magnitude_A']:.12g} A，正号放电，负号充电。初始 SOC 100%，负极平均锂占比 {C['initial_xn']:.12g}，正极 {C['initial_xp']:.12g}。",
      '从满电先放电至 SOC 0%，再充电至 SOC 100%，连续三圈。电压附加边界为 3.0 V 和 4.2 V，先到边界即停止。本参数下六个分支均先到 SOC 边界，持续约 36000 s。外部测试驱动负责边界切换，不验证原 PDU 满充保护。',
      '最大步长 1 s，每 1 s 输出，rtol = 1e-9，atol = 1e-11。Python RK45 和 Simulink ode45 分别积分平均锂占比、端口电能和热量。物理状态连续接续，只重置画图用的分支容量原点。容量为 abs(积分电流)/3600，单位 Ah。横轴同一容量通常不代表相同 SOC。活性材料质量未知，不换成 mAh/g。输出包括端电压、SOC、电功率、发热和能量积分。','',
      'Python 用 SOC 和电压事件定位终点。Simulink 针对这组恒流参数在理论 SOC 终点 36000 s 分段，电压边界按完整输出离线核对；本组轨迹始终位于 3.0 至 4.2 V 内。该 Simulink 模型不是通用电压截止控制器。','',
      '![完整充放电曲线](figures/full_voltage_capacity.png)','',
      '| 案例 | 输入 | 实际结果 |','|---|---|---|',
      '| FC-01 恒流放电 | SOC 100%，+0.276485 A | 4.144107 至 3.073552 V，放出 2.764847495 Ah |',
      '| FC-02 恒流充电 | 接续 SOC 0%，−0.276485 A | 3.122570 至 4.178817 V，充入 2.764847495 Ah |',
      '| FC-03 连续三圈 | 两个分支连续执行三遍 | 三圈重合，差异仅为数值舍入，没有首圈损失或老化模型 |','',
      '黑色第一圈，红色第二圈，蓝色第三圈，以线型和稀疏空心标记区分重合，没有人为偏移。上升曲线为充电，下降曲线为放电。','',
      '![第一圈真实秒级推进](figures/full_cycle_time_seconds.png)','',
      '图中电流、电压和 SOC 都以秒为时间轴。36000 s 时电流切换，电压允许跳变，SOC 和平均浓度连续。0.1C 一个完整分支约 36000 s，秒级分辨率不能把物理充放电压缩为 30 s。','',
      '## 秒级输入与结果','',
      '四项独立从 SOC 50%、25°C 和均匀浓度分布开始。外部指定电流，理想恒温边界维持温度；热量为输出，不更新温度。最大步长和输出间隔均为 0.01 s；切换保留同一时刻的左右两行，状态接续。','',
      '| 案例 | 输入电流时序 | 最终 SOC |','|---|---|---|']
    for k,r in enumerate(SCHEDULES):lines.append(f"| {r[0]} | {r[1]} | {S['cases'][k]['soc_final']*100:.6f}% |")
    lines += ['','![四项秒级案例](figures/second_scale_four_cases.png)','',
      '每个子图横轴为秒，纵轴为单节端电压。蓝线为现有模型，绿线为独立固相扩散参考。充放电方向和电量通过核对；短时接入和断流显示代数表面浓度近似缺少扩散记忆。','',
      '## 已确认的问题','',
      '1. 模型仅保存平均浓度，表面浓度由当前电流直接计算。5 s 脉冲撤去后，模型立即平衡，随后恢复 0 mV；扩散参考在 23 s 内恢复 2.51815 mV，尚未完全平衡。',
      f"2. 完整循环回到相同平均锂占比和温度，但净输入 {CY['net_input_J']:.9f} J，发热 {CY['heat_J']:.9f} J，差额 {CY['unclosed_energy_J']:.9f} J。现有模型未声明其他物理储能状态，能量账没有闭合。",
      '3. 没有副反应、活性锂损失、老化和滞回状态，所以不能生成首圈不可逆容量和逐圈演化。重合由模型结构决定，不能为模仿参考图把曲线画开。',
      '4. OCP 使用示例三次多项式，未标定真实材料，不声称复现参考图的平台和比容量。','',
      '![断流后电压及逐点差](figures/rest_recovery_seconds.png)','',
      '右侧按相同时间的蓝线减绿线计算。热量分解为 I×反应过电压 + I²R − ITbeta，可逆热允许负值。分解恒等式成立不等于完整热力学能量守恒。','',
      '## 数值核对与物理边界','',
      '独立库仑计数核对 SOC = SOC0 − 积分电流/(3600×容量)。总锂库存 Qn xn + Qp xp 应守恒。端口电能和热量沿解析平均浓度轨迹用独立自适应求积复核。完整循环 54 项数值检查通过，秒级案例 87 项通过；物理缺陷单独保留，不用通过数代表模型整体正确。',
      '完整循环 Simulink 模型用真实连续 State-Space、Integrator 和编译 Fcn 方程块独立组成，不读入 Python 状态或电压。秒级案例用独立 MATLAB S-function，由 Simulink 积分器推进。两者检验同方程实现，不是 Simscape Battery 官方电芯。',
      '球形扩散参考方程：∂x/∂t=(D/R²)ρ⁻²∂ρ(ρ²∂ρx)，中心零通量，表面导数 mR²/(3D)。平均变化率 m 由电流决定。解析参考用 1000 个非零特征根 tan λ=λ，t=0 使用精确极限；各阶跃按线性叠加。有限体积参考用 128 和 256 层球壳，常通量段采用矩阵指数推进。网格和解析解差异满足预设 0.1 mV 精度要求。',
      '[MathWorks 单颗粒扩散模型定义](https://www.mathworks.com/help/simscape-battery/ref/batterysingleparticle.html)；[MathWorks 扩散与断流恢复示例](https://www.mathworks.com/help/simscape-battery/ug/examine-effect-diffusion-coefficient-and-volume-fraction-on-terminal-voltage.html)。参考求解由本项目独立实现，没有冒充官方组件运行结果。','',
      '## 参数','',
      '内阻 0.025 Ω，Tref = 298.15 K，OCP 与温度系数数组按常数项在前排列。参数、初值、全部边界与容差在两份 contract.json 中。','',
      '| 参数 | 负极 | 正极 |','|---|---|---|']
    es=C['parameters']['battery']['electrodes']
    for key in ['D_ref_m2_s','radius_m','I0_ref_A','active_fraction','electrode_area_m2','thickness_m','c_max_mol_m3','E_D_J_mol','E_I_J_mol','b_V','d_V_K']:
        lines.append(f"| {key} | {es['n'][key]} | {es['p'][key]} |")
    lines += ['','## 复现','', '在仓库根目录依次执行。','', '```powershell',
      '& ./Thermal/.venv/Scripts/python.exe Power/battery_validation/run_full_cycles.py',
      '& "C:/Program Files/MATLAB/R2026b/bin/matlab.exe" -batch "addpath(\'C:/Workspace/SpaceDC/Power/battery_validation/matlab\'); run_full_cycles_simulink"',
      '& ./Thermal/.venv/Scripts/python.exe Power/battery_validation/analyze_full_cycles.py',
      '& ./Thermal/.venv/Scripts/python.exe Power/battery_validation/run_battery.py',
      '& "C:/Program Files/MATLAB/R2026b/bin/matlab.exe" -batch "addpath(\'C:/Workspace/SpaceDC/Power/battery_validation/matlab\'); run_battery_simulink"',
      '& ./Thermal/.venv/Scripts/python.exe Power/battery_validation/analyze.py',
      '```','',
      '`build_current_preview.py` 从保存结果生成当前四页 PDF 和图，需要 numpy、matplotlib、reportlab。完整循环 SLX 默认演示第一段 36000 s 放电，秒级 SLX 默认演示 20 s 充电，完整协议由对应 run 脚本执行。','',
      '| 文件 | 内容 |','|---|---|',
      '| results/full_cycles/contract.json | 三圈协议、材料、初值与容差 |',
      '| results/full_cycles/segment_N_python.csv 与 segment_N_simulink.csv | 六个半循环原始结果 |',
      '| results/full_cycles/segment_N_accepted_steps.csv | 实际内部积分时刻 |',
      '| results/full_cycles/summary.json | 54 项数值检查及循环能量账 |',
      '| results/contract.json | 四个秒级用例参数与时序 |',
      '| results/BAT-T0x_python.csv 与 BAT-T0x_simulink.csv | 秒级完整输出与热源分量 |',
      '| results/BAT-T0x_analytic.csv 与 diffusion_128/256.csv | 扩散参考及两种网格 |',
      '| results/BAT-T0x_accepted_steps.csv 与 simulink_derivatives.csv | 内部积分步及导数求值记录 |',
      '| results/summary.json | 87 项数值检查和秒级物理诊断 |',
      '| matlab/sdtwin_battery_full_cycles.slx | 内置连续模块搭成的完整循环模型 |','',
      '原图 3 审计：BT-002 在固定平均浓度和温度下改变电流，是独立静态扫描，不能当成恒流充电随时间变化。原 DY 类案例确有积分。本次补齐完整容量曲线、明确输入和真实时间推进。','']
    (HERE/'README.md').write_text('\n'.join(lines),encoding='utf-8')

if __name__=='__main__':
    figures();make_pdf();make_readme();print('Current preview generated.')
