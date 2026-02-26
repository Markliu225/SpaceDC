/* ================================================================
 *  trend-chart.js — Real-time telemetry trend chart
 * ================================================================ */

function drawTrend() {
  const W = tC.width, H = tC.height;
  if (W < 10 || H < 10) return;
  tX.clearRect(0, 0, W, H);

  // Background
  tX.fillStyle = 'rgba(4,8,18,0.98)'; tX.fillRect(0, 0, W, H);
  const padL = 40, padR = 10, padT = 22, padB = 18;
  const gW = W - padL - padR, gH = H - padT - padB;

  // Grid
  tX.strokeStyle = 'rgba(13,32,64,0.5)'; tX.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = padT + i * (gH / 4);
    tX.beginPath(); tX.moveTo(padL, y); tX.lineTo(padL + gW, y); tX.stroke();
    tX.fillStyle = 'rgba(58,90,122,0.6)'; tX.font = '7px Share Tech Mono'; tX.textAlign = 'right';
    const val = Math.round(100 - i * 25);
    tX.fillText(val + '%', padL - 4, y + 3);
  }

  // Normalization helpers
  const tech = CELL_TECHS[currentCellTech];
  const cool = COOLANTS[currentCoolant];
  const peakSolar = Math.max(1, wingCount * wingArea * 1367 * tech.eff / 1000);
  const Tsurf = 58 + 273.15;
  const peakRad = Math.max(1, (radEpsilon * SIGMA * radCount * radArea * 0.9 * (Tsurf ** 4 - 2.7 ** 4)) / 1000 * cool.heatCapFactor);

  const lines = [
    { data: trendData.solar, color: '#ffe066', norm: v => Math.min(100, v / peakSolar * 100) },
    { data: trendData.bat,   color: '#ff6b00', norm: v => v },
    { data: trendData.rad,   color: '#ff4400', norm: v => Math.min(100, v / peakRad * 100) },
    { data: trendData.gpuT,  color: '#00d4ff', norm: v => Math.min(100, Math.max(0, (v - 20) / 80 * 100)) },
  ];

  // Eclipse shading
  const n = trendData.solar.length;
  if (n > 1) {
    for (let i = 0; i < n; i++) {
      if (trendData.solar[i] < 1) {
        const x = padL + (i / (n - 1)) * gW;
        tX.fillStyle = 'rgba(0,20,80,0.15)'; tX.fillRect(x - 0.5, padT, 1.5, gH);
      }
    }
  }

  // Draw trend lines
  lines.forEach(line => {
    if (line.data.length < 2) return;
    tX.beginPath();
    const pts = line.data;
    for (let i = 0; i < pts.length; i++) {
      const x = padL + (i / (pts.length - 1)) * gW;
      const y = padT + gH - (line.norm(pts[i]) / 100) * gH;
      i === 0 ? tX.moveTo(x, y) : tX.lineTo(x, y);
    }
    tX.strokeStyle = line.color; tX.lineWidth = 1.2; tX.stroke();
    // Glow
    tX.strokeStyle = line.color.replace(')', ',0.3)').replace('rgb', 'rgba');
    tX.lineWidth = 3; tX.stroke();
  });

  // Time axis
  tX.textAlign = 'center'; tX.fillStyle = 'rgba(58,90,122,0.5)'; tX.font = '6px Share Tech Mono';
  for (let i = 0; i <= 4; i++) {
    const x = padL + i * (gW / 4);
    tX.fillText(`−${Math.round((4 - i) / 4 * TREND_MAX)}`, x, H - 4);
  }
  tX.fillText('NOW', padL + gW, H - 4);

  // Current values at right edge
  if (n > 0) {
    const labelData = [
      { val: trendData.solar[n - 1].toFixed(0) + 'kW', color: '#ffe066' },
      { val: trendData.bat[n - 1].toFixed(0) + '%',    color: '#ff6b00' },
      { val: trendData.rad[n - 1].toFixed(0) + 'kW',   color: '#ff4400' },
      { val: trendData.gpuT[n - 1].toFixed(0) + '°C',  color: '#00d4ff' },
    ];
    labelData.forEach((l, i) => {
      tX.fillStyle = l.color; tX.font = 'bold 7px Share Tech Mono'; tX.textAlign = 'left';
      tX.fillText(l.val, padL + gW + 3, padT + 12 + i * 12);
    });
  }
}
