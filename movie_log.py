# movie_log.py
import requests
import streamlit as st
import pandas as pd
from datetime import date
import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials

# =========================
# Secrets 設定（必須チェックあり）
# =========================
def require_secret(key: str, hint: str = ""):
    try:
        return st.secrets[key]
    except KeyError:
        st.error(f"Secret '{key}' が見つかりません。{hint}")
        st.stop()

TMDB_API_KEY: str = st.secrets.get("TMDB_API_KEY")
if not TMDB_API_KEY:
    st.error("Secret 'TMDB_API_KEY' が見つかりません。TMDBのAPIキーを設定してください。")
    st.stop()

SPREADSHEET_ID: str = st.secrets.get("spreadsheet_id")
if not SPREADSHEET_ID:
    st.error("Secret 'spreadsheet_id' が見つかりません。GoogleスプレッドシートのIDを設定してください。")
    st.stop()

SHEET_NAME: str = st.secrets.get("sheet_name", "movies")

# Google 認証（サービスアカウント）
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
gsa = require_secret(
    "google_service_account",
    "Secrets の [google_service_account] セクションにサービスアカウントJSONを設定してください。"
)
credentials = Credentials.from_service_account_info(dict(gsa), scopes=scope)
client = gspread.authorize(credentials)

# =========================
# シート準備（なければ作る / 既存に TMDB_ID を追記）
# =========================
def get_or_create_worksheet(spreadsheet_id: str, title: str):
    ss = client.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet(title)
    except WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows="2000", cols="10")
        ws.update("A1:G1", [[
            "映画を見た日", "映画名", "公開日", "監督", "評価", "コメント", "TMDB_ID"
        ]])
        return ws

    # 既存ヘッダーに TMDB_ID がなければ追加
    header = ws.row_values(1)
    if not header:
        header = ["映画を見た日", "映画名", "公開日", "監督", "評価", "コメント", "TMDB_ID"]
        ws.update("A1:G1", [header])
    elif "TMDB_ID" not in header:
        header.append("TMDB_ID")
        # A1 からヘッダ行を丸ごと更新
        end_col_letter = chr(ord('A') + len(header) - 1)
        ws.update(f"A1:{end_col_letter}1", [header])
    return ws

sheet = get_or_create_worksheet(SPREADSHEET_ID, SHEET_NAME)

# =========================
# セッション状態
# =========================
if "candidates" not in st.session_state:
    st.session_state.candidates = []
if "selected_movie_id" not in st.session_state:
    st.session_state.selected_movie_id = None
if "last_query" not in st.session_state:
    st.session_state.last_query = ""

# =========================
# UI
# =========================
st.title("🎬 映画鑑賞記録")

with st.container():
    st.subheader("映画タイトル検索")
    movie_title_input = st.text_input("映画のタイトルを入力してください", placeholder="例）トップガン")

    # 🔍 検索ボタンのみ（クリアは削除）
    if st.button("検索", use_container_width=True):
        if not movie_title_input:
            st.warning("タイトルを入力してください。")
        else:
            search_url = "https://api.themoviedb.org/3/search/movie"
            params = {
                "api_key": TMDB_API_KEY,
                "query": movie_title_input,
                "include_adult": "false",
                "language": "ja",
            }
            res = requests.get(search_url, params=params)
            if res.status_code != 200:
                st.error("TMDB検索でエラーが発生しました。")
            else:
                data = res.json()
                st.session_state.candidates = (data.get("results") or [])[:5]
                st.session_state.selected_movie_id = None
                st.session_state.last_query = movie_title_input

# =========================
# 検索結果 → 1つ確定
# =========================
if st.session_state.candidates:
    st.subheader("🔎 検索結果")
    options = []
    labels = {}
    for r in st.session_state.candidates:
        rid = r["id"]
        title = r.get("title") or r.get("original_title", "N/A")
        orig = r.get("original_title", "")
        year = (r.get("release_date") or "????")[:4]
        label = f"{title} ({orig}) - {year}"
        options.append(rid)
        labels[rid] = label

    default_index = (
        options.index(st.session_state.selected_movie_id)
        if st.session_state.selected_movie_id in options
        else 0
    )
    selected_id = st.radio(
        "該当する作品を選択してください",
        options=options,
        index=default_index if options else 0,
        format_func=lambda rid: labels.get(rid, str(rid)),
    )

    if st.button("この作品を確定"):
        st.session_state.selected_movie_id = selected_id
        st.success("作品を確定しました。下に詳細を表示します。")

# =========================
# 詳細表示（確定後）
# =========================
def show_movie_detail_by_id(movie_id: int):
    d_url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    d_params = {"api_key": TMDB_API_KEY, "language": "ja"}
    d_res = requests.get(d_url, params=d_params)
    if d_res.status_code != 200:
        st.error("TMDB詳細でエラーが発生しました。")
        return None, None

    detail = d_res.json()
    title = detail.get("title", "N/A")
    original_title = detail.get("original_title", "")
    release_date = detail.get("release_date", "N/A")
    runtime = detail.get("runtime", "N/A")
    vote_average = detail.get("vote_average", "N/A")
    vote_count = detail.get("vote_count", "N/A")
    overview = detail.get("overview", "N/A")
    poster_path = detail.get("poster_path")

    # クレジット
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

    # 詳細表示
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

    st.write("### キャスト情報")
    for actor in cast[:5]:
        name = actor.get("name", "N/A")
        character = actor.get("character", "N/A")
        st.write(f"- {name} ({character})")

    return title, (release_date, director_name)

if st.session_state.selected_movie_id:
    show_movie_detail_by_id(st.session_state.selected_movie_id)

# =========================
# 鑑賞記録フォーム（詳細表示がある時のみ）
# =========================
if st.session_state.get("selected_movie_id"):
    movie_id = int(st.session_state.selected_movie_id)
    with st.form("entry_form"):
        movie_day = st.date_input("映画を見た日", value=date.today())
        user_rating = st.selectbox(
            "評価",
            ["★☆☆☆☆", "★★☆☆☆", "★★★☆☆", "★★★★☆", "★★★★★"],
            index=2,
        )
        user_comment = st.text_area("感想コメント", value="", height=100)
        submitted = st.form_submit_button("スプレッドシートに保存")

    if submitted:
        # 詳細を再取得（保存用）
        d_url = f"https://api.themoviedb.org/3/movie/{movie_id}"
        d_params = {"api_key": TMDB_API_KEY, "language": "ja"}
        d_res = requests.get(d_url, params=d_params)
        if d_res.status_code != 200:
            st.error("保存前のTMDB詳細取得でエラーが発生しました。")
        else:
            detail = d_res.json()
            title = detail.get("title", "N/A")
            release_date = detail.get("release_date", "N/A")

            # 監督名取得
            c_url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits"
            c_params = {"api_key": TMDB_API_KEY, "language": "ja"}
            c_res = requests.get(c_url, params=c_params)
            director_name = "N/A"
            if c_res.status_code == 200:
                credits = c_res.json()
                crew = credits.get("crew", []) or []
                directors = [m for m in crew if m.get("job") == "Director"]
                if directors:
                    director_name = directors[0].get("name", "N/A")

            try:
                sheet.append_row([
                    movie_day.strftime("%Y-%m-%d"),
                    title,
                    release_date,
                    director_name,
                    user_rating,
                    user_comment,
                    str(movie_id),  # ← TMDB_ID を保存
                ])
                st.success(f"『{title}』をスプレッドシートに保存しました。")
            except Exception as e:
                st.error(f"保存中にエラーが発生しました: {e}")

# =========================
# 一覧表示（キャッシュ付き）
# =========================
@st.cache_data(ttl=60)
def load_records(_sheet):
    return _sheet.get_all_records()

st.subheader("📖 鑑賞記録")
try:
    records = load_records(sheet)
    if records:
        df = pd.DataFrame(records)

        # 表示用は TMDB_ID を隠す
        df_display = df.copy()
        if "TMDB_ID" in df_display.columns:
            df_display = df_display.drop(columns=["TMDB_ID"])

        # 1からの採番表示（画面表示だけ）
        df_display.index = range(1, len(df_display) + 1)
        df_display.index.name = "No."
        st.dataframe(df_display, use_container_width=True)

        # ---- タイトルクリックで詳細表示 ----
        st.write("### 🎯 タイトルをクリックして詳細を表示")
        if "TMDB_ID" in df.columns:
            # クリック候補を最新順にしたい場合は df = df.iloc[::-1]
            for i, row in df.iterrows():
                title_btn = row.get("映画名", "")
                tmdb_id = row.get("TMDB_ID", "")
                if not title_btn or not tmdb_id:
                    continue
                # 同名タイトルでも一意になるようにキーにIDを付与
                if st.button(title_btn, key=f"open_{tmdb_id}_{i}"):
                    try:
                        st.session_state.selected_movie_id = int(tmdb_id)
                        st.success(f"『{title_btn}』の詳細を表示します。")
                        st.rerun()
                    except Exception:
                        st.error("TMDB_ID が不正です。")
        else:
            st.info("クリック表示を有効にするには、保存時に TMDB_ID 列へIDを保存してください。")
    else:
        st.write("まだ鑑賞記録はありません。")
except Exception as e:
    st.error(f"スプレッドシートの読み込み中にエラーが発生しました: {e}")



