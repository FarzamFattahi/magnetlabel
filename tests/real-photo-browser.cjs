const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs/promises');
(async () => {
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  try {
    const base = process.env.MAGNETLABEL_URL || 'http://127.0.0.1:8769';
    await page.goto(base);
    await page.locator('#datasetSelect option').first().waitFor({state:'attached'});
    await page.locator('#newDatasetBtn').click();
    await page.locator('#settingsDialog').waitFor({state: 'visible'});
    await page.locator('#nameInput').fill('Cup & spoon study');
    await page.locator('#labelCount').fill('2');
    for (const [i, name] of ['cup', 'spoon'].entries()) await page.locator(`#className${i}`).fill(name);
    await page.screenshot({path: 'docs/screenshots/label-setup.png'});
    await page.locator('#saveSettingsBtn').click();
    await page.locator('#importDialog').waitFor({state: 'visible'});
    await page.locator('#fileInput').setInputFiles(path.resolve('examples/coffee.png'));
    await page.locator('#canvasControls').waitFor({state: 'visible'});
    const point = async (x, y) => {
      const b = await page.locator('#canvas').boundingBox();
      const scale = Math.min((b.width - 48) / 600, (b.height - 64) / 400);
      return [b.x + (b.width - 600 * scale) / 2 + x * scale, b.y + (b.height - 400 * scale) / 2 + y * scale];
    };
    const drag = async points => {
      await page.mouse.move(...await point(...points[0])); await page.mouse.down();
      for (const p of points.slice(1)) await page.mouse.move(...await point(...p), {steps: 8});
      await page.mouse.up();
    };
    await drag([[160, 10], [424, 319]]);
    await page.waitForFunction(() => !document.querySelector('#commitBtn').disabled);
    await page.screenshot({path: 'docs/screenshots/real-photo-initial.png'});
    const strokes = [
      [false, 8, [[180,190],[175,260],[170,305]]],
      [false, 10, [[300,305],[365,305],[405,245],[413,195]]],
      [true, 10, [[285,210],[285,260],[220,280]]],
      [false, 9, [[413,78]]],
      [false, 10, [[361,270],[365,285],[372,300]]],
    ];
    for (const [fg, radius, points] of strokes) {
      const button = page.locator(fg ? '#fgHint' : '#bgHint');
      if (!(await button.getAttribute('class') || '').includes('active')) await button.click();
      await page.locator('#brushSize').fill(String(radius));
      await drag(points);
    }
    await page.locator('#recomputeBtn').click();
    await page.waitForFunction(() => !document.querySelector('#commitBtn').disabled);
    await page.locator('#commitBtn').click();
    await page.waitForFunction(() => document.querySelector('#saveStatus').textContent.includes('All changes saved'));
    await page.screenshot({path: 'docs/screenshots/real-photo-cup.png'});
    // The second label is a spoon. Trace its visible bowl, then paint its exposed handle.
    await page.locator('#newObjectBtn').click();
    await page.locator('#classSelect').selectOption('1');
    await page.locator('[data-tool="polygon"]').click();
    for (const p of [[338,245],[347,236],[359,232],[372,225],[380,239],[391,247],[400,263],[404,281],[399,298],[390,312],[374,324],[354,325],[338,318],[329,305],[326,286],[328,266]]) {
      await page.mouse.click(...await point(...p));
      await page.waitForFunction(() => document.querySelector('#busyIndicator').hidden);
    }
    await page.locator('#finishBtn').click();
    await page.waitForFunction(() => !document.querySelector('#commitBtn').disabled);
    await page.locator('[data-tool="add"]').click();
    await page.locator('#brushSize').fill('5');
    await drag([[411,73],[414,78],[413,87],[410,99],[406,111]]);
    await page.locator('#brushSize').fill('3');
    await drag([[340,245],[349,242],[359,238],[365,234]]);
    await page.locator('#commitBtn').click();
    await page.waitForFunction(() => document.querySelector('#saveStatus').textContent.includes('All changes saved'));
    await page.screenshot({path: 'docs/screenshots/real-photo-workspace.png'});
    const project = await (await page.request.get(base + '/api/project')).json();
    assert.equal(project.classes.length, 2);
    const image = await (await page.request.get(`${base}/api/images/${project.images[0].id}`)).json();
    assert.deepEqual(image.objects.map(o => o.class_id), [0, 1]);
    const output = {image: image.name, objects: image.objects.length, classes: image.objects.map(o => project.classes[o.class_id].name), status: 'draft for human review'};
    await fs.writeFile('docs/real-photo-ui-result.json', JSON.stringify(output, null, 2));
    assert.deepEqual(errors, []);
    console.log('PASS: real-photo upload, cup/spoon labels, approximate cup box, hint correction, polygon/brush spoon mask, separate class assignments, persisted masks.');
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exitCode = 1;});
