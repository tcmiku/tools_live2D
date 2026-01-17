let backend = null;
let currentState = { status: "idle" };
let canvasCtx = null;
let canvasSize = { width: 0, height: 0 };
let usePlaceholder = true;
let live2dApp = null;
let live2dModel = null;
let animationSpeed = 1.0;
let motionGroups = ["Tap", "Flick", "Flick3", "Idle"];
let expressionNames = [];
const bindingCategories = {
  mood: ["开心", "愉快", "平静", "低落", "孤独"],
  status: ["active", "idle", "sleep", "paused"],
  pomodoro: ["focus", "break", "completed"],
  ai: ["greeting", "cheer", "reminder", "farewell"],
  interaction: ["click", "petting", "drag"],
};
let bindingState = {
  model_path: "",
  name: "",
  bindings: {},
  default: { motion: "Idle", expression: null },
};
let bindingActiveCategory = "mood";
let bindingSelectedKey = null;
let bindingLoopTimer = null;
let presetState = {};
let modelLoadSeq = 0;
let modelLoading = false;
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
  model_edit_mode: false,
  model_path: "model/miku/miku.model3.json",
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
  local_location: "",
  favor: 50,
  mood: 60,
  hotkey_chat_toggle: "Ctrl+H",
};
let moodState = { score: 60, label: "平静", emoji: "😐" };
let noteState = "";
let clipboardItems = [];
let pomodoroState = null;
let todoItems = [];
let launcherData = { launchers: [], recent: [] };
let pluginData = [];
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
let modelEditModeEnabled = false;
let modelDragState = {
  active: false,
  startX: 0,
  startY: 0,
  startXOffset: 0,
  startYOffset: 0,
};
let modelOptions = [];
let currentModelIndex = 0;

function appendChatMessage(who, text) {
  const box = document.getElementById("chat-box");
  const msg = document.createElement("div");
  msg.className = `msg ${who}`;
  msg.textContent = text;
  box.appendChild(msg);
  box.scrollTop = box.scrollHeight;
}

function getBindingValue(category, key) {
  const cat = bindingState.bindings?.[category];
  if (cat && typeof cat === "object" && cat[key]) {
    return cat[key];
  }
  return { motion: null, expression: null };
}

function updateBindingModelName() {
  const badge = document.getElementById("binding-model-name");
  if (!badge) return;
  badge.textContent = bindingState.name || "-";
}

function renderBindingGrid() {
  const grid = document.getElementById("binding-grid");
  if (!grid) return;
  const keys = bindingCategories[bindingActiveCategory] || [];
  const motions = ["", ...motionGroups];
  const expressions = ["", ...expressionNames];
  grid.innerHTML = "";
  keys.forEach((key) => {
    const binding = getBindingValue(bindingActiveCategory, key);
    const row = document.createElement("div");
    row.className = "binding-row";
    if (bindingSelectedKey === key) {
      row.classList.add("active");
    }
    const label = document.createElement("label");
    label.textContent = key;
    const motionSelect = document.createElement("select");
    motions.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name || "无动作";
      if ((binding.motion || "") === name) opt.selected = true;
      motionSelect.appendChild(opt);
    });
    const exprSelect = document.createElement("select");
    expressions.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name || "无表情";
      if ((binding.expression || "") === name) opt.selected = true;
      exprSelect.appendChild(opt);
    });
    motionSelect.addEventListener("change", () => {
      saveBinding(bindingActiveCategory, key, motionSelect.value, exprSelect.value);
    });
    exprSelect.addEventListener("change", () => {
      saveBinding(bindingActiveCategory, key, motionSelect.value, exprSelect.value);
    });
    row.addEventListener("click", () => {
      bindingSelectedKey = key;
      renderBindingGrid();
    });
    row.appendChild(label);
    row.appendChild(motionSelect);
    row.appendChild(exprSelect);
    grid.appendChild(row);
  });
}

function syncBindingPanel() {
  updateBindingModelName();
  renderBindingGrid();
}

function saveBinding(category, key, motion, expression) {
  if (!bindingState.model_path || !backend || typeof backend.setBinding !== "function") return;
  backend.setBinding(bindingState.model_path, category, key, motion, expression);
}

function syncBindingsFromBackend() {
  if (!backend || typeof backend.getModelBindings !== "function") return;
  const modelPath = settingsState.model_path || "";
  if (!modelPath) return;
  backend.getModelBindings(modelPath, (data) => {
    if (!data) return;
    bindingState = data;
    bindingState.model_path = modelPath;
    syncBindingPanel();
  });
  refreshPresetList();
}

function refreshPresetList() {
  if (!backend || typeof backend.getAvailablePresets !== "function") return;
  backend.getAvailablePresets((data) => {
    presetState = data || {};
  });
}

function openPresetDialog() {
  const dialog = document.getElementById("preset-dialog");
  const list = document.getElementById("preset-list");
  if (!dialog || !list) return;
  list.innerHTML = "";
  Object.keys(presetState || {}).forEach((name) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = presetState[name]?.name || name;
    btn.addEventListener("click", () => {
      if (backend && typeof backend.applyPreset === "function") {
        backend.applyPreset(bindingState.model_path || "", name);
      }
      dialog.style.display = "none";
    });
    list.appendChild(btn);
  });
  dialog.style.display = "flex";
  dialog.addEventListener(
    "click",
    (event) => {
      if (event.target === dialog) {
        dialog.style.display = "none";
      }
    },
    { once: true }
  );
}

function exportPreset() {
  if (!backend || typeof backend.exportPreset !== "function") return;
  backend.exportPreset(bindingState.model_path || "", (data) => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${bindingState.name || "preset"}.preset.json`;
    link.click();
    URL.revokeObjectURL(url);
  });
}

function previewBinding(selectedKey) {
  if (!backend || typeof backend.previewBinding !== "function") return;
  const key = selectedKey || bindingSelectedKey || (bindingCategories[bindingActiveCategory] || [])[0];
  if (!key) return;
  backend.previewBinding(bindingState.model_path || "", bindingActiveCategory, key);
}

function triggerBinding(category, key) {
  const binding = getBindingValue(category, key);
  if (!binding) return;
  if (binding.motion) {
    triggerMotion(binding.motion);
  }
  if (binding.expression) {
    triggerExpression(binding.expression);
  }
}

function setupBindingPanel() {
  const panel = document.getElementById("binding-panel");
  if (!panel) return;
  panel.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      panel.querySelectorAll(".tab").forEach((el) => el.classList.remove("active"));
      tab.classList.add("active");
      bindingActiveCategory = tab.getAttribute("data-tab") || "mood";
      renderBindingGrid();
    });
  });
  const previewBtn = document.getElementById("preview-btn");
  const loopBtn = document.getElementById("loop-btn");
  const stopBtn = document.getElementById("stop-btn");
  const applyBtn = document.getElementById("apply-preset-btn");
  const savePresetBtn = document.getElementById("save-preset-btn");
  const exportBtn = document.getElementById("export-btn");
  const resetBtn = document.getElementById("reset-btn");
  const desktopBtn = document.getElementById("open-desktop-binding");
  if (previewBtn) previewBtn.addEventListener("click", () => previewBinding());
  if (loopBtn) {
    loopBtn.addEventListener("click", () => {
      if (bindingLoopTimer) return;
      previewBinding();
      bindingLoopTimer = setInterval(() => previewBinding(), 1500);
    });
  }
  if (stopBtn) {
    stopBtn.addEventListener("click", () => {
      if (bindingLoopTimer) {
        clearInterval(bindingLoopTimer);
        bindingLoopTimer = null;
      }
    });
  }
  if (desktopBtn) {
    desktopBtn.addEventListener("click", () => {
      if (backend && typeof backend.openBindingDialog === "function") {
        backend.openBindingDialog();
      }
    });
  }
  if (applyBtn) applyBtn.addEventListener("click", () => openPresetDialog());
  if (savePresetBtn) {
    savePresetBtn.addEventListener("click", () => {
      if (!backend || typeof backend.savePreset !== "function") return;
      const name = window.prompt("预设名称", bindingState.name || "新预设");
      if (!name) return;
      backend.savePreset(bindingState.model_path || "", name.trim());
      refreshPresetList();
    });
  }
  if (exportBtn) exportBtn.addEventListener("click", () => exportPreset());
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      if (backend && typeof backend.resetModelBindings === "function") {
        backend.resetModelBindings(bindingState.model_path || "");
      }
    });
  }
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

function updateMoodEmoji() {
  const badge = document.getElementById("mood-emoji");
  if (!badge) return;
  badge.textContent = moodState.emoji || "";
  badge.style.opacity = moodState.emoji ? "0.9" : "0";
  badge.title = `${moodState.label} ${moodState.score}`;
}

function logStatus(text) {
  appendChatMessage("pet", text);
}

function handleStateUpdate(state) {
  if (!state) return;
  currentState = state;
  if (state.mood != null) {
    moodState.score = Number(state.mood);
  }
  if (state.mood_label) {
    moodState.label = state.mood_label;
  }
  if (state.mood_emoji) {
    moodState.emoji = state.mood_emoji;
  }
  updateMoodEmoji();
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

function updateModelEditToggle() {
  const button = document.getElementById("model-edit-toggle");
  if (!button) return;
  const enabled = Boolean(settingsState.model_edit_mode);
  button.textContent = enabled ? "关闭" : "开启";
  button.classList.toggle("active", enabled);
}

function getModelPath() {
  return settingsState.model_path || "model/miku/miku.model3.json";
}

function getModelUrl(path) {
  return new URL(path, window.location.href).toString();
}

function updateModelSwitchButton() {
  const button = document.getElementById("tool-model-switch");
  if (!button) return;
  const hasOptions = modelOptions.length > 1;
  button.disabled = !hasOptions || modelLoading;
  if (modelOptions.length > 0) {
    const current = modelOptions[currentModelIndex] || modelOptions[0];
    button.title = current ? `当前模型：${current.name || current.path}` : "切换模型";
  } else {
    button.title = "切换模型";
  }
}

function setModelOptions(list) {
  modelOptions = Array.isArray(list) ? list : [];
  if (modelOptions.length === 0) {
    modelOptions = [{ name: "默认模型", path: getModelPath() }];
  }
  const path = getModelPath();
  const matchIndex = modelOptions.findIndex((item) => item.path === path);
  currentModelIndex = matchIndex >= 0 ? matchIndex : 0;
  updateModelSwitchButton();
}

function syncModelOptionsFromBackend() {
  if (!backend || typeof backend.getAvailableModels !== "function") {
    setModelOptions([]);
    return;
  }
  backend.getAvailableModels((list) => {
    console.log("available models:", Array.isArray(list) ? list.length : 0);
    setModelOptions(list || []);
  });
}

async function switchModel() {
  if (modelLoading) return;
  if (modelOptions.length <= 1) {
    logStatus("没有可切换的模型");
    return;
  }
  const nextIndex = (currentModelIndex + 1) % modelOptions.length;
  const nextModel = modelOptions[nextIndex];
  if (!nextModel?.path) return;
  const ok = await loadLive2DModelFromUrl(getModelUrl(nextModel.path));
  if (!ok) {
    logStatus("模型切换失败");
    return;
  }
  currentModelIndex = nextIndex;
  settingsState.model_path = nextModel.path;
  if (backend && typeof backend.setSettings === "function") {
    backend.setSettings({ model_path: nextModel.path });
  }
  applySettings({ model_path: nextModel.path });
  updateModelSwitchButton();
  logStatus(`切换模型：${nextModel.name || nextModel.path}`);
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
  const bindingsItem = document.getElementById("context-bindings");
  const pluginsItem = document.getElementById("context-plugins");
  if (!menu || !settingsItem || !chatToggle || !toolsItem || !pomoItem || !reminderItem || !aiItem || !passiveItem || !moreInfoItem || !bindingsItem || !pluginsItem) return;

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

  bindingsItem.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.classList.remove("visible");
    toggleToolPanel("binding-panel");
  });

  pluginsItem.addEventListener("click", (event) => {
    event.stopPropagation();
    menu.classList.remove("visible");
    toggleToolPanel("plugin-panel");
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

function closeAllPanels() {
  const panelIds = [
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
    "binding-panel",
    "launcher-panel",
    "plugin-panel",
  ];
  panelIds.forEach((panelId) => {
    const panel = document.getElementById(panelId);
    if (panel) panel.classList.remove("visible");
  });
  const menu = document.getElementById("context-menu");
  if (menu) menu.classList.remove("visible");
  setPanelCollapsed(true);
}

function setupGlobalShortcuts() {
  document.addEventListener("keydown", (event) => {
    const chatHotkey = settingsState.hotkey_chat_toggle || "Ctrl+H";
    if (matchesHotkey(event, chatHotkey)) {
      event.preventDefault();
      toggleChatPanelVisibility();
      return;
    }
    if (event.key !== "Escape") return;
    event.preventDefault();
    closeAllPanels();
  });
}

function matchesHotkey(event, hotkeyText) {
  if (!hotkeyText) return false;
  const parts = String(hotkeyText)
    .split("+")
    .map((part) => part.trim())
    .filter(Boolean);
  if (!parts.length) return false;
  const expected = { ctrl: false, shift: false, alt: false, meta: false, key: "" };
  parts.forEach((part) => {
    const lower = part.toLowerCase();
    if (lower === "ctrl" || lower === "control") {
      expected.ctrl = true;
    } else if (lower === "shift") {
      expected.shift = true;
    } else if (lower === "alt") {
      expected.alt = true;
    } else if (lower === "meta" || lower === "win" || lower === "cmd" || lower === "command") {
      expected.meta = true;
    } else {
      expected.key = part;
    }
  });
  if (!expected.key) return false;
  if (event.ctrlKey !== expected.ctrl) return false;
  if (event.shiftKey !== expected.shift) return false;
  if (event.altKey !== expected.alt) return false;
  if (event.metaKey !== expected.meta) return false;
  const key = event.key || "";
  if (expected.key.toLowerCase() === "space") {
    return key === " " || event.code === "Space";
  }
  return key.toLowerCase() === expected.key.toLowerCase();
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
    "binding-panel",
    "launcher-panel",
    "plugin-panel",
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
  if (id === "launcher-panel") {
    loadLaunchers();
  }
  if (id === "plugin-panel") {
    loadPlugins();
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
  const modelSwitchBtn = document.getElementById("tool-model-switch");
  const launcherBtn = document.getElementById("tool-launcher");
  const bindingBtn = document.getElementById("tool-bindings");
  const pluginBtn = document.getElementById("tool-plugins");
  if (launcherBtn) {
    launcherBtn.innerHTML = '<span class="tool-icon">&#x1F5A5;</span>启动器';
  }
  if (noteBtn) {
    noteBtn.addEventListener("click", () => toggleToolPanel("note-panel"));
  }
  if (clipboardBtn) {
    clipboardBtn.addEventListener("click", () => toggleToolPanel("clipboard-panel"));
  }
  if (sysBtn) {
    sysBtn.addEventListener("click", () => toggleToolPanel("sysinfo-panel"));
  }
  if (modelSwitchBtn) {
    modelSwitchBtn.addEventListener("click", () => {
      switchModel();
    });
  }
  if (launcherBtn) {
    launcherBtn.addEventListener("click", () => toggleToolPanel("launcher-panel"));
  }
  if (bindingBtn) {
    bindingBtn.addEventListener("click", () => toggleToolPanel("binding-panel"));
  }
  if (pluginBtn) {
    pluginBtn.addEventListener("click", () => toggleToolPanel("plugin-panel"));
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
      if (backend && typeof backend.openTodoDialog === "function") {
        backend.openTodoDialog();
      }
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
  const modelBtn = document.getElementById("quick-model");
  const launcherBtn = document.getElementById("quick-launcher");
  const settingsBtn = document.getElementById("quick-settings");
  const collapseBtn = document.getElementById("quick-collapse");

  if (collapseBtn) {
    collapseBtn.addEventListener("click", () => {
      toolbar.classList.toggle("collapsed");
      collapseBtn.textContent = toolbar.classList.contains("collapsed") ? "\u25C0" : "\u25B6";
    });
    collapseBtn.textContent = toolbar.classList.contains("collapsed") ? "\u25C0" : "\u25B6";
  }

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
  if (modelBtn) {
    modelBtn.addEventListener("click", () => switchModel());
  }
  if (launcherBtn) {
    launcherBtn.addEventListener("click", () => toggleToolPanel("launcher-panel"));
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

function setupBackupRestore() {
  const backupBtn = document.getElementById("backup-btn");
  const restoreBtn = document.getElementById("restore-btn");
  if (backupBtn) {
    backupBtn.addEventListener("click", () => {
      if (backend && typeof backend.openBackupDialog === "function") {
        backend.openBackupDialog();
      }
    });
  }
  if (restoreBtn) {
    restoreBtn.addEventListener("click", () => {
      if (backend && typeof backend.restoreBackup === "function") {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".zip";
        input.onchange = () => {
          const file = input.files?.[0];
          if (!file) return;
          backend.restoreBackup(file.path || "");
        };
        input.click();
      }
    });
  }
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
  const mood = document.getElementById("info-mood");
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
  if (mood) mood.textContent = `${moodState.emoji} ${moodState.label} ${moodState.score}`;
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
  const x = width * modelConfig.x + modelConfig.xOffset;
  const y = height * modelConfig.y + modelConfig.yOffset + Math.sin(t / 600) * 6;
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
  live2dModel.position.set(
    live2dApp.renderer.width * modelConfig.x + modelConfig.xOffset,
    live2dApp.renderer.height * modelConfig.y + modelConfig.yOffset
  );
  applyModelScale();
  updateSpeechBubblePosition();
}

function applyModelScale() {
  if (!live2dModel) return;
  const scale = clamp(modelConfig.scale, 0.1, 2.0);
  live2dModel.scale.set(scale);
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
    // 编辑模式下的拖动由 setupModelEditMode 处理
    if (modelEditModeEnabled || moveModeEnabled) {
      return;
    }
    setDragBlocker("model", isPointerOverModel(event));
  });

  window.addEventListener("mouseup", () => {
    setDragBlocker("model", false);
  });
}

function setupModelEditMode() {
  const canvas = document.getElementById("canvas");
  if (!canvas) return;

  canvas.addEventListener("wheel", (event) => {
    if (!modelEditModeEnabled) return;

    event.preventDefault();

    if (usePlaceholder) {
      const delta = event.deltaY > 0 ? -0.02 : 0.02;
      const rect = canvas.getBoundingClientRect();
      const currentScale = (settingsState.model_scale || 0.35);
      const newScale = clamp(currentScale + delta, 0.1, 2.0);
      settingsState.model_scale = newScale;
      applySettings({ model_scale: newScale });
    } else if (live2dModel) {
      const delta = event.deltaY > 0 ? -0.02 : 0.02;
      modelConfig.scale = clamp(modelConfig.scale + delta, 0.1, 2.0);
      settingsState.model_scale = modelConfig.scale;
      applyModelScale();
      scheduleSaveModelConfig();
      logStatus(`模型缩放：${modelConfig.scale.toFixed(2)}`);
    }
  }, { passive: false });

  canvas.addEventListener("mousedown", (event) => {
    if (!modelEditModeEnabled || event.button !== 0) return;

    if (isPointerOverPlaceholder(event) || isPointerOverModel(event)) {
      modelDragState.active = true;
      modelDragState.startX = event.clientX;
      modelDragState.startY = event.clientY;
      modelDragState.startXOffset = modelConfig.xOffset;
      modelDragState.startYOffset = modelConfig.yOffset;
      event.preventDefault();
      event.stopPropagation();
      triggerBinding("interaction", "drag");
    }
  });

  window.addEventListener("mousemove", (event) => {
    if (!modelEditModeEnabled || !modelDragState.active) return;

    const canvas = document.getElementById("canvas");
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const scaleX = live2dApp ? live2dApp.renderer.width / rect.width : 1;
    const scaleY = live2dApp ? live2dApp.renderer.height / rect.height : 1;

    const deltaX = (event.clientX - modelDragState.startX) * scaleX;
    const deltaY = (event.clientY - modelDragState.startY) * scaleY;

    modelConfig.xOffset = modelDragState.startXOffset + deltaX;
    modelConfig.yOffset = modelDragState.startYOffset + deltaY;

    if (!usePlaceholder && live2dModel) {
      positionLive2D();
    }
  });

  window.addEventListener("mouseup", () => {
    if (modelDragState.active) {
      modelDragState.active = false;
      settingsState.model_x_offset = modelConfig.xOffset;
      settingsState.model_y_offset = modelConfig.yOffset;
      scheduleSaveModelConfig();
    }
  });
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
  if (triggerMotion(group)) {
    return true;
  }
  if (expressionNames.length > 0) {
    const expr = expressionNames[Math.floor(Math.random() * expressionNames.length)];
    return triggerExpression(expr);
  }
  return false;
}

function triggerExpression(name) {
  if (!live2dModel || !name) return false;
  if (typeof live2dModel.expression === "function") {
    live2dModel.expression(name);
    return true;
  }
  const internal = live2dModel.internalModel;
  const manager = internal?.motionManager?.expressionManager;
  if (manager && typeof manager.setExpression === "function") {
    manager.setExpression(name);
    return true;
  }
  return false;
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
      motionGroups = keys.length > 0 ? keys : [];
    } else {
      motionGroups = [];
    }
    const expressions = data?.FileReferences?.Expressions;
    if (Array.isArray(expressions)) {
      expressionNames = expressions
        .map((item) => item?.Name)
        .filter((name) => typeof name === "string" && name.length > 0);
    } else {
      expressionNames = [];
    }
    renderBindingGrid();
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
        triggerBinding("interaction", "click");
      }
      return;
    }
    if (live2dModel && isPointerOverModel(event)) {
      if (triggerRandomMotion()) {
        createSpark(event.clientX, event.clientY);
      }
      triggerBinding("interaction", "click");
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
        triggerBinding("interaction", "petting");
      }
      return;
    }
    if (live2dModel && isPointerOverModel(event)) {
      lastPettingTime = now;
      triggerRandomMotion();
      createSpark(event.clientX, event.clientY);
      triggerBinding("interaction", "petting");
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

async function loadLive2DModelFromUrl(modelUrl) {
  if (!modelUrl) {
    logStatus("模型地址为空，无法加载");
    return false;
  }
  const loadId = ++modelLoadSeq;
  modelLoading = true;
  updateModelSwitchButton();
  try {
    await loadMotionGroups(modelUrl);
    if (!window.Live2DCubismCore) {
      logStatus("未加载Live2D Core，请放置 live2d.core.min.js");
    }
    if (window.PIXI && window.PIXI.live2d && window.PIXI.live2d.Live2DModel) {
      const canvas = document.getElementById("canvas");
      if (!live2dApp) {
        live2dApp = new window.PIXI.Application({
          view: canvas,
          backgroundAlpha: 0,
          antialias: true,
          autoStart: true,
          resolution: window.devicePixelRatio || 1,
        });
      }
      const nextModel = await window.PIXI.live2d.Live2DModel.from(modelUrl);
      if (!nextModel) {
        logStatus("模型加载失败：返回为空");
        modelLoading = false;
        updateModelSwitchButton();
        return false;
      }
      if (loadId !== modelLoadSeq) {
        if (nextModel && typeof nextModel.destroy === "function") {
          nextModel.destroy({ children: true, texture: true, baseTexture: true });
        }
        modelLoading = false;
        updateModelSwitchButton();
        return false;
      }
      const prevModel = live2dModel;
      live2dModel = nextModel;
      live2dModel.anchor.set(0.5, 0.5);
      if (prevModel) {
        live2dApp.stage.removeChild(prevModel);
        if (typeof prevModel.destroy === "function") {
          prevModel.destroy({ children: true, texture: true, baseTexture: true });
        }
      }
      live2dApp.stage.addChild(live2dModel);
      positionLive2D();
      applyAnimationSpeed();
      logStatus("已加载Live2D 模型");
      modelLoading = false;
      updateModelSwitchButton();
      return true;
    }

    if (typeof window.loadLive2D === "function") {
      if (loadId !== modelLoadSeq) {
        modelLoading = false;
        updateModelSwitchButton();
        return false;
      }
      window.loadLive2D("canvas", modelUrl);
      logStatus("已加载Live2D 模型");
      modelLoading = false;
      updateModelSwitchButton();
      return true;
    }
  } catch (err) {
    console.warn("Live2D load failed:", err);
    logStatus(`模型加载失败：${err}`);
    modelLoading = false;
    updateModelSwitchButton();
    return false;
  }

  logStatus("未检测到 Live2D SDK，仍使用占位模型");
  modelLoading = false;
  updateModelSwitchButton();
  return false;
}

async function tryLoadLive2DModel() {

  const modelUrl = getModelUrl(getModelPath());

  const loaded = await loadLive2DModelFromUrl(modelUrl);
  if (loaded) {
    applySettings(settingsState);
    syncSettingsFromBackend();
    window.modelConfig = modelConfig;
    window.applyModelTransform = positionLive2D;
    setupModelInteraction();
  }
  return loaded;
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
      loadLaunchers();

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
    syncModelOptionsFromBackend();

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

    if (backend.modelEditModeChanged) {
      backend.modelEditModeChanged.connect((enabled) => {
        modelEditModeEnabled = Boolean(enabled);
        settingsState.model_edit_mode = modelEditModeEnabled;
        document.body.classList.toggle("model-edit-mode", modelEditModeEnabled);
        setDragBlocker("model", modelEditModeEnabled);
        updateModelEditToggle();
        logStatus(modelEditModeEnabled ? "模型编辑模式已开启，可拖动和滚轮缩放" : "模型编辑模式已关闭");
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

    if (backend.bindingPreview) {
      backend.bindingPreview.connect((motion, expression) => {
        if (motion) {
          triggerMotion(motion);
        }
        if (expression) {
          triggerExpression(expression);
        }
      });
    }
    if (backend.bindingsUpdated) {
      backend.bindingsUpdated.connect((data) => {
        if (!data) return;
        bindingState = data;
        bindingState.model_path = settingsState.model_path || "";
        syncBindingPanel();
      });
    }
    if (backend.launchersUpdated) {
      backend.launchersUpdated.connect((data) => {
        launcherData = data || { launchers: [], recent: [] };
        syncLauncherPanel();
      });
    }
    if (backend.pluginsUpdated) {
      backend.pluginsUpdated.connect((data) => {
        pluginData = data?.plugins || [];
        renderPluginList();
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
    syncBindingsFromBackend();
    loadPlugins();
  });
}

function applySettings(data) {
  if (!data) return;
  const prevModelPath = settingsState.model_path;
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
    applyModelScale();
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
  if (data.model_path !== undefined && data.model_path !== prevModelPath) {
    syncBindingsFromBackend();
  }
  if (data.model_path && data.model_path !== prevModelPath) {
    loadLive2DModelFromUrl(getModelUrl(settingsState.model_path));
    updateModelSwitchButton();
  }
  if (data.model_edit_mode !== undefined) {
    modelEditModeEnabled = Boolean(data.model_edit_mode);
    settingsState.model_edit_mode = modelEditModeEnabled;
    document.body.classList.toggle("model-edit-mode", modelEditModeEnabled);
    setDragBlocker("model", modelEditModeEnabled);
    updateModelEditToggle();
        logStatus(modelEditModeEnabled ? "模型编辑模式已开启，可拖动和滚轮缩放" : "模型编辑模式已关闭");
  }
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
  updateModelEditToggle();
}

function setupSettingsPanel() {
  const opacityRange = document.getElementById("opacity-range");
  const opacityValue = document.getElementById("opacity-value");
  const closeBtn = document.getElementById("settings-close");
  const saveBtn = document.getElementById("settings-save");
  const modelEditToggle = document.getElementById("model-edit-toggle");

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
        model_edit_mode: Boolean(settingsState.model_edit_mode),
      };

      if (backend && typeof backend.setSettings === "function") {
        backend.setSettings(payload);
      }
      applySettings(payload);
      const panel = document.getElementById("settings-panel");
      if (panel) panel.classList.remove("visible");
    });
  }

  if (modelEditToggle) {
    modelEditToggle.addEventListener("click", () => {
      const next = !Boolean(settingsState.model_edit_mode);
      if (backend && typeof backend.setModelEditMode === "function") {
        backend.setModelEditMode(next);
      } else if (backend && typeof backend.setSettings === "function") {
        backend.setSettings({ model_edit_mode: next });
      }
      applySettings({ model_edit_mode: next });
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

function renderLauncherList(container, items) {
  if (!container) return;
  container.innerHTML = "";
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "launcher-item";
    const left = document.createElement("div");
    left.className = "launcher-meta";
    const icon = document.createElement("span");
    icon.className = "launcher-icon";
    icon.textContent = item.icon || "🧩";
    const name = document.createElement("span");
    name.textContent = item.name || "未命名";
    const tags = document.createElement("span");
    tags.className = "launcher-tags";
    tags.textContent = (item.tags || []).join(", ");
    left.appendChild(icon);
    left.appendChild(name);
    if (tags.textContent) left.appendChild(tags);
    const actions = document.createElement("div");
    const runBtn = document.createElement("button");
    runBtn.textContent = "打开";
    runBtn.addEventListener("click", () => executeLauncher(item.id));
    const editBtn = document.createElement("button");
    editBtn.textContent = "编辑";
    editBtn.addEventListener("click", () => editLauncher(item));
    const delBtn = document.createElement("button");
    delBtn.textContent = "删除";
    delBtn.addEventListener("click", () => deleteLauncher(item.id));
    actions.appendChild(runBtn);
    actions.appendChild(editBtn);
    actions.appendChild(delBtn);
    row.appendChild(left);
    row.appendChild(actions);
    container.appendChild(row);
  });
}

function syncLauncherPanel() {
  const recentEl = document.getElementById("launcher-recent");
  const listEl = document.getElementById("launcher-list");
  const recentIds = launcherData.recent || [];
  const lookup = new Map(launcherData.launchers.map((x) => [x.id, x]));
  const recentItems = recentIds.map((id) => lookup.get(id)).filter(Boolean);
  renderLauncherList(recentEl, recentItems);
  renderLauncherList(listEl, launcherData.launchers || []);
}

function loadLaunchers() {
  if (!backend || typeof backend.getLaunchers !== "function") return;
  backend.getLaunchers((data) => {
    launcherData = data || { launchers: [], recent: [] };
    syncLauncherPanel();
  });
}

function searchLaunchers(query) {
  if (!backend || typeof backend.searchLaunchers !== "function") return;
  backend.searchLaunchers(query || "", (data) => {
    launcherData = data || { launchers: [], recent: [] };
    syncLauncherPanel();
  });
}

function executeLauncher(id) {
  if (!backend || typeof backend.executeLauncher !== "function") return;
  backend.executeLauncher(Number(id), (result) => {
    if (result && result.message) logStatus(result.message);
  });
}

function parseLauncherItems(raw) {
  if (!raw) return [];
  const trimmed = raw.trim();
  if (trimmed.startsWith("[")) {
    try {
      return JSON.parse(trimmed);
    } catch (err) {
      return [];
    }
  }
  return trimmed
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean)
    .map((val) => ({ launcher_id: Number(val) }));
}

function editLauncher(item) {
  const name = window.prompt("名称", item?.name || "");
  if (!name) return;
  const type = window.prompt("类型(web/app/group)", item?.type || "web") || "web";
  const url = window.prompt("URL", item?.url || "") || "";
  const path = window.prompt("路径", item?.path || "") || "";
  const args = window.prompt("参数(空格分隔)", (item?.args || []).join(" ")) || "";
  const icon = window.prompt("图标", item?.icon || "") || "";
  const tags = window.prompt("标签(逗号分隔)", (item?.tags || []).join(",")) || "";
  const hotkey = window.prompt("热键", item?.hotkey || "") || "";
  const itemsRaw = type === "group" ? window.prompt("套件内容(launcher_id 列表或 JSON)", "") || "" : "";
  const payload = {
    id: item?.id,
    name,
    type,
    url,
    path,
    args: args ? args.split(" ").filter(Boolean) : [],
    icon,
    tags: tags ? tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
    hotkey,
    items: parseLauncherItems(itemsRaw),
  };
  if (backend && typeof backend.saveLauncher === "function") {
    backend.saveLauncher(payload);
  }
}

function deleteLauncher(id) {
  if (!window.confirm("确定删除该启动项？")) return;
  if (backend && typeof backend.deleteLauncher === "function") {
    backend.deleteLauncher(Number(id));
  }
}

function exportLaunchers() {
  if (!backend || typeof backend.exportLaunchers !== "function") return;
  backend.exportLaunchers((data) => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "launchers.json";
    link.click();
    URL.revokeObjectURL(link.href);
  });
}

function importLaunchers() {
  if (!backend || typeof backend.importLaunchers !== "function") return;
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "application/json";
  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(reader.result || "{}");
        backend.importLaunchers(data);
      } catch (err) {
        logStatus("导入失败");
      }
    };
    reader.readAsText(file);
  });
  input.click();
}

function setupLauncherPanel() {
  const searchInput = document.getElementById("launcher-search");
  const addBtn = document.getElementById("launcher-add");
  const importBtn = document.getElementById("launcher-import");
  const exportBtn = document.getElementById("launcher-export");
  const desktopBtn = document.getElementById("launcher-desktop");
  if (searchInput) {
    searchInput.addEventListener("input", () => searchLaunchers(searchInput.value));
  }
  if (addBtn) addBtn.addEventListener("click", () => editLauncher({}));
  if (importBtn) importBtn.addEventListener("click", () => importLaunchers());
  if (exportBtn) exportBtn.addEventListener("click", () => exportLaunchers());
  if (desktopBtn) {
    desktopBtn.addEventListener("click", () => {
      if (backend && typeof backend.openLauncherDialog === "function") {
        backend.openLauncherDialog();
      }
    });
  }
}

function loadPlugins() {
  if (!backend || typeof backend.getPlugins !== "function") return;
  backend.getPlugins((data) => {
    pluginData = data?.plugins || [];
    renderPluginList();
  });
}

function renderPluginList() {
  const list = document.getElementById("plugin-list");
  if (!list) return;
  list.innerHTML = "";
  (pluginData || []).forEach((item) => {
    const row = document.createElement("div");
    row.className = "plugin-item";

    const head = document.createElement("div");
    head.className = "plugin-row";
    const title = document.createElement("div");
    title.className = "plugin-name";
    title.textContent = item.name || item.id || "plugin";
    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.checked = !!item.enabled;
    toggle.addEventListener("change", () => {
      if (!backend || typeof backend.setPluginEnabled !== "function") return;
      backend.setPluginEnabled(String(item.id || ""), !!toggle.checked);
    });
    head.appendChild(title);
    head.appendChild(toggle);

    const meta = document.createElement("div");
    meta.className = "plugin-meta";
    const version = item.version ? `v${item.version}` : "v0.0.0";
    const status = item.loaded ? "loaded" : "idle";
    meta.textContent = `${item.id || "-"} · ${version} · ${status}`;

    const desc = document.createElement("div");
    desc.className = "plugin-desc";
    desc.textContent = item.description || "No description";

    const actions = document.createElement("div");
    actions.className = "plugin-row";
    const reloadBtn = document.createElement("button");
    reloadBtn.type = "button";
    reloadBtn.textContent = "Reload";
    reloadBtn.addEventListener("click", () => {
      if (!backend || typeof backend.reloadPlugin !== "function") return;
      backend.reloadPlugin(String(item.id || ""));
    });
    actions.appendChild(reloadBtn);

    row.appendChild(head);
    row.appendChild(meta);
    row.appendChild(desc);
    if (item.error) {
      const err = document.createElement("div");
      err.className = "plugin-error";
      err.textContent = item.error;
      row.appendChild(err);
    }
    row.appendChild(actions);
    list.appendChild(row);
  });
}

function setupPluginPanel() {
  const reloadAll = document.getElementById("plugin-reload-all");
  const openFolder = document.getElementById("plugin-open-folder");
  const desktopBtn = document.getElementById("plugin-desktop");
  if (reloadAll) {
    reloadAll.addEventListener("click", () => {
      if (backend && typeof backend.reloadPlugins === "function") {
        backend.reloadPlugins();
      }
    });
  }
  if (openFolder) {
    openFolder.addEventListener("click", () => {
      if (backend && typeof backend.openPluginFolder === "function") {
        backend.openPluginFolder();
      }
    });
  }
  if (desktopBtn) {
    desktopBtn.addEventListener("click", () => {
      if (backend && typeof backend.openPluginDialog === "function") {
        backend.openPluginDialog();
      }
    });
  }
  loadPlugins();
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
  setupLauncherPanel();
  setupPluginPanel();
  setupBindingPanel();
setupPomodoroPanel();
setupReminderPanel();
setupTodoPanel();
setupAIConfigPanel();
setupPassivePanel();
setupGiftButton();
setupFavorReset();
setupBackupRestore();
setupQuickToolbar();
setupPanelCloseButtons();
setupGlobalShortcuts();
setupPanelDrag();
setupWindowMoveInteraction();
initLive2D();
initWebChannel();
setupPetInteraction();
setupModelEditMode();

