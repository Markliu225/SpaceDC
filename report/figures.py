"""Draws the block diagrams used by the design report (matplotlib, no GUI).

Run:  python figures.py   ->  report/figures/*.png
"""
from __future__ import annotations

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "figures")
os.makedirs(OUT, exist_ok=True)

plt.rcParams["font.family"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#1F2933"
LINE = "#5B6470"
FILL_ROOT = "#D9E4F2"
FILL_L1 = "#E8EEF6"
FILL_L2 = "#FFFFFF"
DPI = 220


def _box(ax, x, y, w, h, text, fill=FILL_L2, fs=9, bold=False, edge=LINE, lw=1.0,
         rounded=True):
    style = "round,pad=0.02,rounding_size=0.08" if rounded else "square,pad=0.02"
    p = FancyBboxPatch((x, y), w, h, boxstyle=style, linewidth=lw,
                       edgecolor=edge, facecolor=fill)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
            color=INK, fontweight="bold" if bold else "normal", wrap=True)


def _line(ax, x0, y0, x1, y1, lw=1.0):
    ax.plot([x0, x1], [y0, y1], color=LINE, lw=lw, solid_capstyle="round", zorder=0)


def _arrow(ax, x0, y0, x1, y1, lw=1.2, color=LINE, style="-|>"):
    a = FancyArrowPatch((x0, y0), (x1, y1), arrowstyle=style, mutation_scale=12,
                        lw=lw, color=color, zorder=1)
    ax.add_patch(a)


def _finish(fig, ax, name, w, h):
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(os.path.join(OUT, name), dpi=DPI, bbox_inches="tight",
                pad_inches=0.05, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Generic org-chart style tree: root -> groups -> stacked leaves
# ---------------------------------------------------------------------------
def tree(name, root, groups, col_w=2.6, gap=0.35, leaf_h=0.52, leaf_gap=0.14,
         root_h=0.62, g_h=0.62, fs_leaf=8.5, fs_group=9, fs_root=10):
    n = len(groups)
    total_w = n * col_w + (n - 1) * gap
    max_leaves = max(len(ls) for _, ls in groups)
    height = root_h + 0.6 + g_h + 0.45 + max_leaves * (leaf_h + leaf_gap) + 0.3
    fig, ax = plt.subplots(figsize=(max(5.0, total_w * 0.95), height * 0.95))
    top = height - 0.15
    # root
    rw = min(total_w, max(3.2, col_w * 1.4))
    rx = (total_w - rw) / 2
    _box(ax, rx, top - root_h, rw, root_h, root, fill=FILL_ROOT, fs=fs_root, bold=True)
    y_bus = top - root_h - 0.3
    _line(ax, total_w / 2, top - root_h, total_w / 2, y_bus)
    xs = [i * (col_w + gap) + col_w / 2 for i in range(n)]
    if n > 1:
        _line(ax, xs[0], y_bus, xs[-1], y_bus)
    gy = y_bus - 0.3 - g_h
    for x, (gname, leaves) in zip(xs, groups):
        _line(ax, x, y_bus, x, gy + g_h)
        _box(ax, x - col_w / 2, gy, col_w, g_h, gname, fill=FILL_L1, fs=fs_group, bold=True)
        ly = gy - 0.45
        if leaves:
            _line(ax, x, gy, x, ly)
        for leaf in leaves:
            ly -= leaf_h
            _box(ax, x - col_w / 2 + 0.15, ly, col_w - 0.3, leaf_h, leaf, fs=fs_leaf)
            _line(ax, x, ly + leaf_h, x, ly + leaf_h + leaf_gap)
            ly -= leaf_gap
    _finish(fig, ax, name, total_w, height)


# ---------------------------------------------------------------------------
# Figure 1: layered architecture
# ---------------------------------------------------------------------------
def architecture():
    W, H = 15.6, 9.6
    fig, ax = plt.subplots(figsize=(W * 0.85, H * 0.85))
    band_x, band_w = 1.05, 10.9
    label_w = 0.75

    def band(y, h, title, fill, edge):
        _box(ax, band_x, y, band_w, h, "", fill=fill, edge=edge, lw=1.4, rounded=False)
        _box(ax, 0.2, y, label_w, h, "", fill=edge, edge=edge, rounded=False)
        ax.text(0.2 + label_w / 2, y + h / 2, title, rotation=90, ha="center",
                va="center", fontsize=11, color="white", fontweight="bold")

    # application layer
    ay, ah = 7.15, 2.25
    band(ay, ah, "应用层", "#EEF4FB", "#2E5A88")
    tiles = [("星座配置与效能评估", ["轨道与星座设计器", "星座态势与覆盖分析", "地面站可见性分析"]),
             ("算力卫星数字孪生", ["实时三维孪生视口", "卫星配置器与设计库", "遥测曲线与告警"]),
             ("算力任务效能验证", ["卫星搭建向导与试算", "作业档案适配评估", "设计变体同步对比"])]
    tw = (band_w - 0.3 * 4) / 3
    for i, (t, items) in enumerate(tiles):
        x = band_x + 0.3 + i * (tw + 0.3)
        _box(ax, x, ay + 0.15, tw, ah - 0.3, "", fill="#FFFFFF", edge="#2E5A88")
        ax.text(x + tw / 2, ay + ah - 0.45, t, ha="center", va="center", fontsize=9.5,
                fontweight="bold", color=INK)
        for j, it in enumerate(items):
            _box(ax, x + 0.18, ay + ah - 0.95 - j * 0.48, tw - 0.36, 0.4, it, fs=8)

    # service layer
    sy, sh = 3.55, 3.25
    band(sy, sh, "服务层", "#FDF3EA", "#B85C1E")
    groups = [("仿真引擎服务", ["1 Hz 实时步进", "固定顺序模型调用", "态势快照与读时刷新", "对比仿真会话"]),
              ("仿真控管服务", ["配置与几何指令", "设计与搭建指令", "作业档案与姿态指令", "任务与星座切换"]),
              ("数据收发服务", ["WebSocket 广播", "REST 接口", "渲染端状态轮询", "统一消息信封"]),
              ("三维渲染服务", ["RTX 实时渲染", "USD 舞台与会话层", "WebRTC 推流", "场景与拾取扩展"])]
    gw = (band_w - 0.3 * 5) / 4
    for i, (t, items) in enumerate(groups):
        x = band_x + 0.3 + i * (gw + 0.3)
        _box(ax, x, sy + 0.15, gw, sh - 0.3, "", fill="#FFFFFF", edge="#B85C1E")
        ax.text(x + gw / 2, sy + sh - 0.45, t, ha="center", va="center", fontsize=9.5,
                fontweight="bold", color=INK)
        for j, it in enumerate(items):
            _box(ax, x + 0.15, sy + sh - 0.95 - j * 0.55, gw - 0.3, 0.44, it, fs=8)

    # computation layer
    cy, ch = 0.2, 3.05
    band(cy, ch, "计算层", "#EEF7EE", "#2F6B3A")
    cols = [("轨道", ["SGP4 轨道外推", "星下点与坐标转换", "太阳位置与地影", "Walker 星座生成"]),
            ("通信", ["地面站可见性", "接入窗口与下行", "通信波段目录"]),
            ("算力", ["GPU 硬件目录", "类型化作业表", "DVFS 功耗频率关系", "LLM 推理性能模型"]),
            ("电源", ["太阳翼发电", "电池片效率与温度系数", "电池荷电状态积分"]),
            ("热控", ["辐射板辐射散热", "环境热流", "集总热节点", "GPU 结温与降频"])]
    cw = (band_w - 0.25 * 6) / 5
    for i, (t, items) in enumerate(cols):
        x = band_x + 0.25 + i * (cw + 0.25)
        _box(ax, x, cy + 0.12, cw, ch - 0.24, "", fill="#FFFFFF", edge="#2F6B3A")
        ax.text(x + cw / 2, cy + ch - 0.4, t, ha="center", va="center", fontsize=9.5,
                fontweight="bold", color=INK)
        for j, it in enumerate(items):
            _box(ax, x + 0.12, cy + ch - 0.85 - j * 0.52, cw - 0.24, 0.42, it, fs=7.8)

    # asset library
    axx, aw = 13.0, 2.45
    _box(ax, axx, 0.2, aw, 9.2, "", fill="#F7EEF7", edge="#7A3E7A", lw=1.4, rounded=False)
    ax.text(axx + aw / 2, 9.05, "三维资产库", ha="center", va="center", fontsize=10.5,
            fontweight="bold", color=INK)
    for j, it in enumerate(["参数化卫星模型生成器", "六种整星构型", "USD 舞台库", "几何参数存储",
                            "离线软件渲染器", "设计缩略图缓存"]):
        _box(ax, axx + 0.2, 8.2 - j * 0.85, aw - 0.4, 0.62, it, fs=8.5)

    # arrows between layers
    mid = band_x + band_w / 2
    _arrow(ax, mid - 0.25, sy + sh, mid - 0.25, ay, lw=1.4)
    _arrow(ax, mid + 0.25, ay, mid + 0.25, sy + sh, lw=1.4)
    ax.text(mid + 0.45, (ay + sy + sh) / 2, "控制指令下行，态势广播与视频流上行",
            fontsize=8, va="center", color=LINE)
    _arrow(ax, mid - 0.25, sy, mid - 0.25, cy + ch, lw=1.4)
    _arrow(ax, mid + 0.25, cy + ch, mid + 0.25, sy, lw=1.4)
    ax.text(mid + 0.45, (sy + cy + ch) / 2, "每个物理步按固定顺序调用全部模型",
            fontsize=8, va="center", color=LINE)
    _arrow(ax, band_x + band_w, 5.4, axx, 5.4, lw=1.4)
    _arrow(ax, axx, 4.7, band_x + band_w, 4.7, lw=1.4)
    ax.text((band_x + band_w + axx) / 2, 5.62, "几何参数", fontsize=7.5, ha="center", color=LINE)
    ax.text((band_x + band_w + axx) / 2, 4.32, "USD 模型", fontsize=7.5, ha="center", color=LINE)
    _finish(fig, ax, "fig_architecture.png", W, H)


# ---------------------------------------------------------------------------
# Usage flow (lanes)
# ---------------------------------------------------------------------------
def usage_flow():
    W, H = 15.0, 9.2
    fig, ax = plt.subplots(figsize=(W * 0.82, H * 0.82))
    lanes = ["态势展示与仿真管理分系统", "数据收发分系统", "仿真引擎分系统", "三维渲染分系统与三维资产分系统"]
    lw_ = W / 4
    for i, name in enumerate(lanes):
        x = i * lw_
        fill = ["#EEF4FB", "#EEF7EE", "#FDF3EA", "#F7EEF7"][i]
        _box(ax, x + 0.08, 0.1, lw_ - 0.16, H - 0.2, "", fill=fill, edge="#C9CFD6", rounded=False)
        ax.text(x + lw_ / 2, H - 0.42, name, ha="center", va="center", fontsize=9, fontweight="bold")

    def node(lane, y, text, h=0.62, w=None, fill="#FFFFFF"):
        w = w or (lw_ - 0.7)
        x = lane * lw_ + (lw_ - w) / 2
        _box(ax, x, y - h / 2, w, h, text, fs=8.2, fill=fill)
        return (x, x + w, y)

    bw = 0.62
    a1 = node(0, 7.7, "编辑想定：卫星搭建向导、\n配置器、设计库、轨道设计器", h=0.75)
    a2 = node(1, 7.7, "接收 REST 或 WebSocket 指令，\n解析统一信封", h=0.75)
    a3 = node(2, 7.7, "指令响应：更新配置、几何、\n作业档案、轨道预设", h=0.75)
    a4 = node(3, 7.7, "几何变化时再生 USD 模型，\n版本号递增，渲染端重载", h=0.75)
    b1 = node(0, 6.3, "开始仿真")
    b3 = node(2, 6.3, "仿真初始化：恢复几何、\n装配实体模型、启动步进协程", h=0.75)
    c3 = node(2, 5.0, "实时步进推演：轨道、光照、\n发电、作业、电池、热、告警", h=0.9)
    c2 = node(1, 5.0, "态势数据 1 Hz 广播，\n渲染端 5 Hz 轮询", h=0.75)
    c1 = node(0, 5.0, "遥测曲线、状态卡片、\n事件流实时刷新", h=0.75)
    c4 = node(3, 5.0, "逐帧投影态势到 USD，\nRTX 渲染并经 WebRTC 推流", h=0.75)
    d1 = node(0, 3.6, "运行期操作：姿态、展开、\n对比、地面站配置", h=0.75)
    d3 = node(2, 3.6, "对比会话：离线变体引擎\n与在线步进同步推进", h=0.75)
    e3 = node(2, 2.35, "仿真结束或用户暂停")
    e1 = node(0, 2.35, "浏览器显示三维视口\n与全部分析页签", h=0.75)
    f = node(2, 1.25, "结束", fill=FILL_ROOT, w=2.0)

    def arr(p, q, dy=0):
        # horizontal arrow between lanes, at the lower y of the two nodes
        if p[2] == q[2]:
            if p[0] < q[0]:
                _arrow(ax, p[1], p[2] + dy, q[0], q[2] + dy)
            else:
                _arrow(ax, p[0], p[2] + dy, q[1], q[2] + dy)

    def varr(p, q):
        xm = (p[0] + p[1]) / 2
        _arrow(ax, xm, p[2] - 0.4, xm, q[2] + 0.4)

    arr(a1, a2); arr(a2, a3); arr(a3, a4)
    varr(a1, b1)
    arr(b1, b3)  # start -> engine init (spans lane 1)
    varr(b3, c3)
    arr(c3, c2); arr(c2, c1); arr(c3, c4)
    varr(c1, d1)
    arr(d1, d3)
    varr(d3, e3)
    varr(d1, e1)
    varr(e3, f)
    # feedback: rendering stream back to the browser, routed along the bottom
    xc4 = (c4[0] + c4[1]) / 2
    xe1 = (e1[0] + e1[1]) / 2
    ax.plot([xc4, xc4, xe1], [c4[2] - 0.4, 0.5, 0.5], color=LINE, lw=1.2, zorder=2)
    _arrow(ax, xe1, 0.5, xe1, e1[2] - 0.4)
    ax.text((xc4 + xe1) / 2, 0.68, "WebRTC 视频流回到浏览器视口", fontsize=8, color=LINE, ha="center")
    _finish(fig, ax, "fig_usage_flow.png", W, H)


# ---------------------------------------------------------------------------
# Engine tick flow (vertical flowchart)
# ---------------------------------------------------------------------------
def tick_flow():
    steps = [
        "读取仿真时间 t，取当前配置、几何与作业档案",
        "星座与被跟踪卫星轨道外推，得到 TEME 位置速度",
        "星下点、日照、太阳矢量、可见太阳盘分数、地面站仰角",
        "太阳翼发电：面积、效率、姿态入射率、日地距离、温度降额、展开度",
        "作业表取当前作业块，按卡型分组求 GPU 工作点与实际功耗",
        "电池荷电状态积分，充电计往返损耗",
        "热平衡积分：耗散热流与环境热流入，辐射板辐射出",
        "下行链路可见性与速率",
        "设计裕度校验与告警判定",
        "生成态势快照并广播，对比会话同步步进一步",
    ]
    W = 8.6
    h_box, gap = 0.62, 0.32
    H = 1.6 + len(steps) * (h_box + gap) + 1.0
    fig, ax = plt.subplots(figsize=(W * 0.8, H * 0.8))
    y = H - 0.4
    _box(ax, W / 2 - 1.0, y - 0.5, 2.0, 0.5, "开始一个物理步", fill=FILL_ROOT, fs=9, bold=True)
    prev_y = y - 0.5
    for s in steps:
        y = prev_y - gap
        _box(ax, 0.6, y - h_box, W - 1.2, h_box, s, fs=8.6)
        _arrow(ax, W / 2, prev_y, W / 2, y)
        prev_y = y - h_box
    y = prev_y - gap
    _box(ax, W / 2 - 1.2, y - 0.5, 2.4, 0.5, "等待下一个 1 Hz 心跳", fill=FILL_ROOT, fs=9, bold=True)
    _arrow(ax, W / 2, prev_y, W / 2, y)
    _finish(fig, ax, "fig_tick_flow.png", W, H)


# ---------------------------------------------------------------------------
# Thermal-compute feedback loop
# ---------------------------------------------------------------------------
def coupling_loop():
    W, H = 12.0, 5.2
    fig, ax = plt.subplots(figsize=(W * 0.8, H * 0.8))
    nodes = [
        (0.4, 3.5, "轨道与光照\n位置、日照、太阳矢量"),
        (3.3, 3.5, "太阳翼与电池\n发电功率、荷电状态"),
        (6.2, 3.5, "GPU 载荷\n功率预算、频率、吞吐"),
        (9.1, 3.5, "散热板与结构\n耗散热、环境热流、温度"),
    ]
    bw, bh = 2.5, 1.1
    for x, y, t in nodes:
        _box(ax, x, y, bw, bh, t, fs=8.8, fill=FILL_L1)
    for i in range(3):
        x0 = nodes[i][0] + bw
        x1 = nodes[i + 1][0]
        _arrow(ax, x0, 4.05, x1, 4.05, lw=1.4)
    labels = ["日照与入射率", "可用功率", "实际功耗即产热"]
    for i, lb in enumerate(labels):
        xm = (nodes[i][0] + bw + nodes[i + 1][0]) / 2
        ax.text(xm, 4.78, lb, ha="center", fontsize=8, color=LINE)
    # feedback arrow from thermal back to GPU
    _arrow(ax, 9.1 + bw / 2, 3.5, 9.1 + bw / 2, 2.4, lw=1.4)
    _line(ax, 9.1 + bw / 2, 2.4, 6.2 + bw / 2, 2.4, lw=1.4)
    _arrow(ax, 6.2 + bw / 2, 2.4, 6.2 + bw / 2, 3.5, lw=1.4)
    ax.text(7.65 + 1.45, 2.05, "结构温度即冷板温度，限制 GPU 功率预算", ha="center",
            fontsize=8.5, color=INK)
    # feedback from thermal to solar (cell derating)
    _line(ax, 9.1 + bw - 0.3, 3.5, 9.1 + bw - 0.3, 1.3, lw=1.1)
    _line(ax, 9.1 + bw - 0.3, 1.3, 3.3 + bw / 2, 1.3, lw=1.1)
    _arrow(ax, 3.3 + bw / 2, 1.3, 3.3 + bw / 2, 3.5, lw=1.1)
    ax.text(6.3, 0.95, "结构温度对电池片效率的温度降额", ha="center", fontsize=8.5, color=INK)
    _box(ax, 0.4, 0.3, 2.5, 0.55, "回路每步闭合一次", fill=FILL_ROOT, fs=8.5, bold=True)
    _finish(fig, ax, "fig_coupling_loop.png", W, H)


# ---------------------------------------------------------------------------
# Model hierarchy: concept -> algorithm -> entity
# ---------------------------------------------------------------------------
def model_hierarchy():
    W, H = 12.4, 5.0
    fig, ax = plt.subplots(figsize=(W * 0.8, H * 0.8))
    rows = [
        (3.6, "概念模型", ["算力卫星", "卫星星座", "地面站与目标"], "#FBE9DD"),
        (2.0, "算法模型", ["轨道外推与地影", "发电与储能", "热平衡", "GPU 推理性能", "可见性与链路"], "#E4E1F2"),
        (0.4, "实体模型", ["卫星实体与载荷组件", "星座实体", "地面站实体"], "#E3E7EC"),
    ]
    for y, title, items, fill in rows:
        _box(ax, 0.3, y, W - 0.6, 1.15, "", fill="#F4F5F7", edge=LINE, rounded=False)
        _box(ax, 0.45, y + 0.2, 1.7, 0.75, title, fill=fill, fs=9.5, bold=True)
        n = len(items)
        avail = W - 0.6 - 2.2
        iw = min(2.6, (avail - 0.2 * (n - 1)) / n)
        x0 = 2.4 + (avail - (n * iw + 0.2 * (n - 1))) / 2
        for i, it in enumerate(items):
            _box(ax, x0 + i * (iw + 0.2), y + 0.2, iw, 0.75, it, fs=8.6, fill=fill)
    for y in (3.6, 2.0):
        _arrow(ax, W / 2, y - 0.03, W / 2, y - 0.42, lw=1.6)
    _finish(fig, ax, "fig_model_hierarchy.png", W, H)


# ---------------------------------------------------------------------------
# Satellite entity run flow
# ---------------------------------------------------------------------------
def entity_flow():
    steps = [
        ("开始", True), ("实体初始化：平台常数、槽位载荷、几何面积、初始荷电与温度", False),
        ("轨道外推与光照判定", False), ("发电与作业工作点求解", False),
        ("电池与热节点积分", False), ("结温是否超过降频目标", "dec"),
        ("收缩功率预算，记录降频告警", False), ("写回状态并进入下一步", False), ("仿真结束", True),
    ]
    W = 8.2
    hb, gap = 0.6, 0.3
    H = 1.0 + len(steps) * (hb + gap) + 0.4
    fig, ax = plt.subplots(figsize=(W * 0.8, H * 0.8))
    y = H - 0.3
    prev = None
    for text, kind in steps:
        y_top = y
        if kind == "dec":
            # diamond
            cx, cy = W / 2, y_top - hb / 2
            ax.add_patch(plt.Polygon([(cx - 2.6, cy), (cx, cy + hb / 2 + 0.05), (cx + 2.6, cy),
                                      (cx, cy - hb / 2 - 0.05)], closed=True, fc="#FFFFFF", ec=LINE))
            ax.text(cx, cy, text, ha="center", va="center", fontsize=8.5)
            ax.text(cx + 2.7, cy + 0.15, "否", fontsize=8, color=LINE)
            ax.text(cx + 0.12, cy - hb / 2 - 0.25, "是", fontsize=8, color=LINE)
        elif kind is True:
            _box(ax, W / 2 - 1.0, y_top - hb, 2.0, hb, text, fill=FILL_ROOT, fs=9, bold=True)
        else:
            _box(ax, 0.5, y_top - hb, W - 1.0, hb, text, fs=8.6)
        if prev is not None:
            _arrow(ax, W / 2, prev, W / 2, y_top + (0.05 if kind == "dec" else 0))
        prev = y_top - hb - (0.05 if kind == "dec" else 0)
        y = prev - gap
    # "no" branch bypasses the throttle box: from diamond right side to the 'write back' box
    dec_idx = 5
    y_dec = H - 0.3 - dec_idx * (hb + gap) - hb / 2
    y_wb = H - 0.3 - 7 * (hb + gap) - hb / 2
    _line(ax, W / 2 + 2.6, y_dec, W - 0.25, y_dec)
    _line(ax, W - 0.25, y_dec, W - 0.25, y_wb)
    _arrow(ax, W - 0.25, y_wb, W - 0.5, y_wb)
    # loop back from write-back to orbit step
    y_orb = H - 0.3 - 2 * (hb + gap) - hb / 2
    _line(ax, 0.5, y_wb, 0.25, y_wb)
    _line(ax, 0.25, y_wb, 0.25, y_orb)
    _arrow(ax, 0.25, y_orb, 0.5, y_orb)
    _finish(fig, ax, "fig_entity_flow.png", W, H)


# ---------------------------------------------------------------------------
# Time cascade
# ---------------------------------------------------------------------------
def time_cascade():
    W, H = 13.0, 3.6
    fig, ax = plt.subplots(figsize=(W * 0.8, H * 0.8))
    items = [
        ("物理步进\n1 Hz", "仿真引擎推进仿真时间\n并积分状态"),
        ("读时刷新\n每次读取", "按仿真时间与墙钟分数\n重算几何量"),
        ("渲染端轮询\n5 Hz", "拉取态势，更新锚点\n与缓动目标"),
        ("帧回调\n约 30 fps", "指数缓动逼近目标，\n外插星座相位"),
        ("显示外插\n刷新率", "浏览器抹平\n1 Hz 台阶"),
    ]
    bw, bh = 2.2, 1.0
    x = 0.3
    for i, (t, d) in enumerate(items):
        _box(ax, x, 2.0, bw, bh, t, fill=FILL_L1, fs=8.8, bold=True)
        ax.text(x + bw / 2, 1.4, d, ha="center", va="center", fontsize=7.6, color=INK)
        if i < len(items) - 1:
            _arrow(ax, x + bw, 2.5, x + bw + 0.35, 2.5, lw=1.3)
        x += bw + 0.35
    ax.text(W / 2, 0.55, "全系统只有一个权威时钟，其余时间都是对它的降频采样或升频平滑",
            ha="center", fontsize=8.8, color=INK)
    _finish(fig, ax, "fig_time_cascade.png", W, H)


def main():
    architecture()
    tree("fig_system_tree.png", "在轨算力数据中心数字孪生平台", [
        ("仿真模型分系统", ["计算模型模块", "模型标准接口模块", "实体模型模块", "载荷组件模型模块"]),
        ("仿真引擎分系统", ["模型初始化模块", "实时步进推演模块", "指令响应模块", "态势输出模块", "对比仿真模块"]),
        ("数据收发分系统", ["WebSocket 广播模块", "REST 接口模块", "渲染端轮询接口", "数据实体契约"]),
        ("态势展示与仿真管理分系统", ["态势总览页", "卫星孪生页", "卫星搭建向导", "轨道与地面站工作台", "对比面板"]),
        ("三维渲染分系统", ["渲染宿主应用", "场景扩展", "拾取扩展", "消息扩展", "推流层"]),
        ("三维资产分系统", ["参数化模型生成器", "整星构型库", "USD 舞台库", "离线软件渲染器"]),
    ], col_w=2.45, gap=0.28, fs_leaf=8, fs_group=8.6)
    tree("fig_model_subsystem.png", "仿真模型分系统", [
        ("计算模型模块", ["轨道外推", "星下点与坐标转换", "太阳位置与地影", "地面站可见性", "太阳翼发电",
                     "电池荷电状态", "热平衡", "GPU 作业与功耗", "LLM 推理性能", "设计裕度校验", "地面站分析"]),
        ("模型标准接口模块", ["初始化接口", "步进推进接口", "指令响应接口", "态势输出接口"]),
        ("实体模型模块", ["算力卫星实体", "星座实体", "地面站实体"]),
        ("载荷组件模型模块", ["太阳翼组件", "电池组件", "散热板组件", "GPU 载荷组件", "通信组件"]),
    ], col_w=2.9, gap=0.35)
    tree("fig_engine_subsystem.png", "仿真引擎分系统", [
        ("模型初始化模块", ["几何恢复", "实体装配", "参数表加载"]),
        ("实时步进推演模块", ["1 Hz 心跳协程", "固定顺序模型调用", "状态积分", "告警判定"]),
        ("指令响应模块", ["配置与几何指令", "设计与搭建指令", "作业与姿态指令", "任务与星座指令"]),
        ("态势输出模块", ["态势快照", "读时运动学刷新", "广播回调"]),
        ("对比仿真模块", ["一致性快照", "离线变体引擎", "同步步进会话", "试算引擎"]),
    ], col_w=2.6, gap=0.3)
    tree("fig_comm_subsystem.png", "数据收发分系统", [
        ("WebSocket 广播模块", ["连接管理", "指令分发", "态势广播", "确认与错误回执"]),
        ("REST 接口模块", ["状态读取", "配置与几何", "设计与搭建", "轨道与地面站", "对比与任务"]),
        ("渲染端轮询接口", ["状态轮询", "拾取上报", "场景就绪通知"]),
        ("数据实体契约", ["态势数据包", "卫星状态", "卫星配置", "孪生几何"]),
    ], col_w=2.9, gap=0.35)
    tree("fig_ui_subsystem.png", "态势展示与仿真管理分系统", [
        ("态势总览页", ["三维地球与星座", "遥测参数卡", "星座预设切换", "事件流"]),
        ("轨道与地面站工作台", ["轨道设计页签", "覆盖页签", "太阳直方图页签", "波段对比页签"]),
        ("卫星孪生页", ["三维孪生视口", "卫星配置器", "设计库", "遥测曲线带"]),
        ("卫星搭建向导", ["平台选型", "结构设计", "载荷设计", "作业档案"]),
        ("对比面板", ["对比维度选择", "变体候选值", "实时数值表"]),
    ], col_w=2.6, gap=0.3)
    tree("fig_render_subsystem.png", "三维渲染分系统", [
        ("渲染宿主应用", ["RTX 渲染器", "USD 舞台与会话层", "帧事件流", "WebRTC 推流层"]),
        ("场景扩展", ["态势轮询", "舞台切换", "逐帧驱动", "模型热重载"]),
        ("拾取扩展", ["构件拾取事件", "选择上报"]),
        ("消息扩展", ["浏览器与渲染端数据通道"]),
        ("启动与布局扩展", ["初始舞台打开", "窗口布局"]),
    ], col_w=2.6, gap=0.3)
    tree("fig_asset_subsystem.png", "三维资产分系统", [
        ("参数化模型生成器", ["骨干与机架槽位", "太阳翼板簇", "散热板", "刀片与卡型色标"]),
        ("整星构型库", ["单桁架", "双桁架塔", "毯式翼", "十字翼小卫星", "风车翼通信星", "扁平载荷舱"]),
        ("USD 舞台库", ["总览舞台", "卫星特写舞台", "地球与星野", "灯光与相机"]),
        ("离线软件渲染器", ["无 GL 光栅化", "设计缩略图", "几何核对图"]),
    ], col_w=2.9, gap=0.35)
    usage_flow()
    tick_flow()
    coupling_loop()
    model_hierarchy()
    entity_flow()
    time_cascade()
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
