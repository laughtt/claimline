// Auto-play for the public demo: sends the scenario's suggested lines on both phones, waits for each
// turn, approves every review form and points at the PDF. Uses the page's own globals (post, SCRIPTS...).
(() => {
  const ORDER = {
    solo: [["A", 0], ["A", 1], ["A", 2], ["A", 3], ["A", 4], ["A", 5], ["A", 6], ["A", 7],
           ["B", 0], ["B", 1], ["B", 2], ["B", 3], ["B", 4], ["B", 5], ["B", 6]],
    nino: [["A", 0], ["A", 1], ["A", 2], ["A", 3], ["A", 4], ["B", 0], ["B", 1], ["B", 2], ["A", 5], ["B", 3],
           ["A", 6], ["A", 7], ["A", 9], ["B", 4], ["B", 5], ["B", 7]],
  };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let running = false, waiting = null;

  const ui = document.createElement("div");
  ui.innerHTML = `<button id="ap-btn">▶ Play the demo automatically</button><span id="ap-msg"></span>`;
  ui.style.cssText = "position:fixed;bottom:70px;left:50%;transform:translateX(-50%);z-index:9999;display:flex;gap:12px;align-items:center;" +
    "background:#102A2E;color:#F6F3EC;padding:8px 10px 8px 8px;border-radius:999px;box-shadow:0 10px 30px rgba(0,0,0,.35);font:600 14px system-ui,sans-serif";
  document.body.appendChild(ui);
  const btn = ui.querySelector("#ap-btn"), msg = ui.querySelector("#ap-msg");
  btn.style.cssText = "background:#F0A35E;color:#102A2E;border:0;border-radius:999px;padding:9px 16px;font:700 14px system-ui,sans-serif;cursor:pointer";
  const say = t => { msg.textContent = t; };

  // Approve each review form as it arrives, and know when each turn ends
  const original = handle;
  handle = e => {
    original(e);
    if (e.kind === "turn_done" && waiting && waiting.who === e.who) waiting.done();
    if (running && e.kind === "wa_out" && e.body?.interactive?.action?.parameters?.flow_token) {
      const token = e.body.interactive.action.parameters.flow_token;
      setTimeout(() => { say(`Person ${e.who} approves the report…`); post("/api/message", {who: e.who, form: {flow_token: token, decision: "approve", comment: ""}}); }, 2500);
    }
    if (running && e.kind === "wa_out" && e.body?.type === "document") say("📄 The PDF report arrived in the chat. Tap it to open.");
  };

  async function send(who, body) {
    const turn = new Promise(r => { waiting = {who, done: r}; });
    await post("/api/message", {who, ...body});
    await Promise.race([turn, sleep(15000)]);
    waiting = null;
    await sleep(1600);
  }

  async function run() {
    if (running) return;
    running = true; btn.disabled = true; btn.textContent = "Playing…";
    const sc = SCRIPTS[scenario] ? scenario : "solo";
    say(sc === "solo" ? "Two floods in Piura, one person each" : "A crash in the rain, two drivers");
    await send("A", {text: "RESET"});
    await send("B", {text: "RESET"});
    for (const [who, i] of ORDER[sc]) {
      const [raw, , extra] = SCRIPTS[sc][who][i];
      if (extra?.pin) await send(who, {location: PINS[sc][who]});
      else if (extra?.button) await send(who, {button: {id: extra.button, title: raw.replace("👆 ", "")}});
      else await send(who, {text: raw.replace("{code}", caseId)});
    }
    await sleep(6000);
    say("Done. Open the PDF in the chat, or see the case on the Claims board.");
    running = false; btn.disabled = false; btn.textContent = "▶ Play again";
  }

  btn.onclick = run;
  if (new URLSearchParams(location.search).has("autoplay")) setTimeout(run, 1500);
})();
