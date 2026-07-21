const token = document.querySelector('meta[name="operator-panel-token"]').content;
const state = {
  catalog: null,
  status: null,
  cameraHealth: null,
  activePanel: null,
};
const cameraHealthPollMs = 2000;
const cameraCollapsedStorageKey = 'operator-panel.camera-preview-collapsed';
let renderedTerminalLines = ['Panel ready.'];

function element(tag, attributes = {}, text = '') {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name === 'class') node.className = value;
    else if (name === 'dataset') Object.assign(node.dataset, value);
    else if (name in node) node[name] = value;
    else node.setAttribute(name, value);
  }
  if (text) node.textContent = text;
  return node;
}

async function request(path, options = {}) {
  const response = await fetch(path, { cache: 'no-store', ...options });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed: ${response.status}`);
  return payload;
}

async function post(path, payload) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Operator-Panel-Token': token },
    body: JSON.stringify(payload),
  });
}

function toast(message) {
  const node = document.getElementById('toast');
  node.textContent = message;
  node.classList.add('show');
  window.setTimeout(() => node.classList.remove('show'), 2800);
}

function refreshCameras() {
  document.querySelectorAll('[data-camera-url]').forEach(image => {
    image.src = `${image.dataset.cameraUrl}?panel_refresh=${Date.now()}`;
  });
}

function cameraUrl(camera) {
  if (camera.url) return camera.url;
  if (!Number.isInteger(camera.port) || !camera.path?.startsWith('/')) {
    throw new Error(`Invalid camera endpoint: ${camera.id}`);
  }
  return `${window.location.protocol}//${window.location.hostname}:${camera.port}${camera.path}`;
}

function setCameraPreviewCollapsed(collapsed) {
  const grid = document.getElementById('camera-grid');
  const toggle = document.getElementById('toggle-camera-grid');
  grid.classList.toggle('collapsed', collapsed);
  toggle.textContent = collapsed ? 'Show preview' : 'Collapse preview';
  toggle.setAttribute('aria-expanded', String(!collapsed));
  try { window.localStorage.setItem(cameraCollapsedStorageKey, collapsed ? '1' : '0'); }
  catch (_error) { /* Local storage is optional. */ }
}

function storedCameraPreviewCollapsed() {
  try { return window.localStorage.getItem(cameraCollapsedStorageKey) === '1'; }
  catch (_error) { return false; }
}

function renderProduct() {
  document.getElementById('product-brand').textContent = state.catalog.product.brand;
  document.getElementById('product-title').textContent = state.catalog.product.title;
  document.title = `${state.catalog.product.brand} ${state.catalog.product.title}`;
}

function renderCameras() {
  const section = document.getElementById('camera-section');
  section.classList.toggle('hidden', !state.catalog.cameras.length);
  const grid = document.getElementById('camera-grid');
  grid.replaceChildren(...state.catalog.cameras.map(camera => {
    const streamUrl = cameraUrl(camera);
    const image = element('img', {
      alt: `${camera.label} camera stream`,
      loading: 'eager',
    });
    image.dataset.cameraUrl = streamUrl;
    const figure = element('figure', {
      class: 'camera-frame',
      dataset: { cameraId: camera.id, cameraHealth: 'checking' },
    });
    const caption = element('figcaption');
    caption.append(
      element('span', { class: 'camera-name' }, camera.label),
      element('span', {
        class: 'camera-status',
        dataset: { cameraStatus: camera.id },
      }, 'Checking…'),
    );
    figure.append(image, caption);
    return figure;
  }));
  const controls = document.getElementById('camera-controls');
  controls.replaceChildren(...state.catalog.camera_controls.map(control => {
    const classes = ['quiet', control.tone === 'danger' ? 'danger' : '']
      .filter(Boolean)
      .join(' ');
    const button = element('button', { type: 'button', class: classes }, control.label);
    button.dataset.panelAction = control.workflow;
    button.addEventListener('click', async () => {
      if (control.confirm && !window.confirm(control.confirm)) return;
      try {
        await startWorkflow(control.workflow, control.values);
        window.setTimeout(refreshCameras, 1000);
      } catch (error) { toast(error.message); }
    });
    return button;
  }));
  setCameraPreviewCollapsed(storedCameraPreviewCollapsed());
  renderCameraHealth();
  refreshCameras();
}

function renderCameraHealth() {
  if (!state.catalog) return;
  const cameras = state.catalog.cameras;
  const health = state.cameraHealth;
  let liveCount = 0;
  for (const camera of cameras) {
    const figure = document.querySelector(`[data-camera-id="${camera.id}"]`);
    const status = document.querySelector(`[data-camera-status="${camera.id}"]`);
    if (!figure || !status) continue;
    const stream = health?.streams?.[camera.id];
    let mode = 'offline';
    let text = 'Monitor offline';
    if (!health) {
      mode = 'checking';
      text = 'Checking…';
    } else if (health.available && stream?.error) {
      mode = 'error';
      text = 'Stream error';
    } else if (health.available && !stream) {
      mode = 'error';
      text = 'Status unavailable';
    } else if (health.available && stream && !stream.ready) {
      mode = 'waiting';
      text = 'Waiting for frames';
    } else if (health.available && stream?.ready && !stream.fresh) {
      mode = 'stale';
      text = stream.age_s == null ? 'Stale' : `Stale · ${formatFrameAge(stream.age_s)}`;
    } else if (health.available && stream?.ready && stream.fresh) {
      mode = 'live';
      liveCount += 1;
      const fps = Number.isFinite(stream.preview_fps)
        ? `${stream.preview_fps.toFixed(1)} fps`
        : 'Live';
      text = stream.age_s == null ? fps : `${fps} · ${formatFrameAge(stream.age_s)}`;
    }
    figure.dataset.cameraHealth = mode;
    status.textContent = text;
    status.title = stream?.error || text;
  }

  const summary = document.getElementById('camera-summary');
  if (!health) summary.textContent = 'Checking camera monitor…';
  else if (!health.available) summary.textContent = health.reason || 'Camera monitor offline';
  else summary.textContent = `${liveCount}/${cameras.length} live · read-only preview`;
}

function formatFrameAge(ageSeconds) {
  if (ageSeconds < 1) return `${Math.round(ageSeconds * 1000)} ms`;
  return `${ageSeconds.toFixed(1)} s`;
}

async function pollCameraHealth() {
  if (!state.catalog?.cameras.length) return;
  try {
    state.cameraHealth = await request('/api/camera-health');
  } catch (_error) {
    state.cameraHealth = {
      available: false,
      ok: false,
      streams: {},
      reason: 'Camera health unavailable',
    };
  }
  renderCameraHealth();
}

function fieldControl(field) {
  if (field.type === 'checkbox') {
    const input = element('input', { type: 'checkbox', name: field.name });
    input.checked = Boolean(field.default);
    const label = element('label', { class: 'check' });
    label.append(input, document.createTextNode(field.label));
    return label;
  }

  let control;
  if (field.type === 'select') {
    control = element('select', { name: field.name, required: field.required !== false });
  } else {
    control = element('input', {
      type: 'text',
      name: field.name,
      required: field.required !== false,
      placeholder: field.placeholder || '',
      value: field.default || '',
    });
  }
  const label = element('label', {}, field.label);
  label.append(control);
  return label;
}

function updateSelects(form, workflow) {
  for (const field of workflow.fields.filter(item => item.type === 'select')) {
    const select = form.elements.namedItem(field.name);
    const previous = select.value || field.default || '';
    const dependency = field.depends_on
      ? form.elements.namedItem(field.depends_on).value
      : null;
    const options = field.options.filter(item => (
      !field.depends_on || item.depends_value === dependency
    ));
    select.replaceChildren(...options.map(item => element('option', {
      value: item.value,
      selected: item.value === previous,
    }, item.label)));
    if (![...select.options].some(item => item.value === select.value) && select.options.length) {
      select.selectedIndex = 0;
    }
  }
}

function workflowValues(form, workflow) {
  return Object.fromEntries(workflow.fields.map(field => {
    const control = form.elements.namedItem(field.name);
    return [field.name, field.type === 'checkbox' ? control.checked : control.value];
  }));
}

function configureDerivedFields(form, definition) {
  for (const field of definition.fields.filter(item => item.derive_from)) {
    const source = form.elements.namedItem(field.derive_from);
    const target = form.elements.namedItem(field.name);
    if (!source || !target || field.transform !== 'snake_case') continue;
    source.addEventListener('input', () => {
      if (target.value && target.value !== target.dataset.derivedValue) return;
      const derived = source.value
        .normalize('NFKD')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '');
      target.value = derived;
      target.dataset.derivedValue = derived;
    });
  }
}

function renderWorkflows() {
  const tabs = document.getElementById('workflow-tabs');
  const panels = document.getElementById('workflow-panels');
  tabs.replaceChildren();
  panels.replaceChildren();

  const forms = [
    ...state.catalog.workflows.map(item => ({ ...item, operation: 'workflow' })),
    ...(state.catalog.registrations || []).map(item => ({
      ...item, operation: 'registration',
    })),
  ];
  for (const workflow of forms) {
    const tab = element('button', {
      type: 'button',
      class: 'tab',
      id: `tab-${workflow.id}`,
      role: 'tab',
      'aria-controls': `workflow-${workflow.id}`,
    }, workflow.label);
    tab.dataset.panel = workflow.id;
    tabs.append(tab);

    const form = element('form', {
      class: 'workflow-panel',
      id: `workflow-${workflow.id}`,
      role: 'tabpanel',
      'aria-labelledby': `tab-${workflow.id}`,
    });
    const heading = element('div', { class: 'workflow-heading' });
    heading.append(
      element('p', { class: 'eyebrow' }, workflow.eyebrow),
      element('h2', {}, workflow.title),
      ...(workflow.description
        ? [element('p', { class: 'workflow-description' }, workflow.description)]
        : []),
    );
    form.append(
      heading,
      ...workflow.fields.map(fieldControl),
    );
    configureDerivedFields(form, workflow);
    const submitClasses = ['primary', workflow.tone === 'danger' ? 'danger' : '']
      .filter(Boolean)
      .join(' ');
    const submit = element('button', {
      type: 'submit',
      class: submitClasses,
    }, workflow.submit_label);
    submit.dataset.panelAction = workflow.id;
    form.append(submit);
    form.querySelectorAll('select').forEach(select => {
      select.addEventListener('change', () => updateSelects(form, workflow));
    });
    updateSelects(form, workflow);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (workflow.confirm && !window.confirm(workflow.confirm)) return;
      try {
        if (workflow.operation === 'registration') {
          await register(workflow.id, workflowValues(form, workflow));
        } else {
          await startWorkflow(workflow.id, workflowValues(form, workflow));
        }
      }
      catch (error) { toast(error.message); }
    });
    panels.append(form);
  }

  if (state.catalog.config_types.length) {
    const tab = element('button', {
      type: 'button',
      class: 'tab',
      id: 'tab-configuration',
      role: 'tab',
      'aria-controls': 'configuration-panel',
    }, 'Configurations');
    tab.dataset.panel = 'configuration';
    tabs.append(tab);
    const panel = document.getElementById('configuration-panel');
    panel.setAttribute('aria-labelledby', 'tab-configuration');
  }
  tabs.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => activatePanel(tab.dataset.panel));
    tab.addEventListener('keydown', event => moveTabFocus(event, tabs));
  });
  const defaultPanel = state.catalog.workflows[0]?.id
    || (state.catalog.config_types.length ? 'configuration' : null);
  if (defaultPanel) activatePanel(state.activePanel || defaultPanel);
}

async function register(registration, values) {
  const result = await post('/api/register', { registration, values });
  state.catalog = result.catalog;
  state.activePanel = result.activate?.panel || state.activePanel;
  renderCatalog();
  const activation = result.activate;
  if (activation?.panel && activation.values) {
    const form = document.getElementById(`workflow-${activation.panel}`);
    for (const [name, value] of Object.entries(activation.values)) {
      const control = form?.elements.namedItem(name);
      if (!control) continue;
      control.value = value;
      control.dispatchEvent(new Event('change'));
    }
  }
  toast(`Registered: ${result.created}`);
}

function activatePanel(panelId) {
  state.activePanel = panelId;
  document.querySelectorAll('.tab').forEach(tab => {
    const active = tab.dataset.panel === panelId;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll('.workflow-panel').forEach(panel => {
    const expected = panelId === 'configuration' ? 'configuration-panel' : `workflow-${panelId}`;
    const active = panel.id === expected;
    panel.classList.toggle('active', active);
    panel.hidden = !active;
  });
}

function moveTabFocus(event, tabs) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  const items = [...tabs.querySelectorAll('.tab')];
  const current = items.indexOf(event.currentTarget);
  let next = current;
  if (event.key === 'ArrowLeft') next = (current - 1 + items.length) % items.length;
  if (event.key === 'ArrowRight') next = (current + 1) % items.length;
  if (event.key === 'Home') next = 0;
  if (event.key === 'End') next = items.length - 1;
  event.preventDefault();
  activatePanel(items[next].dataset.panel);
  items[next].focus();
}

function renderConfigurationEditor() {
  const kind = document.getElementById('config-kind');
  kind.replaceChildren(...state.catalog.config_types.map(item => (
    element('option', { value: item.id }, item.label)
  )));
  updateConfigTemplates();
}

function updateConfigTemplates() {
  const kindId = document.getElementById('config-kind').value;
  const definition = state.catalog.config_types.find(item => item.id === kindId);
  const template = document.getElementById('config-template');
  template.replaceChildren(...(definition ? definition.templates : []).map(item => (
    element('option', { value: item.value }, item.label)
  )));
}

async function startWorkflow(workflow, values) {
  state.status = await post('/api/start', { workflow, values });
  renderStatus();
}

const terminalToneByLevel = {
  INFO: 'info',
  STEP: 'step',
  PASS: 'pass',
  WARN: 'warn',
  FAIL: 'fail',
  RUN: 'run',
  PANEL: 'panel',
  CLEANUP: 'cleanup',
};

function terminalLine(value) {
  const text = String(value).replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, '');
  const line = element('span', { class: 'terminal-line' });
  const match = text.match(/^(\s*)\[([A-Z]+)\](.*)$/);
  const tone = match && terminalToneByLevel[match[2]];
  if (!tone) {
    line.textContent = text;
    return line;
  }
  line.append(
    document.createTextNode(match[1]),
    element('span', { class: `terminal-label terminal-${tone}` }, `[${match[2]}]`),
    document.createTextNode(match[3]),
  );
  return line;
}

function progressValue(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function renderProgress(status) {
  const container = document.getElementById('session-progress');
  const items = Array.isArray(status.progress) ? status.progress : [];
  const rows = items.map(item => {
    const row = element('div', { class: 'progress-item' });
    const heading = element('div', { class: 'progress-heading' });
    const label = element('span', { class: 'progress-label' }, item.label);
    const value = item.total == null
      ? progressValue(item.current)
      : `${progressValue(item.current)} / ${progressValue(item.total)}`;
    heading.append(
      label,
      element('span', { class: 'progress-value' }, value),
    );
    const bar = element('progress', {
      class: 'progress-bar',
      'aria-label': item.label,
    });
    if (item.total == null) {
      bar.removeAttribute('value');
    } else {
      bar.max = item.total;
      bar.value = item.current;
    }
    const detail = [item.phase, item.detail].filter(Boolean).join(' · ');
    row.append(heading, bar);
    if (detail) row.append(element('p', { class: 'progress-detail' }, detail));
    return row;
  });
  if (status.status_line) {
    rows.push(element(
      'p',
      { class: 'live-status' },
      status.status_line.replace(/^\[RUN\]\s*/, ''),
    ));
  }
  container.replaceChildren(...rows);
  container.classList.toggle('hidden', rows.length === 0);
  container.dataset.state = status.active
    ? 'running'
    : status.exit_code === 0 ? 'complete' : 'failed';
}

function renderTerminal(logs, lines) {
  const values = lines.length ? lines : ['Panel ready.'];
  if (
    values.length === renderedTerminalLines.length
    && values.every((value, index) => value === renderedTerminalLines[index])
  ) return;
  const atBottom = logs.scrollHeight - logs.scrollTop - logs.clientHeight < 40;
  const previousScrollTop = logs.scrollTop;
  const appendOnly = values.length >= renderedTerminalLines.length
    && renderedTerminalLines.every((value, index) => values[index] === value);
  if (appendOnly) {
    logs.append(...values.slice(renderedTerminalLines.length).map(terminalLine));
  } else {
    logs.replaceChildren(...values.map(terminalLine));
  }
  renderedTerminalLines = [...values];
  if (atBottom) logs.scrollTop = logs.scrollHeight;
  else logs.scrollTop = previousScrollTop;
}

function renderStatus() {
  const status = state.status || {
    active: false, name: '', logs: [], input_actions: [],
  };
  document.getElementById('status-dot').classList.toggle('active', status.active);
  document.getElementById('status-label').textContent = status.active ? 'Running' : 'Idle';
  document.getElementById('session-name').textContent = status.name || 'No active workflow';
  renderProgress(status);
  const logs = document.getElementById('logs');
  renderTerminal(logs, status.logs);

  const actions = document.getElementById('session-actions');
  actions.replaceChildren(...status.input_actions.map(action => {
    const tone = ['primary', 'danger', 'quiet'].includes(action.tone)
      ? action.tone
      : '';
    const button = element('button', {
      type: 'button',
      class: ['session-action', tone].filter(Boolean).join(' '),
    }, action.label);
    button.addEventListener('click', async () => {
      actions.querySelectorAll('button').forEach(item => { item.disabled = true; });
      try {
        state.status = await post('/api/input', { action: action.id });
        renderStatus();
      } catch (error) { toast(error.message); }
    });
    return button;
  }));
  const sessionNote = document.getElementById('session-state-note');
  if (!status.active) {
    sessionNote.textContent = 'Start a workflow to see its progress and available actions.';
  } else if (status.input_actions.length) {
    sessionNote.textContent = 'Waiting for your decision.';
  } else {
    sessionNote.textContent = 'Workflow running. Actions appear only when input is accepted.';
  }
  document.getElementById('stop-workflow').disabled = !status.active;
  document.querySelectorAll('[data-panel-action]').forEach(button => {
    button.disabled = status.active;
  });
  document.getElementById('create-config').disabled = status.active;
}

async function pollStatus() {
  try {
    state.status = await request('/api/status');
    renderStatus();
  } catch (_error) {
    document.getElementById('status-label').textContent = 'Disconnected';
  }
}

async function loadCatalog() {
  state.catalog = await request('/api/catalog');
  renderCatalog();
  await pollCameraHealth();
}

function renderCatalog() {
  renderProduct();
  renderCameras();
  renderWorkflows();
  renderConfigurationEditor();
  renderStatus();
}

document.getElementById('config-kind').addEventListener('change', updateConfigTemplates);
document.getElementById('toggle-camera-grid').addEventListener('click', () => {
  const collapsed = document.getElementById('camera-grid').classList.contains('collapsed');
  setCameraPreviewCollapsed(!collapsed);
});

document.getElementById('load-template').addEventListener('click', async () => {
  try {
    const source = document.getElementById('config-template').value;
    const payload = await post('/api/config/template', {
      kind: document.getElementById('config-kind').value,
      source,
    });
    document.getElementById('config-content').value = payload.content;
    document.getElementById('config-filename').value = `${source.split('/').pop().replace(/\.toml$/, '')}_copy.toml`;
    toast('Template loaded.');
  } catch (error) { toast(error.message); }
});

document.getElementById('validate-config').addEventListener('click', async () => {
  try {
    const result = await post('/api/config/validate', configPayload());
    toast(`Valid: ${result.path}`);
  } catch (error) { toast(error.message); }
});

document.getElementById('configuration-panel').addEventListener('submit', async event => {
  event.preventDefault();
  if (!window.confirm('Create this new validated repository configuration?')) return;
  try {
    const result = await post('/api/config/create', configPayload());
    state.catalog = result.catalog;
    document.getElementById('config-filename').value = '';
    document.getElementById('config-content').value = '';
    renderCatalog();
    toast(`Created: ${result.created}`);
  } catch (error) { toast(error.message); }
});

function configPayload() {
  return {
    kind: document.getElementById('config-kind').value,
    filename: document.getElementById('config-filename').value,
    content: document.getElementById('config-content').value,
  };
}

document.getElementById('stop-workflow').addEventListener('click', async () => {
  if (!window.confirm('Interrupt the active workflow and let it run cleanup?')) return;
  try {
    state.status = await post('/api/stop', {});
    renderStatus();
  } catch (error) { toast(error.message); }
});

loadCatalog().catch(error => toast(error.message));
pollStatus();
window.setInterval(pollStatus, 800);
window.setInterval(pollCameraHealth, cameraHealthPollMs);
