"""
縦型（1行1問題・回答）フォーマットのExcelを採点するスクリプト。
e-learning系ツールのエクスポート形式（ユニット, 出題順, 問題文, 解答 列）に対応。

Usage:
  python grade_longformat.py <answers.xlsx> [exam_id]

exam_id を省略すると環境変数 DEFAULT_EXAM_ID を使用。
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import json
import uuid
import datetime
from pathlib import Path
import pandas as pd
from grader import grade_single, get_certification
import re
import html

EXAM_ID = "9cc1d5d4-8a43-428f-849c-1d55206832d4"
BASE_DIR = Path(__file__).parent
EXAMS_DIR = BASE_DIR / "exams"
RESULTS_DIR = BASE_DIR / "results"
UPLOADS_DIR = BASE_DIR / "uploads"

SCENE_OFFSET = {
    "シーン1": 0,
    "シーン2": 8,
    "シーン3": 15,
}
BAND_KEY = "10情報統括"  # group_questions.json のキー（属性列の値から解決）


def detect_band_key(attr: str, gq_keys: list) -> str:
    """属性列の値（例: '情報統括班'）からgroup_questionsのキーを解決"""
    # 完全部分一致
    for k in gq_keys:
        if attr in k or k in attr:
            return k
    # 数字プレフィックスを除去して照合（例: '10情報統括' → '情報統括'）
    # 属性から「班」を除去して照合
    attr_core = attr.rstrip("班")
    for k in gq_keys:
        k_core = k.lstrip("0123456789")
        if attr_core in k_core or k_core in attr_core:
            return k
    return None


def extract_scene(unit_str: str) -> str:
    """ユニット列からシーン名を抽出"""
    for scene in ["シーン1", "シーン2", "シーン3"]:
        if scene in unit_str:
            return scene
    return None


def clean_question_text(raw: str) -> str:
    """問題文からHTMLエンティティ・状況付与資料リンク部分を除去"""
    text = html.unescape(raw)
    # 「状況付与資料（クリックで別ウィンドウ表示）」以降の本文を取る
    marker = "状況付与資料（クリックで別ウィンドウ表示）"
    if marker in text:
        text = text[text.index(marker) + len(marker):].strip()
    return text.strip()


def load_context(exam_id: str) -> dict:
    ctx_path = EXAMS_DIR / exam_id / "context.json"
    if ctx_path.exists():
        with open(ctx_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def grade_longformat(answers_path: str, exam_id: str = EXAM_ID):
    answers_path = Path(answers_path)
    df = pd.read_excel(answers_path)
    df = df.dropna(subset=["名前"])  # 空行除去

    # 練習問題を除外
    df = df[~df["ユニット"].astype(str).str.contains("練習問題", na=False)]

    # group_questions 読み込み
    gq_path = EXAMS_DIR / exam_id / "group_questions.json"
    with open(gq_path, encoding="utf-8") as f:
        group_questions = json.load(f)

    ctx = load_context(exam_id)
    prerequisite = ctx.get("prerequisite", "")
    scenes = ctx.get("scenes", {})

    # 受験者一覧（ログインID単位で集約）
    examinees = df.groupby("ログインID")
    all_results = []

    for login_id, rows in examinees:
        name = rows["名前"].iloc[0]
        attr = rows["属性"].iloc[0] if "属性" in rows.columns else ""
        group = rows["グループ"].iloc[0] if "グループ" in rows.columns else ""

        band_key = detect_band_key(str(attr), list(group_questions.keys()))
        if not band_key:
            band_key = detect_band_key(str(group), list(group_questions.keys()))
        if not band_key:
            print(f"  [SKIP] {name}: 班キー不明 (属性={attr}, グループ={group})")
            continue

        questions = group_questions[band_key]
        q_by_seq = {q["seq"]: q for q in questions}

        comp_cols = ['ｺﾐｭﾆｹｰｼｮﾝ', '情報収集', '情報分析', '想像・先読み', '計画']
        comp_totals = {c: 0 for c in comp_cols}
        comp_max = {c: 0 for c in comp_cols}
        graded_answers = []

        print(f"\n採点開始: {name}（{band_key}）")

        for _, row in rows.sort_values("出題順").iterrows():
            unit = str(row["ユニット"])
            scene = extract_scene(unit)
            if not scene:
                continue

            seq_in_scene = int(row["出題順"])
            offset = SCENE_OFFSET.get(scene, 0)
            seq = offset + seq_in_scene

            q = q_by_seq.get(seq)
            if not q:
                print(f"  [WARN] seq={seq} が見つかりません (scene={scene}, 出題順={seq_in_scene})")
                continue

            answer_text = str(row.get("解答", ""))
            if answer_text in ("nan", "NaN", "None"):
                answer_text = ""

            active = q["active_comps"]
            rubrics = q.get("rubrics", {})
            scene_context = scenes.get(q["scene"], "")

            print(f"  Q{seq:02d} ({q['scene']}) [{', '.join(active)}] ...", end="", flush=True)

            result = grade_single(
                question_text=q["text"],
                rubrics_per_comp=rubrics,
                answer=answer_text,
                competencies=active,
                prerequisite=prerequisite,
                scene_context=scene_context,
            )
            result.update({
                "question_id":    q["label"],
                "question_text":  q["text"],
                "question_type":  q.get("type", "記述式"),
                "question_genre": q["scene"],
                "answer_text":    answer_text,
                "competencies":   active,
            })
            graded_answers.append(result)

            scores = result["competency_scores"]
            score_str = " ".join(f"{c}:{v}" for c, v in scores.items())
            fz = " [強制0点]" if result.get("forced_zero") else ""
            print(f" {score_str}{fz}")

            for c, s in scores.items():
                comp_totals[c] = comp_totals.get(c, 0) + s
                comp_max[c] = comp_max.get(c, 0) + 3

        total_score = sum(comp_totals.values())
        total_max = sum(comp_max.values())
        percentage = round(total_score / total_max * 100, 1) if total_max > 0 else 0
        comp_rates = {
            c: round(comp_totals[c] / comp_max[c] * 100, 1) if comp_max[c] > 0 else 0
            for c in comp_cols
        }

        all_results.append({
            "id":              login_id,
            "name":            name,
            "genre":           str(attr),
            "department":      str(group),
            "total_score":     total_score,
            "total_max":       total_max,
            "percentage":      percentage,
            "certification":   get_certification(percentage),
            "comp_totals":     comp_totals,
            "comp_max":        comp_max,
            "comp_rates":      comp_rates,
            "competency_cols": comp_cols,
            "answers":         graded_answers,
        })
        print(f"  合計: {total_score}/{total_max}点 ({percentage}%) → {get_certification(percentage)['level']}")

    # 結果保存
    session_id = str(uuid.uuid4())
    results_dir = RESULTS_DIR / session_id
    results_dir.mkdir(parents=True, exist_ok=True)

    # exam_ref.json も作成（Word DL 等のため）
    session_dir = UPLOADS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    with open(session_dir / "exam_ref.json", "w", encoding="utf-8") as f:
        json.dump({"exam_id": exam_id}, f)

    summary_path = results_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n結果保存: {summary_path}")
    print(f"\n--- レポートURL ---")
    for r in all_results:
        print(f"http://localhost:5051/report/{session_id}/{r['id']}")
    print(f"\n一覧: http://localhost:5051/results/{session_id}")
    return session_id, all_results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python grade_longformat.py <answers.xlsx> [exam_id]")
        sys.exit(1)
    answers_file = sys.argv[1]
    exam_id = sys.argv[2] if len(sys.argv) > 2 else EXAM_ID
    grade_longformat(answers_file, exam_id)
