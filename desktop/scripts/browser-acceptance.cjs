const {_electron:electron}=require('playwright')
const {join,resolve}=require('node:path')
const fs=require('node:fs/promises')
const assert=require('node:assert/strict')
const root=resolve(__dirname,'../..')
;(async()=>{
 const env={...process.env,PHOTOWORKFLOW_HOME:join(root,'.cache/browser-acceptance-'+Date.now())};delete env.ELECTRON_RUN_AS_NODE
 const app=await electron.launch({executablePath:join(root,'desktop/dist/win-unpacked/Photo Workflow.exe'),env})
 try{
 const page=await app.firstWindow();await page.waitForFunction(()=>window.photo);page.on('pageerror',console.error);await page.evaluate(()=>{window.browserEvents=[];window.photo.events(e=>{if(e.type==='browser')window.browserEvents.push(e)})});console.log('Browser test ready')
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setContentSize(1440,960))
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
 await page.getByRole('tab',{name:'Photo controls',exact:true}).click()
 assert.equal(await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].contentView.children.at(-1).getVisible()),false)
 await page.screenshot({path:join(root,'.cache/desktop-studio-ui.png')})
 await fs.writeFile(join(root,'.cache/desktop-browser-report.json'),JSON.stringify({status:'passed',checks:['Public HTTPS page loads in the embedded browser','Remote page has no photo bridge, Node or preload','Sandbox enabled and Node disabled','Browser hides when switching tabs']},null,2))
 console.log('Browser isolation and public navigation passed')
 }finally{await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].close());await new Promise(r=>app.process().once('exit',r))}
})().catch(e=>{console.error(e);process.exitCode=1})
