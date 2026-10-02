/* Real pointer input against a running app. No app-state injection or mocked APIs. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL || 'msedge'});
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const base = process.env.MAGNETLABEL_URL || 'http://127.0.0.1:8769';
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  try {
    await page.goto(base);
    await page.locator('#datasetSelect option').first().waitFor({state:'attached'});
    await page.locator('#newDatasetBtn').click();
    await page.locator('#nameInput').fill('Selection interaction check');
    await page.locator('#className0').fill('circle');
    await page.locator('#saveSettingsBtn').click();
    await page.locator('#importDialog').waitFor({state:'visible'});
    assert.equal(await page.locator('.image-item').count(), 0);
    await page.locator('#fileInput').setInputFiles(path.resolve('data/browser-circle.png'));
    await page.locator('#canvasControls').waitFor({state:'visible'});
    const firstDataset = await page.locator('#datasetSelect').inputValue();
    const point = async (x,y) => {
      const b = await page.locator('#canvas').boundingBox();
      const s = Math.min((b.width-48)/140,(b.height-64)/100);
      return [b.x+(b.width-140*s)/2+x*s,b.y+(b.height-100*s)/2+y*s];
    };
    const drag = async (points,button='left') => {
      await page.mouse.move(...await point(...points[0])); await page.mouse.down({button});
      for (const p of points.slice(1)) await page.mouse.move(...await point(...p),{steps:8});
      await page.mouse.up({button});
    };
    const canvasPixels = () => page.locator('#canvas').evaluate(c => ({w:c.width,h:c.height,px:Array.from(c.getContext('2d').getImageData(0,0,c.width,c.height).data)}));
    const before = await canvasPixels();
    const b = await page.locator('#canvas').boundingBox();
    await page.mouse.move(b.x+b.width/2,b.y+b.height/2); await page.mouse.down({button:'right'});
    await page.mouse.move(b.x+b.width/2+40,b.y+b.height/2+20,{steps:8}); await page.mouse.up({button:'right'});
    const after = await canvasPixels();
    let matches=0,total=0;
    for(let y=100;y<before.h-100;y+=7) for(let x=100;x<before.w-100;x+=7) {
      const i=(y*before.w+x)*4,j=((y+20)*after.w+x+40)*4;
      total++; if(before.px.slice(i,i+4).every((v,k)=>Math.abs(v-after.px[j+k])<=2)) matches++;
    }
    assert.ok(matches/total>.98, `Right pan shifted image: ${matches/total}`);
    assert.equal(await page.locator('#commitBtn').isEnabled(),false);
    await page.locator('#fitBtn').click();
    await page.locator('[data-tool="smart"]').click();
    for(const p of [[35,15],[105,15],[105,85],[35,85]]) await page.mouse.click(...await point(...p));
    await page.locator('#finishBtn').click();
    await page.waitForFunction(()=>!document.querySelector('#commitBtn').disabled);
    await page.locator('#commitBtn').click();
    await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent.includes('All changes saved'));
    const getImage = async () => {
      const headers={'X-Dataset-ID':firstDataset};
      const project=await (await page.request.get(base+'/api/project',{headers})).json();
      return (await page.request.get(`${base}/api/images/${project.images[0].id}`,{headers})).json();
    };
    async function inspect(mask) {
      return page.evaluate(async src=> {
        const img=new Image();img.src=src;await img.decode();
        const c=document.createElement('canvas');c.width=img.width;c.height=img.height;
        c.getContext('2d').drawImage(img,0,0);
        const data=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
        let intersection=0,union=0;
        for(let y=0;y<c.height;y++)for(let x=0;x<c.width;x++){
          const predicted=data[(y*c.width+x)*4]>127;
          const expected=(x-70)**2+(y-50)**2<=25**2;
          if(predicted&&expected)intersection++;if(predicted||expected)union++;
        }
        return intersection/union;
      },mask);
    }
    const smartPolygonIoU = await inspect((await getImage()).objects[0].mask);
    assert.ok(smartPolygonIoU>.98);
    await page.locator('#newObjectBtn').click(); await page.locator('[data-tool="lasso"]').click();
    await drag([[30,50],[40,20],[70,12],[100,20],[110,50],[100,80],[70,88],[40,80],[30,50]]);
    await page.waitForFunction(()=>!document.querySelector('#commitBtn').disabled);
    await page.locator('#commitBtn').click();
    await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent.includes('All changes saved'));
    const lassoIoU = await inspect((await getImage()).objects[1].mask);
    assert.ok(lassoIoU>.98);
    await page.locator('#newObjectBtn').click(); await page.locator('[data-tool="polygon"]').click();
    for(const p of [[35,15],[105,15],[105,85],[35,85]]) await page.mouse.click(...await point(...p));
    await page.locator('#finishBtn').click();
    await page.locator('#recomputeBtn').click();
    await page.waitForFunction(()=>!document.querySelector('#commitBtn').disabled);
    await page.locator('#commitBtn').click();
    await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent.includes('All changes saved'));
    assert.ok(await inspect((await getImage()).objects[2].mask)>.98);
    const normalWidth=(await page.locator('#canvas').boundingBox()).width;
    await page.locator('#focusBtn').click();
    await page.waitForFunction(()=>document.querySelector('#workspace').classList.contains('focus-mode'));
    assert.ok((await page.locator('#canvas').boundingBox()).width>normalWidth+400);
    await page.locator('#focusBtn').click();
    await page.locator('#newDatasetBtn').click(); await page.locator('#nameInput').fill('Fresh empty dataset');
    await page.locator('#className0').fill('spoon'); await page.locator('#saveSettingsBtn').click();
    await page.locator('#importDialog').waitFor({state:'visible'});
    assert.equal(await page.locator('.image-item').count(),0);
    assert.equal(await page.locator('#objectCount').textContent(),'0');
    assert.equal(await page.locator('#emptyState').isVisible(),true);
    await page.locator('#importDialog [aria-label="Close dialog"]').click();
    await page.locator('#datasetSelect').selectOption(firstDataset);
    await page.locator('#canvasControls').waitFor({state:'visible'});
    assert.equal(await page.locator('.image-item').count(),1);
    assert.equal(await page.locator('.object-row').count(),3);
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert.deepEqual(errors,[]);
    await fs.writeFile('data/usability-result.json',JSON.stringify({rightPan:true,smartPolygonIoU,lassoIoU,manualPolygonTighten:true,focusMode:true,newDatasetIsolation:true,restorePrevious:true,pageErrors:errors},null,2));
    console.log('PASS: right-button pan, smart polygon, freehand lasso, manual polygon tighten, focus canvas, fresh dataset, previous dataset restoration, mobile width.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
