# 防災訓練認定試験 採点システム 仕様書

**バージョン**: 2026年5月15日時点  
**開発環境**: Python 3.14 / Flask / Windows 11

---

## 1. システム概要

危機管理室が実施する「防災訓練認定試験」の受験者回答を、Claude AI（Anthropic API）を使って自動採点し、個人採点レポートをWeb画面・Word・PDFで出力するシステム。

---

## 2. ファイル構成

```
bousai-grader/
├── app.py                  # Flaskアプリ本体（ルーティング・ビジネスロジック）
├── grader.py               # Claude APIを使った採点エンジン
├── grade_longformat.py     # 縦型（e-learning）Excelを採点するCLIスクリプト
├── report_generator.py     # Word（.docx）レポート生成
├── pdf_generator.py        # reportlabベースPDF生成（補助用・現在は未使用）
├── import_exam.py          # 試験問題ExcelをDBにインポートするCLIスクリプト
├── requirements.txt
├── exams/
│   └── {exam_id}/
│       ├── meta.json           # 試験名・作成日など
│       ├── context.json        # 試験背景・シーン説明・前提条件
│       ├── group_questions.json # 班別問題リスト（採点ルーブリック含む）
│       └── source.xlsx         # 元の試験問題Excel
├── results/
│   └── {session_id}/
│       ├── summary.json        # 採点結果（全受験者分）
│       └── report_{id}.docx    # 生成済みWordレポート
├── uploads/
│   └── {session_id}/
│       └── exam_ref.json       # 使用した試験IDの参照
├── static/
│   ├── css/
│   │   ├── bootstrap.min.css
│   │   └── bootstrap-icons.css
│   ├── fonts/
│   │   ├── bootstrap-icons.woff
│   │   └── bootstrap-icons.woff2
│   ├── js/
│   │   └── bootstrap.bundle.min.js
│   ├── sample_answers.xlsx     # 横型回答サンプル
│   ├── sample_questions.xlsx   # 問題サンプル
│   └── templates/              # 班別回答記入Excelテンプレート
└── templates/
    ├── base.html               # 共通レイアウト（ナビバー・フッター）
    ├── index.html              # トップページ（採点開始）
    ├── results.html            # 採点結果一覧
    ├── report.html             # 個人採点レポート
    ├── sessions.html           # 採点済みセッション一覧
    ├── exam_new.html           # 試験登録フォーム
    └── exam_list.html          # 試験一覧
```

---

## 3. 起動方法

```
ポート: 5051
起動コマンド: python -m flask --app bousai-grader/app run --port 5051 --debug
```

VS Code の launch.json に設定済み。

---

## 4. 採点フロー

### 4-1. 横型フォーマット（Web UI から）

1. トップページ（`/`）で試験を選択
2. 受験者回答Excelをアップロード（1行＝1受験者、Q01〜Q22列に回答）
3. Flask が `grader.py` の `grade_exam()` / `grade_exam_group_based()` を呼び出し
4. Claude API（`claude-sonnet-4-6`）が各問題をルーブリックに基づき採点
5. 結果を `results/{session_id}/summary.json` に保存
6. 採点結果一覧ページへリダイレクト

### 4-2. 縦型フォーマット（CLI から）

e-learning系ツールのエクスポート形式（1行＝1問題回答）を処理するスクリプト。

```bash
python grade_longformat.py <answers.xlsx> [exam_id]
```

- `ユニット` 列からシーンを判定（シーン1/2/3）
- `出題順` 列 + SCENE_OFFSET でseq番号を算出して問題を特定
- `属性` 列から受験者の班を特定してルーブリックを選択

**SCENE_OFFSET**:
| シーン | オフセット |
|--------|-----------|
| シーン1 | 0 |
| シーン2 | 8 |
| シーン3 | 15 |

---

## 5. データ構造

### 5-1. group_questions.json

```json
{
  "10情報統括": [
    {
      "seq": 1,
      "label": "共通01",
      "scene": "シーン1",
      "no": 1,
      "type": "共通",
      "text": "問題文（※評価対象コンピテンシー：〜 の注記を含む）",
      "active_comps": ["情報収集", "想像・先読み", "計画"],
      "rubrics": {
        "情報収集": "1点：〜\n2点：〜\n3点：〜",
        ...
      }
    },
    ...
  ],
  "04サービス": [ ... ],
  ...
}
```

### 5-2. summary.json（採点結果）

```json
[
  {
    "id": "takahito.toda",
    "name": "戸田 貴士",
    "genre": "情報統括班",
    "department": "危機管理室",
    "total_score": 119,
    "total_max": 153,
    "percentage": 77.8,
    "comp_totals": {"ｺﾐｭﾆｹｰｼｮﾝ": 28, "情報収集": 30, ...},
    "comp_max":    {"ｺﾐｭﾆｹｰｼｮﾝ": 33, "情報収集": 36, ...},
    "comp_rates":  {"ｺﾐｭﾆｹｰｼｮﾝ": 84.8, "情報収集": 83.3, ...},
    "competency_cols": ["ｺﾐｭﾆｹｰｼｮﾝ", "情報収集", "情報分析", "想像・先読み", "計画"],
    "answers": [
      {
        "question_id": "共通01",
        "question_text": "問題文",
        "question_type": "共通",
        "question_genre": "シーン1",
        "answer_text": "受験者の回答",
        "competencies": ["情報収集", "想像・先読み", "計画"],
        "competency_scores": {"情報収集": 2, "想像・先読み": 2, "計画": 2},
        "feedback": "採点コメント",
        "key_points_achieved": ["良かった点1", "良かった点2"],
        "key_points_missed": ["不足点1"],
        "improvement_advice": "改善アドバイス",
        "forced_zero": false,
        "forced_zero_reason": ""
      },
      ...
    ]
  }
]
```

---

## 6. コンピテンシー

採点対象の5コンピテンシー（各問題につき対象は1〜3種）：

| 表示名 | 内部キー |
|--------|---------|
| コミュニケーション | `ｺﾐｭﾆｹｰｼｮﾝ`（半角カナ） |
| 情報収集 | `情報収集` |
| 情報分析 | `情報分析` |
| 想像・先読み | `想像・先読み` |
| 計画 | `計画` |

各コンピテンシーは **0〜3点**で採点（ルーブリック基準）。

---

## 7. Webルート一覧

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/` | トップページ（採点開始） |
| POST | `/grade` | 採点実行 |
| GET | `/results/<session_id>` | 採点結果一覧 |
| GET | `/report/<session_id>/<examinee_id>` | 個人採点レポート（Web） |
| GET | `/report/<session_id>/<examinee_id>/download` | Wordダウンロード |
| GET | `/report/<session_id>/<examinee_id>/download/pdf` | PDFダウンロード |
| GET | `/sessions` | 採点済みセッション一覧 |
| GET | `/exam/new` | 試験登録フォーム |
| POST | `/exam/new` | 試験登録実行 |
| GET | `/exam/list` | 試験一覧 |

---

## 8. 個人採点レポートの構成

### Web画面（report.html）

1. **ヘッダー** - 氏名・所属・ジャンル・採点日・Word DL / PDF DL ボタン
2. **受験者情報 + 総合スコア** - 得点・得点率・コンピテンシー別達成率バー
3. **シーン別得点** - シーン1/2/3ごとの得点・達成率・コンピテンシー内訳
4. **ジャンル内比較** - ジャンル内順位・平均との差（同一ジャンルが複数いる場合）
5. **総合評価** - Claude生成の4段落コメント（得点率に応じたトーン）
6. **問題別採点結果** - シーン別にグループ化した全22問の詳細

### Word（.docx）

`report_generator.py` の `generate_word_report()` で生成。  
Webと同等の構成をテーブル形式で出力。

### PDF

`app.py` の `download_report_pdf()` で生成。  
Playwright（Chromium）がWebレポートページをHTMLレンダリングしてPDF化。  
**所要時間**: 約20秒（Chromiumが22問分のレイアウトを処理するため）。

---

## 9. 総合評価コメントの生成ロジック

`build_overall_comment()` 関数（app.py）が4段落で構成：

| 段落 | 内容 |
|------|------|
| ① 導入 | 得点率に応じた評価（≥80%／≥65%／≥50%／それ以下） |
| ② 強みの言語化 | 達成率70%以上のコンピテンシーを列挙・称賛 |
| ③ シーン別振り返り | 各シーンの得点率に応じた一言評価 |
| ④ 成長への期待 | 達成率70%未満のコンピテンシーを具体的に示し改善を促す |

---

## 10. 採点結果一覧（results.html）の表示要素

- 受験者数・全体平均得点率・最高得点率・最低得点率
- 全体コンピテンシー別平均達成率（バーグラフ）
- ジャンル別フィルタボタン
- 受験者テーブル（氏名・ジャンル・所属・得点・得点率・コンピテンシー別・レポートリンク）
- ジャンル別サマリー（平均・最高・最低・コンピテンシー別平均）

---

## 11. 認定レベルについて

本システムでは認定レベル（上級／中級／基礎／要再受験）の表示は**行わない**。  
得点（●点中●点）と得点率のみを表示する。

---

## 12. 依存ライブラリ

```
flask>=3.0.0
anthropic>=0.40.0
pandas>=2.0.0
openpyxl>=3.1.0
python-docx>=1.1.0
werkzeug>=3.0.0
reportlab>=4.0.0
playwright>=1.40.0
```

Playwrightは初回セットアップ時に別途 Chromium のインストールが必要：
```bash
python -m playwright install chromium
```

---

## 13. 既知の制限・注意事項

- **PDF生成時間**: 約20秒（Chromiumのレイアウト処理）。ブラウザの接続タイムアウトには引っかからないが、待ち時間が発生する。
- **縦型採点（grade_longformat.py）**: CLIのみ。WebUIからのアップロードには未対応。
- **問題文の空欄**: 試験データ登録時に `text` フィールドが未入力だと問題文が表示されない。`group_questions.json` を直接編集して補完し、既存 `summary.json` も合わせて修正する必要がある。
- **ANTHROPIC_API_KEY**: 環境変数に設定が必要。PowerShellでは `$env:ANTHROPIC_API_KEY = "sk-ant-..."` で設定。
