const {_electron:electron}=require('playwright')
const {join,resolve}=require('node:path')
const fs=require('node:fs/promises')
const assert=require('node:assert/strict')
const root=resolve(__dirname,'../..')
;(async()=>{
 const env={...process.env,PHOTOWORKFLOW_HOME:join(root,'.cache/browser-acceptance-'+Date.now())};delete env.ELECTRON_RUN_AS_NODE
 const app=await electron.launch({executablePath:join(root,'desktop/dist/win-unpacked/Photo Studio.exe'),env})
 try{
 const page=await app.firstWindow();await page.waitForFunction(()=>window.photo);page.on('pageerror',console.error);await page.evaluate(()=>{window.browserEvents=[];window.photo.events(e=>{if(e.type==='browser')window.browserEvents.push(e)})});await page.getByRole('button',{name:'Install / repair complete setup',exact:true}).waitFor();console.log('Browser test ready')
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setContentSize(1440,960))
 if(!await page.getByRole('button',{name:'Studio',exact:true}).isVisible())await page.getByRole('button',{name:'Toggle navigation',exact:true}).click()
 await page.getByRole('button',{name:'Studio',exact:true}).click()
 await page.getByRole('tab',{name:'Browser',exact:true}).click()
 await page.getByLabel('Browser address').fill('https://en.wikipedia.org/wiki/Photography')
 await page.getByRole('button',{name:'Go',exact:true}).click();console.log('Go submitted')
 const deadline=Date.now()+60000
 let remote
 while(Date.now()<deadline){
 remote=await app.evaluate(async({webContents,BrowserWindow})=>{
 const owner=BrowserWindow.getAllWindows()[0]
 const wc=webContents.getAllWebContents().find(w=>w!==owner.webContents&&w.getURL().startsWith('https://en.wikipedia.org/wiki/Photography'))
 if(!wc||wc.isLoading())return null
 return {text:await wc.executeJavaScript('document.body.innerText'),access:await wc.executeJavaScript('typeof window.photo + ":" + typeof require'),prefs:wc.getLastWebPreferences(),visible:owner.contentView.children.at(-1).getVisible()}
 })
 if(remote)break
 await new Promise(r=>setTimeout(r,500))
 }
 if(!remote)console.log(await page.evaluate(()=>window.browserEvents),await app.evaluate(({webContents})=>webContents.getAllWebContents().map(w=>({id:w.id,url:w.getURL()}))));assert.ok(remote?.text.includes('Photography'));assert.equal(remote.access,'undefined:undefined');assert.equal(remote.prefs.sandbox,true);assert.equal(remote.prefs.nodeIntegration,false);assert.ok(!remote.prefs.preload)
 const boundsChecks=[]
 for(const [width,height] of [[640,480],[800,600],[1280,720],[1920,1080],[900,1400],[2560,720]])for(const zoom of [1,1.25,1.5,2]){
  await app.evaluate(({BrowserWindow},{width,height,zoom})=>{const w=BrowserWindow.getAllWindows()[0];w.setContentSize(width,height);w.webContents.setZoomFactor(zoom)},{width,height,zoom})
  // Electron's native zoom is not reflected in Playwright pointer coordinates.
  await page.evaluate(()=>{const b=[...document.querySelectorAll('button')].find(e=>e.textContent==='Controls & review');if(b&&b.checkVisibility())b.click()})
  await page.evaluate(()=>new Promise(r=>setTimeout(r,150)))
  const geometry=await page.evaluate(()=>{const e=document.querySelector('.browser-host'),r=e.getBoundingClientRect();let left=Math.max(0,r.left),top=Math.max(0,r.top),right=Math.min(innerWidth,r.right),bottom=Math.min(innerHeight,r.bottom);for(let p=e.parentElement;p;p=p.parentElement){const s=getComputedStyle(p),c=p.getBoundingClientRect();if(s.overflowX!=='visible'){left=Math.max(left,c.left);right=Math.min(right,c.right)}if(s.overflowY!=='visible'){top=Math.max(top,c.top);bottom=Math.min(bottom,c.bottom)}}return {x:left,y:top,width:right-left,height:bottom-top}})
  const native=await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0],v=w.contentView.children.at(-1);return {bounds:v.getBounds(),visible:v.getVisible(),size:w.getContentSize()}})
  if(geometry.height>=1&&geometry.width>=1){assert.equal(native.visible,true);for(const key of ['x','y','width','height'])assert.ok(Math.abs(native.bounds[key]-geometry[key]*zoom)<=2,JSON.stringify({width,height,zoom,geometry,native}));assert.ok(native.bounds.x+native.bounds.width<=native.size[0]+1);assert.ok(native.bounds.y+native.bounds.height<=native.size[1]+1)}else assert.equal(native.visible,false)
  boundsChecks.push({width,height,zoom})
 }
 await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.webContents.setZoomFactor(1);w.setContentSize(1440,960)})
 await page.evaluate(()=>document.querySelector('[data-slot=tabs-trigger][data-value=controls]').click())
 assert.equal(await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].contentView.children.at(-1).getVisible()),false)
 await page.screenshot({path:join(root,'.cache/desktop-studio-ui.png')})
 await fs.writeFile(join(root,'.cache/desktop-browser-report.json'),JSON.stringify({status:'passed',boundsChecks,checks:['Native browser bounds match clipped CSS bounds at six sizes and four real zoom levels','Public HTTPS page loads in the embedded browser','Remote page has no photo bridge, Node or preload','Sandbox enabled and Node disabled','Browser hides when switching tabs']},null,2))
 console.log('Browser isolation and public navigation passed')
 }finally{await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].close());await new Promise(r=>app.process().once('exit',r))}
})().catch(e=>{console.error(e);process.exitCode=1})
