import io
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── フォント登録 ──────────────────────────────────────────────────────────────
pdfmetrics.registerFont(TTFont("JP",     "C:/Windows/Fonts/YuGothR.ttc", subfontIndex=0))
pdfmetrics.registerFont(TTFont("JP-B",   "C:/Windows/Fonts/YuGothR.ttc", subfontIndex=0))

PRIMARY    = colors.HexColor("#1A3A5C")
LIGHT_BG   = colors.HexColor("#E8EEF5")
GREEN_BG   = colors.HexColor("#D4EDDA")
YELLOW_BG  = colors.HexColor("#FFF3CD")
RED_BG     = colors.HexColor("#F8D7DA")
GREEN_TXT  = colors.HexColor("#1A6E3C")
YELLOW_TXT = colors.HexColor("#856404")
RED_TXT    = colors.HexColor("#8C2A1A")
WHITE      = colors.white
GREY_TXT   = colors.HexColor("#888888")

SCENE_ORDER = ["シーン1", "シーン2", "シーン3"]

PAGE_W, PAGE_H = A4
MARGIN = 2.0 * cm
INNER_W = PAGE_W - MARGIN * 2


def _style(name="normal", size=9, bold=False, color=colors.black,
           leading=None, align="LEFT"):
    return ParagraphStyle(
        name=name,
        fontName="JP-B" if bold else "JP",
        fontSize=size,
        leading=leading or size * 1.4,
        textColor=color,
        wordWrap="CJK",
        alignment={"LEFT": 0, "CENTER": 1, "RIGHT": 2}.get(align, 0),
    )


def _score_bg(pct):
    if pct >= 75: return GREEN_BG
    if pct >= 50: return YELLOW_BG
    return RED_BG


def _score_fg(pct):
    if pct >= 75: return GREEN_TXT
    if pct >= 50: return YELLOW_TXT
    return RED_TXT


def _tbl_style(extra=None):
    base = [
        ("FONTNAME",    (0, 0), (-1, -1), "JP"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("LEADING",     (0, 0), (-1, -1), 12),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if extra:
        base.extend(extra)
    return TableStyle(base)


def generate_pdf_report(examinee: dict, scene_scores: dict = None,
                        overall_comment: str = "") -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=MARGIN, bottomMargin=MARGIN,
        leftMargin=MARGIN, rightMargin=MARGIN,
    )
    story = []
    comp_cols = examinee.get("competency_cols", [])

    # ── タイトル ──────────────────────────────────────────────────────────────
    story.append(Paragraph("防災訓練認定試験　個人採点レポート",
                            _style("title", size=16, bold=True, color=PRIMARY, align="CENTER")))
    story.append(Spacer(1, 0.3 * cm))

    # ── 受験者情報 ─────────────────────────────────────────────────────────────
    today = datetime.date.today().strftime("%Y年%m月%d日")
    info_data = [
        [Paragraph("氏名", _style(bold=True, color=WHITE)),
         Paragraph(examinee.get("name", ""), _style()),
         Paragraph("所属部署", _style(bold=True, color=WHITE)),
         Paragraph(examinee.get("department", ""), _style())],
        [Paragraph("ジャンル", _style(bold=True, color=WHITE)),
         Paragraph(examinee.get("genre", ""), _style()),
         Paragraph("受験日", _style(bold=True, color=WHITE)),
         Paragraph(today, _style())],
    ]
    col_w = INNER_W / 4
    info_tbl = Table(info_data, colWidths=[col_w * 0.6, col_w * 1.4, col_w * 0.6, col_w * 1.4])
    info_tbl.setStyle(_tbl_style([
        ("BACKGROUND", (0, 0), (0, -1), PRIMARY),
        ("BACKGROUND", (2, 0), (2, -1), PRIMARY),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 0.3 * cm))

    # ── 総合スコア ─────────────────────────────────────────────────────────────
    story.append(Paragraph(
        f"総合得点: {examinee['total_score']} / {examinee['total_max']} 点"
        f"　（得点率 {examinee['percentage']}%）",
        _style("score", size=13, bold=True, color=PRIMARY, align="CENTER")))
    story.append(Spacer(1, 0.4 * cm))

    # ── シーン別得点 ──────────────────────────────────────────────────────────
    if scene_scores:
        story.append(Paragraph("シーン別得点", _style("h2", size=11, bold=True, color=PRIMARY)))
        story.append(Spacer(1, 0.15 * cm))

        ordered_scenes = [s for s in SCENE_ORDER if s in scene_scores] + \
                         [s for s in scene_scores if s not in SCENE_ORDER]
        for sc in ordered_scenes:
            ss = scene_scores[sc]
            pct = ss["pct"]
            bg = _score_bg(pct)
            fg = _score_fg(pct)

            sh_data = [[
                Paragraph(sc, _style(bold=True, color=WHITE)),
                Paragraph(f"{ss['total']} / {ss['max']}点　({pct}%)",
                          _style(bold=True, color=fg)),
            ]]
            sh_tbl = Table(sh_data, colWidths=[INNER_W * 0.3, INNER_W * 0.7])
            sh_tbl.setStyle(_tbl_style([
                ("BACKGROUND", (0, 0), (0, 0), PRIMARY),
                ("BACKGROUND", (1, 0), (1, 0), bg),
            ]))
            story.append(sh_tbl)

            comp_bd = ss.get("comp_breakdown", {})
            if comp_bd:
                hdr = [[Paragraph(t, _style(bold=True))
                        for t in ["コンピテンシー", "得点", "達成率"]]]
                rows = []
                for c, cb in comp_bd.items():
                    cbg = _score_bg(cb["pct"])
                    rows.append([
                        Paragraph(c, _style()),
                        Paragraph(f"{cb['total']} / {cb['max']}点", _style()),
                        Paragraph(f"{cb['pct']}%", _style()),
                    ])
                c_tbl = Table(hdr + rows,
                              colWidths=[INNER_W * 0.5, INNER_W * 0.25, INNER_W * 0.25])
                extra = [("BACKGROUND", (0, 0), (-1, 0), LIGHT_BG)]
                for i, (_, cb) in enumerate(comp_bd.items()):
                    extra.append(("BACKGROUND", (2, i + 1), (2, i + 1), _score_bg(cb["pct"])))
                c_tbl.setStyle(_tbl_style(extra))
                story.append(c_tbl)
            story.append(Spacer(1, 0.2 * cm))

    # ── コンピテンシー別達成率 ──────────────────────────────────────────────────
    if comp_cols:
        story.append(Paragraph("コンピテンシー別達成率",
                                _style("h2", size=11, bold=True, color=PRIMARY)))
        story.append(Spacer(1, 0.15 * cm))
        hdr = [[Paragraph(t, _style(bold=True, color=WHITE))
                for t in ["コンピテンシー", "得点", "達成率"]]]
        rows = []
        for c in comp_cols:
            rate = examinee["comp_rates"].get(c, 0)
            rows.append([
                Paragraph(c, _style()),
                Paragraph(f"{examinee['comp_totals'].get(c, 0)} / {examinee['comp_max'].get(c, 0)}",
                          _style()),
                Paragraph(f"{rate}%", _style()),
            ])
        ct_tbl = Table(hdr + rows,
                       colWidths=[INNER_W * 0.5, INNER_W * 0.25, INNER_W * 0.25])
        extra = [("BACKGROUND", (0, 0), (-1, 0), PRIMARY)]
        for i, c in enumerate(comp_cols):
            rate = examinee["comp_rates"].get(c, 0)
            extra.append(("BACKGROUND", (2, i + 1), (2, i + 1), _score_bg(rate)))
        ct_tbl.setStyle(_tbl_style(extra))
        story.append(ct_tbl)
        story.append(Spacer(1, 0.4 * cm))

    # ── 総合評価 ───────────────────────────────────────────────────────────────
    if overall_comment:
        story.append(Paragraph("総合評価", _style("h2", size=11, bold=True, color=PRIMARY)))
        story.append(Spacer(1, 0.15 * cm))
        for para in overall_comment.split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), _style(size=9)))
                story.append(Spacer(1, 0.1 * cm))
        story.append(Spacer(1, 0.2 * cm))

    # ── 問題別採点結果 ─────────────────────────────────────────────────────────
    story.append(Paragraph("問題別採点結果", _style("h2", size=11, bold=True, color=PRIMARY)))
    story.append(Spacer(1, 0.15 * cm))

    answers_by_scene = {}
    for ans in examinee.get("answers", []):
        sc = ans.get("question_genre", "その他")
        answers_by_scene.setdefault(sc, []).append(ans)
    ordered_scenes = [s for s in SCENE_ORDER if s in answers_by_scene] + \
                     [s for s in answers_by_scene if s not in SCENE_ORDER]

    q_num = 0
    for scene in ordered_scenes:
        scene_ans_list = answers_by_scene[scene]
        s_total = sum(sum(a.get("competency_scores", {}).values()) for a in scene_ans_list)
        s_max   = sum(len(a.get("competency_scores", {})) * 3 for a in scene_ans_list)
        s_pct   = round(s_total / s_max * 100, 1) if s_max > 0 else 0

        sh_row = [[
            Paragraph(f"{scene}　{s_total}/{s_max}点 ({s_pct}%)",
                      _style(bold=True, color=WHITE, size=10)),
        ]]
        sh_tbl = Table(sh_row, colWidths=[INNER_W])
        sh_tbl.setStyle(_tbl_style([("BACKGROUND", (0, 0), (-1, -1), PRIMARY)]))
        story.append(sh_tbl)
        story.append(Spacer(1, 0.1 * cm))

        for ans in scene_ans_list:
            q_num += 1
            comp_scores = ans.get("competency_scores", {})
            total_q = sum(comp_scores.values())
            max_q   = len(comp_scores) * 3
            score_str = "  ".join(f"{c}: {s}/3点" for c, s in comp_scores.items())

            # 問タイトル
            q_text = ans.get("question_text", "")
            for marker in ["※評価対象コンピテンシー", "※評価対象　コンピテンシー"]:
                idx = q_text.find(marker)
                if idx != -1:
                    q_text = q_text[:idx].rstrip()
            story.append(Paragraph(
                f"問{q_num}【{ans.get('question_type', '')}】　{q_text}",
                _style(bold=True, size=9, color=colors.black)))

            rows_data = [
                ("受験者の回答", ans.get("answer_text") or "（無回答）"),
                ("得点", f"{total_q} / {max_q}点　│　{score_str}"),
                ("採点コメント", ans.get("feedback", "")),
                ("良かった点",  "、".join(p for p in ans.get("key_points_achieved", []) if p) or "なし"),
                ("不足点",     "、".join(p for p in ans.get("key_points_missed", []) if p) or "なし"),
                ("改善アドバイス", ans.get("improvement_advice") or "—"),
            ]
            if ans.get("forced_zero"):
                rows_data.insert(1, ("強制0点", ans.get("forced_zero_reason", "")))

            tbl_data = [
                [Paragraph(lbl, _style(bold=True, size=8)),
                 Paragraph(str(val), _style(size=8))]
                for lbl, val in rows_data
            ]
            q_tbl = Table(tbl_data, colWidths=[INNER_W * 0.18, INNER_W * 0.82])
            extra = [("BACKGROUND", (0, 0), (0, -1), LIGHT_BG)]
            for i, (lbl, _) in enumerate(rows_data):
                if lbl == "得点" and max_q > 0:
                    extra.append(("BACKGROUND", (1, i), (1, i),
                                  _score_bg(total_q / max_q * 100)))
                if lbl == "強制0点":
                    extra.append(("BACKGROUND", (1, i), (1, i), RED_BG))
            q_tbl.setStyle(_tbl_style(extra))
            story.append(q_tbl)
            story.append(Spacer(1, 0.2 * cm))

    # ── フッター ───────────────────────────────────────────────────────────────
    story.append(HRFlowable(width=INNER_W, color=GREY_TXT))
    story.append(Paragraph(
        "本レポートは危機管理室 防災訓練認定試験システムにより自動生成されました",
        _style(size=7, color=GREY_TXT, align="CENTER")))

    doc.build(story)
    return buf.getvalue()
