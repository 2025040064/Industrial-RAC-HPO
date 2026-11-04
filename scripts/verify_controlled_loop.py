"""Reproducible real CNC acceptance and native Qt screenshots, entirely local."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--render-root', type=Path)
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--scale', type=float, default=1)
    parser.add_argument('--sizes', default='720x560,1280x800,1920x1080')
    args = parser.parse_args()
    output = args.render_root or ROOT/'workspace/verification/controlled-loop'/f'acceptance-{time.time_ns()}'
    output = output.resolve()
    (output/'tmp').mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(output/'tmp')
    os.environ['MPLCONFIGDIR'] = str(output/'matplotlib')
    os.environ['QT_QPA_PLATFORM'] = 'windows' if args.native else 'offscreen'
    os.environ['QT_SCALE_FACTOR'] = str(args.scale)
    from rac_hpo.application.loop_service import LoopService
    from rac_hpo.infrastructure.artifacts import write_json, source_fingerprint
    if not args.render_root:
        (output/'configs').mkdir()
        shutil.copy2(ROOT/'configs/default.yaml', output/'configs/default.yaml')
        shutil.copy2(ROOT/'uv.lock', output/'uv.lock')
        write_json(output/'implementation.json', {'root': str(ROOT), 'source_sha256': source_fingerprint(ROOT)})
        with zipfile.ZipFile(output/'implementation.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for source in (ROOT/'src').rglob('*.py'):
                archive.write(source, source.relative_to(ROOT))
        service = LoopService(output)
        session = service.create_session(ROOT/'datasets/raw/cnc_milling_2025/FeatureAndMetadata_Milling.csv',
                                         authorize_training=True)
        with (output/'run-events.jsonl').open('w', encoding='utf-8') as log:
            def progress(event):
                log.write(json.dumps(event, ensure_ascii=False, allow_nan=False)+'\n')
                log.flush()
            result = service.run_session(session['id'], manual_demo=True, progress_callback=progress)
        exported = service.export_session(session['id'])
        write_json(output/'acceptance.json', {'session_id': session['id'], 'state': result['state'],
            'training_seconds': result['training_seconds'], 'gate': result['gate'],
            'champion': result['champion'], 'candidate': result['candidate'], 'export_path': exported,
            'pending_human_approval': result['state'] == 'WAITING_RELEASE',
            'test_used': False, 'directory': str(output)})
        if not result['candidate'] or not result['gate']:
            raise RuntimeError(f"Real acceptance did not reach gate: {result['state']}")
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QScrollArea
    from rac_hpo.interfaces.gui.main_window import MainWindow
    from rac_hpo.interfaces.gui.theme import apply_theme
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = MainWindow(output)
    window.loop_page.path_edit.setText(str(ROOT/'datasets/raw/cnc_milling_2025/FeatureAndMetadata_Milling.csv'))
    window.navigation.setCurrentRow(5)
    window.show()
    captures = []
    mode = 'native' if args.native else 'offscreen'
    for requested in args.sizes.split(','):
        width, height = map(int, requested.split('x'))
        window.resize(width, height)
        QTest.qWait(250)
        filename = output/f'loop-{mode}-{width}x{height}-scale{args.scale:g}.png'
        assert window.grab().save(str(filename))
        scroll = window.loop_page.findChild(QScrollArea)
        item = {'requested': [width, height], 'actual': [window.width(), window.height()],
                'dpr': window.devicePixelRatioF(), 'horizontal_overflow': scroll.horizontalScrollBar().maximum(),
                'image': str(filename), 'pages': window.pages.count()}
        captures.append(item)
        if item['actual'] != item['requested'] or item['horizontal_overflow']:
            raise RuntimeError(f'Layout verification failed: {item}')
    write_json(output/f'gui-{mode}-scale{args.scale:g}.json', captures)
    window.close()
    app.processEvents()
    print(json.dumps({'directory': str(output), 'captures': captures}, ensure_ascii=False))


if __name__ == '__main__':
    main()
