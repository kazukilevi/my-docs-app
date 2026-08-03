import re
import unicodedata
from google.oauth2 import service_account
from googleapiclient.discovery import build
import streamlit as st

# --- アプリの設定 ---
st.set_page_config(page_title="Google Docs一括検索", layout="wide")


# --- 秘密鍵の安全な読み込み ---
@st.cache_resource
def get_docs_service():
    try:
        info = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/documents.readonly"]
        )
        return build("docs", "v1", credentials=creds)
    except Exception as e:
        st.error(
            "認証情報の読み込みに失敗しました。Secretsの設定を確認してください。"
        )
        st.stop()


docs_service = get_docs_service()


# --- 検索ロジック ---
def get_doc_content(doc_id):
    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()
        title = doc.get("title", f"({doc_id})")
        text = ""
        for c in doc.get("body", {}).get("content", []):
            if "paragraph" in c:
                for e in c["paragraph"]["elements"]:
                    text += e.get("textRun", {}).get("content", "")
        return title, text
    except Exception as e:
        return "(取得失敗)", str(e)


def normalize_for_search(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def search_text_grouped(text, groups, not_keys, within_para):
    paras_orig = (
        [p.strip() for p in text.split("\n\n") if p.strip()]
        if within_para
        else [text]
    )
    paras_norm = [normalize_for_search(p) for p in paras_orig]

    groups_norm = [
        [normalize_for_search(k) for k in group] for group in groups
    ]
    not_keys_norm = [normalize_for_search(nk) for nk in not_keys]

    hits = []
    for p_orig, p_norm in zip(paras_orig, paras_norm):
        if all(
            any(k in p_norm for k in group) for group in groups_norm
        ) and not any(nk in p_norm for nk in not_keys_norm):
            hits.append(p_orig)
    return hits


# --- ハイライト処理 ---
def highlight_text(text: str, groups: list[list[str]]) -> str:
    all_keywords = [word for group in groups for word in group if word.strip()]
    if not all_keywords:
        return text

    norm_text = normalize_for_search(text)
    matches = []

    for kw in all_keywords:
        norm_kw = normalize_for_search(kw)
        if not norm_kw:
            continue

        start_idx = 0
        while True:
            found_pos = norm_text.find(norm_kw, start_idx)
            if found_pos == -1:
                break
            matches.append((found_pos, found_pos + len(norm_kw)))
            start_idx = found_pos + len(norm_kw)

    if not matches:
        return text

    matches.sort(key=lambda x: x[0])
    merged_matches = []
    for current in matches:
        if not merged_matches:
            merged_matches.append(current)
        else:
            prev_start, prev_end = merged_matches[-1]
            if current[0] <= prev_end:
                merged_matches[-1] = (prev_start, max(prev_end, current[1]))
            else:
                merged_matches.append(current)

    highlighted_text = text
    for start, end in reversed(merged_matches):
        highlighted_text = (
            highlighted_text[:start]
            + f"<mark style='background-color: #ffe066; color: #000000; padding: 2px 4px; border-radius: 2px;'>{highlighted_text[start:end]}</mark>"
            + highlighted_text[end:]
        )

    return highlighted_text


# --- 画面レイアウト ---
st.title("🔎 Google Docs 一括検索")

with st.sidebar:
    st.header("1. ドキュメント設定")
    DEFAULT_DOCS = """https://docs.google.com/document/d/1i5_EAkkvJO8azk2P-C1AnPqBnsOj_RBWpHpZT0kxpqs/edit
https://docs.google.com/document/d/1ApYsSIm91UFOjPKz3EG2mG6vBh9xaln9rGsompRgruk/edit
https://docs.google.com/document/d/1-aL1wvDxQ7ZS6xf_cCM4XpSvvPG7iQcYCc0eEoJ0e9w/edit
https://docs.google.com/document/d/1hYrfVLTPiq0aHH1EacLl8yIrGY1MkLLeClwPjsl_m8U/edit
https://docs.google.com/document/d/1p0QNDVahSWo5MZg7FJ3Yq5O9A62EqvW04TplapL5lAM/edit
https://docs.google.com/document/d/1q5ga4m-_yeE9b1IgdQIWiSgnAjX5O4mLDx5ZgUm5yOk/edit
https://docs.google.com/document/d/1YqXPaL8P1_Do_kFSwZzgwtLbdqiiVtgX_8jdm-H6m6Q/edit
https://docs.google.com/document/d/1Oe1OECA3dYqv8HKz8FPn6iovTxcDuf-P-6pI_gmJz0c/edit
https://docs.google.com/document/d/1NyskSU3wl9LsWC0_Np6pHOpViq15Mr57RRdqa4PHPFg/edit
https://docs.google.com/document/d/1H1NflE8NPahqUvdpr2NezEHLgpJ9z0hFQ-P7gwAVyHc/edit"""

    docs_raw = st.text_area("対象URL（複数可）", value=DEFAULT_DOCS, height=400)
    para_chk = st.checkbox("段落単位で検索する", value=True)

st.header("2. 検索条件")
col1, col2 = st.columns([2, 1])
with col1:
    groups_input = st.text_area(
        "条件（1行に書くとOR、行を変えるとAND）",
        placeholder="例：東京 大阪\n出張",
    )
with col2:
    not_input = st.text_input("除外キーワード（NOT）")

if st.button("検索を実行する", type="primary"):
    doc_ids = [
        d.split("/d/")[1].split("/")[0]
        for d in re.split(r"[\s,]+", docs_raw.strip())
        if "/d/" in d
    ]
    groups = [g.split() for g in groups_input.splitlines() if g.strip()]
    not_keys = not_input.split()

    if not doc_ids:
        st.error("有効なドキュメントURLが見つかりません。")
    elif not groups:
        st.warning("検索条件を入力してください。")
    else:
        status_area = st.empty()
        total_hits_area = st.empty()
        results_container = st.container()

        total_hits_count = 0

        for i, did in enumerate(doc_ids):
            status_area.write(f"⏳ 検索中 ({i+1}/{len(doc_ids)}): {did}...")

            title, text = get_doc_content(did)
            hits = search_text_grouped(text, groups, not_keys, para_chk)
            total_hits_count += len(hits)

            if hits:
                with results_container:
                    with st.expander(
                        f"📘 {title} ({len(hits)}件ヒット)", expanded=False
                    ):
                        for h in hits:
                            highlighted_h = highlight_text(h, groups)
                            st.markdown(
                                f"""<div style="background-color: #262730; color: #ffffff; padding: 12px; border-radius: 6px; margin-bottom: 8px; border: 1px solid #464b5d;">
                                {highlighted_h}
                                </div>""",
                                unsafe_allow_html=True,
                            )

            total_hits_area.subheader(
                f"現在の総ヒット数: {total_hits_count} 件"
            )

        status_area.success(
            f"✅ すべてのドキュメント（{len(doc_ids)}個）の検索が完了しました！"
        )
            if "paragraph" in c:
                for e in c["paragraph"]["elements"]:
                    text += e.get("textRun", {}).get("content", "")
        return title, text
    except Exception as e:
        return "(取得失敗)", str(e)


def normalize_for_search(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def search_text_grouped(text, groups, not_keys, within_para):
    paras_orig = (
        [p.strip() for p in text.split("\n\n") if p.strip()]
        if within_para
        else [text]
    )
    paras_norm = [normalize_for_search(p) for p in paras_orig]

    groups_norm = [
        [normalize_for_search(k) for k in group] for group in groups
    ]
    not_keys_norm = [normalize_for_search(nk) for nk in not_keys]

    hits = []
    for p_orig, p_norm in zip(paras_orig, paras_norm):
        if all(
            any(k in p_norm for k in group) for group in groups_norm
        ) and not any(nk in p_norm for nk in not_keys_norm):
            hits.append(p_orig)
    return hits


# --- ハイライト処理 ---
def highlight_text(text: str, groups: list[list[str]]) -> str:
    """検索キーワードを全角半角・大文字小文字を問わずマッチさせ、<mark>タグでハイライトする"""
    # 検索条件に含まれる全キーワードを1つのリストに展開
    all_keywords = [word for group in groups for word in group if word.strip()]
    if not all_keywords:
        return text

    # NFKC正規化に基づくマッチングを行うため、元のテキストと正規化後のインデックス対応を作成
    norm_text = normalize_for_search(text)

    # ハイライトする対象の（原文上の）文字範囲(start, end)を保持するリスト
    matches = []

    for kw in all_keywords:
        norm_kw = normalize_for_search(kw)
        if not norm_kw:
            continue

        # 正規化後のテキスト内でキーワードの位置を探索
        start_idx = 0
        while True:
            found_pos = norm_text.find(norm_kw, start_idx)
            if found_pos == -1:
                break

            # NFKC正規化では文字数が変化する場合があるため、おおよその位置合わせ
            # （特殊な互換文字等を除き、通常の英数字・ひらがな・カタカナ・漢字は文字長が一致します）
            matches.append((found_pos, found_pos + len(norm_kw)))
            start_idx = found_pos + len(norm_kw)

    if not matches:
        return text

    # 重なり合う領域をマージする処理
    matches.sort(key=lambda x: x[0])
    merged_matches = []
    for current in matches:
        if not merged_matches:
            merged_matches.append(current)
        else:
            prev_start, prev_end = merged_matches[-1]
            if current[0] <= prev_end:
                merged_matches[-1] = (prev_start, max(prev_end, current[1]))
            else:
                merged_matches.append(current)

    # 後ろからタグを埋め込んでいくことでインデックスのズレを防ぐ
    highlighted_text = text
    for start, end in reversed(merged_matches):
        highlighted_text = (
            highlighted_text[:start]
            + f"<mark style='background-color: #ffe066; padding: 2px 4px; border-radius: 2px;'>{highlighted_text[start:end]}</mark>"
            + highlighted_text[end:]
        )

    return highlighted_text


# --- 画面レイアウト ---
st.title("🔎 Google Docs 一括検索")

with st.sidebar:
    st.header("1. ドキュメント設定")
    DEFAULT_DOCS = """https://docs.google.com/document/d/1i5_EAkkvJO8azk2P-C1AnPqBnsOj_RBWpHpZT0kxpqs/edit
https://docs.google.com/document/d/1ApYsSIm91UFOjPKz3EG2mG6vBh9xaln9rGsompRgruk/edit
https://docs.google.com/document/d/1-aL1wvDxQ7ZS6xf_cCM4XpSvvPG7iQcYCc0eEoJ0e9w/edit
https://docs.google.com/document/d/1hYrfVLTPiq0aHH1EacLl8yIrGY1MkLLeClwPjsl_m8U/edit
https://docs.google.com/document/d/1p0QNDVahSWo5MZg7FJ3Yq5O9A62EqvW04TplapL5lAM/edit
https://docs.google.com/document/d/1q5ga4m-_yeE9b1IgdQIWiSgnAjX5O4mLDx5ZgUm5yOk/edit
https://docs.google.com/document/d/1YqXPaL8P1_Do_kFSwZzgwtLbdqiiVtgX_8jdm-H6m6Q/edit
https://docs.google.com/document/d/1Oe1OECA3dYqv8HKz8FPn6iovTxcDuf-P-6pI_gmJz0c/edit
https://docs.google.com/document/d/1NyskSU3wl9LsWC0_Np6pHOpViq15Mr57RRdqa4PHPFg/edit
https://docs.google.com/document/d/1H1NflE8NPahqUvdpr2NezEHLgpJ9z0hFQ-P7gwAVyHc/edit"""

    docs_raw = st.text_area("対象URL（複数可）", value=DEFAULT_DOCS, height=400)
    para_chk = st.checkbox("段落単位で検索する", value=True)

st.header("2. 検索条件")
col1, col2 = st.columns([2, 1])
with col1:
    groups_input = st.text_area(
        "条件（1行に書くとOR、行を変えるとAND）",
        placeholder="例：東京 大阪\n出張",
    )
with col2:
    not_input = st.text_input("除外キーワード（NOT）")

if st.button("検索を実行する", type="primary"):
    doc_ids = [
        d.split("/d/")[1].split("/")[0]
        for d in re.split(r"[\s,]+", docs_raw.strip())
        if "/d/" in d
    ]
    groups = [g.split() for g in groups_input.splitlines() if g.strip()]
    not_keys = not_input.split()

    if not doc_ids:
        st.error("有効なドキュメントURLが見つかりません。")
    elif not groups:
        st.warning("検索条件を入力してください。")
    else:
        status_area = st.empty()
        total_hits_area = st.empty()
        results_container = st.container()

        total_hits_count = 0

        for i, did in enumerate(doc_ids):
            status_area.write(f"⏳ 検索中 ({i+1}/{len(doc_ids)}): {did}...")

            title, text = get_doc_content(did)
            hits = search_text_grouped(text, groups, not_keys, para_chk)
            total_hits_count += len(hits)

            if hits:
                with results_container:
                    with st.expander(
                        f"📘 {title} ({len(hits)}件ヒット)", expanded=False
                    ):
                        for h in hits:
                            # 検索条件の単語部分をハイライト表示に置換
                            highlighted_h = highlight_text(h, groups)
                            # HTML描画用コンテナを出力
                            st.markdown(
                                f"""<div style="background-color: #f0f2f6; padding: 10px; border-radius: 5px; margin-bottom: 8px;">
                                {highlighted_h}
                                </div>""",
                                unsafe_allow_html=True,
                            )

            total_hits_area.subheader(
                f"現在の総ヒット数: {total_hits_count} 件"
            )

        status_area.success(
            f"✅ すべてのドキュメント（{len(doc_ids)}個）の検索が完了しました！"
        )
