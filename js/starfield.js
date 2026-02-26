/* ================================================================
 *  starfield.js — Background star layer
 * ================================================================ */

const sfC = document.getElementById('starfield'), sfX = sfC.getContext('2d');
let stars = [];

function initStars() {
  sfC.width = window.innerWidth;
  sfC.height = window.innerHeight;
  stars = Array.from({ length: 400 }, () => ({
    x: Math.random() * sfC.width,
    y: Math.random() * sfC.height,
    r: Math.random() * 1.2,
    a: Math.random(),
    sp: Math.random() * 0.25 + 0.05
  }));
}

function drawStars() {
  sfX.clearRect(0, 0, sfC.width, sfC.height);
  stars.forEach(s => {
    s.a += s.sp * 0.008;
    sfX.beginPath();
    sfX.arc(s.x, s.y, s.r, 0, Math.PI * 2);
    sfX.fillStyle = `rgba(180,220,255,${0.25 + 0.6 * Math.abs(Math.sin(s.a))})`;
    sfX.fill();
  });
}
