# VRChat 天気＆ニュース掲示板

VRChatワールド内に「現在の天気」と「最新ニュース」を表示するシステムです。

## しくみ

```
[GitHub Actions 30分ごと]
   ├─ Open-Meteo API → 天気
   └─ RSS (NHK等)    → ニュース
        ↓ data.json を生成
[GitHub Pages]  https://<user>.github.io/<repo>/data.json
        ↓ VRCStringDownloader（ワールド内）
[Udon / TextMeshPro で表示]
```

VRChatはUdonから任意のAPIを呼べない（URLは事前定義のみ、5秒に1回まで、許可ドメイン制限あり）ため、
許可ドメインである `*.github.io` に中継用JSONを置く構成にしています。
これなら **「Allow Untrusted URLs」がオフのプレイヤーでも表示されます**。APIキー・サーバー代は不要です。

## セットアップ

### 1. GitHub 側
1. このフォルダの中身で新しい **Public** リポジトリを作る（`.github` フォルダも含める）
2. リポジトリの **Settings → Pages → Source** を **「GitHub Actions」** に変更
3. **Actions** タブ → 「Update weather & news」→ **Run workflow** で初回実行
4. `https://<ユーザー名>.github.io/<リポジトリ名>/data.json` が開けばOK

### 2. 都市・ニュースの変更
`config.json` を編集してpushするだけ。
- `cities`: 名前と緯度経度（Googleマップで右クリック→座標コピー）
- `news.feeds`: RSS/AtomのURL。複数可

### 3. Unity 側（ワンクリック）
1. VCC で作ったワールドプロジェクトに `unity/WeatherNewsBoard.unitypackage` をインポート
   （TMP Essentials のインポートを求められたら Import）
2. メニュー **Tools > Weather News Board > セットアップ**
3. data.json の URL を入力して **「シーンに配置」**
4. Build & Test

自動で作られるもの：
- 看板UI（1.6m×1.0m）… いまの天気 / 明日の天気 / ニュース / ティッカー / 更新ボタン / テスト用ボタン
- 天気演出 … 太陽光・空(Procedural Skybox)・霧・雨・雪・雷・環境音（仮の音を同梱）
- Lighting 設定（Fog オン、環境光 Color）、Directional Light が Baked なら Mixed に変更
- 日本語フォント（Noto Sans JP 同梱）から TMP フォントアセットを自動生成
- スクリプトの参照・ボタンのイベントの割り当て

天気ごとの見た目は `WeatherEnvironment` のインスペクタで `Debug Override` をオンにするか、看板の「天気テスト」「昼 / 夜」ボタンで確認できます。
細かい内容は `unity/Assets/WeatherNewsBoard/はじめに.txt` を参照。

## 調整ポイント
- 更新頻度: `update.yml` の `cron`（GitHubの仕様上5分未満は不可。実際は数分遅れることも）
- ワールド内の再取得間隔: `refreshInterval`（既定900秒）
- 天気ごとの色・明るさ: `WeatherEnvironment.cs` 冒頭のプリセット配列
- 看板のレイアウト: `Editor/WeatherBoardSetupWindow.cs` の `BuildBoard`（作成後はシーン上で自由に編集可）
- 反映する都市: `WeatherEnvironment` の `cityIndex`
- 表示の見た目: `fetch.py` の `w_lines` / `n_lines` でリッチテキストを組み立てています

## データソース
天気はすべて Open-Meteo（APIキー不要・無料・座標指定）。現在の天気、今日の最高/最低、明日の天気・気温・6時間ごとの降水確率・最大風速を取得します。
日本の座標では気象庁のモデル（MSM）が自動で使われます。

## 注意
- 天気データは Open-Meteo（CC BY 4.0）。ワールド内にクレジットを表示しています（ステータス欄）
- ニュースは見出しのみ取得します。**公開ワールドで使う場合は各RSS提供元の利用規約を確認してください**
  （NHKなど規約で用途が定められている提供元もあります）
- 60日間リポジトリに動きがないと、GitHubがスケジュール実行を自動停止します。止まったら Actions から再有効化してください
