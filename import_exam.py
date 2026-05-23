"""
2026年度認定プログラムExcelを読み込み、試験をシステムに登録し、
回答記入用テンプレートExcelを生成するスクリプト。

使い方:
  python import_exam.py <Excelファイルパス> [出力フォルダ]
"""
import sys
import io
import json
import uuid
import shutil
from pathlib import Path
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).parent
EXAMS_DIR = BASE_DIR / "exams"
EXAMS_DIR.mkdir(exist_ok=True)

COMP_COLS = ['ｺﾐｭﾆｹｰｼｮﾝ', '情報収集', '情報分析', '想像・先読み', '計画']
RUBRIC_COLS = {
    'ｺﾐｭﾆｹｰｼｮﾝ': '評価基準（ｺﾐｭﾆｹｰｼｮﾝ）',
    '情報収集':    '評価基準（情報収集）',
    '情報分析':    '評価基準（情報分析）',
    '想像・先読み': '評価基準（想像・先読み）',
    '計画':       '評価基準（計画）',
}

GROUPS = [
    '01本部長支援', '02広報', '03総務', '04サービス', '05お客様対応',
    '06設備', '07資材', '08セキュリティ', '09社内システム', '10情報統括',
]


def parse_questions(df):
    """問題シートを解析して、班ごとの問題リストを返す"""
    common_rows = df[df['班名'] == '00全班共通'].copy()

    group_questions = {}
    for group in GROUPS:
        group_rows = df[df['班名'] == group].copy()
        # 共通(シーン1) + 班固有(シーン2,3) を結合してシーン→No. 順でソート
        all_rows = pd.concat([common_rows, group_rows])
        # シーン順: シーン1 < シーン2 < シーン3
        scene_order = {'シーン1': 0, 'シーン2': 1, 'シーン3': 2}
        all_rows['_scene_ord'] = all_rows['シーン'].map(scene_order)
        all_rows = all_rows.sort_values(['_scene_ord', 'No.']).reset_index(drop=True)

        questions = []
        for i, row in all_rows.iterrows():
            q_no = row.get('共通', '')
            q_no_str = str(q_no).strip() if pd.notna(q_no) and str(q_no).strip() not in ('nan', '') else ''
            label = q_no_str if q_no_str else f"個別{row['シーン'].replace('シーン','')}Q{int(row['No.'])}"

            # このコンピテンシーを評価する列
            active_comps = [c for c in COMP_COLS if str(row.get(c, '')).strip() == '●']

            # コンピテンシー別採点基準
            rubrics = {}
            for c in active_comps:
                r = str(row.get(RUBRIC_COLS[c], '')).strip()
                rubrics[c] = r if r and r != 'nan' else ''

            questions.append({
                'seq': len(questions) + 1,           # 1〜22の通し番号
                'label': label,                        # 共通01 / 個別2Q3 等
                'scene': row['シーン'],
                'no': int(row['No.']),
                'type': row.get('共／個', '共通'),     # 共通 / 個別
                'text': str(row.get('問題', '')).strip(),
                'active_comps': active_comps,
                'rubrics': rubrics,
            })
        group_questions[group] = questions

    return group_questions


def build_exam_meta(exam_name, group_questions, source_path):
    exam_id = str(uuid.uuid4())
    exam_dir = EXAMS_DIR / exam_id
    exam_dir.mkdir()

    # 元ファイルをコピー
    shutil.copy(source_path, exam_dir / ('source' + Path(source_path).suffix))

    # 問題データをJSONで保存
    with open(exam_dir / 'group_questions.json', 'w', encoding='utf-8') as f:
        json.dump(group_questions, f, ensure_ascii=False, indent=2)

    sample_group = list(group_questions.keys())[0]
    meta = {
        'exam_id': exam_id,
        'name': exam_name,
        'created_at': str(pd.Timestamp.today().date()),
        'questions_count': len(group_questions[sample_group]),
        'groups': list(group_questions.keys()),
        'competency_cols': COMP_COLS,
        'columns': ['受験者ID', '氏名', '班名', '所属'] + [f'Q{i:02d}' for i in range(1, 23)],
        'column_mapping': {
            'a_id': '受験者ID',
            'a_name': '氏名',
            'a_genre': '班名',
            'a_dept': '所属',
            'competency_cols': COMP_COLS,
        },
        'mode': 'group_based',   # 班ごとに問題セットが異なるモード
        'file_ext': '.xlsx',
    }
    with open(exam_dir / 'meta.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return exam_id, exam_dir


def generate_answer_template(group_questions, output_dir):
    """回答記入用テンプレートExcelを班ごとに生成"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_rows = []  # 全班まとめたシートも作成

    with pd.ExcelWriter(output_dir / '回答記入テンプレート_全班.xlsx', engine='openpyxl') as writer:
        for group, questions in group_questions.items():
            # ヘッダー行: 基本情報 + 問題ラベル
            headers_row1 = ['受験者ID', '氏名', '班名', '所属'] + \
                           [f"Q{q['seq']:02d}" for q in questions]
            headers_row2 = ['', '', '', ''] + \
                           [q['label'] for q in questions]
            scene_row = ['', '', '', ''] + \
                        [q['scene'] for q in questions]

            # サンプルデータ行（空）
            sample = ['（例）E001', '山田 太郎', group, '〇〇部'] + [''] * 22

            df_out = pd.DataFrame([headers_row2, scene_row, sample],
                                  columns=headers_row1)
            df_out.to_excel(writer, sheet_name=group, index=False)

            all_rows.append({
                'group': group,
                'headers': headers_row1,
                'row2': headers_row2,
                'scene': scene_row,
            })

        print(f"  回答テンプレート生成: {len(group_questions)}班分")

    # 各班ごとの個別テンプレートも生成
    for group, questions in group_questions.items():
        headers_row1 = ['受験者ID', '氏名', '班名', '所属'] + \
                       [f"Q{q['seq']:02d}" for q in questions]
        headers_row2 = ['', '', '', ''] + [q['label'] for q in questions]
        scene_row   = ['', '', '', ''] + [q['scene'] for q in questions]
        comp_row    = ['', '', '', ''] + \
                      ['/'.join(q['active_comps']) for q in questions]

        rows = [
            ['問題ラベル'] + headers_row2[1:],
            ['シーン'] + scene_row[1:],
            ['評価コンピテンシー'] + comp_row[1:],
        ]
        df_top = pd.DataFrame(rows, columns=headers_row1)
        empty_rows = pd.DataFrame(
            [[''] * len(headers_row1)] * 10,
            columns=headers_row1
        )
        empty_rows.iloc[:, 0] = [f'E{str(i+1).zfill(3)}' for i in range(10)]
        empty_rows.iloc[:, 2] = group

        df_out = pd.concat([df_top, empty_rows], ignore_index=True)
        fname = output_dir / f'回答テンプレート_{group}.xlsx'
        df_out.to_excel(fname, index=False)

    print(f"  個別テンプレート生成: {len(group_questions)}ファイル")


def main():
    if len(sys.argv) < 2:
        print("使い方: python import_exam.py <Excelファイルパス>")
        sys.exit(1)

    source_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else str(BASE_DIR / 'static' / 'templates')
    exam_name = sys.argv[3] if len(sys.argv) > 3 else '2026年度防災認定プログラム（中上級）'

    print(f"読み込み: {source_path}")
    df = pd.read_excel(source_path, sheet_name='問題', header=0)
    print(f"  問題シート: {len(df)}行")

    print("問題データを解析中...")
    group_questions = parse_questions(df)
    for g, qs in group_questions.items():
        active = sum(1 for q in qs if q['active_comps'])
        print(f"  {g}: {len(qs)}問 (コンピテンシー設定: {active}問)")

    print(f"\n試験を登録中: {exam_name}")
    exam_id, exam_dir = build_exam_meta(exam_name, group_questions, source_path)
    print(f"  exam_id: {exam_id}")

    print("\n回答テンプレートを生成中...")
    generate_answer_template(group_questions, output_dir)

    print(f"\n完了!")
    print(f"  試験ID: {exam_id}")
    print(f"  テンプレート: {output_dir}")


if __name__ == '__main__':
    main()
