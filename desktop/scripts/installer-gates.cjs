// Execute the production NSIS gate against small, deterministic child executables.
// No registry writes, shortcuts, real app installation or model downloads.
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict')
const {spawnSync}=require('node:child_process')
const {getMakeNsisPath}=require('app-builder-lib/out/toolsets/windows')
const root=path.resolve(__dirname,'../..'),out=path.join(root,'.cache/installer-acceptance',String(Date.now()))
;(async()=>{
 const compiler=await getMakeNsisPath()
 const compile=async(name,source)=>{
  const file=path.join(out,name+'.nsi');await fs.writeFile(file,source)
  const result=spawnSync(compiler.path,['/V2',file],{env:{...process.env,...compiler.env},encoding:'utf8',windowsHide:true})
  assert.equal(result.status,0,result.stdout+result.stderr)
 }
 const checks=[]
 for(const expected of [0,1,2,'missing']){
  const dir=path.join(out,'case '+expected),python=path.join(dir,'resources/backend/python'),receipt=path.join(dir,'command.txt'),complete=path.join(dir,'complete.txt')
  await fs.mkdir(python,{recursive:true})
  if(expected!=='missing')await compile('child-'+expected,`
!include "FileFunc.nsh"
OutFile "${path.join(python,'pythonw.exe')}"
RequestExecutionLevel user
SilentInstall silent
Section
 \${GetParameters} $0
 FileOpen $1 "${receipt}" w
 FileWrite $1 $0
 FileClose $1
 SetErrorLevel ${expected}
 Quit
SectionEnd
`)
  const installer=path.join(out,'gate-'+expected+'.exe')
  await compile('gate-'+expected,`
!include "LogicLib.nsh"
!include "${path.join(root,'desktop/resources/installer.nsh')}"
OutFile "${installer}"
RequestExecutionLevel user
SilentInstall silent
Section
 StrCpy $INSTDIR "${dir}"
 !insertmacro customInstall
 FileOpen $2 "${complete}" w
 FileWrite $2 "complete"
 FileClose $2
SectionEnd
`)
  const result=spawnSync(installer,['/S'],{windowsHide:true,timeout:30000})
  assert.equal(result.error,undefined)
  assert.equal(result.status,expected==='missing'?1:expected,'installer exit for '+expected)
  const finished=await fs.stat(complete).then(()=>true,()=>false)
  assert.equal(finished,expected===0,'Finish must require successful setup')
  if(expected!=='missing'){
   const command=await fs.readFile(receipt,'utf8')
   assert.ok(command.startsWith('-I "'+path.join(dir,'resources/backend/scripts/install_desktop.py')+'"'),command)
   assert.ok(command.endsWith('--silent'),command)
  }
  checks.push({childExit:expected,installerExit:result.status,finished})
 }
 // Compile and execute electron-builder's actual data-removal block and our
 // updater hook. Redirect shell-folder constants into fixtures, never real AppData.
 const config=require('../package.json')
 assert.equal(config.build.nsis.deleteAppDataOnUninstall,true)
 const template=await fs.readFile(path.join(root,'desktop/node_modules/app-builder-lib/templates/nsis/uninstaller.nsh'),'utf8')
 const cleanup=template.slice(template.indexOf('  Var /GLOBAL isDeleteAppData'),template.indexOf('  DeleteRegKey SHELL_CONTEXT'))
 assert.ok(cleanup.includes('RMDir /r "$APPDATA\\${APP_PACKAGE_NAME}"'))
 const sandbox=source=>source.replaceAll('$APPDATA','$sandboxRoaming').replaceAll('$LOCALAPPDATA','$sandboxLocal')
 const hooks=await fs.readFile(path.join(root,'desktop/resources/installer.nsh'),'utf8')
 await fs.writeFile(path.join(out,'sandbox-hooks.nsh'),sandbox(hooks))
 for(const updated of [false,true]){
  const dir=path.join(out,updated?'upgrade':'uninstall'),roaming=path.join(dir,'roaming'),local=path.join(dir,'local')
  const owned=[path.join(roaming,config.name,'Workspace/models/model.gguf'),path.join(roaming,config.name,'Workspace/runtime/library.bin'),path.join(roaming,config.name,'Workspace/outputs/result.tif'),path.join(roaming,config.name,'Workspace/Photo Vault/note.md'),path.join(roaming,'Photo Studio','Cache/cache.bin'),path.join(local,'photo-workflow-updater/installer.exe')]
  const preserved=[path.join(dir,'original-photo.jpg'),path.join(dir,'custom-workspace/model.gguf'),path.join(roaming,'another-app/keep.txt')]
  for(const file of [...owned,...preserved]){await fs.mkdir(path.dirname(file),{recursive:true});await fs.writeFile(file,'fixture')}
  const writer=path.join(dir,'write-uninstaller.exe'),uninstaller=path.join(dir,'uninstall.exe')
  await compile('uninstall-'+updated,`
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!define DELETE_APP_DATA_ON_UNINSTALL
!define APP_FILENAME "Photo Studio"
!define APP_PRODUCT_FILENAME "Photo Studio"
!define APP_PACKAGE_NAME "${config.name}"
!define isUpdated '$testUpdated == "1"'
!include "${path.join(out,'sandbox-hooks.nsh')}"
OutFile "${writer}"
RequestExecutionLevel user
SilentInstall silent
SilentUnInstall silent
Var testUpdated
Var installMode
Var sandboxRoaming
Var sandboxLocal
Section
 WriteUninstaller "${uninstaller}"
SectionEnd
Section "Uninstall"
 StrCpy $testUpdated "${updated?1:0}"
 StrCpy $installMode "current"
 StrCpy $sandboxRoaming "${roaming}"
 StrCpy $sandboxLocal "${local}"
 !insertmacro customUnInstall
 ${sandbox(cleanup)}
SectionEnd
`)
  for(const [exe,args] of [[writer,['/S']],[uninstaller,['/S','_?='+dir]]]){
   const result=spawnSync(exe,args,{windowsHide:true,timeout:30000});assert.equal(result.error,undefined);assert.equal(result.status,0,result.stdout+result.stderr)
  }
  for(const file of owned)assert.equal(await fs.stat(file).then(()=>true,()=>false),updated,file)
  for(const file of preserved)assert.equal(await fs.readFile(file,'utf8'),'fixture')
  checks.push({updated,workspaceAndUpdaterRemoved:!updated,externalFilesPreserved:true})
 }
 await fs.writeFile(path.join(out,'report.json'),JSON.stringify({status:'passed',checks},null,2))
 console.log('Installer gates, real NSIS workspace/updater removal and upgrade preservation passed:',out)
})().catch(error=>{console.error(error);process.exitCode=1})
