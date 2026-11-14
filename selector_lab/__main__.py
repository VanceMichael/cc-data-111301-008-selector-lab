DESCRIPTION = '页面样本引导的字段定位规则生成与歧义检出'
SAMPLE = 'fixtures/annotations.json'

import argparse
import json
from pathlib import Path
import tempfile

from .archive import archive_file
from .core import inspect_file, load_pages
from .execute import run_page
from .generate import generate
from .labio import load_tree
from .store import (
    activate_pack,
    lab_status,
    load_draft,
    load_pack,
    publish_pack,
)
from .verify import verify_pages


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _selection(arg):
    """解析 模板/字段=候选id 形式的显式选择。"""
    if '=' not in arg:
        raise argparse.ArgumentTypeError('选择项格式应为 模板/字段=候选id')
    key, candidate_id = arg.split('=', 1)
    if '/' not in key:
        raise argparse.ArgumentTypeError('选择项的字段部分应为 模板/字段')
    return key, candidate_id


def build_parser():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('inspect').add_argument('path', nargs='?', default=SAMPLE)
    capture = sub.add_parser('capture', help='内容寻址归档原始资料')
    capture.add_argument('path', nargs='?', default=SAMPLE)
    capture.add_argument('--archive', default='.work/raw')

    gen = sub.add_parser('generate', help='从人工圈选生成候选草稿（不改动已发布规则）')
    gen.add_argument('path', nargs='?', default=SAMPLE)
    gen.add_argument('--lab', default='.work/lab')

    ver = sub.add_parser('verify', help='对页面复算全部候选并展示覆盖与实际 DOM 位置')
    ver.add_argument('path', nargs='?', default=SAMPLE)
    ver.add_argument('--draft', required=True)
    ver.add_argument('--lab', default='.work/lab')

    pub = sub.add_parser('publish', help='把草稿中的显式选择发布为不可变规则包')
    pub.add_argument('--draft', required=True)
    pub.add_argument('--lab', default='.work/lab')
    pub.add_argument('--select', action='append', default=[], type=_selection)

    act = sub.add_parser('activate', help='把规则包固定为运行版本')
    act.add_argument('pack_id')
    act.add_argument('--lab', default='.work/lab')

    run = sub.add_parser('run', help='按激活的规则包执行页面定位')
    run.add_argument('html')
    run.add_argument('--lab', default='.work/lab')
    run.add_argument('--pack', default=None)

    sub.add_parser('status').add_argument('--lab', default='.work/lab')
    sub.add_parser('demo')
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _dispatch(args)
    except (ValueError, FileNotFoundError) as error:
        # 输入或规则状态问题：给出可读原因并以非零码退出，不产出空成功结果
        print(f'失败: {error}', file=__import__('sys').stderr)
        raise SystemExit(1)


def _dispatch(args):
    if args.command == 'inspect':
        _print(inspect_file(Path(args.path)))
    elif args.command == 'capture':
        _print(archive_file(Path(args.path), Path(args.archive)))
    elif args.command == 'generate':
        pages = load_pages(args.path)
        _print(generate(pages, Path(args.path).name, Path(args.lab)))
    elif args.command == 'verify':
        pages = load_pages(args.path)
        draft = load_draft(Path(args.lab), args.draft)
        _print(verify_pages(pages, draft))
    elif args.command == 'publish':
        draft = load_draft(Path(args.lab), args.draft)
        selections = dict(args.select)
        _print(publish_pack(Path(args.lab), draft, selections))
    elif args.command == 'activate':
        _print({'active': activate_pack(Path(args.lab), args.pack_id)})
    elif args.command == 'run':
        pack = load_pack(Path(args.lab), args.pack)
        tree = load_tree(args.html)
        _print(run_page(tree, pack, Path(args.html).name))
    elif args.command == 'status':
        _print(lab_status(Path(args.lab)))
    elif args.command == 'demo':
        with tempfile.TemporaryDirectory() as directory:
            lab = Path(directory) / 'lab'
            pages = load_pages(SAMPLE)
            draft_info = generate(pages, Path(SAMPLE).name, lab)
            verification = verify_pages(pages, load_draft(lab, draft_info['id']))
            draft = load_draft(lab, draft_info['id'])
            selections = {}
            for template, body in draft['templates'].items():
                for field, report in body['fields'].items():
                    if report['status'] == 'consistent':
                        selections[f'{template}/{field}'] = report['candidates'][0]['id']
            pack_info = publish_pack(lab, draft, selections)
            activate_pack(lab, pack_info['id'])
            tree = load_tree(Path(SAMPLE).parent / 'changed.html')
            execution = run_page(tree, load_pack(lab), 'changed.html')
            _print({
                '原始资料': archive_file(Path(SAMPLE), Path(directory) / 'raw'),
                '资料预览': inspect_file(Path(SAMPLE)),
                '草稿': draft_info,
                '未标注页验证': verification,
                '发布': pack_info,
                '执行': execution,
            })


if __name__ == '__main__':
    main()
