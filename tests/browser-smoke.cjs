/* Run against a fresh server: NODE_PATH may point to an existing Playwright installation.
   This exercises the real UI and backend without injecting app state or mocking requests. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.BROWSER_CHANNEL || 'msedge'});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}, deviceScaleFactor: 1});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const base = process.env.MAGNETLABEL_URL || 'http://127.0.0.1:8766';
  const output = process.env.SCREENSHOT_DIR || 'docs/screenshots';
  await fs.mkdir(output, {recursive: true});
  try {
    await page.goto(base);
    await page.locator('#demoBtn').waitFor({state: 'visible'});
    await page.screenshot({path: path.join(output, 'welcome.png')});
    await page.locator('#demoBtn').click();
    await page.locator('#settingsDialog').waitFor({state: 'visible'});
    await page.locator('#nameInput').fill('Leaf study');
    await page.locator('#labelCount').fill('2');
    await page.locator('#className0').fill('leaf');
    await page.locator('#className1').fill('petiole');
    await page.locator('#saveSettingsBtn').click();
    await page.locator('#settingsDialog').waitFor({state: 'hidden'});
    await page.locator('#canvasControls').waitFor({state: 'visible'});
    const imagePoint = async (x, y) => {
      const b = await page.locator('#canvas').boundingBox();
      const scale = Math.min((b.width - 48) / 960, (b.height - 64) / 640);
      return [b.x + (b.width - 960 * scale) / 2 + x * scale, b.y + (b.height - 640 * scale) / 2 + y * scale];
    };
    const clickPoint = async (x, y) => page.mouse.click(...await imagePoint(x, y));
    const drag = async (x1, y1, x2, y2) => {
      await page.mouse.move(...await imagePoint(x1, y1)); await page.mouse.down();
      await page.mouse.move(...await imagePoint(x2, y2), {steps: 12}); await page.mouse.up();
    };
    await drag(270, 120, 660, 475);
    await page.waitForFunction(() => !document.querySelector('#commitBtn').disabled, {timeout: 30000});
    await page.locator('#commitBtn').click();
    await page.waitForFunction(() => document.querySelector('#saveStatus').textContent.includes('All changes saved'));
    let project = await (await page.request.get(base + '/api/project')).json();
    assert.equal(project.images[0].objects_count, 1);
    const firstId = project.images[0].id;
    await page.locator('#classSelect').selectOption('1');
    await page.waitForFunction(() => document.querySelector('#saveStatus').textContent.includes('All changes saved'));
    let relabeled = await (await page.request.get(`${base}/api/images/${firstId}`)).json();
    assert.equal(relabeled.objects[0].class_id, 1);
    await page.locator('#undoBtn').click();
    await page.waitForFunction(() => document.querySelector('#saveStatus').textContent.includes('All changes saved'));
    assert.equal(await page.locator('#classSelect').inputValue(), '0');
    // Review the first image; editing it later must clear reviewed state.
    await page.locator('#reviewBtn').click();
    await page.waitForFunction(() => document.querySelector('#fileName').textContent === 'demo_leaf_2.png');
    await page.locator('.image-item').first().click();
    await page.waitForFunction(() => document.querySelector('#fileName').textContent === 'demo_leaf_1.png');
    await page.locator('.object-select').first().click();
    await page.locator('[data-tool="erase"]').click();
    await drag(455, 295, 460, 300);
    await page.waitForFunction(() => document.querySelector('#saveStatus').textContent.includes('All changes saved'));
    project = await (await page.request.get(base + '/api/project')).json();
    assert.equal(project.images[0].reviewed, 0);
    await page.locator('#undoBtn').click();
    await page.waitForFunction(() => document.querySelector('#saveStatus').textContent.includes('All changes saved'));
    await page.locator('#reviewBtn').click();
    await page.waitForFunction(() => document.querySelector('#fileName').textContent === 'demo_leaf_2.png');
    await page.locator('[data-tool="magnetic"]').click();
    await clickPoint(430, 175);
    await page.mouse.move(...await imagePoint(645, 225));
    // Allow at least one preview request to complete, then place genuine anchors.
    await page.waitForResponse(r => r.url().endsWith('/magnetic') && r.status() === 200);
    for (const [x, y] of [[645, 225], [660, 355], [570, 425], [445, 435], [345, 395]]) {
      await clickPoint(x, y);
      await page.waitForFunction(() => document.querySelector('#busyIndicator').hidden);
    }
    await page.locator('#finishBtn').click();
    await page.waitForFunction(() => !document.querySelector('#commitBtn').disabled);
    await page.locator('#commitBtn').click();
    await page.waitForFunction(() => document.querySelector('#saveStatus').textContent.includes('All changes saved'));
    await page.screenshot({path: path.join(output, 'workspace.png')});
    await page.locator('#reviewBtn').click();
    await page.waitForFunction(() => document.querySelector('#fileName').textContent === 'demo_leaf_3.png');
    // Polygon tool on the third image.
    await page.locator('[data-tool="polygon"]').click();
    for (const p of [[455, 165], [585, 135], [680, 215], [695, 345], [605, 415], [480, 425], [380, 385], [415, 275]]) await clickPoint(...p);
    await page.locator('#canvas').press('Enter');
    await page.waitForFunction(() => !document.querySelector('#commitBtn').disabled);
    await page.locator('#commitBtn').click();
    await page.waitForFunction(() => document.querySelector('#saveStatus').textContent.includes('All changes saved'));
    await page.locator('#reviewBtn').click();
    await page.waitForFunction(() => document.querySelector('#progressPct').textContent === '100%');
    await page.reload();
    await page.locator('#canvasControls').waitFor({state: 'visible'});
    assert.equal(await page.locator('#progressPct').textContent(), '100%');
    project = await (await page.request.get(base + '/api/project')).json();
    assert.equal(project.images.find(i => i.id === firstId).objects_count, 1);
    assert.equal(project.images.filter(i => i.reviewed).length, 3);
    await page.locator('#exportBtn').click();
    const download = page.waitForEvent('download');
    await page.locator('#downloadBtn').click();
    const zip = await download; await zip.saveAs(path.join(output, 'smoke-yolo.zip'));
    assert.equal(await zip.failure(), null);
    const yoloBytes = await fs.readFile(path.join(output, 'smoke-yolo.zip'));
    assert.ok(yoloBytes.length > 1000, 'YOLO download must contain an archive, not an empty file');
    assert.equal(yoloBytes.subarray(0, 2).toString(), 'PK');
    await page.locator('#exportFormat').selectOption('coco');
    const cocoDownload = page.waitForEvent('download');
    await page.locator('#downloadBtn').click();
    const coco = await cocoDownload; await coco.saveAs(path.join(output, 'smoke-coco.zip'));
    assert.equal(await coco.failure(), null);
    const cocoBytes = await fs.readFile(path.join(output, 'smoke-coco.zip'));
    assert.ok(cocoBytes.length > 1000, 'COCO download must contain an archive, not an empty file');
    assert.equal(cocoBytes.subarray(0, 2).toString(), 'PK');
    await page.locator('#exportDialog button[aria-label="Close dialog"]').click();
    await page.setViewportSize({width: 390, height: 844});
    await page.screenshot({path: path.join(output, 'mobile.png'), fullPage: true});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    console.log('PASS: box assist, brushes, undo, review invalidation, magnetic preview/outline, polygon, persistence, YOLO/COCO downloads, mobile layout; no page errors.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
