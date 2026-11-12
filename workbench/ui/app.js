(function () {
  var selectedId = "";
  var lastOverview = null;

  var SUGGEST = {
    tick: "推進一步",
    stop_after_save: "保存後停止",
    stop_now: "立即停止"
  };

  var VERIFY = {
    verified: "已驗",
    unverified: "未驗",
    mismatch: "不符"
  };

  var CONTRACT_LABEL = {
    job_id: "工作編號",
    template_id: "範本",
    job_type: "類型",
    workload_kind: "工作型態",
    cu_cap: "硬上限",
    cu_soft_ratio: "軟上限比例",
    max_minutes: "最長分鐘",
    stall_minutes: "停滯門檻",
    on_host_offline: "關機策略",
    submitted_by: "提交者"
  };

  var WORK = {
    training: "訓練",
    batch_inference: "批次推論"
  };

  var OFFLINE = {
    pause_safely: "先保存再暫停",
    continue_until_checkpoint: "跑到下一個檢查點"
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function clear(node) {
    while (node && node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function add(parent, tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    parent.appendChild(node);
    return node;
  }

  function num(value) {
    if (typeof value !== "number" || !isFinite(value)) {
      return "—";
    }
    var rounded = Math.round(value * 1000) / 1000;
    return String(rounded);
  }

  function flashText(text) {
    byId("flash").textContent = text || "";
  }

  function read(res) {
    return res.json().then(function (data) {
      return { ok: res.ok, status: res.status, data: data };
    });
  }

  function fail() {
    flashText("無法讀取本機服務");
  }

  function messageOf(data) {
    if (!data) {
      return "";
    }
    if (data.ui_message) {
      return data.ui_message;
    }
    if (data.decision && data.decision.ui_message) {
      return data.decision.ui_message;
    }
    if (data.reason_code) {
      return data.reason_code;
    }
    return "已更新";
  }

  function titleFor(id) {
    var jobs = (lastOverview && lastOverview.jobs) || [];
    var index;
    for (index = 0; index < jobs.length; index += 1) {
      if (jobs[index].job_id === id) {
        return jobs[index].title + "（" + id + "）";
      }
    }
    return id;
  }

  function renderHost(data) {
    byId("host-now").textContent = data.host_label || "";
    var list = byId("wind-list");
    clear(list);
    var ids = data.wind_down || [];
    if (!ids.length) {
      add(list, "li", "muted", "目前沒有需要先收尾的工作");
      return;
    }
    ids.forEach(function (id) {
      add(list, "li", "", titleFor(id));
    });
  }

  function renderList(data) {
    var box = byId("job-rows");
    clear(box);
    (data.jobs || []).forEach(function (job) {
      var button = document.createElement("button");
      button.type = "button";
      var selected = job.job_id === selectedId ? " is-selected" : "";
      button.className = "job-row" + selected;
      add(button, "span", "job-title", job.title);
      add(button, "span", "pill state-" + job.state, job.state_label);
      add(
        button,
        "span",
        "job-meta",
        job.job_type + " · " + (job.busy ? "忙" : "閒") + " · " + (job.submitter_label || "")
      );
      if (job.human_hold) {
        add(button, "span", "job-sub", "人工鎖");
      }
      var progress = job.progress || {};
      var total = progress.total || 1;
      var value = typeof progress.value === "number" ? progress.value : 0;
      var pct = Math.max(0, Math.min(100, (value / total) * 100));
      var bar = add(button, "span", "bar");
      var fill = add(bar, "span", "bar-fill");
      fill.style.width = pct.toFixed(0) + "%";
      var used = job.cu ? job.cu.used : null;
      var cap = job.cu ? job.cu.cap : null;
      add(button, "span", "job-sub", "已用 " + num(used) + " / 上限 " + num(cap));
      button.addEventListener("click", function () {
        selectedId = job.job_id;
        renderList(lastOverview);
        loadDetail();
      });
      box.appendChild(button);
    });
  }

  function renderDetail(job) {
    var box = byId("detail-body");
    clear(box);
    add(box, "h3", "", job.title);
    var line = add(box, "p", "");
    add(line, "span", "pill state-" + job.state, job.state_label);
    add(line, "span", "", " " + (job.job_type || "") + " · " + (job.submitter_label || ""));
    add(line, "span", "", job.busy ? " · 忙" : " · 閒");
    if (job.human_hold) {
      add(line, "span", "risk", " · 人工鎖");
    }
    if (job.decision && job.decision.ui_message) {
      add(box, "p", "next-step", job.decision.ui_message);
    }
    if (job.decision_error) {
      add(box, "p", "risk", "這筆假資料目前無法判斷下一步");
    }
    if (job.decision && job.decision.data_at_risk) {
      add(box, "p", "risk", "有未保存的產出可能遺失");
    }
    var progress = job.progress || {};
    add(box, "p", "", "進度 " + num(progress.value) + " / " + num(progress.total));
    renderCheckpoint(box, job.checkpoint || {});
    renderTimeline(box, job.timeline || []);
    renderContract(box, job.contract_summary || {});
    renderAudit(box, job.audit || []);
    renderBlocker(job);
    renderCu(job);
    renderFiles(job.files || []);
    renderRelease(job);
  }

  function renderCheckpoint(box, checkpoint) {
    add(box, "h3", "", "最後確認的檢查點");
    add(box, "p", "kv", "步數 " + num(checkpoint.step));
    add(box, "p", "kv", checkpoint.confirmed ? "已確認" : "尚未確認");
    add(box, "p", "kv", "確認時間（假分鐘） " + num(checkpoint.confirmed_at));
  }

  function renderTimeline(box, items) {
    add(box, "h3", "", "時間軸");
    if (!items.length) {
      add(box, "p", "muted", "尚無轉移紀錄");
      return;
    }
    var list = add(box, "ul", "timeline");
    items.forEach(function (item) {
      var origin = item.from === null || item.from === undefined ? "起點" : String(item.from);
      var text = "第 " + num(item.at) + " 分，" + origin + " → " + item.to + "，觸發者 " + item.by;
      add(list, "li", "", text);
    });
  }

  function showValue(key, value) {
    if (key === "workload_kind" && WORK[value]) {
      return WORK[value];
    }
    if (key === "on_host_offline" && OFFLINE[value]) {
      return OFFLINE[value];
    }
    if (typeof value === "number") {
      return num(value);
    }
    if (value === null || value === undefined) {
      return "—";
    }
    return String(value);
  }

  function renderContract(box, summary) {
    add(box, "h3", "", "合約摘要");
    Object.keys(summary).forEach(function (key) {
      var label = CONTRACT_LABEL[key] || key;
      add(box, "p", "kv", label + " " + showValue(key, summary[key]));
    });
  }

  function renderAudit(box, items) {
    add(box, "h3", "", "稽核（只在這次開啟的記憶體裡）");
    if (!items.length) {
      add(box, "p", "muted", "尚無稽核");
      return;
    }
    var list = add(box, "ul", "audit-list");
    items.forEach(function (item) {
      var when = item.at === null || item.at === undefined ? "無時間" : ("第 " + num(item.at) + " 分");
      add(list, "li", "", when + " · " + item.caller + " · " + item.action + " · " + item.result);
    });
  }

  function renderBlocker(job) {
    var box = byId("blocker-body");
    clear(box);
    if (!job.blocker) {
      add(box, "p", "muted", "目前沒有需要你處理的阻塞");
      return;
    }
    add(box, "p", "", job.blocker.message);
    var row = add(box, "div", "suggest");
    (job.blocker.suggested || []).forEach(function (name) {
      var button = add(row, "button", "", SUGGEST[name] || name);
      button.type = "button";
      button.addEventListener("click", function () {
        runSuggest(name);
      });
    });
  }

  function renderCu(job) {
    var box = byId("cu-body");
    clear(box);
    var cu = job.cu || {};
    add(box, "p", "", "已用 " + num(cu.used) + " / 硬上限 " + num(cu.cap));
    add(box, "p", "", "軟上限 " + num(cu.soft) + " · 餘額 " + num(cu.balance));
    add(box, "p", "", "每小時 " + num(cu.rate_per_hour));
    var minutes = cu.minutes_to_cap;
    var minuteText = minutes === null || minutes === undefined ? "無法估算" : num(minutes);
    add(box, "p", "", "預計到上限（分鐘） " + minuteText);
  }

  function renderFiles(files) {
    var box = byId("outputs-body");
    clear(box);
    if (!files.length) {
      add(box, "p", "muted", "這筆任務沒有列出產出檔");
      return;
    }
    files.forEach(function (file) {
      var row = add(box, "div", "file-row");
      add(row, "strong", "", file.name);
      add(row, "span", "", num(file.size_bytes) + " 位元組");
      add(row, "span", "", "雜湊 " + file.sha256_8);
      add(row, "span", "", VERIFY[file.verify] || String(file.verify));
      add(row, "span", "", file.landed ? "已落地" : "尚未落地");
    });
  }

  function renderRelease(job) {
    var box = byId("release-body");
    clear(box);
    add(box, "p", "release-flag state-" + job.state, job.release_label);
  }

  function renderEmpty() {
    var box = byId("detail-body");
    clear(box);
    add(box, "p", "muted", "從左側列表點一筆任務。");
    clear(byId("blocker-body"));
    add(byId("blocker-body"), "p", "muted", "尚未選擇任務");
    clear(byId("cu-body"));
    clear(byId("outputs-body"));
    clear(byId("release-body"));
  }

  function loadDetail() {
    if (!selectedId) {
      renderEmpty();
      return Promise.resolve();
    }
    return fetch("/api/jobs/" + selectedId)
      .then(read)
      .then(function (pack) {
        if (!pack.ok) {
          flashText(messageOf(pack.data));
          return;
        }
        renderDetail(pack.data);
      })
      .catch(fail);
  }

  function loadList() {
    return fetch("/api/jobs")
      .then(read)
      .then(function (pack) {
        if (!pack.ok) {
          flashText(messageOf(pack.data));
          return;
        }
        lastOverview = pack.data;
        if (!selectedId && pack.data.jobs && pack.data.jobs.length) {
          selectedId = pack.data.jobs[0].job_id;
        }
        renderHost(pack.data);
        renderList(pack.data);
        return loadDetail();
      })
      .catch(fail);
  }

  function afterWrite(pack) {
    flashText(messageOf(pack.data));
    return loadList();
  }

  function needSelection() {
    if (selectedId) {
      return false;
    }
    flashText("請先在列表選一筆任務");
    return true;
  }

  function sendCommand(command, confirm) {
    if (needSelection()) {
      return;
    }
    var payload = { command: command };
    if (confirm === true) {
      payload.confirm = true;
    }
    fetch("/api/jobs/" + selectedId + "/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(read).then(afterWrite).catch(fail);
  }

  function onStopNow() {
    if (needSelection()) {
      return;
    }
    var accepted = window.confirm("立即停止可能遺失未保存產出，確定要繼續嗎？");
    if (!accepted) {
      return;
    }
    sendCommand("stop_now", true);
  }

  function onTick() {
    if (needSelection()) {
      return;
    }
    fetch("/api/jobs/" + selectedId + "/tick", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    }).then(read).then(afterWrite).catch(fail);
  }

  function sendHost(name) {
    fetch("/api/host", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ host: name })
    }).then(read).then(afterWrite).catch(fail);
  }

  function onReset() {
    fetch("/api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    }).then(read).then(function (pack) {
      selectedId = "";
      return afterWrite(pack);
    }).catch(fail);
  }

  function runSuggest(name) {
    if (name === "tick") {
      onTick();
      return;
    }
    if (name === "stop_now") {
      onStopNow();
      return;
    }
    if (name === "stop_after_save") {
      sendCommand("stop_after_save", false);
    }
  }

  byId("btn-stop-after-save").addEventListener("click", function () {
    sendCommand("stop_after_save", false);
  });
  byId("btn-stop-now").addEventListener("click", onStopNow);
  byId("btn-pause").addEventListener("click", function () {
    sendCommand("pause", false);
  });
  byId("btn-resume").addEventListener("click", function () {
    sendCommand("resume", false);
  });
  byId("btn-tick").addEventListener("click", onTick);
  byId("btn-host-online").addEventListener("click", function () {
    sendHost("online");
  });
  byId("btn-host-shut").addEventListener("click", function () {
    sendHost("shutting_down");
  });
  byId("btn-host-boot").addEventListener("click", function () {
    sendHost("just_booted");
  });
  byId("btn-reset").addEventListener("click", onReset);
  loadList();
}());
