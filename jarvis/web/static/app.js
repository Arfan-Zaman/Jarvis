'use strict';

/* JARVIS interface. Plain JavaScript, no dependencies, no build step.
   All content is inserted as text nodes, never as HTML. */

const $ = (selector) => document.querySelector(selector);
const state = { projects: [], conversationId: null, timer: null, navigation: 0 };

// --- helpers ---------------------------------------------------------------
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  attrs = attrs || {};
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false || key === 'value') continue;
    if (key === 'class') el.className = value;
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  if (attrs.value !== undefined && attrs.value !== null) el.value = attrs.value;
  return el;
}

async function api(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function toast(message, isError) {
  const el = h('div', { class: 'toast' + (isError ? ' error' : '') }, message);
  $('#toasts').append(el);
  setTimeout(() => el.remove(), isError ? 7000 : 3000);
}

/** Run an async action, showing any failure instead of swallowing it. */
function act(fn) {
  return async (...args) => {
    try { return await fn(...args); } catch (error) { toast(error.message, true); }
  };
}

function when(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

function bytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

const label = (value) => String(value).replace(/_/g, ' ');
const chip = (text, tone) => h('span', { class: 'chip' + (tone ? ' ' + tone : '') }, text);
const projectName = (id) => (state.projects.find((p) => p.id === id) || {}).name;

function dialog({ title, text, note, okLabel, danger, input }) {
  const box = $('#confirm');
  $('#confirm-title').textContent = title;
  $('#confirm-text').textContent = text || '';
  $('#confirm-note').textContent = note || '';
  const field = $('#confirm-input');
  field.hidden = !input;
  field.value = '';
  field.placeholder = input || '';
  const ok = $('#confirm-ok');
  ok.textContent = okLabel || 'Confirm';
  ok.className = 'btn ' + (danger ? 'danger' : 'primary');
  return new Promise((resolve) => {
    const finish = (confirmed) => {
      ok.onclick = $('#confirm-cancel').onclick = box.onclose = null;
      if (box.open) box.close();
      resolve(confirmed ? (input ? field.value.trim() : true) : null);
    };
    ok.onclick = () => finish(true);
    $('#confirm-cancel').onclick = () => finish(false);
    box.onclose = () => finish(false);
    box.showModal();
    (input ? field : $('#confirm-cancel')).focus();
  });
}

/** Permanent deletion: the server refuses until the human approves. */
async function destroy(path, after) {
  const first = await api('DELETE', path);
  if (first.status === 'approval_required') {
    const approval = first.approval;
    const confirmed = await dialog({
      title: 'Permanent deletion',
      text: approval.summary,
      note: 'This cannot be undone. Archive instead if you might need it later.',
      okLabel: 'Delete permanently',
      danger: true,
    });
    if (!confirmed) {
      await api('POST', `/api/approvals/${approval.id}/deny`);
      return;
    }
    await api('POST', `/api/approvals/${approval.id}/approve`);
    await api('DELETE', `${path}?approval_id=${approval.id}`);
  }
  toast('Deleted permanently');
  await after();
  refreshChrome();
}

async function loadProjects() {
  state.projects = (await api('GET', '/api/projects?active=all')).items;
}

// --- forms -----------------------------------------------------------------
const VERIFICATION = ['unverified', 'user_provided', 'verified', 'disputed'];

function projectOptions() {
  return [['', 'No project'], ...state.projects.filter((p) => p.is_active).map((p) => [String(p.id), p.name])];
}

function control(spec) {
  const common = { name: spec.name, required: spec.required, placeholder: spec.placeholder };
  if (spec.type === 'textarea') return h('textarea', { ...common, value: spec.value });
  if (spec.type === 'select') {
    return h('select', { ...common, value: spec.value },
      spec.options.map((option) => {
        const [value, text] = Array.isArray(option) ? option : [option, label(option)];
        return h('option', { value }, text);
      }));
  }
  return h('input', { ...common, type: spec.type || 'text', value: spec.value, min: spec.min, max: spec.max, step: spec.step });
}

/** Build a form. `wide` specs take a full row; neighbouring others share a grid. */
function form(specs, submitLabel, onSubmit) {
  const field = (spec) => h('label', { class: 'field' }, spec.label, control(spec));
  const rows = [];
  for (const spec of specs) {
    const last = rows[rows.length - 1];
    if (spec.wide) rows.push(field(spec));
    else if (last && last.classList.contains('fields')) last.append(field(spec));
    else rows.push(h('div', { class: 'fields' }, field(spec)));
  }
  const el = h('form', { class: 'form' }, rows,
    h('div', { class: 'row end' }, h('button', { class: 'btn primary', type: 'submit' }, submitLabel)));
  el.addEventListener('submit', act(async (event) => {
    event.preventDefault();
    const data = {};
    for (const spec of specs) {
      let value = el.elements[spec.name].value;
      if (spec.name.endsWith('_id')) value = value ? Number(value) : null;
      else if (spec.type === 'number') value = Number(value);
      else if (spec.type === 'date' && !value) value = null;
      data[spec.name] = value;
    }
    await onSubmit(data);
    // Back to each field's starting value (reset() would blank the defaults).
    for (const spec of specs) el.elements[spec.name].value = spec.value ?? '';
    refreshChrome();
  }));
  return el;
}

const metaSpecs = (category) => [
  { name: 'category', label: 'Category', value: category || 'general', required: true },
  { name: 'project_id', label: 'Project', type: 'select', options: projectOptions(), value: '' },
  { name: 'source', label: 'Source', value: 'user', required: true },
  { name: 'verification_status', label: 'Verification', type: 'select', options: VERIFICATION, value: 'user_provided' },
  { name: 'confidence', label: 'Confidence (0–1)', type: 'number', min: 0, max: 1, step: 0.05, value: 1 },
];

// --- record rendering ------------------------------------------------------
function metaChips(record) {
  const tone = { verified: 'ok', user_provided: 'violet', disputed: 'bad', unverified: 'warn' }[record.verification_status];
  return h('div', { class: 'meta' },
    chip(record.category, 'violet'),
    record.project_id && projectName(record.project_id) ? chip(projectName(record.project_id)) : null,
    chip(label(record.verification_status), tone),
    chip(`confidence ${Math.round(record.confidence * 100)}%`),
    chip(`source: ${record.source}`),
    chip(when(record.created_at)),
    record.is_active ? null : chip('archived', 'pink'));
}

function recordActions(kind, record, reload) {
  return h('div', { class: 'actions' },
    record.is_active
      ? h('button', { class: 'btn sm', onclick: act(async () => { await api('POST', `/api/${kind}/${record.id}/archive`); await reload(); refreshChrome(); }) }, 'Archive')
      : h('button', { class: 'btn sm', onclick: act(async () => { await api('POST', `/api/${kind}/${record.id}/restore`); await reload(); refreshChrome(); }) }, 'Restore'),
    h('button', { class: 'btn sm danger', onclick: act(() => destroy(`/api/${kind}/${record.id}`, reload)) }, 'Delete'));
}

/** A searchable list with an "include archived" toggle. */
function listPanel(title, kind, renderItem, extraQuery) {
  const body = h('div', { class: 'list' });
  const search = h('input', { type: 'search', placeholder: 'Search…', 'aria-label': 'Search' });
  const archived = h('input', { type: 'checkbox', id: `archived-${kind}` });
  const reload = act(async () => {
    const params = new URLSearchParams(extraQuery || {});
    if (search.value.trim()) params.set('q', search.value.trim());
    if (archived.checked) params.set('active', 'all');
    const { items } = await api('GET', `/api/${kind}?${params}`);
    body.replaceChildren(...(items.length
      ? items.map((item) => renderItem(item, reload))
      : [h('div', { class: 'empty' }, search.value.trim() ? 'Nothing matches that search.' : 'Nothing here yet.')]));
  });
  let debounce;
  search.addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(reload, 200); });
  archived.addEventListener('change', reload);
  const panel = h('div', { class: 'glass panel' },
    h('div', { class: 'row between' },
      h('h2', null, title),
      h('div', { class: 'row' },
        h('label', { class: 'row small muted', for: `archived-${kind}` }, archived, 'Include archived'))),
    search, body);
  return { panel, reload };
}

// --- views -----------------------------------------------------------------
const views = {};

views.dashboard = {
  title: 'Dashboard',
  subtitle: 'Command centre overview',
  async render(root) {
    const data = await api('GET', '/api/dashboard');
    const { status } = data;
    const counts = status.counts;
    const stat = (value, text) => h('div', { class: 'glass stat' }, h('div', { class: 'value' }, value), h('div', { class: 'label' }, text));

    root.append(h('div', { class: 'stack' },
      aiBanner(status.ai),
      h('div', { class: 'grid stats' },
        stat(counts.tasks_open, 'Open tasks'),
        stat(counts.projects, 'Projects'),
        stat(counts.memories, 'Memories'),
        stat(counts.experiences, 'Experiences'),
        stat(counts.pending_approvals, 'Pending approvals')),
      h('div', { class: 'grid two' },
        h('div', { class: 'glass panel' }, h('h2', null, 'Open tasks'),
          data.open_tasks.length
            ? h('div', { class: 'list' }, data.open_tasks.map((task) => h('div', { class: 'item' },
              h('div', { class: 'grow' }, h('div', { class: 'title' }, task.title),
                h('div', { class: 'meta' }, chip(label(task.status), 'violet'), priorityChip(task.priority),
                  task.project_id && projectName(task.project_id) ? chip(projectName(task.project_id)) : null)))))
            : h('div', { class: 'empty' }, 'No open tasks.')),
        h('div', { class: 'glass panel' }, h('h2', null, 'Projects'),
          data.projects.length
            ? h('div', { class: 'list' }, data.projects.map((project) => h('div', { class: 'item' },
              h('div', { class: 'grow' }, h('div', { class: 'title' }, project.name),
                h('div', { class: 'muted small' }, project.description)),
              chip(project.status, 'ok'))))
            : h('div', { class: 'empty' }, 'No projects.'))),
      h('div', { class: 'glass panel' }, h('h2', null, 'Recent activity'), eventTable(data.recent_events))));
  },
};

function aiBanner(ai) {
  if (ai.configured && ai.available) {
    return h('div', { class: 'banner ok' }, h('div', null,
      h('strong', null, `AI connected: ${ai.name} (${ai.model})`), h('span', { class: 'muted' }, ai.detail)));
  }
  return h('div', { class: 'banner' }, h('div', null,
    h('strong', null, 'No AI model is connected'),
    h('span', { class: 'muted' }, `${ai.detail} Everything else works; chat cannot generate replies.`)));
}

const priorityChip = (priority) => chip(priority, { urgent: 'pink', high: 'warn' }[priority]);

function eventTable(events) {
  if (!events.length) return h('div', { class: 'empty' }, 'No activity recorded yet.');
  const tone = { warning: 'warn', error: 'bad' };
  return h('div', { class: 'scroll-x' }, h('table', null,
    h('tr', null, ['When', 'Category', 'Action', 'Actor', 'Message'].map((name) => h('th', null, name))),
    events.map((event) => h('tr', null,
      h('td', { class: 'muted small' }, when(event.created_at)),
      h('td', null, chip(event.category, tone[event.level])),
      h('td', { class: 'mono' }, event.action),
      h('td', { class: 'muted' }, event.actor),
      h('td', { class: 'wrap' }, event.message)))));
}

views.chat = {
  title: 'Chat',
  subtitle: 'Conversations are stored locally',
  async render(root) {
    const status = await api('GET', '/api/status');
    const threads = h('div', { class: 'glass threads' });
    const messages = h('div', { class: 'messages' });
    const input = h('textarea', { placeholder: 'Message JARVIS…', title: 'Enter to send, Shift+Enter for a new line', 'aria-label': 'Message' });
    const send = h('button', { class: 'btn primary', type: 'submit' }, 'Send');

    const runTone = { completed: 'ok', failed: 'bad', blocked: 'warn', waiting_approval: 'pink', interrupted: 'warn', cancelled: null };
    const actionCard = (runId) => {
      const card = h('div', { class: 'action-card' }, h('span', { class: 'muted small' }, 'Loading action…'));
      api('GET', `/api/runs/${runId}`).then(({ report }) => {
        const resume = act(async () => { await api('POST', `/api/runs/${runId}/resume`); await openThread(); refreshChrome(); });
        card.replaceChildren(
          h('div', { class: 'row' }, h('span', { class: 'small muted' }, `Action #${runId}`),
            chip(label(report.status), runTone[report.status]), report.verified_complete ? chip('verified', 'ok') : null),
          report.changes_made.length ? h('ul', { class: 'small' }, report.changes_made.map((c) => h('li', null, `${c.tool}: ${c.what}`))) : null,
          h('div', { class: 'row' },
            h('a', { class: 'btn sm', href: '#goals' }, 'Details'),
            report.status === 'waiting_approval' ? h('a', { class: 'btn sm', href: '#system' }, 'Review approval') : null,
            ['waiting_approval', 'interrupted'].includes(report.status) ? h('button', { class: 'btn sm primary', onclick: resume }, 'Continue') : null));
      }).catch(() => card.replaceChildren(h('span', { class: 'muted small' }, `Action #${runId}`)));
      return card;
    };

    const bubble = (message) => h('div', { class: `msg ${message.role}` },
      h('div', { class: 'who' }, message.role === 'assistant' ? `JARVIS · ${message.model || message.provider || ''}`
        : message.role === 'system' ? 'System notice' : 'You'),
      h('div', { class: 'wrap' }, message.content),
      message.memory_refs && message.memory_refs.length
        ? h('div', { class: 'meta' }, chip('From memory', 'violet'),
          message.memory_refs.map((ref) => h('span', { class: 'chip', title: ref.content },
            ref.content.length > 48 ? ref.content.slice(0, 47) + '…' : ref.content)))
        : null,
      message.run_id ? actionCard(message.run_id) : null);

    const showMessages = (list) => {
      messages.replaceChildren(...(list.length ? list.map(bubble)
        : [h('div', { class: 'empty' }, 'Start a conversation below.')]));
      messages.scrollTop = messages.scrollHeight;
    };

    const loadThreads = async () => {
      const { items } = await api('GET', '/api/conversations');
      threads.replaceChildren(
        h('button', { class: 'btn sm', onclick: () => { state.conversationId = null; showMessages([]); loadThreads(); input.focus(); } }, '+ New conversation'),
        ...items.map((item) => h('button', {
          class: 'thread' + (item.id === state.conversationId ? ' active' : ''), title: item.title,
          onclick: act(async () => { state.conversationId = item.id; await openThread(); }),
        }, item.title)));
    };

    const openThread = async () => {
      if (state.conversationId === null) return showMessages([]);
      try {
        showMessages((await api('GET', `/api/conversations/${state.conversationId}`)).messages);
      } catch (error) {
        state.conversationId = null;
        showMessages([]);
      }
      await loadThreads();
    };

    const composer = h('form', { class: 'composer' }, input, send);
    composer.addEventListener('submit', act(async (event) => {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      send.disabled = true;
      // Show the message and a thinking indicator at once; the first reply after a restart
      // can take ~20 seconds while the model loads.
      messages.querySelector('.empty')?.remove();
      messages.append(bubble({ role: 'user', content: text }),
        h('div', { class: 'msg assistant thinking' }, h('div', { class: 'who' }, 'JARVIS'),
          h('div', null, 'Thinking…'),
          h('div', { class: 'muted small' }, 'The first reply after JARVIS starts can take up to 30 seconds.')));
      messages.scrollTop = messages.scrollHeight;
      input.value = '';
      try {
        const result = await api('POST', '/api/chat', { message: text, conversation_id: state.conversationId });
        state.conversationId = result.conversation.id;
        await openThread();
      } catch (error) {
        messages.querySelector('.thinking')?.remove();
        input.value = text;                        // give the message back so it can be resent
        throw error;
      } finally {
        send.disabled = false;
        input.focus();
      }
    }));
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); composer.requestSubmit(); }
    });

    root.append(h('div', { class: 'stack' },
      status.ai.configured && status.ai.available ? null : aiBanner(status.ai),
      h('div', { class: 'chat' }, threads, h('div', { class: 'glass conversation' }, messages, composer))));
    await loadThreads();
    await openThread();
  },
};

views.goals = {
  title: 'Goals',
  subtitle: 'Give JARVIS a goal; it plans, acts through its tools, and reports what was verified',
  async render(root) {
    const status = await api('GET', '/api/status');
    const connected = status.ai.configured && status.ai.available;
    const list = h('div', { class: 'stack' });
    const tone = { completed: 'ok', failed: 'bad', blocked: 'warn', waiting_approval: 'pink', cancelled: null, interrupted: 'warn', running: 'violet', pending: null };
    const control = (path, body) => act(async () => { await api('POST', path, body || {}); await reload(); refreshChrome(); });

    const card = (report) => h('div', { class: 'glass panel' },
      h('div', { class: 'row between' }, h('div', { class: 'title grow wrap' }, report.goal),
        chip(label(report.status), tone[report.status]), report.verified_complete ? chip('verified', 'ok') : null),
      h('p', { class: 'wrap' }, report.summary),
      report.plan.length ? h('div', { class: 'list' }, report.plan.map((step) => h('div', { class: 'item' },
        h('div', { class: 'grow' }, h('div', null, `${step.position}. ${step.description}`),
          step.note ? h('div', { class: 'muted small wrap' }, step.note) : null),
        chip(step.tool), chip(label(step.status), tone[step.status])))) : null,
      report.model_summary ? h('p', { class: 'muted small wrap' }, `Model's own summary (not verified): ${report.model_summary}`) : null,
      h('div', { class: 'row end' },
        h('span', { class: 'muted small grow' }, `Run #${report.run_id} · ${when(report.created_at)}`),
        report.status === 'blocked' ? h('button', { class: 'btn sm primary', onclick: act(async () => {
          const answer = await dialog({ title: 'JARVIS needs information', text: report.question, okLabel: 'Send and continue', input: 'Your answer…' });
          if (answer) await control(`/api/runs/${report.run_id}/resume`, { answer })();
        }) }, 'Answer') : null,
        ['waiting_approval', 'interrupted'].includes(report.status)
          ? h('button', { class: 'btn sm primary', onclick: control(`/api/runs/${report.run_id}/resume`) }, 'Continue') : null,
        report.status === 'waiting_approval' ? h('a', { class: 'btn sm', href: '#system' }, 'Review approval') : null,
        ['blocked', 'waiting_approval', 'interrupted'].includes(report.status)
          ? h('button', { class: 'btn sm', onclick: control(`/api/runs/${report.run_id}/cancel`) }, 'Cancel') : null));

    const reload = act(async () => {
      const { items } = await api('GET', '/api/runs?kind=goal&limit=15');
      const runs = await Promise.all(items.map((run) => api('GET', `/api/runs/${run.id}`)));
      list.replaceChildren(...(runs.length ? runs.map((run) => card(run.report))
        : [h('div', { class: 'glass panel empty' }, 'No goals have been run yet.')]));
    });

    const goal = h('textarea', { name: 'goal', required: true, placeholder: 'For example: add a high-priority task to review this week\'s open jobs' });
    const submit = h('button', { class: 'btn primary', type: 'submit', disabled: !connected }, 'Run goal');
    const entry = h('form', { class: 'form' }, h('label', { class: 'field' }, 'Goal', goal), h('div', { class: 'row end' }, submit));
    entry.addEventListener('submit', act(async (event) => {
      event.preventDefault();
      submit.disabled = true;
      try {
        await api('POST', '/api/runs', { goal: goal.value });
        goal.value = '';
        await reload();
        refreshChrome();
      } finally { submit.disabled = !connected; }
    }));

    root.append(h('div', { class: 'stack' },
      connected ? null : h('div', { class: 'banner' }, h('div', null, h('strong', null, 'Goals need an AI model'),
        h('span', { class: 'muted' }, 'The reasoning engine is built, but no model is connected to do the planning, so goals cannot run yet.'))),
      h('div', { class: 'glass panel' }, h('h2', null, 'New goal'), entry), list));
    await reload();
  },
};

views.memory = {
  title: 'Memory',
  subtitle: 'Facts and notes JARVIS retains, with their provenance',
  async render(root) {
    const { panel, reload } = listPanel('Stored memories', 'memories', (memory, again) =>
      h('div', { class: 'item' + (memory.is_active ? '' : ' archived') },
        h('div', { class: 'grow' }, h('div', { class: 'wrap' }, memory.content), metaChips(memory)),
        recordActions('memories', memory, again)));
    root.append(h('div', { class: 'stack' },
      h('div', { class: 'glass panel' }, h('h2', null, 'Add a memory'),
        form([{ name: 'content', label: 'What should JARVIS remember?', type: 'textarea', required: true, wide: true }, ...metaSpecs()],
          'Save memory', async (data) => { await api('POST', '/api/memories', data); toast('Memory saved'); await reload(); })),
      panel));
    await reload();
  },
};

views.tasks = {
  title: 'Tasks',
  subtitle: 'What needs doing',
  async render(root) {
    const { panel, reload } = listPanel('All tasks', 'tasks', (task, again) => {
      const done = task.status === 'completed';
      const toggle = h('input', { type: 'checkbox', 'aria-label': done ? 'Reopen task' : 'Complete task' });
      toggle.checked = done;
      toggle.addEventListener('change', act(async () => {
        await api('POST', `/api/tasks/${task.id}/${done ? 'reopen' : 'complete'}`);
        await again();
        refreshChrome();
      }));
      const addLesson = act(async () => {
        const lesson = await dialog({ title: 'Record a lesson', text: `What did “${task.title}” teach you?`,
          note: 'Saved as an experience linked to this task.', okLabel: 'Save lesson', input: 'Lesson learned…' });
        if (!lesson) return;
        await api('POST', '/api/experiences', { title: `Task completed: ${task.title}`.slice(0, 300), lesson,
          outcome: 'success', category: 'task', source: `task:${task.id}`, task_id: task.id, project_id: task.project_id });
        toast('Lesson saved to Experiences');
        refreshChrome();
      });
      return h('div', { class: 'item' + (done ? ' done' : '') + (task.is_active ? '' : ' archived') },
        toggle,
        h('div', { class: 'grow' }, h('div', { class: 'title' }, task.title),
          task.description ? h('div', { class: 'muted wrap' }, task.description) : null,
          h('div', { class: 'meta' }, chip(label(task.status), done ? 'ok' : 'violet'), priorityChip(task.priority),
            task.project_id && projectName(task.project_id) ? chip(projectName(task.project_id)) : null,
            task.due_at ? chip(`due ${task.due_at}`) : null,
            done ? chip(`completed ${when(task.completed_at)}`) : null,
            task.is_active ? null : chip('archived', 'pink'))),
        h('div', { class: 'actions' },
          done ? h('button', { class: 'btn sm', onclick: addLesson }, '+ Lesson') : null,
          [...recordActions('tasks', task, again).childNodes]));
    });
    root.append(h('div', { class: 'stack' },
      h('div', { class: 'glass panel' }, h('h2', null, 'Add a task'),
        form([
          { name: 'title', label: 'Task', required: true, wide: true },
          { name: 'description', label: 'Details (optional)', type: 'textarea', wide: true },
          { name: 'priority', label: 'Priority', type: 'select', options: ['low', 'normal', 'high', 'urgent'], value: 'normal' },
          { name: 'project_id', label: 'Project', type: 'select', options: projectOptions(), value: '' },
          { name: 'due_at', label: 'Due date', type: 'date' },
        ], 'Add task', async (data) => { await api('POST', '/api/tasks', data); toast('Task added'); await reload(); })),
      panel));
    await reload();
  },
};

views.projects = {
  title: 'Projects',
  subtitle: 'Workspaces that tasks, memories and experiences attach to',
  async render(root) {
    const cards = h('div', { class: 'grid cards' });
    const reload = act(async () => {
      await loadProjects();
      const active = state.projects.filter((project) => project.is_active);
      const archived = state.projects.filter((project) => !project.is_active);
      const tallies = await Promise.all(active.map(async (project) => {
        const [tasks, memories] = await Promise.all([
          api('GET', `/api/tasks?project_id=${project.id}`), api('GET', `/api/memories?project_id=${project.id}`)]);
        return { open: tasks.items.filter((task) => ['pending', 'in_progress'].includes(task.status)).length, memories: memories.items.length };
      }));
      const card = (project, tally) => h('div', { class: 'glass panel' + (project.is_active ? '' : ' item archived') },
        h('div', { class: 'row between' }, h('div', { class: 'title' }, project.name), chip(project.is_active ? project.status : 'archived', project.is_active ? 'ok' : 'pink')),
        h('p', { class: 'muted wrap' }, project.description || 'No description.'),
        h('div', { class: 'meta' }, chip(project.category, 'violet'),
          tally ? chip(`${tally.open} open task${tally.open === 1 ? '' : 's'}`) : null,
          tally ? chip(`${tally.memories} memor${tally.memories === 1 ? 'y' : 'ies'}`) : null,
          chip(`source: ${project.source}`)),
        h('div', { class: 'row end' }, [...recordActions('projects', project, reload).childNodes]));
      cards.replaceChildren(...[...active.map((project, index) => card(project, tallies[index])), ...archived.map((project) => card(project))]);
      if (!state.projects.length) cards.append(h('div', { class: 'empty' }, 'No projects yet.'));
    });
    root.append(h('div', { class: 'stack' }, cards,
      h('div', { class: 'glass panel' }, h('h2', null, 'Add a project'),
        form([
          { name: 'name', label: 'Name', required: true },
          { name: 'category', label: 'Category', value: 'general', required: true },
          { name: 'description', label: 'Description', type: 'textarea', wide: true },
        ], 'Create project', async (data) => {
          await api('POST', '/api/projects', { ...data, verification_status: 'user_provided' });
          toast('Project created');
          await reload();
        }))));
    await reload();
  },
};

views.experiences = {
  title: 'Experiences',
  subtitle: 'What happened, how it went, and what to do next time',
  async render(root) {
    const tone = { success: 'ok', failure: 'bad', mixed: 'warn' };
    const { panel, reload } = listPanel('Recorded experiences', 'experiences', (item, again) =>
      h('div', { class: 'item' + (item.is_active ? '' : ' archived') },
        h('div', { class: 'grow' },
          h('div', { class: 'row' }, h('div', { class: 'title' }, item.title), chip(item.outcome, tone[item.outcome])),
          item.description ? h('div', { class: 'muted wrap' }, item.description) : null,
          item.lesson ? h('div', { class: 'wrap' }, h('span', { class: 'muted' }, 'Lesson: '), item.lesson) : null,
          metaChips(item)),
        recordActions('experiences', item, again)));
    root.append(h('div', { class: 'stack' },
      h('div', { class: 'glass panel' }, h('h2', null, 'Record an experience'),
        form([
          { name: 'title', label: 'What happened?', required: true, wide: true },
          { name: 'description', label: 'Details (optional)', type: 'textarea', wide: true },
          { name: 'lesson', label: 'Lesson for next time', type: 'textarea', wide: true },
          { name: 'outcome', label: 'Outcome', type: 'select', options: ['success', 'failure', 'mixed', 'unknown'], value: 'unknown' },
          ...metaSpecs(),
        ], 'Save experience', async (data) => { await api('POST', '/api/experiences', data); toast('Experience saved'); await reload(); })),
      panel));
    await reload();
  },
};

views.system = {
  title: 'System status',
  subtitle: 'Health, safety, backups and the audit trail',
  async render(root) {
    const [status, approvals, backups, agents, events, tools, executions] = await Promise.all([
      api('GET', '/api/status'), api('GET', '/api/approvals?status=pending'), api('GET', '/api/backups'),
      api('GET', '/api/agents'), api('GET', '/api/events?limit=60'), api('GET', '/api/tools'),
      api('GET', '/api/executions?limit=25')]);
    const stepTone = { succeeded: 'ok', failed: 'bad', refused: 'bad', waiting_approval: 'warn' };
    const kv = (pairs) => h('dl', { class: 'kv' }, pairs.map(([key, value]) => [h('dt', null, key), h('dd', null, value)]));
    const rerender = () => show('system');

    root.append(h('div', { class: 'stack' },
      aiBanner(status.ai),
      h('div', { class: 'grid two' },
        h('div', { class: 'glass panel' }, h('h2', null, 'Core'), kv([
          ['Version', status.version],
          ['Environment', status.environment],
          ['Uptime', `${Math.floor(status.uptime_seconds / 60)} min`],
          ['Database', h('span', { class: 'mono' }, status.database.path)],
          ['Schema', `v${status.database.schema_version}`],
          ['Size', bytes(status.database.size_bytes)],
          ['Integrity', status.database.integrity_ok ? chip('ok', 'ok') : chip('FAILED', 'bad')],
        ])),
        h('div', { class: 'glass panel' }, h('h2', null, 'AI provider'), kv([
          ['Provider', status.ai.name],
          ['Type', status.ai.kind],
          ['Configured', status.ai.configured ? chip('yes', 'ok') : chip('no', 'pink')],
          ['Available', status.ai.available ? chip('yes', 'ok') : chip('no', 'pink')],
          ['Model', status.ai.model || '—'],
          ['Detail', status.ai.detail],
        ])),
        h('div', { class: 'glass panel' }, h('h2', null, 'Safety'), kv([
          ['Mode', status.safety.read_only ? chip('read-only', 'warn') : chip('read / write', 'ok')],
          ['Runs automatically', h('div', { class: 'meta' }, (status.safety.automatic || []).map((name) => chip(label(name), 'ok')))],
          ['Asks you first', h('div', { class: 'meta' }, status.safety.approval_required_for.map((name) => chip(label(name), 'pink')))],
          ['Workspace', h('span', { class: 'mono' }, status.safety.workspace || '')],
          ['Approval lifetime', `${status.safety.approval_ttl_minutes} min, single use`],
          ['External AI', status.safety.external_ai_allowed ? chip('allowed', 'warn') : chip('blocked', 'ok')],
          ['Not built yet', status.not_built_yet.join(', ')],
        ])),
        h('div', { class: 'glass panel' },
          h('div', { class: 'row between' }, h('h2', null, `Backups (${backups.items.length}, keeps ${status.backups.keep})`),
            h('button', { class: 'btn sm primary', onclick: act(async () => { await api('POST', '/api/backups', { label: 'manual' }); toast('Backup created'); rerender(); }) }, 'Back up now')),
          backups.items.length
            ? h('div', { class: 'list' }, backups.items.slice(0, 6).map((item) => h('div', { class: 'item' },
              h('div', { class: 'grow mono' }, item.name), h('span', { class: 'muted small' }, `${bytes(item.size_bytes)} · ${when(item.created_at)}`))))
            : h('div', { class: 'empty' }, 'No backups yet.'),
          h('p', { class: 'muted small' }, 'Restore from the command line: python3 -m jarvis restore <name>'))),
      h('div', { class: 'glass panel' }, h('h2', null, 'Pending approvals'),
        approvals.items.length
          ? h('div', { class: 'list' }, approvals.items.map((item) => h('div', { class: 'item' },
            h('div', { class: 'grow' }, h('div', { class: 'title' }, item.summary),
              h('div', { class: 'meta' }, chip(label(item.category), 'pink'), chip(item.action), chip(`requested by ${item.requested_by}`), chip(`expires ${when(item.expires_at)}`))),
            h('div', { class: 'actions' },
              h('button', { class: 'btn sm', onclick: act(async () => { await api('POST', `/api/approvals/${item.id}/deny`); rerender(); }) }, 'Deny'),
              h('button', { class: 'btn sm danger', onclick: act(async () => { await api('POST', `/api/approvals/${item.id}/approve`); toast('Approved. The requester may now proceed once.'); rerender(); }) }, 'Approve'))))
          )
          : h('div', { class: 'empty' }, 'Nothing is waiting for approval.')),
      h('div', { class: 'glass panel' }, h('h2', null, 'Agents'),
        h('div', { class: 'list' }, agents.items.map((agent) => h('div', { class: 'item' },
          h('div', { class: 'grow' }, h('div', { class: 'title mono' }, agent.name), h('div', { class: 'muted small' }, agent.description)),
          chip(agent.kind, 'violet'), chip(agent.status, agent.status === 'active' ? 'ok' : null))))),
      h('div', { class: 'glass panel' }, h('h2', null, `Tools (${tools.items.length})`),
        h('div', { class: 'list' }, tools.items.map((tool) => h('div', { class: 'item' },
          h('div', { class: 'grow' }, h('div', { class: 'title mono' }, tool.name), h('div', { class: 'muted small' }, tool.description)),
          chip(label(tool.permission), tool.requires_approval ? 'pink' : tool.permission === 'write' ? 'violet' : 'ok'))))),
      h('div', { class: 'glass panel' }, h('h2', null, 'Recent tool executions'),
        executions.items.length
          ? h('div', { class: 'scroll-x' }, h('table', null,
            h('tr', null, ['When', 'Tool', 'Result', 'Actor', 'Time', 'Error'].map((name) => h('th', null, name))),
            executions.items.map((step) => h('tr', null,
              h('td', { class: 'muted small' }, when(step.started_at)), h('td', { class: 'mono' }, step.tool),
              h('td', null, chip(label(step.status), stepTone[step.status])), h('td', { class: 'muted' }, step.actor),
              h('td', { class: 'muted small' }, `${step.duration_ms} ms`), h('td', { class: 'wrap' }, step.error || '')))))
          : h('div', { class: 'empty' }, 'No tools have been executed yet.')),
      h('div', { class: 'glass panel' }, h('h2', null, 'Audit trail and system events'), eventTable(events.items))));
  },
};

// --- shell -----------------------------------------------------------------
async function refreshChrome() {
  try {
    const status = await api('GET', '/api/status');
    const connected = status.ai.configured && status.ai.available;
    $('#ai-dot').className = 'dot ' + (connected ? 'ok' : 'off');
    $('#ai-label').textContent = connected ? `AI: ${status.ai.name}` : 'No AI connected';
    $('#ai-pill').title = status.ai.detail;
    $('#brand-version').textContent = `core v${status.version}`;
    const badge = $('#approval-badge');
    badge.hidden = !status.counts.pending_approvals;
    badge.textContent = status.counts.pending_approvals;
  } catch (error) {
    $('#ai-dot').className = 'dot off';
    $('#ai-label').textContent = 'JARVIS is not responding';
  }
}

async function show(name) {
  const view = views[name] || views.dashboard;
  const key = views[name] ? name : 'dashboard';
  const token = ++state.navigation;
  document.querySelectorAll('.nav a').forEach((link) => {
    const active = link.dataset.view === key;
    link.classList.toggle('active', active);
    if (active) { link.setAttribute('aria-current', 'page'); link.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }
    else link.removeAttribute('aria-current');
  });
  $('#view-title').textContent = view.title;
  $('#view-subtitle').textContent = view.subtitle;
  document.title = `${view.title} · JARVIS`;
  const root = h('section', { id: 'view' });
  try {
    await loadProjects();
    await view.render(root);
  } catch (error) {
    root.replaceChildren(h('div', { class: 'banner' }, h('div', null, h('strong', null, 'This page could not load'), h('span', { class: 'muted' }, error.message))));
  }
  if (token !== state.navigation) return;  // a newer navigation has taken over
  $('#view').replaceWith(root);
}

const route = async () => { await show(location.hash.replace('#', '') || 'dashboard'); window.scrollTo(0, 0); };
window.addEventListener('hashchange', route);
route();
refreshChrome();
state.timer = setInterval(refreshChrome, 30000);
