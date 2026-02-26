/* ================================================================
 *  radiator.js — Radiator canvas + panel status table
 * ================================================================ */

function drawRadiator(eclipse) {
  const W = rC.width, H = rC.height; rX.clearRect(0, 0, W, H);
  rX.fillStyle = '#040c1a'; rX.fillRect(0, 0, W, H);
  const n = radPanels.length;
  if (n === 0) return;

  const margin = 5, gap = 4;
  const panelW = (W - 2 * margin - (n - 1) * gap) / n;
  const panelH = H - 2 * margin - 14;

  radPanels.forEach((panel, i) => {
    const px = margin + i * (panelW + gap), py = margin;

    // Panel gradient
    const pg = rX.createLinearGradient(px, py, px, py + panelH);
    eclipse
      ? (pg.addColorStop(0, '#160500'), pg.addColorStop(0.5, '#0c0300'), pg.addColorStop(1, '#060100'))
      : (pg.addColorStop(0, '#dd3800'), pg.addColorStop(0.3, '#ff5500'), pg.addColorStop(0.7, '#bb2800'), pg.addColorStop(1, '#651000'));
    rX.fillStyle = pg; rX.fillRect(px, py, panelW, panelH);

    // Heat pipes
    const numPipes = 10;
    for (let p = 0; p < numPipes; p++) {
      const py2 = py + p * (panelH / numPipes), heatI = 1 - p / numPipes;
      rX.strokeStyle = eclipse ? 'rgba(70,20,0,0.4)' : `rgba(255,${Math.floor(55 + heatI * 115)},0,${0.3 + heatI * 0.28})`;
      rX.lineWidth = 1.1; rX.beginPath(); rX.moveTo(px + 2, py2); rX.lineTo(px + panelW - 2, py2); rX.stroke();
      if (p % 2 === 0) {
        const ax = px + panelW * 0.5;
        rX.fillStyle = eclipse ? 'rgba(45,12,0,0.35)' : 'rgba(255,110,0,0.3)';
        rX.beginPath(); rX.moveTo(ax, py2 + 2.5); rX.lineTo(ax - 3.5, py2 + 6); rX.lineTo(ax + 3.5, py2 + 6); rX.closePath(); rX.fill();
      }
    }

    // IR emission lines (left side)
    if (!eclipse) {
      for (let r = 0; r < 5; r++) {
        const ry2 = py + r * (panelH / 4);
        const alpha = 0.1 + 0.07 * Math.sin(simTime * 0.05 + r + i * 0.7);
        for (let d = 1; d <= 3; d++) {
          rX.beginPath(); rX.moveTo(px, ry2); rX.lineTo(px - d * 4, ry2);
          rX.strokeStyle = `rgba(255,80,0,${alpha / d})`; rX.lineWidth = 0.9;
          rX.setLineDash([1, 2]); rX.stroke(); rX.setLineDash([]);
        }
      }
    }

    // Panel border
    rX.strokeStyle = eclipse ? '#260d00' : '#ff4400'; rX.lineWidth = 1.1; rX.strokeRect(px, py, panelW, panelH);
    if (!eclipse) { rX.shadowColor = 'rgba(255,80,0,0.3)'; rX.shadowBlur = 7; rX.strokeStyle = 'rgba(255,80,0,0.18)'; rX.strokeRect(px, py, panelW, panelH); rX.shadowBlur = 0; }

    // Labels
    rX.fillStyle = eclipse ? 'rgba(130,55,8,0.75)' : 'rgba(255,190,75,0.88)';
    rX.font = `bold ${Math.max(7, Math.min(panelW * 0.17, 12))}px Share Tech Mono`; rX.textAlign = 'center';
    rX.fillText(`P${i + 1}`, px + panelW / 2, py + 12);
    rX.font = `${Math.max(6, Math.min(panelW * 0.14, 10))}px Share Tech Mono`;
    rX.fillStyle = eclipse ? 'rgba(110,45,5,0.7)' : 'rgba(255,145,45,0.82)';
    rX.fillText(`${panel.surfTemp.toFixed(0)}°C`, px + panelW / 2, py + panelH - 16);
    rX.fillStyle = eclipse ? 'rgba(90,35,3,0.6)' : 'rgba(255,115,28,0.72)';
    rX.fillText(`${panel.qRad.toFixed(0)}kW`, px + panelW / 2, py + panelH - 5);
  });

  rX.textAlign = 'left';
  const cool = COOLANTS[currentCoolant];
  rX.fillStyle = 'rgba(255,80,0,0.38)'; rX.font = '7px Share Tech Mono';
  rX.fillText(`← IR to deep space (2.7K) · ε=${radEpsilon.toFixed(2)}`, margin, H - 3);
  rX.textAlign = 'right'; rX.fillStyle = 'rgba(0,150,200,0.38)';
  rX.fillText(`${cool.name}: ${cool.tIn}°C in → ${cool.tOut}°C out`, W - margin - 5, H - 3);
  rX.textAlign = 'left';
}

// --- Radiator panel status table ---
function updateRadTable(eclipse) {
  const tb = document.getElementById('radPanelTable');
  while (tb.rows.length > 1) tb.deleteRow(1);
  const cool = COOLANTS[currentCoolant];
  radPanels.forEach(p => {
    p.surfTemp = eclipse ? Math.max(14, p.surfTemp - 0.5) : Math.min(63, 54 + Math.random() * 7);
    const T = p.surfTemp + 273.15;
    p.qRad = (p.emissivity * SIGMA * p.area * p.viewFactor * (T ** 4 - 2.7 ** 4)) / 1000 * cool.heatCapFactor;
    const tr = tb.insertRow();
    const tc = p.surfTemp > 60 ? 'ht' : p.surfTemp > 50 ? 'wn' : 'ok';
    tr.innerHTML = `<td>P${p.id}</td><td class="${tc}">${p.surfTemp.toFixed(0)}</td>` +
      `<td class="ok">${p.qRad.toFixed(0)}</td><td class="${eclipse ? 'wn' : 'ok'}">${eclipse ? 'RED' : 'OK'}</td>`;
  });
}
