import os
import json
from pathlib import Path
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """あなたは防災・危機管理分野の専門家であり、公正な試験採点者です。
受験者の回答をコンピテンシーごとに採点し、必ずJSON形式のみで回答してください（説明文不要）。

【認定プログラムの目的と背景】
本試験はインバスケット形式を通じて、受講者自身の災害対応における強みと弱みを把握し、
災害対策員に求められるコンピテンシーを高めることを目的としている。

■ 災害対策員とは
災害等が発生、又は発生する恐れがある場合に、班毎にあらかじめ定められた場所に参集（リモート含む）して、
情報共有及び災害等応急復旧を実施する者。

■ 災害対策員のありたい姿
収集された情報からリスク・影響を想像して先読みし、組織全体を俯瞰して優先順位を判断し意思決定できる。
収集された情報の中から重大な影響を及ぼすクリティカルな情報を判断でき、分かりやすく伝えることができる。
災対の経験や課題に対して改善の提案ができる。

採点・フィードバックは常にこの文脈——「災害対策員として、上記のありたい姿に近づくための評価」——を意識して記述すること。

【フィードバックの表現ルール（厳守）】
- 「中級者」「上級者」「中級者として」「上級者として」「上級者を目指し」などの
  レベルを示す表現は一切使用禁止。
- フィードバックは受験者を「災害対策員」として評価する表現のみ使用すること。
- 例：「災害対策員として」「班のリーダーとして」「今後の実践に向けて」など。

【採点の優先順位（必ず守ること）】

■ ステップ1：採点メモ（最優先）
採点基準のテキスト末尾に「〇〇している　X点」「〇〇な場合　X点」のような
具体的な記述例＋点数が示されている場合（採点メモ）、それを最優先で従う。
回答が採点メモの記述に該当するなら、そのメモの点数をそのまま採用すること。
採点メモが示す点数を、寛大な方針で上書きしてはならない。

■ ステップ2：通常判断（採点メモがない・グレーゾーンの場合）
採点メモがない、または回答が採点メモのどの例にも明確に当てはまらない場合は、
採点基準（1点・2点・3点）に照らして普通に判断する。
- 「書いていないこと」ではなく「書いていること」を積極的に評価する
- 迷った場合は寛大に評価しつつも、一律に上位点へ格上げはしない。格上げするか据え置くかはAIが判断し、その理由を明記する

【通常の採点原則】
- 各コンピテンシーを0〜3点で独立して評価する（3点満点）
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
        comp_blocks.append(f"【{c}の採点基準】\n{r or '（防災危機管理の専門知識と一般的な採点基準に基づいて評価してください）'}")

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
        temperature=0,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    # JSON部分だけをパース（余分なテキストを無視）
    brace_start = raw.find('{')
    if brace_start == -1:
        raise ValueError(f"JSONオブジェクトが見つかりません: {raw[:200]}")
    try:
        result, _ = json.JSONDecoder().raw_decode(raw, brace_start)
    except json.JSONDecodeError:
        brace_end = raw.rfind('}')
        result = json.loads(raw[brace_start:brace_end + 1])

    # 強制0点処理
    if result.get("forced_zero", False):
        result["competency_scores"] = {c: 0 for c in competencies}
    else:
        # Claudeが返すキー名を正規化（想像・先読み力 → 想像・先読み など）
        raw_scores = result["competency_scores"]
        normalized = {}
        for k, v in raw_scores.items():
            canonical = _COMP_NAME_MAP.get(k.strip(), k.strip())
            normalized[canonical] = max(0, min(3, int(v)))
        # competencies にあるがClaudeが返さなかった場合は0点
        for c in competencies:
            if c not in normalized:
                normalized[c] = 0
        result["competency_scores"] = normalized
    result.setdefault("forced_zero", False)
    result.setdefault("forced_zero_reason", "")
    # competency_reasons のキーも正規化
    raw_reasons = result.get("competency_reasons", {})
    result["competency_reasons"] = {
        _COMP_NAME_MAP.get(k.strip(), k.strip()): v
        for k, v in raw_reasons.items()
    }
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


# ── 縦型フォーマット用ヘルパー ─────────────────────────────────────────────────

import re as _re

print("=== GRADER VERSION 2026-05-24-B LOADED ===", flush=True)

_COMP_NAME_MAP = {
    'コミュニケーション力': 'コミュニケーション',
    'コミュニケーション':   'コミュニケーション',
    '情報収集力':           '情報収集',
    '情報収集':             '情報収集',
    '情報分析力':           '情報分析',
    '情報分析':             '情報分析',
    '想像・先読み力':       '想像・先読み',
    '想像先読み力':         '想像・先読み',
    '想像・先読み':         '想像・先読み',
    '想像':                 '想像・先読み',
    '先読み力':             '想像・先読み',
    '先読み':               '想像・先読み',
    '計画力':               '計画',
    '計画':                 '計画',
}
_DEFAULT_COMPS = ['コミュニケーション', '情報収集', '情報分析', '想像・先読み', '計画']
_ALL_COMPS     = ['コミュニケーション', '情報収集', '情報分析', '想像・先読み', '計画']


def _extract_comps(q_text: str) -> list:
    m = _re.search(r'※評価対象\s*コンピテンシー[：:]\s*(.+?)(?:\r?\n|$)', q_text)
    if not m:
        return _DEFAULT_COMPS[:]
    ann = m.group(1).strip()
    result = []
    # 文字コードに依存しない内容ベースの判定
    if 'コミュニケーション' in ann and 'コミュニケーション' not in result:
        result.append('コミュニケーション')
    if '情報収集' in ann and '情報収集' not in result:
        result.append('情報収集')
    if '情報分析' in ann and '情報分析' not in result:
        result.append('情報分析')
    if '想像' in ann and '先読み' in ann and '想像・先読み' not in result:
        result.append('想像・先読み')
    if '計画' in ann and '計画' not in result:
        result.append('計画')
    return result if result else _DEFAULT_COMPS[:]


def _clean_q(q_text: str) -> str:
    q = _re.sub(r'※評価対象\s*コンピテンシー[：:].*', '', q_text).strip()
    q = _re.sub(r'&[a-zA-Z]+;', ' ', q)
    q = _re.sub(r'^最初に資料を読んで.*?(?=発災|以下|あなた|本社|班|現在|翌日|当日)',
                '', q, flags=_re.DOTALL).strip()
    return q


def _scene(unit_text: str) -> str:
    if not unit_text or unit_text in ('nan', 'NaN', 'None'):
        return 'その他'
    m = _re.search(r'シーン([1-3１-３一二三])', unit_text)
    if m:
        n = m.group(1).translate(str.maketrans('１２３一二三', '123123'))
        return f'シーン{n}'
    if '共通' in unit_text:
        return 'シーン1'
    return 'その他'


def is_tall_format(df) -> bool:
    """問題文と解答が同一ファイルにある縦型フォーマットかどうかを判定"""
    cols = set(df.columns)
    # 直接列名で判定
    if ('問題文' in cols and '解答' in cols):
        return True
    if ('question_text' in cols and 'answer' in cols):
        return True
    # ヒューリスティック判定:
    # 先頭列（受験者ID相当）にほぼ同じ値が繰り返されている = 縦型
    if len(df) >= 10:
        first_col = df.columns[0]
        n_unique = df[first_col].dropna().nunique()
        n_rows   = len(df.dropna(subset=[first_col]))
        # ユニーク率が25%未満 → 明らかに1行1問の縦型
        if n_rows > 0 and n_unique / n_rows < 0.25:
            return True
    return False


def _find_col(df, candidates, fallback_idx=0):
    """候補列名リストから最初に見つかった列名を返す。なければ位置インデックスで取得。"""
    for c in candidates:
        if c in df.columns:
            return c
    cols = list(df.columns)
    return cols[fallback_idx] if fallback_idx < len(cols) else cols[0]


def grade_tall_format(answers_df, column_mapping: dict, results_dir, progress_cb=None):
    """
    縦型フォーマット採点（1行 = 1問の回答、LMSエクスポート形式）
    問題文・解答が同一ファイルに含まれるため、問題ファイル不要。
    """
    import datetime as _dt
    _log_path = Path(results_dir) / "grade_debug.log"
    def _dlog(msg):
        try:
            with open(str(_log_path), 'a', encoding='utf-8') as _f:
                _f.write(f"[{_dt.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        except Exception as _e:
            print(f"[DLOG_ERR] {_e}: {msg}", flush=True)

    _selftest = _extract_comps("テスト※評価対象コンピテンシー：想像・先読み力、計画力")
    _dlog(f"SELF_TEST: {_selftest}")
    _dlog(f"grader __file__: {__file__}")

    cm = column_mapping
    # 列名が文字化けしている場合でも位置ベースでフォールバック
    a_id_col    = _find_col(answers_df, [cm.get("a_id",     "ログインID"), "loginid", "id"],       0)
    a_name_col  = _find_col(answers_df, [cm.get("a_name",   "名前"), "name"],                      1)
    a_dept_col  = _find_col(answers_df, [cm.get("a_dept",   "グループ"), "group", "dept"],          2)
    a_genre_col = _find_col(answers_df, [cm.get("a_genre",  "属性"), "genre", "class"],             3)
    q_text_col  = _find_col(answers_df, [cm.get("q_text_col", "問題文"), "question_text", "問題"],  -3)
    a_text_col  = _find_col(answers_df, [cm.get("a_text_col", "解答"), "answer", "回答"],           -1)
    unit_col    = _find_col(answers_df, [cm.get("unit_col", "ユニット"), "unit", "シーン"], 1)

    # 有効行に絞る：受験者IDと問題文が存在する行
    df = answers_df.copy()
    df = df[df[a_id_col].notna() & (df[a_id_col].astype(str).str.strip() != '')]
    df = df[df[q_text_col].notna() & (df[q_text_col].astype(str).str.strip() != '')]
    # 練習問題を除外
    if unit_col in df.columns:
        df = df[~df[unit_col].astype(str).str.contains('練習', na=True)]
    df[a_id_col] = df[a_id_col].astype(str).str.strip()

    all_results = []
    grouped = list(df.groupby(a_id_col, sort=False))
    total_persons = len(grouped)

    for person_idx, (person_id, person_df) in enumerate(grouped, 1):
        first        = person_df.iloc[0]
        person_name  = str(first[a_name_col])  if a_name_col  in first.index else person_id
        person_dept  = str(first[a_dept_col])  if a_dept_col  in first.index else ""
        person_genre = str(first[a_genre_col]) if a_genre_col in first.index else ""

        graded_answers = []
        comp_totals    = {}
        comp_max       = {}

        for idx, (_, row) in enumerate(person_df.iterrows(), 1):
            raw_q   = str(row[q_text_col])
            raw_ans = str(row[a_text_col]) if (
                a_text_col in row.index and
                str(row[a_text_col]) not in ('nan', 'NaN', 'None', '')
            ) else ""
            unit_val = str(row[unit_col]) if unit_col in row.index else ""

            # コンピテンシーと採点基準をマップから取得
            _q_comp_map   = cm.get('q_comp_map', {})
            _q_rubric_map = cm.get('q_rubric_map', {})
            if raw_q in _q_comp_map:
                comps = _q_comp_map[raw_q]
            else:
                comps = _extract_comps(raw_q)
            rubrics = _q_rubric_map.get(raw_q, {})
            _dlog(f"Q{idx:02d} comps={comps} has_rubrics={bool(rubrics)}")
            clean_q = _clean_q(raw_q)
            scene   = _scene(unit_val)

            result = grade_single(
                question_text=clean_q,
                rubrics_per_comp=rubrics,
                answer=raw_ans,
                competencies=comps,
            )

            for c in comps:
                s = result["competency_scores"].get(c, 0)
                comp_totals[c] = comp_totals.get(c, 0) + s
                comp_max[c]    = comp_max.get(c, 0) + 2

            result.update({
                "question_id":    f"Q{idx:02d}",
                "question_text":  clean_q,
                "question_type":  "記述式",
                "question_genre": scene,
                "answer_text":    raw_ans,
                "competencies":   comps,
            })
            graded_answers.append(result)

        used_comps  = [c for c in _ALL_COMPS if c in comp_totals]
        total_score = sum(comp_totals.values())
        total_max   = sum(comp_max.values())
        percentage  = round(total_score / total_max * 100, 1) if total_max > 0 else 0
        comp_rates  = {
            c: round(comp_totals[c] / comp_max[c] * 100, 1) if comp_max.get(c, 0) > 0 else 0
            for c in used_comps
        }

        all_results.append({
            "id":              person_id,
            "name":            person_name,
            "genre":           person_genre,
            "department":      person_dept,
            "total_score":     total_score,
            "total_max":       total_max,
            "percentage":      percentage,
            "certification":   get_certification(percentage),
            "comp_totals":     comp_totals,
            "comp_max":        comp_max,
            "comp_rates":      comp_rates,
            "competency_cols": used_comps,
            "answers":         graded_answers,
        })

        if progress_cb:
            progress_cb(person_idx, total_persons, person_name)

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
