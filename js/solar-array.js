/* ================================================================
 *  solar-array.js — Solar array canvas + wing table
 * ================================================================ */

function drawSolarArray(eclipse) {
  const W = sC.width, H = sC.height; sX.clearRect(0, 0, W, H);
  sX.fillStyle = '#040c1a'; sX.fillRect(0, 0, W, H);
  const n = wings.length;
  if (n === 0) return;

  let cols = Math.ceil(Math.sqrt(n));
  let rows = Math.ceil(n / cols);
  const margin = 5, gap = 3;
  const cellW = (W - 2 * margin - (cols - 1) * gap) / cols;
  const cellH = (H - 2 * margin - (rows - 1) * gap) / rows;
  const tech = CELL_TECHS[currentCellTech];
  const maxPwr = wingArea * 1367 * tech.eff / 1000 * 1.1;

  for (let idx = 0; idx < n; idx++) {
    const wing = wings[idx];
    const col = idx % cols, row = Math.floor(idx / cols);
    const wx = margin + col * (cellW + gap), wy = margin + row * (cellH + gap);
    const norm = eclipse ? 0 : Math.min(1, wing.output / maxPwr);

    const wg = sX.createLinearGradient(wx, wy, wx + cellW, wy + cellH);
    eclipse
      ? (wg.addColorStop(0, '#0c121c'), wg.addColorStop(1, '#070a12'))
      : (wg.addColorStop(0, `rgb(${Math.floor(18 + norm * 52)},${Math.floor(40 + norm * 100)},${Math.floor(55 + norm * 28)})`),
         wg.addColorStop(1, `rgb(${Math.floor(10 + norm * 38)},${Math.floor(26 + norm * 75)},${Math.floor(42 + norm * 18)})`));
    sX.fillStyle = wg; sX.fillRect(wx, wy, cellW, cellH);

    const cC = Math.max(2, Math.min(6, Math.floor(cellW / 12))), cR = Math.max(2, Math.min(4, Math.floor(cellH / 12)));
    const cw = (cellW - 4) / cC, ch = (cellH - 4) / cR;
    for (let cc = 0; cc < cC; cc++) for (let cr = 0; cr < cR; cr++) {
      const cx3 = wx + 2 + cc * cw, cy3 = wy + 2 + cr * ch;
      const jitter = eclipse ? 0 : Math.random() * 0.12;
      const r2 = eclipse ? 10 : Math.floor(32 + norm * 62 + jitter * 18);
      const g2 = eclipse ? 13 : Math.floor(70 + norm * 85 + jitter * 25);
      const b2 = eclipse ? 38 : Math.floor(18 + norm * 14);
      sX.fillStyle = `rgb(${r2},${g2},${b2})`; sX.fillRect(cx3 + 0.5, cy3 + 0.5, cw - 1, ch - 1);
      sX.strokeStyle = 'rgba(0,0,0,0.55)'; sX.lineWidth = 0.5; sX.strokeRect(cx3 + 0.5, cy3 + 0.5, cw - 1, ch - 1);
      if (!eclipse && cr === 0) { sX.fillStyle = `rgba(255,255,180,${0.04 + norm * 0.09})`; sX.fillRect(cx3 + 1, cy3 + 1, cw - 2, 1.5); }
    }

    sX.strokeStyle = eclipse ? 'rgba(28,56,95,0.45)' : 'rgba(255,200,50,0.38)'; sX.lineWidth = 1;
    if (!eclipse) { sX.shadowColor = 'rgba(255,200,50,0.25)'; sX.shadowBlur = 5; }
    sX.strokeRect(wx, wy, cellW, cellH); sX.shadowBlur = 0;

    sX.fillStyle = eclipse ? 'rgba(70,90,140,0.65)' : 'rgba(255,220,50,0.82)';
    sX.font = `bold ${Math.max(7, Math.min(cellH * 0.13, 12))}px Share Tech Mono`; sX.textAlign = 'left';
    sX.fillText(wing.name, wx + 3, wy + cellH - 11);
    sX.font = `${Math.max(6, Math.min(cellH * 0.11, 10))}px Share Tech Mono`;
    sX.fillStyle = eclipse ? 'rgba(50,65,105,0.65)' : 'rgba(180,255,90,0.8)';
    sX.fillText(eclipse ? '0kW' : `${wing.output.toFixed(0)}kW`, wx + 3, wy + cellH - 1);

    const tN = Math.min(1, (wing.temp + 70) / 160);
    sX.beginPath(); sX.arc(wx + cellW - 7, wy + 7, 3.5, 0, Math.PI * 2);
    sX.fillStyle = eclipse ? `rgb(25,${Math.floor(10 + tN * 20)},10)` : `rgb(${Math.floor(60 + tN * 195)},${Math.floor(Math.max(0, 175 - tN * 175))},15)`; sX.fill();
  }
  sX.textAlign = 'left';

  // Power summary bar
  const total = eclipse ? 0 : wings.reduce((a, w) => a + w.output, 0);
  const peakTotal = wingCount * wingArea * 1367 * CELL_TECHS[currentCellTech].eff / 1000;
  const bw = W - 10, bh = 3;
  sX.fillStyle = 'rgba(13,32,64,0.7)'; sX.fillRect(5, H - 8, bw, bh);
  if (!eclipse && total > 0) {
    const fill = sX.createLinearGradient(5, 0, 5 + bw, 0);
    fill.addColorStop(0, '#39ff14'); fill.addColorStop(0.5, '#ffe066'); fill.addColorStop(1, '#ff4400');
    sX.fillStyle = fill; sX.fillRect(5, H - 8, bw * Math.min(1, total / peakTotal), bh);
  }
}

// --- Wing status table ---
function updateWingTable(eclipse) {
  const tb = document.getElementById('wingTable');
  while (tb.rows.length > 1) tb.deleteRow(1);
  const tech = CELL_TECHS[currentCellTech];
  wings.forEach(w => {
    w.output = eclipse ? 0 : (w.area * 1367 * w.efficiency / 1000) * (1 - (w.temp - 25) * tech.tcoef);
    w.temp = eclipse ? Math.max(-65, w.temp - 1.4) : Math.min(84, w.temp + 0.35);
    const tr = tb.insertRow();
    const tc = w.temp > 80 ? 'ht' : w.temp > 70 ? 'wn' : 'ok';
    tr.innerHTML = `<td>${w.name}</td><td class="${eclipse ? '' : 'ok'}">${w.output.toFixed(0)}</td>` +
      `<td class="${tc}">${w.temp.toFixed(0)}</td><td class="${eclipse ? 'wn' : 'ok'}">${eclipse ? 'STB' : 'ACT'}</td>`;
  });
}
