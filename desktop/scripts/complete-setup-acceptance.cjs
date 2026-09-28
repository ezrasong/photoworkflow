// Opt-in acceptance with cached, pinned downloads and a synthetic photo only.
const {_electron:electron}=require('playwright')
const fs=require('node:fs/promises')
const {resolve,join}=require('node:path')
const {execFileSync}=require('node:child_process')
const {createHash}=require('node:crypto')
const assert=require('node:assert/strict')
const root=resolve(__dirname,'../..'),exe=join(root,'desktop/dist/win-unpacked/Luma Atelier.exe')
const resources=resolve(exe,'../resources/backend')
const home=join(root,'.cache/complete-setup-acceptance-'+Date.now())
let app
const hash=bytes=>createHash('sha256').update(bytes).digest('hex')
async function launch(){
 const env={...process.env,PHOTOWORKFLOW_HOME:home};delete env.ELECTRON_RUN_AS_NODE
 app=await electron.launch({executablePath:exe,env,timeout:60000})
 const page=await app.firstWindow();await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.webContents.setZoomFactor(1);w.setContentSize(1440,960)});await page.waitForFunction(()=>!!window.photo)
 await page.evaluate(()=>{window.testEvents=[];window.photo.events(e=>window.testEvents.push(e))})
 return page
}
async function close(){
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].close())
 await new Promise((resolve,reject)=>{const p=app.process();if(p.exitCode!==null)return resolve();const t=setTimeout(()=>reject(new Error('Close timed out')),60000);p.once('exit',()=>{clearTimeout(t);resolve()})})
 app=null
}
(async()=>{
 await fs.mkdir(home,{recursive:true})
 // Hard-link immutable cached inputs. Setup still verifies every pinned hash and
 // extracts runtime/model assets into this fresh workspace. Never use a venv.
 const catalog=JSON.parse(await fs.readFile(join(root,'packaging/downloads.json'),'utf8')).files
 for(const name of Object.keys(catalog)){
  const candidates=[join(root,name),join(root,'.cache/desktop-gpu-acceptance',name)]
  let source
  for(const path of candidates){try{if((await fs.stat(path)).isFile()){source=path;break}}catch{}}
  assert.ok(source,'Missing cached download: '+name)
  const target=join(home,name);await fs.mkdir(resolve(target,'..'),{recursive:true});await fs.link(source,target)
 }
 let page=await launch()
 await page.getByRole('button',{name:'Setup and settings',exact:true}).click()
 await page.getByRole('button',{name:'Install / repair complete setup',exact:true}).click()
 console.log('Complete setup started in fresh workspace; verifying cached downloads and extracting all groups')
 await page.getByText('Setup complete. Restart Luma Atelier before model editing.',{exact:true}).waitFor({timeout:600000})
 const events=await page.evaluate(()=>window.testEvents)
 assert.deepEqual(events.filter(e=>e.type==='setup_group_complete').map(e=>e.group),['runtime','assistant','photo','legacy','obsidian'])
 assert.deepEqual(events.filter(e=>e.type==='setup_complete').map(e=>e.group),['all'])
 const obsidian=JSON.parse(await fs.readFile(join(home,'apps/ObsidianData/obsidian.json'),'utf8'))
 assert.equal(Object.values(obsidian.vaults)[0].path,join(home,'Photo Vault'))
 await fs.stat(join(home,'apps/Obsidian/Obsidian.exe'))
 await close();page=await launch()
 const status=await page.evaluate(()=>window.photo.call('status'))
 assert.ok(status.gpu.available);assert.ok(status.dependencies.every(d=>d.missingBytes===0))
 const photo=join(home,'synthetic.png')
 execFileSync(join(resources,'python/python.exe'),['-c',`from PIL import Image, ImageDraw; im=Image.new('RGB',(320,240),(80,95,110)); ImageDraw.Draw(im).rectangle((70,60,220,180),fill=(155,95,50)); im.save(${JSON.stringify(photo)})`],{windowsHide:true})
 const original=hash(await fs.readFile(photo))
 await page.getByRole('button',{name:'Toggle navigation',exact:true}).click()
 await page.getByRole('button',{name:'＋ New session',exact:true}).click()
 await page.waitForFunction(()=>window.testEvents.some(e=>e.type==='ready'),{},{timeout:60000})
 await app.evaluate(({dialog},path)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[path]})},photo)
 await page.getByRole('button',{name:'Choose photo',exact:true}).click()
 await page.locator('.composer').getByRole('button',{name:'Suggest prompts from photo',exact:true}).click()
 await page.locator('.prompt-suggestions').waitFor({timeout:240000})
 const cards=page.locator('.prompt-suggestions article')
 assert.ok(await cards.count()>0)
 const first=await cards.first().locator('p').textContent()
 await cards.first().getByRole('button',{name:'Use as draft',exact:true}).click()
 assert.equal(await page.getByRole('textbox',{name:'Photo instructions'}).inputValue(),first)
 assert.equal((await page.evaluate(()=>window.photo.call('results'))).length,0)
 assert.equal(hash(await fs.readFile(photo)),original)
 assert.ok(!(await page.evaluate(()=>window.testEvents)).some(e=>e.type==='user'))
 await page.screenshot({path:join(root,'.cache/prompt-suggestions-ui.png')})
 await close()
 const evidence={status:'passed',home,checks:['All five setup groups verified and extracted through packaged UI','One final setup completion; vault registered; CUDA available after restart','Actual local Qwen3-VL suggestions rendered as editable drafts','No prompt submitted or photo edited by suggestion generation'],gpu:status.gpu}
 await fs.writeFile(join(root,'.cache/complete-setup-acceptance-report.json'),JSON.stringify(evidence,null,2))
 console.log(JSON.stringify(evidence,null,2))
})().catch(async error=>{console.error(error);if(app)await app.close().catch(()=>{});process.exitCode=1})
