const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const base=process.env.BASE_URL||'http://127.0.0.1:8769';
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL||'msedge'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message)); await page.goto(base);
 await page.locator('#newDatasetBtn').click(); await page.locator('#nameInput').fill('Everyday objects · detection');
 await page.locator('#settingsTask').selectOption('detection'); await page.locator('#labelCount').fill('3');
 for(const [i,name] of ['cup','spoon','cat'].entries())await page.locator(`#className${i}`).fill(name);
 await page.locator('#saveSettingsBtn').click(); await page.locator('#importDialog').waitFor({state:'visible'});
 await page.locator('#fileInput').setInputFiles(['examples/coffee.png','examples/chelsea.png']);
 await page.locator('#importDialog').waitFor({state:'hidden'});await page.locator('#busyIndicator').waitFor({state:'hidden'});
 assert.equal(await page.locator('#taskSelect').inputValue(),'detection');assert.equal(await page.locator('[data-tool]:visible').count(),1);
 const dataset=await page.locator('#datasetSelect').inputValue();
 const project=async()=> (await page.request.get(`${base}/api/project?dataset=${dataset}`)).json();
 const image=async id=>(await page.request.get(`${base}/api/images/${id}?dataset=${dataset}`)).json();
 const coffee=(await project()).images.find(i=>i.name==='coffee.png');
 async function pos(x,y,w=600,h=400){const b=await page.locator('#canvas').boundingBox();const s=Math.min((b.width-48)/w,(b.height-64)/h);return [b.x+(b.width-w*s)/2+x*s,b.y+(b.height-h*s)/2+y*s];}
 async function drag(a,b,button='left'){await page.mouse.move(...a);await page.mouse.down({button});await page.mouse.move(...b,{steps:8});await page.mouse.up({button});}
 await drag(await pos(410,308),await pos(170,18)); // reverse drag
 await page.locator('#commitBtn').click();await page.waitForFunction(()=>document.querySelector('#saveStatus').textContent.includes('saved'));
 let data=await image(coffee.id);assert.deepEqual(data.objects[0].bbox,[170,18,240,290]);
 const initial=data.objects[0].bbox;
 await drag(await pos(270,170),await pos(280,180));await page.waitForTimeout(850);
 data=await image(coffee.id);assert.deepEqual(data.objects[0].bbox,[180,28,240,290]);
 await page.locator('#undoBtn').click();await page.waitForTimeout(850);assert.deepEqual((await image(coffee.id)).objects[0].bbox,initial);
 await drag(await pos(410,308),await pos(420,318));await page.waitForTimeout(850);assert.deepEqual((await image(coffee.id)).objects[0].bbox,[170,18,250,300]);
 await page.locator('#undoBtn').click();await page.waitForTimeout(850);
 // Right drag moves viewport and leaves box unchanged.
 await drag(await pos(270,170),await pos(310,200),'right');await page.locator('#fitBtn').click();assert.deepEqual((await image(coffee.id)).objects[0].bbox,initial);
 await page.locator('#newObjectBtn').click();await page.locator('#classSelect').selectOption('1');
 await drag(await pos(326,67),await pos(425,327));await page.locator('#commitBtn').click();await page.locator('#reviewBtn').click();
 await page.waitForFunction(()=>document.querySelector('#fileName').textContent==='chelsea.png');await page.locator('#busyIndicator').waitFor({state:'hidden'});
 await page.locator('#classSelect').selectOption('2');await drag(await pos(0,0,451,300),await pos(385,300,451,300));await page.locator('#commitBtn').click();
 await page.locator('#reviewBtn').click();await page.waitForTimeout(850);
 // Editing a reviewed object clears review; restore and review again.
 const cat=(await project()).images.find(i=>i.name==='chelsea.png');
 await page.locator('.object-select').click();await page.locator('#classSelect').selectOption('0');await page.waitForTimeout(850);assert.equal((await image(cat.id)).reviewed,0);
 await page.locator('#undoBtn').click();await page.waitForTimeout(850);assert.equal((await image(cat.id)).objects[0].class_id,2);
 await page.locator('#reviewBtn').click();
 // Occupied task change offers a new dataset, preserving original.
 await page.locator('#taskSelect').selectOption('segmentation');await page.locator('#settingsDialog').waitFor({state:'visible'});
 assert.equal(await page.locator('#settingsTask').inputValue(),'segmentation');
 await page.locator('#settingsDialog [aria-label="Close dialog"]').click();assert.equal((await project()).task,'detection');
 await page.reload();await page.locator('#busyIndicator').waitFor({state:'hidden'});await page.locator('.image-item').filter({hasText:'coffee.png'}).click();
 await page.locator('#busyIndicator').waitFor({state:'hidden'});assert.equal(await page.locator('.object-row').count(),2);
 await page.screenshot({path:'docs/screenshots/object-detection-coffee.png',fullPage:true});
 await page.locator('.image-item').filter({hasText:'chelsea.png'}).click();await page.locator('#busyIndicator').waitFor({state:'hidden'});
 await page.screenshot({path:'docs/screenshots/object-detection-cat.png',fullPage:true});
 await page.locator('#exportBtn').click();assert.equal(await page.locator('#segmentationExport').isVisible(),false);
 const downloadPromise=page.waitForEvent('download');await page.locator('#downloadBtn').click();await (await downloadPromise).saveAs('data/detection-ui-export.zip');
 const coco=await page.request.post(`${base}/api/export?dataset=${dataset}`,{data:{format:'coco'}});assert.equal(coco.status(),200);fs.writeFileSync('data/detection-ui-coco.zip',await coco.body());
 await page.locator('#exportDialog [aria-label="Close dialog"]').click();
 assert.deepEqual(errors,[]);fs.writeFileSync('docs/detection-ui-result.json',JSON.stringify({dataset,images:(await project()).images,pageErrors:errors,checks:['reverse rectangle drag','class labels','move','corner resize','undo','right-drag pan','review invalidation','task isolation','reload persistence','YOLO download','COCO download']},null,2));
 console.log('Detection interactions passed; actual UI screenshots and both export ZIPs saved.');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
