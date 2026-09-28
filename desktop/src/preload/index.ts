// Narrow capability bridge adapted from OpenCode's contextBridge/webUtils preload.
import { contextBridge, ipcRenderer, webUtils } from 'electron'
contextBridge.exposeInMainWorld('photo', {
  call:(method:string,args:unknown={})=>ipcRenderer.invoke('photo:call',method,args),
  pick:(kind:string)=>ipcRenderer.invoke('photo:pick',kind),
  drop:(files:File[])=>ipcRenderer.invoke('photo:drop',files.map(file=>webUtils.getPathForFile(file))),
  preview:(path:string,full=false)=>ipcRenderer.invoke('photo:preview',path,full),
  browser:(action:string,args:unknown={})=>ipcRenderer.invoke('photo:browser',action,args),
  reveal:(path:string)=>ipcRenderer.invoke('photo:reveal',path),
  events:(callback:(event:unknown)=>void)=>{
    const listener=(_:unknown,event:unknown)=>callback(event)
    ipcRenderer.on('photo:event',listener)
    return ()=>ipcRenderer.removeListener('photo:event',listener)
  }
})
