#!/usr/bin/env python3
"""
koyomi-bot: 二十四節気七十二候を Slack に投稿する bot
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from skyfield import api as skyfield_api
from skyfield.framelib import ecliptic_frame


def load_sekki_data() -> dict:
    """七十二候データを読み込む"""
    data_path = Path(__file__).parent / "data" / "sekki.json"
    with open(data_path, encoding="utf-8") as f:
        return json.load(f)


def get_sun_longitude(dt: datetime) -> float:
    """指定日時の太陽黄経を計算（度）"""
    # ~/.skyfield/ にデータを保存（GitHub Actions でキャッシュ可能）
    load = skyfield_api.Loader("~/.skyfield", verbose=False)
    ts = load.timescale()
    eph = load("de421.bsp")

    earth = eph["earth"]
    sun = eph["sun"]

    t = ts.from_datetime(dt.replace(tzinfo=timezone.utc))

    # 地球から見た太陽の位置
    astrometric = earth.at(t).observe(sun)
    _, lon, _ = astrometric.apparent().frame_latlon(ecliptic_frame)

    return lon.degrees


def find_current_ko(longitude: float, data: dict) -> tuple[dict, dict, int]:
    """
    太陽黄経から現在の節気と候を特定

    Returns:
        (sekki, ko, ko_index): 節気データ、候データ、候インデックス(0-2)
    """
    sekki_list = data["sekki"]

    # 各節気の開始黄経でソート（立春315°から始まる）
    for i, sekki in enumerate(sekki_list):
        sekki_lon = sekki["longitude"]
        next_sekki = sekki_list[(i + 1) % 24]
        next_lon = next_sekki["longitude"]

        # 0° をまたぐ場合の処理
        if sekki_lon > next_lon:  # 例: 大寒(300) -> 立春(315) -> ... -> 春分(0)
            if longitude >= sekki_lon or longitude < next_lon:
                # この節気の範囲内
                return _find_ko_in_sekki(longitude, sekki, next_lon)
        else:
            if sekki_lon <= longitude < next_lon:
                return _find_ko_in_sekki(longitude, sekki, next_lon)

    # フォールバック（ありえないはずだが）
    return sekki_list[0], sekki_list[0]["ko"][0], 0


def _find_ko_in_sekki(longitude: float, sekki: dict, next_sekki_lon: float) -> tuple[dict, dict, int]:
    """節気内の候を特定（3等分）"""
    sekki_lon = sekki["longitude"]

    # 節気の範囲を計算（0° をまたぐ場合を考慮）
    if sekki_lon > next_sekki_lon:
        span = (360 - sekki_lon) + next_sekki_lon
        if longitude >= sekki_lon:
            offset = longitude - sekki_lon
        else:
            offset = (360 - sekki_lon) + longitude
    else:
        span = next_sekki_lon - sekki_lon
        offset = longitude - sekki_lon

    # 3等分して候を決定
    ko_span = span / 3
    ko_index = min(int(offset / ko_span), 2)

    return sekki, sekki["ko"][ko_index], ko_index


def format_message(date: datetime, sekki: dict, ko: dict, ko_index: int) -> str:
    """Slack 投稿用メッセージを生成"""
    date_str = date.strftime("%Y/%m/%d")
    ko_names = ["初候", "次候", "末候"]

    return f"*{date_str} dev-daily* {ko['emoji']}\n> {sekki['name']}・{ko_names[ko_index]}「{ko['name']}」（{ko['reading']}）"


ICON_URL = "https://raw.githubusercontent.com/carrotRakko/koyomi-bot/main/assets/icon.png"
BOT_NAME = "暦ぼっと"


def post_to_slack(message: str, webhook_url: str) -> bool:
    """Slack に投稿"""
    try:
        response = requests.post(
            webhook_url,
            json={
                "text": message,
                "username": BOT_NAME,
                "icon_url": ICON_URL,
            },
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Slack 投稿エラー: {e}")
        return False


def main():
    # 日本時間で今日の日付を取得
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)

    # データ読み込み
    data = load_sekki_data()

    # 太陽黄経を計算
    longitude = get_sun_longitude(now)
    print(f"日時: {now}")
    print(f"太陽黄経: {longitude:.2f}°")

    # 現在の候を特定
    sekki, ko, ko_index = find_current_ko(longitude, data)
    print(f"節気: {sekki['name']}（{sekki['reading']}）")
    print(f"候: {ko['name']}（{ko['reading']}）")
    print(f"絵文字: {ko['emoji']}")

    # メッセージ生成
    message = format_message(now, sekki, ko, ko_index)
    print(f"\n投稿メッセージ:\n{message}")

    # Slack 投稿（環境変数から Webhook URL を取得）
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if webhook_url:
        success = post_to_slack(message, webhook_url)
        print(f"\nSlack 投稿: {'成功' if success else '失敗'}")
    else:
        print("\nSLACK_WEBHOOK_URL が設定されていないため、投稿をスキップ")


if __name__ == "__main__":
    main()
