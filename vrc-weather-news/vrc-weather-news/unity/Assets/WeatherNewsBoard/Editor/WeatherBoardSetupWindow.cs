// VRChat 天気＆ニュース掲示板 ワンクリックセットアップ
// メニュー: Tools > Weather News Board > セットアップ
using System.IO;
using System.Linq;
using TMPro;
using UdonSharp;
using UdonSharpEditor;
using UnityEditor;
using UnityEditor.Events;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.Rendering;
using UnityEngine.TextCore.LowLevel;
using UnityEngine.UI;
using VRC.SDKBase;
using VRC.Udon;

public class WeatherBoardSetupWindow : EditorWindow
{
    const string Root = "Assets/WeatherNewsBoard";
    const string PrefUrl = "WeatherNewsBoard_DataUrl";
    const string DefaultUrl = "https://YOURNAME.github.io/vrc-weather-news/data.json";

    string _url;
    Font _font;
    bool _makeBoard = true, _makeEnv = true, _debugButtons = true;
    int _cityIndex;

    // ------------------------------------------------------------ メニュー
    [MenuItem("Tools/Weather News Board/セットアップ", false, 0)]
    static void Open()
    {
        var w = GetWindow<WeatherBoardSetupWindow>(true, "Weather News Board");
        w.minSize = new Vector2(440, 360);
    }

    [MenuItem("Tools/Weather News Board/Skybox を初期状態に戻す", false, 20)]
    static void ResetSkybox()
    {
        var m = AssetDatabase.LoadAssetAtPath<Material>(Root + "/Materials/WeatherSkybox.mat");
        if (m == null) return;
        m.SetFloat("_Exposure", 1.3f);
        m.SetFloat("_AtmosphereThickness", 1f);
        m.SetColor("_SkyTint", new Color(0.5f, 0.5f, 0.5f));
        EditorUtility.SetDirty(m);
        AssetDatabase.SaveAssets();
    }

    // インポート直後に UdonSharp のプログラムアセットを用意しておく
    [InitializeOnLoadMethod]
    static void AutoCreateProgramAssets()
    {
        EditorApplication.delayCall += () =>
        {
            EnsureProgramAsset("WeatherNewsBoard");
            EnsureProgramAsset("WeatherEnvironment");
        };
    }

    void OnEnable()
    {
        _url = EditorPrefs.GetString(PrefUrl, DefaultUrl);
        if (_font == null) _font = AssetDatabase.LoadAssetAtPath<Font>(Root + "/Fonts/NotoSansJP-Medium.ttf");
    }

    // ------------------------------------------------------------ GUI
    void OnGUI()
    {
        EditorGUILayout.Space(6);
        EditorGUILayout.LabelField("天気＆ニュース掲示板 セットアップ", EditorStyles.boldLabel);
        EditorGUILayout.HelpBox(
            "ボタンを押すと、選択中のシーンに以下を自動で作成します。\n" +
            "・看板UI（現在の天気 / 明日の予報 / ニュース / ティッカー）\n" +
            "・天気演出（太陽光・空・霧・雨・雪・雷・環境音）と Lighting 設定\n" +
            "・各スクリプトの参照の割り当て", MessageType.None);

        EditorGUILayout.Space(4);
        EditorGUILayout.LabelField("data.json の URL（GitHub Pages）");
        _url = EditorGUILayout.TextField(_url);
        if (_url.Contains("YOURNAME"))
            EditorGUILayout.HelpBox("YOURNAME とリポジトリ名を自分のものに書き換えてください（後からインスペクタでも変更できます）", MessageType.Warning);

        _font = (Font)EditorGUILayout.ObjectField("日本語フォント", _font, typeof(Font), false);
        _cityIndex = EditorGUILayout.IntField(new GUIContent("演出に使う都市番号", "config.json の cities の順番（0 = 1番目）"), _cityIndex);

        EditorGUILayout.Space(4);
        _makeBoard = EditorGUILayout.ToggleLeft("看板UIを作る", _makeBoard);
        _makeEnv = EditorGUILayout.ToggleLeft("ワールドの天気演出を作る（Lighting 設定も変更します）", _makeEnv);
        using (new EditorGUI.DisabledScope(!_makeBoard || !_makeEnv))
            _debugButtons = EditorGUILayout.ToggleLeft("看板にテスト用ボタン（天気切替・昼夜切替）を付ける", _debugButtons);

        EditorGUILayout.Space(10);
        using (new EditorGUI.DisabledScope(!_makeBoard && !_makeEnv))
        {
            if (GUILayout.Button("シーンに配置", GUILayout.Height(40)))
            {
                EditorPrefs.SetString(PrefUrl, _url);
                try { Build(); }
                catch (System.Exception e)
                {
                    Debug.LogException(e);
                    EditorUtility.DisplayDialog("Weather News Board", "作成中にエラーが発生しました。\nConsole を確認してください。\n\n" + e.Message, "OK");
                }
            }
        }
    }

    // ------------------------------------------------------------ 本体
    void Build()
    {
        EnsureProgramAsset("WeatherNewsBoard");
        EnsureProgramAsset("WeatherEnvironment");

        Undo.IncrementCurrentGroup();
        int group = Undo.GetCurrentGroup();

        var root = new GameObject("WeatherNewsBoard System");
        Undo.RegisterCreatedObjectUndo(root, "Create Weather News Board");

        WeatherEnvironment env = null;
        if (_makeEnv) env = BuildEnvironment(root.transform);

        GameObject boardGo = null;
        if (_makeBoard)
        {
            var fontAsset = GetOrCreateFontAsset(_font);
            if (fontAsset == null)
                Debug.LogWarning("[WeatherNewsBoard] 日本語フォントが未設定のため、TMP の既定フォントを使います（日本語は表示されません）");
            boardGo = BuildBoard(root.transform, fontAsset, env);
        }

        Undo.CollapseUndoOperations(group);
        EditorSceneManager.MarkSceneDirty(root.scene);
        Selection.activeGameObject = boardGo != null ? boardGo : root;
        if (boardGo != null) SceneView.lastActiveSceneView?.FrameSelected();

        EditorUtility.DisplayDialog("Weather News Board",
            "配置しました。\n\n" +
            "・URL を変える: 看板オブジェクトの WeatherNewsBoard > Data Url\n" +
            "・演出のテスト: WeatherEnvironment の Debug Override をオン\n" +
            "・雨音などの音: Audio フォルダの仮の音を好きな音に差し替え可\n\n" +
            "Build & Test で確認してください。", "OK");
    }

    // ============================================================ 看板UI
    GameObject BuildBoard(Transform parent, TMP_FontAsset font, WeatherEnvironment env)
    {
        // 置き場所：シーンビューの注視点、なければ原点の前
        Vector3 pos = new Vector3(0f, 1.6f, 3f);
        Quaternion rot = Quaternion.identity;
        var sv = SceneView.lastActiveSceneView;
        if (sv != null)
        {
            Vector3 fwd = sv.rotation * Vector3.forward; fwd.y = 0;
            if (fwd.sqrMagnitude < 0.001f) fwd = Vector3.forward;
            pos = sv.pivot; pos.y = Mathf.Max(pos.y, 1.6f);
            rot = Quaternion.LookRotation(fwd.normalized); // 看板の表がカメラを向く
        }

        var go = new GameObject("WeatherNewsBoard", typeof(RectTransform));
        go.transform.SetParent(parent, false);
        go.transform.SetPositionAndRotation(pos, rot);
        go.layer = 0; // Default（UI レイヤーだとプレイヤーが操作できない）

        var canvas = go.AddComponent<Canvas>();
        canvas.renderMode = RenderMode.WorldSpace;
        var scaler = go.AddComponent<CanvasScaler>();
        scaler.dynamicPixelsPerUnit = 10;
        go.AddComponent<GraphicRaycaster>();
        var rt = (RectTransform)go.transform;
        rt.sizeDelta = new Vector2(1600, 1000);
        rt.localScale = Vector3.one * 0.001f;   // 1.6m × 1.0m

        AddVrcUiShape(go);   // 当たり判定は VRC Ui Shape が実行時に自動で作る

        Sprite sprite = AssetDatabase.GetBuiltinExtraResource<Sprite>("UI/Skin/UISprite.psd");
        Color bg = new Color(0.05f, 0.07f, 0.11f, 0.94f);
        Color panel = new Color(1f, 1f, 1f, 0.05f);
        Color accent = new Color(0.45f, 0.75f, 1f);
        Color sub = new Color(0.75f, 0.8f, 0.88f);

        var bgImg = Img("Background", go.transform, 0, 0, 1600, 1000, bg, sprite);
        bgImg.raycastTarget = false;

        // --- ヘッダー
        var title = Txt("Title", go.transform, font, 40, 22, 600, 60, 46, Color.white, FontStyles.Bold);
        title.text = "WEATHER <color=#73BFFF>&</color> NEWS";
        Img("HeaderLine", go.transform, 40, 92, 1520, 3, accent, null);

        // --- 現在の天気（左）
        Img("NowPanel", go.transform, 30, 110, 760, 440, panel, sprite);
        var nowLabel = Txt("NowLabel", go.transform, font, 55, 122, 700, 46, 30, accent, FontStyles.Bold);
        nowLabel.text = "いまの天気";
        var weather = Txt("WeatherText", go.transform, font, 55, 172, 715, 370, 28, Color.white);
        weather.lineSpacing = 8;
        weather.text = "-";

        // --- 明日（右）
        Img("TomorrowPanel", go.transform, 810, 110, 760, 440, panel, sprite);
        var fTitle = Txt("ForecastTitle", go.transform, font, 835, 122, 700, 46, 30, accent, FontStyles.Bold);
        fTitle.text = "明日の天気";
        var fText = Txt("ForecastText", go.transform, font, 835, 172, 715, 370, 26, Color.white);
        fText.lineSpacing = 4;
        fText.text = "-";

        // --- ニュース
        Img("NewsPanel", go.transform, 30, 570, 1540, 320, panel, sprite);
        var newsLabel = Txt("NewsLabel", go.transform, font, 55, 582, 400, 46, 30, accent, FontStyles.Bold);
        newsLabel.text = "ニュース";
        var news = Txt("NewsText", go.transform, font, 55, 632, 1495, 218, 26, Color.white);
        news.lineSpacing = 6;
        news.text = "-";
        var status = Txt("Status", go.transform, font, 55, 854, 1495, 30, 18, sub);
        status.alignment = TextAlignmentOptions.BottomRight;
        status.enableWordWrapping = false;
        status.overflowMode = TextOverflowModes.Ellipsis;
        status.text = "読み込み中…";

        // --- ティッカー
        Img("TickerBar", go.transform, 0, 910, 1600, 90, new Color(0.45f, 0.75f, 1f, 0.18f), null);
        var ticker = Txt("TickerText", go.transform, font, 40, 925, 1520, 60, 32, Color.white);
        ticker.alignment = TextAlignmentOptions.MidlineLeft;
        ticker.overflowMode = TextOverflowModes.Ellipsis;
        ticker.text = "";

        // --- スクリプト
        var board = UdonSharpUndo.AddComponent<WeatherNewsBoard>(go);
        board.dataUrl = new VRCUrl(_url);
        board.weatherText = weather;
        board.newsText = news;
        board.statusText = status;
        board.forecastTitle = fTitle;
        board.forecastText = fText;
        board.tickerText = ticker;
        board.environment = env;
        UdonSharpEditorUtility.CopyProxyToUdon(board);
        EditorUtility.SetDirty(board);

        // --- ボタン（ヘッダー右側）
        UdonBehaviour boardUdon = UdonSharpEditorUtility.GetBackingUdonBehaviour(board);
        float bx = 1060;
        Btn("RefreshButton", go.transform, font, sprite, bx + 340, 20, 160, 56, "更新", boardUdon, "Refresh");
        if (_debugButtons && env != null)
        {
            UdonBehaviour envUdon = UdonSharpEditorUtility.GetBackingUdonBehaviour(env);
            Btn("DebugWeatherButton", go.transform, font, sprite, bx, 20, 160, 56, "天気テスト", envUdon, "DebugNext");
            Btn("DebugDayNightButton", go.transform, font, sprite, bx + 170, 20, 160, 56, "昼 / 夜", envUdon, "DebugToggleDayNight");
        }

        return go;
    }

    static void AddVrcUiShape(GameObject go)
    {
        // SDK のバージョン差を吸収して VRCUiShape を追加
        var t = System.Type.GetType("VRC.SDK3.Components.VRCUiShape, VRCSDK3")
                ?? System.AppDomain.CurrentDomain.GetAssemblies()
                    .Select(a => a.GetType("VRC.SDK3.Components.VRCUiShape"))
                    .FirstOrDefault(x => x != null);
        if (t != null) go.AddComponent(t);
        else Debug.LogWarning("[WeatherNewsBoard] VRCUiShape が見つかりません。Canvas に VRC Ui Shape を手動で追加してください。");
    }

    // ============================================================ 天気演出
    WeatherEnvironment BuildEnvironment(Transform parent)
    {
        var go = new GameObject("WeatherEnvironment");
        go.transform.SetParent(parent, false);

        // --- 太陽
        Light sun = RenderSettings.sun;
        if (sun == null)
            sun = FindObjectsOfType<Light>().FirstOrDefault(l => l.type == LightType.Directional);
        if (sun == null)
        {
            var s = new GameObject("Sun (Directional Light)");
            s.transform.SetParent(parent, false);
            s.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
            sun = s.AddComponent<Light>();
            sun.type = LightType.Directional;
            sun.shadows = LightShadows.Soft;
        }
        else Undo.RecordObject(sun, "Weather Sun");
        if (sun.lightmapBakeType == LightmapBakeType.Baked)
        {
            sun.lightmapBakeType = LightmapBakeType.Mixed;
            Debug.Log("[WeatherNewsBoard] Directional Light を Baked → Mixed に変更しました（天気で明るさを変えるため）");
        }
        RenderSettings.sun = sun;

        // --- Skybox / Lighting
        var sky = GetOrCreateSkybox();
        RenderSettings.skybox = sky;
        RenderSettings.fog = true;
        RenderSettings.fogMode = FogMode.Exponential;
        RenderSettings.fogDensity = 0.003f;
        RenderSettings.ambientMode = AmbientMode.Flat;

        // --- 雨・雪（プレイヤー追従）
        var follow = new GameObject("FollowPlayer (Rain/Snow)").transform;
        follow.SetParent(go.transform, false);
        follow.localPosition = new Vector3(0, 8, 0);
        Material pmat = GetParticleMaterial();
        var rain = MakeRain(follow, pmat);
        var snow = MakeSnow(follow, pmat);

        // --- 雷
        var lgo = new GameObject("Lightning");
        lgo.transform.SetParent(go.transform, false);
        lgo.transform.rotation = Quaternion.Euler(60f, 20f, 0f);
        var lightning = lgo.AddComponent<Light>();
        lightning.type = LightType.Directional;
        lightning.intensity = 2.5f;
        lightning.color = new Color(0.8f, 0.85f, 1f);
        lightning.shadows = LightShadows.None;
        lightning.lightmapBakeType = LightmapBakeType.Realtime;
        lightning.enabled = false;

        // --- 環境音
        var rainLoop = MakeAudio(go.transform, "RainLoop", "rain_loop.wav", true);
        var windLoop = MakeAudio(go.transform, "WindLoop", "wind_loop.wav", true);
        var thunder = MakeAudio(go.transform, "Thunder", "thunder.wav", false);

        // --- スクリプト
        var env = UdonSharpUndo.AddComponent<WeatherEnvironment>(go);
        env.cityIndex = Mathf.Max(0, _cityIndex);
        env.sun = sun;
        env.skyboxMaterial = sky;
        env.rain = rain;
        env.snow = snow;
        env.followPlayerRoot = follow;
        env.lightningLight = lightning;
        env.thunderAudio = thunder;
        env.rainLoop = rainLoop;
        env.windLoop = windLoop;
        UdonSharpEditorUtility.CopyProxyToUdon(env);
        EditorUtility.SetDirty(env);
        return env;
    }

    static ParticleSystem MakeRain(Transform parent, Material mat)
    {
        var go = new GameObject("Rain");
        go.transform.SetParent(parent, false);
        var ps = go.AddComponent<ParticleSystem>();
        ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);

        var main = ps.main;
        main.playOnAwake = false;
        main.loop = true;
        main.startLifetime = 1.1f;
        main.startSpeed = 15f;
        main.startSize = 0.025f;
        main.startColor = new Color(0.75f, 0.82f, 1f, 0.5f);
        main.gravityModifier = 0.4f;
        main.simulationSpace = ParticleSystemSimulationSpace.World;
        main.maxParticles = 2000;

        var em = ps.emission;
        em.rateOverTime = 1500f;  // 最大の強さ（スクリプトが 0〜100% に調整）

        var sh = ps.shape;
        sh.shapeType = ParticleSystemShapeType.Box;
        sh.scale = new Vector3(30f, 30f, 0.5f);
        sh.rotation = new Vector3(90f, 0f, 0f);   // 下向きに放出

        var r = go.GetComponent<ParticleSystemRenderer>();
        r.renderMode = ParticleSystemRenderMode.Stretch;
        r.velocityScale = 0.04f;
        r.lengthScale = 1f;
        r.sharedMaterial = mat;
        r.shadowCastingMode = ShadowCastingMode.Off;
        r.receiveShadows = false;
        return ps;
    }

    static ParticleSystem MakeSnow(Transform parent, Material mat)
    {
        var go = new GameObject("Snow");
        go.transform.SetParent(parent, false);
        var ps = go.AddComponent<ParticleSystem>();
        ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);

        var main = ps.main;
        main.playOnAwake = false;
        main.loop = true;
        main.startLifetime = 9f;
        main.startSpeed = 1.1f;
        main.startSize = new ParticleSystem.MinMaxCurve(0.04f, 0.09f);
        main.startColor = new Color(1f, 1f, 1f, 0.9f);
        main.gravityModifier = 0.02f;
        main.simulationSpace = ParticleSystemSimulationSpace.World;
        main.maxParticles = 3000;

        var em = ps.emission;
        em.rateOverTime = 320f;

        var sh = ps.shape;
        sh.shapeType = ParticleSystemShapeType.Box;
        sh.scale = new Vector3(30f, 30f, 0.5f);
        sh.rotation = new Vector3(90f, 0f, 0f);

        var noise = ps.noise;
        noise.enabled = true;
        noise.strength = 0.35f;
        noise.frequency = 0.4f;

        var r = go.GetComponent<ParticleSystemRenderer>();
        r.renderMode = ParticleSystemRenderMode.Billboard;
        r.sharedMaterial = mat;
        r.shadowCastingMode = ShadowCastingMode.Off;
        r.receiveShadows = false;
        return ps;
    }

    static AudioSource MakeAudio(Transform parent, string name, string clipFile, bool loop)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        var a = go.AddComponent<AudioSource>();
        a.clip = AssetDatabase.LoadAssetAtPath<AudioClip>(Root + "/Audio/" + clipFile);
        a.loop = loop;
        a.playOnAwake = false;
        a.spatialBlend = 0f;   // 2D（どこにいても聞こえる）
        a.volume = loop ? 0f : 0.8f;
        return a;
    }

    static Material GetParticleMaterial()
    {
        Material m = AssetDatabase.GetBuiltinExtraResource<Material>("Default-ParticleSystem.mat");
        if (m != null) return m;
        string path = Root + "/Materials/WeatherParticle.mat";
        m = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (m != null) return m;
        var sh = Shader.Find("Particles/Standard Unlit") ?? Shader.Find("Legacy Shaders/Particles/Alpha Blended");
        m = new Material(sh);
        // Standard Unlit を Fade（半透明）に
        m.SetFloat("_Mode", 2f);
        m.SetInt("_SrcBlend", (int)BlendMode.SrcAlpha);
        m.SetInt("_DstBlend", (int)BlendMode.OneMinusSrcAlpha);
        m.SetInt("_ZWrite", 0);
        m.EnableKeyword("_ALPHABLEND_ON");
        m.renderQueue = 3000;
        m.mainTexture = AssetDatabase.GetBuiltinExtraResource<Texture2D>("Default-Particle.psd");
        EnsureFolder(Root + "/Materials");
        AssetDatabase.CreateAsset(m, path);
        return m;
    }

    static Material GetOrCreateSkybox()
    {
        string path = Root + "/Materials/WeatherSkybox.mat";
        var m = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (m != null) return m;
        m = new Material(Shader.Find("Skybox/Procedural"));
        m.SetFloat("_SunSize", 0.04f);
        m.SetFloat("_Exposure", 1.3f);
        m.SetFloat("_AtmosphereThickness", 1f);
        EnsureFolder(Root + "/Materials");
        AssetDatabase.CreateAsset(m, path);
        return m;
    }

    // ============================================================ フォント
    static TMP_FontAsset GetOrCreateFontAsset(Font font)
    {
        string path = Root + "/Fonts/NotoSansJP SDF.asset";
        var existing = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(path);
        if (existing != null) return existing;
        if (font == null) return null;

        var fa = TMP_FontAsset.CreateFontAsset(font, 64, 6, GlyphRenderMode.SDFAA, 2048, 2048,
                                               AtlasPopulationMode.Dynamic, true);
        if (fa == null) return null;
        fa.name = "NotoSansJP SDF";
        AssetDatabase.CreateAsset(fa, path);
        // アトラスとマテリアルをサブアセットとして保存（これが無いと保存/ビルドで消える）
        fa.atlasTextures[0].name = fa.name + " Atlas";
        fa.material.name = fa.name + " Material";
        AssetDatabase.AddObjectToAsset(fa.atlasTextures[0], fa);
        AssetDatabase.AddObjectToAsset(fa.material, fa);

        // よく使う文字を先に焼いておく（残りの漢字は表示時に自動追加）
        const string common =
            " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~" +
            "、。・ー「」『』（）【】！？：；％℃°／〜…■◆●○" +
            "ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろわをん" +
            "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロワヲンヴ" +
            "天気予報明日今最高低温度降水確率湿風速晴曇雨雪雷霧時々後一部小大強弱北南東西朝昼夕夜方更新読込中取得失敗東京大阪札幌月火水木金土日年分秒";
        fa.TryAddCharacters(common, out _);
        EditorUtility.SetDirty(fa);
        AssetDatabase.SaveAssets();
        return fa;
    }

    // ============================================================ UI ヘルパー
    // 座標はキャンバス左上を原点にしたピクセル（x, y, 幅, 高さ）
    static RectTransform Place(GameObject go, Transform parent, float x, float y, float w, float h)
    {
        var rt = go.GetComponent<RectTransform>();
        if (rt == null) rt = go.AddComponent<RectTransform>();
        rt.SetParent(parent, false);
        rt.anchorMin = rt.anchorMax = new Vector2(0, 1);
        rt.pivot = new Vector2(0, 1);
        rt.anchoredPosition = new Vector2(x, -y);
        rt.sizeDelta = new Vector2(w, h);
        go.layer = parent.gameObject.layer;
        return rt;
    }

    static Image Img(string name, Transform parent, float x, float y, float w, float h, Color c, Sprite sprite)
    {
        var go = new GameObject(name, typeof(RectTransform));
        Place(go, parent, x, y, w, h);
        var img = go.AddComponent<Image>();
        img.color = c;
        img.raycastTarget = false;
        if (sprite != null) { img.sprite = sprite; img.type = Image.Type.Sliced; }
        return img;
    }

    static TextMeshProUGUI Txt(string name, Transform parent, TMP_FontAsset font, float x, float y, float w, float h,
                               float size, Color c, FontStyles style = FontStyles.Normal)
    {
        var go = new GameObject(name, typeof(RectTransform));
        Place(go, parent, x, y, w, h);
        var t = go.AddComponent<TextMeshProUGUI>();
        if (font != null) t.font = font;
        t.fontSize = size;
        t.color = c;
        t.fontStyle = style;
        t.richText = true;
        t.enableWordWrapping = true;
        t.overflowMode = TextOverflowModes.Truncate;
        t.alignment = TextAlignmentOptions.TopLeft;
        t.raycastTarget = false;
        return t;
    }

    static void Btn(string name, Transform parent, TMP_FontAsset font, Sprite sprite, float x, float y, float w, float h,
                    string label, UdonBehaviour target, string eventName)
    {
        var go = new GameObject(name, typeof(RectTransform));
        Place(go, parent, x, y, w, h);
        var img = go.AddComponent<Image>();
        img.sprite = sprite;
        img.type = Image.Type.Sliced;
        img.color = new Color(0.45f, 0.75f, 1f, 0.35f);
        var b = go.AddComponent<Button>();
        b.targetGraphic = img;
        var colors = b.colors;
        colors.highlightedColor = new Color(1f, 1f, 1f, 1f);
        colors.pressedColor = new Color(0.7f, 0.85f, 1f, 1f);
        b.colors = colors;
        if (target != null)
            UnityEventTools.AddStringPersistentListener(b.onClick, new UnityAction<string>(target.SendCustomEvent), eventName);

        var t = Txt("Label", go.transform, font, 0, 0, w, h, 26, Color.white, FontStyles.Bold);
        t.alignment = TextAlignmentOptions.Center;
        t.enableWordWrapping = false;
        t.text = label;
    }

    // ============================================================ その他
    static void EnsureFolder(string path)
    {
        if (AssetDatabase.IsValidFolder(path)) return;
        string parent = Path.GetDirectoryName(path).Replace('\\', '/');
        EnsureFolder(parent);
        AssetDatabase.CreateFolder(parent, Path.GetFileName(path));
    }

    static void EnsureProgramAsset(string scriptName)
    {
        string scriptPath = AssetDatabase.FindAssets(scriptName + " t:MonoScript")
            .Select(AssetDatabase.GUIDToAssetPath)
            .FirstOrDefault(p => Path.GetFileNameWithoutExtension(p) == scriptName);
        if (scriptPath == null) return;
        var script = AssetDatabase.LoadAssetAtPath<MonoScript>(scriptPath);

        bool exists = AssetDatabase.FindAssets("t:UdonSharpProgramAsset")
            .Select(g => AssetDatabase.LoadAssetAtPath<UdonSharpProgramAsset>(AssetDatabase.GUIDToAssetPath(g)))
            .Any(a => a != null && a.sourceCsScript == script);
        if (exists) return;

        var asset = CreateInstance<UdonSharpProgramAsset>();
        asset.sourceCsScript = script;
        AssetDatabase.CreateAsset(asset, Path.ChangeExtension(scriptPath, ".asset"));
        AssetDatabase.SaveAssets();
        Debug.Log("[WeatherNewsBoard] UdonSharp Program Asset を作成: " + scriptName);
    }
}
