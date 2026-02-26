/* ================================================================
 *  satellite.js — drawSatIcon() + drawDetail() (dynamic geometry)
 * ================================================================ */

function drawSatIcon(ctx, x, y, angle, eclipse, s) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(angle + Math.PI / 2);

  // --- Dynamic geometry from DT controls ---
  const wingWBase = Math.max(28, Math.min(80, (wingArea / 350) * 52)) * s;
  const wingsPerSide = Math.ceil(wingCount / 2);
  const wingH = 12 * s;
  const wingGap = 2 * s;
  const totalWingStackH = wingsPerSide * wingH + (wingsPerSide - 1) * wingGap;

  const radsPerSide = Math.ceil(radCount / 2);
  const radHBase = Math.max(12, Math.min(32, (radArea / 143) * 20)) * s;
  const radW = 8 * s;
  const radGap = 1.5 * s;
  const totalRadStackH = radsPerSide * radHBase + (radsPerSide - 1) * radGap;

  const cellCols = Math.max(3, Math.min(10, Math.round(wingWBase / (6 * s))));
  const cellRows = 2;
  const bw = 12 * s, bh = 14 * s;
  const armLen = 4 * s;

  // --- Draw Solar Wings (stacked per side) ---
  for (let side of [-1, 1]) {
    const nThisSide = side > 0 ? Math.ceil(wingCount / 2) : Math.floor(wingCount / 2);
    if (nThisSide === 0) continue;
    const stackH = nThisSide * wingH + (nThisSide - 1) * wingGap;
    for (let wi = 0; wi < nThisSide; wi++) {
      const wy = -stackH / 2 + wi * (wingH + wingGap);
      const wx = side > 0 ? (bw / 2 + armLen) : -(bw / 2 + armLen + wingWBase);
      ctx.fillStyle = eclipse ? '#1a2030' : '#1a3060'; ctx.fillRect(wx, wy, wingWBase, wingH);
      const cw = wingWBase / cellCols, ch = wingH / cellRows;
      for (let col = 0; col < cellCols; col++) for (let row = 0; row < cellRows; row++) {
        const cx2 = wx + col * cw, cy2 = wy + row * ch;
        const bright = eclipse ? 0 : 0.45 + 0.5 * Math.random() + 0.05;
        ctx.fillStyle = eclipse ? 'rgb(18,20,52)' : `rgb(${Math.floor(35 + bright * 65)},${Math.floor(75 + bright * 90)},${Math.floor(22 + bright * 14)})`;
        ctx.fillRect(cx2 + 0.5, cy2 + 0.5, cw - 1, ch - 1);
        ctx.strokeStyle = 'rgba(0,0,0,0.45)'; ctx.lineWidth = 0.5 / s; ctx.strokeRect(cx2 + 0.5, cy2 + 0.5, cw - 1, ch - 1);
        if (!eclipse && col % 2 === 0 && row === 0) { ctx.fillStyle = 'rgba(255,255,180,0.08)'; ctx.fillRect(cx2 + 1, cy2 + 1, cw - 2, 1.5); }
      }
      ctx.strokeStyle = eclipse ? '#334466' : '#4488cc'; ctx.lineWidth = 1 / s; ctx.strokeRect(wx, wy, wingWBase, wingH);
      if (!eclipse) { ctx.shadowColor = 'rgba(255,200,0,0.3)'; ctx.shadowBlur = 7 * s; ctx.strokeStyle = 'rgba(255,220,50,0.22)'; ctx.strokeRect(wx, wy, wingWBase, wingH); ctx.shadowBlur = 0; }
    }
    ctx.fillStyle = '#334455';
    const armX = side > 0 ? bw / 2 : -(bw / 2 + armLen);
    ctx.fillRect(armX, -1.5 * s, armLen, 3 * s);
  }

  // --- Draw Spacecraft Body ---
  ctx.shadowColor = eclipse ? 'rgba(0,20,60,0.4)' : 'rgba(0,212,255,0.6)'; ctx.shadowBlur = eclipse ? 4 * s : 12 * s;
  ctx.fillStyle = eclipse ? '#1c2535' : '#b8860b'; ctx.fillRect(-bw / 2, -bh / 2, bw, bh);
  ctx.strokeStyle = eclipse ? '#2a3545' : 'rgba(220,180,20,0.4)'; ctx.lineWidth = 0.5 / s;
  for (let i = 1; i < 4; i++) { ctx.beginPath(); ctx.moveTo(-bw / 2 + i * bw / 4, -bh / 2); ctx.lineTo(-bw / 2 + i * bw / 4, bh / 2); ctx.stroke(); }
  for (let i = 1; i < 5; i++) { ctx.beginPath(); ctx.moveTo(-bw / 2, -bh / 2 + i * bh / 5); ctx.lineTo(bw / 2, -bh / 2 + i * bh / 5); ctx.stroke(); }
  ctx.strokeStyle = eclipse ? '#445566' : '#00aadd'; ctx.lineWidth = 1 / s; ctx.strokeRect(-bw / 2, -bh / 2, bw, bh); ctx.shadowBlur = 0;

  // --- Draw Radiator Panels (stacked per side, beside body) ---
  for (let side of [-1, 1]) {
    const nThisSide = side > 0 ? Math.ceil(radCount / 2) : Math.floor(radCount / 2);
    if (nThisSide === 0) continue;
    const stackH = nThisSide * radHBase + (nThisSide - 1) * radGap;
    for (let ri = 0; ri < nThisSide; ri++) {
      const ry = -stackH / 2 + ri * (radHBase + radGap);
      const rx = side > 0 ? bw / 2 : -(bw / 2 + radW);
      const rg = ctx.createLinearGradient(rx, ry, rx + radW, ry + radHBase);
      eclipse ? (rg.addColorStop(0, '#180600'), rg.addColorStop(1, '#0a0300')) : (rg.addColorStop(0, '#cc3300'), rg.addColorStop(0.5, '#ff6600'), rg.addColorStop(1, '#882200'));
      ctx.fillStyle = rg; ctx.fillRect(rx, ry, radW, radHBase);
      const numPipes = Math.max(2, Math.min(6, Math.round(radHBase / (3 * s))));
      ctx.strokeStyle = eclipse ? '#2a0e00' : 'rgba(255,100,0,0.45)'; ctx.lineWidth = 0.6 / s;
      for (let i = 1; i <= numPipes; i++) { const py = ry + i * (radHBase / (numPipes + 1)); ctx.beginPath(); ctx.moveTo(rx + 1, py); ctx.lineTo(rx + radW - 1, py); ctx.stroke(); }
      ctx.strokeStyle = eclipse ? '#3a1000' : '#ff4400'; ctx.lineWidth = 1 / s; ctx.strokeRect(rx, ry, radW, radHBase);
      if (!eclipse) { ctx.shadowColor = 'rgba(255,80,0,0.4)'; ctx.shadowBlur = 5 * s; ctx.strokeStyle = 'rgba(255,80,0,0.3)'; ctx.strokeRect(rx, ry, radW, radHBase); ctx.shadowBlur = 0; }
      for (let r = 0; r < Math.min(3, nThisSide > 3 ? 2 : 3); r++) {
        const ery = ry + radHBase * (r + 1) / (Math.min(3, nThisSide > 3 ? 2 : 3) + 1);
        const erx = rx + (side > 0 ? radW : 0);
        const len = (5 + Math.sin(simTime * 0.012 + r + ri) * 2) * s;
        ctx.beginPath(); ctx.moveTo(erx, ery); ctx.lineTo(erx + (side > 0 ? len : -len), ery);
        ctx.strokeStyle = `rgba(255,80,0,${eclipse ? 0.05 : 0.13 + 0.04 * Math.sin(simTime * 0.02 + r + ri)})`;
        ctx.lineWidth = 1.5 / s; ctx.setLineDash([1, 2]); ctx.stroke(); ctx.setLineDash([]);
      }
    }
  }

  // --- Antenna ---
  ctx.fillStyle = '#667788'; ctx.beginPath(); ctx.arc(0, -bh / 2 - 3 * s, 2 * s, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.moveTo(0, -bh / 2 - 1 * s); ctx.lineTo(0, -bh / 2 - 6 * s);
  ctx.strokeStyle = '#445566'; ctx.lineWidth = 1.5 / s; ctx.stroke();
  ctx.restore();
}

// ================================================================
// SATELLITE DETAIL (annotations follow dynamic sat geometry)
// ================================================================
function drawDetail(eclipse) {
  const W = dC.width, H = dC.height; dX.clearRect(0, 0, W, H);
  const bg = dX.createRadialGradient(W / 2, H / 2, 40, W / 2, H / 2, W * 0.55);
  bg.addColorStop(0, 'rgba(0,12,35,0.95)'); bg.addColorStop(1, 'rgba(0,0,8,0.95)');
  dX.fillStyle = bg; dX.fillRect(0, 0, W, H);
  dX.fillStyle = 'rgba(0,180,255,0.55)'; dX.font = '9px Orbitron'; dX.textAlign = 'center';
  dX.fillText('SPACECRAFT DETAIL · ORBITAL DC-1', W / 2, 20);
  dX.font = '7px Share Tech Mono'; dX.fillStyle = 'rgba(0,180,255,0.3)';
  dX.fillText(eclipse ? 'ECLIPSE — Battery Discharge Active' : 'SUNLIT — Solar Arrays at Peak Output', W / 2, 32);
  dX.textAlign = 'left';
  const sc = Math.min(W, H) * 0.0035;
  const yB = H / 2 + 15;
  drawSatIcon(dX, W / 2, yB, Math.PI / 2, eclipse, sc);

  // Compute geometry dimensions for annotation placement
  const bw = 12 * sc, bh = 14 * sc;
  const armLen = 4 * sc;
  const wingWPx = Math.max(28, Math.min(80, (wingArea / 350) * 52)) * sc;
  const wingsPerSide = Math.ceil(wingCount / 2);
  const wingHPx = 12 * sc;
  const wingGapPx = 2 * sc;
  const totalWingStackH = wingsPerSide * wingHPx + (wingsPerSide - 1) * wingGapPx;
  const radWPx = 8 * sc;
  const radsPerSide = Math.ceil(radCount / 2);
  const radHPx = Math.max(12, Math.min(32, (radArea / 143) * 20)) * sc;
  const totalRadStackH = radsPerSide * radHPx + (radsPerSide - 1) * 1.5 * sc;

  const wingTipOffset = bw / 2 + armLen + wingWPx;
  const tech = CELL_TECHS[currentCellTech];
  const cool = COOLANTS[currentCoolant];

  // --- Left wing annotation ---
  const lwTipX = W / 2 - wingTipOffset;
  const annoLx = Math.max(10, lwTipX - 60);
  const annoLy = yB - Math.max(totalWingStackH / 2, 30) - 10;
  dX.fillStyle = eclipse ? 'rgba(70,70,180,0.7)' : 'rgba(255,220,50,0.88)'; dX.font = 'bold 8px Share Tech Mono';
  dX.fillText('◄ SOLAR WING', annoLx, annoLy);
  dX.font = '7px Share Tech Mono'; dX.fillStyle = eclipse ? 'rgba(60,60,140,0.6)' : 'rgba(255,200,50,0.6)';
  dX.fillText(tech.name, annoLx, annoLy + 11);
  dX.fillText(`${wingArea}m² × ${wingCount} wings`, annoLx, annoLy + 21);
  const perWingPwr = eclipse ? 0 : Math.round(wings.length > 0 && wings[0].output ? wings[0].output : wingArea * 1367 * tech.eff / 1000);
  dX.fillText(eclipse ? 'DARK — 0 kW' : `~${perWingPwr} kW/wing`, annoLx, annoLy + 31);
  dX.strokeStyle = eclipse ? 'rgba(70,70,180,0.25)' : 'rgba(255,220,50,0.3)'; dX.lineWidth = 0.7; dX.setLineDash([3, 4]);
  dX.beginPath(); dX.moveTo(lwTipX, yB); dX.lineTo(annoLx + 30, annoLy + 5); dX.stroke(); dX.setLineDash([]);

  // --- Right wing annotation ---
  const rwTipX = W / 2 + wingTipOffset;
  const annoRx = Math.min(W - 10, rwTipX + 10);
  const annoRy = annoLy;
  dX.fillStyle = eclipse ? 'rgba(70,70,180,0.7)' : 'rgba(255,220,50,0.88)'; dX.font = 'bold 8px Share Tech Mono'; dX.textAlign = 'right';
  dX.fillText('WING ►', annoRx + 50, annoRy);
  dX.font = '7px Share Tech Mono'; dX.fillStyle = eclipse ? 'rgba(60,60,140,0.6)' : 'rgba(255,200,50,0.6)';
  dX.fillText(`η=${(tech.eff * 100).toFixed(1)}% (EOL ${tech.eolEff})`, annoRx + 50, annoRy + 11);
  dX.fillText(`T-coef: ${tech.tcoefStr}`, annoRx + 50, annoRy + 21);
  dX.fillText(`Total: ${(wingCount * wingArea)} m²`, annoRx + 50, annoRy + 31);
  dX.strokeStyle = eclipse ? 'rgba(70,70,180,0.25)' : 'rgba(255,220,50,0.3)'; dX.lineWidth = 0.7; dX.setLineDash([3, 4]);
  dX.beginPath(); dX.moveTo(rwTipX, yB); dX.lineTo(annoRx + 20, annoRy + 5); dX.stroke(); dX.setLineDash([]); dX.textAlign = 'left';

  // --- Radiator annotation ---
  const radAnnoX = W / 2 + bw / 2 + radWPx + 12;
  const radAnnoY = yB + Math.max(totalRadStackH / 2, 10) + 10;
  dX.fillStyle = 'rgba(255,80,0,0.82)'; dX.font = 'bold 8px Share Tech Mono'; dX.fillText('RADIATOR ►', radAnnoX, radAnnoY);
  dX.font = '7px Share Tech Mono'; dX.fillStyle = 'rgba(255,80,0,0.6)';
  dX.fillText(`${cool.name} VCHP`, radAnnoX, radAnnoY + 11);
  const rT = eclipse ? 26 : 57;
  dX.fillText(`ε=${radEpsilon.toFixed(2)}  T=${rT}°C`, radAnnoX, radAnnoY + 21);
  const avgQPerPanel = radPanels.length > 0 ? radPanels.reduce((a, p) => a + p.qRad, 0) / radPanels.length : 0;
  dX.fillText(`Q≈${avgQPerPanel.toFixed(0)}kW/panel × ${radCount}`, radAnnoX, radAnnoY + 31);
  dX.fillText('Q = ε·σ·A·(T⁴−T_space⁴)', radAnnoX, radAnnoY + 41);
  dX.strokeStyle = 'rgba(255,80,0,0.25)'; dX.lineWidth = 0.7; dX.setLineDash([3, 4]);
  dX.beginPath(); dX.moveTo(W / 2 + bw / 2 + radWPx, yB); dX.lineTo(radAnnoX - 2, radAnnoY - 4); dX.stroke(); dX.setLineDash([]);

  // --- Bus label ---
  dX.textAlign = 'center'; dX.font = '7px Share Tech Mono'; dX.fillStyle = 'rgba(200,180,50,0.65)';
  const busLabelY = yB + Math.max(totalRadStackH / 2 + 10, totalWingStackH / 2 + 10) + 30;
  dX.fillText(`SPACECRAFT BUS · 5120×H100 · MLI blanket · T_GPU=${eclipse ? 72 : 84}°C`, W / 2, busLabelY);
  dX.textAlign = 'left';

  // --- Solar irradiance arrows ---
  if (!eclipse) {
    const arY = yB - Math.max(totalWingStackH / 2, 20) - 25;
    dX.strokeStyle = 'rgba(255,220,50,0.38)'; dX.lineWidth = 1.2; dX.setLineDash([4, 4]);
    dX.beginPath(); dX.moveTo(lwTipX, arY); dX.lineTo(W / 2 - bw / 2, arY); dX.stroke();
    dX.beginPath(); dX.moveTo(W / 2 + bw / 2, arY); dX.lineTo(rwTipX, arY); dX.stroke();
    dX.setLineDash([]);
    for (let d of [-1, 1]) {
      const ax = W / 2 + d * (bw / 2);
      dX.beginPath(); dX.moveTo(ax, arY); dX.lineTo(ax - d * 7, arY - 3.5); dX.lineTo(ax - d * 7, arY + 3.5); dX.closePath();
      dX.fillStyle = 'rgba(255,220,50,0.45)'; dX.fill();
    }
    dX.fillStyle = 'rgba(255,220,50,0.5)'; dX.font = '7px Share Tech Mono'; dX.textAlign = 'center';
    dX.fillText('1367 W/m² solar irradiance', W / 2, arY - 5); dX.textAlign = 'left';
  }

  // --- Radiator IR emission lines ---
  const emBaseX = W / 2 + bw / 2 + radWPx;
  const emCount = Math.min(5, radsPerSide * 2 + 1);
  for (let i = 0; i < emCount; i++) {
    const frac = (i + 0.5) / emCount;
    const ery = yB - totalRadStackH / 2 + totalRadStackH * frac;
    const alpha = eclipse ? 0.05 : 0.16 + 0.05 * Math.sin(simTime * 0.05 + i);
    dX.strokeStyle = `rgba(255,80,0,${alpha})`; dX.lineWidth = 0.9;
    dX.beginPath(); dX.moveTo(emBaseX, ery); dX.lineTo(emBaseX + sc * 16, ery); dX.stroke();
    dX.beginPath(); dX.moveTo(emBaseX + sc * 16, ery); dX.lineTo(emBaseX + sc * 13, ery - 3); dX.lineTo(emBaseX + sc * 13, ery + 3); dX.closePath();
    dX.fillStyle = `rgba(255,80,0,${alpha})`; dX.fill();
  }
}
