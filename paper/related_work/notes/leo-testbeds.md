# 类别笔记：空间计算网络与低轨星座的仿真与实验平台

本类别覆盖六篇论文。四篇为指定目标，两篇为 2024 到 2025 年补充的新工作。六篇 PDF 均已下载到 c:/Workspace/SpaceDC/paper/related_work/ 并通过 %PDF 头与大小校验。

共同背景。这一类工作回答的问题是研究者如何在地面低成本地实验大规模低轨星座系统。它们的关注点几乎全部落在网络行为上，即拓扑、时延、路由与传输协议。SpaceDC 的关注点是卫星本体的物理与算力，即轨道、电源、热控与 GPU 推理吞吐的逐秒耦合。两条线互补，前者把卫星当作网络节点，后者把卫星当作会发热会缺电的计算机。

## 1. StarryNet

引用信息。Zeqi Lai, Hewu Li, Yangtao Deng, Qian Wu, Jun Liu, Yuanjie Li, Jihao Li, Lixin Liu, Weisen Liu, Jianping Wu. StarryNet: Empowering Researchers to Evaluate Futuristic Integrated Space and Terrestrial Networks. In Proceedings of the 20th USENIX Symposium on Networked Systems Design and Implementation, NSDI 2023, Boston, MA, USA, pages 1309 to 1324. 作者单位为清华大学与中关村实验室。开放 PDF 在 USENIX 官网。代码在 github.com/SpaceNetLab/StarryNet。

研究的问题。研究者要评估星地一体化网络的新想法，现有三条路都有缺陷。真实卫星网络有真实性但普通团队在技术与经济上都难以使用且不可灵活改动。离散事件仿真抽象层次太高，无法暴露真实负载下的资源竞争、能耗与软件错误。已有网络模拟器无法刻画低轨卫星的高动态性。

方法。StarryNet 采用真实数据驱动加轻量级模拟辅助的路线，在地面虚拟环境中构建物理星地网络的数字孪生。它用众包方式汇集公开的星座监管信息、卫星轨迹、地面站分布与用户终端测量数据，用星座同步器保证虚拟环境与真实星座在空间与时间特征上一致，用大量轻量级虚拟节点模拟卫星、地面站与地面主机，节点可以运行未修改的真实应用与网络协议栈，并用星座编排器在多台机器上调度资源以支撑大规模与高动态的星座。评估包括与真实卫星网络和其他模拟器的保真度对比，以及星地互联机制权衡、路由协议韧性、硬件在环负载测试三个案例研究。

关键结论与数字。作者在四项要求上对比了现有平台，即星座一致性、系统与协议栈真实性、灵活可扩展、低成本易用，指出只有 StarryNet 同时满足四项。少量本地或云端机器即可搭建实验环境。后续论文指出其单机容器规模受 Linux 网桥端口限制，约在一千零二十三个节点封顶。

与 SpaceDC 的关系。这是与 SpaceDC 表述最接近的工作，它明确自称星地网络的数字孪生，而且提出了系统效应问题，即新功能在不同负载下会消耗多少在轨能量。SpaceDC 可以引它来确立数字孪生实验方法在星座研究中的地位。

它没覆盖而我们覆盖的地方。StarryNet 的孪生对象是网络，卫星本体只是运行协议栈的容器。它不建模太阳入射与地影下的发电、电池充放电、结构温度演化，也没有 GPU 推理性能模型，更没有温度压缩功率预算进而降低吞吐的反馈回路。它的能耗只能靠硬件在环测量而非物理引擎推演。它没有对 STK 的数值验证，也没有搭建向导与三维渲染。

## 2. Celestial

引用信息。Tobias Pfandzelter, David Bermbach. Celestial: Virtual Software System Testbeds for the LEO Edge. In Proceedings of the 23rd ACM/IFIP International Middleware Conference, Middleware 2022, Quebec City, Canada. 作者单位为柏林工业大学。arXiv 编号 2204.06282。代码在 github.com/OpenFogStack/celestial。

研究的问题。低轨边缘计算目前只是概念，没有可用的真实在轨算力基础设施，研究者如何在地面准确且低成本地评估面向低轨边缘的任意软件系统。

方法。Celestial 用 microVM 为每颗卫星服务器和每个地面站服务器建立虚拟机，应用无关，任何能在 microVM 里跑的软件都能测试。测试床按秒级更新星座运动带来的网络拓扑与时延变化，网络条件由星座轨道计算得出。用户可以只模拟星座在某个地理包围盒内的子集，盒外卫星的虚拟机被挂起以节省资源。论文用一个时延敏感的边缘应用验证模拟保真度，并用分布式遥感数据分析服务做案例研究。

关键结论与数字。以第一期 Starlink 五个壳层共约五千三百颗卫星为建模对象，其中最低壳层一千五百八十四颗在五百五十公里高度。通过挂起盒外虚拟机，单台主机可以承载多颗卫星服务器，成本远低于为每个节点配置专用云虚拟机的方案。论文同时指出在轨服务器会遭遇单粒子翻转与间歇性性能退化，软件必须针对这类故障测试。

与 SpaceDC 的关系。Celestial 是把算力放进卫星并为其做测试床这条路线的代表作，与 SpaceDC 同样把卫星当作计算节点。它对卫星故障与降级的讨论支持 SpaceDC 强调的环境对算力的影响。

它没覆盖而我们覆盖的地方。Celestial 的卫星算力是抽象的处理器与内存配额，功率与温度不在模型之内。它承认功耗与废热管理是工程挑战但不建模它们。SpaceDC 把发电、储能、热平衡与 GPU 动态调频耦合成逐秒物理引擎并对 STK 完成数值验证，还给出热与吞吐之间的定量反馈，这些都在 Celestial 范围之外。

## 3. Hypatia

引用信息。Simon Kassing, Debopam Bhattacherjee, André Baptista Águas, Jens Eirik Saethre, Ankit Singla. Exploring the Internet from space with Hypatia. In Proceedings of the ACM Internet Measurement Conference, IMC 2020, virtual event, 16 pages, doi 10.1145/3419394.3423635. 作者单位为苏黎世联邦理工学院。代码在 github.com/snkas/hypatia。

研究的问题。网络社区缺少能刻画低轨星座轨道动态的分析工具，没有工具就无法研究高速轨道运动带来的时延波动、路径重构对拥塞控制与路由的影响。

方法。Hypatia 由基于 ns-3 的包级仿真模块与基于 Cesium 的可视化模块组成。它从美国联邦通信委员会与国际电信联盟的申报文件中提取 Starlink、Kuiper、Telesat 三个星座的轨道参数，生成星座并按轨道运动逐时刻更新星地链路与星间链路，然后在包级粒度上分析端到端连接的时延变化、包乱序、可用带宽波动及其对拥塞控制和路由的影响。

关键结论与数字。分析对象为规划中的四千四百零九颗 Starlink 卫星、三千二百三十六颗 Kuiper 卫星与一千六百七十一颗 Telesat 卫星。以 Starlink 第一壳层为例，一千五百八十四颗卫星分布在七十二个轨道面，高度五百五十公里，倾角五十三度。仿真显示端到端往返时延与路径结构持续变化，链路利用率高度动态，这使路由与流量工程变得困难，也让拥塞控制在无竞争流量时都难以收敛。

与 SpaceDC 的关系。Hypatia 是低轨网络仿真的奠基性工具，被后续几乎所有平台引用和对比。SpaceDC 的轨道传播与可见性计算在功能上与它的轨道模块同类，但 SpaceDC 将轨道结果进一步馈入电源与热控。

它没覆盖而我们覆盖的地方。Hypatia 是纯网络仿真器，节点不执行计算负载,没有资源与能量的概念。它不建模卫星的电源、温度与算力，没有软件在环，没有交互式对比实验，其轨道模块也未报告对 STK 的逐点数值验证。

## 4. StarPerf

引用信息。Zeqi Lai, Hewu Li, Jihao Li. StarPerf: Characterizing Network Performance for Emerging Mega-Constellations. In Proceedings of the 28th IEEE International Conference on Network Protocols, ICNP 2020. 作者单位为清华大学。会议开放 PDF 在 icnp20.cs.ucr.edu。代码在 github.com/SpaceNetLab/StarPerf_Simulator。

研究的问题。巨型星座的架构与可达网络性能鲜为人知，直接测量尚未部署完的星座不可行，星座制造商与内容提供商需要在多种星座设计选项下估计可达性能。

方法。StarPerf 是一个星座性能仿真平台，输入为星座拓扑描述、网络策略与流量模式，内部用轨道与链路模型生成随时间变化的网络拓扑并计算区域到区域的可达性能。平台包含两项技术，一是捕捉卫星高速移动影响的性能仿真，二是星座缩放，即通过调整卫星数量、链路可用性与容量等参数合成不同拓扑选项，从而探索现实中难以复现的多种运行条件。论文用它对比 Starlink、OneWeb、Telesat 三个星座并做假设分析，最后提出一个自适应中继选择算法。

关键结论与数字。星间链路部署齐全时巨型星座对跨洲长距离通信有明显低时延机会。星座拓扑需要精心设计以避免卫星移动造成的高时延波动。在星地云一体化架构中恰当选择中继可以把典型交互式流量的端到端时延降低至多百分之六十二。平台用 Python 实现并开源，作者称其为首个刻画巨型星座网络性能的开源模拟器。

与 SpaceDC 的关系。StarPerf 的星座缩放思想与 SpaceDC 的假设对比功能同源，都是在仿真中改变设计参数并观察指标变化。SpaceDC 把这一交互扩展到平台选型、GPU 配置与负载设定，且对比在并行孪生中实时进行。

它没覆盖而我们覆盖的地方。StarPerf 只输出网络性能指标，不涉及卫星平台的发电、热控与计算硬件。它的假设分析改变的是网络拓扑参数，SpaceDC 的假设分析改变的是卫星本体设计并能看到功率、温度与推理吞吐的耦合响应。它同样没有第三方工具的数值验证与三维可视化。

## 5. xeoverse，2024 年补充

引用信息。Mohamed M. Kassem, Nishanth Sastry. xeoverse: A Real-time Simulation Platform for Large LEO Satellite Mega-Constellations. In Proceedings of the 2024 IFIP Networking Conference, 2024. 作者单位为萨里大学。arXiv 编号 2406.11366。

研究的问题。测试新协议需要对整个巨型星座做高保真且实时的仿真，即一秒仿真时间在一秒钟壁钟时间内完成，现有工具在规模、速度与保真度上无法同时满足。

方法。xeoverse 在 Mininet 中把用户终端、卫星与地面站建模为轻量级 Linux 虚拟机，采用三个关键策略，一是在仿真开始前预计算拓扑与路由变化，二是每个时间步只更新发生变化的星间链路，三是只维护与仿真场景相关流量所经过的链路。链路层建模包含射频参数、信噪比与天气影响。星座由标准两行根数描述，可适配任意星座。

关键结论与数字。单台二十六核六十四 GB 内存的机器可以实时仿真当时完整的 Starlink 星座共五千四百四十二颗卫星。总仿真时间比 Hypatia 快二点九倍，比 StarryNet 快四十倍。预测吞吐在晴天与观测值相差约百分之二，雨天相差约百分之十六。论文还指出 StarryNet 受容器网桥限制单机难以超过约一千零二十三个节点，Hypatia 在拓扑更新阶段比 xeoverse 慢五倍。

与 SpaceDC 的关系。xeoverse 强调实时性与假设分析的快速重跑，这与 SpaceDC 逐秒推进并支持实时并行对比的定位相似。它对天气影响链路的建模也说明环境物理正在进入网络仿真，SpaceDC 把环境物理推进到了热与电。

它没覆盖而我们覆盖的地方。xeoverse 的节点是网络端点，不承载计算负载,不建模星上算力。它没有电源与热控模型，没有 GPU 推理吞吐,没有热对算力的反馈,没有卫星搭建向导与三维渲染，也没有对 STK 的轨道电热逐项数值验证。

## 6. Stardust，2025 年补充

引用信息。Thomas Pusztai, Jan Hisberger, Cynthia Marcelino, Stefan Nastic. Stardust: A Scalable and Extensible Simulator for the 3D Continuum. In Proceedings of the 2025 IEEE International Conference on Edge Computing and Communications, IEEE EDGE 2025, pages 44 to 53. 作者单位为维也纳工业大学。arXiv 编号 2506.01513。代码在 github.com/polaris-slo-cloud/stardust。

研究的问题。边缘、云与低轨卫星正在合并为一个三维连续体，评估跨这三类节点的编排与调度算法需要一个既可扩展到巨型星座规模又能获取节点算力信息的模拟器，现有模拟器要么只做网络不做算力，要么用虚拟化模拟节点导致单机规模受限。

方法。Stardust 用纯仿真而非虚拟化来同时表示低轨卫星、云与边缘节点，逐步跟踪节点位置、节点资源与网络路由，仿真步长可配置。它提供动态路由机制，允许替换星间链路路由协议与路径计算算法。它提供 SimPlugin 插件机制，自定义逻辑在每个仿真步执行并能访问完整基础设施状态，编排算法可以直接接入仿真。论文用洪灾应急响应中星地协同的无服务器工作流作为动机场景。

关键结论与数字。单机可以模拟至多两万零六百颗卫星的巨型星座，规模约为当时最大星座的三倍，扩展性优于被比较的现有工具。论文将 Celestial 与 StarryNet 归为模拟器中资源开销大的虚拟化路线，将 Hypatia 归为不执行节点的纯网络路线，并指出许多现有工具在实验中不维护实时节点位置。

与 SpaceDC 的关系。这是与 SpaceDC 时间上最接近的仿真平台工作，它明确提出网络仿真必须补上节点算力才能研究在轨计算，这正是 SpaceDC 立场的旁证。它的插件式扩展与 SpaceDC 的模块化物理引擎在架构口味上相似。

它没覆盖而我们覆盖的地方。Stardust 的节点资源是容量数字，用于调度决策，不是物理量。它不建模发电、电池、温度，也不建模 GPU 动态调频与大模型推理吞吐，因此无法表达热约束压缩算力这类跨域效应。它没有对 STK 的数值验证，没有面向单星设计的搭建向导，没有 Omniverse 级别的三维可视化。

## 对 SpaceDC 相关工作章节的定位建议

六篇论文构成一条清晰的演进线。Hypatia 与 StarPerf 建立了低轨星座的网络仿真，StarryNet 与 Celestial 让真实软件跑进模拟环境，xeoverse 追求全星座实时，Stardust 把算力资源纳入仿真。整条线的共同盲区是卫星本体物理，没有一篇建模发电、热平衡与计算性能之间的耦合，也没有一篇报告对 STK 这类工业工具的数值验证。SpaceDC 的差异化表述可以是，已有平台回答卫星网络如何表现，SpaceDC 回答一颗算力卫星在轨道环境里究竟能算多快，并用轨道电热三模块对 STK 11.6 的验证和热到吞吐的反馈回路支撑这一句话。
