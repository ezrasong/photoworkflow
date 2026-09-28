// Adapted from OpenCode's actual Electron window/protocol implementation.
// Copyright OpenCode contributors, MIT. See vendor/opencode/LICENSE and UPSTREAM.md.
import windowState from 'electron-window-state'
import { BrowserWindow, net, protocol } from 'electron'
import { isAbsolute, join, relative, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const rendererRoot = join(__dirname, '../renderer')
const rendererProtocol = 'photo'
const rendererHost = 'renderer'
protocol.registerSchemesAsPrivileged([{scheme:rendererProtocol,privileges:{secure:true,standard:true,supportFetchAPI:true,stream:true}}])

export function trusted(value: string) {
  try {
    const url = new URL(value)
    if (url.protocol === 'photo:' && url.host === rendererHost) return true
    return !!process.env.ELECTRON_RENDERER_URL && url.origin === new URL(process.env.ELECTRON_RENDERER_URL).origin
  } catch { return false }
}

export function registerRendererProtocol() {
  protocol.handle(rendererProtocol, async request => {
    const url = new URL(request.url)
    if (url.host !== rendererHost) return new Response('Not found',{status:404})
    const file = resolve(rendererRoot, `.${decodeURIComponent(url.pathname)}`)
    const rel = relative(rendererRoot,file)
    if (rel.startsWith('..') || isAbsolute(rel)) return new Response('Not found',{status:404})
    try { return await net.fetch(pathToFileURL(file).toString()) }
    catch { return new Response('Not found',{status:404}) }
  })
}

export function createWindow() {
  const state=windowState({defaultWidth:1440,defaultHeight:960})
  const win=new BrowserWindow({x:state.x,y:state.y,width:state.width,height:state.height,
    minWidth:640,minHeight:480,show:false,autoHideMenuBar:true,title:'Photo Studio',backgroundColor:'#101010',
    titleBarStyle:'hidden',titleBarOverlay:{color:'#101010',symbolColor:'#eeeeee',height:40},
    webPreferences:{preload:join(__dirname,'../preload/index.js'),contextIsolation:true,nodeIntegration:false,sandbox:true}})
  win.webContents.session.setPermissionRequestHandler((_wc,_p,cb)=>cb(false))
  win.webContents.session.setPermissionCheckHandler(()=>false)
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}))
  win.webContents.on('will-navigate',(event,url)=>{if(!trusted(url))event.preventDefault()})
  win.webContents.on('will-attach-webview',event=>event.preventDefault())
  state.manage(win)
  if(process.env.ELECTRON_RENDERER_URL) void win.loadURL(process.env.ELECTRON_RENDERER_URL)
  else void win.loadURL('photo://renderer/index.html')
  win.once('ready-to-show',()=>win.show())
  return win
}
