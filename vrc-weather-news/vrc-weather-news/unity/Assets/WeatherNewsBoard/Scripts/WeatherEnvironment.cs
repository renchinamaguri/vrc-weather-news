using System;
using UdonSharp;
using UnityEngine;
using VRC.SDK3.Data;
using VRC.SDKBase;

/// <summary>
/// 実際の天気データをワールドの環境（太陽光・空・霧・環境光・雨・雪・雷・環境音）に反映する。
/// WeatherNewsBoard からデータを受け取る。各プレイヤーのローカルで動作。
/// </summary>
[UdonBehaviourSyncMode(BehaviourSyncMode.None)]
public class WeatherEnvironment : UdonSharpBehaviour
{
    // 天気カテゴリ
    public const int CLEAR = 0, PARTLY = 1, CLOUDY = 2, FOG = 3, RAIN = 4, SNOW = 5, THUNDER = 6;

    [Header("どの都市の天気を反映するか（config.json の cities の順番, 0始まり）")]
    public int cityIndex = 0;

    [Header("ライト・空")]
    public Light sun;                    // Realtime / Mixed の Directional Light
    public Material skyboxMaterial;      // Skybox/Procedural 推奨（_Exposure, _AtmosphereThickness, _SkyTint を変化）
    public bool controlFog = true;
    public bool controlAmbient = true;   // Lighting > Environment Lighting Source = Color のとき有効

    [Header("太陽の向きを現地の時刻に合わせる")]
    public bool followRealTime = true;
    public float sunYaw = -30f;

    [Header("パーティクル（プレイヤーの頭上に追従させる）")]
    public ParticleSystem rain;
    public ParticleSystem snow;
    public Transform followPlayerRoot;   // rain/snow の親。ローカルプレイヤーに追従
    public float followHeight = 8f;

    [Header("雷")]
    public Light lightningLight;         // 普段は無効にしておく
    public AudioSource thunderAudio;
    public Vector2 thunderInterval = new Vector2(8f, 25f);

    [Header("環境音（ループ）")]
    public AudioSource rainLoop;
    public AudioSource windLoop;
    public float maxRainVolume = 0.6f;
    public float maxWindVolume = 0.5f;

    [Header("切り替えにかける秒数")]
    public float transitionSeconds = 8f;

    [Header("テスト用（オンにすると実データを無視）")]
    public bool debugOverride = false;
    public int debugCategory = RAIN;
    public bool debugIsDay = true;

    // ---- プリセット（カテゴリ順: 晴/晴曇/曇/霧/雨/雪/雷）----
    private float[] pSunInt   = { 1.25f, 1.0f, 0.55f, 0.45f, 0.35f, 0.6f, 0.25f };
    private float[] pFog      = { 0.002f, 0.003f, 0.007f, 0.045f, 0.014f, 0.018f, 0.016f };
    private float[] pExposure = { 1.3f, 1.2f, 0.8f, 0.75f, 0.6f, 0.9f, 0.45f };
    private float[] pAtmos    = { 1.0f, 1.2f, 2.0f, 2.6f, 2.6f, 2.0f, 3.2f };
    private Color[] pSunCol, pAmb, pFogCol, pTint;

    // 目標値と現在値
    private float tSunInt, tFog, tExp, tAtm, tRain, tSnow, tWind;
    private Color tSunCol, tAmb, tFogCol, tTint;
    private float cSunInt, cFog, cExp, cAtm, cRain, cSnow, cWind;
    private Color cSunCol, cAmb, cFogCol, cTint;

    private int _category = CLEAR;
    private bool _isDay = true;
    private float _windMs;
    private int _utcOffset = 9 * 3600;
    private float _baseRainRate, _baseSnowRate;
    private float _nextThunder;
    private bool _initialized;

    void Start()
    {
        pSunCol = new Color[] {
            new Color(1f, 0.96f, 0.88f), new Color(1f, 0.95f, 0.88f), new Color(0.85f, 0.88f, 0.92f),
            new Color(0.85f, 0.87f, 0.9f), new Color(0.7f, 0.75f, 0.82f), new Color(0.9f, 0.93f, 1f),
            new Color(0.6f, 0.62f, 0.72f) };
        pAmb = new Color[] {
            new Color(0.55f, 0.6f, 0.7f), new Color(0.52f, 0.56f, 0.64f), new Color(0.45f, 0.47f, 0.5f),
            new Color(0.5f, 0.52f, 0.55f), new Color(0.35f, 0.38f, 0.42f), new Color(0.6f, 0.63f, 0.7f),
            new Color(0.25f, 0.27f, 0.32f) };
        pFogCol = new Color[] {
            new Color(0.7f, 0.8f, 0.92f), new Color(0.72f, 0.78f, 0.86f), new Color(0.62f, 0.64f, 0.67f),
            new Color(0.78f, 0.79f, 0.8f), new Color(0.5f, 0.53f, 0.57f), new Color(0.85f, 0.87f, 0.9f),
            new Color(0.32f, 0.33f, 0.38f) };
        pTint = new Color[] {
            new Color(0.5f, 0.5f, 0.5f), new Color(0.52f, 0.52f, 0.52f), new Color(0.6f, 0.6f, 0.6f),
            new Color(0.7f, 0.7f, 0.7f), new Color(0.55f, 0.57f, 0.6f), new Color(0.75f, 0.77f, 0.8f),
            new Color(0.4f, 0.4f, 0.45f) };

        if (rain != null) { var e = rain.emission; _baseRainRate = e.rateOverTimeMultiplier; e.rateOverTimeMultiplier = 0f; }
        if (snow != null) { var e = snow.emission; _baseSnowRate = e.rateOverTimeMultiplier; e.rateOverTimeMultiplier = 0f; }
        if (lightningLight != null) lightningLight.enabled = false;
        if (skyboxMaterial != null) RenderSettings.skybox = skyboxMaterial;
        if (controlFog) RenderSettings.fog = true;

        if (debugOverride) SetTargets(debugCategory, 0.7f, debugIsDay, 3f);
        else SetTargets(CLEAR, 0f, true, 0f);
        SnapToTargets();
        _initialized = true;
    }

    /// <summary>WeatherNewsBoard から呼ばれる。data.json の "weather" 配列を渡す。</summary>
    public void ApplyWeather(DataList weatherList)
    {
        if (debugOverride || weatherList == null || weatherList.Count == 0) return;
        int i = Mathf.Clamp(cityIndex, 0, weatherList.Count - 1);
        if (weatherList[i].TokenType != TokenType.DataDictionary) return;
        DataDictionary w = weatherList[i].DataDictionary;

        int code = (int)GetNum(w, "code", 0);
        bool isDay = GetNum(w, "is_day", 1) > 0.5;
        _windMs = (float)GetNum(w, "wind", 0);
        _utcOffset = (int)GetNum(w, "utc_offset", 9 * 3600);

        int cat = CodeToCategory(code);
        SetTargets(cat, CodeToIntensity(code), isDay, _windMs);
        if (!_initialized) SnapToTargets();
    }

    /// <summary>ワールド内ボタン用：天気を順番に切り替えてテスト</summary>
    public void DebugNext()
    {
        debugOverride = true;
        debugCategory = (debugCategory + 1) % 7;
        SetTargets(debugCategory, 0.7f, debugIsDay, 4f);
    }

    public void DebugToggleDayNight()
    {
        debugOverride = true;
        debugIsDay = !debugIsDay;
        SetTargets(debugCategory, 0.7f, debugIsDay, 4f);
    }

    // ---------------------------------------------------------------

    private int CodeToCategory(int c)
    {
        if (c <= 1) return CLEAR;
        if (c == 2) return PARTLY;
        if (c == 3) return CLOUDY;
        if (c == 45 || c == 48) return FOG;
        if ((c >= 71 && c <= 77) || c == 85 || c == 86) return SNOW;
        if (c >= 95) return THUNDER;
        if ((c >= 51 && c <= 67) || (c >= 80 && c <= 82)) return RAIN;
        return CLOUDY;
    }

    private float CodeToIntensity(int c)
    {
        switch (c)
        {
            case 51: case 56: case 61: case 66: case 71: case 80: case 85: return 0.35f;
            case 53: case 63: case 73: case 81: case 77: return 0.65f;
            case 55: case 57: case 65: case 67: case 75: case 82: case 86:
            case 95: case 96: case 99: return 1f;
        }
        return 0f;
    }

    private void SetTargets(int cat, float intensity, bool isDay, float wind)
    {
        _category = Mathf.Clamp(cat, 0, 6);
        _isDay = isDay;

        tSunInt = pSunInt[_category];
        tSunCol = pSunCol[_category];
        tAmb = pAmb[_category];
        tFog = pFog[_category];
        tFogCol = pFogCol[_category];
        tExp = pExposure[_category];
        tAtm = pAtmos[_category];
        tTint = pTint[_category];

        if (!isDay)
        {
            // 夜：月明かり（青白く暗く）
            tSunInt *= 0.15f;
            tSunCol = Color.Lerp(tSunCol, new Color(0.55f, 0.65f, 1f), 0.7f);
            tAmb *= 0.25f;
            tFogCol *= 0.2f;
            tExp *= 0.12f;
        }

        tRain = (_category == RAIN || _category == THUNDER) ? Mathf.Max(intensity, 0.35f) : 0f;
        tSnow = (_category == SNOW) ? Mathf.Max(intensity, 0.35f) : 0f;
        tWind = Mathf.Clamp01(wind / 12f);

        if (_category == THUNDER) _nextThunder = Time.time + UnityEngine.Random.Range(thunderInterval.x, thunderInterval.y);
    }

    private void SnapToTargets()
    {
        cSunInt = tSunInt; cSunCol = tSunCol; cAmb = tAmb; cFog = tFog; cFogCol = tFogCol;
        cExp = tExp; cAtm = tAtm; cTint = tTint; cRain = tRain; cSnow = tSnow; cWind = tWind;
        ApplyCurrent();
    }

    void Update()
    {
        if (!_initialized) return;
        float k = Mathf.Clamp01(Time.deltaTime / Mathf.Max(0.1f, transitionSeconds));

        cSunInt = Mathf.Lerp(cSunInt, tSunInt, k);
        cSunCol = Color.Lerp(cSunCol, tSunCol, k);
        cAmb = Color.Lerp(cAmb, tAmb, k);
        cFog = Mathf.Lerp(cFog, tFog, k);
        cFogCol = Color.Lerp(cFogCol, tFogCol, k);
        cExp = Mathf.Lerp(cExp, tExp, k);
        cAtm = Mathf.Lerp(cAtm, tAtm, k);
        cTint = Color.Lerp(cTint, tTint, k);
        cRain = Mathf.Lerp(cRain, tRain, k);
        cSnow = Mathf.Lerp(cSnow, tSnow, k);
        cWind = Mathf.Lerp(cWind, tWind, k);

        ApplyCurrent();
        FollowPlayer();
        UpdateSunDirection();
        UpdateThunder();
    }

    private void ApplyCurrent()
    {
        if (sun != null) { sun.intensity = cSunInt; sun.color = cSunCol; }
        if (controlAmbient) RenderSettings.ambientLight = cAmb;
        if (controlFog) { RenderSettings.fogDensity = cFog; RenderSettings.fogColor = cFogCol; }
        if (skyboxMaterial != null)
        {
            skyboxMaterial.SetFloat("_Exposure", cExp);
            skyboxMaterial.SetFloat("_AtmosphereThickness", cAtm);
            skyboxMaterial.SetColor("_SkyTint", cTint);
        }

        SetParticle(rain, _baseRainRate, cRain);
        SetParticle(snow, _baseSnowRate, cSnow);

        // 風で雨を傾ける
        if (rain != null) rain.transform.localRotation = Quaternion.Euler(0f, 0f, cWind * 25f);

        if (rainLoop != null) SetLoop(rainLoop, cRain * maxRainVolume);
        if (windLoop != null) SetLoop(windLoop, cWind * maxWindVolume);
    }

    private void SetParticle(ParticleSystem ps, float baseRate, float amount)
    {
        if (ps == null) return;
        var e = ps.emission;
        e.rateOverTimeMultiplier = baseRate * amount;
        if (amount > 0.01f) { if (!ps.isPlaying) ps.Play(); }
        else if (ps.isPlaying && ps.particleCount == 0) ps.Stop();
    }

    private void SetLoop(AudioSource a, float vol)
    {
        a.volume = vol;
        if (vol > 0.01f) { if (!a.isPlaying) a.Play(); }
        else if (a.isPlaying) a.Stop();
    }

    private void FollowPlayer()
    {
        if (followPlayerRoot == null) return;
        VRCPlayerApi p = Networking.LocalPlayer;
        if (p == null || !p.IsValid()) return;
        followPlayerRoot.position = p.GetPosition() + Vector3.up * followHeight;
    }

    private void UpdateSunDirection()
    {
        if (!followRealTime || sun == null) return;
        DateTime local = DateTime.UtcNow.AddSeconds(_utcOffset);
        float hour = local.Hour + local.Minute / 60f;
        // 6時=0°(地平線) → 12時=90° → 18時=180°。夜は月として反対側から照らす
        float angle = Mathf.Repeat((hour - 6f) / 12f * 180f, 360f);
        if (angle > 180f) angle -= 180f;   // 夜間（18時〜翌6時）は月の位置
        sun.transform.rotation = Quaternion.Euler(Mathf.Clamp(angle, 5f, 175f), sunYaw, 0f);
    }

    // ---- 雷 ----
    private void UpdateThunder()
    {
        if (_category != THUNDER || Time.time < _nextThunder) return;
        _nextThunder = Time.time + UnityEngine.Random.Range(thunderInterval.x, thunderInterval.y);
        FlashOn();
        SendCustomEventDelayedSeconds(nameof(FlashOff), 0.08f);
        SendCustomEventDelayedSeconds(nameof(FlashOn), 0.2f);
        SendCustomEventDelayedSeconds(nameof(FlashOff), 0.3f);
        SendCustomEventDelayedSeconds(nameof(PlayThunder), UnityEngine.Random.Range(0.4f, 2.5f));
    }

    public void FlashOn() { if (lightningLight != null) lightningLight.enabled = true; }
    public void FlashOff() { if (lightningLight != null) lightningLight.enabled = false; }
    public void PlayThunder()
    {
        if (thunderAudio == null) return;
        thunderAudio.pitch = UnityEngine.Random.Range(0.85f, 1.1f);
        thunderAudio.Play();
    }

    private double GetNum(DataDictionary d, string key, double fallback)
    {
        return d.TryGetValue(key, TokenType.Double, out DataToken v) ? v.Double : fallback;
    }
}
