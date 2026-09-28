import argparse
import json
from pathlib import Path
import sys
import time
import uuid

from .runtime import ROOT, disable_network, local_runtime, json_write, check_cancel

def record_error(error, output, source):
    if getattr(error, 'workflow_logged', False):
        return
    folder = output / 'errors'
    folder.mkdir(parents=True, exist_ok=True)
    json_write(folder / (uuid.uuid4().hex + '.json'), {'source_name': Path(source).name,
        'error_type': type(error).__name__, 'error': str(error), 'unix_time': time.time()})

def main():
    local_runtime()
    parser = argparse.ArgumentParser(description='Local CUDA photo restoration; originals are never overwritten')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('single', 'batch', 'watch'):
        command = sub.add_parser(name)
        command.add_argument('input', type=Path)
        command.add_argument('--output', type=Path, default=ROOT / 'outputs')
        command.add_argument('--scale', type=int, choices=[1, 2, 4], default=1)
        command.add_argument('--blend', type=float, default=.35)
        command.add_argument('--allow-8bit', action='store_true')
        command.add_argument('--bit-depth', type=int, choices=[8, 16], default=16)
        command.add_argument('--config', type=Path)
        command.add_argument('--subject', help='Explicit subject mapping for human reference review only')
    adobe = sub.add_parser('photoshop')
    adobe.add_argument('job_folder', type=Path)
    edit = sub.add_parser('edit', help='16-bit grading, DRUNet and explicit masked clone; no face restoration')
    edit.add_argument('input', type=Path)
    edit.add_argument('--recipe', type=Path, required=True)
    edit.add_argument('--output', type=Path, default=ROOT / 'outputs')
    upscale = sub.add_parser('upscale', help='Conservative 16-bit upscale; face reconstruction disabled')
    upscale.add_argument('input', type=Path)
    upscale.add_argument('--scale', type=int, choices=[2, 4], default=2)
    upscale.add_argument('--detail-strength', type=float, default=.2)
    upscale.add_argument('--model', choices=['mambairv2', 'realesrgan'], default='mambairv2')
    upscale.add_argument('--output', type=Path, default=ROOT / 'outputs')
    agent = sub.add_parser('agent', help='Local text model with one bounded editing tool')
    agent.add_argument('input', type=Path)
    agent.add_argument('--request', required=True)
    agent.add_argument('--grade-mask', type=Path)
    agent.add_argument('--output', type=Path, default=ROOT / 'outputs')
    agent.add_argument('--export-psd', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'photoshop':
            from .photoshop import export
            print(json.dumps(export(args.job_folder), indent=2))
            return 0
        if args.command == 'agent':
            from .agent import run
            run(args.request, args.input, args.output, args.grade_mask, args.export_psd)
            return 0
        disable_network()
        from .imaging import EXTENSIONS
        from .pipeline import Pipeline
        from .references import subject_context, local_path
        if args.command == 'upscale':
            destination, skipped = Pipeline(args.output).process(args.input, scale=args.scale, blend=0,
                                                                upscale_strength=args.detail_strength, upscale_model=args.model)
            print(('EXISTING ' if skipped else 'DONE ') + str(destination), flush=True)
            return 0
        if args.command == 'edit':
            recipe = json.loads(local_path(args.recipe).read_text(encoding='utf-8-sig'))
            destination, skipped = Pipeline(args.output).process(args.input, recipe=recipe)
            print(('EXISTING ' if skipped else 'DONE ') + str(destination), flush=True)
            return 0
        if not 0 <= args.blend <= 1:
            parser.error('--blend must be in [0,1]')
        context = subject_context(args.config, args.subject)
        pipeline = Pipeline(args.output)
        args.input = local_path(args.input)
        if args.input.is_relative_to(pipeline.output) or pipeline.output.is_relative_to(args.input):
            raise ValueError('Input and output folders must not overlap')
        if args.command != 'single' and not args.input.is_dir():
            raise ValueError('Batch/watch input must be a folder')
        attempted = {}
        failures = 0
        if args.command == 'watch':
            print('WATCHING ' + str(args.input) + ' (Ctrl+C to stop)', flush=True)
        while True:
            check_cancel()
            paths = [args.input] if args.command == 'single' else sorted(
                p for p in args.input.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS)
            for path in paths:
                try:
                    stat = path.stat(); state = (stat.st_size, stat.st_mtime_ns)
                    if attempted.get(path) == state:
                        continue
                    attempted[path] = state
                    destination, skipped = pipeline.process(path, args.scale, args.blend, args.allow_8bit, context, bit_depth=args.bit_depth)
                    print(('EXISTING ' if skipped else 'DONE ') + str(destination), flush=True)
                    job = json.loads((destination / 'job.json').read_text(encoding='utf-8'))
                    print(json.dumps({'faces': job['faces'], 'conversions': job['conversions']}), flush=True)
                except Exception as error:
                    failures += 1
                    record_error(error, pipeline.output, path)
                    print(f'ERROR {path.name}: {type(error).__name__}: {error}', file=sys.stderr, flush=True)
                    if 'out of memory' in str(error).lower():
                        print('GPU memory exhausted: close other GPU workloads or reduce input dimensions.', file=sys.stderr)
            if args.command != 'watch':
                return 1 if failures else 0
            time.sleep(2)
    except KeyboardInterrupt:
        print('Cancelled; originals preserved. Incomplete job removed.', file=sys.stderr)
        return 130
    except Exception as error:
        record_error(error, ROOT / 'outputs', getattr(args, 'input', getattr(args, 'job_folder', 'command')))
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
