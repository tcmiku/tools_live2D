let backend = null;
let currentState = { status: "idle" };
let canvasCtx = null;
let canvasSize = { width: 0, height: 0 };
let usePlaceholder = true;
let live2dApp = null;
let live2dModel = null;
let animationSpeed = 1.0;
let motionGroups = ["Tap", "Flick", "Flick3", "Idle"];
const modelConfig = {
  scale: 0.35,
  x: 0.6,
  y: 0.65,
  xOffset: 0,
  yOffset: 0,
};
let settingsState = {
  focus_active_ms: 60000,
  focus_sleep_ms: 120000,
  window_opacity: 100,
  model_scale: 0.35,
  model_x: 0.6,
  model_y: 0.65,
  model_x_offset: 0.0,
  model_y_offset: 0.0,
  ui_scale: 1.0,
  animation_speed: 1.0,
  pomodoro_focus_min: 25,
  pomodoro_break_min: 5,
  rest_enabled: true,
  rest_interval_min: 90,
  water_enabled: true,
  water_interval_min: 60,
  eye_enabled: true,
  eye_interval_min: 45,
  ai_provider: "OpenAI兼容",
  ai_base_url: "https://api.openai.com/v1",
  ai_model: "gpt-4o-mini",
  ai_api_key: "",
  passive_enabled: true,
  passive_interval_min: 30,
  passive_random_enabled: true,
  passive_blessing_enabled: true,
  passive_focus_enabled: true,
  passive_focus_interval_min: 60,
  local_city: "",
  local_location: "",
  favor: 50,
};
let noteState = "";
let clipboardItems = [];
let pomodoroState = null;
let todoItems = [];
const interactionState = {
  dragging: false,
  lastX: 0,
  lastY: 0,
};
const dragBlockers = {
  model: false,
  ui: false,
};
let allowWindowDrag = true;
let moveModeEnabled = false;
let pendingWindowDrag = null;
let saveTimer = null;
let noteSaveTimer = null;
let moveDragActive = false;
let settingsSyncTimer = null;
let clickPulseUntil = 0;
let lastPettingTime = 0;
let lastSystemInfo = null;
let lastAiTestStatus = "未测试";
let bubbleTimer = null;
let bubbleText = "";
let toolbarHideTimer = null;

function appendChatMessage(who, text) {
  const box = document.getElementById("chat-box");
  const msg = document.createElement("div");
  msg.className = `msg ${who}`;
  msg.textContent = text;
  box.appendChild(msg);
  box.scrollTop = box.scrollHeight;
}

function showSpeechBubble(text, durationMs = 4000) {
  const bubble = document.getElementById("speech-bubble");
  if (!bubble) return;
  bubbleText = text;
  bubble.textContent = text;
  bubble.classList.add("show");
  updateSpeechBubblePosition();
  if (bubbleTimer) {
    clearTimeout(bubbleTimer);
  }
  bubbleTimer = setTimeout(() => {
    bubble.classList.remove("show");
    bubbleText = "";
  }, durationMs);
}

function updateSpeechBubblePosition() {
  const bubble = document.getElementById("speech-bubble");
  const canvas = document.getElementById("canvas");
  if (!bubble || !canvas) return;
  if (!bubbleText) return;
  const rect = canvas.getBoundingClientRect();
  let x = rect.right - 40;
  let y = rect.top + 20;

  if (!usePlaceholder && live2dModel && live2dApp) {
    const bounds = live2dModel.getBounds();
    const scaleX = rect.width / live2dApp.renderer.width;
    const scaleY = rect.height / live2dApp.renderer.height;
    const headX = rect.left + (bounds.x + bounds.width * 0.5) * scaleX;
    const headY = rect.top + bounds.y * scaleY - 12;
    x = headX - bubble.offsetWidth * 0.5;
    y = headY - bubble.offsetHeight;
  } else {
    const baseSize = Math.min(rect.width, rect.height) * 0.42;
    const headX = rect.left + rect.width * 0.58;
    const headY = rect.top + rect.height * 0.58 - baseSize * 0.65;
    x = headX - bubble.offsetWidth * 0.5;
    y = headY - bubble.offsetHeight;
  }

  bubble.style.left = `${x}px`;
  bubble.style.top = `${y}px`;
  bubble.style.right = "auto";
}

function logStatus(text) {
  appendChatMessage("pet", text);
}

function handleStateUpdate(state) {
  if (!state) return;
  currentState = state;
  // TODO: trigger Live2D motions or expressions based on state.status
}

function sendUserMessage() {
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text || !backend) return;
  appendChatMessage("user", text);
  if (typeof backend.addFavor === "function") {
    backend.addFavor(1);
  }
  backend.sendUserMessage(text);
  input.value = "";
}

function setupEnterSend() {
  const input = document.getElementById("chat-input");
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      sendUserMessage();
    }
  });
}

function setPanelCollapsed(collapsed) {
  const panel = document.getElementById("chat-panel");
  const hint = document.querySelector("#chat-handle .hint");
  if (!panel) return;
  panel.classList.toggle("collapsed", collapsed);
  if (hint) {
    hint.textContent = collapsed ? "点击展开" : "点击收起";
  }
}

function setWindowDragAllowed(allowed) {
  if (!backend || typeof backend.setWindowDragEnabled !== "function") {
    pendingWindowDrag = allowed;
    return;
  }
  if (allowWindowDrag === allowed) return;
  allowWindowDrag = allowed;
  backend.setWindowDragEnabled(allowed);
}

function updateWindowDragState() {
  if (moveModeEnabled) {
    setWindowDragAllowed(true);
    return;
  }
  setWindowDragAllowed(!dragBlockers.model && !dragBlockers.ui);
}

function setDragBlocker(key, value) {
  dragBlockers[key] = value;
  updateWindowDragState();
}

function updateMoveButton(enabled) {
  const button = document.getElementById("move-toggle");
  if (!button) return;
  button.textContent = enabled ? "移动中" : "移动";
}

function setMoveMode(enabled) {
  moveModeEnabled = enabled;
  updateMoveButton(moveModeEnabled);
  document.body.classList.toggle("move-mode", moveModeEnabled);
  if (moveModeEnabled) {
    setDragBlocker("model", false);
    setDragBlocker("ui", false);
  }
  updateWindowDragState();
  logStatus(moveModeEnabled ? "进入移动模式" : "退出移动模式");
}

function setupChatPanelBehavior() {
  const panel = document.getElementById("chat-panel");
  const handle = document.getElementById("chat-handle");
  const input = document.getElementById("chat-input");
  const moveButton = document.getElementById("move-toggle");
  const settingsButton = document.getElementById("settings-toggle");
  if (!panel || !handle || !input) return;

  handle.addEventListener("click", () => {
    const isCollapsed = panel.classList.contains("collapsed");
    setPanelCollapsed(!isCollapsed);
    if (isCollapsed) {
      input.focus();
    }
  });

  input.addEventListener("focus", () => {
    if (panel.classList.contains("collapsed")) {
      setPanelCollapsed(false);
    }
  });

  panel.addEventListener("mouseenter", () => setDragBlocker("ui", true));
  panel.addEventListener("mouseleave", () => setDragBlocker("ui", false));
  input.addEventListener("focus", () => setDragBlocker("ui", true));
  input.addEventListener("blur", () => setDragBlocker("ui", false));

  if (moveButton) {
    moveButton.addEventListener("click", (event) => {
      event.stopPropagation();
      setMoveMode(!moveModeEnabled);
    });
  }

  if (settingsButton) {
    settingsButton.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleSettingsPanel();
    });
  }

  setPanelCollapsed(true);
}

function setupContextMenu() {
  const menu = document.getElementById("context-menu");
  const settingsItem = document.getElementById("context-settings");
  const chatToggle = document.getElementById("context-chat-toggle");
  const toolsItem = document.getElementById("context-tools");
  const pomoItem = document.getElementById("context-pomodoro");
  const reminderItem = document.getElementById("context-reminders");
  const aiItem = document.getElementById("context-ai");
  const passiveItem = document.getElementById("context-passive");
  const moreInfoItem = document.getElementById("context-more-info");
  if (!menu || !settingsItem || !chatToggle || !toolsItem || !pomoItem || !reminderItem || !aiItem || !passiveItem || !moreInfoItem) return;

  document.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    menu.classList.add("visible");
    menu.style.left = `${event.clientX}px`;
    menu.style.top = `${event.clientY}px`;
    chatToggle.textContent = isChatPanelHidden() ? "显示聊天框" : "隐藏聊天框";
  });

  document.addEventListener("click", () => {
    menu.classList.remove("visible");
  });

  toolsItem.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.classList.remove("visible");
    toggleToolPanel("tools-panel");
  });

  pomoItem.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.classList.remove("visible");
    toggleToolPanel("pomodoro-panel");
  });

  reminderItem.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.classList.remove("visible");
    toggleToolPanel("reminder-panel");
  });

  aiItem.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.classList.remove("visible");
    toggleToolPanel("ai-panel");
  });

  passiveItem.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.classList.remove("visible");
    toggleToolPanel("passive-panel");
  });

  moreInfoItem.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.classList.remove("visible");
    toggleToolPanel("more-info-panel");
  });

  settingsItem.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.classList.remove("visible");
    toggleSettingsPanel(true);
  });

  chatToggle.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.classList.remove("visible");
    toggleChatPanelVisibility();
    chatToggle.textContent = isChatPanelHidden() ? "显示聊天框" : "隐藏聊天框";
  });
}

function setupPanelCloseButtons() {
  document.querySelectorAll(".panel-close").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      const targetId = btn.getAttribute("data-close");
      if (!targetId) return;
      const panel = document.getElementById(targetId);
      if (panel) {
        panel.classList.remove("visible");
      }
    });
  });
}

function setupPanelDrag() {
  document.querySelectorAll(".tool-panel").forEach((panel) => {
    const title = panel.querySelector(".panel-title");
    if (!title) return;
    let dragging = false;
    let offsetX = 0;
    let offsetY = 0;

    title.addEventListener("mousedown", (event) => {
      if (event.button !== 0) return;
      dragging = true;
      const rect = panel.getBoundingClientRect();
      offsetX = event.clientX - rect.left;
      offsetY = event.clientY - rect.top;
      panel.style.left = `${rect.left}px`;
      panel.style.top = `${rect.top}px`;
      panel.style.right = "auto";
      panel.style.bottom = "auto";
      panel.classList.add("dragging");
      event.preventDefault();
    });

    window.addEventListener("mousemove", (event) => {
      if (!dragging) return;
      const x = event.clientX - offsetX;
      const y = event.clientY - offsetY;
      panel.style.left = `${x}px`;
      panel.style.top = `${y}px`;
    });

    window.addEventListener("mouseup", () => {
      if (!dragging) return;
      dragging = false;
      panel.classList.remove("dragging");
    });
  });
}

function toggleToolPanel(id) {
  const panels = [
    "tools-panel",
    "note-panel",
    "clipboard-panel",
    "sysinfo-panel",
    "settings-panel",
    "pomodoro-panel",
    "reminder-panel",
    "todo-panel",
    "ai-panel",
    "passive-panel",
    "more-info-panel",
  ];
  panels.forEach((panelId) => {
    const panel = document.getElementById(panelId);
    if (!panel) return;
    if (panelId === id) {
      panel.classList.toggle("visible");
    } else {
      panel.classList.remove("visible");
    }
  });
  if (id === "note-panel") {
    loadNote();
  }
  if (id === "clipboard-panel") {
    renderClipboard();
  }
  if (id === "pomodoro-panel") {
    syncPomodoroPanel();
  }
  if (id === "reminder-panel") {
    syncReminderPanel();
  }
  if (id === "todo-panel") {
    renderTodoList();
  }
  if (id === "ai-panel") {
    syncAIConfig();
  }
  if (id === "passive-panel") {
    syncPassivePanel();
  }
  if (id === "more-info-panel") {
    syncMoreInfoPanel();
  }
}

function setupToolsPanel() {
  const noteBtn = document.getElementById("tool-note");
  const clipboardBtn = document.getElementById("tool-clipboard");
  const sysBtn = document.getElementById("tool-sysinfo");
  if (noteBtn) {
    noteBtn.addEventListener("click", () => toggleToolPanel("note-panel"));
  }
  if (clipboardBtn) {
    clipboardBtn.addEventListener("click", () => toggleToolPanel("clipboard-panel"));
  }
  if (sysBtn) {
    sysBtn.addEventListener("click", () => toggleToolPanel("sysinfo-panel"));
  }
}

function setupPomodoroPanel() {
  const focusInput = document.getElementById("pomodoro-focus");
  const breakInput = document.getElementById("pomodoro-break");
  const startBtn = document.getElementById("pomodoro-start");
  const pauseBtn = document.getElementById("pomodoro-pause");
  const stopBtn = document.getElementById("pomodoro-stop");

  if (startBtn) {
    startBtn.addEventListener("click", () => {
      if (backend && typeof backend.setPomodoroDurations === "function") {
        const focusVal = Number(focusInput?.value || 25);
        const breakVal = Number(breakInput?.value || 5);
        backend.setPomodoroDurations(focusVal, breakVal);
      }
      if (backend && typeof backend.startPomodoro === "function") {
        backend.startPomodoro();
      }
    });
  }
  if (pauseBtn) {
    pauseBtn.addEventListener("click", () => {
      if (backend && typeof backend.pausePomodoro === "function") {
        backend.pausePomodoro();
      }
    });
  }
  if (stopBtn) {
    stopBtn.addEventListener("click", () => {
      if (backend && typeof backend.stopPomodoro === "function") {
        backend.stopPomodoro();
      }
    });
  }
  if (focusInput) {
    focusInput.addEventListener("input", () => {
      const focusVal = Number(focusInput.value || 25);
      const breakVal = Number(breakInput?.value || 5);
      if (backend && typeof backend.setPomodoroDurations === "function") {
        backend.setPomodoroDurations(focusVal, breakVal);
      }
    });
  }
  if (breakInput) {
    breakInput.addEventListener("input", () => {
      const focusVal = Number(focusInput?.value || 25);
      const breakVal = Number(breakInput.value || 5);
      if (backend && typeof backend.setPomodoroDurations === "function") {
        backend.setPomodoroDurations(focusVal, breakVal);
      }
    });
  }
}

function setupReminderPanel() {
  const restEnabled = document.getElementById("rest-enabled");
  const restInterval = document.getElementById("rest-interval");
  const waterEnabled = document.getElementById("water-enabled");
  const waterInterval = document.getElementById("water-interval");
  const eyeEnabled = document.getElementById("eye-enabled");
  const eyeInterval = document.getElementById("eye-interval");
  const todoOpen = document.getElementById("open-todo-panel");

  const pushSettings = () => {
    const payload = {
      rest_enabled: !!restEnabled?.checked,
      rest_interval_min: Number(restInterval?.value || 90),
      water_enabled: !!waterEnabled?.checked,
      water_interval_min: Number(waterInterval?.value || 60),
      eye_enabled: !!eyeEnabled?.checked,
      eye_interval_min: Number(eyeInterval?.value || 45),
    };
    if (backend && typeof backend.setReminderSettings === "function") {
      backend.setReminderSettings(payload);
    }
    applySettings(payload);
  };

  [restEnabled, restInterval, waterEnabled, waterInterval, eyeEnabled, eyeInterval].forEach((el) => {
    if (!el) return;
    el.addEventListener("input", pushSettings);
    el.addEventListener("change", pushSettings);
  });

  if (todoOpen) {
    todoOpen.addEventListener("click", () => {
      toggleToolPanel("todo-panel");
    });
  }
}

function setupTodoPanel() {
  const todoTitle = document.getElementById("todo-title");
  const todoTime = document.getElementById("todo-time");
  const todoAdd = document.getElementById("todo-add");

  if (todoAdd) {
    todoAdd.addEventListener("click", () => {
      const title = todoTitle?.value.trim();
      const timeValue = todoTime?.value;
      if (!title || !timeValue) return;
      const ts = new Date(timeValue).getTime() / 1000;
      if (Number.isNaN(ts)) return;
      if (backend && typeof backend.addTodo === "function") {
        backend.addTodo(title, ts);
      }
      todoTitle.value = "";
    });
  }
}

function setupAIConfigPanel() {
  const provider = document.getElementById("ai-provider");
  const baseUrl = document.getElementById("ai-base-url");
  const model = document.getElementById("ai-model");
  const apiKey = document.getElementById("ai-api-key");
  const localCity = document.getElementById("ai-local-city");
  const localLocation = document.getElementById("ai-local-location");
  const saveBtn = document.getElementById("ai-save");
  const detailBtn = document.getElementById("ai-detail");
  const testBtn = document.getElementById("ai-test");
  const testResult = document.getElementById("ai-test-result");

  if (saveBtn) {
    saveBtn.addEventListener("click", () => {
      const payload = {
        ai_provider: provider?.value.trim() || "OpenAI兼容",
        ai_base_url: baseUrl?.value.trim() || "https://api.openai.com/v1",
        ai_model: model?.value.trim() || "gpt-4o-mini",
        ai_api_key: apiKey?.value.trim() || "",
        local_city: localCity?.value.trim() || "",
        local_location: localLocation?.value.trim() || "",
      };
      if (backend && typeof backend.setAISettings === "function") {
        backend.setAISettings(payload);
      }
      applySettings(payload);
    });
  }

  if (detailBtn) {
    detailBtn.addEventListener("click", () => {
      if (backend && typeof backend.openAIDetailDialog === "function") {
        backend.openAIDetailDialog();
      }
    });
  }

  if (testBtn) {
    testBtn.addEventListener("click", () => {
      if (testResult) {
        testResult.textContent = "测试中...";
      }
      if (backend && typeof backend.testAIConnection === "function") {
        backend.testAIConnection();
      }
    });
  }
}

function setupGiftButton() {
  const giftButton = document.getElementById("gift-button");
  if (!giftButton) return;
  giftButton.addEventListener("click", () => {
    if (typeof backend?.addFavor === "function") {
      backend.addFavor(5);
      appendChatMessage("pet", "收到啦！谢谢你～");
    }
  });
}

function setupQuickToolbar() {
  const toolbar = document.getElementById("quick-toolbar");
  if (!toolbar) return;
  const toggleBtn = document.getElementById("quick-toggle");
  const noteBtn = document.getElementById("quick-note");
  const pomoBtn = document.getElementById("quick-pomodoro");
  const settingsBtn = document.getElementById("quick-settings");

  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      if (backend && typeof backend.togglePetWindow === "function") {
        backend.togglePetWindow();
      } else {
        toggleChatPanelVisibility();
      }
    });
  }
  if (noteBtn) {
    noteBtn.addEventListener("click", () => toggleToolPanel("note-panel"));
  }
  if (pomoBtn) {
    pomoBtn.addEventListener("click", () => toggleToolPanel("pomodoro-panel"));
  }
  if (settingsBtn) {
    settingsBtn.addEventListener("click", () => toggleToolPanel("settings-panel"));
  }

  let dragging = false;
  let offsetX = 0;
  let offsetY = 0;
  toolbar.addEventListener("mousedown", (event) => {
    if (event.button !== 0) return;
    dragging = true;
    const rect = toolbar.getBoundingClientRect();
    offsetX = event.clientX - rect.left;
    offsetY = event.clientY - rect.top;
    toolbar.style.left = `${rect.left}px`;
    toolbar.style.top = `${rect.top}px`;
    toolbar.style.right = "auto";
    toolbar.style.bottom = "auto";
    event.preventDefault();
  });
  window.addEventListener("mousemove", (event) => {
    if (!dragging) return;
    const x = event.clientX - offsetX;
    const y = event.clientY - offsetY;
    toolbar.style.left = `${x}px`;
    toolbar.style.top = `${y}px`;
  });
  window.addEventListener("mouseup", () => {
    dragging = false;
  });

  const hideToolbar = () => {
    toolbar.classList.add("hidden");
  };
  const showToolbar = () => {
    toolbar.classList.remove("hidden");
    if (toolbarHideTimer) {
      clearTimeout(toolbarHideTimer);
    }
    toolbarHideTimer = setTimeout(hideToolbar, 2500);
  };
  toolbar.addEventListener("mouseenter", showToolbar);
  toolbar.addEventListener("mouseleave", () => {
    if (toolbarHideTimer) clearTimeout(toolbarHideTimer);
    toolbarHideTimer = setTimeout(hideToolbar, 1200);
  });
  showToolbar();
}

function setupFavorReset() {
  const resetButton = document.getElementById("favor-reset");
  if (!resetButton) return;
  resetButton.addEventListener("click", () => {
    if (typeof backend?.addFavor === "function") {
      const current = Number(settingsState.favor ?? 50);
      backend.addFavor(-current);
      showSpeechBubble("好感度已重置");
    }
  });
}

function setupPassivePanel() {
  const enabled = document.getElementById("passive-enabled");
  const randomEnabled = document.getElementById("passive-random-enabled");
  const blessingEnabled = document.getElementById("passive-blessing-enabled");
  const focusEnabled = document.getElementById("passive-focus-enabled");
  const interval = document.getElementById("passive-interval");
  const focusInterval = document.getElementById("passive-focus-interval");

  const pushSettings = () => {
    const payload = {
      passive_enabled: !!enabled?.checked,
      passive_random_enabled: !!randomEnabled?.checked,
      passive_blessing_enabled: !!blessingEnabled?.checked,
      passive_focus_enabled: !!focusEnabled?.checked,
      passive_interval_min: Number(interval?.value || 30),
      passive_focus_interval_min: Number(focusInterval?.value || 60),
    };
    if (backend && typeof backend.setSettings === "function") {
      backend.setSettings(payload);
    }
    applySettings(payload);
  };

  [enabled, randomEnabled, blessingEnabled, focusEnabled, interval, focusInterval].forEach((el) => {
    if (!el) return;
    el.addEventListener("input", pushSettings);
    el.addEventListener("change", pushSettings);
  });
}
function syncPomodoroPanel() {
  const focusInput = document.getElementById("pomodoro-focus");
  const breakInput = document.getElementById("pomodoro-break");
  const progress = document.getElementById("pomodoro-progress");
  if (focusInput) focusInput.value = settingsState.pomodoro_focus_min;
  if (breakInput) breakInput.value = settingsState.pomodoro_break_min;
  if (!pomodoroState) return;
  const mode = document.getElementById("pomodoro-mode");
  const remaining = document.getElementById("pomodoro-remaining");
  const count = document.getElementById("pomodoro-count");
  if (mode) mode.textContent = pomodoroState.mode;
  if (remaining) remaining.textContent = formatTime(pomodoroState.remaining_sec);
  if (count) count.textContent = String(pomodoroState.count_today || 0);
  if (progress) {
    const total = pomodoroState.mode === "break" ? pomodoroState.break_min * 60 : pomodoroState.focus_min * 60;
    const value = total > 0 ? Math.max(0, Math.min(1, 1 - pomodoroState.remaining_sec / total)) : 0;
    progress.style.width = `${Math.round(value * 100)}%`;
  }
}

function applyPomodoroState(state) {
  pomodoroState = state;
  syncPomodoroPanel();
  if (!state) return;
  if (state.mode === "focus") {
    console.log("pomodoro focus: trigger focused motion");
  } else if (state.mode === "break") {
    console.log("pomodoro break: trigger relaxed motion");
  }
}

function syncReminderPanel() {
  const restEnabled = document.getElementById("rest-enabled");
  const restInterval = document.getElementById("rest-interval");
  const waterEnabled = document.getElementById("water-enabled");
  const waterInterval = document.getElementById("water-interval");
  const eyeEnabled = document.getElementById("eye-enabled");
  const eyeInterval = document.getElementById("eye-interval");

  if (restEnabled) restEnabled.checked = !!settingsState.rest_enabled;
  if (restInterval) restInterval.value = settingsState.rest_interval_min;
  if (waterEnabled) waterEnabled.checked = !!settingsState.water_enabled;
  if (waterInterval) waterInterval.value = settingsState.water_interval_min;
  if (eyeEnabled) eyeEnabled.checked = !!settingsState.eye_enabled;
  if (eyeInterval) eyeInterval.value = settingsState.eye_interval_min;
  renderTodoList();
}

function renderTodoList() {
  const list = document.getElementById("todo-list");
  if (!list) return;
  list.innerHTML = "";
  todoItems.forEach((item) => {
    const row = document.createElement("div");
    row.className = "todo-item";
    const title = document.createElement("span");
    title.textContent = item.title;
    const due = new Date(item.due_ts * 1000);
    const timeLabel = Number.isNaN(due.getTime()) ? "" : due.toLocaleString();
    title.title = timeLabel;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "todo-remove";
    remove.textContent = "删除";
    remove.addEventListener("click", () => {
      if (backend && typeof backend.removeTodo === "function") {
        backend.removeTodo(item.id);
      }
    });
    row.appendChild(title);
    row.appendChild(remove);
    list.appendChild(row);
  });
}

function syncAIConfig() {
  const provider = document.getElementById("ai-provider");
  const baseUrl = document.getElementById("ai-base-url");
  const model = document.getElementById("ai-model");
  const apiKey = document.getElementById("ai-api-key");
  const localCity = document.getElementById("ai-local-city");
  const localLocation = document.getElementById("ai-local-location");
  if (provider) provider.value = settingsState.ai_provider || "OpenAI兼容";
  if (baseUrl) baseUrl.value = settingsState.ai_base_url || "https://api.openai.com/v1";
  if (model) model.value = settingsState.ai_model || "gpt-4o-mini";
  if (apiKey) apiKey.value = settingsState.ai_api_key || "";
  if (localCity) localCity.value = settingsState.local_city || "";
  if (localLocation) localLocation.value = settingsState.local_location || "";
}

function syncFavorLabel() {
  const label = document.getElementById("favor-label");
  if (!label) return;
  const favor = Number(settingsState.favor || 50);
  label.textContent = `好感 ${favor}`;
}

function syncMoreInfoPanel() {
  const status = document.getElementById("info-status");
  const focus = document.getElementById("info-focus");
  const favor = document.getElementById("info-favor");
  const aiStatus = document.getElementById("info-ai-status");
  const aiModel = document.getElementById("info-ai-model");
  const pomo = document.getElementById("info-pomodoro");
  const thresholds = document.getElementById("info-thresholds");
  const opacity = document.getElementById("info-opacity");
  const modelScale = document.getElementById("info-model-scale");
  const cpu = document.getElementById("info-cpu");
  const mem = document.getElementById("info-mem");
  const net = document.getElementById("info-net");
  const battery = document.getElementById("info-battery");
  if (status) status.textContent = currentState?.status || "-";
  if (focus) focus.textContent = formatDuration(currentState?.focus_seconds_today || 0);
  if (favor) favor.textContent = String(settingsState.favor ?? 50);
  if (aiStatus) aiStatus.textContent = lastAiTestStatus;
  if (aiModel) aiModel.textContent = settingsState.ai_model || "-";
  if (pomo && pomodoroState) {
    const mode = pomodoroState.mode || "-";
    const remaining = formatTime(pomodoroState.remaining_sec || 0);
    pomo.textContent = `${mode} / ${remaining}`;
  } else if (pomo) {
    pomo.textContent = "-";
  }
  if (thresholds) {
    thresholds.textContent = `${Math.round(settingsState.focus_active_ms / 1000)} / ${Math.round(
      settingsState.focus_sleep_ms / 1000
    )}`;
  }
  if (opacity) opacity.textContent = `${settingsState.window_opacity}%`;
  if (modelScale) modelScale.textContent = Number(settingsState.model_scale).toFixed(2);
  if (lastSystemInfo) {
    if (cpu) cpu.textContent = lastSystemInfo.cpu == null ? "-" : `${lastSystemInfo.cpu.toFixed(0)}%`;
    if (mem) mem.textContent = lastSystemInfo.memory == null ? "-" : `${lastSystemInfo.memory.toFixed(0)}%`;
    const up = lastSystemInfo.net_up == null ? "-" : formatSpeed(lastSystemInfo.net_up);
    const down = lastSystemInfo.net_down == null ? "-" : formatSpeed(lastSystemInfo.net_down);
    if (net) net.textContent = `${down} / ${up}`;
    if (battery) battery.textContent = lastSystemInfo.battery == null ? "-" : `${lastSystemInfo.battery}%`;
  } else {
    if (cpu) cpu.textContent = "-";
    if (mem) mem.textContent = "-";
    if (net) net.textContent = "-";
    if (battery) battery.textContent = "-";
  }
}

function formatDuration(seconds) {
  const sec = Number(seconds || 0);
  if (sec < 60) return `${sec} 秒`;
  const minutes = Math.floor(sec / 60);
  const rem = sec % 60;
  if (minutes < 60) return `${minutes} 分钟 ${rem} 秒`;
  const hours = Math.floor(minutes / 60);
  const min = minutes % 60;
  return `${hours} 小时 ${min} 分钟`;
}

function syncPassivePanel() {
  const enabled = document.getElementById("passive-enabled");
  const randomEnabled = document.getElementById("passive-random-enabled");
  const blessingEnabled = document.getElementById("passive-blessing-enabled");
  const focusEnabled = document.getElementById("passive-focus-enabled");
  const interval = document.getElementById("passive-interval");
  const focusInterval = document.getElementById("passive-focus-interval");
  if (enabled) enabled.checked = !!settingsState.passive_enabled;
  if (randomEnabled) randomEnabled.checked = !!settingsState.passive_random_enabled;
  if (blessingEnabled) blessingEnabled.checked = !!settingsState.passive_blessing_enabled;
  if (focusEnabled) focusEnabled.checked = !!settingsState.passive_focus_enabled;
  if (interval) interval.value = settingsState.passive_interval_min;
  if (focusInterval) focusInterval.value = settingsState.passive_focus_interval_min;
}

function formatTime(seconds) {
  if (seconds == null) return "-";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function resizeCanvas() {
  const canvas = document.getElementById("canvas");
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  if (!usePlaceholder && live2dApp) {
    live2dApp.renderer.resize(rect.width, rect.height);
    positionLive2D();
    return;
  }
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  canvasCtx = canvas.getContext("2d");
  canvasCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  canvasSize = { width: rect.width, height: rect.height };
}

function statusColor(status) {
  switch (status) {
    case "active":
      return "#6ed7a7";
    case "idle":
      return "#f7d774";
    case "sleep":
      return "#8aa3ff";
    case "paused":
      return "#a5a5a5";
    default:
      return "#6ed7a7";
  }
}

function drawEye(ctx, x, y, w, h) {
  ctx.beginPath();
  if (typeof ctx.roundRect === "function") {
    ctx.roundRect(x, y, w, h, 6);
  } else {
    ctx.rect(x, y, w, h);
  }
  ctx.fill();
}

function drawPet(ctx, width, height, t) {
  const pulse = performance.now() < clickPulseUntil ? 1.06 : 1.0;
  const baseSize = Math.min(width, height) * 0.42 * pulse;
  const x = width * 0.58;
  const y = height * 0.58 + Math.sin(t / 600) * 6;
  const color = statusColor(currentState.status);

  ctx.clearRect(0, 0, width, height);

  ctx.fillStyle = "rgba(0,0,0,0.2)";
  ctx.beginPath();
  ctx.ellipse(x, y + baseSize * 0.58, baseSize * 0.45, baseSize * 0.12, 0, 0, Math.PI * 2);
  ctx.fill();

  const grad = ctx.createRadialGradient(x - baseSize * 0.2, y - baseSize * 0.3, baseSize * 0.2, x, y, baseSize);
  grad.addColorStop(0, "#ffffff");
  grad.addColorStop(0.5, color);
  grad.addColorStop(1, "#2b2b2b");

  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.arc(x, y, baseSize * 0.55, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(x - baseSize * 0.45, y - baseSize * 0.3);
  ctx.lineTo(x - baseSize * 0.7, y - baseSize * 0.7);
  ctx.lineTo(x - baseSize * 0.2, y - baseSize * 0.6);
  ctx.closePath();
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(x + baseSize * 0.45, y - baseSize * 0.3);
  ctx.lineTo(x + baseSize * 0.7, y - baseSize * 0.7);
  ctx.lineTo(x + baseSize * 0.2, y - baseSize * 0.6);
  ctx.closePath();
  ctx.fill();

  const blink = Math.abs(Math.sin(t / 900));
  const eyeH = blink < 0.1 ? 2 : 8;

  ctx.fillStyle = "#1a1a1a";
  drawEye(ctx, x - baseSize * 0.2, y - baseSize * 0.12, baseSize * 0.12, eyeH);
  drawEye(ctx, x + baseSize * 0.08, y - baseSize * 0.12, baseSize * 0.12, eyeH);

  ctx.strokeStyle = "#1a1a1a";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(x, y + baseSize * 0.12, baseSize * 0.12, 0, Math.PI);
  ctx.stroke();

  updateSpeechBubblePosition();
}

function animatePlaceholder(t) {
  if (!canvasCtx || !usePlaceholder) return;
  drawPet(canvasCtx, canvasSize.width, canvasSize.height, t * animationSpeed);
  requestAnimationFrame(animatePlaceholder);
}

function positionLive2D() {
  if (!live2dApp || !live2dModel) return;
  const scale = clamp(modelConfig.scale, 0.1, 2.0);
  live2dModel.position.set(
    live2dApp.renderer.width * modelConfig.x + modelConfig.xOffset,
    live2dApp.renderer.height * modelConfig.y + modelConfig.yOffset
  );
  live2dModel.scale.set(scale);
  updateSpeechBubblePosition();
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function getPointerInRenderer(event) {
  if (!live2dApp) return null;
  const canvas = document.getElementById("canvas");
  if (!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  const scaleX = live2dApp.renderer.width / rect.width;
  const scaleY = live2dApp.renderer.height / rect.height;
  return {
    x: (event.clientX - rect.left) * scaleX,
    y: (event.clientY - rect.top) * scaleY,
  };
}

function isPointerOverModel(event) {
  if (!live2dModel || !live2dApp) return false;
  const p = getPointerInRenderer(event);
  if (!p) return false;
  const bounds = live2dModel.getBounds();
  return bounds.contains(p.x, p.y);
}

function setupModelInteraction() {
  const canvas = document.getElementById("canvas");
  if (!canvas) return;

  canvas.addEventListener("mousedown", (event) => {
    if (moveModeEnabled) {
      return;
    }
    if (!isPointerOverModel(event)) {
      setDragBlocker("model", false);
      return;
    }
    interactionState.dragging = true;
    interactionState.lastX = event.clientX;
    interactionState.lastY = event.clientY;
    setDragBlocker("model", true);
  });

  window.addEventListener("mouseup", () => {
    if (!interactionState.dragging) return;
    interactionState.dragging = false;
    setDragBlocker("model", false);
    scheduleSaveModelConfig();
  });

  window.addEventListener("mousemove", (event) => {
    if (moveModeEnabled) {
      return;
    }
    if (live2dModel && !interactionState.dragging) {
      setDragBlocker("model", isPointerOverModel(event));
    }
    if (!interactionState.dragging || !live2dApp) return;
    const dx = event.clientX - interactionState.lastX;
    const dy = event.clientY - interactionState.lastY;
    interactionState.lastX = event.clientX;
    interactionState.lastY = event.clientY;
    modelConfig.xOffset += dx;
    modelConfig.yOffset += dy;
    positionLive2D();
  });

  canvas.addEventListener(
    "wheel",
    (event) => {
      if (moveModeEnabled) {
        return;
      }
      if (!live2dApp) return;
      event.preventDefault();
      const delta = -event.deltaY / 800;
      modelConfig.scale = clamp(modelConfig.scale + delta, 0.1, 2.0);
      positionLive2D();
      scheduleSaveModelConfig();
    },
    { passive: false }
  );
}

function isPointerOverPlaceholder(event) {
  const canvas = document.getElementById("canvas");
  if (!canvas) return false;
  const rect = canvas.getBoundingClientRect();
  const baseSize = Math.min(rect.width, rect.height) * 0.42;
  const cx = rect.left + rect.width * 0.58;
  const cy = rect.top + rect.height * 0.58;
  const dx = event.clientX - cx;
  const dy = event.clientY - cy;
  return dx * dx + dy * dy <= (baseSize * 0.6) * (baseSize * 0.6);
}

function createSpark(x, y) {
  const favor = Number(settingsState.favor || 50);
  const scale = favor >= 75 ? 1.3 : favor <= 25 ? 0.9 : 1.0;
  const spark = document.createElement("div");
  spark.className = "petting-spark";
  spark.textContent = "*";
  spark.style.left = `${x}px`;
  spark.style.top = `${y}px`;
  spark.style.fontSize = `${14 * scale}px`;
  document.body.appendChild(spark);
  setTimeout(() => spark.remove(), 800);
}

function triggerRandomMotion() {
  if (!live2dModel) return false;
  const groups = motionGroups.length ? motionGroups : ["Tap", "Flick", "Idle"];
  const group = groups[Math.floor(Math.random() * groups.length)];
  return triggerMotion(group);
}

function triggerMotion(group) {
  if (!live2dModel || !group) return false;
  if (typeof live2dModel.motion === "function") {
    live2dModel.motion(group);
    return true;
  }
  const internal = live2dModel.internalModel;
  if (internal && internal.motionManager && typeof internal.motionManager.startMotion === "function") {
    internal.motionManager.startMotion(group);
    return true;
  }
  return false;
}

function triggerMotionByMessage(text) {
  if (!text) return;
  if (text.includes("加油")) {
    triggerMotion("Tap");
  } else if (text.includes("困")) {
    triggerMotion("Idle");
  } else if (text.includes("专心")) {
    triggerMotion("Flick");
  } else if (text.includes("查找资料")) {
    triggerMotion("Tap");
  }
}

async function loadMotionGroups(modelUrl) {
  try {
    const resp = await fetch(modelUrl);
    if (!resp.ok) return;
    const data = await resp.json();
    const motions = data?.FileReferences?.Motions;
    if (motions && typeof motions === "object") {
      const keys = Object.keys(motions);
      if (keys.length > 0) {
        motionGroups = keys;
      }
    }
  } catch (err) {
    console.warn("load motion groups failed:", err);
  }
}

function triggerPlaceholderClick() {
  clickPulseUntil = performance.now() + 350;
}

function setupPetInteraction() {
  const canvas = document.getElementById("canvas");
  if (!canvas) return;

  canvas.addEventListener("click", (event) => {
    if (moveModeEnabled) return;
    if (usePlaceholder) {
      if (isPointerOverPlaceholder(event)) {
        triggerPlaceholderClick();
        createSpark(event.clientX, event.clientY);
      }
      return;
    }
    if (live2dModel && isPointerOverModel(event)) {
      if (triggerRandomMotion()) {
        createSpark(event.clientX, event.clientY);
      }
    }
  });

  canvas.addEventListener("mousemove", (event) => {
    if (moveModeEnabled) return;
    const now = performance.now();
    if (now - lastPettingTime < 800) return;
    if (usePlaceholder) {
      if (isPointerOverPlaceholder(event)) {
        lastPettingTime = now;
        triggerPlaceholderClick();
        createSpark(event.clientX, event.clientY);
      }
      return;
    }
    if (live2dModel && isPointerOverModel(event)) {
      lastPettingTime = now;
      triggerRandomMotion();
      createSpark(event.clientX, event.clientY);
    }
  });
}

function getGlobalPointer(event) {
  return {
    x: window.screenX + event.clientX,
    y: window.screenY + event.clientY,
  };
}

function setupWindowMoveInteraction() {
  document.addEventListener("mousedown", (event) => {
    if (!moveModeEnabled || !backend) return;
    moveDragActive = true;
    const p = getGlobalPointer(event);
    if (typeof backend.startWindowDrag === "function") {
      backend.startWindowDrag(p.x, p.y);
    }
  });

  window.addEventListener("mousemove", (event) => {
    if (!moveModeEnabled || !moveDragActive || !backend) return;
    const p = getGlobalPointer(event);
    if (typeof backend.moveWindowDrag === "function") {
      backend.moveWindowDrag(p.x, p.y);
    }
  });

  window.addEventListener("mouseup", () => {
    if (!moveDragActive) return;
    moveDragActive = false;
    if (backend && typeof backend.endWindowDrag === "function") {
      backend.endWindowDrag();
    }
  });
}

async function tryLoadLive2DModel() {
  const modelUrl = new URL("./model/miku/miku.model3.json", window.location.href).toString();

  try {
    await loadMotionGroups(modelUrl);
    if (!window.Live2DCubismCore) {
      logStatus("未加载 Live2D Core，请放置 live2d.core.min.js");
    }
    if (window.PIXI && window.PIXI.live2d && window.PIXI.live2d.Live2DModel) {
      const canvas = document.getElementById("canvas");
      live2dApp = new window.PIXI.Application({
        view: canvas,
        backgroundAlpha: 0,
        antialias: true,
        autoStart: true,
        resolution: window.devicePixelRatio || 1,
      });
      live2dModel = await window.PIXI.live2d.Live2DModel.from(modelUrl);
      live2dModel.anchor.set(0.5, 0.5);
      live2dApp.stage.addChild(live2dModel);
      positionLive2D();
      applyAnimationSpeed();
      applySettings(settingsState);
      syncSettingsFromBackend();
      window.modelConfig = modelConfig;
      window.applyModelTransform = positionLive2D;
      setupModelInteraction();
      logStatus("已加载 Live2D 模型");
      return true;
    }

    if (typeof window.loadLive2D === "function") {
      window.loadLive2D("canvas", modelUrl);
      logStatus("已加载 Live2D 模型");
      return true;
    }
  } catch (err) {
    console.warn("Live2D load failed:", err);
    logStatus(`模型加载失败：${err}`);
    return false;
  }

  logStatus("未检测到 Live2D SDK，仍使用占位模型");

  return false;
}

async function initLive2D() {
  const loaded = await tryLoadLive2DModel();
  if (loaded) {
    usePlaceholder = false;
    resizeCanvas();
    window.addEventListener("resize", resizeCanvas);
    setMoveMode(false);
    return;
  }

  // Placeholder rendering until Live2D SDK is wired.
  resizeCanvas();
  window.addEventListener("resize", resizeCanvas);
  requestAnimationFrame(animatePlaceholder);
}

function initWebChannel() {
  if (typeof QWebChannel === "undefined") {
    console.warn("QWebChannel not available");
    return;
  }

  new QWebChannel(qt.webChannelTransport, (channel) => {
    backend = channel.objects.backend;

    const initial = backend.getInitialState();
    handleStateUpdate(initial);

    if (pendingWindowDrag !== null) {
      setWindowDragAllowed(pendingWindowDrag);
      pendingWindowDrag = null;
    }

    if (typeof backend.getSettings === "function") {
      backend.getSettings((cfg) => {
        applySettings(cfg);
      });
    }
    syncSettingsFromBackend();

    if (backend.settingsUpdated) {
      backend.settingsUpdated.connect((data) => {
        applySettings(data);
      });
    }
    if (backend.remindersUpdated) {
      backend.remindersUpdated.connect((data) => {
        applySettings(data);
      });
    }

    if (backend.todosUpdated) {
      backend.todosUpdated.connect((items) => {
        todoItems = items || [];
        renderTodoList();
      });
    }

    if (backend.getAISettings) {
      backend.getAISettings((cfg) => {
        applySettings(cfg);
      });
    }

    if (backend.clipboardUpdated) {
      backend.clipboardUpdated.connect((items) => {
        clipboardItems = items || [];
        renderClipboard();
      });
    }

    if (backend.systemInfoUpdated) {
      backend.systemInfoUpdated.connect((info) => {
        lastSystemInfo = info || null;
        renderSystemInfo(info);
        syncMoreInfoPanel();
      });
    }

    if (backend.noteUpdated) {
      backend.noteUpdated.connect((text) => {
        noteState = text || "";
        syncNotePanel();
      });
    }

    if (backend.pomodoroUpdated) {
      backend.pomodoroUpdated.connect((state) => {
        applyPomodoroState(state);
      });
    }

    backend.stateUpdated.connect((state) => {
      handleStateUpdate(state);
      syncMoreInfoPanel();
    });

    backend.aiReply.connect((text) => {
      appendChatMessage("pet", text);
    });

    if (backend.favorUpdated) {
      backend.favorUpdated.connect((value) => {
        settingsState.favor = Number(value);
        syncMoreInfoPanel();
      });
    }

    if (backend.aiTestResult) {
      backend.aiTestResult.connect((result) => {
        const target = document.getElementById("ai-test-result");
        if (!target) return;
        const ok = result?.ok;
        const message = result?.message || "未返回结果";
        target.textContent = ok ? `成功：${message}` : `失败：${message}`;
        lastAiTestStatus = ok ? `成功：${message}` : `失败：${message}`;
        syncMoreInfoPanel();
      });
    }

    if (backend.passiveMessage) {
      backend.passiveMessage.connect((text) => {
        triggerMotionByMessage(text);
        showSpeechBubble(text);
      });
    }

    if (backend.openPanel) {
      backend.openPanel.connect((name) => {
        if (!name) return;
        toggleToolPanel(name);
        if (name === "note-panel") {
          const textarea = document.getElementById("note-text");
          if (textarea) textarea.focus();
        }
      });
    }

    if (backend.getReminderSettings) {
      backend.getReminderSettings((cfg) => applySettings(cfg));
    }
    if (backend.getTodos) {
      backend.getTodos((items) => {
        todoItems = items || [];
        renderTodoList();
      });
    }

    if (backend.getFavor) {
      backend.getFavor((value) => {
        settingsState.favor = Number(value);
        syncMoreInfoPanel();
      });
    }

    loadNote();
    loadClipboard();
  });
}

function applySettings(data) {
  if (!data) return;
  settingsState = { ...settingsState, ...data };
  modelConfig.scale = Number(settingsState.model_scale);
  modelConfig.x = Number(settingsState.model_x);
  modelConfig.y = Number(settingsState.model_y);
  modelConfig.xOffset = Number(settingsState.model_x_offset);
  modelConfig.yOffset = Number(settingsState.model_y_offset);
  animationSpeed = Number(settingsState.animation_speed) || 1.0;
  document.body.style.setProperty("--ui-scale", String(settingsState.ui_scale || 1));
  positionLive2D();
  if (live2dModel) {
    live2dModel.scale.set(clamp(modelConfig.scale, 0.1, 2.0));
    if (typeof live2dModel.update === "function") {
      live2dModel.update(0);
    }
    logStatus(`应用模型缩放：${modelConfig.scale.toFixed(2)}`);
  }
  applyAnimationSpeed();
  syncSettingsPanel();
  syncPomodoroPanel();
  syncReminderPanel();
  syncAIConfig();
  syncPassivePanel();
  syncMoreInfoPanel();
}

function applyAnimationSpeed() {
  if (live2dApp && live2dApp.ticker) {
    live2dApp.ticker.speed = animationSpeed;
  }
}

function scheduleSaveModelConfig() {
  if (!backend || typeof backend.setModelConfig !== "function") return;
  if (saveTimer) {
    clearTimeout(saveTimer);
  }
  saveTimer = setTimeout(() => {
    backend.setModelConfig({
      scale: modelConfig.scale,
      x: modelConfig.x,
      y: modelConfig.y,
      xOffset: modelConfig.xOffset,
      yOffset: modelConfig.yOffset,
    });
  }, 200);
}

function toggleSettingsPanel(forceOpen = false) {
  const panel = document.getElementById("settings-panel");
  if (!panel) return;
  if (forceOpen) {
    panel.classList.add("visible");
  } else {
    panel.classList.toggle("visible");
  }
  syncSettingsPanel();
}

function syncSettingsPanel() {
  const active = document.getElementById("active-threshold");
  const sleep = document.getElementById("sleep-threshold");
  const opacityRange = document.getElementById("opacity-range");
  const opacityValue = document.getElementById("opacity-value");
  const modelScale = document.getElementById("model-scale");
  const uiScale = document.getElementById("ui-scale");
  const animSpeed = document.getElementById("anim-speed");
  if (active) active.value = Math.round(settingsState.focus_active_ms / 1000);
  if (sleep) sleep.value = Math.round(settingsState.focus_sleep_ms / 1000);
  if (opacityRange) opacityRange.value = settingsState.window_opacity;
  if (opacityValue) opacityValue.value = settingsState.window_opacity;
  if (modelScale) modelScale.value = Number(settingsState.model_scale).toFixed(2);
  if (uiScale) uiScale.value = Number(settingsState.ui_scale).toFixed(2);
  if (animSpeed) animSpeed.value = Number(settingsState.animation_speed).toFixed(1);
}

function setupSettingsPanel() {
  const opacityRange = document.getElementById("opacity-range");
  const opacityValue = document.getElementById("opacity-value");
  const closeBtn = document.getElementById("settings-close");
  const saveBtn = document.getElementById("settings-save");

  if (opacityRange && opacityValue) {
    opacityRange.addEventListener("input", () => {
      opacityValue.value = opacityRange.value;
    });
    opacityValue.addEventListener("input", () => {
      opacityRange.value = opacityValue.value;
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      const panel = document.getElementById("settings-panel");
      if (panel) panel.classList.remove("visible");
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener("click", () => {
      const active = document.getElementById("active-threshold");
      const sleep = document.getElementById("sleep-threshold");
      const opacity = document.getElementById("opacity-value");
      const modelScale = document.getElementById("model-scale");
      const uiScale = document.getElementById("ui-scale");
      const animSpeed = document.getElementById("anim-speed");

      const payload = {
        focus_active_ms: Number(active?.value || 60) * 1000,
        focus_sleep_ms: Number(sleep?.value || 120) * 1000,
        window_opacity: Number(opacity?.value || 100),
        model_scale: Number(modelScale?.value || 0.35),
        ui_scale: Number(uiScale?.value || 1.0),
        animation_speed: Number(animSpeed?.value || 1.0),
      };

      if (backend && typeof backend.setSettings === "function") {
        backend.setSettings(payload);
      }
      applySettings(payload);
      const panel = document.getElementById("settings-panel");
      if (panel) panel.classList.remove("visible");
    });
  }
}

function toggleChatPanelVisibility() {
  const panel = document.getElementById("chat-panel");
  if (!panel) return;
  panel.classList.toggle("hidden");
}

function isChatPanelHidden() {
  const panel = document.getElementById("chat-panel");
  return panel ? panel.classList.contains("hidden") : false;
}

function loadNote() {
  if (!backend || typeof backend.getNote !== "function") return;
  backend.getNote((text) => {
    noteState = text || "";
    syncNotePanel();
  });
}

function syncNotePanel() {
  const textarea = document.getElementById("note-text");
  if (textarea) {
    textarea.value = noteState;
  }
}

function setupNotePanel() {
  const textarea = document.getElementById("note-text");
  if (!textarea) return;
  textarea.addEventListener("input", () => {
    noteState = textarea.value;
    if (noteSaveTimer) {
      clearTimeout(noteSaveTimer);
    }
    noteSaveTimer = setTimeout(() => {
      if (backend && typeof backend.setNote === "function") {
        backend.setNote(noteState);
      }
    }, 300);
  });
}

function loadClipboard() {
  if (!backend || typeof backend.getClipboardHistory !== "function") return;
  backend.getClipboardHistory((items) => {
    clipboardItems = items || [];
    renderClipboard();
  });
}

function renderClipboard() {
  const list = document.getElementById("clipboard-list");
  const search = document.getElementById("clipboard-search");
  if (!list) return;
  const keyword = (search?.value || "").toLowerCase();
  list.innerHTML = "";
  clipboardItems
    .filter((item) => item.text.toLowerCase().includes(keyword))
    .forEach((item) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "clipboard-item";
      row.textContent = item.text.length > 80 ? `${item.text.slice(0, 80)}...` : item.text;
      row.title = item.text;
      row.addEventListener("click", () => {
        if (backend && typeof backend.setClipboardText === "function") {
          backend.setClipboardText(item.text);
          logStatus("已复制到剪贴板");
        }
      });
      list.appendChild(row);
    });
}

function setupClipboardPanel() {
  const search = document.getElementById("clipboard-search");
  const clearBtn = document.getElementById("clipboard-clear");
  if (search) {
    search.addEventListener("input", () => {
      renderClipboard();
    });
  }
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      if (backend && typeof backend.clearClipboard === "function") {
        backend.clearClipboard();
      }
    });
  }
}

function renderSystemInfo(info) {
  if (!info) return;
  const cpu = document.getElementById("sys-cpu");
  const mem = document.getElementById("sys-mem");
  const net = document.getElementById("sys-net");
  const battery = document.getElementById("sys-battery");
  if (cpu) cpu.textContent = info.cpu == null ? "-" : `${info.cpu.toFixed(0)}%`;
  if (mem) mem.textContent = info.memory == null ? "-" : `${info.memory.toFixed(0)}%`;
  const up = info.net_up == null ? "-" : formatSpeed(info.net_up);
  const down = info.net_down == null ? "-" : formatSpeed(info.net_down);
  if (net) net.textContent = `${down} / ${up}`;
  if (battery) battery.textContent = info.battery == null ? "-" : `${info.battery}%`;
}

function formatSpeed(bytes) {
  if (bytes == null) return "-";
  if (bytes < 1024) return `${bytes} B/s`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB/s`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB/s`;
}

function syncSettingsFromBackend(retries = 5) {
  if (!backend || typeof backend.getSettings !== "function") {
    if (retries > 0) {
      clearTimeout(settingsSyncTimer);
      settingsSyncTimer = setTimeout(() => syncSettingsFromBackend(retries - 1), 500);
    }
    return;
  }
  backend.getSettings((cfg) => {
    applySettings(cfg);
  });
}

setupContextMenu();
setupEnterSend();
setupChatPanelBehavior();
setupSettingsPanel();
setupNotePanel();
setupClipboardPanel();
setupToolsPanel();
setupPomodoroPanel();
setupReminderPanel();
setupTodoPanel();
setupAIConfigPanel();
setupPassivePanel();
setupGiftButton();
setupFavorReset();
setupQuickToolbar();
setupPanelCloseButtons();
setupPanelDrag();
setupWindowMoveInteraction();
initLive2D();
initWebChannel();
setupPetInteraction();

