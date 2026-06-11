(function () {
  const canvas = document.getElementById("graph");
  const ctx = canvas.getContext("2d");
  const log = document.getElementById("log");
  // name -> {angle, activity (0..1 decaying), count}
  const nodes = new Map();

  function resize() {
    canvas.width = canvas.clientWidth * devicePixelRatio;
    canvas.height = canvas.clientHeight * devicePixelRatio;
  }
  window.addEventListener("resize", resize);
  resize();

  window.JARVIS.on("agent_event", (m) => {
    if (!nodes.has(m.name)) {
      nodes.set(m.name, { angle: Math.random() * Math.PI * 2, activity: 1, count: 0 });
    }
    const n = nodes.get(m.name);
    n.activity = 1;
    n.count += 1;
    const li = document.createElement("li");
    li.innerHTML = `<b>${m.name}</b> ${m.detail || ""}`;
    log.prepend(li);
    while (log.children.length > 60) log.removeChild(log.lastChild);
  });

  window.JARVIS.on("state", (m) => {
    if (m.state === "listening") { nodes.clear(); log.innerHTML = ""; }
  });

  function draw() {
    const w = canvas.width, h = canvas.height;
    const cx = w / 2, cy = h / 2;
    const R = Math.min(w, h) * 0.34;
    ctx.clearRect(0, 0, w, h);
    const busy = window.JARVIS.state === "working";

    // center core
    ctx.fillStyle = busy ? "#ffb347" : "#2ee6ff";
    ctx.shadowBlur = 16;
    ctx.shadowColor = ctx.fillStyle;
    ctx.beginPath();
    ctx.arc(cx, cy, 9 * devicePixelRatio, 0, Math.PI * 2);
    ctx.fill();
    ctx.font = `${10 * devicePixelRatio}px Menlo`;
    ctx.fillText("JARVIS", cx + 14 * devicePixelRatio, cy + 4);

    for (const [name, n] of nodes) {
      n.activity = Math.max(0.15, n.activity * 0.985);
      const x = cx + Math.cos(n.angle) * R;
      const y = cy + Math.sin(n.angle) * R;
      // pulsing edge
      ctx.strokeStyle = `rgba(46,230,255,${n.activity * 0.8})`;
      ctx.lineWidth = (0.5 + n.activity * 2) * devicePixelRatio;
      ctx.shadowBlur = 10 * n.activity;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(x, y);
      ctx.stroke();
      // node
      ctx.fillStyle = `rgba(255,179,71,${0.4 + n.activity * 0.6})`;
      ctx.beginPath();
      ctx.arc(x, y, (4 + n.activity * 5) * devicePixelRatio, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#8fc7d4";
      ctx.fillText(`${name} ×${n.count}`, x + 10 * devicePixelRatio, y + 3);
    }
    requestAnimationFrame(draw);
  }
  draw();
})();
