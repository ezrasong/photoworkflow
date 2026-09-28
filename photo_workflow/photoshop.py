import json
from pathlib import Path
import uuid

from .runtime import ROOT, check_cancel, json_write, sha256, workspace_path

# Leave room for channel compression overhead and Photoshop metadata below 2 GiB.
PSD_SAFE_BYTES = 1536 * 1024**2


def review_name(width, height, layer_count, bit_depth):
    estimated = width * height * (bit_depth // 8) * (6 + 4 * layer_count)
    return 'review.psb' if estimated > PSD_SAFE_BYTES else 'review.psd'


def review_path(folder):
    folder = Path(folder)
    for name in ('review.psd', 'review.psb'):
        if (folder / name).exists(): return folder / name
    manifest = json.loads((folder / 'job.json').read_text(encoding='utf-8'))
    return folder / review_name(*manifest['output_size'], len(manifest['layers']), manifest.get('bit_depth', 8))


JSX = r'''
#target photoshop
(function () {
  var root = File($.fileName).parent;
  var target = File(root + '/__REVIEW__');
  if (target.exists) throw Error('Layered review already exists; refusing overwrite.');
  var oldDialogs = app.displayDialogs;
  var previous = app.documents.length ? app.activeDocument : null;
  var owned = [], copies = [], succeeded = false;
  app.displayDialogs = DialogModes.NO;
  var doc;
  function asset(name) {
    var f = File(root + '/' + name), existing = false;
    for (var i=0; i<app.documents.length; i++) {
      try { if (app.documents[i].fullName.fsName.toLowerCase() == f.fsName.toLowerCase()) existing = true; } catch (_) {}
    }
    // Read the committed disk asset even when its tab contains unsaved changes.
    if (existing) {
      var copy = File(root + '/.export-__TOKEN__-' + copies.length + '.' + f.name.split('.').pop());
      if (copy.exists || !f.copy(copy)) throw Error('Cannot isolate open export asset');
      copies.push(copy); f = copy;
    }
    var opened = app.open(f); owned.push(opened);
    return {doc: opened, existing: false};
  }
  function importLayer(file, name, opacity, mask) {
    var a = asset(file);
    var layer = a.doc.activeLayer.duplicate(doc, ElementPlacement.PLACEATBEGINNING);
    if (!a.existing) a.doc.close(SaveOptions.DONOTSAVECHANGES);
    app.activeDocument = doc; doc.activeLayer = layer;
    layer.name = name; layer.opacity = opacity;
    if (mask) {
      var m = asset(mask);
      var alpha = m.doc.channels[0].duplicate(doc);
      if (!m.existing) m.doc.close(SaveOptions.DONOTSAVECHANGES);
      app.activeDocument = doc; doc.activeLayer = layer;
      var d = new ActionDescriptor();
      d.putClass(charIDToTypeID('Nw  '), charIDToTypeID('Chnl'));
      var r = new ActionReference();
      r.putEnumerated(charIDToTypeID('Chnl'), charIDToTypeID('Chnl'), charIDToTypeID('Msk '));
      d.putReference(charIDToTypeID('At  '), r);
      d.putEnumerated(charIDToTypeID('Usng'), charIDToTypeID('UsrM'), charIDToTypeID('RvlA'));
      executeAction(charIDToTypeID('Mk  '), d, DialogModes.NO);
      var targetMask = new ActionDescriptor();
      targetMask.putReference(charIDToTypeID('null'), r);
      executeAction(charIDToTypeID('slct'), targetMask, DialogModes.NO);
      // Apply Image copies channel samples directly. Loading a selection first
      // quantizes masks to 256 levels even in a 16-bit Photoshop document.
      var source = new ActionReference();
      source.putName(charIDToTypeID('Chnl'), alpha.name);
      source.putIdentifier(charIDToTypeID('Dcmn'), doc.id);
      var calculation = new ActionDescriptor();
      calculation.putReference(charIDToTypeID('T   '), source);
      calculation.putEnumerated(charIDToTypeID('Clcl'), charIDToTypeID('Clcn'), charIDToTypeID('Nrml'));
      calculation.putUnitDouble(charIDToTypeID('Opct'), charIDToTypeID('#Prc'), 100);
      calculation.putBoolean(charIDToTypeID('PrsT'), false);
      var apply = new ActionDescriptor();
      apply.putObject(charIDToTypeID('With'), charIDToTypeID('Clcl'), calculation);
      executeAction(charIDToTypeID('AppI'), apply, DialogModes.NO);
      alpha.remove();
      var rgb = new ActionReference();
      rgb.putEnumerated(charIDToTypeID('Chnl'), charIDToTypeID('Chnl'), charIDToTypeID('RGB '));
      var ds = new ActionDescriptor(); ds.putReference(charIDToTypeID('null'), rgb);
      executeAction(charIDToTypeID('slct'), ds, DialogModes.NO);
      var check = new ActionReference();
      check.putEnumerated(charIDToTypeID('Lyr '), charIDToTypeID('Ordn'), charIDToTypeID('Trgt'));
      if (!executeActionGet(check).getBoolean(stringIDToTypeID('hasUserMask')))
        throw Error('Layer mask missing: ' + name);
    }
    return layer;
  }
  try {
    doc = app.documents.add(UnitValue(__WIDTH__, 'px'), UnitValue(__HEIGHT__, 'px'),
       72, 'Photo restoration review', NewDocumentMode.RGB, DocumentFill.TRANSPARENT,
       1, BitsPerChannelType.__DEPTH__, 'sRGB IEC61966-2.1');
    owned.push(doc);
    var empty = doc.activeLayer;
    var base = importLayer(__BASELINE__, 'Original - oriented sRGB baseline', 100, null);
    empty.remove(); base.allLocked = true;
    __LAYERS__
    if (doc.layers.length != __COUNT__) throw Error('Unexpected layer count');
    var pending = File(root + '/__PARTIAL__');
    if (pending.exists) throw Error('Partial layered review exists; inspect it before retrying.');
    if (__LARGE__) {
      var save = new ActionDescriptor(), format = new ActionDescriptor();
      format.putBoolean(stringIDToTypeID('maximizeCompatibility'), true);
      save.putObject(charIDToTypeID('As  '), stringIDToTypeID('largeDocumentFormat'), format);
      save.putPath(charIDToTypeID('In  '), pending);
      save.putBoolean(charIDToTypeID('Cpy '), true);
      save.putBoolean(charIDToTypeID('LwCs'), true);
      save.putBoolean(charIDToTypeID('EmbP'), true);
      executeAction(charIDToTypeID('save'), save, DialogModes.NO);
    } else {
      var options = new PhotoshopSaveOptions(); options.layers = true;
      options.embedColorProfile = true;
      doc.saveAs(pending, options, true, Extension.LOWERCASE);
    }
    if (target.exists || !pending.rename('__REVIEW__')) throw Error('Cannot publish layered review safely');
    succeeded = true;
    return 'OK: ' + doc.layers.length + ' layers; masks verified';
  } finally {
    for (var i=owned.length-1; i>=0; i--) {
      if (succeeded && !__CLOSE_CREATED__ && owned[i] == doc) continue;
      try { owned[i].close(SaveOptions.DONOTSAVECHANGES); } catch (_) {}
    }
    for (var i=0; i<copies.length; i++) { try { copies[i].remove(); } catch (_) {} }
    if (previous && (!succeeded || __CLOSE_CREATED__)) { try { app.activeDocument = previous; } catch (_) {} }
    app.displayDialogs = oldDialogs;
  }
})();
'''

def import_script(width, height, layers, bit_depth=8, baseline_file='original.png', close_created=False):
    statements = []
    for layer in layers:
        args = [layer['file'], layer['name'], layer['opacity'], layer.get('mask')]
        statements.append('importLayer(' + ','.join(json.dumps(x) for x in args) + ');')
    script = JSX.replace('__WIDTH__', str(width)).replace('__HEIGHT__', str(height))
    script = script.replace('__DEPTH__', 'SIXTEEN' if bit_depth == 16 else 'EIGHT')
    script = script.replace('__BASELINE__', json.dumps(baseline_file))
    script = script.replace('__LAYERS__', '\n    '.join(statements)).replace('__COUNT__', str(len(layers) + 1))
    script = script.replace('__CLOSE_CREATED__', 'true' if close_created else 'false')
    name = review_name(width, height, len(layers), bit_depth)
    script = script.replace('__REVIEW__', name).replace('__PARTIAL__', name.replace('.', '.partial.'))
    script = script.replace('__LARGE__', 'true' if name.endswith('.psb') else 'false')
    return script.replace('__TOKEN__', uuid.uuid4().hex)


def write_import(folder, width, height, layers, bit_depth=8, baseline_file='original.png'):
    script = import_script(width, height, layers, bit_depth, baseline_file)
    (folder / 'import-photoshop.jsx').write_text(script, encoding='utf-8')

def export(folder, close_created=False, session=None):
    from .pipeline import job_lock
    (ROOT / '.cache').mkdir(exist_ok=True)
    with job_lock(ROOT / '.cache/photoshop.lock'):
        return _export(folder, close_created, session)


class PhotoshopSession:
    """Keep one COM connection; a crash must fail the batch, never restart it."""
    def __init__(self, defer_start=False):
        import win32com.client
        if defer_start:
            import pywintypes
            try:
                self.app = win32com.client.GetActiveObject('Photoshop.Application')
            except pywintypes.com_error as error:
                if error.hresult != -2147221021: raise  # MK_E_UNAVAILABLE: no running instance.
                self.app = None
                self.before = {}
                return
        else:
            self.app = win32com.client.Dispatch('Photoshop.Application')
        self.before = self.document_state()

    def document_state(self):
        # No names, paths or pixels leave Photoshop in this state check.
        text = self.app.DoJavaScript('''(function(){var a=[];
          for(var i=0;i<app.documents.length;i++){var d=app.documents[i];
            a.push([d.id,d.saved,d.layers.length,d.historyStates.length,
                    d.width.as('px'),d.height.as('px')].join(':'));}
          return a.join('|');})();''')
        return {int(row.split(':')[0]): row for row in str(text).split('|') if row}

    def verify(self):
        if self.app is None:
            # Start only when Adobe work is needed, after offline GPU processing.
            # Once connected, retain this instance: never reconnect after a crash.
            import win32com.client
            self.app = win32com.client.Dispatch('Photoshop.Application')
            self.before = self.document_state()
        after = self.document_state()
        if any(after.get(key) != value for key, value in self.before.items()):
            raise RuntimeError('Existing Photoshop document state changed; batch stopped')
        return after


def _export(folder, close_created, session):
    """Separate explicit Adobe action; never invoked by the offline processing engine."""
    import msvcrt
    from psd_tools import PSDImage
    folder = workspace_path(folder)
    # Same nonblocking Windows lock pattern as processing; released on process death.
    with (folder / '.adobe.lock').open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        if any((folder / name).exists() for name in ('review.psd', 'review.psb')):
            raise FileExistsError('Layered review already exists; refusing overwrite')
        if any((folder / name).exists() for name in ('review.partial.psd', 'review.partial.psb')):
            raise FileExistsError('Partial PSD exists; inspect the previous failure before exporting')
        manifest = json.loads((folder / 'job.json').read_text(encoding='utf-8'))
        assets = {manifest.get('baseline_file', 'original.tif' if manifest.get('bit_depth') == 16 else 'original.png')}
        for layer in manifest['layers']:
            assets.add(layer['file'])
            if layer.get('mask'): assets.add(layer['mask'])
        digests = {}
        for name in assets:
            path = (folder / name).resolve()
            if not path.is_relative_to(folder): raise ValueError('Export asset is outside the job')
            digests[name] = sha256(path)
            expected = manifest.get('artifacts', {}).get(name)
            if expected and digests[name] != expected:
                raise RuntimeError('Export asset changed: ' + name)
        check_cancel()
        session = session or PhotoshopSession()
        before = session.verify()
        app = session.app
        script = import_script(*manifest['output_size'], manifest['layers'], manifest.get('bit_depth', 8),
                               manifest.get('baseline_file', 'original.tif' if manifest.get('bit_depth') == 16 else 'original.png'), close_created)
        # Regenerate from the manifest so historical jobs receive lifecycle fixes too.
        batch_script = folder / 'import-photoshop-batch.jsx'
        batch_script.write_text(script, encoding='utf-8')
        try:
            result = app.DoJavaScriptFile(str(batch_script))
            after = session.verify()
            if any(after.get(key) != value for key, value in before.items()):
                raise RuntimeError('Existing Photoshop document changed during export')
            if close_created and after != before:
                raise RuntimeError('Photoshop export left a temporary document open')
            if any(sha256(folder / name) != digest for name, digest in digests.items()):
                raise RuntimeError('Export assets changed during Adobe execution')
        except BaseException as error:
            json_write(folder / ('photoshop-failure-' + uuid.uuid4().hex + '.json'),
                       {'status': 'failed', 'error': str(error), 'automatic_retry': False})
            raise
        saved = review_path(folder)
        psd = PSDImage.open(saved)
        expected = ['Original - oriented sRGB baseline'] + [x['name'] for x in manifest['layers']]
        if [x.name for x in psd] != expected:
            raise RuntimeError('Saved PSD layer names/order do not match manifest')
        masks = [x.name for x in psd if x.has_mask()]
        if masks != [x['name'] for x in manifest['layers']]:
            raise RuntimeError('Saved PSD masks do not match manifest')
        if psd.size != tuple(manifest['output_size']):
            raise RuntimeError('PSD dimensions do not match')
        if psd.depth != manifest.get('bit_depth', 8):
            raise RuntimeError('PSD bit depth does not match')
        report = {'status': 'verified', 'photoshop_version': app.Version,
                  'layers': expected, 'masks': masks, 'dimensions': psd.size, 'bit_depth': psd.depth, 'script_result': result,
                  'existing_document_count': len(before), 'existing_document_state_preserved': True,
                  'assets_preserved': True, 'close_created': close_created, 'file': saved.name,
                  'format': saved.suffix[1:].upper()}
        json_write(folder / 'photoshop-verification.json', report)
        return report
