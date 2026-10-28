// The public demo plays itself on the server; this only shows what is happening and follows the scenario.
(() => {
  const ui = document.createElement("div");
  ui.innerHTML = `<span style="width:9px;height:9px;border-radius:50%;background:#25D366;box-shadow:0 0 0 4px rgba(37,211,102,.25)"></span><b>Live demo, playing by itself</b><span id="ap-msg"></span>`;
  ui.style.cssText = "position:fixed;bottom:70px;left:50%;transform:translateX(-50%);z-index:9999;display:flex;gap:12px;align-items:center;max-width:calc(100% - 32px);" +
    "background:#102A2E;color:#F6F3EC;padding:10px 18px;border-radius:999px;box-shadow:0 10px 30px rgba(0,0,0,.35);font:500 14px system-ui,sans-serif";
  document.body.appendChild(ui);
  const msg = ui.querySelector("#ap-msg");
  const original = handle;
  handle = e => {
    original(e);
    if (e.kind !== "demo") return;
    msg.textContent = "· " + e.text;
    if (e.scenario && e.scenario !== scenario) {
      const s = document.getElementById("scenario");
      s.value = e.scenario; s.dispatchEvent(new Event("change"));
    }
  };
  document.getElementById("reset").style.display = "none";
})();
