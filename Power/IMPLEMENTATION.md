# Power implementation status

## 当前设计与测试

当前依据为用户更新的[中文设计报告 v19.1](SDTwin_Power_Design_Report_CN_v19.1.docx)。
模型采用一阶 ECM、随 SOC 与温度查表的只读资产参数和 EKF，运行时不做 RLS。
物理积分和功率求根由外部求解器负责，EKF 不参与功率分配。

[模型验证方案](TEST_PLAN.md) 包含 10 项：太阳发电 1 项、电池模型 7 项、
EKF 1 项和功率分配 1 项。2026年10月8日已完成 26 次独立 Simulink 仿真，
逐点比较 70,554 个时间点，10 项满足执行前固定的模型判据。

- [正式测试报告 PDF](SDTwin_Power_Model_Test_Report_CN_v19.1.pdf)
- [正式测试报告 Word](SDTwin_Power_Model_Test_Report_CN_v19.1.docx)
- [仿真模型、数据与复现入口](tests_v19_1/README.md)
- [当前电池核心](battery.py)

电池核心提供纯 ECM 响应、二维只读参数表和独立 EKF。物理积分及功率求根在
`tests_v19_1/run_python.py`；Simulink 使用原生连续积分器和独立 MATLAB 方程。
三组 25 °C 留出电压 RMSE 为 26.70、28.65、17.27 mV，部分充电和静置阶段仍有系统偏差。
BT06 原始时钟相差约 17 ns，反转样本按同一事件侧配对，原始记录均保留。
真实 SOC、发热实测、多温度实物精度和完整热电联调不属于已验证结论。

## 保留的历史依赖

2026年10月9日已清理 v19 设计报告、旧测试报告、电池预览 PDF 及旧版排版检查文件。
当前交付使用上面的 v19.1 设计、测试方案与测试报告。

`battery_rebuild/data`、`fixtures` 和 `results/parameters.json` 为当前实测输入与
离线参数的来源，因此保留。历史仿真代码及原始结果仍可追溯，不作为新版验收结论。
当前报告生成器使用 `tests_v19_1/templates/orbit_power_test_source.docx` 作为版式源，
该文件从旧测试报告移入，内容及哈希不变。

以下两份历史设计仍由现有 Thermal 报告引用，因此作为旧 SPM 的设计依据保留：

- [历史中文设计](SDTwin_Power_Design_Report_CN.docx)
- [历史英文设计](SDTwin_Power_Design_Report_EN.docx)

`Thermal/sdtwin_sim/power_stand_in.py` 及其场景适配器仍采用旧 SPM，尚未迁移至 v19.1 ECM。
本轮清理不改变 Thermal 的模型或历史实验结果。
