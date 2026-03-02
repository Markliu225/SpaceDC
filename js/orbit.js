/* ================================================================
 *  orbit.js — Earth orbit view (top-left quad)
 * ================================================================ */

function drawOrbit(eclipse) {
  if (!oC || !oX) return;
  const W = oC.width, H = oC.height, cx = W * 0.46, cy = H * 0.5;
  const earthR = Math.min(W, H) * 0.28, orbitR = earthR * 1.7;
  oX.clearRect(0, 0, W, H);

  // Background glow
  const bg = oX.createRadialGradient(cx, cy, 0, cx, cy, W * 0.7);
  bg.addColorStop(0, 'rgba(0,18,50,0.35)'); bg.addColorStop(1, 'rgba(0,0,0,0)');
  oX.fillStyle = bg; oX.fillRect(0, 0, W, H);

  // Sun
  const sunX = cx - orbitR * 1.85, sunY = cy - orbitR * 0.65;
  const sg = oX.createRadialGradient(sunX, sunY, 0, sunX, sunY, 110);
  sg.addColorStop(0, 'rgba(255,248,200,0.95)'); sg.addColorStop(0.2, 'rgba(255,200,50,0.5)');
  sg.addColorStop(0.6, 'rgba(255,130,0,0.12)'); sg.addColorStop(1, 'rgba(255,80,0,0)');
  oX.beginPath(); oX.arc(sunX, sunY, 110, 0, Math.PI * 2); oX.fillStyle = sg; oX.fill();
  oX.beginPath(); oX.arc(sunX, sunY, 22, 0, Math.PI * 2); oX.fillStyle = '#fff8c0'; oX.fill();
  for (let i = 0; i < 14; i++) {
    const ra = (i / 14) * Math.PI * 2 + simTime * 0.00012;
    const len = 22 + 10 * Math.sin(simTime * 0.002 + i);
    oX.beginPath(); oX.moveTo(sunX + Math.cos(ra) * 28, sunY + Math.sin(ra) * 28);
    oX.lineTo(sunX + Math.cos(ra) * (28 + len), sunY + Math.sin(ra) * (28 + len));
    oX.strokeStyle = `rgba(255,220,80,${0.12 + 0.07 * Math.sin(simTime * 0.003 + i)})`; oX.lineWidth = 1.3; oX.stroke();
  }

  // Sunlight rays toward satellite
  if (!eclipse) {
    const ang = getAngle(simTime);
    const sx2 = cx + Math.cos(ang) * orbitR, sy2 = cy + Math.sin(ang) * orbitR;
    const ddx = sx2 - sunX, ddy = sy2 - sunY, dist = Math.sqrt(ddx * ddx + ddy * ddy);
    for (let j = 0; j < 5; j++) {
      const off = (j - 2) * 14, px = -ddy / dist * off, py2 = ddx / dist * off;
      oX.beginPath(); oX.moveTo(sunX + ddx * 0.23 + px, sunY + ddy * 0.23 + py2);
      oX.lineTo(sunX + ddx * 0.73 + px, sunY + ddy * 0.73 + py2);
      oX.strokeStyle = `rgba(255,220,80,${0.09 - Math.abs(j - 2) * 0.015})`; oX.lineWidth = 0.9;
      oX.setLineDash([3, 5]); oX.stroke(); oX.setLineDash([]);
    }
  }

  // Shadow cone
  const shAng = Math.atan2(cy - sunY, cx - sunX);
  oX.save(); oX.beginPath(); oX.moveTo(cx, cy);
  oX.arc(cx, cy, orbitR * 1.5, shAng + Math.PI + (ECLIPSE_FRAC * Math.PI), shAng + Math.PI - (ECLIPSE_FRAC * Math.PI), true);
  oX.closePath();
  const shG = oX.createRadialGradient(cx, cy, earthR * 0.85, cx, cy, orbitR * 1.3);
  shG.addColorStop(0, 'rgba(0,4,15,0.78)'); shG.addColorStop(0.65, 'rgba(0,4,15,0.4)'); shG.addColorStop(1, 'rgba(0,4,15,0)');
  oX.fillStyle = shG; oX.fill(); oX.restore();

  // Orbit ring
  oX.beginPath(); oX.arc(cx, cy, orbitR, 0, Math.PI * 2);
  oX.strokeStyle = 'rgba(0,140,255,0.12)'; oX.lineWidth = 1.1; oX.setLineDash([5, 7]); oX.stroke(); oX.setLineDash([]);

  // Earth
  const eG = oX.createRadialGradient(cx - earthR * 0.22, cy - earthR * 0.18, earthR * 0.05, cx, cy, earthR);
  eG.addColorStop(0, '#1e9460'); eG.addColorStop(0.3, '#1565a0'); eG.addColorStop(0.7, '#0d3d7a'); eG.addColorStop(1, '#030c20');
  oX.beginPath(); oX.arc(cx, cy, earthR, 0, Math.PI * 2); oX.fillStyle = eG; oX.fill();
  const atG = oX.createRadialGradient(cx, cy, earthR * 0.88, cx, cy, earthR * 1.12);
  atG.addColorStop(0, 'rgba(60,140,255,0.3)'); atG.addColorStop(1, 'rgba(20,80,200,0)');
  oX.beginPath(); oX.arc(cx, cy, earthR * 1.12, 0, Math.PI * 2); oX.fillStyle = atG; oX.fill();
  oX.fillStyle = 'rgba(100,200,100,0.5)'; oX.font = 'bold 11px Orbitron'; oX.textAlign = 'center';
  oX.fillText('EARTH', cx, cy + 4); oX.textAlign = 'left';

  // Orbital trail
  for (let i = 1; i <= 3; i++) {
    const ta = getAngle(simTime - i * ORBIT_PERIOD * 0.07);
    oX.beginPath(); oX.arc(cx, cy, orbitR, ta, ta + 0.22, false);
    oX.strokeStyle = `rgba(0,100,200,${0.07 - i * 0.02})`; oX.lineWidth = 2.5; oX.stroke();
  }

  // Satellite position
  const angle = getAngle(simTime);
  const satX = cx + Math.cos(angle) * orbitR, satY = cy + Math.sin(angle) * orbitR;
  // Satellite icon scale: shrink as wing/rad count grows to avoid overwhelming the orbit view
  const satScale = Math.max(0.5, 1.2 / (1 + Math.max(wingCount, radCount) * 0.04));
  if (!eclipse) {
    const haloR = 20 * satScale + 8;
    const halo = oX.createRadialGradient(satX, satY, 0, satX, satY, haloR);
    halo.addColorStop(0, 'rgba(0,212,255,0.22)'); halo.addColorStop(1, 'rgba(0,212,255,0)');
    oX.beginPath(); oX.arc(satX, satY, haloR, 0, Math.PI * 2); oX.fillStyle = halo; oX.fill();
  }
  drawSatIcon(oX, satX, satY, angle, eclipse, satScale);

  // Downlink beam
  if (!eclipse && Math.random() > 0.5) {
    const gx = cx + Math.cos(angle + 0.32) * earthR * 0.8, gy = cy + Math.sin(angle + 0.32) * earthR * 0.8;
    oX.beginPath(); oX.moveTo(satX, satY); oX.lineTo(gx, gy);
    oX.strokeStyle = 'rgba(0,255,160,0.18)'; oX.lineWidth = 1; oX.setLineDash([2, 4]); oX.stroke(); oX.setLineDash([]);
  }

  // Labels
  oX.fillStyle = eclipse ? '#6688ff' : '#00d4ff'; oX.font = 'bold 8px Share Tech Mono';
  oX.fillText(eclipse ? '● ECLIPSE' : '☀ SUNLIT', satX + 18, satY - 10);
  oX.fillStyle = 'rgba(0,140,220,0.4)'; oX.font = '8px Share Tech Mono';
  oX.fillText('SSO 550km  T=95.7min', cx + orbitR + 4, cy - 4);
  oX.fillStyle = 'rgba(0,160,255,0.4)'; oX.font = '8px Orbitron'; oX.textAlign = 'center';
  oX.fillText(`ORBIT #${orbitCount}`, cx, cy + earthR + 18); oX.textAlign = 'left';
}
