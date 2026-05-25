// Shooting stars and dragon sky effects.
(function () {
  "use strict";

  const canvas = document.getElementById("sky-effects");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener("resize", resize);

  // --- Shooting stars ---
  const shootingStars = [];

  function spawnShootingStar() {
    const startX = Math.random() * canvas.width * 0.8;
    const startY = Math.random() * canvas.height * 0.4;
    shootingStars.push({
      x: startX,
      y: startY,
      vx: 3 + Math.random() * 4,
      vy: 1.5 + Math.random() * 2,
      len: 30 + Math.random() * 60,
      life: 1.0,
      decay: 0.008 + Math.random() * 0.012,
    });
    // Next shooting star in 3-10 seconds
    setTimeout(spawnShootingStar, 3000 + Math.random() * 7000);
  }
  // First one after 1-4s
  setTimeout(spawnShootingStar, 1000 + Math.random() * 3000);

  function drawShootingStar(s) {
    const tailX = s.x - (s.vx / Math.sqrt(s.vx * s.vx + s.vy * s.vy)) * s.len;
    const tailY = s.y - (s.vy / Math.sqrt(s.vx * s.vx + s.vy * s.vy)) * s.len;
    const grad = ctx.createLinearGradient(tailX, tailY, s.x, s.y);
    grad.addColorStop(0, "rgba(255,255,255,0)");
    grad.addColorStop(1, `rgba(255,255,240,${s.life * 0.9})`);
    ctx.strokeStyle = grad;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(tailX, tailY);
    ctx.lineTo(s.x, s.y);
    ctx.stroke();
    // Bright head
    ctx.fillStyle = `rgba(255,255,240,${s.life})`;
    ctx.beginPath();
    ctx.arc(s.x, s.y, 1.5, 0, Math.PI * 2);
    ctx.fill();
  }

  // --- Dragon ---
  let dragon = null;

  // Dragon SVG path points (wing-flapping silhouette)
  function drawDragon(d) {
    ctx.save();
    ctx.translate(d.x, d.y);
    ctx.scale(d.dir, 1);
    ctx.scale(d.size, d.size);
    const wingPhase = Math.sin(d.wingT) * 0.4;

    ctx.fillStyle = `rgba(100,15,15,${d.opacity})`;
    ctx.strokeStyle = `rgba(60,5,5,${d.opacity})`;
    ctx.lineWidth = 0.5;

    // Body
    ctx.beginPath();
    ctx.ellipse(0, 0, 18, 5, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    // Neck + head
    ctx.beginPath();
    ctx.moveTo(15, -2);
    ctx.quadraticCurveTo(22, -6, 26, -4);
    ctx.quadraticCurveTo(28, -3, 27, -1);
    ctx.quadraticCurveTo(24, 0, 22, -1);
    ctx.quadraticCurveTo(18, 0, 15, 2);
    ctx.fill();
    ctx.stroke();
    // Eye
    ctx.fillStyle = `rgba(255,180,0,${d.opacity})`;
    ctx.beginPath();
    ctx.arc(25, -3, 0.8, 0, Math.PI * 2);
    ctx.fill();
    // Horns
    ctx.strokeStyle = `rgba(80,20,20,${d.opacity})`;
    ctx.beginPath();
    ctx.moveTo(25, -5);
    ctx.lineTo(27, -8);
    ctx.moveTo(23, -5);
    ctx.lineTo(24, -8);
    ctx.stroke();

    // Tail
    ctx.fillStyle = `rgba(100,15,15,${d.opacity})`;
    ctx.strokeStyle = `rgba(60,5,5,${d.opacity})`;
    ctx.beginPath();
    ctx.moveTo(-16, 0);
    ctx.quadraticCurveTo(-24, -2 + Math.sin(d.wingT * 0.7) * 2, -30, 1);
    ctx.quadraticCurveTo(-32, 3, -30, 2);
    ctx.quadraticCurveTo(-24, 2, -16, 2);
    ctx.fill();
    ctx.stroke();
    // Tail spike
    ctx.beginPath();
    ctx.moveTo(-30, 1);
    ctx.lineTo(-34, -1);
    ctx.lineTo(-32, 3);
    ctx.fill();

    // Wings (flapping)
    ctx.fillStyle = `rgba(90,10,10,${d.opacity * 0.8})`;
    // Upper wing
    ctx.beginPath();
    ctx.moveTo(-5, -4);
    ctx.quadraticCurveTo(-2, -14 + wingPhase * 15, 10, -12 + wingPhase * 18);
    ctx.quadraticCurveTo(14, -10 + wingPhase * 14, 12, -5);
    ctx.quadraticCurveTo(5, -4, -5, -4);
    ctx.fill();
    ctx.stroke();
    // Wing membrane lines
    ctx.strokeStyle = `rgba(60,5,5,${d.opacity * 0.5})`;
    ctx.beginPath();
    ctx.moveTo(0, -4);
    ctx.quadraticCurveTo(2, -10 + wingPhase * 12, 6, -11 + wingPhase * 15);
    ctx.moveTo(5, -4);
    ctx.quadraticCurveTo(7, -9 + wingPhase * 11, 10, -10 + wingPhase * 14);
    ctx.stroke();

    // Legs
    ctx.strokeStyle = `rgba(80,10,10,${d.opacity})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(-4, 4);
    ctx.lineTo(-5, 9);
    ctx.lineTo(-3, 9);
    ctx.moveTo(4, 4);
    ctx.lineTo(3, 9);
    ctx.lineTo(5, 9);
    ctx.stroke();

    ctx.restore();
  }

  function spawnDragon() {
    const fromLeft = Math.random() > 0.5;
    dragon = {
      x: fromLeft ? -80 : canvas.width + 80,
      y: 40 + Math.random() * canvas.height * 0.25,
      vx: (fromLeft ? 1 : -1) * (0.6 + Math.random() * 0.8),
      dir: fromLeft ? 1 : -1,
      wingT: 0,
      size: 0.9 + Math.random() * 0.6,
      opacity: 0,
    };
    // Next dragon in 45-120 seconds
    setTimeout(spawnDragon, 45000 + Math.random() * 75000);
  }
  // First dragon after 15-40s
  setTimeout(spawnDragon, 15000 + Math.random() * 25000);

  // --- Animation loop ---
  function frame() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Shooting stars
    for (let i = shootingStars.length - 1; i >= 0; i--) {
      const s = shootingStars[i];
      s.x += s.vx;
      s.y += s.vy;
      s.life -= s.decay;
      if (s.life <= 0 || s.x > canvas.width || s.y > canvas.height) {
        shootingStars.splice(i, 1);
      } else {
        drawShootingStar(s);
      }
    }

    // Dragon
    if (dragon) {
      dragon.x += dragon.vx;
      dragon.wingT += 0.08;
      // Gentle sine wave path
      dragon.y += Math.sin(dragon.wingT * 0.3) * 0.3;
      // Fade in/out
      const edgeDist = Math.min(
        Math.abs(dragon.x),
        Math.abs(canvas.width - dragon.x)
      );
      dragon.opacity = Math.min(0.55, edgeDist / 150);
      if (
        (dragon.vx > 0 && dragon.x > canvas.width + 100) ||
        (dragon.vx < 0 && dragon.x < -100)
      ) {
        dragon = null;
      } else {
        drawDragon(dragon);
      }
    }

    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
