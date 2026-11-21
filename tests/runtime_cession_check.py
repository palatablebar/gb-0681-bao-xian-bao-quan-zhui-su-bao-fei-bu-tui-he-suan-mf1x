"""Run a real cession adjudication flow and print a compact evidence summary."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app
from app.modules.m8_cession import ledger
from app.modules.m8_cession.rules import CURRENT_OFFSET, ORIGINAL_RESTATEMENT


def main():
    with tempfile.TemporaryDirectory(prefix='cession-runtime-') as temp_dir:
        os.environ['DB_PATH'] = os.path.join(temp_dir, 'records.db')
        client = create_app().test_client()

        synced = client.post('/api/m8_cession/sync', json={})
        assert synced.status_code == 200
        created = synced.get_json()['created']
        assert created['adjustments'] == 3 and created['originals'] == 3

        view = client.get('/api/m8_cession').get_json()
        adjustments = {item['policy_id']: item for item in view['adjustments']}
        assert adjustments['P002']['period_closed'] is True
        assert adjustments['P005']['period_closed'] is True
        assert adjustments['P009']['period_closed'] is False

        for policy_id, destination in (
            ('P002', CURRENT_OFFSET),
            ('P005', CURRENT_OFFSET),
            ('P009', ORIGINAL_RESTATEMENT),
        ):
            response = client.post(
                '/api/m8_cession/adjustments/%s/attribute' % adjustments[policy_id]['adj_id'],
                json={'destination': destination},
            )
            assert response.status_code == 200

        attributed = client.get('/api/m8_cession').get_json()
        summary = attributed['summary']
        assert summary['pending_count'] == 0
        assert summary['all_attributed'] is True
        assert summary['net_conserved'] is True

        repeated = client.post('/api/m8_cession/sync', json={}).get_json()['created']
        assert repeated['skipped_duplicates'] == 3

        before = ledger.snapshot()
        open_adjustment = next(
            item for item in attributed['adjustments'] if item['policy_id'] == 'P009'
        )
        try:
            ledger.attribute(
                open_adjustment['adj_id'],
                CURRENT_OFFSET,
                'rollback-check',
                failure_hook=lambda: (_ for _ in ()).throw(RuntimeError('injected cutover failure')),
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError('injected failure did not roll back')
        after = ledger.snapshot()
        assert after == before
        active = next(item for item in after['adjustments'] if item['policy_id'] == 'P009')
        assert active['destination'] == ORIGINAL_RESTATEMENT

        exported = client.get('/api/m8_cession/export.csv')
        assert exported.status_code == 200
        csv_text = exported.data.decode('utf-8-sig')
        assert all(item['adj_id'] in csv_text for item in attributed['adjustments'])
        assert '原账期重述' in csv_text and '当期冲抵' in csv_text
        assert '全部已归属,true' in csv_text

        print(json.dumps({
            'adjustment_count': summary['adjustment_count'],
            'pending_after': summary['pending_count'],
            'all_attributed': summary['all_attributed'],
            'net_conserved': summary['net_conserved'],
            'skipped_duplicates': repeated['skipped_duplicates'],
            'rollback_old_version_preserved': True,
            'download_matches_page': True,
            'download_bytes': len(exported.data),
        }, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
