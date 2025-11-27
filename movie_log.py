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
# シート準備（なければ作る）
# =========================
def get_or_create_worksheet(spreadsheet_id: str, title: str):
    ss = client.open_by_key(spreadsheet_id)
    try:
        ws = ss.worksheet(title)
    except WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows="2000", cols="10")
        # カラム名は固定
        ws.update("A1:F1", [[
            "鑑賞日", "タイトル", "公開日", "監督名", "評価", "感想"
        ]])
    return ws

sheet = get_or_create_worksheet(SPREADSHEET_ID, SHEET_NAME)

# =========================
# TMDB ID 解決（タイトルクリック用）
# =========================
def resolve_tmdb_id_by_title(title: str, release_date: str | None = None) -> int | None:
    """
    タイトル（＋公開年があれば年）から TMDB の movie_id を推定。
    見つからなければ None。
    """
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

    year = None
    if release_date and release_date not in ("N/A", "不明"):
        year = str(release_date)[:4]

    if year:
        for m in results:
            if (m.get("release_date") or "")[:4] == year:
                return m["id"]

    return results[0]["id"]

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
    movie_title_input = st.text_input(
        "映画のタイトルを入力してください", placeholder="例）トップガン"
    )

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
        t = r.get("title") or r.get("original_title", "N/A")
        orig = r.get("original_title", "")
        year = (r.get("release_date") or "????")[:4]
        label = f"{t} ({orig}) - {year}"
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
if st.session_state.selected_movie_id:
    movie_id = st.session_state.selected_movie_id
    d_res = requests.get(
        f"https://api.themoviedb.org/3/movie/{movie_id}",
        params={"api_key": TMDB_API_KEY, "language": "ja"},
    )
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

    # クレジット
    c_res = requests.get(
        f"https://api.themoviedb.org/3/movie/{movie_id}/credits",
        params={"api_key": TMDB_API_KEY, "language": "ja"},
    )
    director_name = "N/A"
    cast = []
    if c_res.status_code == 200:
        credits = c_res.json()
        crew = credits.get("crew", []) or []
        cast = credits.get("cast", []) or []
        directors = [m for m in crew if m.get("job") == "Director"]
        if directors:
            director_name = directors[0].get("name", "N/A")

    st.subheader(f"{title} ({original_title})")
    cols = st.columns([1, 2])
    with cols[0]:
        if poster_path:
            st.image(
                f"https://image.tmdb.org/t/p/w300{poster_path}",
                caption="Movie Poster"
            )
    with cols[1]:
        st.markdown(f"**概要**: {overview}")
        st.markdown(f"**公開日**: {release_date}")
        st.markdown(f"**監督名**: {director_name}")
        st.markdown(f"**上映時間**: {runtime} 分")
        st.markdown(f"**評価スコア**: {vote_average} /10")
        st.markdown(f"**評価数**: {vote_count} 件")

    st.write("### キャスト情報")
    for actor in cast[:5]:
        name = actor.get("name", "N/A")
        character = actor.get("character", "N/A")
        st.write(f"- {name} ({character})")

    # =========================
    # 鑑賞記録フォーム（シートのカラム名と合わせる）
    # =========================
    with st.form("entry_form"):
        movie_day = st.date_input("鑑賞日", value=date.today())
        user_rating = st.selectbox(
            "評価",
            ["★☆☆☆☆", "★★☆☆☆", "★★★☆☆", "★★★★☆", "★★★★★"],
            index=2,
        )
        user_comment = st.text_area("感想コメント", value="", height=100)
        submitted = st.form_submit_button("スプレッドシートに保存")

        if submitted:
            try:
                sheet.append_row([
                    movie_day.strftime("%Y-%m-%d"),  # 鑑賞日
                    title,                           # タイトル
                    release_date,                    # 公開日
                    director_name,                   # 監督名
                    user_rating,                     # 評価
                    user_comment,                    # 感想
                ])
                st.success(f"『{title}』をスプレッドシートに保存しました。")

                # キャッシュをクリアして再実行 → 一覧を即時更新
                st.cache_data.clear()
                try:
                    st.rerun()
                except Exception:
                    st.experimental_rerun()
            except Exception as e:
                st.error(f"保存中にエラーが発生しました: {e}")

# =========================
# 一覧表示（新しい順・タイトルクリック）
# =========================
@st.cache_data(ttl=60)
def load_records(_sheet):
    return _sheet.get_all_records()

st.subheader("📖 鑑賞記録（新しい順）")

try:
    records = load_records(sheet)
    if not records:
        st.write("まだ鑑賞記録はありません。")
    else:
        df = pd.DataFrame(records)

        # ▼ 新しい順に並べ替え
        df["_sort_key"] = pd.to_datetime(df["鑑賞日"], errors="coerce")
        df = df.sort_values("_sort_key", ascending=False, na_position="last").drop(columns="_sort_key")

        st.caption("※ タイトルをタップすると、上部に映画の詳細が表示されます（スマホ向けカード表示）")

        # ▼ 1レコード＝1カードで縦に並べる
        for i, row in df.iterrows():
            with st.container():
                st.markdown("---")  # カードの区切り線（不要なら消してOK）

                # タイトル＋評価を一番上に大きめに
                title_val = row["タイトル"]
                rating_val = row.get("評価", "")

                # タイトルをボタンに（スマホだとタップしやすい）
                if st.button(f"🎬 {title_val}（{rating_val}）", key=f"title_btn_{i}"):
                    tmdb_id = resolve_tmdb_id_by_title(
                        title=title_val,
                        release_date=row.get("公開日", "")
                    )
                    if tmdb_id:
                        st.session_state.selected_movie_id = tmdb_id
                        st.success(f"『{title_val}』の詳細を上部に表示します。")
                        try:
                            st.rerun()
                        except Exception:
                            st.experimental_rerun()
                    else:
                        st.warning("TMDBで該当作品を見つけられませんでした。")

                # それ以外の情報は縦に並べる
                st.markdown(f"**鑑賞日**：{row.get('鑑賞日', '')}")
                st.markdown(f"**公開日**：{row.get('公開日', '')}")
                st.markdown(f"**監督名**：{row.get('監督名', '')}")

                # 感想は長くなりがちなので折りたたみもアリ
                comment = row.get("感想", "")
                if comment:
                    with st.expander("感想を見る"):
                        st.write(comment)

except Exception as e:
    st.error(f"スプレッドシートの読み込み中にエラーが発生しました: {e}")








