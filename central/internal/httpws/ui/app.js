(function () {
  var statusEl = document.getElementById("status");
  var logEl = document.getElementById("log");
  var teleEl = document.getElementById("telemetry");
  var chatInput = document.getElementById("chatInput");
  var sendChatBtn = document.getElementById("sendChatBtn");

  var activeCrew = null;
  var msgSeq = 0;

  var proto = location.protocol === "https:" ? "wss:" : "ws:";
  var ws = new WebSocket(proto + "//" + location.host + "/ws");

  function appendLog(line) {
    logEl.textContent = line + "\n" + logEl.textContent.slice(0, 4000);
  }

  function sendEnvelope(type, payload) {
    msgSeq += 1;
    var env = {
      v: 1,
      type: type,
      ts_us: Date.now() * 1000,
      crew_id: activeCrew,
      client_msg_id: "ui-" + msgSeq,
      payload: payload
    };
    ws.send(JSON.stringify(env));
  }

  ws.onopen = function () {
    statusEl.textContent = "connected";
  };

  ws.onclose = function (e) {
    statusEl.textContent = "closed (" + e.code + ")";
  };

  ws.onmessage = function (e) {
    try {
      var msg = JSON.parse(e.data);
      if (msg.type === "CREW_STATE" && msg.payload) {
        activeCrew = msg.payload.crew_id || null;
      }
      if (msg.type === "TELEMETRY_FRAME") {
        teleEl.textContent = JSON.stringify(msg, null, 2);
        return;
      }
    } catch (_) {}
    appendLog(e.data);
  };

  document.querySelectorAll("button[data-crew]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      sendEnvelope("SET_CREW", { crew_id: btn.getAttribute("data-crew") });
    });
  });

  if (sendChatBtn) {
    sendChatBtn.addEventListener("click", function () {
      var text = (chatInput && chatInput.value ? chatInput.value : "").trim();
      if (!text) return;
      sendEnvelope("CHAT_MSG", { text: text });
    });
  }
})();
