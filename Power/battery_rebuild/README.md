# v19 历史电池实现与标定数据

本目录保留旧版一阶 Thevenin ECM、RLS 与 EKF 的代码和实验记录，核心为
[legacy_battery_v19.py](legacy_battery_v19.py)。当前版本为
[v19.1 模型与 Simulink 验证](../tests_v19_1/README.md)，运行时已取消 RLS。

## 保留内容

旧版设计和测试报告及其排版检查文件已于 2026年10月9日清理。
`data`、`fixtures` 和 `results/parameters.json` 仍是 v19.1 输入生成与审计的依赖。

* [历史 Simulink 模型](matlab/sdtwin_battery_ekf_rls_1rc.slx)
* [完整结果与预设判据](results/summary.json)

9 组 Python 与 Simulink 全时序输出一致。三组独立留出实测工况的开环电压通过
30 mV RMSE 与 100 mV 最大误差标准。无噪声参数恢复通过。加入 3 mV 电压噪声后，
R1 误差 21.40%、时间常数误差 30.46%，未达到预设 20% 门槛，保留为失败。
EKF 电压接近测量值并不证明参数正确，实测 SOC 也没有独立真值。

## 模型和边界

放电电流为正。物理状态为 SOC 与 RC 极化电压；温度由调用方提供。
当前标定只支持 25°C，其他温度明确拒绝。EKF 每 0.1 s 预测和校正，RLS 每 1 s
辨识 R0、R1 和时间常数，C1 由 tau/R1 换算。OCV 与容量由离线标定提供。
RLS 使用相同预滤波的 ARX 回归和局部偏差项，无激励时冻结，非法参数不应用于 ECM。
估计器参数从下一样本使用，物理仿真状态不被测量重置。

热源为两个电阻的耗散；RC 储能另行计算。能量验算使用常参数。
本轮不声称验证了熵热、老化、真实 SOC、多温度或完整卫星 Thermal 闭环。
旧 Thermal 场景的 SPM 适配器尚未迁移，不能将其历史通过项转移给新模型。

## 实验输入

BAK N18650CL-29 的 MathWorks 配套实测数据已保存在 data，原始 MAT 和许可在
reference/mathworks_download。保留五个温度，当前仅用 25°C 完成标定与验证。
采用官方示例的容量 2.84 Ah 和原始记录初始 SOC 0.055，电流积分只形成电量参考。

训练使用第 1、2、5、7、9 个放电脉冲的 30 s 加载段及对应预静置电压。
第 4、6、8 个脉冲的 120 s 放电、静置、充电、静置序列独立留出。
第 3 个脉冲按来源文档的异常记录单列，不纳入标定。
原始数据不改写。电流按零阶保持到 0.1 s 网格，电压不跨电流方向切换插值。

三次容量曲线使用 0.1 C、最多 1 s 步长，SOC 0.12 至 0.96。
每半循环容量为 2.3856 Ah；这是已标定 SOC 窗口，不是假称全电量的 0 至 100% 曲线。
横轴没有按图形需要压缩真实时间，也没有在缺少活性物质质量时改成 mAh/g。

## 复现

在仓库根目录执行：

```powershell
& Thermal/.venv/Scripts/python.exe Power/battery_rebuild/run.py
& 'C:/Program Files/MATLAB/R2026b/bin/matlab.exe' -batch "addpath('C:/Workspace/SpaceDC/Power/battery_rebuild/matlab');run_simulink"
& 'C:/Users/markl/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -X utf8 Power/battery_rebuild/analyze.py
& Thermal/.venv/Scripts/python.exe Power/battery_rebuild/test_model.py
```

MATLAB/Simulink 是实际执行的固定步长引擎。模型采用自定义 MATLAB S 函数和离散
状态，未使用 Simscape Battery 工厂模块。Python 与 MATLAB 分别编写，输入文件共享，
输出不互相读取。默认打开模型展示留出实测脉冲 4。

results 保留每步原始输出、同点差值和汇总；fixtures 的参考 SOC 仅用于评分。
history 保存早期错误回归方案与其失败结果。contract 的误差门槛未放宽。
data/LICENSE.txt 必须随数据再分发保留。原始数据属于公开 BAK 电芯，不能声称是
SpaceDC 目标航天电芯的测量。参考页面：

* [MathWorks HPPC 参数估计与 BAK 数据](https://www.mathworks.com/help/simscape-battery/ug/estimate-battery-model-parameters-from-hppc-data.html)
* [RLS 算法文档](https://www.mathworks.com/help/ident/ref/recursiveleastsquaresestimator.html)
* [Kalman SOC 估计器文档](https://www.mathworks.com/help/simscape-battery/ref/socestimatorkalmanfilter.html)
