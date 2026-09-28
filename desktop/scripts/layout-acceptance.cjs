const {_electron:electron}=require('playwright')
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict')
const root=path.resolve(__dirname,'../..'),out=path.join(root,'.cache/layout-acceptance')
async function fixture(){
 await fs.mkdir(out,{recursive:true})
 await fs.writeFile(path.join(out,'preload.cjs'),`const {contextBridge}=require('electron');
 const long='Long synthetic project and photo path '+('archive_'.repeat(30));
 const source='C:/Synthetic/'+long+'/sample.png';
 const results=[{name:long,path:'C:/Synthetic/result',details:{baseline_file:'original.png',composite_file:'result.png'}}];
 const svg='<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800"><rect width="1200" height="800" fill="#34536b"/><circle cx="400" cy="400" r="250" fill="#d9b786"/><path d="M0 700 L1200 100" stroke="#7ba392" stroke-width="70"/></svg>';
 const preview='data:image/svg+xml;base64,'+Buffer.from(svg).toString('base64');
 let listener=()=>{};
 contextBridge.exposeInMainWorld('photo',{
 events:cb=>{listener=cb;return()=>{}},pick:async()=>[source],drop:async()=>[source],preview:async()=>preview,reveal:async()=>true,
 browser:async(action,args)=>{if(action==='bounds'&&(!Object.values(args).every(Number.isFinite)||args.x<0||args.y<0))throw Error('Invalid fixture bounds');return true},
 call:async(method,args={})=>{
 if(method==='status')return {home:'C:/Synthetic/'+long,plugin:'C:/Synthetic/'+long+'/plugin',free:400*1024**3,gpu:{name:long,memory:32*1024**3,capability:[12,0]},adobe:{},dependencies:['runtime','assistant','photo','legacy','obsidian'].map(group=>({group,bytes:8*1024**3,missingBytes:8*1024**3})),sessions:Array.from({length:24},(_,i)=>({id:''+i,title:long+' '+i,updated:1})),results};
 if(method==='settings')return {theme:'dark',reviewZoom:'fit'};
 if(method==='session')return {id:'0',source,events:[{type:'user',text:long.repeat(5),corrected:long.repeat(6)},{type:'message_update',assistantMessageEvent:{type:'text_delta',delta:long.repeat(12)}}]};
 if(method==='setup'){listener({type:'setup_progress',file:source,done:1,total:100});return {restartRecommended:true}};
 if(method==='suggest'){listener({type:'prompt_suggestions',source,summary:long,prompts:[long,long]});return {}};
 return {};
 }});`)
 await fs.writeFile(path.join(out,'main.cjs'),`const {app,BrowserWindow}=require('electron');app.whenReady().then(()=>{const w=new BrowserWindow({width:1280,height:720,webPreferences:{preload:${JSON.stringify(path.join(out,'preload.cjs'))},contextIsolation:true,nodeIntegration:false,sandbox:false}});w.loadFile(${JSON.stringify(path.join(root,'desktop/out/renderer/index.html'))})});app.on('window-all-closed',()=>app.quit());`)
}
async function settle(page){await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))}
async function noOverflow(page,label){
 const bad=await page.evaluate(()=>({w:innerWidth,h:innerHeight,sw:document.documentElement.scrollWidth,sh:document.documentElement.scrollHeight}))
 assert.ok(bad.sw<=bad.w+1&&bad.sh<=bad.h+1,label+' document overflow '+JSON.stringify(bad))
}
async function reachable(locator){await locator.scrollIntoViewIfNeeded();await locator.focus();assert.ok(await locator.evaluate(e=>{const r=e.getBoundingClientRect();return r.left>=-1&&r.right<=innerWidth+1&&r.top>=-1&&r.bottom<=innerHeight+1}),await locator.textContent())}
async function studio(page){
 const nav=page.getByRole('button',{name:'Toggle navigation',exact:true});
 if(!await page.getByRole('button',{name:'Studio',exact:true}).isVisible())await nav.click()
 await page.getByRole('button',{name:'Studio',exact:true}).click()
}
async function details(page){const button=page.getByRole('button',{name:'Controls & review',exact:true});if(await button.isVisible())await button.click()}
(async()=>{
 await fixture();const env={...process.env};delete env.ELECTRON_RUN_AS_NODE
 const app=await electron.launch({executablePath:require('electron'),args:[path.join(out,'main.cjs')],env})
 const checks=[],errors=[]
 try{
 const page=await app.firstWindow();page.on('pageerror',e=>errors.push(String(e)))
 for(const [width,height] of (process.env.LAYOUT_DEBUG?[[640,480]]:[[640,480],[800,600],[1280,720],[1920,1080],[900,1400],[2560,720]]))for(const scale of (process.env.LAYOUT_DEBUG?[2]:[1,1.25,1.5,2])){
  const label=width+'x'+height+'-'+scale
  await app.evaluate(({BrowserWindow},{width,height,scale})=>{const w=BrowserWindow.getAllWindows()[0];w.webContents.setZoomFactor(1);w.setContentSize(Math.floor(width/scale),Math.floor(height/scale))},{width,height,scale})
  await settle(page);console.log('Checking',label);await page.reload();await page.getByRole('button',{name:'Install / repair complete setup',exact:true}).waitFor();await settle(page)
  const effective=await page.evaluate(()=>[innerWidth,innerHeight]);assert.ok(Math.abs(effective[0]-width/scale)<=2&&Math.abs(effective[1]-height/scale)<=2,label+' effective viewport '+effective);await noOverflow(page,label+' setup');await reachable(page.getByRole('button',{name:'Install / repair complete setup',exact:true}));
  await reachable(page.getByRole('button',{name:'Show workspace',exact:true}));
  await studio(page)
  await page.getByRole('button',{name:'Choose photo',exact:true}).click()
  if(!await page.getByRole('button',{name:'＋ New session',exact:true}).isVisible())await page.getByRole('button',{name:'Toggle navigation',exact:true}).click()
  await reachable(page.locator('.session-list button').last());await page.getByRole('button',{name:'＋ New session',exact:true}).click()
  await reachable(page.getByLabel('Photo instructions'));await page.getByLabel('Photo instructions').fill('A long instruction '.repeat(100));await reachable(page.getByRole('button',{name:'Send ↑',exact:true}));
  await noOverflow(page,label+' conversation');await details(page)
  await page.getByRole('tab',{name:'Photo controls',exact:true}).click();await reachable(page.getByRole('button',{name:'Apply manual operation',exact:true}));await noOverflow(page,label+' controls')
  await page.getByRole('tab',{name:'Results',exact:true}).click();await page.locator('.result-list button').last().click();
  await page.getByAltText('Local before and after photo comparison').waitFor();await settle(page)
  const ratio=await page.getByAltText('Local before and after photo comparison').evaluate(e=>{const r=e.getBoundingClientRect();return r.width/r.height});assert.ok(Math.abs(ratio-1.5)<.02,label+' aspect ratio '+ratio)
  await reachable(page.getByRole('button',{name:'100% pixels',exact:true}));await noOverflow(page,label+' review')
  if(scale===1||width===640&&scale===2)await page.screenshot({path:path.join(out,label+'-review.png')})
  await page.getByRole('tab',{name:'Browser',exact:true}).click();await reachable(page.getByLabel('Browser address'));await noOverflow(page,label+' browser')
  await page.getByRole('tab',{name:'Prompt Master',exact:true}).click();await reachable(page.getByRole('button',{name:'Suggest prompts from photo',exact:true}).last());await noOverflow(page,label+' prompts')
  await page.getByRole('tab',{name:'Photo controls',exact:true}).focus();await page.keyboard.press('ArrowRight');assert.equal(await page.evaluate(()=>document.activeElement?.getAttribute('role')),'tab');assert.notEqual(await page.evaluate(()=>getComputedStyle(document.activeElement).outlineStyle),'none')
  if(scale===1||width===640&&scale===2){await studio(page);await page.screenshot({path:path.join(out,label+'-chat.png')})}
  checks.push(label);console.log('Passed',label)
 }
 for(const textScale of [1.25,1.5,2]){
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setContentSize(640,480));await page.reload();await page.getByRole('button',{name:'Install / repair complete setup',exact:true}).waitFor()
  await page.addStyleTag({content:'.app :is(p,button,input,select,textarea,label,summary,small,code,pre,strong,span,h2,h3){font-size:'+14*textScale+'px!important;line-height:1.5!important}'})
  await reachable(page.getByRole('button',{name:'Install / repair complete setup',exact:true}));await reachable(page.getByRole('button',{name:'Show workspace',exact:true}));await noOverflow(page,'text '+textScale+' setup')
  await studio(page);await reachable(page.getByLabel('Photo instructions'));await noOverflow(page,'text '+textScale+' conversation');await details(page);await reachable(page.getByRole('button',{name:'Apply manual operation',exact:true}));await noOverflow(page,'text '+textScale+' controls')
  checks.push('640x480-text-'+textScale);await page.screenshot({path:path.join(out,'text-'+textScale+'.png')})
 }
 assert.deepEqual(errors,[])
 await fs.writeFile(path.join(out,'report.json'),JSON.stringify({status:'passed',checks,scaling:'Effective CSS viewports for display/zoom scaling; separate enlarged-text checks; native zoom tested by browser acceptance',fixture:'Synthetic paths, 24 sessions, long messages, all setup groups and 1200x800 photo',coverage:['setup and actions reachable','conversation composer and send reachable','navigation/session scroll','review aspect ratio','browser and prompts','keyboard tab focus','no document overflow'],errors},null,2))
 }finally{await app.close()}
})().catch(e=>{console.error(e);process.exitCode=1})
