const $ = id => document.getElementById(id);
const state = {
  project: null, image: null, bitmap: null, objects: [], active: -1, draft: null,
  tool: 'box', rect: null, strokes: [], anchors: [], segments: [], preview: [],
  scale: 1, fit: 1, ox: 0, oy: 0, busy: false, drawing: null, space: false,
  dirty: 0, saved: 0, saving: null, saveTimer: null, undo: [], redo: [], epoch: 0,
  hint: null, cursor: null, hoverTimer: null, pathRequest: 0, datasetId: null, outlinePrompt: null,
};
const canvas = $('canvas');
const ctx = canvas.getContext('2d');
const styles = getComputedStyle(document.documentElement);
const color = name => styles.getPropertyValue(name).trim();
let toastTimer;
let afterSetup = null;
let creatingDataset = false;
function toast(message, error = false) {
  $('toast').textContent = message; $('toast').classList.toggle('error', error);
  $('toast').hidden = false; clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').hidden = true, error ? 7000 : 3500);
}
async function api(url, method = 'GET', body = null) {
  const headers = body && !(body instanceof FormData) ? {'Content-Type': 'application/json'} : {};
  if (state.datasetId) headers['X-Dataset-ID'] = state.datasetId;
  const response = await fetch(url, {method, headers, body: body ? body instanceof FormData ? body : JSON.stringify(body) : null});
  if (!response.ok) {
    let data; try { data = await response.json(); } catch { data = {}; }
    throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}). Check your input.`);
  }
  return response.headers.get('content-type')?.includes('application/json') ? response.json() : response.blob();
}
function run(action) { return (...args) => Promise.resolve().then(() => action(...args)).catch(error => toast(error.message, true)); }
function busy(value, text = 'Finding the boundary…') {
  state.busy = value; $('busyIndicator').hidden = !value; $('busyText').textContent = text; updateControls();
}
function maskCanvas() {
  const c = document.createElement('canvas'); c.width = state.image.width; c.height = state.image.height;
  return c;
}
async function loadBitmap(src) {
  const image = new Image(); image.src = src; await image.decode(); return image;
}
async function loadMask(src) {
  const image = await loadBitmap(src), c = document.createElement('canvas'); c.width = image.width; c.height = image.height;
  const cx = c.getContext('2d', {willReadFrequently: true}); cx.drawImage(image, 0, 0);
  const pixels = cx.getImageData(0, 0, c.width, c.height);
  // Stored grayscale masks and browser alpha masks are both accepted.
  const alphaMask = pixels.data.some((v, i) => i % 4 === 3 && v < 255);
  for (let i = 0; i < pixels.data.length; i += 4) {
    const on = alphaMask ? pixels.data[i + 3] >= 128 : pixels.data[i] >= 128;
    pixels.data[i] = pixels.data[i + 1] = pixels.data[i + 2] = 255; pixels.data[i + 3] = on ? 255 : 0;
  }
  cx.putImageData(pixels, 0, 0); return c;
}
function serializeObjects() { return state.objects.map(o => ({id: o.id, class_id: o.class_id, mask: o.canvas.toDataURL('image/png')})); }
function snapshot() {
  return {objects: serializeObjects(), draft: state.draft?.toDataURL('image/png'), active: state.active,
    rect: state.rect, strokes: structuredClone(state.strokes), anchors: structuredClone(state.anchors),
    segments: structuredClone(state.segments), outlinePrompt: structuredClone(state.outlinePrompt), reviewed: Boolean(state.image.reviewed)};
}
function history() { state.undo.push(snapshot()); if (state.undo.length > 12) state.undo.shift(); state.redo = []; updateControls(); }
async function restore(snap) {
  state.objects = await Promise.all(snap.objects.map(async o => ({...o, canvas: await loadMask(o.mask)})));
  state.draft = snap.draft ? await loadMask(snap.draft) : null;
  Object.assign(state, {active: snap.active, rect: snap.rect, strokes: snap.strokes, anchors: snap.anchors, segments: snap.segments, outlinePrompt: snap.outlinePrompt, preview: []});
  state.image.reviewed = snap.reviewed; changed(false); renderObjects(); updateControls(); render();
  if (state.active >= 0) $('classSelect').value = state.objects[state.active].class_id;
}
async function undo(redo = false) {
  if (state.busy || !state.image) return;
  const from = redo ? state.redo : state.undo, to = redo ? state.undo : state.redo;
  if (!from.length) return; to.push(snapshot()); busy(true, 'Restoring edit…');
  try { await restore(from.pop()); } finally { busy(false); }
}
function changed(unreview = true) {
  if (unreview) state.image.reviewed = false;
  state.dirty++; $('saveStatus').textContent = 'Saving draft…';
  clearTimeout(state.saveTimer); state.saveTimer = setTimeout(run(() => save()), 650);
  updateImageSummary();
}
async function save() {
  clearTimeout(state.saveTimer);
  if (state.saving) { await state.saving; if (state.dirty > state.saved) return save(); return; }
  if (!state.image || state.dirty === state.saved) return;
  const version = state.dirty, id = state.image.id;
  state.saving = api(`/api/images/${id}`, 'PUT', {objects: serializeObjects(), reviewed: Boolean(state.image.reviewed), revision: state.image.revision});
  try {
    const result = await state.saving; state.image.revision = result.revision; state.saved = version;
    $('saveStatus').textContent = state.draft || state.anchors.length ? 'Objects saved · selection not added' : 'All changes saved locally';
    updateImageSummary();
  } catch (error) { $('saveStatus').textContent = 'Save failed · keep this tab open'; throw error; }
  finally { state.saving = null; }
  if (state.dirty > state.saved) return save();
}
function updateImageSummary() {
  if (!state.project || !state.image) return;
  const item = state.project.images.find(i => i.id === state.image.id);
  Object.assign(item, {reviewed: state.image.reviewed, objects_count: state.objects.length, revision: state.image.revision});
  renderDataset();
}
async function refreshProject() { state.project = await api('/api/project'); state.datasetId = state.project.dataset_id; renderProject(); }
const imageURL = id => `/api/images/${id}/file?dataset=${encodeURIComponent(state.datasetId)}`;
async function refreshDatasets() {
  const datasets = await api('/api/datasets');
  $('datasetSelect').replaceChildren(...datasets.map(d => { const option = document.createElement('option'); option.value = d.id; option.textContent = d.name; return option; }));
  $('datasetSelect').value = state.datasetId;
}
function resetEditor() {
  state.epoch++; clearTimeout(state.hoverTimer); clearTimeout(state.saveTimer); clearPending();
  Object.assign(state, {image: null, bitmap: null, objects: [], active: -1, drawing: null, cursor: null, undo: [], redo: [], dirty: 0, saved: 0});
  $('search').value = ''; $('filter').value = 'all'; $('fileInput').value = ''; $('directoryInput').value = '';
  $('emptyState').hidden = false; $('canvasControls').hidden = true;
  $('fileName').textContent = 'A little guidance. A precise mask.'; $('imageDimensions').textContent = 'READY WHEN YOU ARE';
  $('saveStatus').textContent = 'Ready to import'; setTool('box'); render();
}
function renderProject() {
  $('projectName').textContent = state.project.name;
  $('classSelect').replaceChildren(...state.project.classes.map(c => {
    const option = document.createElement('option'); option.value = c.id; option.textContent = `${c.id} · ${c.name}`; return option;
  }));
  renderDataset(); renderObjects(); updateControls();
}
function renderDataset() {
  const all = state.project.images, done = all.filter(i => i.reviewed).length;
  $('imageCount').textContent = String(all.length).padStart(2, '0');
  $('progressText').textContent = `${done} / ${all.length} reviewed`;
  $('progressPct').textContent = `${all.length ? Math.round(done / all.length * 100) : 0}%`;
  $('progress').value = all.length ? done / all.length * 100 : 0;
  const query = $('search').value.toLowerCase(), filter = $('filter').value;
  const items = all.filter(i => i.name.toLowerCase().includes(query) && (filter === 'all' || Boolean(i.reviewed) === (filter === 'reviewed')));
  $('imageList').replaceChildren(...items.map(i => {
    const b = document.createElement('button'); b.className = 'image-item' + (state.image?.id === i.id ? ' active' : '');
    b.setAttribute('aria-current', state.image?.id === i.id ? 'true' : 'false');
    const img = new Image(); img.src = imageURL(i.id); img.alt = ''; img.loading = 'lazy';
    const info = document.createElement('span'); info.className = 'image-info';
    const name = document.createElement('strong'); name.textContent = i.name;
    const details = document.createElement('small'); details.textContent = `${i.objects_count} object${i.objects_count === 1 ? '' : 's'} · ${i.reviewed ? 'reviewed' : 'draft'}`;
    info.append(name, details); const mark = document.createElement('span'); mark.className = 'review-marker'; mark.textContent = i.reviewed ? '✓' : '';
    b.append(img, info, mark); b.onclick = run(() => openImage(i.id)); return b;
  }));
  if (!items.length) { const p = document.createElement('p'); p.className = 'muted small'; p.textContent = all.length ? 'No matching images.' : 'Your dataset starts here.'; $('imageList').append(p); }
  const position = all.findIndex(i => i.id === state.image?.id);
  $('imagePosition').textContent = position < 0 ? '— / —' : `${position + 1} / ${all.length}`;
  $('prevBtn').disabled = position <= 0 || state.busy; $('nextBtn').disabled = position < 0 || position >= all.length - 1 || state.busy;
}
function hasPending() { return Boolean(state.draft || state.anchors.length || state.rect || state.outlinePrompt); }
function allowDiscard() { return !hasPending() || confirm('Discard the unfinished selection? Add it as an object to keep it.'); }
async function openImage(id) {
  if (state.busy || id === state.image?.id || !allowDiscard()) return;
  await save(); busy(true, 'Opening image…');
  try {
    const [image, bitmap] = await Promise.all([api(`/api/images/${id}`), loadBitmap(imageURL(id))]);
    const objects = await Promise.all(image.objects.map(async o => ({id: o.id, class_id: o.class_id, canvas: await loadMask(o.mask)})));
    state.epoch++; Object.assign(state, {image, bitmap, objects, active: -1, draft: null, rect: null, outlinePrompt: null, strokes: [], anchors: [], segments: [], preview: [], undo: [], redo: [], dirty: 0, saved: 0, hint: null});
    $('emptyState').hidden = true; $('canvasControls').hidden = false;
    $('fileName').textContent = image.name; $('imageDimensions').textContent = `${image.width} × ${image.height} PX`;
    $('saveStatus').textContent = image.reviewed ? 'Reviewed · saved locally' : 'All changes saved locally';
    fitImage(); renderDataset(); renderObjects();
  } finally { busy(false); }
}
async function navigate(delta) {
  if (!state.image) return;
  const idx = state.project.images.findIndex(i => i.id === state.image.id);
  const image = state.project.images[idx + delta]; if (image) await openImage(image.id);
}
function fitImage() {
  if (!state.image) return;
  const box = canvas.getBoundingClientRect();
  state.fit = Math.min((box.width - 48) / state.image.width, (box.height - 64) / state.image.height);
  state.scale = state.fit; state.ox = (box.width - state.image.width * state.scale) / 2;
  state.oy = (box.height - state.image.height * state.scale) / 2; render();
}
function resize() {
  const box = canvas.getBoundingClientRect(), dpr = devicePixelRatio || 1;
  canvas.width = Math.round(box.width * dpr); canvas.height = Math.round(box.height * dpr);
  if (state.image) fitImage(); else render();
}
function zoom(factor, x = canvas.clientWidth / 2, y = canvas.clientHeight / 2) {
  if (!state.image) return;
  const old = state.scale; state.scale = Math.max(state.fit * .25, Math.min(state.fit * 20, old * factor));
  state.ox = x - (x - state.ox) * state.scale / old; state.oy = y - (y - state.oy) * state.scale / old; render();
}
function drawMask(mask, tint, alpha = .4) {
  // Cache tinted masks; brush updates invalidate this cache once per stroke point.
  if (!mask._tinted || mask._color !== tint) {
    const c = document.createElement('canvas'); c.width = mask.width; c.height = mask.height;
    const cx = c.getContext('2d'); cx.drawImage(mask, 0, 0); cx.globalCompositeOperation = 'source-in';
    cx.fillStyle = tint; cx.fillRect(0, 0, c.width, c.height); mask._tinted = c; mask._color = tint;
  }
  ctx.globalAlpha = alpha; ctx.drawImage(mask._tinted, 0, 0); ctx.globalAlpha = 1;
}
function render() {
  const dpr = devicePixelRatio || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!state.bitmap) return;
  ctx.translate(state.ox, state.oy); ctx.scale(state.scale, state.scale); ctx.drawImage(state.bitmap, 0, 0);
  if ($('showMasks').checked) {
    state.objects.forEach((o, i) => drawMask(o.canvas, state.project.classes[o.class_id].color, state.active === i ? .55 : .32));
    if (state.draft) drawMask(state.draft, state.project.classes[+$('classSelect').value].color, .48);
  }
  ctx.lineWidth = 1.5 / state.scale; ctx.strokeStyle = color('--accent');
  if (state.rect) { ctx.setLineDash([5 / state.scale, 4 / state.scale]); ctx.strokeRect(...state.rect); ctx.setLineDash([]); }
  if (state.anchors.length) {
    const points = state.segments.flat(); if (points.length) { ctx.beginPath(); points.forEach((p, i) => i ? ctx.lineTo(...p) : ctx.moveTo(...p)); ctx.stroke(); }
    if (state.preview.length) { ctx.setLineDash([4 / state.scale, 3 / state.scale]); ctx.beginPath(); state.preview.forEach((p, i) => i ? ctx.lineTo(...p) : ctx.moveTo(...p)); ctx.stroke(); ctx.setLineDash([]); }
    state.anchors.forEach(p => { ctx.beginPath(); ctx.arc(...p, 3.5 / state.scale, 0, Math.PI * 2); ctx.fillStyle = color('--accent'); ctx.fill(); });
  }
  if (state.drawing?.kind === 'box') { const p = state.drawing.start, q = state.drawing.last; ctx.strokeRect(p[0], p[1], q[0] - p[0], q[1] - p[1]); }
  if (state.drawing?.kind === 'lasso') { ctx.beginPath(); state.drawing.points.forEach((p, i) => i ? ctx.lineTo(...p) : ctx.moveTo(...p)); ctx.stroke(); }
  state.strokes.forEach(s => { ctx.strokeStyle = s.foreground ? color('--accent') : color('--danger'); ctx.lineWidth = s.radius * 2; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.globalAlpha = .75; ctx.beginPath(); s.points.forEach((p, i) => i ? ctx.lineTo(...p) : ctx.moveTo(...p)); if (s.points.length === 1) ctx.lineTo(s.points[0][0] + .1, s.points[0][1]); ctx.stroke(); ctx.globalAlpha = 1; });
  if (state.cursor && ['add', 'erase'].includes(state.tool) || state.cursor && state.hint) {
    ctx.beginPath(); ctx.arc(...state.cursor, +$('brushSize').value, 0, Math.PI * 2); ctx.strokeStyle = state.tool === 'erase' || state.hint === 'bg' ? color('--danger') : color('--accent'); ctx.lineWidth = 1 / state.scale; ctx.stroke();
  }
  $('zoomLevel').textContent = `${Math.round(state.scale * 100)}%`;
}
function renderObjects() {
  $('objectCount').textContent = state.objects.length;
  $('objectList').replaceChildren(...state.objects.map((o, i) => {
    const row = document.createElement('div'); row.className = 'object-row';
    const b = document.createElement('button'); b.className = 'object-select' + (state.active === i ? ' active' : '');
    const swatch = document.createElement('span'); swatch.className = 'swatch'; swatch.style.background = state.project.classes[o.class_id].color;
    const label = document.createElement('span'); label.textContent = `${state.project.classes[o.class_id].name} ${i + 1}`; b.append(swatch, label);
    b.onclick = () => { if (state.busy || !allowDiscard()) return; clearPending(); state.active = i; $('classSelect').value = o.class_id; setTool('add'); renderObjects(); render(); };
    const del = document.createElement('button'); del.className = 'delete-object'; del.textContent = '×'; del.setAttribute('aria-label', `Delete object ${i + 1}`);
    del.onclick = () => { if (state.busy) return; history(); state.objects.splice(i, 1); state.active = -1; changed(); renderObjects(); render(); updateControls(); };
    row.append(b, del); return row;
  }));
  if (!state.objects.length) { const p = document.createElement('p'); p.className = 'muted small'; p.textContent = 'Select an area, then add your first object.'; $('objectList').append(p); }
}
function clearPending() { Object.assign(state, {draft: null, rect: null, outlinePrompt: null, strokes: [], anchors: [], segments: [], preview: [], hint: null}); state.pathRequest++; }
function newObject() {
  if (!state.image || state.busy || !allowDiscard()) return;
  history(); clearPending(); state.active = -1; setTool('box'); renderObjects(); render();
}
const guides = {
  box: ['01 / SELECT', 'Start with a simple box.', 'Draw around one object, leaving background outside the box. Box assist finds a first mask.'],
  magnetic: ['01 / FOLLOW THE EDGE', 'Let the boundary guide you.', 'Click anchors along the object edge. The live outline follows strong edges between them. Press Enter to close.'],
  polygon: ['01 / DRAW', 'Every vertex is yours.', 'Click around the object to place vertices. Press Enter to close the polygon, then refine with brushes.'],
  smart: ['01 / OUTLINE & SNAP', 'A rough polygon. A tighter mask.', 'Click a loose polygon around one object, leaving a little background inside. Press Enter to shrink to the estimated foreground.'],
  lasso: ['01 / DRAW & SNAP', 'Draw once around the object.', 'Hold the left mouse button and draw a loose loop around one object. Release to close and estimate the foreground inside.'],
  add: ['02 / REFINE', 'Keep the details that matter.', 'Paint to add pixels to the selected object or current selection. Use a small brush and zoom in near edges.'],
  erase: ['02 / REFINE', 'Clean up the boundary.', 'Paint to remove pixels from the selected object or current selection. Exact holes are preserved in the stored mask.'],
};
function setTool(tool) {
  if (state.busy) return;
  if (state.anchors.length && state.tool !== tool) { toast('Finish or discard the outline before changing tools.'); return; }
  state.tool = tool; state.hint = null;
  document.querySelectorAll('[data-tool]').forEach(b => b.setAttribute('aria-pressed', b.dataset.tool === tool));
  const [number, title, text] = guides[tool]; $('guideNumber').textContent = number; $('guideTitle').textContent = title; $('guideText').textContent = text;
  canvas.style.cursor = state.space ? 'grab' : 'crosshair'; updateControls(); render();
}
function updateControls() {
  const image = Boolean(state.image), locked = state.busy;
  $('reviewBtn').disabled = !image || locked || hasPending();
  $('commitBtn').disabled = !state.draft || locked;
  $('cancelBtn').disabled = !hasPending() || locked;
  $('finishBtn').disabled = state.anchors.length < 3 || locked;
  $('undoBtn').disabled = !state.undo.length || locked; $('redoBtn').disabled = !state.redo.length || locked;
  $('newObjectBtn').disabled = !image || locked; $('classSelect').disabled = locked;
  $('brushSettings').hidden = !['add', 'erase'].includes(state.tool) && !state.hint;
  $('cutSettings').hidden = !(state.rect || state.outlinePrompt) || state.active !== -1;
  $('fgHint').classList.toggle('active', state.hint === 'fg'); $('bgHint').classList.toggle('active', state.hint === 'bg');
  $('fgHint').setAttribute('aria-pressed', state.hint === 'fg'); $('bgHint').setAttribute('aria-pressed', state.hint === 'bg');
  document.querySelectorAll('[data-tool]').forEach(b => b.disabled = locked);
  for (const id of ['newDatasetBtn', 'datasetSelect', 'settingsBtn', 'importBtn']) $(id).disabled = locked;
  if (state.project) renderDataset();
}
function point(event) {
  const box = canvas.getBoundingClientRect();
  return [Math.max(0, Math.min(state.image.width - 1, Math.round((event.clientX - box.left - state.ox) / state.scale))), Math.max(0, Math.min(state.image.height - 1, Math.round((event.clientY - box.top - state.oy) / state.scale)))];
}
function inside(event) {
  const b = canvas.getBoundingClientRect(), x = (event.clientX - b.left - state.ox) / state.scale, y = (event.clientY - b.top - state.oy) / state.scale;
  return x >= 0 && y >= 0 && x < state.image.width && y < state.image.height;
}
function paint(target, a, b, erase) {
  const c = target.getContext('2d'); c.globalCompositeOperation = erase ? 'destination-out' : 'source-over';
  c.strokeStyle = 'white'; c.fillStyle = 'white'; c.lineWidth = +$('brushSize').value * 2; c.lineCap = 'round'; c.lineJoin = 'round';
  c.beginPath(); c.moveTo(...a); c.lineTo(...b); c.stroke(); c.beginPath(); c.arc(...b, +$('brushSize').value, 0, Math.PI * 2); c.fill();
  c.globalCompositeOperation = 'source-over'; target._tinted = null;
}
canvas.addEventListener('pointerdown', run(async event => {
  if (!state.image || state.busy || event.button > 2) return;
  event.preventDefault();
  canvas.focus(); canvas.setPointerCapture(event.pointerId);
  if (state.space || event.button === 1 || event.button === 2) { state.drawing = {kind: 'pan', start: [event.clientX, event.clientY], offset: [state.ox, state.oy]}; canvas.style.cursor = 'grabbing'; return; }
  if (!inside(event)) return;
  const p = point(event);
  if (state.hint && (state.rect || state.outlinePrompt)) {
    history(); const stroke = {points: [p], radius: +$('brushSize').value, foreground: state.hint === 'fg'};
    state.strokes.push(stroke); state.drawing = {kind: 'hint', stroke}; render(); return;
  }
  if (['add', 'erase'].includes(state.tool)) {
    if (!state.draft && state.active < 0) { if (state.tool === 'erase') { toast('Select an object or create a selection first.'); return; } history(); state.draft = maskCanvas(); } else history();
    const target = state.active >= 0 ? state.objects[state.active].canvas : state.draft;
    paint(target, p, p, state.tool === 'erase'); state.drawing = {kind: 'paint', last: p, target}; render(); updateControls(); return;
  }
  if (state.tool === 'box') {
    if (hasPending() && !allowDiscard()) return;
    history(); clearPending(); state.active = -1; state.drawing = {kind: 'box', start: p, last: p}; renderObjects(); render(); return;
  }
  if (state.tool === 'lasso') {
    if (hasPending() && !allowDiscard()) return;
    history(); clearPending(); state.active = -1; state.drawing = {kind: 'lasso', points: [p]}; renderObjects(); render(); return;
  }
  if (['polygon', 'magnetic', 'smart'].includes(state.tool)) {
    if (state.draft) { toast('Add or discard your current selection before drawing another outline.'); return; }
    if (state.anchors.length >= 3 && Math.hypot(p[0] - state.anchors[0][0], p[1] - state.anchors[0][1]) * state.scale < 10) { await finishOutline(); return; }
    history(); state.active = -1; state.pathRequest++;
    if (state.anchors.length) {
      const start = state.anchors.at(-1);
      if (state.tool === 'magnetic') {
        busy(true, 'Following the edge…');
        try { const result = await api(`/api/images/${state.image.id}/magnetic`, 'POST', {start, end: p}); state.segments.push(result.points); }
        finally { busy(false); }
      } else state.segments.push([start, p]);
    }
    state.anchors.push(p); state.preview = []; renderObjects(); updateControls(); render();
  }
}));
canvas.addEventListener('pointermove', event => {
  if (!state.image) return; const p = point(event); state.cursor = inside(event) ? p : null;
  const drawing = state.drawing;
  if (drawing) {
    if (drawing.kind === 'pan') { state.ox = drawing.offset[0] + event.clientX - drawing.start[0]; state.oy = drawing.offset[1] + event.clientY - drawing.start[1]; }
    if (drawing.kind === 'box') drawing.last = p;
    if (drawing.kind === 'lasso' && drawing.points.length < 3000 && Math.hypot(p[0] - drawing.points.at(-1)[0], p[1] - drawing.points.at(-1)[1]) * state.scale >= 2) drawing.points.push(p);
    if (drawing.kind === 'paint') { paint(drawing.target, drawing.last, p, state.tool === 'erase'); drawing.last = p; }
    if (drawing.kind === 'hint') drawing.stroke.points.push(p);
    render(); return;
  }
  if (state.anchors.length && !state.busy) {
    if (['polygon', 'smart'].includes(state.tool)) state.preview = [state.anchors.at(-1), p];
    else if (state.tool === 'magnetic') {
      clearTimeout(state.hoverTimer); const request = ++state.pathRequest, epoch = state.epoch, start = state.anchors.at(-1), id = state.image.id;
      state.hoverTimer = setTimeout(async () => {
        try { const result = await api(`/api/images/${id}/magnetic`, 'POST', {start, end: p});
          if (request === state.pathRequest && epoch === state.epoch && state.tool === 'magnetic' && !state.busy) { state.preview = result.points; render(); }
        } catch { /* A failed hover does not prevent manual anchors or hide a failed committed path. */ }
      }, 85);
    }
  }
  render();
});
async function endDrawing() {
  const drawing = state.drawing; state.drawing = null;
  canvas.style.cursor = state.space ? 'grab' : 'crosshair';
  if (!drawing) return;
  if (drawing.kind === 'box') {
    const [a, b] = [drawing.start, drawing.last];
    state.rect = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(a[0] - b[0]) + 1, Math.abs(a[1] - b[1]) + 1];
    await computeCut();
  } else if (drawing.kind === 'lasso') {
    if (drawing.points.length < 3) { toast('Draw a loop around an object.', true); return; }
    state.outlinePrompt = drawing.points;
    await computeCut();
    setTool('add');
  } else if (drawing.kind === 'paint') {
    if (state.active >= 0) changed(); else $('saveStatus').textContent = 'Selection not added · click Add object';
  }
  updateControls(); render();
}
canvas.addEventListener('pointerup', run(endDrawing));
canvas.addEventListener('pointercancel', () => { state.drawing = null; render(); });
canvas.addEventListener('contextmenu', event => event.preventDefault());
canvas.addEventListener('pointerleave', () => { state.cursor = null; render(); });
canvas.addEventListener('wheel', event => { if (!state.image) return; event.preventDefault(); const box = canvas.getBoundingClientRect(); zoom(Math.exp(-event.deltaY * .0015), event.clientX - box.left, event.clientY - box.top); }, {passive: false});
async function computeCut() {
  if (!(state.rect || state.outlinePrompt) || state.busy) return;
  busy(true);
  try {
    const outline = Boolean(state.outlinePrompt);
    const result = await api(`/api/images/${state.image.id}/${outline ? 'outline-assist' : 'grabcut'}`, 'POST', {...(outline ? {points: state.outlinePrompt} : {rect: state.rect}), strokes: state.strokes});
    state.draft = await loadMask(result.mask); $('saveStatus').textContent = 'Selection not added · refine, then Add object';
  }
  finally { state.hint = null; busy(false); render(); }
}
async function finishOutline() {
  if (state.anchors.length < 3 || state.busy) return;
  history(); busy(true, 'Closing outline…'); state.pathRequest++;
  try {
    const start = state.anchors.at(-1), end = state.anchors[0];
    const closing = state.tool === 'magnetic' ? (await api(`/api/images/${state.image.id}/magnetic`, 'POST', {start, end})).points : [start, end];
    const points = [...state.segments.flat(), ...closing]; const draft = maskCanvas(), c = draft.getContext('2d');
    c.fillStyle = 'white'; c.beginPath(); points.forEach((p, i) => i ? c.lineTo(...p) : c.moveTo(...p)); c.closePath(); c.fill();
    const automatic = state.tool === 'smart';
    clearPending(); state.draft = draft;
    state.outlinePrompt = points.length > 3000 ? points.filter((_, i) => i % Math.ceil(points.length / 3000) === 0) : points;
    if (automatic) {
      const result = await api(`/api/images/${state.image.id}/outline-assist`, 'POST', {points: state.outlinePrompt, strokes: []});
      state.draft = await loadMask(result.mask);
    }
    $('saveStatus').textContent = 'Selection not added · refine, then Add object';
  } finally { busy(false); setTool('add'); render(); }
}
function hasPixels(c) { const data = c.getContext('2d', {willReadFrequently: true}).getImageData(0, 0, c.width, c.height).data; for (let i = 3; i < data.length; i += 4) if (data[i] >= 128) return true; return false; }
async function commit() {
  if (!state.draft || state.busy) return;
  if (!hasPixels(state.draft)) throw new Error('Selection is empty. Paint an area or discard it.');
  history(); state.objects.push({id: crypto.randomUUID(), class_id: +$('classSelect').value, canvas: state.draft});
  clearPending(); state.active = state.objects.length - 1; changed(); renderObjects(); updateControls(); render(); await save();
}
async function review() {
  if (!state.image || state.busy) return;
  if (hasPending()) throw new Error('Add or discard the unfinished selection before review.');
  if (state.objects.some(o => !hasPixels(o.canvas))) throw new Error('An object is empty. Delete it before review.');
  state.image.reviewed = true; changed(false); await save();
  const index = state.project.images.findIndex(i => i.id === state.image.id);
  const next = [...state.project.images.slice(index + 1), ...state.project.images.slice(0, index)].find(i => !i.reviewed);
  if (next) await openImage(next.id); else toast('All images reviewed. Your dataset is ready to export.');
}
async function importFiles(files) {
  if (!files.length) return; busy(true, 'Importing images…');
  try {
    const form = new FormData(); Array.from(files).forEach(file => form.append('files', file));
    const result = await api('/api/import/upload', 'POST', form); await finishImport(result);
  } finally { busy(false); }
}
async function finishImport(result) {
  $('importResult').textContent = `${result.added} imported · ${result.duplicates} duplicates skipped${result.errors.length ? '\n' + result.errors.map(e => `${e.name}: ${e.error}`).join('\n') : ''}`;
  const currentClass = $('classSelect').value; await refreshProject(); $('classSelect').value = currentClass || '0';
  // Opening waits until busy state clears, to preserve the current image on errors.
  if (!state.image && state.project.images.length) { busy(false); await openImage(state.project.images[0].id); }
  if (!result.errors.length && result.added) { $('importDialog').close(); toast(`${result.added} images imported.`); }
}
async function exportData() {
  await save(); $('downloadBtn').disabled = true; $('exportResult').textContent = 'Checking masks and packaging reviewed images…';
  try {
    const blob = await api('/api/export', 'POST', {format: $('exportFormat').value, val_fraction: +$('valFraction').value / 100, seed: +$('seed').value, epsilon: +$('epsilon').value, allow_lossy: $('allowLossy').checked});
    if (blob.size < 22) throw new Error('The download was empty. Keep this tab open and try exporting again.');
    const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = `magnetlabel-${$('exportFormat').value}.zip`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 10000);
    $('exportResult').textContent = 'Dataset downloaded. Inspect manifest.json, then extract the ZIP to train.';
  } catch (error) { $('exportResult').textContent = error.message; throw error; }
  finally { $('downloadBtn').disabled = false; }
}
document.querySelectorAll('[data-tool]').forEach(button => button.onclick = () => setTool(button.dataset.tool));
$('search').oninput = renderDataset; $('filter').onchange = renderDataset;
$('undoBtn').onclick = run(() => undo()); $('redoBtn').onclick = run(() => undo(true));
$('prevBtn').onclick = run(() => navigate(-1)); $('nextBtn').onclick = run(() => navigate(1));
$('fitBtn').onclick = fitImage; $('zoomIn').onclick = () => zoom(1.25); $('zoomOut').onclick = () => zoom(.8); $('showMasks').onchange = render;
$('brushSize').oninput = () => { $('brushValue').textContent = `${$('brushSize').value} px`; render(); };
$('newObjectBtn').onclick = newObject; $('finishBtn').onclick = run(finishOutline); $('commitBtn').onclick = run(commit);
$('cancelBtn').onclick = () => { if (!state.busy) { history(); clearPending(); updateControls(); render(); $('saveStatus').textContent = 'All added objects saved locally'; } };
$('reviewBtn').onclick = run(review); $('recomputeBtn').onclick = run(async () => { history(); await computeCut(); });
$('classSelect').onchange = () => { if (state.active >= 0) { history(); state.objects[state.active].class_id = +$('classSelect').value; changed(); renderObjects(); } render(); };
for (const [id, hint] of [['fgHint', 'fg'], ['bgHint', 'bg']]) $(id).onclick = () => { state.hint = state.hint === hint ? null : hint; updateControls(); };
function showSettings(create = false) {
  creatingDataset = create;
  $('settingsTitle').textContent = create ? 'Start a fresh dataset' : 'Set up your labels';
  $('nameInput').value = create ? 'My segmentation project' : state.project.name;
  $('labelCount').value = create ? 1 : state.project.classes.length;
  renderClassFields(create ? ['object'] : state.project.classes.map(c => c.name));
  $('settingsDialog').showModal();
}
function renderClassFields(names = null) {
  const existing = names || Array.from($('classNameFields').querySelectorAll('input')).map(i => i.value);
  const count = Math.max(1, Math.min(100, parseInt($('labelCount').value, 10) || 1));
  const lockedCount = !creatingDataset && state.project.images.some(i => i.objects_count) ? state.project.classes.length : 0;
  $('labelCount').min = Math.max(1, lockedCount);
  $('classNameFields').replaceChildren(...Array.from({length: count}, (_, i) => {
    const wrapper = document.createElement('div');
    const label = document.createElement('label'); label.className = 'field-label'; label.htmlFor = `className${i}`; label.textContent = `Label ${i + 1} · class ID ${i}`;
    const input = document.createElement('input'); input.id = `className${i}`; input.maxLength = 80; input.value = existing[i] || ''; input.placeholder = `Name for label ${i + 1}`;
    input.readOnly = i < lockedCount;
    wrapper.append(label, input); return wrapper;
  }));
}
function withSetup(action) {
  if (!state.project.configured) { afterSetup = action; showSettings(); }
  else action();
}
for (const id of ['importBtn', 'emptyImport']) $(id).onclick = () => withSetup(() => { $('importResult').textContent = ''; $('importDialog').showModal(); });
$('helpBtn').onclick = () => $('helpDialog').showModal();
for (const id of ['settingsBtn', 'editLabelsBtn']) $(id).onclick = () => { afterSetup = null; showSettings(); };
$('newDatasetBtn').onclick = run(async () => { if (state.busy || !allowDiscard()) return; await save(); afterSetup = null; showSettings(true); });
$('datasetSelect').onchange = run(async () => {
  const id = $('datasetSelect').value;
  if (state.busy || !allowDiscard()) { $('datasetSelect').value = state.datasetId; return; }
  await save();
  busy(true, 'Switching dataset…');
  let project;
  try {
    project = await api(`/api/datasets/${id}/activate`, 'POST');
    state.project = project; state.datasetId = project.dataset_id; resetEditor(); renderProject();
  } finally { busy(false); }
  setTool('box');
  if (project.images.length) await openImage(project.images[0].id);
});
$('focusBtn').onclick = () => {
  const focus = $('workspace').classList.toggle('focus-mode');
  $('focusBtn').setAttribute('aria-pressed', focus); $('focusBtn').textContent = focus ? 'Show panels' : 'Focus image';
};
$('labelCount').oninput = () => renderClassFields();
$('saveSettingsBtn').onclick = run(async () => {
  if (state.busy) return;
  if (!$('labelCount').checkValidity()) throw new Error(`Choose a label count between ${$('labelCount').min} and 100.`);
  const classes = Array.from($('classNameFields').querySelectorAll('input')).map(i => i.value.trim());
  if (classes.some(c => !c)) throw new Error('Give every label a name before continuing.');
  const currentClass = $('classSelect').value;
  await save();
  $('saveSettingsBtn').disabled = true;
  try { state.project = await api(creatingDataset ? '/api/datasets' : '/api/project', creatingDataset ? 'POST' : 'PUT', {name: $('nameInput').value, classes}); }
  finally { $('saveSettingsBtn').disabled = false; }
  state.datasetId = state.project.dataset_id;
  if (creatingDataset) resetEditor();
  renderProject(); await refreshDatasets();
  $('classSelect').value = creatingDataset ? '0' : currentClass || '0'; $('settingsDialog').close(); toast(creatingDataset ? 'Fresh dataset ready. Import your images.' : 'Project labels saved.');
  if (creatingDataset) { $('importResult').textContent = ''; $('importDialog').showModal(); }
  const next = afterSetup; afterSetup = null; if (next) await next();
});
$('exportBtn').onclick = run(async () => { await save(); const reviewed = state.project.images.filter(i => i.reviewed).length; $('exportSummary').textContent = `${reviewed} reviewed images included. ${state.project.images.length - reviewed} drafts excluded. At least two reviewed images are required.`; $('exportResult').textContent = ''; $('exportDialog').showModal(); });
$('downloadBtn').onclick = run(exportData);
$('fileInput').onchange = run(event => importFiles(event.target.files)); $('directoryInput').onchange = run(event => importFiles(Array.from(event.target.files).filter(f => /\.(png|jpe?g|webp|bmp|tiff?)$/i.test(f.name))));
$('folderImportBtn').onclick = run(async () => { busy(true, 'Importing folder…'); try { await finishImport(await api('/api/import/folder', 'POST', {path: $('folderPath').value, recursive: $('recursive').checked})); } finally { busy(false); } });
$('dropZone').ondragover = event => event.preventDefault(); $('dropZone').ondrop = run(event => { event.preventDefault(); return importFiles(event.dataTransfer.files); });
$('demoBtn').onclick = () => withSetup(run(async () => { busy(true, 'Preparing sample images…'); try { state.project = await api('/api/demo', 'POST'); renderProject(); } finally { busy(false); } await openImage(state.project.images[0].id); }));
document.addEventListener('keydown', run(async event => {
  if (event.target.matches('input,textarea,select') || document.querySelector('dialog[open]')) return;
  if (event.code === 'Space') { event.preventDefault(); state.space = true; canvas.style.cursor = 'grab'; return; }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); await undo(event.shiftKey); return; }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); await save(); return; }
  if (event.ctrlKey || event.metaKey || event.altKey || state.busy) return;
  const key = event.key.toLowerCase();
  if (event.target.closest('button,a') && ['enter', ' '].includes(key)) return;
  const tools = {b: 'box', m: 'magnetic', p: 'polygon', s: 'smart', l: 'lasso', a: 'add', e: 'erase'};
  if (tools[key]) { event.preventDefault(); setTool(tools[key]); }
  if (key === 'n') newObject();
  if (key === 'arrowright') { event.preventDefault(); await navigate(1); }
  if (key === 'arrowleft') { event.preventDefault(); await navigate(-1); }
  if (key === 'enter') { event.preventDefault(); if (state.anchors.length) await finishOutline(); else await commit(); }
  if (key === 'escape' && state.image) { history(); clearPending(); state.active = -1; renderObjects(); updateControls(); render(); }
}));
document.addEventListener('keyup', event => { if (event.code === 'Space') { state.space = false; canvas.style.cursor = 'crosshair'; } });
window.addEventListener('blur', () => state.space = false);
window.addEventListener('beforeunload', event => { if (state.dirty > state.saved || hasPending()) { event.preventDefault(); event.returnValue = ''; } });
new ResizeObserver(resize).observe($('canvasWrap'));
run(async () => { await refreshProject(); await refreshDatasets(); if (state.project.images.length) await openImage(state.project.images.find(i => !i.reviewed)?.id || state.project.images[0].id); })();
