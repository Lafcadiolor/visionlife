// Dashboard-local UI state injected by the server render.
// This lets the static JS know which day/row is currently selected
// without hardcoding those values in the script bundle.
let pendingReassignFile = '';

function visionlifeState() {
  return window.VISIONLIFE_UI_STATE || { selectedDay: '', selectedRow: '' };
}

async function postJson(url, payload) {
  await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// Saves editable header phrases, group labels, and row labels/capacities
// back into dashboard_config.json via the local HTTP API.
async function saveDashboardConfig() {
  const config = {
    identity: {
      inscription: document.querySelector('[data-config-key="inscription"]').innerText.trim(),
      affirmation: document.querySelector('[data-config-key="affirmation"]').innerText.trim(),
      rotating_phrase: document.querySelector('[data-config-key="rotating_phrase"]').innerText.trim(),
    },
    groups: Array.from(document.querySelectorAll('.tracker-group')).map(group => {
      return {
        id: group.querySelector('.group-label').dataset.groupId,
        label: group.querySelector('.group-label').innerText.trim(),
        color: getComputedStyle(group.querySelector('.group-label')).getPropertyValue('--group-color').trim() || '#d8d6d0',
        rows: Array.from(group.querySelectorAll('.tracker-row')).map(row => {
          return {
            id: row.dataset.rowId,
            label: row.querySelector('.row-label').innerText.trim(),
            mode: row.dataset.mode || 'standard',
            capacity_hours: Number(row.dataset.capacityHours || 0),
          };
        })
      };
    }),
  };
  await postJson('/api/config', config);
}

// Cell status is the main tracker color state.
// The current drawer note is persisted at the same time so the focused
// cell remains a complete working surface.
async function updateCellStatus(day, row, status) {
  await postJson('/api/state', {
    kind: 'cell',
    day: day,
    row_id: row,
    status: status,
    note: document.getElementById('cell-note-input') ? document.getElementById('cell-note-input').value : '',
  });
  window.location = `/?day=${encodeURIComponent(day)}&row=${encodeURIComponent(row)}`;
}

// Saves only the freeform note for the selected cell while preserving
// the existing color/status marker.
async function saveCellNote(day, row) {
  await postJson('/api/state', {
    kind: 'cell',
    day: day,
    row_id: row,
    status: '',
    note: document.getElementById('cell-note-input').value,
    preserve_status: true,
  });
  window.location = `/?day=${encodeURIComponent(day)}&row=${encodeURIComponent(row)}`;
}

// Artifact assignments are dashboard-local review state layered on top
// of analyzed notes. This lets the user approve/reassign/archive items
// without mutating the original Markdown note.
async function updateAssignment(filename, field, value) {
  await postJson('/api/state', {
    kind: 'assignment',
    filename: filename,
    field: field,
    value: value,
  });
  window.location.reload();
}

async function toggleAssignmentFlag(filename, field) {
  await postJson('/api/state', {
    kind: 'assignment_toggle',
    filename: filename,
    field: field,
  });
  window.location.reload();
}

async function setArtifactLabel(filename, currentValue) {
  const value = window.prompt('Label this artifact', currentValue || '');
  if (value === null) return;
  await postJson('/api/state', {
    kind: 'assignment',
    filename: filename,
    field: 'label',
    value: value.trim(),
  });
  window.location.reload();
}

function openReassign(filename) {
  pendingReassignFile = filename;
  document.getElementById('reassign-dialog').showModal();
}

function closeReassign() {
  const dialog = document.getElementById('reassign-dialog');
  if (dialog.open) dialog.close();
}

async function submitReassign() {
  await postJson('/api/state', {
    kind: 'assignment',
    filename: pendingReassignFile,
    field: 'row_id',
    value: document.getElementById('reassign-row').value,
  });
  closeReassign();
  window.location.reload();
}

async function createTodo(sourceDay) {
  const text = document.getElementById('todo-text').value.trim();
  if (!text) return;
  await postJson('/api/state', {
    kind: 'todo_create',
    source_day: sourceDay,
    text: text,
    type: document.getElementById('todo-type').value,
    estimate: document.getElementById('todo-estimate').value,
  });
  window.location.reload();
}

// To-do items are stored in dashboard_state.json. They currently support
// a small v1 lifecycle: captured -> provisional/approved -> done.
async function updateTodo(id, field, value) {
  await postJson('/api/state', {
    kind: 'todo_update',
    id: id,
    field: field,
    value: value,
  });
  window.location.reload();
}

// Moves the user one day forward while preserving the selected row.
// This supports lightweight “plan tomorrow” behavior from the drawer.
function openPlanner(day) {
  const selectedRow = visionlifeState().selectedRow || '';
  const tomorrow = new Date(day + 'T00:00:00');
  tomorrow.setDate(tomorrow.getDate() + 1);
  const nextDay = tomorrow.toISOString().slice(0, 10);
  window.location = `/?day=${encodeURIComponent(nextDay)}&row=${encodeURIComponent(selectedRow)}`;
}

// Calendar actions open a lightweight local dialog first so the user can
// inspect and edit extracted event details before creating the draft in
// Google Calendar.
function openCalendarDialog(button) {
  const dialog = document.getElementById('calendar-dialog');
  document.getElementById('calendar-dialog-heading').textContent = button.dataset.note || 'Calendar Draft';
  document.getElementById('calendar-title').value = button.dataset.title || '';
  document.getElementById('calendar-start').value = button.dataset.start || '';
  document.getElementById('calendar-end').value = button.dataset.end || '';
  document.getElementById('calendar-location').value = button.dataset.location || '';
  document.getElementById('calendar-details').value = button.dataset.details || '';
  document.getElementById('calendar-evidence').textContent = button.dataset.evidence || '';
  dialog.showModal();
}

function closeCalendarDialog() {
  const dialog = document.getElementById('calendar-dialog');
  if (dialog.open) dialog.close();
}

function formatGoogleDate(raw, isEnd) {
  if (!raw) return '';
  const dateOnly = raw.match(/^\d{4}-\d{2}-\d{2}$/);
  if (dateOnly) {
    const base = new Date(raw + 'T00:00:00');
    if (isEnd) base.setDate(base.getDate() + 1);
    return base.toISOString().slice(0, 10).replace(/-/g, '');
  }
  const normalized = raw.length === 16 ? raw + ':00' : raw;
  const candidate = new Date(normalized);
  if (Number.isNaN(candidate.getTime())) return '';
  const year = candidate.getFullYear();
  const month = String(candidate.getMonth() + 1).padStart(2, '0');
  const day = String(candidate.getDate()).padStart(2, '0');
  const hour = String(candidate.getHours()).padStart(2, '0');
  const minute = String(candidate.getMinutes()).padStart(2, '0');
  const second = String(candidate.getSeconds()).padStart(2, '0');
  return `${year}${month}${day}T${hour}${minute}${second}`;
}

function openGoogleCalendarDraft() {
  const title = document.getElementById('calendar-title').value;
  const start = document.getElementById('calendar-start').value;
  const end = document.getElementById('calendar-end').value || start;
  const location = document.getElementById('calendar-location').value;
  const details = document.getElementById('calendar-details').value;
  const startStamp = formatGoogleDate(start, false);
  const endStamp = formatGoogleDate(end, true);
  const params = new URLSearchParams({
    action: 'TEMPLATE',
    text: title,
    location: location,
    details: details,
  });
  if (startStamp && endStamp) {
    params.set('dates', `${startStamp}/${endStamp}`);
  }
  window.open(`https://calendar.google.com/calendar/render?${params.toString()}`, '_blank');
}
