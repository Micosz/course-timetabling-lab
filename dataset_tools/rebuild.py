"""Rebuild the pinned adapted JSON in a new output folder; no original files overwritten."""
import argparse
import hashlib
import io
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from build_dataset import convert
from validate_dataset import validate

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-xml',type=Path,help='Use an existing pinned XML instead of downloading')
    parser.add_argument('--output',type=Path,required=True,help='A new directory that does not exist')
    args=parser.parse_args()
    if args.output.exists():parser.error('Choose a new output directory; existing data will not be overwritten')
    config=json.loads((HERE/'config.json').read_text())
    if args.source_xml:
        raw=args.source_xml.read_bytes()
    else:
        with urllib.request.urlopen(config['source_url'],timeout=60) as response:
            zipped=response.read(10*1024*1024+1)
        if len(zipped)>10*1024*1024:raise ValueError('Source archive is unexpectedly large')
        with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
            names=[name for name in archive.namelist() if Path(name).name=='pu-fal07-cs.xml']
            if len(names)!=1:raise ValueError('Unexpected XML members in source archive')
            raw=archive.read(names[0])
    if hashlib.sha256(raw).hexdigest()!=config['expected_source_sha256']:
        raise ValueError('Source XML SHA-256 differs from pinned input')
    with tempfile.TemporaryDirectory() as folder:
        source=Path(folder)/'pu-fal07-cs.xml';source.write_bytes(raw)
        data,assumptions,audit=convert(config,source)
    text=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
    expected=json.loads((HERE.parent/'data/provenance.json').read_text())['dataset_sha256']
    actual=hashlib.sha256(text.encode()).hexdigest()
    if actual!=expected:raise ValueError('Rebuilt dataset hash differs; inspect Python version/config before use')
    report=validate(data)
    if report['errors']:raise ValueError(report['errors'])
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'dataset.json').write_text(text,encoding='utf-8')
    for name,value in [('assumptions.json',assumptions),('conversion_audit.json',audit),('validation_report.json',report)]:
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Rebuilt exact dataset SHA-256:',actual)
    print('Saved',args.output)


if __name__=='__main__':main()
