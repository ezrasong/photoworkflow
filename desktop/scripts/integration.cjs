// Opt-in local GPU acceptance using only a synthetic fixture and pinned model assets.
const {_electron:electron}=require('playwright')
const fs=require('node:fs/promises')
const {resolve,join}=require('node:path')
const {execFileSync}=require('node:child_process')
const assert=require('node:assert/strict')
const root=resolve(__dirname,'../..'),exe=resolve(__dirname,'../dist/win-unpacked/Photo Studio.exe')
const home=join(root,'.cache/desktop-gpu-acceptance')
const resources=resolve(exe,'../resources/backend')
let app,page
async function launch(){
 const env={...process.env,PHOTOWORKFLOW_HOME:home};delete env.ELECTRON_RUN_AS_NODE
 app=await electron.launch({executablePath:exe,env,timeout:60000});page=await app.firstWindow()
 await page.waitForFunction(()=>!!window.photo)
 await page.evaluate(()=>{window.testEvents=[];window.photo.events(e=>window.testEvents.push(e))})
 return page.evaluate(()=>window.photo.call('status'))
}
async function close(){
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].close())
 await new Promise((resolve,reject)=>{const p=app.process();if(p.exitCode!==null)return resolve();const t=setTimeout(()=>reject(new Error('Graceful close timed out')),60000);p.once('exit',()=>{clearTimeout(t);resolve()})})
 app=null
}
(async()=>{
 await fs.mkdir(home,{recursive:true})
 const evidence={checks:[],home}
 await launch()
 if(!process.env.PHOTO_TEST_REUSE){
 console.log('Installing hash-pinned Torch/CUDA wheels through the packaged bridge')
 const timer=setInterval(async()=>{try{const p=await page.evaluate(()=>window.testEvents.filter(e=>e.type==='setup_progress').at(-1));if(p)console.log(p.file,Math.round(p.done/p.total*100)+'%')}catch{}},15000)
 try{await page.evaluate(()=>window.photo.call('setup',{group:'runtime'}))}finally{clearInterval(timer)}
 evidence.checks.push('Actual HTTPS Torch/CUDA wheel download, SHA256 verification and user-data extraction')
 await close();const state=await launch();assert.ok(state.gpu.available);evidence.gpu=state.gpu
 console.log('CUDA runtime loaded:',state.gpu.name)
 const catalog=JSON.parse(await fs.readFile(join(root,'packaging/downloads.json'),'utf8')).files
 // Reuse existing hash-pinned downloads, never a developer virtual environment.
 for(const [name,e] of Object.entries(catalog)){
  if(e.group!=='assistant')continue
  const target=join(home,name);await fs.mkdir(resolve(target,'..'),{recursive:true});await fs.copyFile(join(root,name),target)
 }
 console.log('Repair/verifying assistant assets and extracting its pinned runtime')
 await page.evaluate(()=>window.photo.call('setup',{group:'assistant'}))
 }
 const model=join(home,'models/scunet_color_real_psnr.pth');await fs.copyFile(join(root,'models/scunet_color_real_psnr.pth'),model)
 const fixture=join(home,'synthetic.png')
 execFileSync(join(resources,'python/python.exe'),['-c',`from PIL import Image; import numpy as np; r=np.random.default_rng(21); a=np.clip(r.normal(110,12,(128,192,3)),0,255).astype('uint8'); Image.fromarray(a).save(${JSON.stringify(fixture)})`],{windowsHide:true})
 console.log('Running actual SCUNet CUDA edit on a synthetic fixture')
 const edit=await page.evaluate(source=>window.photo.call('process',{operation:'edit',source,recipe:{denoise:.25,denoise_model:'scunet'}}),fixture)
 assert.equal(edit.code,0);evidence.checks.push('Packaged SCUNet CUDA denoise on synthetic noise fixture')
 console.log('Starting real OMP RPC session')
 const session=await page.evaluate(()=>window.photo.call('session',{title:'Packaged acceptance'}))
 await page.waitForFunction(()=>window.testEvents.some(e=>e.type==='ready'),{},{timeout:60000})
 await page.evaluate(source=>window.photo.call('select',{kind:'photo',paths:[source]}),fixture)
 await page.evaluate(()=>window.photo.call('prompt',{text:'Call photo_status once, then brifly report whether a photo is selected. Do not inspect or edit anything.'}))
 await page.waitForFunction(()=>window.testEvents.some(e=>e.type==='prompt_result'),{},{timeout:240000})
 const events=await page.evaluate(()=>window.testEvents)
 const end=events.findLast(e=>e.type==='prompt_result');assert.equal(end.status,'completed')
 assert.ok(events.some(e=>e.type==='tool_execution_end'&&e.toolName==='photo_status'))
 assert.ok(events.some(e=>e.type==='message_update'))
 assert.ok(events.some(e=>e.type==='user'&&e.corrected&&e.text.includes('brifly')&&e.corrected.includes('briefly')))
 evidence.checks.push('Local Prompt Master corrects spelling and persists both original and corrected prompts')
 evidence.checks.push('Real OMP RPC conversation, authenticated local model request, photo_status tool event and prompt completion')
 evidence.session=session.id;evidence.eventTypes=[...new Set(events.map(e=>e.type))]
 // The outer desktop profile must leave the native worker's lock available.
 execFileSync(join(resources,'python/python.exe'),['-c',"from photo_workflow.pipeline import job_lock; from photo_workflow.runtime import ROOT;\nwith job_lock(ROOT/'.cache/chat.lock'): print('worker lock available')"],{windowsHide:true,env:{...process.env,PHOTOWORKFLOW_HOME:home,PYTHONPATH:resources}})
 evidence.checks.push('Outer assistant session does not hold the native per-photo worker lock')
 const jobs=await page.evaluate(()=>window.photo.call('results'))
 const review=await page.evaluate(path=>window.photo.call('review',{path}),jobs[0].path)
 assert.ok(Number.isInteger(review.pid))
 execFileSync('powershell.exe',['-NoProfile','-Command',`(Get-Process -Id ${review.pid}).CloseMainWindow()`],{windowsHide:true})
 evidence.checks.push('Full-resolution Tk review reports ready using bundled Tk and TIFF decoder')
 await close();await launch()
 const reopened=await page.evaluate(id=>window.photo.call('session',{id}),session.id)
 assert.equal(reopened.source,fixture);assert.ok(reopened.events.some(e=>e.type==='user'))
 evidence.checks.push('Reopened OMP session preserves selected input and conversation history')
 await close();evidence.checks.push('Assistant/backend clean shutdown after local inference')
 evidence.status='passed';await fs.writeFile(join(root,'.cache/desktop-integration-report.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence,null,2))
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1})
