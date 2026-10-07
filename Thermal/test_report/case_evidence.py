"""Reader-facing scenario explanations and measured tables for all test projects.

Numbers in result tables come from the retained case records. The existing FE
blocks retain their detailed comparison tables and figures.
"""


SCENARIOS = {
    'DM-001': (
        '本用例检查数据在进入物理计算前是否完整、顺序正确，以及试算状态是否会污染已接受状态。场景为六节点、五连接的构造输入，分别测试正常值、错误值和运行中修改。电池算例固定 T_B=303 K、T_R=300 K、C_B=1000 J/K、R_BR=0.5 K/W，只改变 Q_B 的正负。结果表分别展示符号检查、异常拒绝和只读约束；通过表示接口行为符合约定。',
        'This case checks data completeness and ordering before physics evaluation, and whether trial states contaminate accepted states. A constructed six-node, five-connection scene exercises valid inputs, invalid inputs and mutation during execution. The battery example fixes T_B=303 K, T_R=300 K, C_B=1000 J/K and R_BR=0.5 K/W while changing the sign of Q_B. The result table separates sign handling, invalid-input rejection and immutability; passing establishes the interface contract.'),
    'PA-001': (
        '本用例把材料质量、比热、导热尺寸及安装接触热阻转换为六个热容和五个热阻。先对同一组构造输入独立手算，再改变电池材料与 BR 接触热阻，检查覆盖是否真正改变装配结果。结果表中的基准值和覆盖后值来自同一次参数装配测试；不含温度积分，也不验证参数是否代表某一真实硬件。',
        'This case converts material mass, heat capacity, conduction geometry and contact resistance into six capacitances and five resistances. Independent hand calculations check the constructed inputs; battery material and BR contact overrides then test whether assembly responds correctly. Baseline and overridden values in the table come from the parameter-assembly test. There is no temperature integration or claim that these parameters represent measured hardware.'),
    'EN-001': (
        '本用例检查姿态、位置与太阳方向如何生成每个表面的入射余弦。输入为 400 km 圆轨道一圈的 5555 个时刻、单位姿态、各轴 90° 旋转及组合姿态，另测朝日和对地姿态。用独立向量旋转求参照，并检查日食时太阳辐照度与 Orbit 输出逐值相同。表中误差是入射余弦的绝对误差，不是温度误差。',
        'This case checks how attitude, position and Sun direction produce each surface incidence cosine. Inputs cover 5555 instants of one 400 km circular orbit, identity attitude, 90° rotations about each axis and composite attitudes, plus Sun- and nadir-pointing cases. Independent vector rotations provide the reference, and irradiance must match Orbit exactly through eclipse. Table errors are absolute incidence-cosine errors, not temperature errors.'),
    'EN-002': (
        '本用例把表面朝向、光学参数、辐照度和温度转换为吸热与放热功率。设计算例固定 A=2 m²、α=0.8、ε=0.85、G=1000 W/m²，先改变入射余弦，再比较 200 K、300 K、400 K 的自身辐射。表中的 Q_env 是环境吸热，Q_emit 是向外辐射，均以 W 计；两者尚未相减，也尚未扣除光伏电输出。',
        'This case converts surface orientation, optical properties, irradiance and temperature into absorbed and emitted power. The design example fixes A=2 m², α=0.8, ε=0.85 and G=1000 W/m², varies the incidence cosine, then compares emission at 200 K, 300 K and 400 K. Q_env is absorbed environmental power and Q_emit is outgoing radiation, both in W. They have not yet been subtracted, and photovoltaic electrical output has not yet been deducted.'),
    'EN-003': (
        '本用例验证地球反照与红外这一环境数据源。先在 400 km 圆轨道上改变 β 角与表面朝向，用解析视角系数和独立数值积分核对 W/m²；再按表面积和光学参数换算成整组太阳翼、散热器的吸收功率，与 COMSOL 比较。原验收表采用完整最后一圈的逐点、时间加权均值和峰值；加密表只比较 10920–16320 s 的 16 个共同采样点算术均值，二者不能互换。',
        'This case validates the Earth albedo and infrared data source. At 400 km altitude, β angle and surface orientation vary; analytic view factors and independent quadrature check irradiance in W/m². Surface area and optical properties then convert irradiance to absorbed power for the full solar-array and radiator groups for COMSOL comparison. Original acceptance uses pointwise values, time-weighted means and peaks over the complete last orbit. Refinement instead uses arithmetic means at 16 common samples from 10920–16320 s; the two windows are not interchangeable.'),
    'HT-001': (
        '本用例固定温度与热阻，直接检查 q=(T_起点−T_终点)/R 的数值和符号。BR 电池支路采用 303 K、300 K 和 0.5 K/W；交换两端温度应改变符号，两端等温应得到零。其余四条支路按同一规则核对，正热流表示从连接名称的第一个节点流向第二个节点。这里计算瞬时热流，不推进时间。',
        'This case fixes temperatures and resistances to check q=(T_start−T_end)/R and its sign directly. The BR battery branch uses 303 K, 300 K and 0.5 K/W; swapping temperatures must reverse the sign and equal temperatures must give zero. The other four branches follow the same rule. Positive flow goes from the first node in a connection name to the second. This is an instantaneous heat-flow calculation without time integration.'),
    'HT-002': (
        '本用例把各支路热流和外部功率组成六个温度导数，并检查内部热流在全网求和后抵消。电池算例的 10 W 产热减去 6 W 外流，除以 1000 J/K，得到 0.004 K/s。随机试验种子为 20261005，共 1000 组：温度在各节点声明区间内取样，P_load 为 0–400 W、Q_B 为 −25–25 W、Q_D 为 0–30 W，光伏输出不超过吸收太阳功率。表中同时报告有量纲的守恒残差和用于验收的归一化残差。',
        'This case assembles six temperature derivatives from branch flows and external powers, then checks cancellation of internal flows in the network sum. The battery example subtracts 6 W outflow from 10 W heating and divides by 1000 J/K to obtain 0.004 K/s. Seed 20261005 generates 1000 sets: temperatures within declared node ranges, P_load of 0–400 W, Q_B of −25–25 W and Q_D of 0–30 W, with PV output bounded by absorbed sunlight. The table reports both the dimensional conservation residual and its normalized acceptance measure.'),
    'HT-003': (
        '本用例用三个已知解析解检查时间积分。阶跃试验在 100 s 把计算功率从 0 W 改为 300 W，冷板为 293.15 K，C_J=500 J/K、R_JC=0.1 K/W，理论时间常数为 50 s、稳态升温为 30 K。串联试验再接入 R_CR=0.05 K/W，理论总温升为 45 K。辐射试验以 600 W 恒定吸热平衡自身辐射。固定温度边界用 10^{12} J/K 大热容近似，隔离支路用 10^{12} K/W 大热阻，边界漂移另行验证。',
        'Three known analytic solutions test time integration. At 100 s, computing power steps from 0 W to 300 W with the cold plate at 293.15 K, C_J=500 J/K and R_JC=0.1 K/W, giving a 50 s time constant and 30 K steady rise. The series case adds R_CR=0.05 K/W for a 45 K total rise. The radiation case balances 600 W constant absorption against emission. Fixed-temperature boundaries use a 10^{12} J/K capacitance approximation and isolated branches use 10^{12} K/W resistance; boundary drift is checked separately.'),
    'EC-001': (
        '本用例先保持状态、几何和环境不变，一次只改变一个 Power 端口：P_pv 从太阳翼能量中扣除，P_load 加到 J，Q_B 加到 B，Q_D 加到 D。下表把四种输入的预期导数变化与实际相对误差逐项对齐。随后测试负电池热、限发、无效返回与供电事件，并运行一圈检查 Power 始终读取热模块当前的电池温度。供电程序及电池参数用于软件联调。',
        'With state, geometry and environment fixed, this case changes one Power port at a time: P_pv is removed from the solar array, P_load heats J, Q_B heats B and Q_D heats D. The table aligns each expected derivative change with its measured relative error. Further cases exercise negative battery heat, curtailment, invalid returns and supply events, then run one orbit to check that Power always reads the current thermal battery temperature. The supply program and cell parameters serve software integration tests.'),
    'FE-001': (
        '本用例将 ISS 美国太阳翼等效为一个温度节点 S，测试环境吸热、辐射散热与实际光伏电输出共同作用下的温度变化。三个场景只按输入表改变环境参数；使用有限元相同的面积、面热容和正反面光学参数。参照量是有限元太阳翼平均温度。比较最后一圈的最低、平均、最高温度，并在相同输出时刻比较整条曲线；两类判据均为 3 K，前者通过不能代替后者通过。',
        'The ISS US solar arrays are represented by one temperature node S to test environmental absorption, radiation and actual photovoltaic output together. The three cases vary environmental parameters as listed, using the FE area, areal heat capacity and front/back optics. The reference is FE mean solar-array temperature. Last-orbit minimum, mean and maximum temperatures and simultaneous curve values are both checked against 3 K; passing the statistics does not establish pointwise agreement.'),
    'FE-002': (
        '本用例把 ISS 的 A、B 两个液氨回路分别等效为公共散热节点 R，在冷、平均、热三种环境下共运行六组。每组把有限元回路进热时程直接作为边界输入，因而检验的是给定进热后的散热器响应，而非整套回路供热预测。每回路单面面积 220.728 m²、总热容 1.6132416 MJ/K，输出与同一回路的有限元面板平均温度比较。验收量为第三圈时间平均温度，限值 5 K。',
        'ISS ammonia loops A and B are each represented by radiator node R, producing six runs across cold, mean and hot environments. FE loop heat-input histories are prescribed, so the case tests radiator response to known heating rather than prediction of the complete loop heat supply. Each loop has one-sided area 220.728 m² and total capacitance 1.6132416 MJ/K. The output is compared with the same loop FE panel-mean temperature; acceptance uses the third-orbit time mean with a 5 K limit.'),
    'FE-003': (
        '本用例单独检查设备 J 到冷板 C 的传热路径。平均环境工况下，冷板固定在 2.8°C 冷却液边界；MBSU、DDCU、IEA 共 14 台设备分别输入按回路热量分摊的 P_load，不能直接把铭牌产热全部视为流入冷板的热。后表同时列出冷板接触面积、接触热阻、固体导热热阻、实际 P_load 和温度结果，使参数到温升的关系可以逐项核对。设备平均温差限值为 1 K。',
        'This case isolates the path from equipment J to cold plate C. In the mean environment, the plate uses a 2.8°C coolant boundary. The 14 MBSU, DDCU and IEA units receive P_load apportioned from loop heat; nominal equipment heat cannot all be assumed to enter the cold plate. The table lists contact area, contact resistance, solid-conduction resistance, applied P_load and temperatures so the parameter-to-rise relationship can be checked. The device mean-temperature difference limit is 1 K.'),
    'FE-004': (
        '本用例运行 12 块 V100 和 12 块 A100 两个整星场景，按有限元轨迹重放位置、太阳方向、姿态和功率时程，累计运行五圈。主要检查 J→C→R 传热链路，装配参数为 R_JC=0.00372948 K/W、R_CR=0.00533046 K/W；J、C、R 热容分别约为 234267.9、7996.9、38077.9 J/K。图展示全过程，验收仅取第四、五圈，分别比较 J 与有限元 GPU 基板、R 与有限元散热板的平均温度，限值 5 K。',
        'Two whole-satellite scenes contain 12 V100 and 12 A100 devices. Position, Sun direction, attitude and power histories are replayed from the FE trajectory over five orbits. The main object is the J→C→R path, with R_JC=0.00372948 K/W and R_CR=0.00533046 K/W; J, C and R capacitances are approximately 234267.9, 7996.9 and 38077.9 J/K. The figure shows the full run, but acceptance uses orbits four and five only: J versus FE GPU baseplate and R versus FE radiator mean temperatures, each against 5 K.'),
    'NI-001': (
        '本用例保持 FE-001 平均环境场景的物理参数和负载不变，只改变求解设置。RK45/Radau、两档相对容限、两档绝对容限、两档最大步长和两档输出间隔构成 32 组组合。表中比较收紧容限、更换方法和改变输出方式后的温差，并独立核对日食边界。它验证数值设置是否足够稳定；即使温差很小，也不能据此消除 FE-001 的模型对标偏差。',
        'Physical inputs and load remain those of the FE-001 mean case while numerical settings vary. RK45/Radau, two relative tolerances, two absolute tolerances, two maximum steps and two output intervals form 32 combinations. The table compares tolerance tightening, method changes and output handling, with an independent eclipse-boundary check. It tests numerical stability of these settings; small numerical differences do not remove the model-to-FE discrepancy in FE-001.'),
    'NI-002': (
        '本用例检查 24 h 联合运行的调用顺序、事件处理、状态归属和可重复性。场景为 400 km、倾角 51.6° 圆轨道，太阳翼入射角 55°，初始电池温度 293.15 K，基准请求 60 W；52898.5–53798.5 s 内请求从 60 W 升至 250 W。除正常日食和负载启停外，分别测试注入供电不足、实际电池约束和独立运行中的 invalid 返回。下表区分故障注入与物理约束，重复性比较覆盖整个归档。',
        'This 24 h coupled case checks call order, event handling, state ownership and repeatability. It uses a 400 km circular orbit at 51.6° inclination, 55° solar incidence, initial battery temperature 293.15 K and a 60 W base request. During 52898.5–53798.5 s the request rises from 60 W to 250 W. Beyond eclipse and load commands, it separately tests injected supply loss, an actual battery constraint and an invalid return in an independent run. The table distinguishes injected and physical events; repeatability covers the whole archive.'),
    'NI-003': (
        '本用例从七个 SimReady 实例及其 USD 物理尺寸装配模型，检查显示缩放不会改变物理面积，材料和安装覆盖会改变相应热参数。两个独立卫星场景采用不同初始温度和电池状态，均以 60 W 请求运行 5600 s，再复跑并在独立进程核对归档。表中分别展示装配准确性与实际状态差异；不同卫星温度不同是独立状态的证据，不是误差。',
        'Seven SimReady instances and their USD physical dimensions assemble the model. Display scaling must preserve physical area, while material and installation overrides must change the corresponding thermal parameters. Two independent satellite scenes start from different temperatures and battery states, run for 5600 s with a 60 W request, and are repeated with separate-process archive checks. The table separates assembly accuracy and actual state differences; different satellite temperatures demonstrate independent states rather than an error.'),
}


CONTEXT = {
    'DM-001': (
        '这是计算前的数据检查，不设置真实轨道或冷热环境。“六节点”是用六个温度分别代表太阳翼、计算设备、冷板、电池、电源设备和散热板；“试算”是求解器尚未确认的一次尝试，失败时不得改写已确认的温度。',
        'This is a data check before calculation, with no physical orbit or cold/hot environment. Six nodes mean six representative temperatures for the solar array, computing equipment, cold plate, battery, power equipment and radiator. A trial is an unaccepted solver attempt; a failed attempt must not overwrite accepted temperatures.'),
    'PA-001': (
        '场景是按材料与安装关系搭建热网络。热容表示使组件升高单位温度需要多少热量；热阻表示传递单位热功率需要多大温差。接触热阻来自两个部件的接合处。“覆盖值”是本次安装明确指定的参数，用来替换资产默认值。',
        'The scene constructs a thermal network from materials and installation connections. Capacitance is the heat needed for a unit temperature rise; resistance is the temperature difference needed to carry a unit heat flow. Contact resistance belongs to the joint between parts. An override is an installation-specific value replacing the asset default.'),
    'EN-001': (
        '这里先问“太阳照到哪个面、照得多斜”，不求温度。姿态描述星体相对空间的转向；表面法向是垂直于该面的向外方向。入射余弦为太阳方向与法向夹角的余弦，正对为 1、侧对为 0、背对为负。日食是地球挡住太阳：本影完全遮挡，半影仅遮挡一部分。',
        'This case asks which face sees the Sun and at what angle, without solving temperature. Attitude is spacecraft orientation; a surface normal points outward perpendicular to the face. The incidence cosine is the cosine between the normal and Sun direction: 1 facing the Sun, 0 edge-on and negative facing away. Eclipse means Earth blocks the Sun: fully in umbra and partly in penumbra.'),
    'EN-002': (
        '场景是受控照射一块平板，便于用手算逐项核对。A 是受照表面的实际面积，α 是太阳光被吸收的比例，ε 是表面发射热辐射的能力。反照是地球反射的太阳光，红外是地球自身发出的热辐射；它们与太阳直射分别输入，不能把日食中的全部外热流都置零。',
        'A plate under controlled illumination permits term-by-term hand checks. A is actual surface area, α the absorbed fraction of sunlight and ε the ability to emit thermal radiation. Albedo is sunlight reflected by Earth; infrared is Earth thermal emission. They enter separately from direct sunlight, so eclipse must not set all external heating to zero.'),
    'EN-003': (
        '这里问“卫星的这个面能看见多少地球，其中多少是被太阳照亮的地球”。对地指法向朝向地心，背地指反向，侧向指法向垂直于当地竖直方向；跟踪太阳指法向随太阳方向转动。视角系数衡量地球对该面的辐射贡献。冷、平均、热的具体环境定义见第 2 章；加密的是辐射积分的地球采样点，不是卫星热结构网格。',
        'The question is how much Earth a face sees and how much of that Earth is sunlit. Nadir-facing means the normal points toward Earth centre, zenith-facing means away, lateral means perpendicular to the local vertical, and Sun-tracking means following the Sun. The view factor weights Earth radiation reaching the face. Chapter 2 defines the cold, mean and hot environments. Refinement increases Earth radiation-integration samples, not spacecraft thermal-mesh density.'),
    'HT-001': (
        '场景是两个温度已知的部件通过一条热阻相连，用来检查热是否从高温端流向低温端。BR 就是电池 B 到散热板 R；其余路径名称也按两个端点命名。此项没有轨道环境，温度是给定输入。',
        'Two parts at prescribed temperatures are joined by a thermal resistance to check flow from hot to cold. BR denotes battery B to radiator R; other path names likewise identify their endpoints. There is no orbital environment in this check: temperatures are prescribed inputs.'),
    'HT-002': (
        '这里检查每个部件的“进热减出热”是否等于储热速度。温度导数是此刻每秒升温或降温多少，不是下一时刻的温度。随机场景是扩大输入覆盖的构造样本；固定随机种子使别人能生成同一批样本。归一化残差是将功率不平衡除以测试定义的功率尺度。',
        'The check asks whether heat entering minus heat leaving equals each part’s storage rate. A temperature derivative is the rise or fall per second now, not the next temperature. Random scenes are constructed samples that broaden input coverage; a fixed seed makes the sample set reproducible. The normalized residual divides power imbalance by the power scale defined in the test.'),
    'HT-003': (
        '这是三种可手算的理想台架：突然打开恒定热源、让热量通过串联连接、让散热板只靠辐射排热。“阶跃”是功率瞬间切换；“稳态”是进出热量平衡后温度不再变化；“时间常数”描述温度接近新稳态的速度。没有轨道日食或变化的环境热流。',
        'Three ideal benches have hand-solvable answers: abruptly switch on a constant heater, pass heat through series connections, and reject heat by radiation alone. A step is an instantaneous power change; steady state means balanced heat flows and constant temperature; the time constant describes approach to the new steady state. No orbital eclipse or varying environmental flux is applied.'),
    'EC-001': (
        '场景是把供电计算与热计算接在一起，检查电功率有没有加到正确的温度节点。端口是两模块交换的一个有单位的数值。P_pv 是太阳翼送出的电功率，P_load 是计算设备的用电产热，Q_B、Q_D 是电池和电源设备的净热功率；负 Q_B 表示吸热。限发是主动少取光伏电能，供电不足是实际输出达不到请求。',
        'The scene connects electrical and thermal calculations to check that power reaches the correct temperature node. A port is a value with units exchanged between modules. P_pv is electrical power exported by the array, P_load is computing-load heating, and Q_B and Q_D are net battery and power-equipment heat; negative Q_B means heat absorption. Curtailment deliberately reduces PV extraction; supply loss means output falls short of the request.'),
    'FE-001': (
        '对象是国际空间站太阳翼，不是把卫星放进某个温度的恒温箱。第 2 章给出三组环境：冷、平均工况每圈有约 36.1 min 日食，热工况全圈日照。太阳翼正面始终跟踪太阳；从 290 K 开始，正反面分别吸热和辐射，发电取走直射入射功率的 0.073。温度由能量收支算出，因此“设计热”不保证每个瞬间都比其他工况热。',
        'The object is the ISS solar array, rather than a spacecraft in a temperature-controlled chamber. Chapter 2 defines the environments: cold and mean cases have about 36.1 min eclipse per orbit, while the hot case stays sunlit. The front tracks the Sun. Starting at 290 K, both faces absorb and radiate; electrical generation removes 0.073 of incident direct solar power. Energy balance determines temperature, so “design hot” need not be hottest at every instant.'),
    'FE-002': (
        'A、B 是两套把设备废热运到舱外散热器的液氨冷却回路，不是两种 GPU。每回路有三个散热器单元、合计 24 块面板。日照时面板侧对太阳以减少直射，日食时正面朝地。环境采用第 2 章三组参数；涂层 α/ε 在冷、平均、热工况分别为 0.15/0.91、0.20/0.91、0.24/0.90。图中变化同时受进热、朝向和外部辐射影响。',
        'A and B are two ammonia cooling loops carrying equipment waste heat to external radiators, not GPU types. Each loop has three radiator units and 24 panels. Panels face edge-on to sunlight to reduce direct heating and face Earth during eclipse. Environments follow Chapter 2; coating α/ε is 0.15/0.91, 0.20/0.91 and 0.24/0.90 for cold, mean and hot cases. Curves reflect heat input, orientation and external radiation together.'),
    'FE-003': (
        '对象是安装在冷板上的空间站电气设备：MBSU 为主母线开关单元，DDCU 为直流变换单元，IEA 为综合设备组件。冷板是把设备热量传给流动冷却液的接触部件。“平均环境”指第 2 章的 nom0 参考数据；模块子试验只保留设备至冷板的导热，并以恒定冷却液温度代表下游冷却系统。',
        'The objects are ISS electrical units mounted on cold plates: MBSU is a main bus switching unit, DDCU a DC-to-DC converter unit, and IEA an integrated equipment assembly. A cold plate transfers equipment heat to flowing coolant. “Mean environment” selects the nom0 reference in Chapter 2; this module subtest retains equipment-to-plate conduction with fixed coolant temperature representing downstream cooling.'),
    'FE-004': (
        '对象是一颗装有 GPU 计算设备的卫星，V100 和 A100 是两种 GPU 型号。热量由设备经冷板/热输运结构送到散热板。此项使用单独的整星轨迹，不套用 ISS 冷热三组参数：反照率为 0.30、地球红外为 237 W/m²，太阳常数见下表。星体 +Z 朝地、+X 沿轨道法向，散热面朝 ±Y。功率按有限元时程变化；平台产热与 GPU 产热均计入。',
        'The object is a satellite carrying GPU computing equipment; V100 and A100 are GPU models. Heat travels through the cold plate/transport structure to radiators. This separate whole-satellite trajectory does not use the three ISS environments: albedo is 0.30, Earth infrared 237 W/m², and solar constant is tabulated below. Body +Z points to Earth, +X follows the orbit normal and radiator faces point along ±Y. Power follows the FE history and includes platform and GPU heating.'),
    'NI-001': (
        '这里检查“计算方法改得更精细，答案是否还一样”。RK45 和 Radau 是两种温度积分算法；容限决定允许的局部数值误差，最大步长限制一次内部推进多远，输出间隔决定多久记录一次。环境沿用第 2 章 nom0；另加负载启停以检查不连续边界。拒绝步是误差过大而被求解器放弃的一次试算。',
        'This asks whether a more accurate numerical calculation gives the same answer. RK45 and Radau are temperature-integration algorithms; tolerances control permitted local numerical error, maximum step limits an internal advance, and output interval controls recording frequency. The environment is nom0 in Chapter 2, with load start/stop events added to test discontinuities. A rejected step is a trial discarded for excessive error.'),
    'NI-002': (
        '这是包含轨道日照、光伏发电、电池供电和温度反馈的整日软件联调。采用独立环境设置：地球反照率 0.30、红外 237 W/m²、太阳常数 1361 W/m²；轨道计算再加入日食。太阳翼法向与太阳夹角 55°，表示斜照。“注入故障”是测试主动制造的供电异常，“物理约束”是测试电池模型自己达到限值；二者分开判定。',
        'This full-day software integration includes orbital lighting, PV generation, battery supply and temperature feedback. Its separate environment uses albedo 0.30, infrared 237 W/m² and solar constant 1361 W/m², with eclipse added by the orbit calculation. A 55° angle between array normal and Sun means oblique illumination. An injected fault is imposed by the test; a physical constraint arises when the test battery model reaches its own limit. They are judged separately.'),
    'NI-003': (
        '场景从可仿真的资产实例装配一颗卫星，再建立第二颗卫星检查彼此状态是否独立。SimReady 指带有仿真所需参数的资产，USD 是记录场景层级、尺寸与实例关系的文件格式。显示缩放只改变画面大小，物理尺寸用于计算面积与质量。初始电池状态包括荷电状态，即当前储电量相对容量的比例。',
        'A satellite is assembled from simulation-ready asset instances, then a second satellite checks state independence. SimReady assets carry simulation parameters; USD files record scene hierarchy, dimensions and instances. Display scale changes the appearance, while physical dimensions determine area and mass. Initial battery state includes state of charge, the stored charge as a fraction of capacity.'),
}


def context(cid, lang):
    return CONTEXT[cid][0 if lang == 'cn' else 1]


ENVIRONMENT = {
    'cn': {
        'intro': '本报告的“设计冷工况、平均环境工况、设计热工况”来自 ISS 有限元输入，表示三组外部辐射与轨道照明条件。它们不表示设定的空气温度，也不是温度计算结果的分组。三组均为高度 400 km 的圆轨道，周期约 5553.6 s（92.6 min）。β 角是太阳方向与轨道平面的夹角；β=0° 表示太阳方向在轨道平面内，β=75° 表示太阳从接近轨道面法线的方向照来。它不同于轨道相对赤道的倾角。',
        'caption': 'ISS 冷、平均、热环境的实际输入与日照条件',
        'headers': ['环境 / 数据标识', 'β 角', '太阳常数 W/m²', '地球反照率', '地球红外 W/m²', '每圈日食 / 日照'],
        'rows': [
            ['设计冷 / cold0', '0°', '1321', '0.20', '206', '约 36.1 min 日食，其余日照'],
            ['平均环境 / nom0', '0°', '1371', '0.31', '241', '约 36.1 min 日食，其余日照'],
            ['设计热 / hot75', '75°', '1423', '0.40', '286', '无日食，全圈日照'],
        ],
        'notes': [
            '设计冷工况结合较低的辐射输入和每圈较长的遮阳时段，用于检查冷却及再受光升温。平均环境保持相同日食几何，采用居中的辐射参数作为基准；“平均”不是把冷热两次的结果取平均，也不是气候统计均值。设计热工况结合较高辐射输入和连续日照，用于检查持续受热。这些是本模型的设计组合，并不证明所有部件的最高或最低温度都出现在对应名称的工况。',
            '太阳常数是未被地球遮挡时、垂直于光线的单位面积接收的太阳功率；实际表面直射吸热还要乘受照比例、入射余弦、面积和吸收率。地球反照率是反射太阳光的比例；地球红外是地球向外发出的热辐射通量，传到卫星表面的量还受朝向、可见地球范围与发射率影响。表中日食由参考模型的圆柱地影几何得到，不表示所有轨道都具有同样的日食时长。',
            '本表用于 EN-003 的 ISS 对比、FE-001、FE-002，以及使用 nom0 数据的 FE-003、NI-001。太阳翼与散热器的朝向和光学参数分别在对应项目说明。FE-004、NI-002、NI-003 使用各自场景；数据对象、参数装配与解析试验采用构造输入，不应自动套入这三组环境。环境来源为 iss_fem/model/iss_spec.py；日食与周期来源为各工况 summary.json。',
        ],
    },
    'en': {
        'intro': '“Design cold”, “mean environment” and “design hot” are three prescribed external-radiation and orbital-lighting conditions from the ISS FE inputs. They are neither specified air temperatures nor groups classified by computed temperatures. All use a 400 km circular orbit with period about 5553.6 s (92.6 min). β is the angle between the Sun direction and orbital plane: β=0° puts the Sun direction in that plane, while β=75° places it close to the plane normal. It differs from orbital inclination relative to the equator.',
        'caption': 'Actual Inputs and Lighting for the ISS Cold, Mean and Hot Environments',
        'headers': ['Environment / Data ID', 'β (°)', 'Solar constant W/m²', 'Earth albedo', 'Earth infrared W/m²', 'Eclipse / Sunlight per Orbit'],
        'rows': [
            ['Design cold / cold0', '0°', '1321', '0.20', '206', 'About 36.1 min eclipse; otherwise sunlit'],
            ['Mean / nom0', '0°', '1371', '0.31', '241', 'About 36.1 min eclipse; otherwise sunlit'],
            ['Design hot / hot75', '75°', '1423', '0.40', '286', 'No eclipse; continuously sunlit'],
        ],
        'notes': [
            'Design cold combines lower radiation inputs with a long shaded part of each orbit to examine cooling and reheating. The mean environment keeps that eclipse geometry and uses intermediate radiation parameters as a baseline: “mean” is neither the average of cold/hot outputs nor a climatological mean. Design hot combines higher radiation inputs with continuous sunlight to examine sustained heating. These are model design combinations; the names do not establish where every part reaches its highest or lowest temperature.',
            'Solar constant is unshadowed solar power per unit area normal to the rays. Actual direct absorption also depends on illumination fraction, incidence cosine, area and absorptivity. Earth albedo is the reflected fraction of sunlight. Earth infrared is the outward thermal radiant flux; its absorbed contribution at the spacecraft also depends on orientation, visible Earth and emissivity. Eclipse duration follows the reference cylindrical-shadow geometry and does not apply to all orbits.',
            'This table applies to the ISS comparison in EN-003, FE-001, FE-002, and the nom0 references used by FE-003 and NI-001. Array/radiator orientation and optical properties are defined in their projects. FE-004, NI-002 and NI-003 use their own scenes. Data, assembly and analytic checks use constructed inputs, not these environments by default. Environment values come from iss_fem/model/iss_spec.py; eclipse and period come from each case summary.json.',
        ],
    },
}


def scenario(cid, lang):
    return SCENARIOS[cid][0 if lang == 'cn' else 1]


def table_spec(cid, lang, m):
    """Return input/reference/measured rows; five existing benchmark blocks supply their own tables."""
    def tr(cn, en):
        return cn if lang == 'cn' else en

    def f(v, n=6):
        return f'{v:.{n}g}'.replace('-', '−')

    def row(cn, en, ref, actual):
        return [tr(cn, en), ref, actual]

    rows = []
    if cid == 'DM-001':
        rows = [row('电池产热 Q_B=+10 W', 'Battery heat Q_B=+10 W', '(10−6)/1000 = 0.004 K/s', f(m['dT_B_dt_K_s_by_Q_B_W']['+10'])+' K/s'),
                row('电池吸热 Q_B=−10 W', 'Battery heat Q_B=−10 W', '(−10−6)/1000 = −0.016 K/s', f(m['dT_B_dt_K_s_by_Q_B_W']['-10'])+' K/s'),
                row('错误维数、数值或时标', 'Invalid dimensions, values or timing', tr('63 项均拒绝', 'Reject all 63 inputs'), str(m['invalid_constructions']['rejected_as_specified'])+'/63'),
                row('尝试修改只读参数', 'Attempt parameter mutation', tr('24 项均拒绝', 'Refuse all 24 attempts'), str(m['parameter_modification_attempts']['refused'])+'/24')]
    elif cid == 'PA-001':
        rows = [row('1 kg × 1000 J/(kg K)', '1 kg × 1000 J/(kg K)', 'C=1000 J/K', f(m['design_4_5_example_C_J_K'])+' J/K'),
                row('MBSU 体积 × 密度 × 比热', 'MBSU volume × density × heat capacity', '0.94×0.84×0.51×300×900 J/K', f(m['mbsu_block_C_J_K'],8)+' J/K'),
                row('电池材料覆盖前 → 后', 'Battery material before → after override', tr('只改变相应热容', 'Update the affected capacitance'), f(m['C_B_baseline_J_K'])+' → '+f(m['C_B_override_J_K'])+' J/K'),
                row('BR 接触覆盖前 → 后', 'BR contact before → after override', tr('保留导热项，更新接触项', 'Keep conduction; update contact'), f(m['R_BR_baseline_K_W'])+' → '+f(m['R_BR_override_K_W'])+' K/W'),
                row('基准与覆盖后的全部 C、R', 'All baseline and overridden C, R', tr('相对误差 ≤ 1×10^{−12}', 'Relative error ≤ 1×10^{−12}'), f(max(m[k] for k in ('max_rel_error_C_baseline','max_rel_error_R_baseline','max_rel_error_C_override','max_rel_error_R_override'))))]
    elif cid == 'EN-001':
        rows = [row('单位姿态及各轴旋转', 'Identity and axis rotations', tr('独立旋转；误差 ≤ 1×10^{−12}', 'Independent rotation; error ≤ 1×10^{−12}'), f(max(m['step1_orbit_constructed_max_error'].values()))),
                row('一圈姿态变化，5555 个时刻', 'Varying attitude, 5555 orbital instants', tr('入射余弦误差 ≤ 1×10^{−12}', 'Incidence cosine error ≤ 1×10^{−12}'), f(m['max_cos_incidence_error'])),
                row('日照、半影与本影', 'Sunlight, penumbra and umbra', tr('G 与 Orbit 完全一致', 'G identical to Orbit'), tr(f"{m['g_compared']} 次比较，{m['g_mismatches']} 次不符", f"{m['g_compared']} comparisons, {m['g_mismatches']} mismatches")),
                row('错误坐标系、法向或缺少环境记录', 'Invalid frame, normal or missing environment', tr('51 项均拒绝', 'Reject all 51 inputs'), str(m['abnormal_rejected_deterministically'])+'/51')]
    elif cid == 'EN-002':
        results = m['design_example_4_4']['results']
        for key,cosine,name in [('facing',1,('正对太阳','Sun-facing')),('oblique',0.5,('斜对太阳','Oblique')),('edge_on',0,('侧对太阳','Edge-on')),('away',-1,('背对太阳','Sun-away'))]:
            rows.append(row(name[0]+f'，cosθ={cosine}',name[1]+f', cosθ={cosine}',f'Q_env=1600×max({cosine},0) W',f(results[key]['300 K']['Q_env_S'])+' W'))
        rows.append(row('自身辐射 200 K → 400 K','Emission 200 K → 400 K','Q_emit(400)/Q_emit(200)=16',f(results['facing']['200 K']['Q_emit_S'])+' → '+f(results['facing']['400 K']['Q_emit_S'])+' W'))
    elif cid == 'HT-001':
        rows = [row('BR：303 K → 300 K，R=0.5 K/W','BR: 303 K → 300 K, R=0.5 K/W','q_BR=+6 W',f(m['q_BR_battery_example_W'])+' W'),
                row('BR：300 K → 303 K，R=0.5 K/W','BR: 300 K → 303 K, R=0.5 K/W','q_BR=−6 W',f(m['q_BR_reversed_W'])+' W'),
                row('BR：两端均为 300 K','BR: both ends at 300 K','q_BR=0 W',f(m['q_BR_equal_end_temperatures_W']['300 K'])+' W'),
                row('SR / JC / CR / BR / DR 基准热流','SR / JC / CR / BR / DR baseline flows',tr('按五条路径分别手算','Independent calculation per path'),' / '.join(f(v) for v in m['q_W_base_W'].values())+' W'),
                row('全部热流比较','All heat-flow comparisons',tr('相对误差 ≤ 1×10^{−12}','Relative error ≤ 1×10^{−12}'),f(m['max_relative_error']))]
    elif cid == 'HT-002':
        r=m['random_cases']
        rows=[row('设计电池算例','Design battery example','(10−6)/1000 = 0.004 K/s',f(m['battery_example']['dT_B_dt_K_s'])+' K/s'),
              row('1000 组全网热平衡','1000 network energy balances',tr('T1 残差应接近 0 W','T1 residual near 0 W'),f(r['t1_residual_max_W'])+' W'),
              row('按输入热功率归一化','Normalize by input heat power','|T1 residual| / P_in ≤ 1×10^{−12}',f(r['t1_ratio_max_heat_input'])),
              row('五条内部支路成对抵消','Cancellation of five internal branches',tr('改变热阻不引入净热量','Changing resistance adds no net heat'),f(m['sign_bookkeeping_detail']['sum_abs_max_W'])+' W'),
              row('随机样本的电池热符号','Battery heat signs in random inputs',tr('覆盖正值和负值','Cover positive and negative heat'),tr(f"正 {r['coverage']['Q_B_positive']}，负 {r['coverage']['Q_B_negative']}",f"Positive {r['coverage']['Q_B_positive']}, negative {r['coverage']['Q_B_negative']}"))]
    elif cid == 'HT-003':
        rows=[row('300 W 阶跃，600 s','300 W step, 600 s','τ=50 s; ΔT∞=30 K',tr('最大瞬态误差 ','Maximum transient error ')+f(m['step_error_max_K'])+' K'),
              row('300 W 串联链路，3000 s','300 W series path, 3000 s','ΔT_JR=300×(0.1+0.05)=45 K',f(m['series_dT_JR_numerical_K'],10)+' K'),
              row('600 W 辐射平衡，4000 s','600 W radiation balance, 4000 s',f(m['radiation_T_eq_analytic_K'],10)+' K',f(m['radiation_T_end_numerical_K'],10)+' K'),
              row('固定冷板边界漂移','Fixed cold-plate boundary drift','≤ '+f(m['step_cold_plate_drift_hand_bound_K'])+' K',f(m['step_cold_plate_drift_K'])+' K')]
    elif cid == 'EC-001':
        for port,node,sign,desc in [('P_pv_W','S','−',('光伏电输出','PV electrical output')),('P_load_W','J','+',('计算负载','Computing load')),('Q_B_W','B','+',('电池净产热','Net battery heat')),('Q_D_W','D','+',('供电设备损耗','Power-equipment loss'))]:
            rows.append(row(desc[0]+' '+port,desc[1]+' '+port,f'Δ(dT_{node}/dt)={sign}ΔP/C_{node}',tr('最大相对误差 ','Maximum relative error ')+f(m[f'step1_{port}_max_relative_error'])))
        rows.append(row('一圈联合运行','One-orbit coupled run',tr('电池温度由 Thermal 唯一更新','Thermal alone updates battery temperature'),tr(f"{m['step5_power_calls']} 次 Power 调用均配对",f"All {m['step5_power_calls']} Power calls paired")))
    elif cid == 'NI-001':
        rows=[row('相对和绝对容限同时收紧 100 倍','Tighten both tolerances 100-fold','max |ΔT| ≤ 0.01 K',f(max(v['max_K'] for v in m['tighten_both']))+' K'),
              row('RK45 与 Radau','RK45 versus Radau','max |ΔT| ≤ 0.01 K',f(max(v['max_K'] for v in m['rk45_vs_radau']))+' K'),
              row('全部设置的日食定位','Eclipse location for all settings',tr('相对解析边界 ≤ 1 s','Difference from analytic boundary ≤ 1 s'),f(m['eclipse_boundaries']['max_error_s_all_runs'])+' s'),
              row('直接环境与环境表插值','Direct environment versus interpolated table',tr('同一物理输入的辅助比较','Supplementary same-input comparison'),f(m['exact_run']['table_run_last_orbit_max_diff_K'])+' K')]
    elif cid == 'NI-002':
        rows=[row('正常联合运行 86400 s','Normal coupled run, 86400 s',tr('全部输出有效','All outputs valid'),str(m['step1_output_samples'])+tr(' 个样本',' samples')),
              row('已知窗口注入供电不足','Supply-loss injection in a known window',tr('定位后断开负载','Locate event and disconnect load'),'t='+f(m['step2_injected_event_s'],10)+' s'),
              row('电池约束导致的实际供电不足','Physical battery-constraint supply loss',tr('爬升请求时检测物理约束','Detect the constraint during the request ramp'),'t='+f(m['step2_physical_event_s'],11)+' s; P='+f(m['step2_physical_request_W'])+' W'),
              row('独立 invalid 返回试验','Separate invalid-return trial',tr('停止且不接受无效试算','Stop without accepting the invalid trial'),'t='+f(m['step2_invalid_time_s'])+' s'),
              row('同输入再次运行','Repeat identical inputs',tr('整个归档相同','Identical complete archives'),tr(f"{m['step5_leaves_compared']} 项，差异 {m['step5_different_leaves']}",f"{m['step5_leaves_compared']} leaves, {m['step5_different_leaves']} differences"))]
    elif cid == 'NI-003':
        rows=[row('物理几何到面积与质量','Physical geometry to area and mass',tr('相对误差 ≤ 0.1%','Relative error ≤ 0.1%'),f(m['step1_max_rel_error_area'])+' / '+f(m['step1_max_rel_error_mass'])),
              row('物理参数到热容与热阻','Physical inputs to capacitance and resistance',tr('与独立手算一致','Agreement with independent hand calculation'),tr('相对误差 ','Relative errors ')+f(m['step1_max_rel_error_C'])+' / '+f(m['step1_max_rel_error_R'])),
              row('Sat01：T_B 初值 → 5600 s','Sat01: T_B initial → 5600 s',tr('独立推进状态','Evolve independent state'),f(m['step5_Sat01_initial_T_K'][3])+' → '+f(m['step5_Sat01_final_T_K'][3])+' K'),
              row('Sat02：T_B 初值 → 5600 s','Sat02: T_B initial → 5600 s',tr('独立推进状态','Evolve independent state'),f(m['step5_Sat02_initial_T_K'][3])+' → '+f(m['step5_Sat02_final_T_K'][3])+' K'),
              row('覆盖后的有效材料密度','Effective density after material override','2810 kg/m³',tr('来源记录保留 2810 kg/m³','Provenance retains 2810 kg/m³'))]
    if not rows:
        return None
    return {'caption': cid + tr(' 具体输入、参照与实测结果',' Inputs, References and Measured Results'),
            'headers': [tr('试验场景与输入','Scenario and Input'),tr('参照或预期','Reference or Expectation'),tr('实测结果','Measured Result')],
            'rows':rows}
