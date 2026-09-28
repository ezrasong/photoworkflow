import { BrowserWindow, WebContentsView, session } from 'electron'
import { lookup } from 'node:dns/promises'
import { isIP } from 'node:net'

export function publicAddress(ip:string) {
  if(isIP(ip)===4){const [a,b]=ip.split('.').map(Number);return !(a===0||a===10||a===127||a>=224||a===169&&b===254||a===172&&b>=16&&b<=31||a===192&&b===168||a===100&&b>=64&&b<=127||a===198&&(b===18||b===19))}
  // IPv6 global unicast only; mapped IPv4, loopback, ULA and link-local are excluded.
  return isIP(ip)===6 && /^[23]/.test(ip) && !/^2001:(?:0:|db8:)/i.test(ip)
}
export async function browserURL(value:string) {
  const url=new URL(value)
  if(!['https:','http:'].includes(url.protocol)||url.username||url.password||url.port&&!['80','443'].includes(url.port))throw new Error('Enter a public HTTP or HTTPS URL on a standard port')
  const host=url.hostname.replace(/^\[|\]$/g,'')
  const addresses=isIP(host)?[{address:host}]:await lookup(host,{all:true})
  if(!addresses.length||addresses.some(x=>!publicAddress(x.address)))throw new Error('Local and private-network addresses are unavailable in the reference browser')
  return url.href
}

export function referenceBrowser(win:BrowserWindow) {
  const browsing=session.fromPartition('photo-reference-browser') // Memory-only, separate cookies/storage.
  browsing.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false))
  browsing.setPermissionCheckHandler(()=>false)
  browsing.on('will-download',event=>event.preventDefault())
  browsing.webRequest.onBeforeRequest((details,callback)=>{
    if(!['GET','HEAD'].includes(details.method)){callback({cancel:true});return}
    void browserURL(details.url).then(()=>callback({}),()=>callback({cancel:true}))
  })
  const view=new WebContentsView({webPreferences:{session:browsing,sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true}})
  win.contentView.addChildView(view);view.setVisible(false)
  const contents=view.webContents
  contents.setWindowOpenHandler(({url})=>{void browserURL(url).then(url=>contents.loadURL(url)).catch(report);return {action:'deny'}})
  contents.on('will-attach-webview',event=>event.preventDefault())
  function report(error:unknown){if(!win.isDestroyed())win.webContents.send('photo:event',{type:'browser',error:String(error)})}
  function state(){if(!win.isDestroyed())win.webContents.send('photo:event',{type:'browser',url:contents.getURL(),title:contents.getTitle(),back:contents.navigationHistory.canGoBack(),forward:contents.navigationHistory.canGoForward(),loading:contents.isLoading()})}
  contents.on('did-navigate',state);contents.on('did-navigate-in-page',state);contents.on('did-stop-loading',state)
  contents.on('did-fail-load',(_event,code,description)=>{if(code!==-3)report(description)})
  win.on('closed',()=>contents.close())
  return async(action:string,args:any={})=>{
    if(action==='navigate'){const url=await browserURL(args.url);void contents.loadURL(url).catch(report);return true}
    if(action==='back'&&contents.navigationHistory.canGoBack())contents.navigationHistory.goBack()
    else if(action==='forward'&&contents.navigationHistory.canGoForward())contents.navigationHistory.goForward()
    else if(action==='reload')contents.reload()
    else if(action==='bounds'){
      const {x,y,width,height}=args
      if(![x,y,width,height].every(Number.isFinite))throw new Error('Invalid browser bounds')
      const [w,h]=win.getContentSize()
      if(x<0||y<0||width<1||height<1||x+width>w+1||y+height>h+1)throw new Error('Browser bounds must fit the window')
      view.setBounds({x:Math.round(x),y:Math.round(y),width:Math.floor(width),height:Math.floor(height)})
      view.setVisible(true)
    }else if(action==='hide')view.setVisible(false)
    else if(!['back','forward'].includes(action))throw new Error('Unsupported browser action')
    return true
  }
}
