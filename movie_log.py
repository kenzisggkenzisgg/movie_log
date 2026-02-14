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
gsa_raw = require_secret(
    "google_service_account",
    "Secrets の [google_service_account] セクションにサービスアカウントJSONを設定してください。"
)

# 通常のdictに変換（Secretsは書き換え不可のため）
gsa = dict(gsa_raw)

# private_key の改行を復元（Streamlit secrets 対策）
if "private_key" in gsa and isinstance(gsa["private_key"], str):
    gsa["private_key"] = gsa["private_key"].replace("\\n", "\n")

credentials = Credentials.from_service_account_info(gsa, scopes=scope)
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
# レコード読み込み（キャッシュ）
# =========================
@st.cache_data(ttl=60)
def load_records(_sheet):
    return _sheet.get_all_records()

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
        timeout=20,
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
if "year_filter" not in st.session_state:
    st.session_state.year_filter = None  # 選択中の年（例: 2025）/ None

# =========================
# UI
# =========================
st.title("🎬 映画鑑賞記録")

# -------------------------
# 映画検索
# -------------------------
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
                timeout=20,
            )
            if res.status_code != 200:
                st.error("TMDB検索でエラーが発生しました。")
            else:
                data = res.json()
                st.session_state.candidates = (data.get("results") or [])[:10]
                st.session_state.selected_movie_id = None
                st.session_state.last_query = movie_title_input

# -------------------------
# 検索結果 → 1つ確定
# -------------------------
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

# -------------------------
# 詳細表示（確定後）
# -------------------------
if st.session_state.selected_movie_id:
    movie_id = st.session_state.selected_movie_id
    d_res = requests.get(
        f"https://api.themoviedb.org/3/movie/{movie_id}",
        params={"api_key": TMDB_API_KEY, "language": "ja"},
        timeout=20,
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
        timeout=20,
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
                caption="Movie Poster",
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

    # -------------------------
    # 鑑賞記録フォーム
    # -------------------------
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
                st.rerun()
            except Exception as e:
                st.error(f"保存中にエラーが発生しました: {e}")

# =========================
# 鑑賞記録（年別バナー＋カード表示）
# =========================
st.subheader("📖 鑑賞記録（年別）")

try:
    records = load_records(sheet)
    if not records:
        st.write("まだ鑑賞記録はありません。")
    else:
        df = pd.DataFrame(records)

        # 鑑賞日を日付型に変換 & 年を抽出
        df["鑑賞日_dt"] = pd.to_datetime(df["鑑賞日"], errors="coerce")
        df["year"] = df["鑑賞日_dt"].dt.year

        years = sorted(df["year"].dropna().unique(), reverse=True)
        years = [int(y) for y in years]

        if years:
            st.markdown("### 📅 年を選択（同じ年をもう一度押すと非表示）")
            banner_cols = st.columns(len(years))

            for idx, y in enumerate(years):
                with banner_cols[idx]:
                    if st.button(f"{y}年", use_container_width=True, key=f"year_btn_{y}"):
                        # 同じ年なら解除／別の年なら切り替え
                        st.session_state.year_filter = None if st.session_state.year_filter == y else y

        current_year = st.session_state.year_filter
        if current_year is None:
            st.info("年のバナーをクリックすると、その年の鑑賞記録が表示されます。")
        else:
            df_filtered = df[df["year"] == current_year].copy()
            df_filtered = df_filtered.sort_values("鑑賞日_dt", ascending=False)

            if df_filtered.empty:
                st.info(f"{current_year}年の鑑賞記録はありません。")
            else:
                st.markdown(f"#### 📂 表示対象：**{current_year}年**")
                st.caption("※ タイトルをタップすると、上部に映画の詳細が表示されます（スマホ向けカード表示）")

                for i, row in df_filtered.iterrows():
                    with st.container():
                        st.markdown("---")

                        title_val = row["タイトル"]
                        rating_val = row.get("評価", "")

                        if st.button(f"🎬 {title_val}（{rating_val}）", key=f"title_btn_{current_year}_{i}"):
                            tmdb_id = resolve_tmdb_id_by_title(
                                title=title_val,
                                release_date=row.get("公開日", "")
                            )
                            if tmdb_id:
                                st.session_state.selected_movie_id = tmdb_id
                                st.success(f"『{title_val}』の詳細を上部に表示します。")
                                st.rerun()
                            else:
                                st.warning("TMDBで該当作品を見つけられませんでした。")

                        st.markdown(f"**鑑賞日**：{row.get('鑑賞日', '')}")
                        st.markdown(f"**公開日**：{row.get('公開日', '')}")
                        st.markdown(f"**監督名**：{row.get('監督名', '')}")

                        comment = row.get("感想", "")
                        if comment:
                            with st.expander("✏ 感想を見る"):
                                st.write(comment)

except Exception as e:
    st.error(f"スプレッドシートの読み込み中にエラーが発生しました: {e}")

# =========================
# 監督ランキング（本数×評価スコア）
# =========================
st.subheader("🏆 監督ランキング（本数 × 評価）")

try:
    records = load_records(sheet)
    if not records:
        st.write("まだ鑑賞記録がないため、ランキングを作成できません。")
    else:
        df = pd.DataFrame(records)

        # 評価（例: "★★★★☆"） → 星の数（4 など）に変換（「★」の数を数える）
        df["星数"] = df["評価"].astype(str).str.count("★")

        # 監督名が空の行は「不明」として扱う
        df["監督名"] = df["監督名"].replace("", "不明").fillna("不明")

        grouped = (
            df.groupby("監督名")
              .agg(
                  本数=("タイトル", "count"),
                  合計スコア=("星数", "sum"),
              )
        )
        grouped["平均評価"] = grouped["合計スコア"] / grouped["本数"]

        grouped = grouped.sort_values("合計スコア", ascending=False).reset_index()
        grouped.index = range(1, len(grouped) + 1)
        grouped.index.name = "順位"

        st.dataframe(
            grouped[["監督名", "本数", "合計スコア", "平均評価"]].head(10),
            use_container_width=True,
        )

except Exception as e:
    st.error(f"監督ランキングの作成中にエラーが発生しました: {e}")








