"""Local Adobe lifecycle checks with real unsaved fixture documents, no image upload."""
import json
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import numpy as np
import win32com.client

from photo_workflow.imaging import save_mask, save_rgb
from photo_workflow.photoshop import PhotoshopSession, export, write_import
from photo_workflow.pipeline import job_lock
from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256
from tests.verify_expanded import check_psd


def fixture(folder, broken=False):
    folder.mkdir()
    rgb = (np.arange(128*96*3, dtype=np.uint32).reshape(96,128,3)*19 % 65536).astype(np.uint16)
    mask = np.arange(128*96, dtype=np.uint16).reshape(96,128)*5
    save_rgb(folder/'original.tif', rgb)
    save_rgb(folder/'edit.tif', 65535-rgb)
    save_mask(folder/'mask.tif', mask)
    if broken: (folder/'edit.tif').write_bytes(b'Invalid TIFF fixture')
    layers = [dict(file='edit.tif', mask='mask.tif', name='Precision correction', opacity=100)]
    write_import(folder,128,96,layers,16,'original.tif')
    json_write(folder/'job.json',dict(output_size=[128,96],bit_depth=16,baseline_file='original.tif',layers=layers))


def verify():
    local_runtime()
    root=ROOT/'outputs'/('photoshop-reliability-'+uuid.uuid4().hex[:8]); root.mkdir()
    report=dict(status='running',folder=str(root),checks=[],pixels_remained_local=True)
    record=root/'verification.json'; json_write(record,report)
    created=[]; app=None
    started=time.monotonic()
    try:
        # This also exercises the normal COM launch when Photoshop is not running.
        session=PhotoshopSession(); app=session.app; user_state=session.before
        for name in ('open-asset','second','large-format','broken'):fixture(root/name,name=='broken')
        source=root/'open-asset/original.tif'; digest=sha256(source)
        doc_id=int(app.DoJavaScript("(function(){var d=app.open(File("+json.dumps(str(source))+"));d.activeLayer.invert();return d.id;})();"))
        created.append(doc_id)
        # This unsaved document has different pixels from the required disk asset.
        baseline=app.DoJavaScript('(function(){var d=app.activeDocument;return d.id+":"+d.saved+":"+d.historyStates.length;})();')
        assert ':false:' in baseline
        session=PhotoshopSession()
        for name in ('open-asset','second'):
            export(root/name,close_created=True,session=session)
            check_psd(root/name)
            assert session.verify()==session.before
        assert app.DoJavaScript('(function(){var d=app.activeDocument;return d.id+":"+d.saved+":"+d.historyStates.length;})();')==baseline
        assert sha256(source)==digest
        report['checks'].append('Two real 16-bit PSD exports preserve an unsaved open fixture, focus and history; open asset uses disk pixels')
        from photo_workflow.photoshop_local import apply
        import tifffile
        apply(source,root/'local-edit',[dict(kind='curve',region=[.25,.25,.75,.75],feather=0,
                                           curve=[0,0,128,150,255,255])])
        original=tifffile.imread(source).astype(np.int32)
        corrected=tifffile.imread(root/'local-edit/composite.tif').astype(np.int32)
        outside=tifffile.imread(root/'local-edit/local-01-mask.tif')==0
        assert np.abs(original[outside]-corrected[outside]).max()<=2
        assert session.verify()==session.before and sha256(source)==digest
        report['checks'].append('Real conventional Photoshop curve reads disk source while its tab is unsaved and preserves that tab')
        with patch('photo_workflow.photoshop.PSD_SAFE_BYTES', 1):
            exported=export(root/'large-format',close_created=True,session=session)
            assert exported['format']=='PSB'
            check_psd(root/'large-format')
            with (root/'large-format/review.psb').open('rb') as stream:
                assert stream.read(6)==b'8BPS\x00\x02'
        assert session.verify()==session.before
        report['checks'].append('Real Photoshop PSB save preserves 16-bit layers and precise masks; format threshold forced on small fixture')
        try:export(root/'broken',close_created=True,session=session)
        except Exception:pass
        else:raise AssertionError('Malformed asset was accepted')
        assert session.verify()==session.before
        assert not (root/'broken/review.psd').exists()
        report['checks'].append('Actual Adobe open failure cleans only owned documents and records failure')
        with job_lock(ROOT/'.cache/photoshop.lock'):
            try:export(root/'broken',close_created=True,session=session)
            except RuntimeError:pass
            else:raise AssertionError('Concurrent Adobe operation was accepted')
        report['checks'].append('Shared Adobe mutation lock rejects concurrent export')
        # A stale session must never call Dispatch and launch a replacement instance.
        with patch.object(session,'verify',side_effect=RuntimeError('simulated disconnected COM')), patch.object(win32com.client,'Dispatch') as dispatch:
            try:export(root/'broken',close_created=True,session=session)
            except RuntimeError:pass
            else:raise AssertionError('Disconnected session accepted')
            dispatch.assert_not_called()
        report['checks'].append('Simulated COM disconnect fails without restarting Photoshop or retrying mutation')
        report.update(status='passed',seconds=time.monotonic()-started,
                      preexisting_user_document_count=len(user_state),unsaved_fixture_document_count=len(created),
                      previous_appcrash_root_cause='unresolved; this tests prevention of silent restart and lifecycle defects')
    except BaseException as error:
        report.update(status='failed',error=repr(error)); raise
    finally:
        if app is not None and created:
            try:
                app.DoJavaScript('(function(){var ids='+json.dumps(created)+';for(var i=app.documents.length-1;i>=0;i--){for(var j=0;j<ids.length;j++){if(app.documents[i].id==ids[j]){app.documents[i].close(SaveOptions.DONOTSAVECHANGES);break;}}}})();')
            except Exception as error:report['fixture_cleanup_error']=repr(error)
        json_write(record,report);json_write(ROOT/'outputs/latest-photoshop-reliability-verification.json',report)
    print('Passed real Photoshop unsaved-document, failure cleanup, disk-asset and shared-lock checks.',flush=True)


if __name__=='__main__':verify()
