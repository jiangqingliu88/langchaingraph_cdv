"""CLI with validated staged output and rollback on publication failure."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile

from .core import (MAX_CASE_BYTES, MAX_OBJECT_BYTES, VERSION, TensorGenError,
                   digest, fail, materialize, prepare_case)
from .formats import byte_hex, memh


def _reject_constant(value):
    fail('INVALID_VALUE', 'JSON', f'nonfinite token {value} is not permitted')


def _unique_pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result: fail('INVALID_PARAMETER','JSON',f'duplicate key {key}')
        result[key]=value
    return result


def _publish(stage,out,names,overwrite):
    out.mkdir(parents=True,exist_ok=True)
    if out.is_symlink(): fail('INVALID_PARAMETER','out-dir','symlink directory not allowed')
    # Serialize cooperating writers and invalidate the previous commit marker
    # before replacing any payload. Consumers must only read committed manifests.
    lock=out/'.scripts.lock'
    try:
        descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        fail('OUTPUT_BUSY',str(out),'another publication or stale .scripts.lock exists')
    os.close(descriptor)
    backup=stage/'backup'
    published=[]; saved=[]
    try:
        backup.mkdir()
        marker=out/'manifest.json'
        if marker.is_symlink() or (marker.exists() and not marker.is_file()):
            fail('INVALID_PARAMETER',str(marker),'manifest must be regular file')
        if marker.exists():
            if not overwrite: fail('OUTPUT_EXISTS',str(marker),'use --overwrite explicitly')
            os.replace(marker,backup/'manifest.json'); saved.append('manifest.json')
        for name in names:
            target=out/name
            if target.is_symlink() or (target.exists() and not target.is_file()):
                fail('INVALID_PARAMETER',str(target),'target must be regular file')
            if target.exists():
                if not overwrite: fail('OUTPUT_EXISTS',str(target),'use --overwrite explicitly')
                os.replace(target,backup/name); saved.append(name)
            # Same-filesystem hard link publishes a complete file exclusively.
            # It cannot expose a partial copy or replace a competing target.
            os.link(stage/name,target)
            published.append(name)
    except BaseException:
        for name in reversed(published): (out/name).unlink(missing_ok=True)
        for name in reversed(saved): os.replace(backup/name,out/name)
        raise
    finally:
        lock.unlink()


def main():
    parser=argparse.ArgumentParser(prog='tensor_gen',
        description='Generate deterministic NPU tensor payloads from a JSON case spec.',
        epilog='Start with: python -m isa_ir_tools.cli generate --help')
    parser.add_argument('--version',action='version',version='tensor_gen '+VERSION)
    sub=parser.add_subparsers(dest='command',required=True)
    gen=sub.add_parser('generate',help='generate all tensors in one JSON case',
        description='Read tensor spec v1 JSON; write bin, optional text payloads and manifest.json.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog='Example: python -m isa_ir_tools.cli generate --spec tensor_spec.json '
               '--out-dir artifacts/patterns --formats bin,hex,memh '
               'Tensor dtype/shape/seed/pattern/layout are JSON fields, not CLI flags. '
               'For FP8 set dtype=fp8 and fp8_format=e5m2/e4m3; '
               'For FP4 set dtype=fp4 and fp4_format=e2m1/e1m2 in the JSON spec.')
    gen.add_argument('--spec',required=True,help='input UTF-8 JSON case path; requires a tensors array')
    gen.add_argument('--out-dir',required=True,help='output directory; paths are relative to the current directory')
    gen.add_argument('--formats',default='bin,hex',help='unique comma-separated bin/hex/memh; no spaces; bin always generated')
    gen.add_argument('--overwrite',action='store_true',help='explicitly replace matching outputs; unrelated old files are retained')
    gen.add_argument('--max-object-bytes',type=int,default=MAX_OBJECT_BYTES,help='positive per-tensor padded binary payload budget in bytes; working-memory checks still apply')
    gen.add_argument('--max-case-bytes',type=int,default=MAX_CASE_BYTES,help='positive total padded binary payload budget in bytes; excludes text expansion and stride gaps')
    args=parser.parse_args()
    try:
        formats=args.formats.split(',')
        if not formats or len(set(formats))!=len(formats) or any(f not in ('bin','hex','memh') for f in formats):
            fail('INVALID_PARAMETER','--formats','unique comma-separated bin/hex/memh required')
        formats=['bin']+[f for f in formats if f!='bin']
        case=json.loads(Path(args.spec).read_text(encoding='utf-8'),parse_constant=_reject_constant,object_pairs_hook=_unique_pairs)
        prepared=prepare_case(case,args.max_object_bytes,args.max_case_bytes)
        out=Path(args.out_dir).absolute()
        if out.is_symlink() or (out.exists() and not out.is_dir()):
            fail('INVALID_PARAMETER','out-dir','regular directory required')
        names=[f"{t['name']}.{fmt}" for t in prepared for fmt in formats]+['manifest.json']
        source=Path(args.spec).resolve()
        for name in names:
            target=out/name
            if target.resolve()==source: fail('INVALID_PARAMETER',str(target),'cannot replace input spec')
            if target.is_symlink(): fail('INVALID_PARAMETER',str(target),'symlink target not allowed')
            if target.exists() and not args.overwrite: fail('OUTPUT_EXISTS',str(target),'use --overwrite explicitly')
        # Stage on the same filesystem; no completed manifest until all objects succeed.
        out.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.tensor_gen.',dir=out.parent) as temporary:
            stage=Path(temporary); items=[]
            for t in prepared:
                tensor=materialize(t); data=tensor.pop('payload'); tensor.pop('values')
                payloads=[]
                for fmt in formats:
                    filename=f"{t['name']}.{fmt}"
                    path=stage/filename
                    if fmt=='bin': path.write_bytes(data)
                    else: path.write_text(byte_hex(data) if fmt=='hex' else memh(data),encoding='utf-8',newline='\n')
                    payloads.append({'role':'tensor_data','file':filename,'format':fmt,
                                     'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
                tensor['payloads']=payloads
                tensor['payload']={'file':f"{t['name']}.bin",'bytes':len(data)} # legacy compatibility
                items.append(tensor)
                del data
            manifest={'schema':'tensor_manifest_v2','tool':{'version':VERSION,'python':platform.python_version(),'stream_version':2},
                      'source_revision':{'isa_directory':'v0.2','pdf_revision':'v1.2','spec_digest':digest(case)},'tensors':items}
            (stage/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
            _publish(stage,out,names,args.overwrite)
        return 0
    except TensorGenError as exc:
        parser.exit(2,f'{exc}\n')
    except (json.JSONDecodeError,UnicodeError,ValueError) as exc:
        parser.exit(2,f'INVALID_SPEC: {exc}\n')
    except OSError as exc:
        parser.exit(1,f'IO_ERROR: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())

