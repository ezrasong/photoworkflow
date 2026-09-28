"""Bounded conventional Photoshop selections, curves and donor-pixel cloning."""
import json
import math
from pathlib import Path

from .lightroom import validate_curve
from .runtime import ROOT, check_cancel, json_write, sha256, workspace_path


def validate_operations(operations):
    if not isinstance(operations, list) or not 1 <= len(operations) <= 8:
        raise ValueError('Supply 1–8 local operations')
    def number(value, low, high):
        return type(value) in (int, float) and math.isfinite(value) and low <= value <= high
    for op in operations:
        if not isinstance(op, dict) or op.get('kind') not in {'curve', 'clone'}:
            raise ValueError('Only local curves and donor cloning are supported')
        fields = {'kind', 'region', 'feather', 'curve'} if op['kind'] == 'curve' else {'kind', 'region', 'feather', 'donor_offset'}
        if set(op) != fields: raise ValueError('Invalid local operation fields')
        region = op['region']
        if not isinstance(region, list) or len(region) != 4 or not all(number(v, 0, 1) for v in region):
            raise ValueError('Region is [left, top, right, bottom], normalized to the current rendered image')
        left, top, right, bottom = region
        if right-left < .005 or bottom-top < .005: raise ValueError('Region is inverted or too small')
        if not number(op['feather'], 0, .05): raise ValueError('Feather must be 0–0.05 of the shorter image edge')
        if op['kind'] == 'curve': validate_curve(op['curve'])
        else:
            delta = op['donor_offset']
            if not isinstance(delta, list) or len(delta) != 2 or not all(number(v, -1, 1) for v in delta):
                raise ValueError('Donor offset needs normalized dx,dy; source = destination + offset')
            dx, dy = delta
            if abs(dx) < .005 and abs(dy) < .005: raise ValueError('Choose a separate donor')
            # Keep the whole donor rectangle and feather margin inside the photograph.
            f = op['feather']
            if min(left+dx, top+dy) < f or max(right+dx, bottom+dy) > 1-f:
                raise ValueError('Donor and feather extend outside the image')
    return operations


JSX = r'''
#target photoshop
(function(){
 var root=File($.fileName).parent, ops=__OPERATIONS__;
 var previous=app.documents.length?app.activeDocument:null, oldDialogs=app.displayDialogs;
 var oldUnits=app.preferences.rulerUnits, source, doc, temp, opened=false;
 app.displayDialogs=DialogModes.NO; app.preferences.rulerUnits=Units.PIXELS;
 function save(d,name){
  var f=File(root+'/'+name); if(f.exists)throw Error('Refusing overwrite: '+name);
  var o=new TiffSaveOptions();o.imageCompression=TIFFEncoding.TIFFZIP;o.layers=false;o.alphaChannels=false;o.embedColorProfile=true;
  d.saveAs(f,o,true,Extension.LOWERCASE);
 }
 function select(d,op){
  var r=op.region,w=d.width.as('px'),h=d.height.as('px');
  d.selection.select([[r[0]*w,r[1]*h],[r[2]*w,r[1]*h],[r[2]*w,r[3]*h],[r[0]*w,r[3]*h]],SelectionType.REPLACE,0,false);
  var feather=Math.min(64,Math.min(w,h)*op.feather);if(feather>0)d.selection.feather(feather);
 }
 function mask(){
  var d=new ActionDescriptor(),r=new ActionReference();
  d.putClass(charIDToTypeID('Nw  '),charIDToTypeID('Chnl'));
  r.putEnumerated(charIDToTypeID('Chnl'),charIDToTypeID('Chnl'),charIDToTypeID('Msk '));d.putReference(charIDToTypeID('At  '),r);
  d.putEnumerated(charIDToTypeID('Usng'),charIDToTypeID('UsrM'),charIDToTypeID('RvlS'));
  executeAction(charIDToTypeID('Mk  '),d,DialogModes.NO);
 }
 try {
  var file=File(__SOURCE__);
  for(var i=0;i<app.documents.length;i++){try{if(app.documents[i].fullName.fsName.toLowerCase()==file.fsName.toLowerCase())source=app.documents[i];}catch(_){}}
  if(source){
   // A selected disk render must not be replaced with unsaved Photoshop pixels.
   file=File(root+'/source-render.tif');
   if(file.exists || !File(__SOURCE__).copy(file))throw Error('Cannot isolate the open source render');
   source=null;
  }
  if(!source){source=app.open(file);opened=true;}
  doc=source.duplicate('Luma Atelier local corrections',true);
  if(opened){source.close(SaveOptions.DONOTSAVECHANGES);source=null;}
  app.activeDocument=doc;
  if(doc.bitsPerChannel!=BitsPerChannelType.SIXTEEN || doc.mode!=DocumentMode.RGB)throw Error('Expected 16-bit RGB');
  for(var n=0;n<ops.length;n++){
   var op=ops[n],name='local-'+('0'+(n+1)).slice(-2),w=doc.width.as('px'),h=doc.height.as('px');
   var layer=doc.activeLayer.duplicate();doc.activeLayer=layer;
   layer.name=op.kind=='curve'?'Local tonal curve':'Clone from existing pixels';
   if(op.kind=='curve'){
    var points=[];for(var j=0;j<op.curve.length;j+=2)points.push([op.curve[j],op.curve[j+1]]);
    layer.adjustCurves(points);
   }else{layer.translate(UnitValue(-Math.round(op.donor_offset[0]*w),'px'),UnitValue(-Math.round(op.donor_offset[1]*h),'px'));}
   // Unmasked correction asset for an independently editable mask in the final PSD.
   temp=doc.duplicate('Correction asset',false);
   for(var j=0;j<temp.layers.length;j++)temp.layers[j].visible=(j==0);
   temp.flatten();save(temp,name+'.tif');temp.close(SaveOptions.DONOTSAVECHANGES);temp=null;
   app.activeDocument=doc;doc.activeLayer=layer;select(doc,op);mask();doc.selection.deselect();
   // Match Photoshop's selection feather exactly in a grayscale mask asset.
   temp=app.documents.add(UnitValue(w,'px'),UnitValue(h,'px'),72,'Local mask',NewDocumentMode.GRAYSCALE,DocumentFill.WHITE,1,BitsPerChannelType.SIXTEEN);
   var black=new SolidColor();black.gray.gray=100;temp.selection.selectAll();temp.selection.fill(black);temp.selection.deselect();
   select(temp,op);var white=new SolidColor();white.gray.gray=0;temp.selection.fill(white);temp.selection.deselect();
   save(temp,name+'-mask.tif');temp.close(SaveOptions.DONOTSAVECHANGES);temp=null;
   app.activeDocument=doc;doc.flatten();
  }
  save(doc,'composite.tif');return 'OK: '+ops.length+' conventional local operations';
 }finally{
  try{if(temp)temp.close(SaveOptions.DONOTSAVECHANGES);}catch(_){}
  try{if(doc)doc.close(SaveOptions.DONOTSAVECHANGES);}catch(_){}
  try{if(source && opened)source.close(SaveOptions.DONOTSAVECHANGES);}catch(_){}
  try{if(previous)app.activeDocument=previous;}catch(_){}
  app.preferences.rulerUnits=oldUnits;app.displayDialogs=oldDialogs;
 }
})();
'''


def apply(source, folder, operations):
    from .pipeline import job_lock
    (ROOT / '.cache').mkdir(exist_ok=True)
    with job_lock(ROOT / '.cache/photoshop.lock'):
        return _apply(source, folder, operations)


def _apply(source, folder, operations):
    import tifffile
    from .photoshop import PhotoshopSession
    operations = validate_operations(operations)
    source, folder = workspace_path(source), workspace_path(folder)
    if not source.is_file(): raise ValueError('Missing controller-rendered TIFF')
    before = tifffile.imread(source)
    if before.dtype.name != 'uint16' or before.ndim != 3 or before.shape[2] != 3:
        raise ValueError('Expected RGB uint16 input')
    digest = sha256(source)
    check_cancel()
    folder.mkdir()  # Never repeat or overwrite a partially completed native operation.
    script = JSX.replace('__OPERATIONS__', json.dumps(operations)).replace('__SOURCE__', json.dumps(str(source)))
    path = folder/'local-edits.jsx'; path.write_text(script, encoding='utf-8')
    json_write(folder/'operations.json', operations)
    session = PhotoshopSession()
    result = session.app.DoJavaScriptFile(str(path))
    if session.verify() != session.before:
        raise RuntimeError('Photoshop local edit left a temporary document open')
    after = tifffile.imread(folder/'composite.tif')
    if after.shape != before.shape or after.dtype != before.dtype or sha256(source) != digest:
        raise RuntimeError('Local edit dimensions, precision or source preservation failed')
    layers = []
    for index, op in enumerate(operations, 1):
        name = f'local-{index:02}'
        pixels, mask = tifffile.imread(folder/(name+'.tif')), tifffile.imread(folder/(name+'-mask.tif'))
        if pixels.shape != before.shape or pixels.dtype != before.dtype or mask.shape != before.shape[:2] or mask.dtype != before.dtype:
            raise RuntimeError('Local layer or mask format mismatch')
        layers.append({'file': name+'.tif', 'mask': name+'-mask.tif', 'opacity': 100,
                       'name': f'{index}: Photoshop '+('local tonal curve' if op['kind']=='curve' else 'clone from donor pixels')})
    report = {'status': 'passed', 'source_preserved': True, 'generative_tools': False,
              'layers': layers, 'operations': operations, 'script_result': result}
    json_write(folder/'verification.json', report)
    check_cancel()
    return report


if __name__ == '__main__':
    import sys
    from .runtime import local_runtime
    local_runtime()
    apply(Path(sys.argv[1]), Path(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text(encoding='utf-8')))
