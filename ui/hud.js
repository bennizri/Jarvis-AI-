(function () {
  const canvas = document.getElementById("core");
  const ctx = canvas.getContext("2d");

  const COLORS = { idle: "#2ee6ff", listening: "#2ee6ff", transcribing: "#ffb347",
                   working: "#ffb347", speaking: "#4dff9d" };
  const SPIN = { idle: 0.2, listening: 0.5, transcribing: 1.2, working: 2.5, speaking: 0.8 };

  let t = 0;
  function resize() {
    canvas.width = canvas.clientWidth * devicePixelRatio;
    canvas.height = canvas.clientHeight * devicePixelRatio;
  }
  window.addEventListener("resize", resize);
  resize();

  function ring(cx, cy, r, width, color, alpha, dashes, rot) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(rot);
    ctx.strokeStyle = color;
    ctx.globalAlpha = alpha;
    ctx.lineWidth = width;
    ctx.shadowBlur = 18;
    ctx.shadowColor = color;
    if (dashes) ctx.setLineDash(dashes);
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  function draw() {
    const st = window.JARVIS.state;
    const color = COLORS[st] || COLORS.idle;
    t += 0.016 * (SPIN[st] || 0.2);
    const w = canvas.width, h = canvas.height;
    const cx = w / 2, cy = h / 2;
    const base = Math.min(w, h) / 2 * 0.62;
    ctx.clearRect(0, 0, w, h);

    // breathing / mic-reactive core
    let pulse = 1 + Math.sin(t * 4) * 0.04;
    if (st === "listening") pulse = 1 + window.JARVIS.micLevel * 2.2;

    const grad = ctx.createRadialGradient(cx, cy, 4, cx, cy, base * 0.42 * pulse);
    grad.addColorStop(0, "#ffffff");
    grad.addColorStop(0.25, color);
    grad.addColorStop(1, "transparent");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, base * 0.42 * pulse, 0, Math.PI * 2);
    ctx.fill();

    // rotating ring stack
    ring(cx, cy, base * 0.55, 3, color, 0.9, [40, 18], t);
    ring(cx, cy, base * 0.72, 1.5, color, 0.55, [8, 10], -t * 1.6);
    ring(cx, cy, base * 0.88, 5, color, 0.35, [90, 50], t * 0.7);
    ring(cx, cy, base * 1.0, 1, color, 0.25, null, 0);

    // tick marks
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-t * 0.5);
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.6;
    for (let i = 0; i < 24; i++) {
      ctx.rotate(Math.PI / 12);
      ctx.beginPath();
      ctx.moveTo(base * 0.93, 0);
      ctx.lineTo(base * (i % 6 === 0 ? 0.99 : 0.96), 0);
      ctx.stroke();
    }
    ctx.restore();

    requestAnimationFrame(draw);
  }
  draw();
})();
