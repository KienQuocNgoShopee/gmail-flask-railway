(function () {
  const SOC = window.SOC; // chỉ có ở mail.html
  if (!SOC) return;

  const currentUserEmail = document.body?.dataset?.email || "";

  const sendBtn = document.getElementById("sendBtn");
  const resultElement = document.getElementById("result");
  const statusIndicator = document.getElementById("status-indicator");
  const progressBar = document.getElementById("progress-bar");
      // ===== LOG FUNCTIONS (SOC-specific) =====
  const logBox = document.getElementById("logBox");

  function setLog(text) {
    if (!logBox) return;
    logBox.textContent = text || "";
    logBox.scrollTop = logBox.scrollHeight; // auto scroll xuống cuối
  }

  async function fetchLog(tail = 400) {
    const res = await fetch(`/log-data?soc=${encodeURIComponent(SOC)}&tail=${tail}`);
    const data = await res.json().catch(() => ({}));
    setLog(data.text || "");
  }

  function refreshLog() {
    fetchLog().catch(() => {});
  }

  function clearLogUI() {
    setLog("");
  }

  // expose ra global để nút trong HTML gọi được
  window.refreshLog = refreshLog;
  window.clearLogUI = clearLogUI;

  function updateStatusUI(status, message, senderEmail = null) {
    if (!resultElement || !statusIndicator) return;

    if (status === "running" && senderEmail && senderEmail !== currentUserEmail) {
      resultElement.innerText = `Đang có người khác gửi: ${senderEmail}`;
    } else {
      resultElement.innerText = message || "";
    }

    statusIndicator.className = "status-indicator";

    if (status === "running") {
      statusIndicator.classList.add("running");
      if (progressBar) progressBar.classList.remove("hidden");
      if (sendBtn) sendBtn.disabled = true;
    } else if (status === "success") {
      statusIndicator.classList.add("success");
      if (progressBar) progressBar.classList.add("hidden");
      if (sendBtn) sendBtn.disabled = false;
    } else if (status === "error") {
      statusIndicator.classList.add("error");
      if (progressBar) progressBar.classList.add("hidden");
      if (sendBtn) sendBtn.disabled = false;
    } else {
      statusIndicator.classList.add("idle");
      if (progressBar) progressBar.classList.add("hidden");
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  async function sendEmails() {
    updateStatusUI("running", "Đang khởi tạo...");

    try {
      const res = await fetch("/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ soc: SOC }),
      });

      const data = await res.json().catch(() => ({}));

      if (data.status === "started") {
        updateStatusUI("running", data.message || "Đang chạy...");
        checkStatusContinuously();
      } else if (data.status === "busy") {
        updateStatusUI("running", data.message || "Đang có người khác chạy", data.by);
      } else {
        updateStatusUI("error", data.message || "Không thể bắt đầu");
      }
    } catch (e) {
      updateStatusUI("error", "Lỗi kết nối: " + e.message);
    }
    fetchLog().catch(() => {});
  }

  async function fetchStatus() {
    const res = await fetch(`/status?soc=${encodeURIComponent(SOC)}`);
    return res.json();
  }

  function checkStatusContinuously() {
    const interval = setInterval(async () => {
      try {
        const data = await fetchStatus();

        if (data.running) {
          if (data.by && data.by !== currentUserEmail) {
            updateStatusUI("running", data.message, data.by);
          } else {
            updateStatusUI("running", data.message || "Đang chạy...");
          }
          fetchLog().catch(() => {});
        } else {
          const msg = String(data.message || "");
          if (msg.toLowerCase().includes("lỗi")) updateStatusUI("error", msg);
          else if (msg.toLowerCase().includes("hoàn thành")) updateStatusUI("success", msg);
          else updateStatusUI("idle", msg || "Chưa chạy");
          clearInterval(interval);
        }
      } catch (e) {
        updateStatusUI("error", "Lỗi kiểm tra trạng thái: " + e.message);
        clearInterval(interval);
      }
    }, 2000);
  }

  // Expose sendEmails to global for onclick
  window.sendEmails = sendEmails;

  // init status
  window.addEventListener("load", async () => {
    try {
        fetchLog().catch(() => {});
      const data = await fetchStatus();
      if (data.running) {
        if (data.by && data.by !== currentUserEmail) {
          updateStatusUI("running", data.message, data.by);
        } else {
          updateStatusUI("running", data.message || "Đang chạy...");
          checkStatusContinuously();
        }
      } else {
        updateStatusUI("idle", data.message || "Chưa chạy");
      }
    } catch (e) {
      updateStatusUI("error", "Không thể kết nối đến server");
    }
  });
})();
