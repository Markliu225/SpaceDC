# SpaceDC 定位分析

本文件回答两个问题。第一，Rhone 是最接近的竞品，我们到底独特在哪里。第二，现有工作的根本性不足是什么。全部论断经过对本地 PDF 的逐页核对，并经过一轮模拟审稿人的对抗攻击，攻击中被推翻的表述已经删除或收窄。证据引用格式为文件名加章节页码。

## 〇、本质：为什么这件事必须被做

这一节是全文的顶层，后面各节都是它的证据。必要性由三个事实压出来，每个事实单独看都平凡，叠在一起就是一个不允许不存在的工具。

**事实一，这是一次性工程。** 卫星发射之后没有测量、修复、再来一次的循环。地面数据中心跑热了可以加冷却，在轨数据中心的每个设计错误都是永久的，代价是整个资产。工程学的常规进步方式是构建、测量、修正，这个循环在这里被物理切断了。

**事实二，目标量在无人能算的位置。** 在轨数据中心的目标函数是算力吞吐，用户购买的是每秒多少 token。这个量由轨道、供电、散热与芯片的耦合回路决定，光照给功率上限，温度给功率预算，预算经动态调频变成吞吐。而今天没有任何工具能把设计参数映射到这个目标函数。航天设计工具的输出是瓦特、开尔文与公里，算不出吞吐。可行性论文用稳态手算，Starcloud 五吉瓦集群的散热依据是半页二十摄氏度平板估算。仿真平台要求卫星已经存在，Rhone 换一颗卫星需要那颗卫星的遥测。一个行业正在为一种机器投入真金白银，而没有任何设计工具能计算这种机器的目标函数。

**事实三，目标量所在的物理区间没有任何飞行数据，也不可能先有数据。** 人类飞过的算力卫星在几十瓦量级，正在论证的在几十千瓦到兆瓦，中间隔三个数量级。在四十瓦上，热与算力的耦合被裕量吸收，是二阶修正。在四十千瓦上它是一阶效应，是决定成败的约束。也就是说，将要起决定作用的物理，从来没有在任何飞行数据里起过决定作用。经验方法在这里失效的原因很干净，无法对不存在的数据做拟合，而数据只能在第一颗星建成之后出现，可能是以失败的形式。

三个事实合起来：一个不可逆的工程决定，指向一个没有先例的物理区间，目标函数由现有工具都看不见的耦合回路决定。工程史上每个处于这种处境的学科，最后都为自己建立了同一类东西，一个机理性的、被独立验证过的、可以在构建之前迭代设计的仿真器。芯片在流片前有全套仿真，飞机上天前有风洞，核装置在禁试之后靠仿真维护。算力卫星今天的工具链是从草稿纸直接到发射台，中间的台阶不存在。SpaceDC 就是这个台阶。它让设计迭代发生在迭代还可能发生的唯一位置，构建之前。

三个事实各自的文献证据。事实一由 Starcloud 白皮书反面印证，它承认扩大规模前必须通过多次在轨演示彻底评估，在轨演示昂贵且不可迭代。事实二由五篇可行性论文与 Rhone 原文直接支撑，见第一节与第二节。事实三由功率量级对比支撑，Rhone 整星功率轨迹峰值约四十瓦，Suncatcher 单星二十八千瓦，Turyshev 明说辐射板温度收益与热节流阈值直接竞争但自己不建模。

给任何领域读者的三句话版本。卫星发射之后无法调试。在轨数据中心卖的是算力，而今天没有任何设计工具能算出一颗设计方案的算力。芯片有流片前仿真，飞机有风洞，算力卫星在草稿纸和发射台之间什么都没有，SpaceDC 补的是这一层。

## 一、Rhone 到底是什么

先把竞品刻画准确，定位才有意义。Rhone 完整版发表在 USENIX ATC 2025，三个模型的构成各不相同。

电源模型的发电侧是解析公式，功耗侧由天算星座 BUPT-1 约两千个轨道周期的遥测聚类拟合而成，论文原文说用遥测数据来调模型参数。见 rhone-atc25.pdf 4.1 节 819 至 820 页。

热模型用 SolidWorks 对 BUPT-1 的具体内部结构做有限元传导求解。关键在于外部热载荷，轨道太阳辐照与地球反照并非从轨道几何推算，论文采用边界锚定策略，把实测的接口温度当作经验边界条件灌入。见 4.2 节 821 页。辐射板面积与涂层属性在全文没有作为参数出现。

计算模型是硬件在环查表。拿真实的树莓派 4B 与华为 Atlas 200 DK 拆掉风扇，循环加压到发生热节流，逐条记录温度与执行时延生成查找表，在线仿真时按当前温度查表并用容器资源配额复现时延。见 4.3 节与 5.2 节。

整星功率轨迹峰值约 40 瓦。论文第 9 节自述扩展方式，换卫星需要那颗卫星的遥测数据，换芯片需要实物做在环画像。全文没有任何改变卫星本体设计再仿真的实验，用户命令接口能改的是运行模式、链路通断与任务启停，全部是运行时量。

这个刻画得出 Rhone 的准确定性。它是一台高保真的回放机，回放对象是已经存在并且已经被测量过的卫星与芯片。它回答的问题是应用在这颗卫星上会表现如何。这不是缺陷，是它的设计目标，它在这个目标上做得很好。

## 二、根本性不足：现有工作分成互不覆盖的两半

对三十一篇文献逐篇核对后，缺口的结构是清楚的。围绕算力卫星，现有工作恰好分成两半，每一半都缺对方拥有的东西。

第一半是航天设计工具，卫星是自变量，但没有计算载荷。RTSS 2013 在设计时对太阳板与电池配置做帕累托寻优。PowerCubeSat 是让用户自定义星体几何与帆板布局的设计工具。Basilisk 与 NASA 42 自述覆盖概念设计到运营。ICES 2025 的热孪生把设计期评估列为用例。这一半把卫星本体当变量的传统有几十年，但各管单一领域，没有一个建模计算载荷，更没有温度到算力的反馈。

第二半是空间计算平台，有计算载荷，但保真度被钉死在已存在的卫星与芯片上。Rhone 如上所述。OEC 的仿真器在 2020 年就扫过太阳板功率、电容量与计算模块数，这是文献里最接近改设计再仿真的先例，但它刻意用超级电容规避了热建模，全文没有温度状态量，功耗是对特定 Jetson TX2 的实测，整星在十瓦级。StarryNet 的能耗数据来自真实立方星接功率计实测，框架本身零能量模型。Celestial 把物理环境退化为故障注入，计算能力是虚拟机配额。xeoverse 与 Stardust 的算力是调度用的容量数字。

还有第三组文献从需求侧证明这个缺口正在变得昂贵。在轨 AI 数据中心方向的五篇文献全部停在稳态点估算。Google 的 Suncatcher 对散热的全部论述是一句话，并在结论里把热管理列为未来里程碑必须解决的问题。JPL 的 Turyshev 最为坦白，他逐条声明自己的集总模型不能替代面板分辨热分析、瞬态阴影分析与流体网络模型，并两次点名热节流与芯片性能的耦合真实存在但自己没有建模。系绳构型论文有精细的结构动力学时间域仿真能力，热却只给一个稳态点。五篇合计，温度对算力反馈的建模空白是百分之百。

把三组放在一起，根本性不足可以一句话表述。**有设计自由度的工具没有算力物理，有算力物理的平台没有设计自由度，而正在兴起的千瓦级算力卫星恰恰需要两者同时在场，因为在这个功率量级上，轨道、供电、散热与算力的耦合从二阶修正变成一阶效应。** 四十瓦的卫星可以靠裕量吸收耦合，两千瓦的节点不能，Turyshev 的原文已经把这一点说透，辐射板温度的四次方收益直接与结温上限、漏电功率与热节流阈值竞争。

## 三、SpaceDC 的独特性，经攻击修正后的表述

对抗攻击推翻了三条主张的初始版本，修正后如下。

**主张一，可设计性，这是根本主张。** 初始表述说现有平台把卫星冻结在拟合系数里，被 OEC 的帆板扫描实验与整个航天工具线证伪，必须收窄。修正表述为：SpaceDC 是第一个把轨道、电源、热控、GPU 推理整条耦合链全部交给卫星本体设计参数驱动的平台，特别是热设计参数与数据中心级 GPU 配置第一次同时成为自变量。辐射板面积、涂层吸收率与发射率、太阳翼面积、电池化学与容量、GPU 型号数量、轨道根数都是输入。模型中仅存的经验常数刻画的是芯片型号与物理定律，锚定的不是某一颗特定卫星，所以平台不被任何已飞卫星锁定。Rhone 换卫星需要新遥测，这是它的方法决定的，我们不需要，这是我们的方法决定的。

**主张二，闭环物理，是主张一的物理推论。** 初始表述声称闭环是我们独有，被 Rhone 证伪，它每个时间步都在做功率读温度、热模型回写温度、温度拖慢计算的迭代，回路拓扑一条边不缺。修正表述为：新颖点在回路每条边的构成。Rhone 的空间热环境边界是实测接口温度，温度到算力是地面查表，所以它的回路参数无法由设计改变。SpaceDC 的每条边是第一性构成，太阳矢量与圆锥地影从轨道推导，环境热流从几何算出，温度经动态调频功率封顶机制压缩 GPU 预算，这条因果链有 ASPLOS 2024 对数据中心 GPU 的实测支撑。设计参数因此真正位于回路上，改辐射板涂层会改变回路的收敛点。深度节流收敛与蚀周期温度循环这两类行为必须以实验曲线呈现在论文里，不能只作声称。

**主张三，参照对标的保真方法，是主张一的认识论推论。** 初始表述称这是设计阶段唯一可行的验证路径且是我们的方法贡献，被 PowerCubeSat 与 Vallado 的先例证伪，对标权威参照是航天界通行做法。修正表述为：SpaceDC 沿用航天界的既定验证路线并第一次把它铺满算力卫星的整条耦合链，轨道电热三个域对 STK 11.6 与其空间环境模型共 51 项判据逐通道对标，GPU 功耗性能模型对已发表的功率封顶实测研究校准。适用条件写清楚，目标卫星连工程样机都不存在时，遥测拟合在原理上不可用，热真空试验在硬件到位前不可用，参照对标是这个阶段可用的手段。边界也要明说，各通道分别锚定不等于耦合回路整体被锚定，回路可信性由每条边各自被验证加上边的组合是守恒律这一论证承担。

三条主张的关系。可设计性是根本，因为卫星是自变量且耦合在千瓦级是一阶效应，物理必须以经设计参数闭合的回路来算，这推出主张二。因为目标卫星不存在，保真锚点必须不依赖目标卫星的遥测，这推出主张三。

## 四、学术表述

上文的白话表述用于内部讨论，论文使用下面的术语体系。每个术语在文献里有明确出处，不需要发明任何词汇。

### 术语映射

| 内部白话 | 学术术语 | 出处与领域 |
| --- | --- | --- |
| 还不存在的卫星的孪生 | digital twin prototype，DTP | Grieves 与 Vickers 的数字孪生分类，DTP 表示物理实体存在之前的产品孪生，DTI 表示某个已制造实体的孪生。这是可直接引用的经典分类 |
| 已飞卫星的回放 | digital twin instance，DTI | 同上。Rhone 与 StarryNet 构建的是 BUPT-1 与既有立方星的 DTI |
| 第一性物理 | mechanistic model，或 physics-based model | 系统辨识里与 empirical 或 data-driven model 相对的标准分类，白盒对黑盒 |
| 卫星是自变量 | design variables 与 design-space exploration | 设计空间探索是计算机体系结构与嵌入式系统的成熟术语，处理器设计者在流片前用机理级仿真器做的正是这件事 |
| 拟合模型答不了设计问题 | validity confined to the measured envelope | 经验模型的效度边界是观测包络，改设计把系统移出包络，模型失效。需要更理论的表述时可用因果推断的语言，设计问题是干预性问题，遥测拟合只支撑观测性问题 |
| 耦合是一阶效应 | non-separable design space | 子系统各自评估不可靠，可行域由跨域耦合约束共同定义，目标量由闭环平衡决定 |
| 对标 STK | verification against an independent reference implementation | 航天软件验证的通行做法，逐通道对权威参照对标 |

### 核心表述，论文用语

中文版。SpaceDC 把算力卫星的评估从实例仿真推进到设计空间探索。现有空间计算平台构建的是数字孪生实例，功率、热与计算模型由已飞卫星的遥测和实物芯片画像拟合，效度边界是被测系统的观测包络。SpaceDC 构建的是数字孪生原型，模型是机理性的，每个参数具有物理语义并与设计变量一一对应，因此在设计变量被改动时保持有效。在千瓦级功率量级，轨道、供电、散热与算力的耦合是一阶效应，设计空间不可分离，机理模型必须在时间域以闭环形式求解。保真通过对独立权威参照的逐通道验证建立。

英文版，引言开篇的必要性段落，对应第〇节三个事实。A satellite cannot be debugged after launch, so every design error in an orbital data center is permanent. The quantity such a system sells is compute throughput, and this quantity is determined by the coupled loop of orbit, power, thermal, and processor frequency scaling, yet no existing tool maps a satellite design to it: astrodynamics tools output positions and temperatures but have no notion of a workload, feasibility studies rely on steady-state estimates, and satellite computing emulators require telemetry from a satellite that already flies. The designs now being proposed sit three orders of magnitude above all flight heritage in compute power, in a regime where the thermal-compute coupling becomes the binding constraint for the first time, so no data exists to fit and none will exist before the first vehicle is built. Chips are simulated before tape-out and aircraft are tested in wind tunnels before flight. Compute satellites today go from spreadsheet to launch pad. SpaceDC supplies the missing step: a mechanistic digital twin, validated channel by channel against an independent reference, that lets designers iterate where iteration is still possible, before the build.

英文版，系统定位段落，供摘要改写。SpaceDC is a physics-based digital twin prototype for orbital AI data centers. Existing satellite computing emulators build digital twin instances, with power, thermal, and computation models fitted to the telemetry and hardware profiles of satellites that already fly, so their validity is confined to the measured envelope. SpaceDC derives every model from mechanism, with parameters that map one-to-one to design variables, and solves the orbit, power, thermal, and compute coupling in the time domain, which enables design-space exploration for satellites that do not yet exist. Fidelity is established channel by channel against STK 11.6 and published GPU power-capping measurements.

一句话版本，按场合选用。给系统领域，Existing platforms emulate instances, SpaceDC explores designs。给任何领域，A satellite cannot be debugged after launch, SpaceDC lets you debug it before。

### 类比句，可选

处理器设计者在流片前用机理级仿真器探索设计空间，算力卫星在发射前需要同样的工具。这个类比一句话就能让系统领域的审稿人明白平台的位置，是否放进引言由篇幅决定。

## 五、审稿人反驳预案

| 预期反对意见 | 回应 |
| --- | --- |
| Rhone 已经有电热算闭环 | 承认回路拓扑相同，指出它的热边界是实测接口温度、温度到算力是查表，设计参数不在回路上，引 rhone-atc25.pdf 4.2 节与 9 节 |
| OEC 早就改过卫星设计再仿真 | 承认并引用它作为先例，指出它无热模型、十瓦级、功耗实测于特定芯片，我们把设计空间扩到热与数据中心级算力 |
| 对标 STK 不是你们发明的 | 承认，引 PowerCubeSat 与 Vallado 为先例，贡献表述改为第一次铺满耦合链 |
| 你们的耦合回路整体没有真值 | 承认，论证结构是每条边各自验证加守恒律组合，并指出这是一切设计阶段方法共同的认识论边界，Turyshev 的稳态模型同样如此且粒度更粗 |
| V100 校准是地面数据 | 承认，指出真空中辐射换热是我们物理模型的求解对象而非芯片模型的输入假设，芯片模型输入是功率预算与温度，这两个量在地面与在轨的语义相同 |
| 单节点集总热模型太粗 | 承认，定位是架构阶段设计筛选而非板级热设计，与 Turyshev 的架构级集总模型同级但多了时间域与算力耦合，细化方向在 future work |

## 六、对论文正文的落地

相关工作段按两半结构写，先航天设计工具一半，后空间计算平台一半，各自给出它们缺失的一侧，Rhone 单独给两到三句准确刻画，语气是互补而非贬低，它面向运行期我们面向设计期。gap 段用第二节的一句话表述。引言的挑战段用 Turyshev 与 Suncatcher 的原文自认作证据，他们替我们写好了需求。摘要里的独特性用第四节的一句话定位改写为英文。
