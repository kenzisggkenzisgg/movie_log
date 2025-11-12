import requests
import streamlit as st
import pandas as pd
import difflib
from datetime import date
import gspread
from google.oauth2.service_account import Credentials

# =========================
# Googleスプレッドシート設定
# =========================
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials = Credentials.from_service_account_info(
    st.secrets["google_service_account"], scopes=scope
)
client = gspread.authorize(credentials)

spreadsheet = client.open_by_key(st.secrets["google_service_account"]["spreadsheet_id"])
sheet = spreadsheet.worksheet(st.secrets["google_service_account"]["sheet_name"])

# =========================
# TMDB API設定
# =========================
api_key = st.secrets["TMDB_API_KEY"]

st.title("🎬 映画情報管理アプリ（Googleスプレッドシート版）")

movie_title = st.text_input("映画のタイトルを入力してください", placeholder="例）トップガン")

if movie_title:
    search_url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": api_key, "query": movie_title, "include_adult": "false", "language": "ja"}
    search_response = requests.get(search_url, params=params)

    if search_response.status_code == 200:
        search_data = search_response.json()

        def get_title_similarity(s1, s2):
            return difflib.SequenceMatcher(None, s1.lower(), s2.lower()).ratio()

        most_similar_movie = max(search_data["results"], key=lambda movie: get_title_similarity(movie["title"], movie_title))
        movie_id = most_similar_movie["id"]

        detail_url = f"https://api.themoviedb.org/3/movie/{movie_id}"
        detail_params = {"api_key": api_key, "language": "ja"}
        detail_response = requests.get(detail_url, params=detail_params)

        if detail_response.status_code == 200:
            detail_data = detail_response.json()
            title = detail_data['title']
            release_date = detail_data.get('release_date', 'N/A')

            credits_url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits"
            credits_params = {"api_key": api_key, "language": "ja"}
            credits_response = requests.get(credits_url, params=credits_params)

            director_name = "N/A"
            if credits_response.status_code == 200:
                credits_data = credits_response.json()
                crew = credits_data.get("crew", [])
                directors = [member for member in crew if member.get("job") == "Director"]
                if directors:
                    director_name = directors[0].get("name", "N/A")

            st.subheader(f"{title} ({detail_data['original_title']})")

            poster_path = detail_data.get("poster_path")
            if poster_path:
                st.image(f"https://image.tmdb.org/t/p/w300{poster_path}", caption="Movie Poster")

            st.write(f"**概要**: {detail_data.get('overview', 'N/A')}")
            st.write(f"**公開日**: {release_date}")
            st.write(f"**監督**: {director_name}")
            st.write(f"**上映時間**: {detail_data.get('runtime', 'N/A')} 分")
            st.write(f"**評価スコア**: {detail_data.get('vote_average', 'N/A')} /10")

            # ユーザー入力フォーム
            st.write("### あなたの鑑賞記録を追加")
            movie_day_input = st.date_input("映画を見た日", value=date.today())
            user_rating = st.selectbox("評価", ["★☆☆☆☆", "★★☆☆☆", "★★★☆☆", "★★★★☆", "★★★★★"], index=0)
            user_comment = st.text_area("感想コメント", value="", height=100)

            if st.button("スプレッドシートに保存"):
                try:
                    # 行番号を自動計算
                    next_no = len(sheet.get_all_values())  # ヘッダー含む
                    sheet.append_row([
                        next_no,  # No.
                        movie_day_input.strftime("%Y-%m-%d"),
                        title,
                        release_date,
                        director_name,
                        user_rating,
                        user_comment
                    ])
                    st.success(f"'{title}' がスプレッドシートに追加されました！")
                except Exception as e:
                    st.error(f"保存中にエラーが発生しました: {e}")

# =========================
# 保存された映画データを表示
# =========================
st.subheader("📖 鑑賞記録一覧")

try:
    data = sheet.get_all_records()
    if data:
        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True)
    else:
        st.write("まだ鑑賞記録はありません。")
except Exception as e:
    st.error(f"スプレッドシートの読み込み中にエラー: {e}")
