import os
import json
from pathlib import Path
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """あなたは防災・危機管理分野の専門家であり、公正な試験採点者です。
受験者の回答をコンピテンシーごとに採点し、必ずJSON形式のみで回答してください（説明文不要）。

【認定プログラムの目的と背景】
本試験はインバスケット形式を通じて、受講者自身の災害対応における強みと弱みを把握し、
中上級者に求められるコンピテンシーを高めることを目的としている。

■ 災害対策員とは
災害等が発生、又は発生する恐れがある場合に、班毎にあらかじめ定められた場所に参集（リモート含む）して、
情報共有及び災害等応急復旧を実施する者。

■ 上級者のありたい姿
収集された情報からリスク・影響を想像して先読みし、組織全体を俯瞰して優先順位を判断し意思決定できる。
災対の経験や課題に対して改善の提案ができる。

■ 中級者のありたい姿
収集された情報の中から重大な影響を及ぼすクリティカルな情報を判断でき、分かりやすく伝えることができる。

採点・フィードバックは常にこの文脈——「災害対策員として、上記のありたい姿に近づくための評価」——を意識して記述すること。

【通常の採点原則】
- 各コンピテンシーを0〜3点で独立して評価する（3点満点）
- 採点基準に明記された1点・2点・3点の条件を厳密に参照する
- フィードバックは建設的かつ実践的に記述する
- 「災害対策員として」「班での情報共有・応急復旧の文脈で」という視点を常に意識する

【強制0点ルール（採点基準より最優先）】
下記のいずれかに該当する場合は、採点基準の達成度に関わらず当該問題の全コンピテンシーを強制0点とする（他の問題には影響しない）。
必ず forced_zero: true と forced_zero_reason に具体的な理由を日本語で記載すること。

① 空欄・無回答
② 人命や安全を軽視した発言・考え方
   （例：負傷者の対応を後回し、安全確認を省略して業務優先、避難を軽視するなど）
③ 自分だけを優先する自己中心的な考え方
   （例：自身の安全のみを確保し、班員・組織・周囲への配慮が一切ない）
④ 他者に迷惑・過度な負担をかける行為
   （例：誤情報の拡散、独断で他班の業務に介入、不必要なリソースの独占など）

該当しない場合は forced_zero: false、forced_zero_reason: \"\" とする。"""


# ── プロンプト構築 ─────────────────────────────────────────────────────────────

def build_prompt(question_text, rubrics_per_comp, answer, competencies,
                 prerequisite="", scene_context=""):
    """
    rubrics_per_comp: dict {comp_name: rubric_text}（コンピテンシー別採点基準）
    prerequisite: 試験全体の前提条件テキスト
    scene_context: この問題が属するシーンのコンテキストテキスト
    """
    comp_blocks = []
    for c in competencies:
        r = rubrics_per_comp.get(c, '') if isinstance(rubrics_per_comp, dict) else rubrics_per_comp
        comp_blocks.append(f"【{c}の採点基準】\n{r or '（採点基準なし）'}")

    comp_keys = ", ".join(f'"{c}": <0〜3の整数>' for c in competencies)
    comp_reason_keys = ", ".join(f'"{c}": "<採点理由（〜のためX点）>"' for c in competencies)

    context_block = ""
    if prerequisite:
        context_block += f"{prerequisite}\n\n"
    if scene_context:
        context_block += f"{scene_context}\n\n"

    return f"""以下の防災危機管理試験の問題に対する受験者の回答を、コンピテンシーごとに採点してください。

{context_block}【問題】
{question_text}

{chr(10).join(comp_blocks)}

【受験者の回答】
{answer if answer and str(answer).strip() else "（無回答）"}

以下のJSON形式のみで回答してください：
{{
  "forced_zero": <true または false>,
  "forced_zero_reason": "<強制0点の場合のみ理由を記載、該当なしは空文字>",
  "competency_scores": {{{comp_keys}}},
  "competency_reasons": {{{comp_reason_keys}}},
  "feedback": "<採点コメント（2〜3文）>",
  "key_points_achieved": ["<達成したポイント（強制0点の場合は空リスト）>"],
  "key_points_missed": ["<不足していたポイント>"],
  "improvement_advice": "<改善アドバイス（1〜2文）>"
}}

competency_reasons の記述ルール：
- 「〜のため（コンピテンシー名）はX点」の形式で、回答のどの部分がその点数の根拠かを1文で記述する
- 強制0点の場合は全て「強制0点のため0点」とする"""


# ── 1問採点（汎用） ───────────────────────────────────────────────────────────

def grade_single(question_text, rubrics_per_comp, answer, competencies,
                 q_type="記述式", prerequisite="", scene_context=""):
    """1問を採点してコンピテンシー別スコアを返す"""
    if not answer or str(answer).strip() in ('', 'nan', 'NaN', 'None'):
        return {
            "competency_scores": {c: 0 for c in competencies},
            "competency_reasons": {c: "無回答のため0点" for c in competencies},
            "feedback": "無回答のため0点です。",
            "key_points_achieved": [],
            "key_points_missed": competencies[:],
            "improvement_advice": "この問題は学習の優先課題です。",
        }

    prompt = build_prompt(question_text, rubrics_per_comp, answer, competencies,
                          prerequisite=prerequisite, scene_context=scene_context)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())

    # 強制0点処理
    if result.get("forced_zero", False):
        result["competency_scores"] = {c: 0 for c in competencies}
    else:
        result["competency_scores"] = {
            k: max(0, min(3, int(v))) for k, v in result["competency_scores"].items()
        }
    result.setdefault("forced_zero", False)
    result.setdefault("forced_zero_reason", "")
    result.setdefault("competency_reasons", {})
    return result


# ── 班別採点（group_based モード） ────────────────────────────────────────────

def load_context(results_dir) -> dict:
    """results_dir の親から exam_id を逆引きしてコンテキストを読む"""
    # results_dir = BASE/results/<session_id>
    # exam_ref.json は uploads/<session_id>/exam_ref.json にある
    base = Path(results_dir).parent.parent  # BASE_DIR
    uploads_dir = base / "uploads"
    exams_dir = base / "exams"

    # session_id は results_dir の名前
    session_id = Path(results_dir).name
    ref_path = uploads_dir / session_id / "exam_ref.json"
    if not ref_path.exists():
        return {}
    with open(ref_path, encoding="utf-8") as f:
        ref = json.load(f)
    exam_id = ref.get("exam_id", "")
    ctx_path = exams_dir / exam_id / "context.json"
    if not ctx_path.exists():
        return {}
    with open(ctx_path, encoding="utf-8") as f:
        return json.load(f)


def grade_exam_group_based(group_questions: dict, answers_df, column_mapping: dict, results_dir):
    """
    group_questions: {班名: [{seq, label, text, active_comps, rubrics, ...}]}
    answers_df: 受験者回答DataFrame（Q01〜Q22列 + 受験者ID/氏名/班名/所属）
    """
    # コンテキスト読み込み
    ctx = load_context(results_dir)
    prerequisite = ctx.get("prerequisite", "")
    scenes = ctx.get("scenes", {})

    cm = column_mapping
    a_id_col    = cm.get("a_id",    answers_df.columns[0])
    a_name_col  = cm.get("a_name",  answers_df.columns[1])
    a_genre_col = cm.get("a_genre", answers_df.columns[2])
    a_dept_col  = cm.get("a_dept",  answers_df.columns[3] if len(answers_df.columns) > 3 else None)
    comp_cols   = cm.get("competency_cols", ['ｺﾐｭﾆｹｰｼｮﾝ', '情報収集', '情報分析', '想像・先読み', '計画'])

    all_results = []

    for _, a_row in answers_df.iterrows():
        examinee_id    = str(a_row[a_id_col])
        examinee_name  = str(a_row[a_name_col])
        examinee_genre = str(a_row[a_genre_col]).strip() if a_genre_col and a_genre_col in a_row.index else ""
        examinee_dept  = str(a_row[a_dept_col]).strip() if a_dept_col and a_dept_col in a_row.index else ""

        # この人の班の問題セットを取得
        questions = group_questions.get(examinee_genre)
        if not questions:
            # 部分一致でフォールバック
            questions = next((v for k, v in group_questions.items() if examinee_genre in k or k in examinee_genre), None)
        if not questions:
            continue  # 班が不明なのでスキップ

        graded_answers = []
        comp_totals = {c: 0 for c in comp_cols}
        comp_max    = {c: 0 for c in comp_cols}

        for q in questions:
            seq_label = f"Q{q['seq']:02d}"
            answer_text = str(a_row.get(seq_label, ''))
            if answer_text in ('nan', 'NaN', 'None'):
                answer_text = ''

            active = q.get('active_comps', [])
            rubrics = q.get('rubrics', {})

            if not active:
                continue

            scene_context = scenes.get(q.get('scene', ''), '')
            result = grade_single(
                question_text=q['text'],
                rubrics_per_comp=rubrics,
                answer=answer_text,
                competencies=active,
                prerequisite=prerequisite,
                scene_context=scene_context,
            )
            result.update({
                "question_id":    q['label'],
                "question_text":  q['text'],
                "question_type":  q.get('type', '記述式'),
                "question_genre": q.get('scene', ''),
                "answer_text":    answer_text,
                "competencies":   active,
            })
            graded_answers.append(result)

            for c, s in result["competency_scores"].items():
                comp_totals[c] = comp_totals.get(c, 0) + s
                comp_max[c]    = comp_max.get(c, 0) + 2

        total_score = sum(comp_totals.values())
        total_max   = sum(comp_max.values())
        percentage  = round(total_score / total_max * 100, 1) if total_max > 0 else 0
        comp_rates  = {
            c: round(comp_totals[c] / comp_max[c] * 100, 1) if comp_max[c] > 0 else 0
            for c in comp_cols
        }

        all_results.append({
            "id":              examinee_id,
            "name":            examinee_name,
            "genre":           examinee_genre,
            "department":      examinee_dept,
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

    return all_results


# ── 汎用採点（既存の Excel形式） ─────────────────────────────────────────────

def detect_competency_columns(questions_df, column_mapping):
    comp_cols = column_mapping.get("competency_cols", [])
    if comp_cols:
        return [c for c in comp_cols if c in questions_df.columns]
    basic_cols = {
        column_mapping.get(k, "") for k in ("q_id", "q_text", "q_type", "q_genre", "q_rubric")
    }
    candidates = []
    for col in questions_df.columns:
        if col in basic_cols:
            continue
        vals = questions_df[col].dropna().astype(str).str.strip()
        if vals.isin(["○", "✓", "1", "true", "TRUE", "◯", "〇"]).any():
            candidates.append(col)
    return candidates


def grade_exam(questions_df, answers_df, column_mapping, results_dir):
    cm = column_mapping
    q_id_col     = cm.get("q_id",    questions_df.columns[0])
    q_text_col   = cm.get("q_text",  questions_df.columns[1])
    q_type_col   = cm.get("q_type",  questions_df.columns[2] if len(questions_df.columns) > 2 else None)
    q_genre_col  = cm.get("q_genre", questions_df.columns[3] if len(questions_df.columns) > 3 else None)
    q_rubric_col = cm.get("q_rubric", questions_df.columns[-1])
    a_id_col     = cm.get("a_id",    answers_df.columns[0])
    a_name_col   = cm.get("a_name",  answers_df.columns[1])
    a_dept_col   = cm.get("a_dept",  answers_df.columns[2] if len(answers_df.columns) > 2 else None)
    a_genre_col  = cm.get("a_genre", answers_df.columns[3] if len(answers_df.columns) > 3 else None)

    competency_cols = detect_competency_columns(questions_df, cm)

    questions = []
    for _, row in questions_df.iterrows():
        active = [c for c in competency_cols if str(row.get(c, '')).strip() in ("○", "✓", "1", "true", "TRUE", "◯", "〇")]
        questions.append({
            "id":     str(row[q_id_col]),
            "text":   str(row[q_text_col]),
            "type":   str(row[q_type_col]) if q_type_col and q_type_col in row.index else "記述式",
            "genre":  str(row[q_genre_col]) if q_genre_col and q_genre_col in row.index else "共通",
            "active_comps": active,
            "rubrics": {c: str(row.get(q_rubric_col, '')) for c in active},
        })

    all_results = []
    for _, a_row in answers_df.iterrows():
        examinee_id    = str(a_row[a_id_col])
        examinee_name  = str(a_row[a_name_col])
        examinee_dept  = str(a_row[a_dept_col]) if a_dept_col and a_dept_col in a_row.index else ""
        examinee_genre = str(a_row[a_genre_col]) if a_genre_col and a_genre_col in a_row.index else ""

        graded_answers = []
        comp_totals = {c: 0 for c in competency_cols}
        comp_max    = {c: 0 for c in competency_cols}

        for q in questions:
            answer_col = cm.get(f"answer_{q['id']}", q["id"])
            if answer_col not in a_row.index:
                matching = [c for c in a_row.index if str(q["id"]) == str(c)]
                answer_col = matching[0] if matching else None
            answer_text = str(a_row[answer_col]) if answer_col and answer_col in a_row.index else ""
            if answer_text in ('nan', 'NaN', 'None'): answer_text = ''

            active = q["active_comps"] or competency_cols
            result = grade_single(q["text"], q["rubrics"], answer_text, active)
            result.update({
                "question_id":    q["id"],
                "question_text":  q["text"],
                "question_type":  q["type"],
                "question_genre": q["genre"],
                "answer_text":    answer_text,
                "competencies":   active,
            })
            graded_answers.append(result)
            for c, s in result["competency_scores"].items():
                comp_totals[c] = comp_totals.get(c, 0) + s
                comp_max[c]    = comp_max.get(c, 0) + 2

        total_score = sum(comp_totals.values())
        total_max   = sum(comp_max.values())
        percentage  = round(total_score / total_max * 100, 1) if total_max > 0 else 0
        comp_rates  = {
            c: round(comp_totals[c] / comp_max[c] * 100, 1) if comp_max[c] > 0 else 0
            for c in competency_cols
        }
        all_results.append({
            "id": examinee_id, "name": examinee_name,
            "department": examinee_dept, "genre": examinee_genre,
            "total_score": total_score, "total_max": total_max,
            "percentage": percentage, "certification": get_certification(percentage),
            "comp_totals": comp_totals, "comp_max": comp_max,
            "comp_rates": comp_rates, "competency_cols": competency_cols,
            "answers": graded_answers,
        })
    return all_results


def get_certification(percentage):
    if percentage >= 90:
        return {"level": "上級認定", "label": "S", "color": "#1a6e3c"}
    elif percentage >= 75:
        return {"level": "中級認定", "label": "A", "color": "#1a4e8c"}
    elif percentage >= 60:
        return {"level": "基礎認定", "label": "B", "color": "#5a7a1a"}
    else:
        return {"level": "要再受験", "label": "C", "color": "#8c2a1a"}
