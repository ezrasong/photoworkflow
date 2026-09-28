import { app, safeStorage } from 'electron'
import { NsisUpdater } from 'electron-updater'
import { promises as fs } from 'node:fs'
import { join } from 'node:path'
import { randomUUID } from 'node:crypto'

type UpdateState = {
  version:string; connected:boolean; phase:'disconnected'|'idle'|'checking'|'downloading'|'ready'|'installing'|'error';
  message:string; availableVersion?:string; percent?:number
}

// Credentials never enter backend environments, release metadata or error text.
export function createUpdates(emit:(state:UpdateState)=>void, isBusy:()=>boolean, stopBackend:()=>Promise<void>) {
  const updater=new NsisUpdater()
  updater.logger=null
  updater.autoDownload=false // Own the check + download promise as one operation.
  updater.autoInstallOnAppQuit=false
  updater.allowPrerelease=false
  updater.allowDowngrade=false
  // Private GitHub assets cannot reliably provide old blockmaps anonymously.
  updater.disableDifferentialDownload=true
  const tokenFile=join(app.getPath('userData'),'update-access.bin')
  let token=''
  let running=false
  let state:UpdateState={version:app.getVersion(),connected:false,phase:'disconnected',message:'Connect GitHub access to enable automatic updates.'}
  const publish=(value:Partial<UpdateState>)=>{state={...state,...value};emit({...state})}
  const failure=()=>publish({phase:'error',message:state.phase==='installing'?'The update installer could not start. Close and reopen Photo Studio, then retry.':'Update failed. Check your connection and GitHub token access, then retry. Your current installation is unchanged.'})
  updater.on('error',failure) // Never forward upstream errors: they may contain headers.
  updater.on('download-progress',p=>publish({phase:'downloading',percent:Math.max(0,Math.min(100,p.percent)),message:'Downloading update…'}))
  updater.on('update-downloaded',info=>publish({phase:'ready',availableVersion:info.version,percent:100,message:'Update downloaded and verified. Restart to install when your work is finished.'}))

  async function check() {
    if(!app.isPackaged)throw new Error('Updates are available in the installed app.')
    if(!token)throw new Error('Add a read-only GitHub token in Settings to enable private updates.')
    if(running||state.phase==='ready'||state.phase==='installing')return {...state}
    running=true
    try {
      publish({phase:'checking',message:'Checking for updates…',percent:undefined,availableVersion:undefined})
      updater.setFeedURL({provider:'github',owner:'ezrasong',repo:'photoworkflow',private:true,token})
      const result=await updater.checkForUpdates()
      if(result?.isUpdateAvailable){
        publish({phase:'downloading',availableVersion:result.updateInfo.version,percent:0,message:'Downloading update…'})
        await updater.downloadUpdate()
      }else publish({phase:'idle',message:'Photo Studio is up to date.'})
    }catch{failure()}
    finally{running=false}
    return {...state}
  }

  async function connect(value:unknown) {
    if(running||state.phase==='installing')throw new Error('Wait for the current update operation to finish.')
    if(typeof value!=='string'||!/^\S{20,255}$/.test(value))throw new Error('Enter a valid GitHub access token.')
    if(!safeStorage.isEncryptionAvailable())throw new Error('Windows credential encryption is unavailable. No token was saved.')
    running=true
    const temporary=tokenFile+'.'+randomUUID()+'.tmp'
    try{
      await fs.mkdir(app.getPath('userData'),{recursive:true})
      await fs.writeFile(temporary,safeStorage.encryptString(value))
      await fs.rename(temporary,tokenFile)
    }catch{throw new Error('Could not save encrypted update access.')}
    finally{await fs.unlink(temporary).catch(()=>{});running=false}
    token=value
    publish({connected:true,phase:'idle',message:'Automatic updates enabled.',availableVersion:undefined,percent:undefined})
    void check().catch(()=>{})
    return {...state}
  }

  async function disconnect() {
    if(running||state.phase==='installing')throw new Error('Wait for the current update operation to finish.')
    running=true
    try{await fs.unlink(tokenFile)}catch(error){if((error as NodeJS.ErrnoException).code!=='ENOENT')throw new Error('Could not remove saved update access.')}
    finally{running=false}
    token=''
    // Replace the provider so it no longer retains the disconnected credential.
    updater.setFeedURL({provider:'github',owner:'ezrasong',repo:'photoworkflow'})
    publish({connected:false,phase:'disconnected',message:'Automatic updates disconnected.',availableVersion:undefined,percent:undefined})
    return {...state}
  }

  async function install() {
    if(!token||state.phase!=='ready'||running)throw new Error('Download an update before installing it.')
    if(isBusy())throw new Error('Finish or stop the current job before installing an update.')
    publish({phase:'installing',message:'Closing the local backend safely…'})
    try {
      await stopBackend()
      // Interactive NSIS keeps component verification/download progress visible.
      updater.quitAndInstall(false,true)
    }catch{publish({phase:'error',message:'Could not restart safely. Close Photo Studio and reopen it before retrying.'})}
    return {...state}
  }

  async function initialize() {
    if(!app.isPackaged)return
    try {
      const encrypted=await fs.readFile(tokenFile)
      if(!safeStorage.isEncryptionAvailable())throw new Error('Encryption unavailable')
      token=safeStorage.decryptString(encrypted)
      if(!/^\S{20,255}$/.test(token))throw new Error('Invalid saved credential')
      publish({connected:true,phase:'idle',message:'Automatic updates enabled.'})
      void check().catch(()=>{})
    }catch(error){
      token=''
      if((error as NodeJS.ErrnoException).code!=='ENOENT')publish({connected:false,phase:'error',message:'Saved update access could not be unlocked. Reconnect in Settings.'})
    }
  }
  const timer=setInterval(()=>{if(token&&!isBusy())void check().catch(()=>{})},6*60*60*1000)
  timer.unref()
  return {
    initialize,
    dispose:()=>clearInterval(timer),
    async command(action:unknown,value?:unknown) {
      if(action==='status')return {...state}
      if(action==='connect')return connect(value)
      if(action==='disconnect')return disconnect()
      if(action==='check')return check()
      if(action==='install')return install()
      throw new Error('Unsupported update action')
    }
  }
}
