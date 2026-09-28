const test=require('node:test'),assert=require('node:assert/strict')
const fs=require('node:fs'),fsp=require('node:fs/promises'),os=require('node:os'),path=require('node:path'),vm=require('node:vm')
const {EventEmitter}=require('node:events'),ts=require('typescript')
const source=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/main/updates.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
async function fixture(t){
 const home=await fsp.mkdtemp(path.join(os.tmpdir(),'photo-updates-')),events=[],order=[]
 let updater,busy=false,encryption=true,packaged=true
 class FakeUpdater extends EventEmitter {
  constructor(){super();updater=this;this.checks=0;this.downloads=0}
  setFeedURL(feed){this.feed=feed}
  async checkForUpdates(){this.checks++;return this.checkResult??{isUpdateAvailable:false}}
  async downloadUpdate(){this.downloads++;if(this.downloadError)throw this.downloadError;this.emit('download-progress',{percent:42});this.emit('update-downloaded',{version:'0.1.8'});return ['verified.exe']}
  quitAndInstall(...args){this.installArgs=args;order.push('install')}
 }
 const electron={app:{getVersion:()=> '0.1.7',getPath:()=>home,get isPackaged(){return packaged}},safeStorage:{isEncryptionAvailable:()=>encryption,encryptString:s=>Buffer.from('encrypted:'+Buffer.from(s).toString('base64')),decryptString:b=>{if(!b.toString().startsWith('encrypted:'))throw Error('corrupt');return Buffer.from(b.toString().slice(10),'base64').toString()}}}
 const module={exports:{}}
 const sandbox={exports:module.exports,module,Buffer,setInterval,clearInterval,require:name=>name==='electron'?electron:name==='electron-updater'?{NsisUpdater:FakeUpdater}:require(name)}
 vm.runInNewContext(source,sandbox)
 const api=module.exports.createUpdates(s=>events.push(s),()=>busy,async()=>{order.push('drain')})
 t.after(async()=>{api.dispose();await fsp.rm(home,{recursive:true,force:true})})
 return {home,api,updater,events,order,setBusy:v=>busy=v,setEncryption:v=>encryption=v,setPackaged:v=>packaged=v}
}
const token='github_pat_fixture_read_only_123456'
async function settle(){await new Promise(r=>setImmediate(r))}

test('private updates encrypt access and never return the credential',async t=>{
 const f=await fixture(t);await f.api.initialize()
 await assert.rejects(f.api.command('check'),/read-only/)
 await f.api.command('connect',token);await settle()
 const bytes=await fsp.readFile(path.join(f.home,'update-access.bin'))
 assert.ok(!bytes.includes(Buffer.from(token)))
 assert.equal(f.updater.feed.owner,'ezrasong');assert.equal(f.updater.feed.repo,'photoworkflow');assert.equal(f.updater.feed.private,true)
 assert.equal(f.updater.autoInstallOnAppQuit,false);assert.equal(f.updater.allowDowngrade,false);assert.equal(f.updater.logger,null)
 assert.ok(!JSON.stringify(f.events).includes(token));assert.ok(!JSON.stringify(await f.api.command('status')).includes(token))
 await f.api.command('disconnect');assert.equal((await f.api.command('status')).connected,false)
 assert.equal(f.updater.feed.token,undefined);await assert.rejects(fsp.stat(path.join(f.home,'update-access.bin')),/ENOENT/)
})

test('verified update waits for an idle app and drained backend before interactive install',async t=>{
 const f=await fixture(t);f.updater.checkResult={isUpdateAvailable:true,updateInfo:{version:'0.1.8'}}
 await f.api.command('connect',token);await settle()
 assert.equal(f.updater.downloads,1);assert.equal((await f.api.command('status')).phase,'ready')
 await f.api.command('check');assert.equal(f.updater.downloads,1)
 f.setBusy(true);await assert.rejects(f.api.command('install'),/current job/);assert.deepEqual(f.order,[])
 f.setBusy(false);await f.api.command('install');assert.deepEqual(f.order,['drain','install']);assert.deepEqual(f.updater.installArgs,[false,true])
 await assert.rejects(f.api.command('install'),/Download/)
})

test('failed downloads cannot install or leak upstream headers',async t=>{
 const f=await fixture(t);f.updater.checkResult={isUpdateAvailable:true,updateInfo:{version:'0.1.8'}}
 f.updater.downloadError=Error('Authorization: token '+token)
 await f.api.command('connect',token);await settle()
 assert.equal((await f.api.command('status')).phase,'error');assert.ok(!JSON.stringify(f.events).includes(token))
 await assert.rejects(f.api.command('install'),/Download/);assert.deepEqual(f.order,[])
 f.updater.downloadError=null;await f.api.command('check');assert.equal((await f.api.command('status')).phase,'ready')
})

test('saved access checks on launch; corrupt storage and unavailable encryption fail closed',async t=>{
 const f=await fixture(t)
 f.setEncryption(false);await assert.rejects(f.api.command('connect',token),/encryption/)
 await assert.rejects(fsp.stat(path.join(f.home,'update-access.bin')),/ENOENT/)
 f.setEncryption(true);await f.api.command('connect',token);await settle()
 const checks=f.updater.checks;await f.api.initialize();await settle();assert.equal(f.updater.checks,checks+1)
 await fsp.writeFile(path.join(f.home,'update-access.bin'),'corrupt');await f.api.initialize()
 assert.equal((await f.api.command('status')).connected,false);await assert.rejects(f.api.command('check'),/read-only/)
 await assert.rejects(f.api.command('connect','not a token'),/valid/);await assert.rejects(f.api.command('shell'),/Unsupported/)
})

test('only one network operation runs and access cannot change mid-download',async t=>{
 const f=await fixture(t);let release
 f.updater.checkForUpdates=()=>{f.updater.checks++;return new Promise(r=>release=r)}
 await f.api.command('connect',token);await f.api.command('check');assert.equal(f.updater.checks,1)
 await assert.rejects(f.api.command('disconnect'),/Wait/)
 await assert.rejects(f.api.command('connect',token),/Wait/)
 release({isUpdateAvailable:false});await settle();assert.equal((await f.api.command('status')).phase,'idle')
})
