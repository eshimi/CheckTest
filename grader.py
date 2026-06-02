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

【採点原則】
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

該当しない場合は forced_zero: false、forced_zero_reason: \"\" とする。

【採点解釈ルール（採点基準の読み方）】
採点基準に記載された要件を判断する際は、以下のルールに従うこと。
各ルールは独立して適用され、下位のルールが上位のルールを上書きしない。

■ ルール1：施設名・組織名の固有名詞は必須としない
採点基準に「本社（大手町プレイス）」「特定の拠点名」などが例示されていても、
概念として同等の内容（例：「電源確保できる場所への移動」）が書かれていれば要件を満たす。
固有名詞の不記載のみを理由に減点してはならない。

■ ルール2：「今後の見通し」には時間軸情報も含む
採点基準で「今後の見通し」「状況が悪化するのか改善するのか」の情報収集が求められている場合、
燃料枯渇想定時間・補給手配の見込み時間・サービス断までの残り時間・復旧見込み時間など
時間軸のある将来予測情報の収集も「今後の見通しの情報収集」として3点要件を満たす。

■ ルール3：計画コンピテンシー／本質的目的との合致を優先する
計画の3点要件に特定の組織名・リスク名（例：「NTT東日本と連携」「両系断」）が記載されていても、
回答の計画内容がその本質的な目的（通信断リスクの予防・冗長化・体制整備）に明確に合致していれば
3点と判定する。組織名・リスク名の文言が明示されていないことのみを理由に2点以下にしてはならない。
採点基準の注記に「〜との連携ではないが、〜の対策がとられている→3点」等の形で別経路での3点達成が
明示されている場合は、その注記通りに採点すること（→ルール8も参照）。

■ ルール4：問題文の核心的要素への完全な無言及は0点
問題文に明示された核心的な情報・状況（特異な視覚情報、重要な警告等）に一切言及していない回答は、
その情報を評価するコンピテンシーを0点とする。
例：問題文に「遠くでオレンジに光っている（火災の可能性）」が示されているのに
  情報分析の回答でそれに全く触れていない場合は情報分析0点。

■ ルール5：付随的な言及は2点以上の根拠にならない
ある点数の要件に対する言及が、回答全体の中で一文以下の補足的・付随的な記述にとどまり、
回答の主軸的な内容となっていない場合は1点留まりとし、2点以上を与えない。
例：「バッテリーが許す限り報告する」程度の一言は先読みの主軸的な記述ではなく、
  2点要件（想定を行動に結びつけている）の根拠にはならない。

■ ルール6：情報収集の3点には予測的・先手先手の収集が必要
採点基準に「先手先手」「今後の見通し」が3点要件として記載されている場合、
問題発覚後の原因確認・状況把握（事後的・反応的な収集）は2点以下とする。
3点には、問題の今後の展開を予測した上で先回りして情報を取りにいく行動が必要。
※ただしルール2（時間軸情報）は本ルールより優先する。

■ ルール7：「想像・先読み」では確認行為と想像行為を厳密に区別する
「想像・先読み」コンピテンシーの評価対象は「想像・推測・洞察の記述」のみ。
「原因を確認する」「件数を確認する」等の確認指示は情報収集コンピテンシーで評価し、
想像・先読みとしてカウントしない。
以下の場合は想像・先読みを0点とする：
・回答に想像・推測を示す記述（「〜が想定される」「〜の可能性がある」「〜が起きるだろう」等）が
  一切なく、既存ツールの活用・管理シートのフラグ変更・優先度調整のみを述べている場合

■ ルール8：採点基準の採点例・注記は採点基準本文と同等の効力を持つ
採点基準に「→X点」「〜ではあるがX点」「〜の場合はX点」等の採点例・注記・コメントが
記載されている場合、その内容を採点基準本文として扱い最優先で適用すること。
採点例に該当する回答にはその点数を付与しなければならない。
採点例と一致するにもかかわらず「より詳細な記述があれば」「一部の要素が足りない」等の
理由で点数を下げることは禁止。

■ ルール9：採点基準の要素列挙に対する合致判定
採点基準の点数要件として具体的要素が列挙されている場合
（例：「移動手段、移動時間、必要備品準備、移動ルートの確認、ルート選定など」）、
回答にこれらの要素の大部分が含まれていれば点数要件を満たすと判定する。
「全要素が一語一句明示されていない」「もう少し詳細があれば」という理由のみで
点数要件を満たさないと判定してはならない。
「など」で終わる列挙は例示であり、列挙された項目がすべて必須要件ではないことに注意する。

■ 網羅性不足のみを理由とした減点は行わない（上記ルール1〜9が適用されない場合）
上記ルール1〜9が適用されない場合に限り、「理想的な回答と比べて不足している要素がある」
だけでは減点の根拠にならない。"""


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


# ── シーン内クロス評価（2パス目） ────────────────────────────────────────────

REVIEW_SYSTEM_PROMPT = """あなたは防災・危機管理分野の専門家であり、公正な試験採点者です。
同一シーン内の複数問題に対する受験者の回答全体を俯瞰し、スコアの見直しを行います。
必ずJSON形式のみで回答してください（説明文不要）。

【クロス評価の目的】
1問ずつの独立採点では「その問題に書いていないが、別の問題で明確に書いている」ことが評価されない場合がある。
同シーン内の別問題の回答に、採点基準が求める内容が具体的に記述されている場合のみ格上げを行う。

【格上げの条件（すべて満たす場合のみ格上げ）】
① 別の問題の回答に、該当問題の採点基準が求める内容・行動が具体的な言葉で書かれている
② 「意識がある」「姿勢が読み取れる」「推測できる」だけでは格上げしない。別問題の回答に明示的な記述が存在すること
③ 採点基準に特定の対象・行為が指定されている場合（例：「火災について」「総務省に対して国の対応状況を」）、その対象・行為が別問題の回答に明記されていること

【格上げしてはいけない場合】
- 0点の問題：採点基準の最低要件（1点相当の内容）が別問題の回答に明示されている場合のみ格上げ可。「一般的な注意深さ」や「全体的な意識の高さ」を根拠に0点から格上げしない
- 確認行為・既存ツールの活用のみの記述：「原因を確認する」「管理シートのフラグを変更する」等は想像・先読みコンピテンシーの格上げ根拠にならない
- 間接的・付随的な言及：「〜かもしれない」「余裕があれば〜」等の一文以下の付随的記述は格上げ根拠にならない
- 格上げ対象問題自身の回答を根拠とした格上げ禁止：格上げの根拠は必ず「格上げ対象とは異なる別の問題の回答」であること。例えば「シーン1 問8」を格上げする場合、根拠は「シーン1 問8」以外の問題の回答でなければならない。同一問題の回答内容を、その問題自身の格上げ根拠に使うことは禁止
- 未来の問題の回答を根拠とした格上げ禁止：問題は時系列順に並んでいる。「シーン3 問2」を格上げする場合、根拠として使えるのは「シーン3 問1」以前の回答のみ。「シーン3 問3」「シーン3 問4」など格上げ対象より後（番号が大きい）の問題の回答を格上げ根拠にしてはならない

【格上げのルール】
- 格上げは最大1点（例：1点→2点、2点→3点）
- 強制0点（forced_zero=true）の問題は格上げしない
- 条件を満たさない場合は格上げしない
- 見直しが不要な場合のみ upgrades を空リストにする"""


def build_review_prompt(scene_name: str, graded_scene_questions: list) -> str:
    """シーン内の全問題・回答・初期スコアを渡してクロス評価を依頼するプロンプトを構築"""
    blocks = []
    for i, gq in enumerate(graded_scene_questions, 1):
        # _display_label があればそちらを使用（例：「シーン1 問8」）
        q_id = gq.get("_display_label", gq.get("question_id", f"Q{i}"))
        q_text = gq.get("question_text", "")
        answer = gq.get("answer_text", "（無回答）")
        comps = gq.get("competencies", [])
        scores = gq.get("competency_scores", {})
        rubrics = gq.get("_rubrics", {})
        forced = gq.get("forced_zero", False)

        score_str = ", ".join(f"{c}:{scores.get(c, 0)}点" for c in comps)
        rubric_str = "\n".join(f"  【{c}】{rubrics.get(c, '')}" for c in comps if rubrics.get(c))
        forced_str = "　※強制0点" if forced else ""

        blocks.append(
            f"--- {q_id}{forced_str} ---\n"
            f"【問題】{q_text}\n"
            f"【回答】{answer}\n"
            f"【採点基準】\n{rubric_str}\n"
            f"【現在のスコア】{score_str}"
        )

    upgrade_keys = '[\n    {"question_id": "<問題の表示名（例：シーン1 問3）>", "competency": "<コンピテンシー名>", "old_score": <旧スコア>, "new_score": <新スコア>, "reason": "<格上げ理由（格上げ対象とは別のどの問題の回答が根拠か、具体的に記述）>"}\n  ]'

    return f"""以下は「{scene_name}」における受験者の全回答と初期採点スコアです。
受験者はシーン全体を通じて回答しています。ある問題で低得点のコンピテンシーがあっても、
同シーン内の別問題の回答にその行動・考え方が示されていれば、格上げを検討してください。

特に注目すること：
- スコアが1点以下のコンピテンシーに対して、他の問題の回答にその要件を満たす記述がないか確認する
- 格上げの根拠は必ず「格上げ対象とは異なる別の問題の回答」であること

{chr(10).join(blocks)}

以下のJSON形式のみで回答してください：
{{
  "upgrades": {upgrade_keys}
}}

格上げ不要な場合のみ： {{"upgrades": []}}"""


def review_scene(scene_name: str, graded_scene_questions: list) -> dict:
    """
    シーン内の全問題を俯瞰して格上げが必要なスコアを返す。
    Returns: {(question_id, competency): {"new_score": int, "reason": str}}
    """
    if len(graded_scene_questions) < 2:
        return {}
    # 強制0点のみのシーンはスキップ
    non_zero = [gq for gq in graded_scene_questions if not gq.get("forced_zero", False)]
    if not non_zero:
        return {}

    # シーン内表示番号を付与（例：「シーン1 問8」）し、元のIDへの逆引きマップを作成
    label_to_qid = {}
    for i, gq in enumerate(graded_scene_questions, 1):
        display = f"{scene_name} 問{i}"
        gq["_display_label"] = display
        label_to_qid[display] = gq.get("question_id", f"Q{i:02d}")

    prompt = build_review_prompt(scene_name, graded_scene_questions)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        temperature=0,
        system=[{"type": "text", "text": REVIEW_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    brace_start = raw.find('{')
    if brace_start == -1:
        return {}
    try:
        result, _ = json.JSONDecoder().raw_decode(raw, brace_start)
    except json.JSONDecodeError:
        return {}

    upgrades = {}
    for u in result.get("upgrades", []):
        try:
            ai_label = u["question_id"]
            # 表示ラベル（例：「シーン1 問8」）を元の question_id にマップバック
            q_id = label_to_qid.get(ai_label, ai_label)
            comp = _COMP_NAME_MAP.get(u["competency"].strip(), u["competency"].strip())
            old_s = int(u["old_score"])
            new_s = int(u["new_score"])
            if new_s > old_s and new_s - old_s <= 1 and new_s <= 3:
                upgrades[(q_id, comp)] = {
                    "new_score": new_s,
                    "reason": u.get("reason", ""),
                }
        except (KeyError, ValueError, TypeError):
            continue
    return upgrades


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


def grade_exam_group_based(group_questions: dict, answers_df, column_mapping: dict, results_dir, progress_cb=None):
    """
    group_questions: {班名: [{seq, label, text, active_comps, rubrics, ...}]}
    answers_df: 受験者回答DataFrame（Q01〜Q22列 + 受験者ID/氏名/班名/所属）
    """
    import datetime as _dt
    _log_path = Path(results_dir) / "grade_debug.log"
    def _dlog(msg):
        try:
            with open(str(_log_path), 'a', encoding='utf-8') as _f:
                _f.write(f"[{_dt.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        except Exception:
            pass

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

    # 個別保存ディレクトリ（クラッシュ対策・再開用）
    individual_dir = Path(results_dir) / "individual"
    individual_dir.mkdir(parents=True, exist_ok=True)

    all_results = []
    rows_list = list(answers_df.iterrows())
    total_persons = len(rows_list)

    for person_idx, (_, a_row) in enumerate(rows_list, 1):
        examinee_id    = str(a_row[a_id_col])
        examinee_name  = str(a_row[a_name_col])
        examinee_genre = str(a_row[a_genre_col]).strip() if a_genre_col and a_genre_col in a_row.index else ""
        examinee_dept  = str(a_row[a_dept_col]).strip() if a_dept_col and a_dept_col in a_row.index else ""

        # 採点済みチェック（再開時はスキップ）
        safe_id = examinee_id.replace('/', '_').replace('\\', '_').replace(':', '_')
        individual_path = individual_dir / f"{safe_id}.json"
        if individual_path.exists():
            with open(individual_path, encoding='utf-8') as _f:
                cached = json.load(_f)
            all_results.append(cached)
            if progress_cb:
                progress_cb(person_idx, total_persons, examinee_name + "（採点済・スキップ）")
            continue

        # この人の班の問題セットを取得
        questions = group_questions.get(examinee_genre)
        if not questions:
            # 部分一致でフォールバック
            questions = next((v for k, v in group_questions.items() if examinee_genre in k or k in examinee_genre), None)
        if not questions:
            continue  # 班が不明なのでスキップ

        graded_answers = []

        # ── パス1：1問ずつ独立採点 ────────────────────────────────────────
        scene_buckets = {}  # {scene_name: [graded_result, ...]}
        for q in questions:
            seq_label = f"Q{q['seq']:02d}"
            answer_text = str(a_row.get(seq_label, ''))
            if answer_text in ('nan', 'NaN', 'None'):
                answer_text = ''

            active = q.get('active_comps', [])
            rubrics = q.get('rubrics', {})

            if not active:
                continue

            scene_name = q.get('scene', '')
            scene_context = scenes.get(scene_name, '')
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
                "question_genre": scene_name,
                "answer_text":    answer_text,
                "competencies":   active,
                "_rubrics":       rubrics,  # クロス評価用（後で削除）
            })
            graded_answers.append(result)
            scene_buckets.setdefault(scene_name, []).append(result)

        # ── パス2：シーン内クロス評価（別問題の回答で格上げ） ─────────────
        for scene_name, scene_qs in scene_buckets.items():
            _dlog(f"PASS2 START: {scene_name} ({len(scene_qs)}問)")
            upgrades = review_scene(scene_name, scene_qs)
            _dlog(f"PASS2 RESULT: {scene_name} → 格上げ{len(upgrades)}件: {list(upgrades.keys())}")
            for (q_id, comp), upg in upgrades.items():
                for ga in graded_answers:
                    if ga["question_id"] == q_id and comp in ga.get("competency_scores", {}):
                        old_s = ga["competency_scores"][comp]
                        new_s = upg["new_score"]
                        if new_s > old_s:
                            ga["competency_scores"][comp] = new_s
                            # 採点理由に格上げ注記を追加
                            old_reason = ga.get("competency_reasons", {}).get(comp, "")
                            ga.setdefault("competency_reasons", {})[comp] = (
                                old_reason + f"　※シーン内別問題の回答を考慮して{old_s}点→{new_s}点に格上げ（{upg['reason']}）"
                            )
                            _dlog(f"  UPGRADE: {q_id} {comp} {old_s}→{new_s}")

        # _rubrics / _display_label はAPIレスポンス用途外なので削除
        for ga in graded_answers:
            ga.pop("_rubrics", None)
            ga.pop("_display_label", None)

        # ── 集計 ─────────────────────────────────────────────────────────
        comp_totals = {c: 0 for c in comp_cols}
        comp_max    = {c: 0 for c in comp_cols}
        for ga in graded_answers:
            for c, s in ga["competency_scores"].items():
                comp_totals[c] = comp_totals.get(c, 0) + s
                comp_max[c]    = comp_max.get(c, 0) + 2

        total_score = sum(comp_totals.values())
        total_max   = sum(comp_max.values())
        percentage  = round(total_score / total_max * 100, 1) if total_max > 0 else 0
        comp_rates  = {
            c: round(comp_totals[c] / comp_max[c] * 100, 1) if comp_max[c] > 0 else 0
            for c in comp_cols
        }

        person_result = {
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
        }
        # 1人完了ごとに個別ファイルへ即時保存
        with open(individual_path, 'w', encoding='utf-8') as _f:
            json.dump(person_result, _f, ensure_ascii=False, indent=2)

        all_results.append(person_result)

        if progress_cb:
            progress_cb(person_idx, total_persons, examinee_name)

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

print("=== GRADER VERSION 2026-06-02-C LOADED ===", flush=True)

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

    # 個別保存ディレクトリ（クラッシュ対策・再開用）
    individual_dir = Path(results_dir) / "individual"
    individual_dir.mkdir(parents=True, exist_ok=True)

    all_results = []
    grouped = list(df.groupby(a_id_col, sort=False))
    total_persons = len(grouped)

    for person_idx, (person_id, person_df) in enumerate(grouped, 1):
        first        = person_df.iloc[0]
        person_name  = str(first[a_name_col])  if a_name_col  in first.index else person_id
        person_dept  = str(first[a_dept_col])  if a_dept_col  in first.index else ""
        person_genre = str(first[a_genre_col]) if a_genre_col in first.index else ""

        # 採点済みチェック（再開時はスキップ）
        safe_id = str(person_id).replace('/', '_').replace('\\', '_').replace(':', '_')
        individual_path = individual_dir / f"{safe_id}.json"
        if individual_path.exists():
            with open(individual_path, encoding='utf-8') as _f:
                cached = json.load(_f)
            all_results.append(cached)
            _dlog(f"SKIP (already graded): {person_name}")
            if progress_cb:
                progress_cb(person_idx, total_persons, person_name + "（採点済・スキップ）")
            continue

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
                "_rubrics":       rubrics,
            })
            graded_answers.append(result)

        # ── パス2：シーン内クロス評価（別問題の回答で格上げ） ─────────────
        scene_buckets_lms = {}
        for ga in graded_answers:
            sn = ga.get("question_genre", "")
            if sn:
                scene_buckets_lms.setdefault(sn, []).append(ga)

        for scene_name, scene_qs in scene_buckets_lms.items():
            _dlog(f"PASS2 START: {scene_name} ({len(scene_qs)}問)")
            upgrades = review_scene(scene_name, scene_qs)
            _dlog(f"PASS2 RESULT: {scene_name} → 格上げ{len(upgrades)}件: {list(upgrades.keys())}")
            for (q_id, comp), upg in upgrades.items():
                for ga in graded_answers:
                    if ga["question_id"] == q_id and comp in ga.get("competency_scores", {}):
                        old_s = ga["competency_scores"][comp]
                        new_s = upg["new_score"]
                        if new_s > old_s:
                            ga["competency_scores"][comp] = new_s
                            old_reason = ga.get("competency_reasons", {}).get(comp, "")
                            ga.setdefault("competency_reasons", {})[comp] = (
                                old_reason + f"　※シーン内別問題の回答を考慮して{old_s}点→{new_s}点に格上げ（{upg['reason']}）"
                            )
                            _dlog(f"  UPGRADE: {q_id} {comp} {old_s}→{new_s}")

        # _rubrics / _display_label 削除・comp_totals 再集計（格上げ反映）
        comp_totals = {}
        for ga in graded_answers:
            ga.pop("_rubrics", None)
            ga.pop("_display_label", None)
            for c, s in ga["competency_scores"].items():
                if c in comp_max:
                    comp_totals[c] = comp_totals.get(c, 0) + s

        used_comps  = [c for c in _ALL_COMPS if c in comp_totals]
        total_score = sum(comp_totals.values())
        total_max   = sum(comp_max.values())
        percentage  = round(total_score / total_max * 100, 1) if total_max > 0 else 0
        comp_rates  = {
            c: round(comp_totals[c] / comp_max[c] * 100, 1) if comp_max.get(c, 0) > 0 else 0
            for c in used_comps
        }

        person_result = {
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
        }
        # 1人完了ごとに個別ファイルへ即時保存
        with open(individual_path, 'w', encoding='utf-8') as _f:
            json.dump(person_result, _f, ensure_ascii=False, indent=2)
        _dlog(f"SAVED individual: {person_name} -> {individual_path.name}")

        all_results.append(person_result)

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
