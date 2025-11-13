# movie_log.py
import requests
import streamlit as st
import pandas as pd
import difflib
from datetime import date
import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials

# =========================
# 設定（Secrets から取得）
# =========================
TMDB_API_KEY: str = st.secrets["TMDB_API_KEY"]
SPREADSHEET_ID: str = st.secrets["spreadsheet_id"]         # ← トップレベル
SHEET_NAME: str = st.secrets.get("sheet_name", "movies")    # ← トップレベル

# Google 認証（サービスアカウント）
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
credentials = Credentials.from_service_account_info(
    dict(st.secrets["google_service_account"]), scopes=scope
)
client = gspread.authorize(credentials)

# =========================
# シート準備（なければ作る）
# =========================
def get_or_create_worksheet(spreadsheet_id: str, title: str):
    ss = client.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet(title)
    except WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows="2000", cols="10")
        ws.update("A1:G1", [[
            "No.", "映画を見た日", "映画名", "公開日", "監督", "評価", "コメント"
        ]])
    return ws

sheet = get_or_create_worksheet(SPREADSHEET_ID, SHEET_NAME)

# =========================
# ユーティリティ
# =========================
def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()

def top_candidates(results, query, k=5):
    # results: TMDB /search の結果配列
    scored = []
    for r in results:
        title = r.get("title", "") or r.get("original_title", "")
        score = similarity(title, query)
        scored.append((score, r))
    # 類似度で降順 → 上位k件
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:k]]

# =========================
# UI
# =========================
st.title("🎬 映画情報管理アプリ（Googleスプレッドシート版）")

# セッション状態
if "selected_movie_id" not in st.session_state:
    st.session_state.selected_movie_id = None
if "last_query" not in st.session_state:
    st.session_state.last_query = ""

movie_title_input = st.text_input("映画のタイトルを入力してください", placeholder="例）トップガン")

# =========================
# 検索 → 候補提示 → 1つ選択
# =========================
candidates = []
if movie_title_input:
    # 新しいクエリなら選択をリセット
    if movie_title_input != st.session_state.last_query:
        st.session_state.selected_movie_id = None
        st.session_state.last_query = movie_title_input

    search_url = "https://api.themoviedb.org/3/search/movie"
    s_params = {
        "api_key": TMDB_API_KEY,
        "query": movie_title_input,
        "include_adult": "false",
        "language": "ja",
    }
    s_res = requests.get(search_url, params=s_params)
    if s_res.status_code != 200:
        st.error("TMDB検索でエラーが発生しました。")
        st.stop()
    s_data = s_res.json()
    results = s_data.get("results", []) or []
    if not results:
        st.warning("候補が見つかりませんでした。別のキーワードでお試しください。")
    else:
        candidates = top_candidates(results, movie_title_input, k=5)

        # 候補表示（最大5件）
        st.subheader("🔎 類似タイトル（最大5件）から選択")
        # ラジオ用の表示ラベルを作成（選択肢は id を値）
        options = []
        labels = {}
        for r in candidates:
            rid = r["id"]
            title = r.get("title") or r.get("original_title", "N/A")
            orig = r.get("original_title", "")
            year = (r.get("release_date") or "????")[:4]
            label = f"{title} ({orig}) - {year} [id:{rid}]"
            options.append(rid)
            labels[rid] = label

        # 初期選択は上位1件
        default_index = 0
        if st.session_state.selected_movie_id in options:
            default_index = options.index(st.session_state.selected_movie_id)

        selected_id = st.radio(
            "該当する作品を1つ選んでください",
            options=options,
            format_func=lambda rid: labels.get(rid, str(rid)),
            index=default_index if options else 0,
        )

        # 確定ボタン
        if st.button("この作品を確定"):
            st.session_state.selected_movie_id = selected_id
            st.success("作品を確定しました。下に詳細を表示します。")

# =========================
# 詳細表示（確定後）
# =========================
if st.session_state.selected_movie_id:
    movie_id = st.session_state.selected_movie_id

    # 詳細
    d_url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    d_params = {"api_key": TMDB_API_KEY, "language": "ja"}
    d_res = requests.get(d_url, params=d_params)
    if d_res.status_code != 200:
        st.error("TMDB詳細でエラーが発生しました。")
        st.stop()
    detail = d_res.json()
    title = detail.get("title", "N/A")
    original_title = detail.get("original_title", "")
    release_date = detail.get("release_date", "N/A")
    runtime = detail.get("runtime", "N/A")
    vote_average = detail.get("vote_average", "N/A")
    vote_count = detail.get("vote_count", "N/A")
    overview = detail.get("overview", "N/A")
    poster_path = detail.get("poster_path")

    # クレジット（監督・キャスト）
    c_url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits"
    c_params = {"api_key": TMDB_API_KEY, "language": "ja"}
    c_res = requests.get(c_url, params=c_params)
    director_name = "N/A"
    cast = []
    if c_res.status_code == 200:
        credits = c_res.json()
        crew = credits.get("crew", []) or []
        cast = credits.get("cast", []) or []
        directors = [m for m in crew if m.get("job") == "Director"]
        if directors:
            director_name = directors[0].get("name", "N/A")

    # 表示
    st.subheader(f"{title} ({original_title})")
    cols = st.columns([1, 2])
    with cols[0]:
        if poster_path:
            st.image(f"https://image.tmdb.org/t/p/w300{poster_path}", caption="Movie Poster")
    with cols[1]:
        st.markdown(f"**概要**: {overview}")
        st.markdown(f"**公開日**: {release_date}")
        st.markdown(f"**監督**: {director_name}")
        st.markdown(f"**上映時間**: {runtime} 分")
        st.markdown(f"**評価スコア**: {vote_average} /10")
        st.markdown(f"**評価数**: {vote_count} 件")

    st.write("### キャスト情報（上位5名）")
    for actor in cast[:5]:
        name = actor.get("name", "N/A")
        character = actor.get("character", "N/A")
        st.write(f"- {name} ({character})")

    # =========================
    # 鑑賞記録 追加フォーム
    # =========================
    with st.form("entry_form"):
        movie_day = st.date_input("映画を見た日", value=date.today())
        user_rating = st.selectbox(
            "評価",
            ["★☆☆☆☆", "★★☆☆☆", "★★★☆☆", "★★★★☆", "★★★★★"],
            index=0,
        )
        user_comment = st.text_area("感想コメント", value="", height=100)
        submitted = st.form_submit_button("スプレッドシートに保存")

    if submitted:
        try:
            # 既存行数を取得（ヘッダー1行）→ 次No.は行数そのまま
            rows_now = len(sheet.get_all_values())
            next_no = rows_now  # 1行目はヘッダーなので、2行目=No.1 → rows_now が No.
            sheet.append_row([
                next_no,
                movie_day.strftime("%Y-%m-%d"),
                title,
                release_date,
                director_name,
                user_rating,
                user_comment
            ])
            st.success(f"『{title}』をスプレッドシートに保存しました。")
        except Exception as e:
            st.error(f"保存中にエラーが発生しました: {e}")

# =========================
# 一覧表示（キャッシュ付き）
# =========================
@st.cache_data(ttl=60)
def load_records(_sheet):
    # 1行目をヘッダーとして dict のリストを返す
    return _sheet.get_all_records()

st.subheader("📖 鑑賞記録一覧")
try:
    records = load_records(sheet)
    if records:
        df = pd.DataFrame(records)
        # インデックスは1始まり表示にする（任意）
        df.index = range(1, len(df) + 1)
        df.index.name = "No."
        st.dataframe(df, use_container_width=True)
    else:
        st.write("まだ鑑賞記録はありません。")
except Exception as e:
    st.error(f"スプレッドシートの読み込み中にエラーが発生しました: {e}")
