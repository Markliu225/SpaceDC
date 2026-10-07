"""Generate concise bilingual report prose from the recorded experimental evidence.

The detailed checks and original test-produced summaries remain in tests/results.
The report never changes a case verdict. Hashes bind both languages to the same evidence.
"""
from pathlib import Path
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT.parent / 'tests' / 'results'
ORDER = ['DM-001', 'PA-001', 'EN-001', 'EN-002', 'EN-003', 'HT-001', 'HT-002', 'HT-003',
         'EC-001', 'FE-001', 'FE-002', 'FE-003', 'FE-004', 'NI-001', 'NI-002', 'NI-003']


def num(v, places=2):
    if v is None or not math.isfinite(float(v)):
        return 'N/A'
    return f'{v:.{places}f}'.replace('-', '−')


def sci(v):
    if v is None or not math.isfinite(float(v)):
        return 'N/A'
    if v == 0:
        return '0'
    a, b = f'{v:.2e}'.split('e')
    return a.replace('-', '−') + '×10^{' + str(int(b)).replace('-', '−') + '}'


def maximum(values):
    values = list(values)
    return max(values) if values and all(math.isfinite(float(v)) for v in values) else float('nan')


def prose(cid, m):
    if cid == 'DM-001':
        n = len(m['exports']['public_names'])
        return (
            f'检查四个数据对象的字段、数组顺序、单位、只读性、异常构造与联合运行中的试算状态。电池热量为 10 W 与 −10 W 时，温度导数分别为 0.004 K/s 与 −0.016 K/s，后者由式 T3 独立计算。修正包公开导出后，公开名称共 {n} 个，包含附录 A 的九个名称及四个错误与警告类。SurfaceRecord 与顺序常量从 thermal.types 导入。拒绝步、事件边界与温度归属检查见原始检查明细。',
            f'The four records were checked for fields, array order, units, immutability, invalid construction and trial-state handling in coupled runs. Battery heat inputs of 10 W and −10 W give 0.004 K/s and −0.016 K/s; the latter is independently calculated from T3. After correcting package exports, the {n} public names comprise the nine names in Appendix A and four error or warning classes. SurfaceRecord and ordering constants are imported from thermal.types. The evidence also records rejected-step, event-boundary and temperature-ownership checks.')
    if cid == 'PA-001':
        e = maximum(m[k] for k in ['max_rel_error_C_baseline', 'max_rel_error_R_baseline', 'max_rel_error_C_override', 'max_rel_error_R_override'])
        return (
            f'按材料质量与比热、几何导热项和接触热阻装配六个热容与五条热阻，并测试场景覆盖值。与独立手算相比，基准值及覆盖值的最大相对误差为 {sci(e)}。设计算例热容为 {num(m["design_4_5_example_C_J_K"], 0)} J/K，MBSU 热容为 {num(m["mbsu_block_C_J_K"] / 1000, 1)} kJ/K，散热器面热容为 {num(m["radiator_panel_C_per_area_J_m2K"] / 1000, 1)} kJ·m^{{−2}}·K^{{−1}}。接触热阻重复计入、参数缺失、非有限值与非法表面参数分别执行拒绝检查，参数记录保留来源与覆盖过程。',
            f'Six capacitances and five resistances were assembled from material mass and specific heat, conduction geometry and contact resistance, with explicit scene overrides. The largest relative error of baseline and overridden values against independent calculations is {sci(e)}. The design example gives {num(m["design_4_5_example_C_J_K"], 0)} J/K, the MBSU gives {num(m["mbsu_block_C_J_K"] / 1000, 1)} kJ/K, and the radiator areal capacity is {num(m["radiator_panel_C_per_area_J_m2K"] / 1000, 1)} kJ·m^{{−2}}·K^{{−1}}. Rejection checks cover double-counted contact resistance, missing and non-finite parameters and invalid surfaces. Provenance records parameter sources and overrides.')
    if cid == 'EN-001':
        return (
            f'在 400 km 圆轨道上取 {m["orbit_samples"]} 个时刻，并用固定旋转、随机四元数、姿态动力学和对地指向等姿态检查表面环境。入射余弦与独立旋转计算的最大绝对差为 {sci(m["max_cos_incidence_error"])}，限值为 1×10^{{−12}}。G 与 Orbit 输出逐位一致，日食因子没有重复相乘。{m["abnormal_inputs"]} 项异常输入检查覆盖四元数、法向、坐标系、表面顺序、时间与缺失环境记录。',
            f'The surface environment was evaluated at {m["orbit_samples"]} instants on a 400 km circular orbit using fixed rotations, random quaternions, attitude dynamics and Earth-pointing attitudes. The largest incidence-cosine error against independent rotation calculations is {sci(m["max_cos_incidence_error"])} against 1×10^{{−12}}. G is bitwise identical to Orbit output, with no second eclipse multiplier. The {m["abnormal_inputs"]} invalid-input checks cover quaternions, normals, frames, surface order, timing and missing environment records.')
    if cid == 'EN-002':
        return (
            f'对不同朝向、光学参数、日照与地球热流组合逐项手算式 T4。吸热与辐射功率最大相对误差为 {sci(m["max_relative_error"])}，验收限值为 1×10^{{−12}}。第 4.4 节算例得到 1600 W。温度由 200 K 变为 400 K 时，辐射功率比为 {num(next(iter(m["emission_ratio_400K_200K"].values())), 0)}，符合四次方关系。内部节点不额外计算表面辐射，温区越界按设计记录警告。',
            f'T4 was calculated independently for combinations of orientation, optical properties, sunlight and Earth flux. The largest relative error of absorbed and emitted power is {sci(m["max_relative_error"])} against 1×10^{{−12}}. The Section 4.4 example gives 1600 W. Raising temperature from 200 K to 400 K gives an emission ratio of {num(next(iter(m["emission_ratio_400K_200K"].values())), 0)}, as required by the fourth-power law. Internal nodes do not receive additional surface-radiation terms, and out-of-range temperatures produce warnings.')
    if cid == 'EN-003':
        levels = m.get('fe_refined_comparison', {})
        n = len(levels.get('cases', {}))
        return (
            f'用对地平板解析视角系数、独立地心面元积分和蒙特卡罗积分检查 earth_flux。相对误差判据保持为 1%，仅数值零使用 1×10^{{−12}} W/m² 绝对容限。有限元对比保留原 2×6 地球离散数据，对相同时刻的热载荷、周期平均值与峰值执行 3% 判据。散热器对比使用不受另一翼遮挡的外侧面，内侧面差异另作诊断。原始参考数据存在超限项，详细数值见后表。另完成 {n} 个工况的 2×6、4×12 与 8×24 地球离散对比，比较固定采样时刻的平均热载荷。加密结果用于核对参照，不能覆盖原验收结果，也不等同于整段温度计算已收敛。',
            f'earth_flux was checked against the analytic nadir-plate view factor, independent geocentric quadrature and Monte Carlo integration. The relative criterion remains 1%; only numerical zero uses an absolute tolerance of 1×10^{{−12}} W/m². The original FE comparison retains the 2×6 planet discretisation and applies the 3% criterion to simultaneous loads, orbit means and peaks. Radiator comparisons use the outer faces without obstruction by the other wing; inner faces are diagnostic. Original-reference exceedances remain in the following tables. A further {n} cases compare 2×6, 4×12 and 8×24 planet discretisations using mean loads at fixed sample instants. Refinement verifies the reference; it neither replaces the original acceptance nor establishes convergence of the full temperature simulation.')
    if cid == 'HT-001':
        return (
            f'五条传热连接逐条按式 T2 与独立手算比较，最大相对误差为 {sci(m["max_relative_error"])}。电池算例热流为 6 W，两端温度交换后为 −6 W，两端等温时为零。测试同时记录端点温度与热阻读取顺序、每条路径求值次数、极端有效热阻，以及非法输入的拒绝结果。',
            f'All five heat paths were compared with independent T2 calculations, giving a largest relative error of {sci(m["max_relative_error"])}. The battery example gives 6 W, changes to −6 W when the end temperatures are exchanged, and gives zero for equal temperatures. Checks also record temperature and resistance access order, evaluations per path, extreme valid resistances and rejection of invalid inputs.')
    if cid == 'HT-002':
        r = m['random_cases']
        return (
            f'设计电池算例得到温度导数 0.004 K/s。对固定随机种子的 {r["n_evaluated"]} 组输入执行逐节点式 T3 与全网式 T1 检查，T1 残差与输入热功率之比最大为 {sci(r["t1_ratio_max_heat_input"])}，限值为 1×10^{{−12}}。五条内部热流在全网求和中成对抵消，返回的 T_B_K 与 T_J_K 是本次输入状态的温度。',
            f'The design battery example gives a derivative of 0.004 K/s. With a fixed random seed, {r["n_evaluated"]} input sets were checked against node balances T3 and total balance T1. The largest T1 residual divided by input heat power is {sci(r["t1_ratio_max_heat_input"])} against 1×10^{{−12}}. All five internal flows cancel in the total balance. Returned T_B_K and T_J_K are temperatures from the input state.')
    if cid == 'HT-003':
        return (
            f'通过联合求解器执行计算节点阶跃响应、串联热阻稳态与散热板辐射平衡三个解析算例。阶跃响应最大温差为 {sci(m["step_error_max_K"])} K，串联链路稳态温差误差为 {sci(m["series_dT_JR_error_K"])} K，辐射平衡温度误差为 {sci(m["radiation_T_error_K"])} K。稳态误差与 0.001 K 判据比较。固定温度边界以已声明的大热容与大热阻近似，边界漂移另行核对。',
            f'Three analytic cases were run through the coupled solver: computing-node step response, series-resistance equilibrium and radiator radiation balance. The largest step-response error is {sci(m["step_error_max_K"])} K, the series steady-temperature-drop error is {sci(m["series_dT_JR_error_K"])} K, and the radiation equilibrium error is {sci(m["radiation_T_error_K"])} K. Steady errors are compared with 0.001 K. Fixed-temperature boundaries use declared large capacitances and isolation resistances, with boundary drift checked separately.')
    if cid == 'EC-001':
        return (
            f'分别改变四个 Power 端口，导数变化与独立式 T3 计算的最大相对差为 {sci(m["step1_max_relative_error"])}。检查负电池热量、光伏限发、超出吸收太阳功率的电输出，以及 invalid、supply_shortfall 与 device_boundary 的处理。联合运行中记录 {m["step5_power_calls"]} 次 Power 调用，电池温度均来自同次热状态。供电端保留的校验温度副本与热初值一致，运行中不独立积分电池温度。',
            f'Each Power port was varied independently. The largest relative error of derivative changes against T3 is {sci(m["step1_max_relative_error"])}. Tests cover negative battery heat, PV curtailment, PV output exceeding absorbed sunlight, and handling of invalid, supply_shortfall and device_boundary results. The coupled run records {m["step5_power_calls"]} Power calls, each using battery temperature from the same thermal evaluation. The Power validation copy agrees with the thermal initial temperature; Power does not integrate a separate battery temperature.')
    if cid == 'FE-001':
        rows = [m[c + '_comparison'] for c in ('cold0', 'nom0', 'hot75')]
        stat = maximum(r['max_abs_diff_K'] for r in rows)
        point = [r['pointwise_max_abs_K'] for r in rows]
        return (
            f'按 ISS 太阳翼面积、面热容、正反面光学参数与三个环境工况运行集总模型。第三圈最低、平均与最高温度九个统计量的最大绝对差为 {num(stat)} K，满足 3 K 判据。但在有限元输出的相同时刻逐点比较，冷、平均、热工况的最大温差分别为 {num(point[0])} K、{num(point[1])} K 与 {num(point[2])} K，冷与平均工况不满足曲线对比要求，因此本用例不通过。比较不允许前后平移时间。偏差集中在日食转换之后，当前证据不能把偏差全部归因于有限元时间步长。关闭反照与红外的对照另行记录。',
            f'The lumped model uses ISS array area, areal heat capacity, front and back optical properties and three environmental cases. The largest absolute difference among nine third-orbit minimum, mean and maximum statistics is {num(stat)} K, meeting 3 K. However, simultaneous pointwise comparison at FE output instants gives maxima of {num(point[0])} K, {num(point[1])} K and {num(point[2])} K for the cold, mean and hot cases. The cold and mean curves exceed the requirement, so the case fails. No time shift is allowed. Differences concentrate after eclipse transitions; current evidence does not attribute all of them to FE time stepping. Runs without albedo and infrared are recorded separately.')
    if cid == 'FE-002':
        values = [abs(m[f'{c}_{l}_difference_orbit3_K']['mean']) if isinstance(m[f'{c}_{l}_difference_orbit3_K'], dict) else abs(m[f'{c}_{l}_difference_orbit3_K']) for c in ('cold0', 'nom0', 'hot75') for l in ('A', 'B')]
        return (
            f'按有限元散热器面积、面热容与氨回路热容配置节点 R，将有限元回路进热量作为边界输入，对三种环境下的 A、B 两个回路分别运行。第三圈平均温度的最大绝对差为 {num(maximum(values))} K，验收限值为 5 K。环境吸热、表面辐射、积分结果与独立计算分别核对。有限元最低面板温度与面板温差另行记录，平均温度通过不代表局部最低温度或热点通过。遮挡与沿流向温差是解释残差的候选因素，本测试没有分离它们各自的贡献。',
            f'Node R uses FE radiator area, panel heat capacity and ammonia-loop capacity. FE loop heat input is prescribed as a boundary condition for separate A and B loop runs in three environments. The largest absolute third-orbit mean-temperature difference is {num(maximum(values))} K against 5 K. Environmental absorption, emission and integration are checked independently. FE coldest-panel temperatures and panel spreads are recorded separately; passing a mean-temperature criterion does not validate local minima or hot spots. Obstruction and along-flow gradients are possible residual contributors, but their individual effects are not isolated here.')
    if cid == 'FE-003':
        return (
            f'以 ISS 平均环境工况的冷却液温度作为冷板边界，对 14 台 MBSU、DDCU 与 IEA 的计算节点到冷板链路进行比较。设备平均温度最大绝对差为 {num(maximum(m["step3_worst_abs_diff_K"].values()))} K，限值为 1 K。冷板边界的大热容、隔离热阻及来源均记入归档，实际求解设置与配置逐项核对。设备分得的冷板进热量按回路比例近似；约 5.4% 的剩余量同时包含外表面辐射与蓄热，现有数据不能将两者分开。',
            f'The computing-node to cold-plate path was compared for 14 ISS MBSU, DDCU and IEA units using mean-case coolant temperature as the cold-plate boundary. The largest absolute device mean-temperature difference is {num(maximum(m["step3_worst_abs_diff_K"].values()))} K against 1 K. Large boundary capacitance, isolation resistance and sources are archived, and actual solver settings are compared with the configuration. Per-device cold-plate input is approximated using each loop share. The roughly 5.4% remainder includes both external radiation and storage; available data cannot separate them.')
    if cid == 'FE-004':
        rows = [m['orbit_means_K'][c][str(o)] for c in ('caseA', 'caseB') for o in (4, 5)]
        dj = [r['J_K'] - r['fe_baseplate_K'] for r in rows]
        dr = [r['R_K'] - r['fe_radiator_K'] for r in rows]
        single = [m['orbit_means_K'][c]['report_window']['fe_baseplate_C'] -
                  m['orbit_means_K'][c]['report_window']['orbitwiz_node_C'] for c in ('caseA', 'caseB')]
        return (
            f'运行 12 块 V100 与 12 块 A100 两个整星算例，比较第四、五圈的平均温度。计算节点比有限元 GPU 基板高 {num(min(dj), 1)} 至 {num(max(dj), 1)} K，散热板高 {num(min(dr), 1)} 至 {num(max(dr), 1)} K，均有超出 5 K 的项目。本用例不通过。单节点对照模型比有限元基板分别低 {num(single[0])} K 与 {num(single[1])} K，后者超出预期的 12 至 15 K 区间。四个散热板主表面以外的有限元能量收支剩余项包含多个节点的表面贡献，现有导出不足以分离来源，不能用整个剩余项修正节点温度或认定链路热阻已被验证。机身改接 D 节点的敏感性试验未消除偏差。',
            f'Two whole-satellite cases with 12 V100 and 12 A100 devices were run, comparing fourth- and fifth-orbit means. Computing-node temperatures exceed FE GPU baseplate temperatures by {num(min(dj), 1)} to {num(max(dj), 1)} K; radiator temperatures exceed FE values by {num(min(dr), 1)} to {num(max(dr), 1)} K. Several values exceed 5 K and the case fails. The single-node controls are {num(single[0])} K and {num(single[1])} K below the FE baseplate; the latter exceeds the expected 12 to 15 K interval. The FE energy-budget remainder beyond four main radiator faces includes surfaces belonging to several nodes, which available exports cannot separate. It cannot be used in full to correct node temperatures or validate chain resistance. Assigning the bus to node D does not remove the discrepancy.')
    if cid == 'NI-001':
        t = maximum(r['max_K'] for r in m['tighten_both'])
        d = maximum(r['max_K'] for r in m['rk45_vs_radau'])
        return (
            f'组合 RK45 与 Radau、两组相对与绝对容限、两种最大步长及两种输出间隔，执行 32 组数值设置对比，并补充直接环境计算和拒绝步试验。容限收紧 100 倍后最大温差为 {sci(t)} K，两种积分方法最大温差为 {sci(d)} K，均与 0.01 K 判据比较。日食定位最大误差为 {sci(m["eclipse_boundaries"]["max_error_s_all_runs"])} s。32 组设置的固定输出网格、边界分段与独立参考解均有记录；积分器统计与试算日志用于检查拒绝状态没有写入输出。',
            f'RK45 and Radau, two relative and absolute tolerances, two maximum steps and two output intervals form a 32-setting matrix, supplemented by direct-environment and rejected-step runs. Tightening tolerances 100-fold changes temperature by at most {sci(t)} K; the largest method difference is {sci(d)} K, compared with 0.01 K. The largest eclipse-location error is {sci(m["eclipse_boundaries"]["max_error_s_all_runs"])} s. Fixed output grids, segmentation and independent reference solutions are recorded for the 32 settings. Solver statistics and trial logs check exclusion of rejected states from output.')
    if cid == 'NI-002':
        return (
            f'使用 Orbit、earth_flux、测试用供电程序与六节点热模型联合运行 24 h，太阳能板法向与太阳方向夹角为 55°，基本请求功率 60 W，另有 900 s 功率爬升。保存 {m["step1_output_samples"]} 个输出样本。两次相同输入运行比较 {m["step5_leaves_compared"]} 个归档叶项，其中 {m["step5_numeric_leaves"]} 个为数值，差异项为 {m["step5_different_leaves"]}。独立故障注入运行检查 invalid 停止行为；注入供电不足与实际电池约束事件分别检查定位、断开与重启。启动前参数记录由测试驱动程序写出。Power 校验温度与热初值一致，运行中的电池温度来自当前热状态。',
            f'Orbit, earth_flux, the Power stand-in and the six-node thermal model were coupled for 24 h with a 55° solar-array incidence angle, a 60 W base request and a 900 s request ramp. The archive contains {m["step1_output_samples"]} output samples. Two identical-input runs compare {m["step5_leaves_compared"]} archive leaves, including {m["step5_numeric_leaves"]} numeric leaves, with {m["step5_different_leaves"]} differences. A separate fault-injection run checks invalid-result stopping. Injected supply loss and a physical battery constraint separately exercise location, disconnection and restart. The test driver writes the pre-run parameter record. Power validation temperature agrees with the thermal initial value; runtime battery temperature comes from the current thermal state.')
    if cid == 'NI-003':
        return (
            f'检查 SimReady 资产、USD 物理尺寸、显示缩放、材料质量、场景覆盖与模型登记。面积、质量、热容与热阻的最大相对误差分别为 {sci(m["step1_max_rel_error_area"])}、{sci(m["step1_max_rel_error_mass"])}、{sci(m["step1_max_rel_error_C"])} 与 {sci(m["step1_max_rel_error_R"])}。其中四个材料部分由尺寸、密度与实心比例计算，其余使用声明质量。两个卫星场景各自运行 5600 s，再次运行及独立进程运行的归档相同。运行前显式修正示例电池锂占比，使其与测试电池参数守恒，运行时不自动替换初值。密度覆盖后的有效密度与质量来源保留在参数记录中，USD 内文本不被执行。',
            f'SimReady assets, USD physical dimensions, display scale, material masses, scene overrides and model registration were checked. The largest relative errors of area, mass, capacitance and resistance are {sci(m["step1_max_rel_error_area"])}, {sci(m["step1_max_rel_error_mass"])}, {sci(m["step1_max_rel_error_C"])} and {sci(m["step1_max_rel_error_R"])}. Four material portions use size, density and solid fraction; the others use declared masses. Two satellite scenes run for 5600 s each, with identical repeat and separate-process archives. Example lithium fractions were explicitly corrected before execution to conserve the test cell inventory; runtime does not replace scene values. Parameter provenance retains effective density and mass sources after overrides, and text embedded in USD is not executed.')
    raise KeyError(cid)


def build():
    out = {}
    for cid in ORDER:
        path = RESULTS / f'{cid}.json'
        raw = json.loads(path.read_text(encoding='utf-8'))
        cn, en = prose(cid, raw['metrics'])
        failed = [c for c in raw['checks'] if not c['passed']]
        count = len(raw['checks'])
        anomaly_cn = '无' if not failed else (f'本用例未满足全部要求，记录 {len(failed)} 项未通过检查。超限数值及证据范围见实际结果和后续对比表。'
                                           f'每项预期值、实际值与判定保存在 tests/results/{cid}.json。')
        anomaly_en = 'None' if not failed else ('The case does not meet all recorded requirements. The measured exceedances and their evidence limits are stated above and in the comparison tables. Failed check count: ' + str(len(failed)) + '. See tests/results/' + cid + '.json for each expected value, actual value and verdict.')
        out[cid] = {'case_id': cid, 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'summary_cn': cn, 'summary_en': en, 'anomalies_cn': anomaly_cn, 'anomalies_en': anomaly_en,
                    'status': raw['status']}
    path = ROOT / 'out' / 'reviewed_results.json'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(path)


if __name__ == '__main__':
    build()
