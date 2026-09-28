"""Known synthetic visuals, real local multimodal inference; no cloud pixel viewer."""
import json
from PIL import Image,ImageDraw

from photo_workflow.runtime import ROOT,json_write,sha256,local_runtime


def fixtures():
    folder=ROOT/'tests/fixtures/vision';folder.mkdir(exist_ok=True)
    source=folder/'shape-source.png';reference=folder/'shape-reference.png'
    for path,color in [(source,'red'),(reference,'green')]:
        im=Image.new('RGB',(640,400),'white');draw=ImageDraw.Draw(im)
        draw.ellipse((60,100,240,280),fill=color);draw.rectangle((400,100,580,280),fill='blue');im.save(path)
    return source,reference


def verify():
    local_runtime();source,reference=fixtures();before={str(p):sha256(p) for p in [source,reference]}
    from photo_workflow.vision import inspect
    result=inspect([('SOURCE',source),('SEPARATE REFERENCE',reference)],
                   'Describe the shapes, their left/right positions and their colors in EACH image. What visibly differs? Do not edit anything.')
    text=result['observations'].lower()
    assert all(word in text for word in ['red','green','blue','circle','square','left','right']),text
    assert before=={str(p):sha256(p) for p in [source,reference]}
    result.update(status='passed',test='Known synthetic shapes/colors/positions and two-image difference',sources_preserved=True)
    json_write(ROOT/'outputs/latest-vision-verification.json',result)
    print('Passed actual local two-image visual comparison; source hashes preserved.')


if __name__=='__main__':verify()
