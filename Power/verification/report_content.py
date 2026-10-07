"""Physical explanations accompany numerical fixtures, not generic test labels."""
TEXT={
'PV-001':(
'检验太阳辐照度和板面朝向是否正确决定最大发电功率。辐照度为零表示完全处于地影，余弦为负表示太阳位于太阳能板背面，两种情况都应停止发电。',
'Verify how irradiance and panel orientation determine available power. Zero irradiance denotes full eclipse; a negative incidence cosine places the Sun behind the active face. Both must produce zero power.',
'辐照度与七个入射余弦组成全部组合。Python 由姿态四元数旋转板面法线后求夹角，Simulink 直接使用相同几何工况的入射余弦。另用面积乘效率乘正向辐照度的解析式核验。',
'All irradiances are crossed with seven incidence cosines. Python rotates the panel normal with a quaternion; Simulink receives the cosine of the same geometry. An analytical area times efficiency times front-face irradiance check is also applied.'),
'BT-001':(
'检验不同初始电量下的开路电压。开路表示单体电流为零，电池不充电也不放电；端电压由两极平衡电位之差决定，发热和锂状态导数应为零。',
'Verify open circuit voltage at different initial charge levels. At zero cell current there is no charge transfer or current-induced heat; terminal voltage is the difference between electrode equilibrium potentials.',
'改变负极平均锂占比，并根据总锂守恒同步计算正极占比。温度固定为 293.15 K，即 20 ℃。这些点是独立的静态状态，不是一条充电轨迹。',
'Sweep the negative-electrode mean fraction and derive the positive fraction from lithium inventory conservation. Temperature is 293.15 K or 20 degrees Celsius. The samples are independent states, not a charging trajectory.'),
'BT-002':(
'检验充电和放电电流对端电压的影响，并检查温度如何改变反应和扩散。正电流表示放电，负电流表示充电。温度指电池温度，不是空间环境空气温度。',
'Verify charge and discharge voltage response and the effect of temperature on kinetics and diffusion. Positive current is discharge and negative current is charge. Temperature is the battery temperature, not ambient air in space.',
'对三种电池温度和六个单体电流执行全部组合，初始锂状态相同。直接调用电池方程，允许输出约束裕量为负，以核对其边界诊断；这些点不全部代表可供电工作点。',
'Cross three cell temperatures with six cell currents at a common lithium state. Direct cell evaluation retains negative constraint margins for boundary diagnostics; not every sample is a feasible power-allocation operating point.'),
'BT-003':(
'检验电池热源的三项组成，包括反应热、欧姆热和带符号的可逆热。可逆热可能使低电流下的总热源为负，此时表示模型中的净吸热，不能截断为零。',
'Verify reaction heat, ohmic heat and signed reversible heat. Reversible heat can make total heat negative at low current; this denotes net heat absorption in the model and must not be clipped to zero.',
'保持两极锂状态不变，在 283.15 K 与 303.15 K 下扫描正负小电流，同时比较整组热源与单体可逆热。',
'Hold both lithium fractions fixed and scan small positive and negative currents at 283.15 K and 303.15 K. Compare pack heat and cell reversible heat separately.'),
'BT-004':(
'检验单体模型到电池组的换算是否只应用一次。串联数决定整组电压，并联数决定整组电流，全部单体数共同决定整组功率和发热。',
'Verify cell-to-pack conversion. Series count scales pack voltage, parallel count scales pack current, and their product scales pack power and heat. Scaling must be applied once.',
'五种串并联连接使用完全相同的单体状态、0.5 A 单体放电电流和 293.15 K 温度。所有单体同温同状态且并联均流。',
'Five series and parallel configurations share the same cell state, 0.5 A cell discharge current and 293.15 K temperature. Cells have identical states and temperature, with equal parallel current sharing.'),
'PD-001':(
'检验太阳能板、电池和负载之间的电力分配。太阳富余时电池充电，太阳不足时电池补足差额；允许范围内仍不能满足请求时，应返回供电不足。',
'Verify power allocation among array, battery and load. Surplus solar charges the battery; a deficit calls for battery discharge. A request beyond the allowed battery capability must report supply shortfall.',
'四个辐照度与六个负载请求做全部组合。配电效率为 0.95，因此配电入口需求高于负载请求。供电不足点只比较状态标志，不能伪造零热源作为有效输出。',
'Cross four irradiances with six load requests. Distribution efficiency is 0.95, so bus-side demand exceeds load demand. Shortfall samples compare status flags and must not publish artificial zero heat as a valid result.'),
'PD-002':(
'检验配电器把入口功率分为负载电力与自身发热的关系，确认损耗不会漏计或重复扣除。',
'Verify that distribution input splits into load power and distribution heat, with no omitted or double-counted loss.',
'关闭太阳输入，由电池供电；分别使用 0.80、0.95 和 1.00 的配电效率。效率为 1.00 的理想边界应使配电发热为零。',
'Set solar input to zero and supply the load from the battery at efficiencies 0.80, 0.95 and 1.00. The ideal 1.00 boundary must have zero distribution heat.'),
'CT-001':(
'检验太阳富余但电池不能接收全部能量时是否限制充电并降低太阳实际输出。限制可能来自电流、端电压或颗粒中心和表面锂占比。',
'Verify curtailment when solar surplus exceeds the battery charge capability. Current, voltage and particle center or surface fractions can constrain charging.',
'辐照度人为设为 1800 W/m²，负载仅请求 25 W，以稳定产生太阳富余。它是边界压力测试，不代表某条实际轨道的太阳常数。分别收紧充电电流上限、端电压上限，或降低电池温度。',
'Use an artificial 1800 W/m² irradiance and a 25 W load to guarantee surplus. This is a boundary stress test, not a solar constant assigned to a real orbit. Tighten charge current or voltage limits, or lower battery temperature.'),
'CT-002':(
'检验放电限制和供电不足判定。达到器件能力上限后，模型应给出需要处理的失电事件，不能用数值求解失败替代物理供电不足。',
'Verify discharge limits and supply shortfall classification. A physically infeasible request must request an event and must not be mislabeled as a numerical solver failure.',
'无太阳输入，组合三个负载请求与四种电池设置，包括基准、较小放电电流、较高最低电压和低温。每个点独立求解允许电流区间。',
'With no solar input, cross three requests with four battery settings: baseline, reduced discharge current, higher minimum voltage and low temperature. Each sample solves its own allowed current interval.'),
'CT-003':(
'检验设计中电池满电后限制充电的要求。100% SOC 对应负极占比 0.90 与正极占比 0.27；在这一起点仍有太阳富余时，不应继续向电池充电。',
'Verify the design requirement to limit charging at full charge. The configured 100% SOC point is negative fraction 0.90 and positive fraction 0.27. Solar surplus at this state should not continue charging the battery.',
'固定初始 SOC 为 1，负载请求 25 W，分别施加三个辐照度。此用例在覆盖性复核中补充，原因是轨道用例观察到 SOC 超过 1；原有数值误差判据保持不变。',
'Set initial SOC to 1, request 25 W, and apply three irradiances. Coverage review added this case after orbital runs exceeded SOC 1; the original numerical comparison tolerances were not relaxed.'),
'PR-001':(
'检验启停、失电锁存、拒绝启动、同刻指令优先级和重复指令处理。负载失电后，即使日照恢复，也必须等待新的启动指令。',
'Verify start and stop commands, loss-of-supply latching, denied restart, simultaneous command priority and duplicate commands. Restored sunlight alone must not restart a latched load.',
'八组状态与指令覆盖正常停机、可供电启动、不可供电启动、失电、停机与启动同刻发生、重复停机以及未接受的试算事件。试算事件必须被拒绝并保持状态。',
'Eight configurations cover stop, feasible and infeasible start, supply loss, simultaneous stop and start, duplicate stop, and an unaccepted trial event. A trial event must be rejected without changing state.'),
'IV-001':(
'检验接口无效与物理边界两类情况的区分。输入错误不能驱动保护事件；已跨越材料状态范围的试算点应报告需要重新处理的器件边界。',
'Distinguish invalid input from a physical state boundary. Invalid input must not drive protection; a trial state outside material limits must report a device boundary requiring handling.',
'依次测试 240 K 电池温度、运行标识不一致、输入时间不一致、坐标系不支持、太阳方向为零和平均锂占比越界。前五项应无效，最后一项应有效地报告边界事件。',
'Test 240 K battery temperature, mismatched run identity, mismatched time, unsupported frame, zero Sun direction and an out-of-range mean lithium fraction. The first five are invalid; the last is a valid boundary-event report.'),
'DY-001':(
'检验持续日照下电池逐渐充电的过程，以及两种积分器计算的 SOC、电流、电压和热源是否一致。',
'Verify gradual charging in continuous sunlight and agreement of SOC, current, voltage and heat between the independent integrators.',
'太阳正对板面，辐照度 1361 W/m²，负载 200 W，电池恒温 293.15 K，持续 900 s。每 10 s 保存一次结果。',
'Normal solar incidence at 1361 W/m², a 200 W load and a prescribed 293.15 K battery temperature for 900 s. Save results every 10 s.'),
'DY-002':(
'检验从日照进入地影、再回到日照时的供电转换。地影期间太阳发电为零，电池承担负载；恢复日照后太阳再次供电并可能充电。',
'Verify transitions from sunlight into eclipse and back. Solar output is zero in eclipse and the battery supplies the load; sunlight recovery restores array power and possible charging.',
'使用理想化 5400 s 周期，1800 至 3800 s 为完全地影，其余时间辐照度为 1361 W/m²。负载恒为 200 W。该周期是受控测试输入，不是 ISS 或轨道传播器的结果。',
'Use a controlled 5400 s cycle with full eclipse from 1800 to 3800 s and 1361 W/m² otherwise. Load stays at 200 W. This fixture is neither ISS telemetry nor orbit-propagator output.'),
'DY-003':(
'检验计算任务功率需求变化时的电池补偿与充放电切换。这里的阶跃表示功率请求突然改变，不用于评价电路开关波形。',
'Verify battery compensation and charge or discharge transitions when compute demand changes. A step is a sudden change of requested power, not a switching-waveform experiment.',
'太阳辐照度恒为 800 W/m²，每 200 s 将负载依次设为 100、350、550、100 W。温度固定；输入变化点精确分段，分别保留变化前后结果。',
'Hold irradiance at 800 W/m² and request 100, 350, 550 and 100 W in consecutive 200 s intervals. Temperature is fixed. Segment boundaries retain both pre-step and post-step values.'),
'DY-004':(
'检验充电电流被限制时，随着电池状态变化，实际太阳输出与电池发热如何变化。',
'Verify actual solar output and battery heat as the battery state evolves under a charge current limit.',
'持续 900 s，辐照度 1800 W/m²，负载 25 W，单体充电电流下限为 −0.2 A。其余参数保持基准值，限制对象是单体电流，不是整组电流。',
'Run for 900 s at 1800 W/m² and 25 W demand, with cell current bounded below by minus 0.2 A. Other parameters are unchanged; the limit applies to a cell, not the pack current.'),
'DY-005':(
'检验完整的失电、锁存、日照恢复、显式重启和再次停机流程。保护逻辑必须改变负载连接状态，并允许断开负载后的电池继续充电。',
'Verify supply loss, latching, sunlight recovery, explicit restart and a subsequent stop. Protection must change load connectivity while allowing charging with the load disconnected.',
'100 s 时关闭太阳并请求 2500 W，触发供电不足；200 s 恢复正常日照但不发送启动；300 s 才启动，400 s 停止，500 s 再启动。测试持续至 600 s。',
'At 100 s remove sunlight and request 2500 W. Restore normal sunlight at 200 s without a start command; start at 300 s, stop at 400 s and start again at 500 s. End at 600 s.'),
'DY-006':(
'检验电池发热反馈到温度后，温度再影响端电压和电流的闭环。热边界是指定温度的散热端，不是空气对流环境。',
'Verify the loop in which battery heat changes temperature, which in turn changes voltage and current. The thermal boundary is a prescribed heat-sink temperature, not ambient-air convection.',
'太阳输入为零，负载 200 W，初始电池温度 283.15 K。电池热容 5000 J/K，通过 0.8 K/W 热阻连接 273.15 K 散热端，持续 1800 s。这里只验证单电池热节点，不代表完整六节点 Thermal 联调。',
'Use no solar power, a 200 W load, initial battery temperature 283.15 K, heat capacity 5000 J/K, thermal resistance 0.8 K/W and a 273.15 K sink for 1800 s. This is a one-node battery thermal test, not full six-node Thermal integration.'),
'DY-007':(
'检验多个日照与地影周期中的累计能量和状态漂移。长时间结果可以暴露单点功率平衡正确但电量边界缺失的问题。',
'Verify cumulative energy and state drift over repeated sunlight and eclipse cycles. Long trajectories can expose missing charge boundaries despite correct instantaneous power balance.',
'连续执行三个与 DY-002 相同的受控周期，共 16200 s。每 30 s 保存结果，额外保留所有入影和出影边界的左右两侧数据。',
'Repeat the controlled DY-002 cycle three times for 16200 s. Save every 30 s and retain both sides of all eclipse entry and exit boundaries.'),
'NU-001':(
'检验观察到的两侧误差是否受求解精度影响。分别缩小两个求解器的容差和最大步长，确认结果在原验收尺度以内收敛。',
'Check whether numerical precision explains the observed difference. Independently tighten both solvers and reduce the maximum step, requiring changes below one tenth of the original acceptance limit.',
'无太阳输入，负载 200 W，电池由 293.15 K 起步并连接 283.15 K 散热端，持续 1200 s。基准相对容差 10⁻⁸，复核为 10⁻¹⁰；最大步长由 10 s 降为 2 s。',
'Run 1200 s with no solar input, a 200 W load, initial battery temperature 293.15 K and a 283.15 K sink. Tighten relative tolerance from 10 to the power minus 8 to 10 to the power minus 10 and reduce maximum step from 10 s to 2 s.')}

PLOT={
'PV-001':['P_pv_max_W'],'BT-001':['V_B_V','SOC'],'BT-002':['V_B_V','I_B_A'],
'BT-003':['Q_B_W','q_reversible_cell_W'],'BT-004':['V_B_V','I_B_A'],
'PD-001':['P_load_W','I_B_A'],'PD-002':['P_load_W','Q_D_W'],
'CT-001':['P_pv_W','i_A'],'CT-002':['can_supply','event_required'],'CT-003':['i_A','P_pv_W'],
'PR-001':['connected','latched'],'IV-001':['valid','event_required'],
'DY-001':['SOC','I_B_A'],'DY-002':['SOC','P_pv_W'],'DY-003':['P_load_W','I_B_A'],
'DY-004':['i_A','P_pv_W'],'DY-005':['connected','P_load_W'],'DY-006':['T_B_K','Q_B_W'],
'DY-007':['SOC','P_pv_W'],'NU-001':['T_B_K','V_B_V']}
LABELS={
'P_pv_max_W':('太阳最大发电功率 W','Available solar power W'),
'P_pv_W':('太阳实际输出 W','Actual solar power W'),'P_load_W':('负载实际供电 W','Delivered load power W'),
'P_B_W':('电池端口功率 W','Battery terminal power W'),'V_B_V':('电池组电压 V','Pack voltage V'),
'I_B_A':('电池组电流 A','Pack current A'),'Q_B_W':('电池组热源 W','Pack heat W'),
'Q_D_W':('配电损耗 W','Distribution loss W'),'SOC':('剩余电量比例','State of charge fraction'),
'x_n':('负极平均锂占比','Mean negative fraction'),'x_p':('正极平均锂占比','Mean positive fraction'),
'T_B_K':('电池温度 K','Battery temperature K'),'connected':('负载连接标志','Load connected flag'),
'latched':('失电锁存标志','Supply trip latched flag'),'valid':('有效标志','Valid flag'),
'event_required':('待处理事件标志','Event required flag'),'can_supply':('可供电标志','Supply capability flag'),
'reason':('结果原因编码','Result reason code'),'i_A':('单体电流 A','Cell current A'),
'v_cell_V':('单体电压 V','Cell voltage V'),'dx_n_dt':('负极锂占比变化率 1/s','Negative fraction rate 1/s'),
'dx_p_dt':('正极锂占比变化率 1/s','Positive fraction rate 1/s'),
'q_reversible_cell_W':('单体可逆热 W','Cell reversible heat W'),'min_margin':('最小器件约束裕量','Minimum device constraint margin'),
'action':('保护处理编码','Protection action code')}
