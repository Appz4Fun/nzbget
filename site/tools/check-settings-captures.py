#!/usr/bin/env python3
"""Verify Settings capture coverage, image integrity, source hashes, and guide links."""
import hashlib,json,re,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
ASSETS=ROOT/'site/assets/settings'
EXPECTED={'info','status','system','web-interface','paths','servers','security','categories','rss-feeds','incoming-nzbs','download-queue','connection','logging','scheduler','check-repair','unpack','extension-scripts','extension-manager','dupe-donors','extended-unpacker','extended-unrar','permission-fix','licenses'}
def jpeg_size(data):
 assert data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'),'Incomplete JPEG'
 pos=2
 while pos<len(data):
  assert data[pos]==255,'Invalid JPEG marker';pos+=1
  while data[pos]==255:pos+=1
  marker=data[pos];pos+=1
  size=struct.unpack('>H',data[pos:pos+2])[0]
  if marker in [192,193,194,195,197,198,199,201,202,203,205,206,207]:
   height,width=struct.unpack('>HH',data[pos+3:pos+7]);return width,height
  pos+=size
 raise AssertionError('JPEG dimensions missing')
def main():
 manifest=json.loads((ASSETS/'captures.json').read_text())
 captures=manifest['captures']
 assert {c['file'] for c in captures if c['kind']=='section'}==EXPECTED,'Missing Settings section capture'
 sources='\n'.join(p.read_text() for p in (ROOT/'site/content').glob('settings*.md'))
 assert len({c['file'] for c in captures})==len(captures),'Repeated capture name'
 for capture in captures:
  name=capture['file'];data=(ASSETS/(name+'.jpg')).read_bytes()
  assert jpeg_size(data)==(capture['width'],capture['height']),name+': dimensions differ'
  assert hashlib.sha256(data).hexdigest()==capture['sha256'],name+': image changed'
  assert not capture['unsafe'] and capture['textSafe'] and not capture['overflow'],name+': capture validation failed'
  assert 'assets/settings/'+name+'.jpg' in sources,name+': picture has no guide link'
 for name,digest in (manifest['ui_source_sha256'].items() if '--check-source' in sys.argv else []):
  assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name+': UI changed after capture; retake affected pictures'
 assert not re.search(r'/(?:Users|home|tmp|private|usr|var|opt|root|mnt|media)/',sources),'Machine-specific folder example in guide'
 print(f"Settings captures: {len(EXPECTED)} sections, {len(captures)} pictures, source hashes and guide links PASS")
if __name__=='__main__':
 try:main()
 except (AssertionError,KeyError,ValueError) as error:raise SystemExit(str(error))
