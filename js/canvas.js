/* ================================================================
 *  canvas.js — Canvas references, resize helper, angle utilities
 * ================================================================ */

const oC = document.getElementById('orbitCanvas'),    oX = oC.getContext('2d');
const dC = document.getElementById('detailCanvas'),   dX = dC.getContext('2d');
const sC = document.getElementById('solarArrayCanvas'), sX = sC.getContext('2d');
const rC = document.getElementById('radiatorCanvas'),  rX = rC.getContext('2d');
const tC = document.getElementById('trendCanvas'),     tX = tC.getContext('2d');

function resizeAll() {
  [oC, dC].forEach(c => {
    if (c.offsetWidth > 0 && c.offsetHeight > 0) { c.width = c.offsetWidth; c.height = c.offsetHeight; }
  });
  [sC, rC, tC].forEach(c => {
    if (c.offsetWidth > 0 && c.offsetHeight > 0) { c.width = c.offsetWidth; c.height = c.offsetHeight; }
  });
}

function getAngle(t) { return (t / ORBIT_PERIOD) * Math.PI * 2; }

function isEclipse(a) {
  const n = ((a % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
  return n > ECLIPSE_START && n < ECLIPSE_START + ECLIPSE_FRAC * Math.PI * 2;
}
