import { app, dialog, ipcMain, shell, nativeImage } from 'electron'
import { spawn, ChildProcessWithoutNullStreams } from 'node:child_process'
import { createInterface } from 'node:readline'
import { randomUUID, createHash } from 'node:crypto'
import { promises as fs } from 'node:fs'
import { join, resolve, relative, isAbsolute, extname } from 'node:path'
import { createWindow, registerRendererProtocol, trusted } from './windows'
import { referenceBrowser } from './browser'

// Retain the established profile and workspace across the display-name change.
app.setPath('userData', join(app.getPath('appData'), 'photo-workflow'))

let win:ReturnType<typeof createWindow>
let backend:ChildProcessWithoutNullStreams
let closing=false
let busy=false
const selected=new Set<string>()
const pending=new Map<string,{resolve:(value:any)=>void,reject:(error:Error)=>void}>()
const resources=app.isPackaged?join(process.resourcesPath,'backend'):resolve(__dirname,'../../../.cache/packaging/bundle')
let home=process.env.PHOTOWORKFLOW_HOME || join(app.getPath('userData'),'Workspace')
const allowed=new Set(['status','results','cancel','setup','session','prompt','suggest','select','process','export','panel','person','settings','review','obsidian','references'])
function inside(base:string,path:string){const r=relative(resolve(base),resolve(path));return !r.startsWith('..')&&!isAbsolute(r)}
function send(method:string,args:any={}) {
  return new Promise<any>((resolve,reject)=>{
    if(!backend || backend.exitCode!==null){reject(new Error('Photo backend is unavailable. Restart Photo Studio.'));return}
    const id=randomUUID();pending.set(id,{resolve,reject})
    backend.stdin.write(JSON.stringify({id,method,args})+'\n',error=>{if(error){pending.delete(id);reject(error)}})
  })
}
async function seed() {
  await fs.mkdir(home,{recursive:true})
  const base=join(resources,'packaging/seed')
  for(const entry of await fs.readdir(base,{recursive:true,withFileTypes:true})){
    if(!entry.isFile())continue
    const source=join(entry.parentPath,entry.name),target=join(home,relative(base,source))
    await fs.mkdir(join(target,'..'),{recursive:true})
    const bytes=await fs.readFile(source)
    const current=await fs.readFile(target).catch(()=>null)
    if(current && createHash('sha256').update(current).digest('hex')===createHash('sha256').update(bytes).digest('hex'))continue
    const temp=target+'.seed-'+randomUUID();await fs.writeFile(temp,bytes);await fs.rename(temp,target)
  }
}
async function authorizePath(path:unknown) {
  if(typeof path!=='string'||path.length>32767||path.startsWith('\\\\')||!isAbsolute(path))throw new Error('Choose a local file or folder')
  const actual=await fs.realpath(path)
  selected.add(actual.toLowerCase());return actual
}
async function permitted(path:unknown) {
  if(typeof path!=='string'||!isAbsolute(path))throw new Error('Invalid path')
  const actual=await fs.realpath(path)
  if(!selected.has(actual.toLowerCase())&&!inside(home,actual))throw new Error('Choose this file through the photo picker first')
  return actual
}
function validateCaller(event:Electron.IpcMainInvokeEvent){if(event.sender!==win.webContents||event.senderFrame!==win.webContents.mainFrame||!trusted(event.senderFrame.url))throw new Error('Untrusted renderer')}
async function start(){
  await seed()
  registerRendererProtocol();win=createWindow()
  const browser=referenceBrowser(win)
  ipcMain.handle('photo:browser',(event,action,args)=>{validateCaller(event);return browser(action,args)})
  const env={...process.env,PHOTOWORKFLOW_HOME:home,PYTHONPATH:resources+';'+join(home,'runtime/python-libs'),PYTHONNOUSERSITE:'1',PYTHONDONTWRITEBYTECODE:'1',PYTHONUTF8:'1'}
  delete (env as any).PYTHONHOME
  backend=spawn(join(resources,'python/python.exe'),['-u','-m','photo_workflow.desktop'],{cwd:resources,env,windowsHide:true,stdio:'pipe'})
  const reader=createInterface({input:backend.stdout})
  reader.on('line',line=>{
    try{
      const value=JSON.parse(line)
      if(value.event){
        const t=value.event.type
        // Windows MSIX can redirect AppData for the owned Python child. Use its
        // resolved workspace for output grants instead of comparing path aliases.
        if(t==='backend_ready'&&typeof value.event.home==='string'&&isAbsolute(value.event.home))home=value.event.home
        if(['agent_start'].includes(t))busy=true
        if(['prompt_result','job_end','setup_complete'].includes(t))busy=false
        if(!win.isDestroyed())win.webContents.send('photo:event',value.event)
      }
      else if(pending.has(value.id)){const p=pending.get(value.id)!;pending.delete(value.id);value.error?p.reject(new Error(value.error)):p.resolve(value.result)}
    }catch(error){void fs.appendFile(join(home,'backend.log'),String(error)+'\n')}
  })
  backend.stderr.on('data',data=>void fs.appendFile(join(home,'backend.log'),data))
  backend.on('error',error=>{for(const p of pending.values())p.reject(error);pending.clear();if(!win.isDestroyed())win.webContents.send('photo:event',{type:'error',text:error.message})})
  backend.on('exit',code=>{for(const p of pending.values())p.reject(new Error('Backend exited: '+code));pending.clear();if(!closing&&!win.isDestroyed())win.webContents.send('photo:event',{type:'error',text:'Backend stopped. Restart the app; user files are preserved.'})})
  ipcMain.handle('photo:call',async(event,method,args)=>{
    validateCaller(event)
    if(!allowed.has(method)||!args||typeof args!=='object'||JSON.stringify(args).length>64000)throw new Error('Unsupported request')
    if(method==='select'){if(!Array.isArray(args.paths)||args.paths.length>4)throw new Error('Invalid selection');args.paths=await Promise.all(args.paths.map(permitted))}
    if(method==='process')args.source=await permitted(args.source)
    if(method==='export'||method==='review')args.path=await permitted(args.path)
    if(['process','setup','prompt','export','suggest','references'].includes(method))busy=true
    try{
      const result=await send(method,args)
      if(method==='session'&&result.source)await authorizePath(result.source)
      return result
    }catch(error){if(method==='prompt')busy=false;throw error}finally{if(['process','setup','export','suggest','references'].includes(method))busy=false}
  })
  ipcMain.handle('photo:pick',async(event,kind)=>{
    validateCaller(event)
    if(!['photo','folder','notes','references','recipe'].includes(kind))throw new Error('Invalid picker')
    const result=await dialog.showOpenDialog(win,{properties:kind==='folder'?['openDirectory']:kind==='references'||kind==='notes'?['openFile','multiSelections']:['openFile'],
      filters:kind==='notes'?[{name:'Vault notes',extensions:['md']}]:kind==='recipe'?[{name:'Recipe',extensions:['json']}]:[{name:'Photos',extensions:['jpg','jpeg','png','tif','tiff','heic','heif','dng','arw','cr2','cr3','nef','raf','orf','rw2','pef']}]})
    return Promise.all(result.filePaths.map(authorizePath))
  })
  ipcMain.handle('photo:drop',async(event,paths)=>{validateCaller(event);if(!Array.isArray(paths)||paths.length!==1)throw new Error('Drop one photo or folder');return Promise.all(paths.map(authorizePath))})
  ipcMain.handle('photo:preview',async(event,path,full=false)=>{
    validateCaller(event);const actual=await permitted(path)
    if(typeof full!=='boolean')throw new Error('Invalid preview mode')
    if(!['.png','.jpg','.jpeg','.tif','.tiff'].includes(extname(actual).toLowerCase()))throw new Error('Preview appears after RAW/HEIF preparation')
    if((await fs.stat(actual)).size>512*1024*1024)throw new Error('Preview source exceeds 512 MiB')
    if(full||['.tif','.tiff'].includes(extname(actual).toLowerCase()))return await send('preview',{path:actual,full})
    const img=nativeImage.createFromPath(actual)
    if(img.isEmpty())return await send('preview',{path:actual})
    return img.resize({width:Math.min(1600,img.getSize().width)}).toDataURL()
  })
  ipcMain.handle('photo:reveal',async(event,path)=>{validateCaller(event);shell.showItemInFolder(await permitted(path));return true})
  win.on('close',event=>{
    if(closing)return
    event.preventDefault()
    void (async()=>{
      if(busy){const choice=await dialog.showMessageBox(win,{type:'question',buttons:['Keep working','Stop safely and close'],defaultId:0,cancelId:0,message:'A job is running. Closing waits for a safe model or Adobe boundary.'});if(choice.response===0)return}
      closing=true;await send('cancel').catch(()=>{});backend.stdin.end()
      // Wait for Python to drain jobs and OMP to release its owned runtime.
      if(backend.exitCode===null)await new Promise<void>(resolve=>backend.once('exit',()=>resolve()))
      win.destroy();app.quit()
    })()
  })
}
if(!app.requestSingleInstanceLock())app.quit()
else {app.on('second-instance',()=>{win?.show();win?.focus()});void app.whenReady().then(start).catch(error=>{dialog.showErrorBox('Photo Studio startup failed',String(error));app.quit()})}
app.on('window-all-closed',()=>app.quit())
