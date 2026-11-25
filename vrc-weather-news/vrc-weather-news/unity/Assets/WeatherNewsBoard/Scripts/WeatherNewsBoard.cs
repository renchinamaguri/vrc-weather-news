using TMPro;
using UdonSharp;
using UnityEngine;
using VRC.SDK3.Data;
using VRC.SDK3.StringLoading;
using VRC.SDKBase;
using VRC.Udon.Common.Interfaces;

/// <summary>
/// GitHub Pages に置いた data.json を定期的に読み込み、天気とニュースを表示する掲示板。
/// 各プレイヤーのローカルで動作（同期なし）。
/// </summary>
[UdonBehaviourSyncMode(BehaviourSyncMode.None)]
public class WeatherNewsBoard : UdonSharpBehaviour
{
    [Header("データURL（https://<ユーザー名>.github.io/<リポジトリ名>/data.json）")]
    public VRCUrl dataUrl;

    [Header("表示先 TextMeshPro")]
    public TextMeshProUGUI weatherText;
    public TextMeshProUGUI newsText;
    public TextMeshProUGUI forecastTitle; // 「明日 11/21(土) の天気」（任意）
    public TextMeshProUGUI forecastText;  // 明日の予報（任意。未設定なら天気欄の下に追記）
    public TextMeshProUGUI statusText;   // 更新時刻・クレジット表示（任意）

    [Header("ニュースティッカー（任意。1行ずつ切り替え表示）")]
    public TextMeshProUGUI tickerText;
    public float tickerInterval = 6f;

    [Header("ワールドの天気演出（任意）")]
    public WeatherEnvironment environment;

    [Header("再取得間隔（秒）。サーバー側は30分ごと更新なので600〜1800推奨")]
    public float refreshInterval = 900f;

    private string[] _headlines = new string[0];
    private int _tickerIndex;
    private bool _tickerRunning;

    private float _lastLoad = -999f;

    void Start()
    {
        SetStatus("読み込み中…");
        _RefreshLoop();
    }

    /// <summary>定期更新ループ（1本だけ回る）</summary>
    public void _RefreshLoop()
    {
        Load();
        SendCustomEventDelayedSeconds(nameof(_RefreshLoop), Mathf.Max(60f, refreshInterval));
    }

    /// <summary>「更新」ボタン用。連打しても10秒に1回まで</summary>
    public void Refresh()
    {
        if (Time.time - _lastLoad < 10f) return;
        SetStatus("更新中…");
        Load();
    }

    private void Load()
    {
        _lastLoad = Time.time;
        if (dataUrl == null || string.IsNullOrEmpty(dataUrl.Get()))
        {
            SetStatus("Data Url が未設定です");
            return;
        }
        VRCStringDownloader.LoadUrl(dataUrl, (IUdonEventReceiver)this);
    }

    public override void OnStringLoadSuccess(IVRCStringDownload result)
    {
        if (!VRCJson.TryDeserializeFromJson(result.Result, out DataToken root)
            || root.TokenType != TokenType.DataDictionary)
        {
            SetStatus("データ形式エラー");
            return;
        }
        DataDictionary d = root.DataDictionary;

        string fTitle = GetString(d, "forecast_title");
        string fText = GetString(d, "forecast_text");
        if (forecastTitle != null) forecastTitle.text = fTitle;
        if (forecastText != null) forecastText.text = fText;
        if (weatherText != null)
        {
            weatherText.text = (forecastText != null)
                ? GetString(d, "weather_text")
                : GetString(d, "weather_text") + "\n\n<b>" + fTitle + "</b>\n" + fText;
        }
        if (newsText != null) newsText.text = GetString(d, "news_text");

        SetStatus("更新 " + GetString(d, "updated") + "　<size=80%>" + GetString(d, "credit") + "</size>");

        // ワールドの空・光・雨などに反映
        if (environment != null && d.TryGetValue("weather", TokenType.DataList, out DataToken wTok))
        {
            environment.ApplyWeather(wTok.DataList);
        }

        // ティッカー用に見出し配列を作る
        if (d.TryGetValue("news", TokenType.DataList, out DataToken newsTok))
        {
            DataList list = newsTok.DataList;
            _headlines = new string[list.Count];
            for (int i = 0; i < list.Count; i++)
            {
                if (list[i].TokenType == TokenType.DataDictionary
                    && list[i].DataDictionary.TryGetValue("title", TokenType.String, out DataToken t))
                    _headlines[i] = t.String;
                else
                    _headlines[i] = "";
            }
            _tickerIndex = 0;
            if (tickerText != null && !_tickerRunning && _headlines.Length > 0)
            {
                _tickerRunning = true;
                Tick();
            }
        }
    }

    public override void OnStringLoadError(IVRCStringDownload result)
    {
        // 「Allow Untrusted URLs」がオフでも github.io は許可ドメインなので通常は通る
        SetStatus("取得失敗 (" + result.ErrorCode + ")");
        Debug.LogWarning("[WeatherNewsBoard] " + result.Error);
    }

    public void Tick()
    {
        if (tickerText == null || _headlines.Length == 0) { _tickerRunning = false; return; }
        _tickerIndex %= _headlines.Length;
        tickerText.text = "■ " +_headlines[_tickerIndex];
        _tickerIndex++;
        SendCustomEventDelayedSeconds(nameof(Tick), Mathf.Max(1f, tickerInterval));
    }

    private string GetString(DataDictionary d, string key)
    {
        return d.TryGetValue(key, TokenType.String, out DataToken v) ? v.String : "";
    }

    private void SetStatus(string s)
    {
        if (statusText != null) statusText.text = s;
    }
}
