local Tasks = import 'LrTasks'
local App = import 'LrApplication'
local Files = import 'LrFileUtils'
local Paths = import 'LrPathUtils'
local Export = import 'LrExportSession'
local selectionToken, selectionPhoto, selectionCatalog
local function same(a,b)
 if type(a)~=type(b) then return false end
 if type(a)~='table' then return a==b end
 for k,v in pairs(a) do if not same(v,b[k]) then return false end end
 for k,_ in pairs(b) do if a[k]==nil then return false end end
 return true
end
local function normalized(path) return path:gsub('\\','/'):lower() end
local root = Paths.parent(Paths.parent(_PLUGIN.path))
local queue = Paths.child(root, '.cache/lightroom')
local limits = {Exposure2012={-3,3}, Contrast2012={-100,100}, Highlights2012={-100,100},
 Shadows2012={-100,100}, Whites2012={-100,100}, Blacks2012={-100,100},
 Vibrance={-100,100}, Saturation={-100,100}, Temperature={2000,50000}, Tint={-150,150},
 SaturationAdjustmentPurple={-100,100}, LuminanceSmoothing={0,100}, ColorNoiseReduction={0,100},
 LuminanceNoiseReductionDetail={0,100},LuminanceNoiseReductionContrast={0,100},
 ColorNoiseReductionDetail={0,100},ColorNoiseReductionSmoothness={0,100},
 CropTop={0,1},CropBottom={0,1},CropLeft={0,1},CropRight={0,1},CropAngle={-15,15},
 ParametricShadows={-100,100},ParametricDarks={-100,100},ParametricLights={-100,100},ParametricHighlights={-100,100},
 LensProfileEnable={0,1},AutoLateralCA={0,1},LensManualDistortionAmount={-100,100},
 VignetteAmount={-100,100},VignetteMidpoint={0,100}}
local curves={ToneCurvePV2012=true,ToneCurvePV2012Red=true,ToneCurvePV2012Green=true,ToneCurvePV2012Blue=true}
local geometry={CropTop=true,CropBottom=true,CropLeft=true,CropRight=true,CropAngle=true}
local function quote(s)
 return '"' .. tostring(s):gsub('[%z\1-\31\\"]', function(c)
  if c == '\\' then return '\\\\' elseif c == '"' then return '\\"' end
  return string.format('\\u%04x', string.byte(c)) end) .. '"'
end
local function json(v)
 if type(v)=='table' then
  if #v>0 then
   local out={}; for _,x in ipairs(v) do out[#out+1]=json(x) end
   return '['..table.concat(out,',')..']'
  end
  local out={}; for k,x in pairs(v) do out[#out+1]=quote(k)..':'..json(x) end
  return '{'..table.concat(out,',')..'}'
 elseif type(v)=='number' or type(v)=='boolean' then return tostring(v)
 elseif v == nil then return 'null' else return quote(v) end
end
local function write(path, data)
 local f=assert(io.open(path..'.partial','wb')); f:write(json(data)); f:close()
 assert(Files.move(path..'.partial',path))
end
local function selected(catalog, id)
 -- With no active photo, getTargetPhotos can return the entire current source.
 assert(catalog:getTargetPhoto(), 'No photo selected in Lightroom. Select the intended photo, then retry. If it is hidden, open its folder and clear Library filters.')
 local photos=catalog:getTargetPhotos() or {}
 assert(#photos==1, 'Select exactly one photo in Lightroom, then retry. If the intended photo is hidden, open its folder and clear Library filters.')
 local photo=photos[1]
 assert(photo:getRawMetadata('fileFormat')~='VIDEO', 'Select a still photograph')
 assert(Files.exists(photo:getRawMetadata('path')), 'Selected source is missing or offline')
 if id then
  assert(id==selectionToken and photo.localIdentifier==selectionPhoto and catalog:getPath()==selectionCatalog,
   'Selection or catalog changed; read selection again')
 end
 return photo
end
local function selectImported(catalog, photo)
 -- setSelectedPhotos silently ignores photos outside the active view source.
 -- The explicit import owns this selection; expose its folder before selecting.
 local folder=assert(catalog:getFolderByPath(Paths.parent(photo:getRawMetadata('path'))),
  'Cannot show the imported photo folder. Open it in Lightroom and retry.')
 catalog:setActiveSources({folder})
 catalog:setSelectedPhotos(photo,{photo})
 assert(App.activeCatalog():getPath()==catalog:getPath(), 'Catalog changed; retry in the intended catalog')
 local actual=selected(catalog)
 assert(actual.localIdentifier==photo.localIdentifier,
  'Lightroom did not select the requested photo. Clear Library filters, select the intended photo, then retry.')
 return actual
end
local function describe(photo, token)
 local values={}
 local settings=photo:getDevelopSettings()
 for key,_ in pairs(limits) do values[key]=settings[key] end
 for key,_ in pairs(curves) do values[key]=settings[key] end
 -- Read-only context: existing sharpening affects how denoising should be judged.
 for _,key in ipairs({'Sharpness','SharpenRadius','SharpenDetail','SharpenEdgeMasking'}) do values[key]=settings[key] end
 selectionToken=token; selectionPhoto=photo.localIdentifier
 selectionCatalog=App.activeCatalog():getPath()
 return {ok=true,selection=selectionToken,settings=values,
  source=photo:getRawMetadata('path'),catalog=selectionCatalog,
  file_format=photo:getRawMetadata('fileFormat'),
  camera_make=photo:getFormattedMetadata('cameraMake'),camera_model=photo:getFormattedMetadata('cameraModel'),
  iso=photo:getFormattedMetadata('isoSpeedRating'),
  dimensions=photo:getRawMetadata('dimensions'),cropped_dimensions=photo:getRawMetadata('croppedDimensions'),
  orientation=settings.orientation,lens_profile=settings.LensProfileName,
  virtual_copy=photo:getRawMetadata('isVirtualCopy') or false}
end
local function render(photo, folder)
 local dest=Paths.child(folder,'render'); Files.createAllDirectories(dest)
 local session=Export{photosToExport={photo},exportSettings={
  LR_export_destinationType='specificFolder', LR_export_destinationPathPrefix=dest,
  LR_export_useSubfolder=false, LR_format='TIFF', LR_tiff_bitDepth=16,
  LR_tiff_compressionMethod='compressionMethod_ZIP', LR_export_colorSpace='sRGB',
  LR_size_doConstrain=false, LR_outputSharpeningOn=false, LR_reimportExportedPhoto=false,
  LR_collisionHandling='ask', LR_renamingTokensOn=false, LR_minimizeEmbeddedMetadata=true}}
 local rendered
 for _,rendition in session:renditions{} do
  local ok,path=rendition:waitForRender()
  if not ok and photo:getRawMetadata('fileFormat')=='HEIC' then
   error('Lightroom could not decode/export this HEIC/HEIF. Check that this file opens in Lightroom and that Adobe-required HEIF/HEVC support is available. No conversion or retry was applied. Adobe: '..tostring(path))
  end
  assert(ok,path); rendered=path
 end
 assert(rendered,'No TIFF rendered'); return rendered
end
local function execute(req, folder)
 assert(tonumber(req.expires) and tonumber(req.expires)>=os.time(), 'Request expired')
 assert(type(req.token)=='string' and #req.token==36 and req.token:match('^[%x%-]+$'), 'Invalid selection token')
 local catalog=App.activeCatalog()
 if req.catalog then assert(normalized(req.catalog)==normalized(catalog:getPath()), 'Catalog changed; batch stopped') end
 if req.operation=='catalog' then return {ok=true,catalog=catalog:getPath(),bridge_version=4} end
 if req.operation=='import_photo' then
  assert(req.catalog and req.source and req.source:match('^[A-Za-z]:[\\/]'), 'Explicit local source and catalog required')
  local extensions={jpg=true,jpeg=true,png=true,tif=true,tiff=true,dng=true,cr2=true,cr3=true,
   nef=true,nrw=true,arw=true,raf=true,orf=true,rw2=true,pef=true,heic=true,heif=true}
  assert(extensions[req.source:match('%.([^%.]+)$'):lower()], 'Unsupported photograph type')
  assert(Files.exists(req.source)=='file', 'Source is missing')
  local photo=catalog:findPhotoByPath(req.source)
  if not photo then catalog:withWriteAccessDo('Import requested photo', function() photo=catalog:addPhoto(req.source) end) end
  return describe(selectImported(catalog,photo),req.token)
 end
 if req.operation=='import_fixture' then
  local p=catalog:getPath():gsub('\\','/'):lower()
  local allowed=Paths.child(root,'tests/lightroom'):gsub('\\','/'):lower()..'/'
  assert(p:sub(1,#allowed)==allowed, 'Fixture import requires workspace test catalog')
  local path=Paths.child(root,'tests/fixtures/astronaut.png')
  local photo=catalog:findPhotoByPath(path)
  if not photo then catalog:withWriteAccessDo('Import public test fixture', function() photo=catalog:addPhoto(path) end) end
  catalog:setSelectedPhotos(photo,{photo})
  return describe(photo,req.token)
 end
 local photo=selected(catalog,req.selection)
 if req.operation=='status' then return describe(photo,req.token) end
 assert(req.selection, 'Selection required')
 if req.operation=='develop' then
  local settings={}; local count=0
  for key,value in pairs(req) do
   if key~='operation' and key~='selection' and key~='expires' and key~='token' and key~='catalog' then
    if curves[key] then
     assert(value:match('^[%d,]+$') and not value:find(',,') and value:sub(1,1)~=',' and value:sub(-1)~=',','Invalid curve encoding')
     local points={}; for v in value:gmatch('[^,]+') do
      local n=tonumber(v); assert(n and n%1==0 and n>=0 and n<=255,'Invalid curve point'); points[#points+1]=n
     end
     assert(#points>=4 and #points<=32 and #points%2==0 and points[1]==0 and points[#points-1]==255,'Invalid curve endpoints')
     for i=3,#points,2 do assert(points[i]>points[i-2] and points[i+1]>=points[i-1],'Curve must be monotonic') end
     settings[key]=points
    else
     local b=assert(limits[key], 'Unsupported Develop field'); local n=tonumber(value)
     assert(n and n==n and n>=b[1] and n<=b[2], 'Develop value out of bounds')
     if key=='LensProfileEnable' or key=='AutoLateralCA' then assert(n==0 or n==1,'Expected 0 or 1') end
     settings[key]=n
    end
    count=count+1
   end
  end
  assert(count>0, 'No settings supplied')
  if settings.CropTop or settings.CropBottom or settings.CropLeft or settings.CropRight then
   assert(settings.CropTop and settings.CropBottom and settings.CropLeft and settings.CropRight,'Supply all crop edges')
   assert(settings.CropRight-settings.CropLeft>=.05 and settings.CropBottom-settings.CropTop>=.05,'Crop too small or inverted')
   settings.HasCrop=true
  end
  for key,_ in pairs(curves) do if settings[key] then settings.ToneCurveName2012='Custom' end end
  if settings.LensProfileEnable or settings.AutoLateralCA or settings.LensManualDistortionAmount or settings.VignetteAmount or settings.VignetteMidpoint then
   settings.EnableLensCorrections=true
  end
  if settings.Temperature or settings.Tint then
   local format=photo:getRawMetadata('fileFormat')
   assert(format=='RAW' or format=='DNG', 'Kelvin white balance is supported only for RAW/DNG; use raster warmth for TIFF/JPEG')
   settings.WhiteBalance='Custom'
  end
  local original=photo.localIdentifier
  local before=photo:getDevelopSettings()
  local copies=catalog:createVirtualCopies('Photo Assistant '..os.date('%Y-%m-%d %H:%M:%S'))
  assert(#copies==1, 'Could not create one virtual copy')
  local copy=copies[1]
  local crop={}; for key,_ in pairs(geometry) do if settings[key] then crop[key]=settings[key] end end
  local baseline
  if next(crop) then
   if settings.HasCrop then crop.HasCrop=true end
   catalog:withWriteAccessDo('Match review crop',function() copy:applyDevelopSettings(crop,'Review geometry') end)
   baseline=render(copy,Paths.child(folder,'baseline'))
  end
  catalog:withWriteAccessDo('Local Photo Assistant Develop', function()
   copy:applyDevelopSettings(settings, 'Local Photo Assistant')
  end)
  local result=describe(copy,req.token)
  local actual=copy:getDevelopSettings()
  for k,v in pairs(settings) do
   local equal=same(actual[k],v)
   if type(v)=='number' and type(actual[k])=='number' then equal=math.abs(actual[k]-v)<0.00001 end
   if limits[k] or curves[k] or k=='WhiteBalance' then assert(equal,'Develop readback mismatch: '..k) end
  end
  if settings.LensProfileEnable==1 then assert(actual.LensProfileName and actual.LensProfileName~='', 'No matching lens profile; inspect copy before retrying') end
  local after=photo:getDevelopSettings()
  assert(same(before,after), 'Original settings changed')
  result.original_selection=tostring(original); result.original_settings_preserved=true
  result.baseline_path=baseline
  return result
 elseif req.operation=='export' then
  local rendered=render(photo,folder)
  return {ok=true,path=rendered,selection=req.selection,bit_depth=16}
 end
 error('Unsupported operation')
end
if not _G.PhotoWorkflowRunning then
 _G.PhotoWorkflowRunning=true
 Tasks.startAsyncTask(function()
  Files.createAllDirectories(queue)
  while _G.PhotoWorkflowRunning do
   for folder in Files.directoryEntries(queue) do
    if Files.exists(folder)=='directory' then
     local request=Paths.child(folder,'request.txt')
     if Files.exists(request) then
      local ok,result=Tasks.pcall(function()
       assert(Files.move(request,Paths.child(folder,'processing.txt')))
       local raw=Files.readFile(Paths.child(folder,'processing.txt'))
       assert(#raw<8192,'Request too large')
       local req={}
       for line in raw:gmatch('[^\r\n]+') do
        local k,v=line:match('^([A-Za-z0-9_]+)\t([^\t]+)$')
        assert(k and not req[k],'Malformed request'); req[k]=v
       end
       return execute(req,folder)
      end)
      write(Paths.child(folder,'response.json'),ok and result or {ok=false,error=tostring(result)})
     end
    end
   end
   Tasks.sleep(.3)
  end
 end)
end
