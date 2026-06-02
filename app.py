import io
import os
import json
import glob as _glob

# grader.py のバイトコードキャッシュを起動時に削除する（古い .pyc が使われるのを防ぐ）
for _pyc in _glob.glob(os.path.join(os.path.dirname(__file__), "__pycache__", "grader.cpython-*.pyc")):
    os.remove(_pyc)

import uuid
import datetime
import zoneinfo
_JST = zoneinfo.ZoneInfo("Asia/Tokyo")
import base64
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, Response
from werkzeug.utils import secure_filename
import pandas as pd
from grader import grade_exam, grade_exam_group_based, grade_tall_format, is_tall_format
from report_generator import generate_word_report
from playwright.sync_api import sync_playwright as _sync_playwright
import threading
from pypdf import PdfReader as _PdfReader, PdfWriter as _PdfWriter
from pypdf.generic import ArrayObject, FloatObject, NameObject, NullObject

# Playwright Sync APIはスレッドローカルで保持する必要がある
_pw_local = threading.local()

def _get_pw_browser():
    """呼び出しスレッドごとにPlaywright+Chromiumを起動・再利用する"""
    try:
        if not getattr(_pw_local, "instance", None):
            _pw_local.instance = _sync_playwright().start()
            _pw_local.browser  = _pw_local.instance.chromium.launch()
        elif not _pw_local.browser.is_connected():
            _pw_local.browser = _pw_local.instance.chromium.launch()
        return _pw_local.browser
    except Exception:
        # 壊れていたらリセットして再起動
        try: _pw_local.instance.stop()
        except Exception: pass
        _pw_local.instance = _sync_playwright().start()
        _pw_local.browser  = _pw_local.instance.chromium.launch()
        return _pw_local.browser

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "bousai-grader-2026")

# ── Basic認証 ────────────────────────────────────────────────────────────────
_BASIC_USER = os.environ.get("BASIC_AUTH_USERNAME", "admin")
_BASIC_PASS = os.environ.get("BASIC_AUTH_PASSWORD", "password")

@app.before_request
def basic_auth():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            if username == _BASIC_USER and password == _BASIC_PASS:
                return
        except Exception:
            pass
    return Response(
        "Authentication required",
        401,
        {"WWW-Authenticate": 'Basic realm="Login Required"'},
    )

def _mask_id(s):
    """ログインIDの中間部分をアスタリスクで伏字にする（先頭3文字＋末尾2文字を残す）"""
    s = str(s)
    if len(s) <= 5:
        return s[0] + '*' * (len(s) - 1)
    return s[:3] + '*' * (len(s) - 5) + s[-2:]

def _mask_id_scattered(s):
    """IDの一部の文字をランダムに見える形で伏字にする（先頭2・末尾1は残す、残りを散らばらせてマスク）"""
    s = str(s)
    if len(s) <= 3:
        return s[0] + '*' * (len(s) - 1)
    result = []
    for i, c in enumerate(s):
        if i < 2 or i == len(s) - 1:
            result.append(c)
        elif (ord(c) * 3 + i * 7) % 3 == 0:
            result.append('*')
        else:
            result.append(c)
    return ''.join(result)

@app.template_filter("mask_id")
def mask_id_filter(s):
    return _mask_id(s)

@app.template_filter("mask_id_scattered")
def mask_id_scattered_filter(s):
    return _mask_id_scattered(s)

@app.template_filter("strip_comp_note")
def strip_comp_note(text):
    """問題文末尾の '※評価対象コンピテンシー：...' を除去"""
    if not text:
        return text
    for marker in ["※評価対象コンピテンシー", "※評価対象　コンピテンシー"]:
        idx = text.find(marker)
        if idx != -1:
            return text[:idx].rstrip()
    return text

BASE_DIR = Path(__file__).parent
# Render Disk が /data にマウントされている場合はそちらを使用（永続化）
# ローカル環境では従来通り BASE_DIR 以下を使用
_DISK_ROOT = Path("/data")
_USE_DISK  = _DISK_ROOT.exists() and _DISK_ROOT.is_dir()
UPLOAD_DIR  = (_DISK_ROOT / "uploads")  if _USE_DISK else (BASE_DIR / "uploads")
RESULTS_DIR = (_DISK_ROOT / "results")  if _USE_DISK else (BASE_DIR / "results")
EXAMS_DIR   = BASE_DIR / "exams"  # 試験定義はコードと一緒に管理
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}

for d in [UPLOAD_DIR, RESULTS_DIR, EXAMS_DIR]:
    d.mkdir(exist_ok=True)


def allowed_file(filename):
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def _clean_columns(df):
    """列名に含まれる Excel XML エスケープ（_x00XX_）や制御文字を除去して正規化する"""
    import re
    def clean(name):
        s = str(name)
        s = re.sub(r'_x[0-9a-fA-F]{4}_', '', s)   # _x0011_ 等を除去
        s = re.sub(r'[\x00-\x1f\x7f]', '', s)       # 残った制御文字を除去
        return s.strip()
    df.columns = [clean(c) for c in df.columns]
    return df


def _is_sane_df(df) -> bool:
    """DataFrameが文字化けしていないかチェックする。
    バイナリをCSVとして読んだ場合は列名に制御文字が混入するため検出できる。
    日本語列名（ひらがな・カタカナ・漢字）は正当なものとして許可する。
    """
    if df is None or df.empty or len(df.columns) == 0:
        return False
    for col in df.columns:
        s = str(col)
        # 制御文字（タブ・改行・復帰以外）が1文字でもあれば文字化け
        if any(ord(c) < 0x20 and c not in '\t\n\r' for c in s):
            return False
        # 非ASCII文字が多い場合、日本語文字（ひらがな・カタカナ・漢字・記号）かを確認
        non_ascii_chars = [c for c in s if ord(c) > 0x7E]
        if len(s) > 3 and len(non_ascii_chars) / len(s) > 0.8:
            # 日本語Unicodeレンジ: U+3000-U+9FFF（ひらがな/カタカナ/漢字）
            #                      U+FF00-U+FFEF（全角英数・半角カタカナ）
            #                      U+F900-U+FAFF（CJK互換漢字）
            jp_count = sum(1 for c in non_ascii_chars if
                           0x3000 <= ord(c) <= 0x9FFF or
                           0xFF00 <= ord(c) <= 0xFFEF or
                           0xF900 <= ord(c) <= 0xFAFF)
            if len(non_ascii_chars) > 0 and jp_count / len(non_ascii_chars) < 0.5:
                # 非ASCII文字の半分未満しか日本語でない → バイナリ起因の文字化け
                return False
    return True


def load_excel(filepath):
    """
    あらゆる形式の表形式ファイルを読み込む。
    拡張子に依存せず複数パーサーを順番に試し、文字化けチェックを通過したものを返す。
    対応形式: xlsx / xls / HTML偽装xls（LMS特有）/ CSV / TSV
    """
    import csv as _csv
    fp = Path(filepath)
    errors = []

    # ファイル先頭バイトで形式を推定（ヒントとして使用）
    try:
        with open(fp, "rb") as f:
            magic = f.read(4)
    except Exception:
        magic = b""
    is_binary = magic[:4] in (b"\xd0\xcf\x11\xe0", b"PK\x03\x04")

    # ① xlsx（openpyxl）
    try:
        df = pd.read_excel(fp, engine="openpyxl")
        if _is_sane_df(df):
            return _clean_columns(df)
        errors.append("openpyxl: 読めたが文字化け")
    except Exception as e:
        errors.append(f"openpyxl: {e}")

    # ② xls バイナリ（xlrd）
    try:
        df = pd.read_excel(fp, engine="xlrd")
        if _is_sane_df(df):
            return _clean_columns(df)
        errors.append("xlrd: 読めたが文字化け")
    except Exception as e:
        errors.append(f"xlrd: {e}")

    # ③ HTML形式の"偽装xls"（LMSがHTML tableをxlsとして出力するケース）
    # lxmlがバイト型エンコーディングを返すバグを避けるため、自分でデコードしてStringIOで渡す
    try:
        raw_bytes = fp.read_bytes()
    except Exception:
        raw_bytes = None

    if raw_bytes:
        for enc in ("utf-8-sig", "cp932", "shift_jis", "utf-8"):
            try:
                decoded = raw_bytes.decode(enc)
                tables = pd.read_html(io.StringIO(decoded), flavor="lxml")
                if tables and _is_sane_df(tables[0]):
                    return _clean_columns(tables[0])
            except Exception as e:
                errors.append(f"html({enc}): {e}")

    # バイナリファイルでここまで全滅 → CSVではないので明確にエラー
    if is_binary:
        raise ValueError(
            "Excelファイルの読み込みに失敗しました。\n"
            "LMSのエクスポート画面で「CSV（カンマ区切り）」か「xlsx形式」を選択し直してください。\n"
            f"（試行結果: {' | '.join(errors[-3:])}）"
        )

    # ④ CSV / TSV（テキスト系ファイル）
    import chardet
    raw = fp.read_bytes()
    detected = chardet.detect(raw)
    enc_detected = detected.get("encoding") or "cp932"
    candidates = [enc_detected, "utf-8-sig", "cp932", "shift_jis", "utf-8", "latin-1"]
    seen = set()
    for enc in candidates:
        if enc in seen:
            continue
        seen.add(enc)
        for kwargs in [
            {"sep": None, "engine": "python"},
            {"sep": None, "engine": "python",
             "quoting": _csv.QUOTE_NONE, "escapechar": "\\", "on_bad_lines": "skip"},
        ]:
            try:
                df = pd.read_csv(fp, encoding=enc, **kwargs)
                if _is_sane_df(df):
                    return _clean_columns(df)
                errors.append(f"csv({enc}): 読めたが文字化け")
            except (UnicodeDecodeError, ValueError, _csv.Error) as e:
                errors.append(f"csv({enc}): {e}")

    raise ValueError(
        "ファイル形式を認識できませんでした。\n"
        "xlsx / xls / CSV形式でエクスポートし直してください。\n"
        f"詳細: {' | '.join(errors[-4:])}"
    )


def list_exams():
    exams = []
    for meta_path in sorted(EXAMS_DIR.glob("*/meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        with open(meta_path, encoding="utf-8") as f:
            exams.append(json.load(f))
    return exams


# ── トップ（採点開始） ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    exams = list_exams()
    return render_template("index.html", exams=exams)


# ── 試験登録 ──────────────────────────────────────────────────────────────────

@app.route("/exam/new")
def exam_new():
    return render_template("exam_new.html")


@app.route("/exam/register", methods=["POST"])
def exam_register():
    """問題・採点基準ファイルを受け取り、試験設定として保存する"""
    exam_name = request.form.get("exam_name", "").strip()
    if not exam_name:
        return jsonify({"error": "試験名を入力してください"}), 400

    if "questions_file" not in request.files:
        return jsonify({"error": "問題ファイルをアップロードしてください"}), 400

    q_file = request.files["questions_file"]
    if not q_file.filename or not allowed_file(q_file.filename):
        return jsonify({"error": "Excel(.xlsx/.xls)またはCSV形式のファイルを選択してください"}), 400

    exam_id = str(uuid.uuid4())
    exam_dir = EXAMS_DIR / exam_id
    exam_dir.mkdir()

    ext = Path(q_file.filename).suffix
    q_path = exam_dir / f"questions{ext}"
    q_file.save(str(q_path))

    try:
        df = load_excel(q_path)
        columns = list(df.columns)
        meta = {
            "exam_id": exam_id,
            "name": exam_name,
            "created_at": datetime.date.today().strftime("%Y-%m-%d"),
            "questions_count": len(df),
            "columns": columns,
            "column_mapping": {},   # confirmed later via /exam/confirm_mapping
            "file_ext": ext,
        }
        with open(exam_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        return jsonify({
            "exam_id": exam_id,
            "exam_name": exam_name,
            "questions_count": len(df),
            "columns": columns,
        })
    except Exception as e:
        return jsonify({"error": f"ファイルの読み込みに失敗しました: {str(e)}"}), 400


@app.route("/exam/confirm_mapping", methods=["POST"])
def exam_confirm_mapping():
    """列マッピングを確定して試験設定を完成させる"""
    data = request.get_json()
    exam_id = data.get("exam_id")
    column_mapping = data.get("column_mapping", {})

    meta_path = EXAMS_DIR / exam_id / "meta.json"
    if not meta_path.exists():
        return jsonify({"error": "試験設定が見つかりません"}), 404

    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    meta["column_mapping"] = column_mapping
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return jsonify({"ok": True, "exam_id": exam_id})


@app.route("/exam/list")
def exam_list_page():
    exams = list_exams()
    return render_template("exam_list.html", exams=exams)


@app.route("/exam/<exam_id>/delete", methods=["POST"])
def exam_delete(exam_id):
    import shutil
    exam_dir = EXAMS_DIR / exam_id
    if exam_dir.exists():
        shutil.rmtree(exam_dir)
    return redirect(url_for("exam_list_page"))


# ── 採点（回答ファイルのみアップロード） ────────────────────────────────────────

@app.route("/upload", methods=["POST"])
def upload():
    """
    2モード対応:
      - exam_id あり → 事前登録した問題を使用、回答ファイルのみ受け取る
      - exam_id なし → 問題・回答ファイルを両方受け取る（従来動作）
    """
    exam_id = request.form.get("exam_id", "").strip()
    a_file = request.files.get("answers_file")

    if not a_file or not a_file.filename:
        return jsonify({"error": "回答ファイルが選択されていません"}), 400
    if not allowed_file(a_file.filename):
        return jsonify({"error": "Excel(.xlsx/.xls)またはCSV形式のファイルのみ対応しています"}), 400

    session_id = str(uuid.uuid4())
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True)

    a_ext = Path(a_file.filename).suffix
    a_path = session_dir / f"answers{a_ext}"
    a_file.save(str(a_path))

    try:
        answers_df = load_excel(a_path)
        a_columns = list(answers_df.columns)

        # 縦型フォーマット（LMSエクスポート形式）の判定
        if is_tall_format(answers_df):
            examinees_count = answers_df["ログインID"].dropna().nunique() \
                if "ログインID" in answers_df.columns else "?"
            # 練習問題を除外した有効問題数
            q_col = "問題文" if "問題文" in answers_df.columns else answers_df.columns[0]
            valid_df = answers_df[answers_df[q_col].notna()]
            if "ユニット" in valid_df.columns:
                valid_df = valid_df[~valid_df["ユニット"].astype(str).str.contains("練習", na=True)]
            q_per_person = len(valid_df) // max(examinees_count, 1) if isinstance(examinees_count, int) else "?"
            return jsonify({
                "session_id":       session_id,
                "format":           "tall",
                "examinees_count":  examinees_count,
                "questions_count":  q_per_person,
                "a_columns":        a_columns,
                "column_mapping": {
                    "a_id":      "ログインID",
                    "a_name":    "名前",
                    "a_dept":    "グループ",
                    "a_genre":   "属性",
                    "q_text_col":"問題文",
                    "a_text_col":"解答",
                    "unit_col":  "ユニット",
                },
            })

        if exam_id:
            # 事前登録モード
            meta_path = EXAMS_DIR / exam_id / "meta.json"
            if not meta_path.exists():
                return jsonify({"error": "指定された試験設定が見つかりません"}), 404
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            # セッションに exam_id を紐付け
            with open(session_dir / "exam_ref.json", "w", encoding="utf-8") as f:
                json.dump({"exam_id": exam_id}, f)
            return jsonify({
                "session_id": session_id,
                "mode": "preset",
                "exam_name": meta["name"],
                "questions_count": meta["questions_count"],
                "examinees_count": len(answers_df),
                "q_columns": meta["columns"],
                "a_columns": a_columns,
                "column_mapping": meta.get("column_mapping", {}),
            })
        else:
            # 両ファイルモード
            q_file = request.files.get("questions_file")
            if not q_file or not q_file.filename:
                return jsonify({"error": "問題ファイルが選択されていません"}), 400
            q_ext = Path(q_file.filename).suffix
            q_path = session_dir / f"questions{q_ext}"
            q_file.save(str(q_path))
            questions_df = load_excel(q_path)
            return jsonify({
                "session_id": session_id,
                "mode": "manual",
                "questions_count": len(questions_df),
                "examinees_count": len(answers_df),
                "q_columns": list(questions_df.columns),
                "a_columns": a_columns,
                "column_mapping": {},
            })
    except Exception as e:
        return jsonify({"error": f"ファイルの読み込みに失敗しました: {str(e)}"}), 400


@app.route("/grade", methods=["POST"])
def grade():
    print("[GRADE] called", flush=True)
    data = request.get_json()
    session_id = data.get("session_id")
    print(f"[GRADE] session_id={session_id}", flush=True)
    column_mapping = data.get("column_mapping", {})

    if not session_id:
        return jsonify({"error": "セッションIDが不正です"}), 400

    session_dir = UPLOAD_DIR / session_id
    a_files = list(session_dir.glob("answers.*"))
    if not a_files:
        return jsonify({"error": "回答ファイルが見つかりません"}), 404

    answers_df = load_excel(a_files[0])

    # 縦型フォーマット（LMSエクスポート）はバックグラウンドで採点
    if is_tall_format(answers_df):
        merged_mapping = column_mapping or {
            "a_id": "ログインID", "a_name": "名前",
            "a_dept": "グループ", "a_genre": "属性",
            "q_text_col": "問題文", "a_text_col": "解答", "unit_col": "ユニット",
        }

        # group_questions.json が存在する場合、ユニット+出題順でcomp/rubricマップを構築
        import re as _re, unicodedata as _ud

        def _nfkc(s):
            return _ud.normalize('NFKC', s)

        def _nfkc_keys(d):
            return {_nfkc(k): v for k, v in d.items()}

        # 最新の group_questions.json を探す
        gq_paths = sorted(EXAMS_DIR.glob("*/group_questions.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        q_comp_map, q_rubric_map = {}, {}
        if gq_paths:
            with open(gq_paths[0], encoding="utf-8") as _f:
                _gq = json.load(_f)

            # インデックス: (group_key, scene, no文字列) → (comps, rubrics)
            _pos_index = {}
            for _grp_key, _qs in _gq.items():
                for _q in _qs:
                    _pk = (_grp_key, _q['scene'], str(_q['no']))
                    _pos_index[_pk] = (
                        [_nfkc(c) for c in _q.get('active_comps', [])],
                        _nfkc_keys(_q.get('rubrics', {}))
                    )

            def _grp_from_unit(unit_str):
                """ユニット文字列 → JSONグループキー（例: '10情報統括'）"""
                for _k in _gq.keys():
                    if _k in unit_str:
                        return _k
                return None

            def _scene_from_unit(unit_str):
                m = _re.search(r'シーン([1-3])', unit_str)
                return f'シーン{m.group(1)}' if m else None

            q_text_col = merged_mapping.get('q_text_col', '問題文')
            unit_col_k = merged_mapping.get('unit_col', 'ユニット')

            if q_text_col in answers_df.columns and unit_col_k in answers_df.columns:
                _seen = set()
                for _, _row in answers_df.dropna(subset=[q_text_col]).iterrows():
                    _raw_q = str(_row[q_text_col])
                    if _raw_q in _seen:
                        continue
                    _unit = str(_row.get(unit_col_k, ''))
                    _no   = str(int(_row['出題順'])) if '出題順' in _row.index else ''
                    _grp  = _grp_from_unit(_unit)
                    _scn  = _scene_from_unit(_unit)
                    # シーン1共通テストはグループキーが取れないので最初のグループを使用
                    if _grp is None and _scn == 'シーン1':
                        _grp = list(_gq.keys())[0]
                    if _grp and _scn and _no:
                        _pk = (_grp, _scn, _no)
                        if _pk in _pos_index:
                            q_comp_map[_raw_q]   = _pos_index[_pk][0]
                            q_rubric_map[_raw_q] = _pos_index[_pk][1]
                            _seen.add(_raw_q)
                print(f"[GRADE] q_comp_map built: {len(q_comp_map)}/{answers_df[q_text_col].dropna().nunique()} questions matched", flush=True)

        merged_mapping['q_comp_map']   = q_comp_map
        merged_mapping['q_rubric_map'] = q_rubric_map

        results_dir = RESULTS_DIR / session_id
        results_dir.mkdir(parents=True, exist_ok=True)
        progress_path = results_dir / "progress.json"
        # 列マッピングを保存（再開時に使用）
        with open(results_dir / "column_mapping.json", "w", encoding="utf-8") as f:
            json.dump(merged_mapping, f, ensure_ascii=False)
        import time as _time
        _started_at = _time.time()
        _total_est_tf = answers_df[answers_df.columns[0]].dropna().nunique()
        with open(progress_path, "w", encoding="utf-8") as f:
            json.dump({"status": "processing", "done": 0, "total": _total_est_tf, "current": "採点準備中…",
                       "started_at": _started_at, "now": _started_at}, f)

        def _bg_grade(df, mapping, rdir, sid, ppath, started_at=_started_at):
            try:
                import importlib, grader as _gmod
                importlib.reload(_gmod)
                _grade_fn = _gmod.grade_tall_format
                def cb(done, total, name):
                    import time as _t
                    with open(ppath, "w", encoding="utf-8") as fp:
                        json.dump({"status": "processing", "done": done, "total": total, "current": name, "started_at": started_at, "now": _t.time()}, fp, ensure_ascii=False)
                results = _grade_fn(df, mapping, rdir, progress_cb=cb)
                with open(rdir / "summary.json", "w", encoding="utf-8") as fp:
                    json.dump(results, fp, ensure_ascii=False, indent=2)
                with open(ppath, "w", encoding="utf-8") as fp:
                    json.dump({"status": "done", "session_id": sid}, fp)
            except Exception as e:
                import traceback
                with open(ppath, "w", encoding="utf-8") as fp:
                    json.dump({"status": "error", "message": str(e), "detail": traceback.format_exc()}, fp, ensure_ascii=False)

        t = threading.Thread(target=_bg_grade, args=(answers_df, merged_mapping, results_dir, session_id, progress_path), daemon=True)
        t.start()
        return jsonify({"session_id": session_id, "status": "processing"})

    # 問題ファイルの解決: セッション内 or 事前登録
    ref_path = session_dir / "exam_ref.json"
    if ref_path.exists():
        with open(ref_path, encoding="utf-8") as f:
            ref = json.load(f)
        exam_id = ref["exam_id"]
        exam_dir = EXAMS_DIR / exam_id
        q_files = list(exam_dir.glob("questions.*")) or \
                  list(exam_dir.glob("source.*")) or \
                  [f for f in (exam_dir.iterdir() if exam_dir.exists() else [])
                   if f.suffix.lower() in ('.xlsx', '.csv', '.xls')]
        print(f"[DEBUG] exam_dir={exam_dir} exists={exam_dir.exists()} q_files={q_files}", flush=True)
        if not q_files:
            existing = [p.name for p in exam_dir.iterdir()] if exam_dir.exists() else []
            return jsonify({"error": f"試験設定の問題ファイルが見つかりません (exam_id={exam_id}, files={existing})"}), 404
        meta_path = EXAMS_DIR / exam_id / "meta.json"
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        merged_mapping = {**meta.get("column_mapping", {}), **column_mapping}
    else:
        q_files = list(session_dir.glob("questions.*"))
        if not q_files:
            return jsonify({"error": "問題ファイルが見つかりません"}), 404
        merged_mapping = column_mapping

    questions_df = load_excel(q_files[0])

    results_dir = RESULTS_DIR / session_id
    results_dir.mkdir(parents=True, exist_ok=True)

    import time as _time
    _started_at2 = _time.time()
    _total_est = len(answers_df)  # 人数を事前にカウント
    progress_path2 = results_dir / "progress.json"
    with open(progress_path2, "w", encoding="utf-8") as f:
        json.dump({"status": "processing", "done": 0, "total": _total_est, "current": "採点準備中…",
                   "started_at": _started_at2, "now": _started_at2}, f)

    # 班別モード（group_based）か通常モードかで分岐
    if ref_path.exists():
        group_q_path = EXAMS_DIR / exam_id / "group_questions.json"
    else:
        group_q_path = None

    def _bg_grade2(gq_path, a_df, mapping, rdir, sid, ppath, started_at=_started_at2):
        try:
            import importlib, grader as _gmod
            importlib.reload(_gmod)
            def cb(done, total, name):
                import time as _t
                with open(ppath, "w", encoding="utf-8") as fp:
                    json.dump({"status": "processing", "done": done, "total": total, "current": name,
                               "started_at": started_at, "now": _t.time()}, fp, ensure_ascii=False)
            if gq_path and Path(gq_path).exists():
                with open(gq_path, encoding="utf-8") as f:
                    gq = json.load(f)
                results = _gmod.grade_exam_group_based(gq, a_df, mapping, rdir, progress_cb=cb)
            else:
                results = _gmod.grade_exam(questions_df, a_df, mapping, rdir)
            with open(rdir / "summary.json", "w", encoding="utf-8") as fp:
                json.dump(results, fp, ensure_ascii=False, indent=2)
            with open(ppath, "w", encoding="utf-8") as fp:
                json.dump({"status": "done", "session_id": sid}, fp)
        except Exception as e:
            import traceback
            with open(ppath, "w", encoding="utf-8") as fp:
                json.dump({"status": "error", "message": str(e), "detail": traceback.format_exc()}, fp, ensure_ascii=False)

    t2 = threading.Thread(target=_bg_grade2, args=(group_q_path, answers_df, merged_mapping, results_dir, session_id, progress_path2), daemon=True)
    t2.start()
    return jsonify({"session_id": session_id, "status": "processing"})


# ── レポート ──────────────────────────────────────────────────────────────────

def calc_genre_stats(results, examinee):
    """同ジャンル内での順位・平均を計算"""
    genre = examinee.get("genre", "")
    if not genre:
        return None
    same = [r for r in results if r.get("genre") == genre]
    if len(same) < 2:
        return None
    sorted_same = sorted(same, key=lambda x: x["percentage"], reverse=True)
    rank = next((i + 1 for i, r in enumerate(sorted_same) if r["id"] == examinee["id"]), None)
    avg = round(sum(r["percentage"] for r in same) / len(same), 1)
    return {"rank": rank, "total": len(same), "avg": avg}


def calc_genre_summaries(results, competency_cols):
    """ジャンル別サマリー統計"""
    from collections import defaultdict
    groups = defaultdict(list)
    for r in results:
        g = r.get("genre") or "未設定"
        groups[g].append(r)
    summaries = {}
    for g, members in groups.items():
        pcts = [m["percentage"] for m in members]
        comp_avgs = {}
        for c in competency_cols:
            rates = [m["comp_rates"].get(c, 0) for m in members]
            comp_avgs[c] = round(sum(rates) / len(rates), 1) if rates else 0
        summaries[g] = {
            "count": len(members),
            "avg_pct": round(sum(pcts) / len(pcts), 1),
            "max_pct": max(pcts),
            "min_pct": min(pcts),
            "comp_avgs": comp_avgs,
        }
    return summaries


def calc_scene_scores(examinee):
    """シーン別得点集計（コンピテンシー別内訳付き）"""
    scene_totals, scene_max = {}, {}
    scene_comp_totals, scene_comp_max = {}, {}
    for ans in examinee.get("answers", []):
        scene = ans.get("question_genre", "その他")
        scores = ans.get("competency_scores", {})
        total = sum(scores.values())
        mx = len(scores) * 2
        scene_totals[scene] = scene_totals.get(scene, 0) + total
        scene_max[scene]    = scene_max.get(scene, 0) + mx
        ct = scene_comp_totals.setdefault(scene, {})
        cm = scene_comp_max.setdefault(scene, {})
        for c, v in scores.items():
            ct[c] = ct.get(c, 0) + v
            cm[c] = cm.get(c, 0) + 2
    result = {}
    for s in scene_totals:
        mx = scene_max[s]
        ct = scene_comp_totals.get(s, {})
        cm = scene_comp_max.get(s, {})
        comp_breakdown = {
            c: {
                "total": ct[c],
                "max":   cm[c],
                "pct":   round(ct[c] / cm[c] * 100, 1) if cm[c] > 0 else 0,
            }
            for c in ct
        }
        result[s] = {
            "total":          scene_totals[s],
            "max":            mx,
            "pct":            round(scene_totals[s] / mx * 100, 1) if mx > 0 else 0,
            "comp_breakdown": comp_breakdown,
        }
    return result


def build_overall_comment(examinee, scene_scores, comp_comments=None):
    """スコアから総合評価コメントを生成（コンピテンシー別コメントと矛盾しない設計）"""
    comp_rates = examinee.get("comp_rates", {})
    pct = examinee.get("percentage", 0)

    # 実際の得点率に基づいてコンピテンシーを分類（名前に依存しない）
    sorted_comps = sorted(comp_rates.items(), key=lambda x: x[1], reverse=True)
    strong_comps = [(c, r) for c, r in sorted_comps if r >= 80]   # 実際に高いもの
    grow_comps   = [(c, r) for c, r in sorted_comps if r < 70]    # 実際に低いもの

    # ① 総評（導入）：全体得点率のみに基づく。コンピテンシー名は挙げない
    if pct >= 80:
        intro = (
            f"総合得点率{pct}%。"
            f"災害対策員として求められる情報の収集・分析・判断・伝達の各場面において、"
            f"高い水準の対応力を発揮できています。"
            f"不確実な状況下でも状況を整理し、班として取るべき行動を的確に選択する力が"
            f"シーンを通じて一貫して示されました。"
        )
    elif pct >= 65:
        intro = (
            f"総合得点率{pct}%。"
            f"災害対策員として求められる情報共有・応急復旧対応の基本的な枠組みは"
            f"概ね身についており、標準的な水準に達しています。"
            f"一部の領域にはさらなる成長の余地がありますが、"
            f"実践を重ねることで着実な向上が期待できます。"
        )
    elif pct >= 50:
        intro = (
            f"総合得点率{pct}%。"
            f"情報共有・応急復旧の基本的な方向性は理解できていますが、"
            f"災害対策員として求められる判断の精度と伝達の明確さに"
            f"改善が必要な部分が見られました。"
            f"今回の試験で確認できた課題を起点に、具体的な改善に取り組んでください。"
        )
    else:
        intro = (
            f"総合得点率{pct}%。"
            f"情報収集・分析・共有のいずれかの場面で対応の精度に課題が見られ、"
            f"班での応急復旧活動に必要な判断力・伝達力の強化が求められます。"
            f"本試験で明らかになった課題を正確に把握し、具体的な改善に取り組んでください。"
        )

    # 強みへの言及：実際に高いコンピテンシーのみ
    if strong_comps:
        strong_names = "・".join(f"「{c}」" for c, _ in strong_comps[:2])
        intro += (
            f"特に{strong_names}については高い水準を示しており、"
            f"この強みを今後の災対活動でも継続して発揮してください。"
        )

    # ② 改善提案：実際に低いコンピテンシーのみ言及
    if grow_comps:
        grow_names = "・".join(f"「{c}」" for c, _ in grow_comps[:2])
        growth_comment = (
            f"{grow_names}については、コンピテンシー別の評価コメントに"
            f"記載した改善点を参照し、日常の災対活動の中で意識的に実践することが"
            f"次のステップです。"
            f"班での情報共有・応急復旧の場面を具体的に意識しながら、"
            f"これらの能力を着実に高めていってください。"
        )
    else:
        growth_comment = (
            f"今後は、より不確実性が高い局面や複数課題が同時発生する場面での"
            f"判断精度の維持・向上が課題です。"
            f"自身の災対経験から気づいた改善点を言語化し、"
            f"具体的な提案として実践していくことが"
            f"災害対策員としてのさらなる成長につながります。"
        )

    return "\n\n".join([intro, growth_comment])


def build_comp_comments(examinee):
    """コンピテンシー別評価コメントを生成"""
    comp_rates = examinee.get("comp_rates", {})
    desc = {
        "コミュニケーション": {
            "high": (
                "班内外への報告・調整のタイミングと内容が的確で、自班の状況を関係者へ正確かつ簡潔に伝え、必要な連携を取れています。"
                "災害対策員として、情報の受け手が意思決定に使えるよう要点を絞ったエスカレーションを徹底し、不明点は確認して双方向のやり取りを意識的に維持することが引き続き重要です。"
            ),
            "mid": (
                "班内の情報共有・報告は概ね適切で、クリティカルな情報を伝達する基盤は確認できます。"
                "一方向の発信にとどまる場面があり、相手が理解・活用できているかを確認しながら進める双方向のコミュニケーションに改善余地があります。"
            ),
            "low_mid": (
                "情報を伝えようとする行動は取れていますが、何を・誰に・いつ伝えるかの判断が曖昧な場面があります。"
                "クリティカルな情報を見極めた上で、伝える相手と内容を明確にして報告する習慣を身につけることが必要です。"
            ),
            "low": (
                "班での情報共有に課題があり、報告の内容・タイミング・相手の選定を見直す必要があります。"
                "まず自班内で「何が起きているか・何が必要か」を簡潔にまとめて伝える訓練を積み、確認の習慣を定着させることが先決です。"
            ),
        },
        "情報収集": {
            "high": (
                "参集後の状況把握において、必要な情報を能動的・多角的に収集し、複数の情報源を組み合わせて状況を先手先手で把握できています。"
                "災害対策員として、収集した情報を班内で共有し応急復旧の判断に直結させるまでの一連の流れを、引き続き精度高く維持することが求められます。"
            ),
            "mid": (
                "公式情報源の確認や関係者への聴取など基本的な収集行動は取れており、状況把握の基盤はあります。"
                "他班・外部機関・現場など多角的なルートから能動的に情報を集める行動が不十分な場面があり、この点のさらなる強化が求められます。"
            ),
            "low_mid": (
                "与えられた情報を受け取ることはできていますが、自ら能動的に確認・収集する行動が不足しています。"
                "「今何を確認すべきか」を自分で問い、参集時の確認先（上位組織・他班・現場）を事前に想定して動く習慣が必要です。"
            ),
            "low": (
                "情報収集の範囲・能動性に課題があり、応急復旧に必要な状況判断の前提が不十分になっています。"
                "参集時にまず確認すべき情報（被害状況・班の状況・対応済み事項）を整理し、優先順位をつけて収集する基本ルーティンを身につけてください。"
            ),
        },
        "情報分析": {
            "high": (
                "収集情報の中からクリティカルな事象を特定し、事実と推測を区別しながら影響範囲・優先度を的確に判断できています。"
                "災害対策員として、分析の根拠を班内で共有し、組織全体の優先順位判断に活かせる形で発信することを引き続き意識してください。"
            ),
            "mid": (
                "重大な影響を及ぼす情報を見極める基本的な分析はできており、判断力の基盤は確認できます。"
                "「なぜそれがクリティカルなのか」という根拠の明示と、分析結果を具体的な対応アクションへつなげる部分に改善余地があります。"
            ),
            "low_mid": (
                "情報を整理しようとする意識はありますが、優先順位が曖昧なまま判断に進む場面があります。"
                "「影響範囲の広さ」と「緊急度」の2軸で情報を評価する習慣を身につけ、クリティカルな情報を他と区別して扱えるようにすることが必要です。"
            ),
            "low": (
                "収集した情報をそのまま行動に移す傾向があり、クリティカルな情報を見極めるプロセスが欠けています。"
                "「確定情報か未確認情報か」「影響範囲はどこまでか」「緊急度はどの程度か」を必ず確認してから判断する習慣を徹底してください。"
            ),
        },
        "想像・先読み": {
            "high": (
                "収集情報からリスク・影響を想像して先読みし、班として取るべき対応を組織全体の視点で判断できています。"
                "災害対策員として、想定外の事態が発生した際の代替対応も事前に考慮しておくことで、状況変化への対応力をさらに高められます。"
            ),
            "mid": (
                "次に起こりうる事態を意識した対応は取れており、基本的なシナリオ想定は身についています。"
                "想定した事態のリスク・影響を組織全体の視点で評価し、優先順位をつけて意思決定につなげる部分にさらなる向上の余地があります。"
            ),
            "low_mid": (
                "現在起きている事象への対応はできていますが、「この後どうなるか・どこへ影響が波及するか」を先読みして予防的に動く場面が不足しています。"
                "情報を受け取った際に「1手先・2手先を想定する」問いかけを意識的に行うことが必要です。"
            ),
            "low": (
                "目の前の事象への対処に集中するあまり、事態の進展や波及影響を見落とす場面が見られます。"
                "発生した事象について「ベースシナリオ（標準的な展開）」と「最悪シナリオ」を両方想定する習慣を意識的に身につけてください。"
            ),
        },
        "計画": {
            "high": (
                "優先順位の設定・役割分担・タイムライン設計が的確で、制約がある中でも実行可能な応急復旧計画を組み立てられています。"
                "災害対策員として、計画立案の段階で状況変化を想定した代替案も準備しておくことで、実行段階での判断をさらに迅速化できます。"
            ),
            "mid": (
                "基本的な行動計画の立案と優先順位の設定は概ね適切で、班内の応急復旧を進める計画力の基盤はあります。"
                "「いつまでに・誰が・何を完了させるか」という時間軸と役割分担の明確化が不十分な場面があり、この部分の具体化が今後の課題です。"
            ),
            "low_mid": (
                "対応の方向性は考えられていますが、計画が抽象的で具体的な応急復旧アクションへの落とし込みが不十分です。"
                "各アクションに「担当者・実施期限・完了条件」を紐付けることを徹底し、実行可能な計画として機能させることが必要です。"
            ),
            "low": (
                "個々の対応が場当たり的になっており、班全体の応急復旧を見渡した計画の枠組みが不足しています。"
                "まず「優先度の高い3つのアクションと担当・期限」を明示することから始め、計画立案を実際の対応に組み込む練習を重ねてください。"
            ),
        },
    }
    # 半角カタカナ→全角正規化マップ
    _normalize = {"ｺﾐｭﾆｹｰｼｮﾝ": "コミュニケーション"}

    def level(r):
        return "high" if r >= 90 else "mid" if r >= 70 else "low_mid" if r >= 50 else "low"

    return {
        comp: desc.get(_normalize.get(comp, comp), {}).get(level(rate), f"{comp}のさらなる強化を期待します。")
        for comp, rate in comp_rates.items()
    }


def calc_all_avg_comp_rates(results):
    """全受験者のコンピテンシー別平均達成率を計算"""
    comp_sums = {}
    comp_counts = {}
    for r in results:
        for comp, rate in r.get("comp_rates", {}).items():
            comp_sums[comp] = comp_sums.get(comp, 0) + rate
            comp_counts[comp] = comp_counts.get(comp, 0) + 1
    return {comp: round(comp_sums[comp] / comp_counts[comp], 1) for comp in comp_sums}


def build_scene_comments(scene_scores):
    """シーン別の総評コメントを生成"""
    comments = {}
    for scene, ss in scene_scores.items():
        pct = ss["pct"]
        comp_breakdown = ss.get("comp_breakdown", {})
        sorted_cb = sorted(comp_breakdown.items(), key=lambda x: x[1]["pct"], reverse=True)
        best_comp = sorted_cb[0] if sorted_cb else None
        low_comp  = sorted_cb[-1] if sorted_cb else None

        if pct >= 80:
            opening = f"得点率{pct}%という非常に高い水準を達成しました。"
            tone = "状況判断と対応の質が高く、シナリオ全体を通じて的確な行動選択が光りました。"
        elif pct >= 65:
            opening = f"得点率{pct}%を獲得し、概ね良好な対応ができていました。"
            tone = "基本的な対応方針を正しく捉えており、安定したパフォーマンスを発揮しました。"
        elif pct >= 50:
            opening = f"得点率{pct}%となりました。"
            tone = "基本的な枠組みは身についていますが、一部の判断・対応に改善の余地があります。"
        else:
            opening = f"得点率{pct}%という結果となりました。"
            tone = "状況の複雑さへの対応に課題が見られました。今回の振り返りを次につなげてください。"

        strength = ""
        if best_comp and best_comp[1]["pct"] >= 70:
            strength = f"特に「{best_comp[0]}」（{best_comp[1]['pct']}%）での対応が優れていました。"

        grow = ""
        if low_comp and low_comp[1]["pct"] < 70 and (not best_comp or low_comp[0] != best_comp[0]):
            grow = f"「{low_comp[0]}」のさらなる強化が期待されます。"

        comments[scene] = opening + tone + strength + grow

    return comments


SCENE_ORDER = ["シーン1", "シーン2", "シーン3"]


@app.route("/report/<session_id>/<examinee_id>")
def report(session_id, examinee_id):
    summary_path = RESULTS_DIR / session_id / "summary.json"
    if not summary_path.exists():
        return "レポートが見つかりません", 404
    with open(summary_path, encoding="utf-8") as f:
        results = json.load(f)
    examinee = next((r for r in results if str(r["id"]) == str(examinee_id)), None)
    if not examinee:
        return "受験者が見つかりません", 404
    now = datetime.date.today().strftime("%Y年%m月%d日")
    genre_stats     = calc_genre_stats(results, examinee)
    scene_scores    = calc_scene_scores(examinee)
    comp_comments   = build_comp_comments(examinee)
    overall_comment = build_overall_comment(examinee, scene_scores, comp_comments)
    scene_comments  = build_scene_comments(scene_scores)
    avg_comp_rates  = calc_all_avg_comp_rates(results)

    # シーン順に並んだ問題リスト（グループ化用）
    answers_by_scene = {}
    for ans in examinee.get("answers", []):
        s = ans.get("question_genre", "その他")
        answers_by_scene.setdefault(s, []).append(ans)
    scene_order = [s for s in SCENE_ORDER if s in answers_by_scene] + \
                  [s for s in answers_by_scene if s not in SCENE_ORDER]

    return render_template(
        "report.html",
        examinee=examinee, session_id=session_id, now=now,
        genre_stats=genre_stats, scene_scores=scene_scores,
        overall_comment=overall_comment, scene_comments=scene_comments,
        avg_comp_rates=avg_comp_rates, comp_comments=comp_comments,
        answers_by_scene=answers_by_scene, scene_order=scene_order,
    )


@app.route("/report/<session_id>/<examinee_id>/download")
def download_report(session_id, examinee_id):
    summary_path = RESULTS_DIR / session_id / "summary.json"
    if not summary_path.exists():
        return "レポートが見つかりません", 404
    with open(summary_path, encoding="utf-8") as f:
        results = json.load(f)
    examinee = next((r for r in results if str(r["id"]) == str(examinee_id)), None)
    if not examinee:
        return "受験者が見つかりません", 404
    scene_scores = calc_scene_scores(examinee)
    comp_comments = build_comp_comments(examinee)
    overall_comment = build_overall_comment(examinee, scene_scores, comp_comments)
    docx_path = RESULTS_DIR / session_id / f"report_{examinee_id}.docx"
    generate_word_report(examinee, str(docx_path),
                         scene_scores=scene_scores, overall_comment=overall_comment,
                         comp_comments=comp_comments)
    return send_file(str(docx_path), as_attachment=True,
                     download_name=f"採点レポート_{examinee['name']}.docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.route("/report/<session_id>/<examinee_id>/download/pdf")
def download_report_pdf(session_id, examinee_id):
    summary_path = RESULTS_DIR / session_id / "summary.json"
    if not summary_path.exists():
        return "レポートが見つかりません", 404
    with open(summary_path, encoding="utf-8") as f:
        results = json.load(f)
    examinee = next((r for r in results if str(r["id"]) == str(examinee_id)), None)
    if not examinee:
        return "受験者が見つかりません", 404

    try:
        port = os.environ.get('PORT', '5051')
        report_url = f"http://127.0.0.1:{port}/report/{session_id}/{examinee_id}"
        browser = _get_pw_browser()
        ctx = browser.new_context()
        pw_page = ctx.new_page()
        pw_page.goto(report_url, wait_until="networkidle", timeout=60000)
        pw_page.wait_for_timeout(800)
        pdf_bytes = pw_page.pdf(
            landscape=True,
            print_background=True,
            margin={"top": "0", "bottom": "0",
                    "left": "12mm", "right": "12mm"},
        )
        ctx.close()
    except Exception as e:
        app.logger.error(f"PDF generation error: {e}")
        return f"PDF生成に失敗しました: {e}", 500

    return send_file(
        io.BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=f"採点レポート_{examinee['name']}.pdf",
        mimetype="application/pdf",
    )


@app.route("/grade/progress/<session_id>")
def grade_progress(session_id):
    progress_path = RESULTS_DIR / session_id / "progress.json"
    if not progress_path.exists():
        return jsonify({"status": "unknown"})
    with open(progress_path, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/grade/debug_log/<session_id>")
def grade_debug_log(session_id):
    log_path = RESULTS_DIR / session_id / "grade_debug.log"
    if not log_path.exists():
        return "<pre>ログファイルが見つかりません</pre>", 404
    with open(log_path, encoding="utf-8") as f:
        content = f.read()
    return f"<pre style='font-family:monospace;font-size:13px;white-space:pre-wrap'>{content}</pre>"


@app.route("/guide")
def guide():
    return render_template("guide.html")


@app.route("/resume/<session_id>", methods=["POST"])
def resume_grade(session_id):
    """途中で止まったセッションを再開する"""
    session_dir = UPLOAD_DIR / session_id
    a_files = list(session_dir.glob("answers.*"))
    if not a_files:
        return jsonify({"error": "回答ファイルが見つかりません。再度アップロードしてください。"}), 404

    results_dir = RESULTS_DIR / session_id
    results_dir.mkdir(parents=True, exist_ok=True)

    # 保存済みの列マッピングを読み込む（なければLMSデフォルト）
    mapping_path = results_dir / "column_mapping.json"
    if mapping_path.exists():
        with open(mapping_path, encoding="utf-8") as f:
            merged_mapping = json.load(f)
    else:
        merged_mapping = {
            "a_id": "ログインID", "a_name": "名前",
            "a_dept": "グループ", "a_genre": "属性",
            "q_text_col": "問題文", "a_text_col": "解答", "unit_col": "ユニット",
        }

    answers_df = load_excel(a_files[0])
    individual_dir = results_dir / "individual"
    done_count = len(list(individual_dir.glob("*.json"))) if individual_dir.exists() else 0
    total_count = int(answers_df[answers_df.columns[0]].dropna().nunique())

    import time as _time
    _started_at = _time.time()
    progress_path = results_dir / "progress.json"
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump({
            "status": "processing",
            "done": done_count,
            "total": total_count,
            "current": f"再開中… ({done_count}人分は採点済みのためスキップ)",
            "started_at": _started_at,
            "now": _started_at,
        }, f, ensure_ascii=False)

    def _bg_resume(df, mapping, rdir, sid, ppath, started_at=_started_at):
        try:
            import importlib, grader as _gmod
            importlib.reload(_gmod)
            _grade_fn = _gmod.grade_tall_format
            def cb(done, total, name):
                import time as _t
                with open(ppath, "w", encoding="utf-8") as fp:
                    json.dump({"status": "processing", "done": done, "total": total,
                               "current": name, "started_at": started_at, "now": _t.time()},
                              fp, ensure_ascii=False)
            results = _grade_fn(df, mapping, rdir, progress_cb=cb)
            with open(rdir / "summary.json", "w", encoding="utf-8") as fp:
                json.dump(results, fp, ensure_ascii=False, indent=2)
            with open(ppath, "w", encoding="utf-8") as fp:
                json.dump({"status": "done", "session_id": sid}, fp)
        except Exception as e:
            import traceback
            with open(ppath, "w", encoding="utf-8") as fp:
                json.dump({"status": "error", "message": str(e),
                           "detail": traceback.format_exc()}, fp, ensure_ascii=False)

    t = threading.Thread(
        target=_bg_resume,
        args=(answers_df, merged_mapping, results_dir, session_id, progress_path),
        daemon=True,
    )
    t.start()
    return jsonify({"session_id": session_id, "status": "processing"})


@app.route("/sessions")
def sessions_list():
    """採点済み・未完了セッション一覧"""
    sessions = []

    # 完了済みセッション
    for summary_path in sorted(RESULTS_DIR.glob("*/summary.json"),
                                key=lambda p: p.stat().st_mtime, reverse=True):
        session_id = summary_path.parent.name
        try:
            with open(summary_path, encoding="utf-8") as f:
                results = json.load(f)
            if not results:
                continue
            graded_at = datetime.datetime.fromtimestamp(
                summary_path.stat().st_mtime, tz=_JST).strftime("%Y年%m月%d日 %H:%M")
            genres = sorted({r.get("genre", "") for r in results if r.get("genre")})
            avg_pct = round(sum(r["percentage"] for r in results) / len(results), 1)
            sessions.append({
                "session_id": session_id,
                "graded_at":  graded_at,
                "count":      len(results),
                "genres":     genres,
                "avg_pct":    avg_pct,
                "status":     "done",
            })
        except Exception:
            continue

    # 未完了セッション（個別ファイルあり・summary.jsonなし）
    done_ids = {s["session_id"] for s in sessions}
    for rdir in sorted(RESULTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not rdir.is_dir():
            continue
        sid = rdir.name
        if sid in done_ids:
            continue
        ind_dir = rdir / "individual"
        if not ind_dir.exists():
            continue
        ind_files = list(ind_dir.glob("*.json"))
        if not ind_files:
            continue
        # 回答ファイルの有無（再開可能か）
        can_resume = bool(list((UPLOAD_DIR / sid).glob("answers.*"))) \
            if (UPLOAD_DIR / sid).exists() else False
        # progress.json から状態を取得
        prog_path = rdir / "progress.json"
        st = "incomplete"
        if prog_path.exists():
            try:
                with open(prog_path, encoding="utf-8") as f:
                    prog = json.load(f)
                st = prog.get("status", "incomplete")
                if st == "done":
                    continue  # summary.jsonが別途存在するはずなのでスキップ
            except Exception:
                pass
        graded_at = datetime.datetime.fromtimestamp(
            max(f.stat().st_mtime for f in ind_files), tz=_JST
        ).strftime("%Y年%m月%d日 %H:%M")
        sessions.append({
            "session_id": sid,
            "graded_at":  graded_at,
            "count":      len(ind_files),
            "genres":     [],
            "avg_pct":    None,
            "status":     st,
            "can_resume": can_resume,
        })

    sessions.sort(key=lambda s: s["graded_at"], reverse=True)
    return render_template("sessions.html", sessions=sessions)


@app.route("/results/<session_id>")
def results_list(session_id):
    summary_path = RESULTS_DIR / session_id / "summary.json"
    if not summary_path.exists():
        return "結果が見つかりません", 404
    with open(summary_path, encoding="utf-8") as f:
        results = json.load(f)
    # Union of all competency_cols across results (not just first person)
    _COMP_ORDER = ['コミュニケーション', '情報収集', '情報分析', '想像・先読み', '計画']
    all_comp_set = {c for r in results for c in r.get("competency_cols", [])}
    competency_cols = [c for c in _COMP_ORDER if c in all_comp_set] + \
                      [c for c in sorted(all_comp_set) if c not in _COMP_ORDER]
    genres = sorted({r.get("genre", "") for r in results if r.get("genre")})
    # 全体コンピテンシー平均
    comp_averages = {}
    for c in competency_cols:
        rates = [r["comp_rates"].get(c, 0) for r in results]
        comp_averages[c] = round(sum(rates) / len(rates), 1) if rates else 0
    genre_summaries = calc_genre_summaries(results, competency_cols) if genres else {}
    return render_template("results.html", results=results, session_id=session_id,
                           competency_cols=competency_cols, genres=genres,
                           comp_averages=comp_averages, genre_summaries=genre_summaries)


@app.route("/exam/<exam_id>/template/<group_name>")
def download_template(exam_id, group_name):
    """班別回答テンプレートのダウンロード"""
    tpl_path = BASE_DIR / "static" / "templates" / f"回答テンプレート_{group_name}.xlsx"
    if not tpl_path.exists():
        return "テンプレートが見つかりません", 404
    return send_file(str(tpl_path), as_attachment=True,
                     download_name=f"回答テンプレート_{group_name}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/exam/<exam_id>/template/all")
def download_template_all(exam_id):
    tpl_path = BASE_DIR / "static" / "templates" / "回答記入テンプレート_全班.xlsx"
    if not tpl_path.exists():
        return "テンプレートが見つかりません", 404
    return send_file(str(tpl_path), as_attachment=True,
                     download_name="回答記入テンプレート_全班.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/regrade/<session_id>/<examinee_id>", methods=["POST"])
def regrade_examinee(session_id, examinee_id):
    """既存 summary.json の answer_text を使って1人分を再採点し competency_reasons を付与する"""
    from grader import grade_single, load_context
    import copy

    results_dir = BASE_DIR / "results" / session_id
    summary_path = results_dir / "summary.json"
    if not summary_path.exists():
        return jsonify({"error": "session not found"}), 404

    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    idx = next((i for i, ex in enumerate(summary) if ex["id"] == examinee_id), None)
    if idx is None:
        return jsonify({"error": "examinee not found"}), 404

    examinee = summary[idx]

    # load exam context
    ctx = load_context(str(results_dir))
    prerequisite = ctx.get("prerequisite", "")
    scenes = ctx.get("scenes", {})

    # load group questions
    ref_path = BASE_DIR / "uploads" / session_id / "exam_ref.json"
    if not ref_path.exists():
        return jsonify({"error": "exam_ref.json not found"}), 404
    exam_id = json.load(open(ref_path, encoding="utf-8"))["exam_id"]
    gq_path = BASE_DIR / "exams" / exam_id / "group_questions.json"
    group_questions = json.load(open(gq_path, encoding="utf-8"))

    genre = examinee["genre"]
    questions = group_questions.get(genre)
    if not questions:
        genre_core = genre.replace("班", "").replace("部", "")
        questions = next(
            (v for k, v in group_questions.items()
             if genre_core in k or k.lstrip("0123456789") in genre),
            None
        )
    if not questions:
        return jsonify({"error": f"questions not found for genre: {genre}"}), 404

    q_map = {q["label"]: q for q in questions}
    new_answers = []
    for ans in examinee["answers"]:
        q = q_map.get(ans["question_id"])
        if not q:
            new_answers.append(ans)
            continue
        result = grade_single(
            question_text=q["text"],
            rubrics_per_comp=q.get("rubrics", {}),
            answer=ans["answer_text"],
            competencies=ans["competencies"],
            prerequisite=prerequisite,
            scene_context=scenes.get(q.get("scene", ""), ""),
        )
        updated = copy.copy(ans)
        updated["competency_reasons"] = result.get("competency_reasons", {})
        new_answers.append(updated)

    examinee["answers"] = new_answers
    summary[idx] = examinee
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return jsonify({"status": "ok", "graded": len(new_answers)})


if __name__ == "__main__":
    app.run(debug=True, port=5050, use_reloader=False)
