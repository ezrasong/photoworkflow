import { app } from 'electron'
import { NsisUpdater } from 'electron-updater'

type UpdateState = {
  version:string; connected:boolean; phase:'disconnected'|'idle'|'checking'|'downloading'|'ready'|'installing'|'error';
  message:string; availableVersion?:string; percent?:number
}

// Public releases require no credentials; legacy saved tokens are never read.
export function createUpdates(emit:(state:UpdateState)=>void, isBusy:()=>boolean, stopBackend:()=>Promise<void>) {
  const updater=new NsisUpdater()
  updater.logger=null
  updater.autoDownload=false // Own the check + download promise as one operation.
  updater.autoInstallOnAppQuit=false
  updater.allowPrerelease=false
  updater.allowDowngrade=false
  // Full downloads also support upgrades from the former private releases.
  updater.disableDifferentialDownload=true
  let running=false
  let state:UpdateState={version:app.getVersion(),connected:true,phase:'idle',message:'Automatic updates enabled.'}
  const publish=(value:Partial<UpdateState>)=>{state={...state,...value};emit({...state})}
  const failure=()=>publish({phase:'error',message:state.phase==='installing'?'The update installer could not start. Close and reopen Photo Studio, then retry.':'Update failed. Check your internet connection and retry. Your current installation is unchanged.'})
  updater.on('error',failure) // Never forward upstream errors: they may contain headers.
  updater.on('download-progress',p=>publish({phase:'downloading',percent:Math.max(0,Math.min(100,p.percent)),message:'Downloading update…'}))
  updater.on('update-downloaded',info=>publish({phase:'ready',availableVersion:info.version,percent:100,message:'Update downloaded and verified. Restart to install when your work is finished.'}))

  async function check() {
    if(!app.isPackaged)throw new Error('Updates are available in the installed app.')
    if(running||state.phase==='ready'||state.phase==='installing')return {...state}
    running=true
    try {
      publish({phase:'checking',message:'Checking for updates…',percent:undefined,availableVersion:undefined})
      updater.setFeedURL({provider:'github',owner:'ezrasong',repo:'photoworkflow',private:false})
      const result=await updater.checkForUpdates()
      if(result?.isUpdateAvailable){
        publish({phase:'downloading',availableVersion:result.updateInfo.version,percent:0,message:'Downloading update…'})
        await updater.downloadUpdate()
      }else publish({phase:'idle',message:'Photo Studio is up to date.'})
    }catch{failure()}
    finally{running=false}
    return {...state}
  }

  async function install() {
    if(state.phase!=='ready'||running)throw new Error('Download an update before installing it.')
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
    void check().catch(()=>{})
  }
  const timer=setInterval(()=>{if(app.isPackaged&&!isBusy())void check().catch(()=>{})},6*60*60*1000)
  timer.unref()
  return {
    initialize,
    dispose:()=>clearInterval(timer),
    async command(action:unknown) {
      if(action==='status')return {...state}
      if(action==='check')return check()
      if(action==='install')return install()
      throw new Error('Unsupported update action')
    }
  }
}
