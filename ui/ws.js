window.JARVIS = {
  state: "idle",
  micLevel: 0,
  handlers: { state: [], mic_level: [], transcript: [], agent_event: [], answer: [], error: [], fleet: [], reports: [], agents: [] },
  on(type, fn) { this.handlers[type].push(fn); },
};

(function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  const dot = document.getElementById("conn-dot");
  ws.onopen = () => dot.classList.add("on");
  ws.onclose = () => { dot.classList.remove("on"); setTimeout(connect, 1500); };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "state") window.JARVIS.state = msg.state;
    if (msg.type === "mic_level") window.JARVIS.micLevel = msg.level;
    (window.JARVIS.handlers[msg.type] || []).forEach((fn) => fn(msg));
  };
})();

const LABELS = { idle: "STANDBY", listening: "LISTENING", transcribing: "ANALYZING",
                 working: "EXECUTING", speaking: "RESPONDING" };
window.JARVIS.on("state", (m) => {
  document.getElementById("status-label").textContent = LABELS[m.state] || m.state.toUpperCase();
  document.body.classList.toggle("error", false);
});
window.JARVIS.on("transcript", (m) => {
  const el = document.getElementById("transcript-text");
  el.textContent = m.text;
  el.classList.toggle("rtl", m.lang === "he");
});
window.JARVIS.on("answer", (m) => {
  const isHe = /[֐-׿]/.test(m.spoken || m.text);
  const spoken = document.getElementById("spoken-line");
  const full = document.getElementById("answer-text");
  spoken.textContent = m.spoken ? `🗣 ${m.spoken}` : "";
  full.textContent = m.text;
  spoken.classList.toggle("rtl", isHe);
  full.classList.toggle("rtl", isHe);
});
window.JARVIS.on("error", (m) => {
  document.body.classList.add("error");
  document.getElementById("status-label").textContent = "ERROR";
  const li = document.createElement("li");
  li.innerHTML = `<b>ERROR</b> ${m.message}`;
  document.getElementById("log").prepend(li);
});

const STATUS_ICON = { running: "\u25d0", done: "\u25cf", failed: "\u2716", scheduled: "\u25f7",
                      paused: "\u23f8", needs_attention: "\u25b2" };
window.JARVIS.on("agents", (m) => {
  const list = document.getElementById("agents-list");
  const counts = document.getElementById("agents-counts");
  list.innerHTML = "";
  const attn = m.agents.filter(a => a.status === "needs_attention").length;
  counts.textContent = `\u00b7 ${m.agents.length} total` + (attn ? ` \u00b7 ${attn} need attention` : "");
  if (!m.agents.length) {
    list.innerHTML = '<li class="dim">no agents yet\u2026</li>';
    return;
  }
  for (const a of m.agents) {
    const li = document.createElement("li");
    li.className = `st-${a.status}`;
    li.innerHTML = `<span class="st-icon">${STATUS_ICON[a.status] || "?"}</span>` +
      `<span class="agent-name"></span><span class="agent-kind">${a.kind}</span>` +
      `<span class="report-summary"></span>`;
    li.querySelector(".agent-name").textContent = a.name;
    li.querySelector(".report-summary").textContent = a.last_report || a.purpose || "";
    list.appendChild(li);
  }
});
