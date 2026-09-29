-- Run the production bridge with a deterministic SDK fixture, never a real catalog.
local bridge = assert(io.open('integrations/PhotoWorkflow.lrplugin/Bridge.lua', 'rb'))
local code = bridge:read('*a'); bridge:close()
local token = '11111111-1111-1111-1111-111111111111'
local nextToken = '22222222-2222-2222-2222-222222222222'
local function photo(id, path)
 return {localIdentifier=id, getRawMetadata=function(_, key)
  return ({path=path,fileFormat='RAW'})[key]
 end, getDevelopSettings=function() return {Exposure2012=0} end,
 getFormattedMetadata=function() return '' end}
end
local intended=photo(1,'C:/photos/intended.arw')
local other=photo(2,'C:/elsewhere/other.arw')
local folder={}
local active, targets, visible, blocked, catalogPath, exports, imports
local catalog={}
function catalog:getPath() return catalogPath end
function catalog:getTargetPhoto() return active end
function catalog:getTargetPhotos() return targets end
function catalog:findPhotoByPath(path) assert(path==intended:getRawMetadata('path')); return intended end
function catalog:getFolderByPath(path) assert(path=='C:/photos'); return folder end
function catalog:setActiveSources(sources) assert(#sources==1 and sources[1]==folder); visible=true end
function catalog:setSelectedPhotos(p, photos)
 assert(p==intended and #photos==1 and photos[1]==intended)
 if visible and not blocked then active=p; targets={p} end
end
function catalog:withWriteAccessDo(_, fn) imports=imports+1; fn() end
function catalog:addPhoto() return intended end
function catalog:createVirtualCopies() error('Inspection must never develop a photo') end
local sdk={
 LrApplication={activeCatalog=function() return catalog end},
 LrTasks={},
 LrFileUtils={exists=function() return 'file' end,createAllDirectories=function() end},
 LrPathUtils={parent=function(p) return p:match('^(.*)/[^/]+$') end,child=function(a,b) return a..'/'..b end},
 LrExportSession=function(args)
  assert(#args.photosToExport==1 and args.photosToExport[1]==intended)
  exports=exports+1
  return {renditions=function()
   local done=false
   return function()
    if done then return end
    done=true
    return 1,{waitForRender=function() return true,'C:/queue/render/intended.tif' end}
   end
  end}
 end
}
function import(name) return assert(sdk[name],name) end
_PLUGIN={path='C:/workspace/apps/PhotoWorkflow.lrplugin'}
PhotoWorkflowRunning=true
local execute=assert((loadstring or load)(code..'\nreturn execute'))()
local function reset()
 active=other; targets={other}; visible=false; blocked=false
 catalogPath='C:/catalog.lrcat'; exports=0; imports=0
end
local function request(operation, selection, catalogName, requestToken)
 return execute({operation=operation,selection=selection,catalog=catalogName,
  source=operation=='import_photo' and 'C:/photos/intended.arw' or nil,
  token=requestToken or token,expires=tostring(os.time()+25)},'C:/queue')
end
local function rejects(fn, message)
 local ok, err=pcall(fn)
 assert(not ok and tostring(err):find(message,1,true),tostring(err))
end
reset()
-- A catalog read requires no selection; an explicit import changes the view first.
active=nil; targets={other,intended}
assert(request('catalog').ok)
assert(request('import_photo',nil,catalogPath).selection==token)
assert(visible and active==intended and #targets==1)
assert(request('export',token,catalogPath).ok and exports==1 and imports==0)

-- No target must not be mistaken for getTargetPhotos' all-in-source fallback.
for _, photos in ipairs({{}, {intended}, {intended,other}}) do
 reset(); active=nil; targets=photos
 rejects(function() request('status') end,'No photo selected')
end
reset(); targets={intended,other}; active=intended
rejects(function() request('status') end,'Select exactly one photo')

-- A hidden/filtered import may leave zero, multiple, or one WRONG target.
for _, photos in ipairs({{}, {other}, {intended,other}}) do
 reset(); blocked=true; targets=photos; active=photos[1]
 rejects(function() request('import_photo',nil,catalogPath) end,'retry')
 assert(exports==0)
 blocked=false
 assert(request('import_photo',nil,catalogPath,nextToken).selection==nextToken)
 assert(request('export',nextToken,catalogPath).ok)
end

-- Selection/catalog changes and stale tokens still stop before export/develop.
reset(); request('import_photo',nil,catalogPath)
active=other; targets={other}
rejects(function() request('export',token,catalogPath) end,'Selection or catalog changed')
rejects(function() request('develop',token,catalogPath) end,'Selection or catalog changed')
active=intended; targets={intended}
rejects(function() request('export',nextToken,catalogPath) end,'Selection or catalog changed')
catalogPath='C:/different.lrcat'
rejects(function() request('export',token,'C:/catalog.lrcat') end,'Catalog changed')
rejects(function() request('export',token) end,'Selection or catalog changed')
assert(exports==0 and intended:getDevelopSettings().Exposure2012==0)
print('Lightroom selection SDK fixtures passed')
