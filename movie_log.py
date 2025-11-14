import requests
import streamlit as st
import pandas as pd
from datetime import date
import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials

# =========================
# Secrets 設定
# =========================
def require_secret(key: str, hint: str = ""):
    try:
        return st.secrets[key]
    except KeyError:
        st.error(f"Secret '{key}' が見つかりません。{hint}")
        st.stop()

TMDB_API_KEY = st.secrets.get("TMDB_API_KEY")
SPREADSHEET_ID = st.secrets.get("spreadsheet_id")
SHEET_NAME = st.secrets.get("sheet_name", "movies")

if not TMDB_API_KEY or not SPREADSHEET_ID:
    st.error("Secrets に TMDB_API_KEY と spreadsheet_id を設定してください。")
    st.stop()

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
gsa = require_secret("google_service_account")
credentials = Credentials.from_service_account_info(dict(gsa), scopes=scope)
client = gspread.authorize(credentials)

# =========================
# シート初期化（No列・TMDB_ID列なし）
# =========================
def get_or_create_worksheet(spreadsheet_id: str, title: str):
    ss = client.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet(title)
    except WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows="2000", cols="10")
        ws.update("A1:F1", [[
            "映画を見た日", "映画名", "公開日", "監督", "評価", "コメント"
        ]])
    return ws

sheet = get_or_create_worksheet(SPREADSHEET_ID, SHEET_NAME)

# =========================
# TMDB ID 解決関数
# =========================
def resolve_tmdb_id_by_title(title: str, release_date: str | None = None) -> int | None:
    """タイトル（＋公開年）からTMDBのIDを推定"""
    if not title:
        return None

    res = requests.get(
        "https://api.themoviedb.org/3/search/movie",
        params={
            "api_key": TMDB_API_KEY,
            "query": title,
            "include_adult": "false",
            "language": "ja",
        },
    )
    if res.status_code != 200:
        return None
    results = res.json().get("results", [])
    if not results:
        return None

    year = (release_date or "")[:4] if release_date else None
    if year:
        for m in results:
            if (m.get("release_date") or "")[:4] == year:
                return m["id"]
    return results[0]["id"]

# =========================
# セッション管理
# =========================
if "candidates" not in st.session_state:
    st.session_state.candidates = []
if "selected_movie_id" not in st.session_state:
    st.session_state.selected_movie_id = None

# =========================
# UI
# =========================
st.title("🎬 映画情報管理アプリ（Googleスプレッドシート版）")

st.subheader("映画タイトル検索")
movie_title_input = st.text_input("映画のタイトルを入力してください", placeholder="例）トップガン")

if st.button("検索", use_container_width=True):
    if not movie_title_input:
        st.warning("タイトルを入力してください。")
    else:
        res = requests.get(
            "https://api.themoviedb.org/3/search/movie",
            params={
                "api_key": TMDB_API_KEY,
                "query": movie_title_input,
                "include_adult": "false",
                "language": "ja",
            },
        )
        if res.status_code != 200:
            st.error("TMDB検索でエラーが発生しました。")
        else:
            data = res.json()
            st.session_state.candidates = (data.get("results") or [])[:5]
            st.session_state.selected_movie_id = None

# =========================
# 検索結果 → 選択
# =========================
if st.session_state.candidates:
    st.subheader("🔎 検索結果（最大5件）")
    for i, r in enumerate(st.session_state.candidates):
        title = r.get("title") or r.get("original_title", "")
        year = (r.get("release_date") or "????")[:4]
        label = f"{title} ({year})"
        if st.button(label, key=f"cand_{i}"):
            st.session_state.selected_movie_id = r["id"]
            st.success(f"『{title}』の詳細を下に表示します。")
            st.experimental_rerun()

# =========================
# 詳細表示
# =========================
if st.session_state.selected_movie_id:
    movie_id = st.session_state.selected_movie_id
    d = requests.get(
        f"https://api.themoviedb.org/3/movie/{movie_id}",
        params={"api_key": TMDB_API_KEY, "language": "ja"},
    ).json()

    title = d.get("title", "")
    original_title = d.get("original_title", "")
    release_date = d.get("release_date", "")
    runtime = d.get("runtime", "不明")
    overview = d.get("overview", "")
    vote_average = d.get("vote_average", "")
    poster = d.get("poster_path")

    # クレジット（監督・キャスト）
    c = requests.get(
        f"https://api.themoviedb.org/3/movie/{movie_id}/credits",
        params={"api_key": TMDB_API_KEY, "language": "ja"},
    ).json()
    director = "N/A"
    crew = c.get("crew", [])
    for p in crew:
        if p.get("job") == "Director":
            director = p.get("name", "N/A")
            break

    st.subheader(f"{title} ({original_title})")
    cols = st.columns([1, 2])
    with cols[0]:
        if poster:
            st.image(f"https://image.tmdb.org/t/p/w300{poster}")
    with cols[1]:
        st.markdown(f"**公開日**: {release_date}")
        st.markdown(f"**監督**: {director}")
        st.markdown(f"**上映時間**: {runtime}分")
        st.markdown(f"**評価スコア**: {vote_average}/10")
        st.markdown(f"**概要**: {overview}")

    # 鑑賞記録フォーム
    with st.form("entry_form"):
        date_seen = st.date_input("映画を見た日", value=date.today())
        rating = st.selectbox("評価", ["★☆☆☆☆", "★★☆☆☆", "★★★☆☆", "★★★★☆", "★★★★★"], index=2)
        comment = st.text_area("感想コメント", height=100)
        if st.form_submit_button("スプレッドシートに保存"):
            try:
                sheet.append_row([
                    date_seen.strftime("%Y-%m-%d"),
                    title,
                    release_date,
                    director,
                    rating,
                    comment,
                ])
                st.success(f"『{title}』をスプレッドシートに保存しました。")
            except Exception as e:
                st.error(f"保存中にエラーが発生しました: {e}")

# =========================
# 一覧表示（タイトルクリック対応）
# =========================
@st.cache_data(ttl=60)
def load_records(_sheet):
    return _sheet.get_all_records()

st.subheader("📖 鑑賞記録一覧")
try:
    recs = load_records(sheet)
    if recs:
        df = pd.DataFrame(recs)
        df.index = range(1, len(df) + 1)
        df.index.name = "No."
        st.dataframe(df, use_container_width=True)
        st.caption("タイトルをクリックすると、その映画の詳細を下に表示します。")

        for i, row in df.reset_index().iterrows():
            c1, c2, c3 = st.columns([1, 6, 3])
            with c1:
                st.write(row["No."])
            with c2:
                if st.button(row["映画名"], key=f"hist_{i}"):
                    tmdb_id = resolve_tmdb_id_by_title(row["映画名"], row.get("公開日", ""))
                    if tmdb_id:
                        st.session_state.selected_movie_id = tmdb_id
                        st.success(f"『{row['映画名']}』の詳細を下に表示します。")
                        st.experimental_rerun()
                    else:
                        st.warning("TMDBで該当作品を見つけられませんでした。")
            with c3:
                st.write(row.get("公開日", ""))
    else:
        st.write("まだ鑑賞記録はありません。")
except Exception as e:
    st.error(f"スプレッドシートの読み込み中にエラーが発生しました: {e}")




