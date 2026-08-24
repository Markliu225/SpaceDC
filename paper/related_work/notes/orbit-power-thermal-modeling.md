# 类别笔记：卫星轨道电源热建模工具与精度验证

本类别覆盖卫星电源建模工具、卫星电源系统设计与管理、热模型对遥测的实时校验、轨道传播精度基准以及通用航天动力学仿真框架。这些工作共同构成 SpaceDC 物理引擎的对照背景。SpaceDC 的差异在于把轨道、电源、热控与 GPU 大模型推理逐秒耦合在同一引擎里，轨道电热三个模块对 STK 11.6 完成数值验证，并且存在热到算力的真实反馈回路，结构温度会压缩 GPU 的 DVFS 功率预算从而降低推理吞吐。

## 1. Developing a Power Modelling Tool for CubeSats

引用信息：Tom Etchells and Lucy Berthoud. Developing a Power Modelling Tool for CubeSats. 33rd Annual AIAA/USU Conference on Small Satellites, SSC19-WP1-16, Logan, Utah, 2019. University of Bristol. 本地文件 cubesat-power-tool-smallsat19.pdf，已下载。

研究的问题：立方星团队普遍缺少公开可用的电源子系统设计工具，太阳能发电功率取决于轨道、姿态、帆板布局、太阳位置与地影，展开帆板还引入自遮挡，解析计算困难，需要一个可配置的计算模型。

方法：作者用 MATLAB 实现名为 PowerCubeSat 的功率模型，轨道传播与地影事件交给 NASA 的 GMAT 完成。模型分为轨道模型、几何模型、指向模型与光照模型四个部分，几何用面板顶点与法向描述，指向模型支持对地与对日两种模式，用两次基变换把星体几何转到太阳视角坐标系后计算有效面积，功率由太阳常数、电池效率、固有退化、寿命退化、余弦损失与面板面积的乘积给出。工具带图形界面并在 GitHub 开源。

关键结论与数字：模型与 Thales Alenia Space 的 Power Sim 工具做了对比验证。ISS 类轨道上各面板峰值功率误差为 2.8 percent 到 9.1 percent，高倾角轨道误差为 0.0 percent 到 0.3 percent。3U 星体安装帆板的平均功率落在 6 到 7 瓦，与文献给出的无展开帆板立方星功率范围一致。作者明确说明缺少真实遥测数据，验证只覆盖指向与光照模型，自遮挡计算尚未验证。

与 SpaceDC 的关系：这是与 SpaceDC 电源模块最接近的公开工具类工作，同样计算轨道、姿态与帆板几何决定的发电功率，同样采取与成熟商业工具对比的验证路线。SpaceDC 的太阳矢量、圆锥地影与发电模型对 STK 11.6 的验证在方法论上与它对 Power Sim 的验证同类。

它没有覆盖而我们覆盖的地方：它只建模发电功率，没有电池充放电、没有热模型、没有载荷功耗，更没有算力负载。验证只有功率一个维度。SpaceDC 把轨道、电源、热控与 GPU 推理逐秒耦合，验证覆盖轨道电热三个模块，并提供搭建向导、what-if 对比与三维可视化。

## 2. Design and Management of Satellite Power Systems

引用信息：Jinkyu Lee, Eugene Kim, and Kang G. Shin. Design and Management of Satellite Power Systems. Proceedings of the 34th IEEE Real-Time Systems Symposium, RTSS 2013, pages 97 to 106, Vancouver, Canada, December 2013. 本地文件 satellite-power-rtss13.pdf，已下载。

研究的问题：卫星电源供给由日照期与地影期交替决定，电池放电行为非线性，任务功耗周期性变化。问题是如何在发射前离线确定太阳帆板与电池的最优配置保证全寿命期任务不断电，以及发射后如何在线管理功率让任务以尽可能高的服务质量版本运行。

方法：作者把卫星视为信息物理系统，先分析供电与需电的特性，推导帆板发电功率下界、整组电池荷电状态的上界与功耗上界，证明只要轨道周期首尾荷电状态存在不减的不动点则功率充足性得到保证。基于该不动点对不同帆板与电池配置求解可行性并挑选帕累托最优配置完成离线设计。在线阶段提出动态版本执行方法，利用荷电状态实际值与下界之间的裕量自适应提升任务版本。电池行为用 Dualfoil 电化学仿真器模拟，案例采用真实立方星的架构与参数。

关键结论与数字：日照期发电功率下界约 2.3 瓦。锂电池在 2C、3C 与 4C 放电倍率下相对 1C 分别损失 4.3 percent、10.0 percent 与 14.6 percent 的可用能量，休息期存在电压恢复效应。仿真表明该方法能找到帕累托最优的帆板电池配置，动态版本执行在不破坏功率充足性的前提下提高了任务服务质量。

与 SpaceDC 的关系：该文与 SpaceDC 一样把周期性日照供电、电池荷电状态与负载功耗放进同一个逐周期的能量收支框架，其电池非线性与放电倍率损失是 SpaceDC 电源模块建模时需要参照的物理事实。它的任务版本思想与 SpaceDC 里工作负载受功率预算约束的思路同源。

它没有覆盖而我们覆盖的地方：它没有热模型，温度只作为电池效率的外生参数出现。它的负载是抽象的周期任务而不是真实 GPU 推理，不存在热压缩功率预算再降低吞吐的反馈回路。它的验证靠 Dualfoil 与仿真而没有与商业整星工具对标。SpaceDC 用 STK 11.6 做轨道电热三模块的数值验证，并把大模型推理性能作为一等公民建模。

## 3. Rationalization of Thermal Simulators for Operations, Real Time Thermal Flight Correlation

引用信息：Francois Brunetti, Vincent Vadez, Alexandre Darrau, Maxime Andre, and Thierry Basset. Rationalization of Thermal Simulators for Operations, Real Time Thermal Flight Correlation. 54th International Conference on Environmental Systems, ICES-2025-318, Prague, Czech Republic, July 2025. 作者单位为 Dorea Technology、欧洲空间局、法国国家空间研究中心与 Thales Alenia Space。本地文件 thermal-digital-twin-ices25.pdf，已下载。

研究的问题：卫星热数学模型通常只在设计与测试阶段使用，运营阶段另建简化模型造成重复投入。问题是能否把经热真空试验校正过的热数学模型直接复用为运营期的实时热仿真器，与在轨遥测持续关联，支持异常检测与新热控策略的推演。

方法：项目由欧洲空间局与法国国家空间研究中心支持，以 Copernicus 星座的 Sentinel-3B 为案例，基于其试验后校正的热数学模型构建实时热仿真演示器。仿真器集成动态轨道传播器、比例积分式热控调节与平台散热器模型，在线求解辐射与热传导方程以覆盖未预见的场景。技术难点包括从遥测恢复并初始化各节点温度以及满足实时性能。辐射视因子采用确定性积分方法而不是蒙特卡洛光线追踪，并在推进 GPU 并行化。系统以动态二维图实时对比仿真输出与遥测数据。

关键结论与数字：演示器达到技术成熟度 3 级。热场重放仿真速度达到实时的 8 倍，热案例结果对在轨遥测完成验证。确定性视因子计算比蒙特卡洛方法快 5 到 10 倍，早期 GPU 移植在小型 GPU 上相对完全并行化的 CPU 实现再提速约 3 倍。结论认为共享同一热模型贯穿设计、测试与运营能提高精度并降低成本。

与 SpaceDC 的关系：这是卫星热数字孪生对真实遥测做实时校验的代表性工业工作，其把校正后的热模型用于运营期推演的思路与 SpaceDC 用经 STK 验证的热模块驱动运行时 what-if 对比的思路一致。它证明了实时热求解在工程上可行，为 SpaceDC 逐秒热积分的设定提供了旁证。

它没有覆盖而我们覆盖的地方：它是热学单一领域的孪生，不建模电源收支，也没有任何算力负载。它面向已发射卫星的运营支持而不是新卫星的设计探索。SpaceDC 在设计阶段就把轨道电热与 GPU 推理耦合起来，提供搭建向导与并行对比，并把热对 GPU 功率预算的压缩效应显式建为反馈回路。

## 4. Physics-constrained Identification of Graph-based Thermal Networks for Spacecraft Digital Twins

引用信息：Luca Sosta, Carlo Ciancarelli, Leonardo Marini, Stefano Pagani, Francesco Regazzoni, and Nicola Parolini. Physics-constrained identification of graph-based thermal networks for spacecraft digital twins. arXiv preprint arXiv:2605.28452, May 2026. 作者单位为 Politecnico di Milano 与 Thales Alenia Space Italia。本地文件 spacecraft-thermal-graph-twin-arxiv26.pdf，已下载。

研究的问题：航天器数字孪生需要能长时间稳定外推且计算便宜的热模型。集总参数热网络的节点电容与边热导通常依赖材料与几何先验，从稀疏局部温度测点反推这些参数是一个不适定的逆问题。

方法：作者把集总参数热模型表述为图上的扩散动力系统，节点为控制体温度，边为对称正值热导，系统矩阵是图拉普拉斯形式。在参数化层面强制物理可采性，电容为正、热导对称且系统耗散，这些约束在构造上成立而不需要额外正则化。辨识采用受神经常微分方程启发的连续时间轨迹匹配方法，直接从温度测量与已知热输入重建热网络参数。方法在高保真有限元仿真生成的合成数据集上验证，覆盖逐渐复杂的激励条件。

关键结论与数字：标定后的集总热网络能准确复现长时程温度演化，对测量噪声保持稳健，物理约束改善了辨识问题的条件性并保证了长时间滚动预测的稳定性。数值结果显示精度与计算开销之间取得了适合数字孪生集成的平衡。

与 SpaceDC 的关系：SpaceDC 的热模块同样采用节点化的热网络描述结构温度并逐秒积分，该文说明这类集总热网络作为航天器数字孪生热核心是当前研究的共识方向，其物理可采性约束对 SpaceDC 后续做参数标定有直接参考价值。

它没有覆盖而我们覆盖的地方：它只在合成有限元数据上验证而没有对商业工具或在轨遥测对标。它只处理热学单一领域，没有轨道与电源耦合，没有任何算力维度。SpaceDC 的热模块与轨道电源模块耦合并对 STK 11.6 验证，热状态进一步反馈到 GPU 推理吞吐。

## 5. Revisiting Spacetrack Report Number 3

引用信息：David A. Vallado, Paul Crawford, Richard Hujsak, and T. S. Kelso. Revisiting Spacetrack Report Number 3. AIAA/AAS Astrodynamics Specialist Conference, AIAA 2006-6753, Keystone, Colorado, August 2006. 本次下载的是作者在 CelesTrak 公开的 Rev 2 修订版。本地文件 sgp4-revisiting-str3-aiaa06.pdf，已下载。

研究的问题：美国国防部通过两行根数发布轨道数据，而公开的 SGP4 代码自 1980 年 Spacetrack Report Number 3 发布后经历大量未公开的修改，公众可得的代码与生成两行根数的运行代码不再一致。问题是给出一个与国防部现行实现高度兼容、可公开获得且经过验证的 SGP4 标准版本。

方法：作者梳理 SGP 系列模型从 1960 年代至今的演化历史，整合 GSFC 释出的 1990 年版代码、Crawford 的 Dundee 版本变更史与 Hoots 2004 年的完整方程文档，合成一个非专有的 SGP4 实现。论文提供多语言源代码、覆盖各类轨道类型的测试用例、与运行版本的比对结果以及 TEME 坐标系到地固坐标系转换的规范说明，并强调两行根数只能配合生成它的模型使用，跨模型混用会产生完全错误的结果。

关键结论与数字：合成版本与国防部运行版本在测试用例上高度一致，成为学界与业界事实上的 SGP4 标准参考实现。论文重申两行根数属于基于模型的参数估计产物，直接把根数转成状态矢量再用数值积分传播是无效做法。文中给出的典型应用包括地面站可见性快速搜索、天线跟踪与低精度轨道设计。

与 SpaceDC 的关系：SpaceDC 的轨道模块用六要素生成两行根数并用 SGP4 传播，地面站可见性与通信窗口计算正是该文列出的典型用途。SpaceDC 对 STK 11.6 的轨道对标之所以能收敛，前提就是双方使用与该文一致的兼容 SGP4 实现，这篇论文是引用 SGP4 精度与实现规范时的标准出处。

它没有覆盖而我们覆盖的地方：它只处理轨道传播这一个层面，不涉及电源、热控或载荷。SpaceDC 在经过验证的轨道传播之上叠加电源与热控耦合，并把轨道决定的日照与地影直接馈入发电与热流计算，再传导到 GPU 推理性能。

## 6. Basilisk, A Flexible, Scalable and Modular Astrodynamics Simulation Framework

引用信息：Patrick W. Kenneally, Scott Piggott, and Hanspeter Schaub. Basilisk, A Flexible, Scalable and Modular Astrodynamics Simulation Framework. Journal of Aerospace Information Systems, volume 17, number 9, pages 496 to 507, September 2020. doi 10.2514/1.I010762. 本地文件 basilisk-jais20.pdf，已下载。

研究的问题：商业与政府的航天仿真工具要么闭源要么模块化不足，缺少一个开源、模块化、能把耦合航天器动力学、空间环境与飞行软件算法一起仿真并支持大规模蒙特卡洛的通用框架。

方法：Basilisk 用 C++ 编写核心动力学与物理模块，通过 SWIG 自动生成 Python 接口，用户在 Python 层组装场景。框架以模块、任务与任务组三个抽象组织仿真，模块之间通过消息传递系统交换数据实现严格解耦，积分步长与模型保真度按模块可配置。框架内置数据记录与蒙特卡洛设施，支持硬件在环与软件在环，动力学采用递归可扩展的多体建模方法，支持柔性帆板、动量交换装置与燃料晃动。

关键结论与数字：Basilisk 提供耦合的位置与姿态动力学，运行速度至少达到实时的 365 倍，一个任务年可在一个计算日内完成。框架被用于任务早期设计、详细设计验证与发射后遥测分析等阶段。与 STK、GMAT、OreKit 等工具的对比指出这些工具在耦合航天器动力学或开源可扩展性上各有欠缺。

与 SpaceDC 的关系：Basilisk 是学术界通用航天仿真框架的标杆，其模块化消息传递架构与 SpaceDC 后端各物理模块逐秒交换状态的设计属于同一类工程思路，其远超实时的运行速度目标与 SpaceDC 支撑实时 what-if 并行对比的需求一致。

它没有覆盖而我们覆盖的地方：Basilisk 聚焦动力学、环境与飞行软件，不建模星上计算载荷，没有 GPU 功耗与推理吞吐模型，也没有热对算力的反馈。它面向航天工程师脚本编程而不是交互式设计。SpaceDC 提供卫星搭建向导、算力工作负载建模与 Omniverse RTX 三维可视化，并对 STK 完成三模块数值对标。

## 7. 42, An Open-Source Simulation Tool for Study and Design of Spacecraft Attitude Control Systems

引用信息：Eric Stoneking. 42, An Open-Source Simulation Tool for Study and Design of Spacecraft Attitude Control Systems. NASA Goddard Space Flight Center, NASA Technical Reports Server document 20180000954, February 2018. 本文档为公开的介绍性讲稿。本地文件 nasa42-simtool-ntrs18.pdf，已下载。

研究的问题：航天器姿态控制系统的设计与验证需要一个高保真、开源、易用且贯穿概念研究到集成测试全阶段的仿真工具。

方法：42 是 NASA Goddard 开发的开源通用仿真器，用 C 编写，精确建模由刚体与柔性体组成的多体航天器姿态动力学，用树状拓扑组织多体结构，支持二体与三体轨道域，环境模型覆盖近地轨道到整个太阳系，可同时仿真多颗航天器以支持交会、邻近操作与编队飞行研究。讲稿从用户、开发者与建模者三个视角介绍工具的使用与内部结构，工具自 2014 年起在 GitHub 开源。

关键结论与数字：42 成为立方星与科学任务姿态控制设计的常用参考工具，被多个任务与工具链集成，Basilisk 的期刊论文也把它列为开源航天仿真的代表。它的定位是高保真与易用并重的姿态与轨道动力学仿真。

与 SpaceDC 的关系：SpaceDC 的姿态指向模式决定帆板受晒与结构受热，42 是这类姿态动力学建模的权威开源参照，引用它可以说明姿态仿真已有成熟工具而 SpaceDC 的贡献在别处。

它没有覆盖而我们覆盖的地方：42 不建模电源收支细节、结构热网络与星上算力，没有与商业工具的数值精度对标发表，也没有面向非专家的交互式设计流程。SpaceDC 把姿态与轨道作为输入耦合到电热与 GPU 推理，并用 STK 11.6 完成验证。

## 类别小结

工具类工作各自覆盖单一领域，PowerCubeSat 只算发电，RTSS 2013 只管电池与任务功率，ICES 2025 与 arXiv 2605.28452 只做热，Vallado 只定轨道传播标准，Basilisk 与 42 覆盖动力学但不碰载荷算力。验证路线上，PowerCubeSat 对 Power Sim，ICES 2025 对在轨遥测，Vallado 对国防部运行代码，都印证了与权威参照对标是这个领域可信度的通行证。SpaceDC 站在这些单领域工作的交集之外，把轨道电热与 GPU 大模型推理耦合进同一个逐秒引擎，对 STK 11.6 完成三模块验证，并用热压缩 GPU 功率预算的反馈回路把热与算力连成闭环，这是上述任何一篇都没有覆盖的位置。
