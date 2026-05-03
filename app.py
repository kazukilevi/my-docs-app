import streamlit as st
import re
import unicodedata
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- アプリの設定 ---
st.set_page_config(page_title="Google Docs一括検索", layout="wide")

# --- 秘密鍵の安全な読み込み ---
@st.cache_resource
def get_docs_service():
    # Streamlit Cloudの"Secrets"設定に貼り付ける内容を読み込む
    info = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/documents.readonly"]
    )
    return build("docs", "v1", credentials=creds)

docs_service = get_docs_service()

# --- 検索ロジック (元のコードをベースに最適化) ---
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
    paras_orig = [p.strip() for p in text.split("\n\n") if p.strip()] if within_para else [text]
    paras_norm = [normalize_for_search(p) for p in paras_orig]
    groups_norm = [[normalize_for_search(k) for k in group] for group in groups]
    not_keys_norm = [normalize_for_search(nk) for nk in not_keys]

    hits = []
    for p_orig, p_norm in zip(paras_orig, paras_norm):
        if all(any(k in p_norm for k in group) for group in groups_norm) \
           and not any(nk in p_norm for nk in not_keys_norm):
            hits.append(p_orig)
    return hits

# --- 画面レイアウト ---
st.title("🔎 Google Docs 一括検索")

with st.sidebar:
    st.header("1. ドキュメント設定")
    DEFAULT_DOCS = "https://docs.google.com/document/d/1_FbN2fK4A8cMp7j9R8Nm9hKi_f_Cwe9pFq0TYzJPo6A/edit\n(他URLもここに)"
    docs_raw = st.text_area("対象URL（複数可）", value=DEFAULT_DOCS, height=250)
    para_chk = st.checkbox("段落単位で検索する", value=True)

st.header("2. 検索条件")
col1, col2 = st.columns([2, 1])
with col1:
    groups_input = st.text_area("条件（1行に書くとOR、行を変えるとAND）", placeholder="例：東京 大阪\n出張")
with col2:
    not_input = st.text_input("除外キーワード（NOT）")

if st.button("検索を実行する", type="primary"):
    doc_ids = [d.split("/d/")[1].split("/")[0] for d in re.split(r"[\s,]+", docs_raw.strip()) if "/d/" in d]
    groups = [g.split() for g in groups_input.splitlines() if g.strip()]
    not_keys = not_input.split()
    
    if not doc_ids:
        st.error("有効なドキュメントURLが見つかりません。")
    else:
        results = []
        progress_bar = st.progress(0)
        
        for i, did in enumerate(doc_ids):
            title, text = get_doc_content(did)
            hits = search_text_grouped(text, groups, not_keys, para_chk)
            results.append({"title": title, "hits": hits})
            progress_bar.progress((i + 1) / len(doc_ids))

        st.success(f"検索完了！ 総ヒット数: {sum(len(r['hits']) for r in results)}件")
        
        # 結果表示（タブ）
        if results:
            tabs = st.tabs([f"{r['title'][:10]}... ({len(r['hits'])})" for r in results])
            for i, tab in enumerate(tabs):
                with tab:
                    st.subheader(results[i]['title'])
                    if results[i]['hits']:
                        for h in results[i]['hits']:
                            st.info(h)
                    else:
                        st.write("該当する箇所はありませんでした。")