# Power v19.1 模型与 Simulink 验证

2026年10月8日执行完成。10 个项目、26 次 Simulink 仿真，对比 70,554 个时间点。
10 项满足执行前判据。结果覆盖范围和残余误差见下文。

- [正式 PDF 报告](../SDTwin_Power_Model_Test_Report_CN_v19.1.pdf)
- [可编辑 Word 报告](../SDTwin_Power_Model_Test_Report_CN_v19.1.docx)
- [Markdown 详细结果](reports/TEST_REPORT_CN.md)
- [逐项机器判定](results/summary.json)
- [执行前冻结方案](fixtures/accepted_test_plan.md)
- [设计依据 v19.1](../SDTwin_Power_Design_Report_CN_v19.1.docx)

2026年10月9日已清理旧版报告、预览和旧版排版检查文件。当前报告所用的原始
Orbit 格式模板移至 `templates/orbit_power_test_source.docx`，文件内容与哈希不变。
旧数据与标定记录继续作为本轮输入来源保留。

## 测试项目

| 项目 | 输入场景 | 输出与验证目标 | Simulink 入口 |
| --- | --- | --- | --- |
| PV01 | 0、60、90、180 度；1000、500、0 W/m²；面积加倍 | 太阳上限与理论方向、面积倍率 | [PV01.slx](matlab/PV01.slx) |
| BT01 | 0、2、−2 A，1 串 1 并与 4 串 2 并 | 静态电压、功率、热源、导数和倍率 | [BT01.slx](matlab/BT01.slx) |
| BT02 | 10 至 30 s 放电 2 A，前后静置 | 60 s 动态、0.1 V 欧姆跳变、极化恢复；3 级步长核算 | [BT02.slx](matlab/BT02.slx) |
| BT03 | 静置、−2 A 充电、2 A 放电、静置 | 80 s 电压方向、反转记忆、SOC 电量 | [BT03.slx](matlab/BT03.slx) |
| BT04 | 人工参数表；0、25、50 °C 相同脉冲 | 25 个插值点与三温度时域响应 | [BT04.slx](matlab/BT04.slx) |
| BT05 | BT03 时序，常参数 | 两项耗散、RC 储能、累计能量守恒 | [BT05.slx](matlab/BT05.slx) |
| BT06 | 0.1C，SOC 0.12 → 0.88 → 0.12 | 完整 54720 s，1.52 Ah 每方向，事件定位与容量曲线 | [BT06.slx](matlab/BT06.slx) |
| BT07 | BAK 25 °C 留出脉冲 4、6、8，各 119.9 s | 开环模型与真实测量电压，整段和分段误差 | [BT07.slx](matlab/BT07.slx) |
| EK01 | 300 s 变化电流，3 mV 噪声，SOC 初始偏差 10 个百分点 | 因果 EKF、先验电压、SOC 误差 | [EK01.slx](matlab/EK01.slx) |
| PA01 | 五段日照与负载，4 串 2 并，配电效率 0.9 | 平衡、放电、充电、限充、供电不足断开 | [PA01.slx](matlab/PA01.slx) |

## 真实执行方式

被测核心是 `Power/battery.py`，只返回物理导数与瞬时响应。`run_python.py`
在外部使用 SciPy DOP853 积分并用 brentq 求功率工作点。
独立 MATLAB 方程运行在 Simulink R2026b 中，物理状态由原生连续 Integrator
和 ode45 推进。参数查表和功率求根使用 MATLAB 代码，EKF 使用独立离散状态。
两套实现没有相互调用，测量电压不反馈开环电池，估计状态不参与功率分配。
这里使用设计方程建立对照，不是厂商预设 Simscape Battery 电芯。

短时项目最大步长及保存间隔 0.1 s，完整充放电 1 s。相对容差 1e-10、绝对容差 1e-12。
所有保存时刻由完整积分产生。静态 BT01 明确冻结物理状态，只测试瞬时响应。

从仓库根目录重现当前冻结输入的全部结果：

```powershell
& Thermal/.venv/Scripts/python.exe -X utf8 Power/tests_v19_1/run_python.py
& 'C:/Program Files/MATLAB/R2026b/bin/matlab.exe' -batch "addpath('Power/tests_v19_1/matlab'); run_suite"
& Thermal/.venv/Scripts/python.exe -X utf8 Power/tests_v19_1/analyze.py
```

`prepare.py` 可从既有离线标定数据重新生成同一组输入。它读取冻结方案副本，
不会把后加的执行状态文字混入执行前方案哈希。普通重现直接使用现有 fixtures 即可。
单项运行示例为 MATLAB `run_suite({'BT02'})`。正式完整执行记录是
`results/simulink_execution.json`，单项重跑记录使用单独文件，避免覆盖完整记录。

交互查看时在 MATLAB 打开同名 slx 并点击 Run。回调自动载入该项目代表场景。
BT01、BT04、BT07 的多组参数由完整运行入口逐组执行；代表模型分别为 4 串 2 并 2 A、
25 °C 和留出脉冲 4。Scope 保存电流、电压和两个物理状态，完整信号保存在输出对象中。

## 结果和证据边界

BAK 三段整段 RMSE 为 26.70、28.65、17.27 mV，最大误差为 60.25、59.47、50.51 mV。
每组满足 30 mV RMSE 和 100 mV 最大误差，但部分充电或静置阶段的 RMSE 达 35 至 41 mV。
报告保留这些分段偏差，没有宣称各阶段都低于 30 mV。

BT06 的 Simulink SOC 事件比解析时刻晚约 1.67e-8 s。
在原始固定时间网格的 27360 s，Python 已反转、Simulink 尚未反转，
所以原始电压差为 0.02 V。按照执行前方案，比较必须在同一事件侧进行。
`BT06_*_aligned.csv` 只将这一处配对到原生求解器的右侧事件记录；
原始 CSV 和 MAT 未修改。`BT06_event_sides.csv` 保存两侧和真实源时间，
`BT06_alignment_audit.json` 保存映射、原始误差、同侧误差和事件时间门限。
`summary_before_event_alignment.json` 与 `BT06_unaligned_difference.csv` 保留最初的失败。
所有其他样本完全未变，没有跨电压跳变插值，也没有放宽误差门限。

A、B 是人工核算参数。B 的三温度结果只验证查表机制。BT06 的近似线性容量曲线
来自 A 的线性 OCV，不代表用户示例图中的材料平台。真实数据只覆盖 BAK 25 °C 的三段
留出电压。真实 SOC、热量、多温度、老化、单体不一致和完整 Thermal 闭环未验证。
现有 Thermal 旧 SPM 适配器尚未接入本版 ECM。

## 字段和可追踪文件

`fixtures/*.csv` 包含 time_s、单体 current_A、temperature_K、irradiance_W_m2、
cos_incidence、request_W、noise_V、measured_voltage_V；项目 JSON 保存初值、资产、
拓扑及输入哈希。只有 BT07 的 measured_voltage_V 是实测电压。

结果 CSV 中 `power_W` 是整组电池端口功率；`heat_W` 为整组两电阻耗散，
`polarization_energy_J` 为整组 RC 储能；`available_solar_W` 是上限，
`actual_solar_W` 是实际取电；`load_W` 为实际交付功率。
`power_residual_W = actual_solar_W + power_W − load_W − distribution_heat_W`，
只对 PA01 有守恒判定含义。其他电池开环试验没有连接配电网络，这一字段为零占位。
`cumulative_Ah` 积分的是单体绝对电流，BT06 每分支横坐标重新从零计算。

每个 `*_difference.csv` 的非时间列严格等于相应 Python 数组减 Simulink 数组。
时间列是时间差，因此通常为零；画图横坐标读取原始 time_s。
BT06 使用明确标识的 aligned 数组。EKF 单独保存先验、后验、创新和协方差，
其 estimator_difference 为 Simulink 减 Python，表头与报告明确按此定义读取。
`*_native_edges.csv` 是切换邻近的原生已接受记录，左侧时间可能是前一个保存点；
瞬时左右极限另在同一边界状态计算，保存于 `pulse_edge_limits.json`。

设计报告和冻结判据的哈希在 `contract.json`；完整源码、输入、模型与结果哈希在
`evidence_manifest.json`。BAK 数据许可为 `fixtures/BAK_DATA_LICENSE.txt`。
参考实现使用 [Integrator](https://www.mathworks.com/help/simulink/slref/integrator.html)
及 [From Workspace](https://www.mathworks.com/help/simulink/slref/fromworkspace.html)
的连续积分与零阶保持语义。
