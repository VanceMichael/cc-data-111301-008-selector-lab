"""规则产物的内容寻址存储与发布边界。

草稿（draft）与已发布规则包（pack）分开存放；发布后的文件不可变，
新标签只能产生新草稿，不能悄悄改动线上规则。运行期通过 active 指针
固定到某一版 pack，重复执行得到同一版定位结果。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

DRAFT_SCHEMA = 'selector-lab/draft/v1'
PACK_SCHEMA = 'selector-lab/pack/v1'
ACTIVE_NAME = 'active.json'


def canonical_id(obj):
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    import hashlib
    return hashlib.sha256(payload).hexdigest()


def _atomic_write_json(target, obj):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=target.parent,
                                     delete=False, encoding='utf-8') as writer:
        temporary = writer.name
        json.dump(obj, writer, ensure_ascii=False, indent=2)
        writer.write('\n')
        writer.flush()
        os.fsync(writer.fileno())
    os.replace(temporary, target)


def save_draft(lab_home, draft):
    if draft.get('schema') != DRAFT_SCHEMA:
        raise ValueError('草稿结构版本不正确')
    target = Path(lab_home) / 'drafts' / f"{draft['id']}.json"
    created = not target.exists()
    if created:
        _atomic_write_json(target, draft)
    return {'id': draft['id'], 'path': str(target), 'created': created}


def _load_json(path):
    with Path(path).open(encoding='utf-8') as reader:
        return json.load(reader)


def load_draft(lab_home, draft_id):
    target = Path(lab_home) / 'drafts' / f'{draft_id}.json'
    draft = _load_json(target)
    if canonical_id({key: value for key, value in draft.items() if key != 'id'}) != draft_id:
        raise ValueError('草稿内容与摘要不一致，可能被篡改')
    return draft


def list_drafts(lab_home):
    directory = Path(lab_home) / 'drafts'
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob('*.json'))


def publish_pack(lab_home, draft, selections):
    """把草稿发布为不可变规则包。

    selections: {(template, field): candidate_id}。只有在全部人工样本上
    一致的候选允许入选；未决字段（samples_conflict）直接拒绝发布。
    同一字段存在多个一致候选且未显式指定时，也拒绝，避免替运营拍板。
    """
    if draft.get('schema') != DRAFT_SCHEMA:
        raise ValueError('只能从草稿发布规则包')
    pack_templates = {}
    chosen = []
    for template, body in draft['templates'].items():
        fields = {}
        for field, report in body['fields'].items():
            if report['status'] != 'consistent':
                raise ValueError(
                    f'{template}/{field} 存在样本冲突（{report["status"]}），'
                    '未决字段不能发布')
            candidates = report['candidates']
            key = f'{template}/{field}'
            wanted = selections.get(key)
            if wanted is None:
                if len(candidates) == 1:
                    pick = candidates[0]
                else:
                    raise ValueError(
                        f'{key} 有 {len(candidates)} 个一致候选，'
                        '必须由运营显式选择后才能发布')
            else:
                matches = [item for item in candidates if item['id'] == wanted]
                if not matches:
                    raise ValueError(f'{key} 选择的候选 {wanted} 不在一致候选列表中')
                pick = matches[0]
            fields[field] = {
                'candidate_id': pick['id'],
                'kind': pick['kind'],
                'feature': pick['feature'],
                'xpath': pick['xpath'],
                'negative': list(report['negative']),
            }
            chosen.append({'field': key, 'candidate_id': pick['id']})
        pack_templates[template] = {
            'record_locator': dict(body['record_locator']),
            'record_signature': list(body['record_signature']),
            'fields': fields,
        }

    pack = {
        'schema': PACK_SCHEMA,
        'sources': draft['sources'],
        'templates': pack_templates,
        'selections': chosen,
    }
    pack['id'] = canonical_id(pack)
    target = Path(lab_home) / 'packs' / f"{pack['id']}.json"
    created = not target.exists()
    if created:
        _atomic_write_json(target, pack)
    return {'id': pack['id'], 'path': str(target), 'created': created,
            'selections': chosen}


def load_pack(lab_home, pack_id=None):
    if pack_id is None:
        pack_id = active_pack(lab_home)
        if pack_id is None:
            raise ValueError('尚未激活任何规则包')
    target = Path(lab_home) / 'packs' / f'{pack_id}.json'
    pack = _load_json(target)
    if canonical_id({key: value for key, value in pack.items() if key != 'id'}) != pack_id:
        raise ValueError('规则包内容与摘要不一致，拒绝执行')
    return pack


def list_packs(lab_home):
    directory = Path(lab_home) / 'packs'
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob('*.json'))


def activate_pack(lab_home, pack_id):
    existing = list_packs(lab_home)
    if pack_id not in existing:
        raise ValueError(f'规则包不存在: {pack_id}')
    _atomic_write_json(Path(lab_home) / ACTIVE_NAME, {'pack': pack_id})
    return pack_id


def active_pack(lab_home):
    pointer = Path(lab_home) / ACTIVE_NAME
    if not pointer.exists():
        return None
    return _load_json(pointer)['pack']


def lab_status(lab_home):
    return {
        'drafts': list_drafts(lab_home),
        'packs': list_packs(lab_home),
        'active': active_pack(lab_home),
    }
