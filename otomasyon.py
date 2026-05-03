import os
import json
import re
import html
import time
import random
import logging
from pathlib import Path
from datetime import datetime
from string import Template

import requests

try:
    import google.generativeai as genai
except ImportError:
    genai = None


# ============================================================
# 1. AYARLAR
# ============================================================

SITE_URL = os.environ.get("SITE_URL", "https://mekanrehber.com").rstrip("/")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

DIST_DIR = Path("dist")
CACHE_DIR = DIST_DIR / "_cache"
AI_CACHE_FILE = CACHE_DIR / "ai_cache.json"

HEDEF_SEHIRLER = [
    "İzmir",
    "İstanbul",
    "Ankara",
    "Antalya",
    "Bursa",
    "Eskişehir",
    "Muğla",
]

MAX_MEKAN_PER_CITY = int(os.environ.get("MAX_MEKAN_PER_CITY", "50"))
OVERPASS_TIMEOUT_SECONDS = int(os.environ.get("OVERPASS_TIMEOUT_SECONDS", "60"))
AI_DELAY_SECONDS = float(os.environ.get("AI_DELAY_SECONDS", "2"))
OVERPASS_DELAY_SECONDS = float(os.environ.get("OVERPASS_DELAY_SECONDS", "2"))

OVERPASS_URL = os.environ.get(
    "OVERPASS_URL",
    "https://overpass-api.de/api/interpreter"
)

USER_AGENT = os.environ.get(
    "USER_AGENT",
    "MekanRehberBot/4.0 (Data-Driven SEO Project; contact: mekanrehber.com)"
)

DIST_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ============================================================
# 2. RENK ALGORİTMASI
# ============================================================

RENK_PALETI = [
    "from-indigo-600 to-purple-800",
    "from-blue-600 to-cyan-700",
    "from-emerald-600 to-teal-800",
    "from-rose-600 to-pink-800",
    "from-amber-600 to-orange-800",
    "from-fuchsia-600 to-indigo-800",
    "from-violet-600 to-fuchsia-800",
    "from-cyan-600 to-blue-800",
]


def renk_sec(isim: str) -> str:
    isim = isim or "mekan"
    index = sum(ord(c) for c in isim) % len(RENK_PALETI)
    return RENK_PALETI[index]


# ============================================================
# 3. YARDIMCI FONKSİYONLAR
# ============================================================

TR_MAP = str.maketrans({
    "İ": "I",
    "I": "I",
    "ı": "i",
    "Ğ": "G",
    "ğ": "g",
    "Ü": "U",
    "ü": "u",
    "Ş": "S",
    "ş": "s",
    "Ö": "O",
    "ö": "o",
    "Ç": "C",
    "ç": "c",
})


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def xml_esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def slugify(value: str) -> str:
    value = str(value or "").translate(TR_MAP).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "mekan"


def city_page_filename(sehir: str) -> str:
    return f"{slugify(sehir)}.html"


def place_page_filename(name: str, sehir: str, osm_type: str, osm_id) -> str:
    return f"{slugify(name)}-{slugify(sehir)}-{slugify(osm_type)}-{osm_id}.html"


def overpass_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def normalize_bool_tag(value, unknown="Belirtilmemiş") -> str:
    if value is None or value == "":
        return unknown

    raw = str(value).strip().lower()

    yes_values = {"yes", "true", "1", "wlan", "wifi", "free", "customers"}
    no_values = {"no", "false", "0"}

    if raw in yes_values:
        return "Var"
    if raw in no_values:
        return "Yok"

    return esc(value)
def paragraphs_to_html(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return "<p>Bu mekan için detaylı analiz henüz hazırlanıyor.</p>"

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    return "\n".join(f"<p>{esc(p)}</p>" for p in paragraphs)


def load_json_file(path: Path, default):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_json_from_model_text(text: str) -> dict:
    text = str(text or "").strip()

    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise ValueError("Model çıktısı JSON olarak parse edilemedi.")


def get_lat_lon(element: dict):
    lat = element.get("lat")
    lon = element.get("lon")

    if lat is None or lon is None:
        center = element.get("center") or {}
        lat = center.get("lat")
        lon = center.get("lon")

    if lat is None or lon is None:
        return None, None

    return lat, lon


# ============================================================
# 4. GEMINI
# ============================================================

def setup_gemini_model():
    if not GEMINI_API_KEY:
        logging.warning("GEMINI_API_KEY bulunamadı. AI içerikler fallback metinle üretilecek.")
        return None

    if genai is None:
        logging.warning("google-generativeai paketi kurulu değil. AI içerikler fallback metinle üretilecek.")
        return None

    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel(GEMINI_MODEL_NAME)


def generate_ai_content(model, sehir: str, name: str, osm_id, ai_cache: dict) -> dict:
    cache_key = f"{sehir}|{name}|{osm_id}"

    if cache_key in ai_cache:
        return ai_cache[cache_key]

    fallback = {
        "vibe": f"{sehir} rotasında keşfedilebilecek sakin bir durak.",
        "makale": (
            f"{name}, {sehir} içinde OpenStreetMap verilerinde cafe kategorisinde görünen "
            f"bir mekan olarak öne çıkıyor. Freelancer veya öğrenci olarak şehir içinde "
            f"çalışmaya, mola vermeye ya da yeni bir nokta keşfetmeye uygun olup olmadığını "
            f"yerinde deneyimleyerek değerlendirebilirsin."
        )
    }

    if model is None:
        ai_cache[cache_key] = fallback
        return fallback

    prompt = f"""
Aşağıdaki mekan için Türkçe, modern, temkinli ve SEO uyumlu kısa bir içerik üret.

Mekan adı: {name}
Şehir: {sehir}

Kurallar:
- Sadece geçerli JSON döndür.
- Gerçek yorum, fiyat, çalışma saati, kalite, kalabalıklık veya hizmet iddiası uydurma.
- OpenStreetMap verisinden geldiği için kesin olmayan şeyleri kesinmiş gibi yazma.
- "freelancer" veya "öğrenci" kelimelerinden en az biri geçsin.
- Vibe tek cümle olsun.
- Makale 2-3 kısa paragraf olsun.
- Reklam dili kullanma.

JSON formatı:
{{
  "vibe": "Tek cümlelik özet",
  "makale": "2-3 paragraflık açıklama"
}}
""".strip()

    try:
        response = model.generate_content(prompt)
        raw_text = getattr(response, "text", "") or ""
        parsed = extract_json_from_model_text(raw_text)

        vibe = str(parsed.get("vibe", "")).strip()
        makale = str(parsed.get("makale", "")).strip()

        if not vibe or not makale:
            raise ValueError("JSON içinde vibe veya makale boş geldi.")

        result = {
            "vibe": vibe,
            "makale": makale
        }

        ai_cache[cache_key] = result
        save_json_file(AI_CACHE_FILE, ai_cache)

        time.sleep(AI_DELAY_SECONDS)
        return result

    except Exception as e:
        logging.warning("AI içerik üretilemedi: %s | %s / %s", e, sehir, name)
        ai_cache[cache_key] = fallback
        save_json_file(AI_CACHE_FILE, ai_cache)
        return fallback

# ============================================================
# 5. OVERPASS / OSM
# ============================================================

def get_with_retry(url: str, params: dict, headers: dict, attempts: int = 3):
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=OVERPASS_TIMEOUT_SECONDS
            )

            if response.status_code == 200:
                return response

            if response.status_code in {429, 502, 503, 504}:
                wait_time = 10 * attempt
                logging.warning(
                    "Overpass geçici hata verdi. Status=%s | %s saniye bekleniyor.",
                    response.status_code,
                    wait_time
                )
                time.sleep(wait_time)
                continue

            logging.warning("Overpass beklenmeyen status verdi: %s", response.status_code)
            return response

        except requests.RequestException as e:
            wait_time = 10 * attempt
            logging.warning(
                "Overpass bağlantı hatası: %s | %s saniye bekleniyor.",
                e,
                wait_time
            )
            time.sleep(wait_time)

    return None


def fetch_city_cafes(sehir: str) -> list:
    safe_city = overpass_escape(sehir)

    query = f"""
[out:json][timeout:50];
area["name"="{safe_city}"]["boundary"="administrative"]->.searchArea;
nwr["amenity"="cafe"]["name"](area.searchArea);
out tags center {MAX_MEKAN_PER_CITY};
""".strip()

    headers = {
        "User-Agent": USER_AGENT
    }

    response = get_with_retry(
        OVERPASS_URL,
        params={"data": query},
        headers=headers,
        attempts=3
    )

    if response is None:
        logging.warning("%s için Overpass yanıtı alınamadı.", sehir)
        return []

    if response.status_code != 200:
        logging.warning("%s için Overpass başarısız oldu. Status=%s", sehir, response.status_code)
        return []

    try:
        data = response.json()
        elements = data.get("elements", [])
        random.shuffle(elements)
        return elements
    except Exception as e:
        logging.warning("%s için Overpass JSON parse hatası: %s", sehir, e)
        return []


# ============================================================
# 6. HTML ŞABLONLARI
# ============================================================

SEO_PAGE_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>$mekan_adi | $sehir Mekan Rehberi</title>
    <meta name="description" content="$meta_description">
    <link rel="canonical" href="$canonical_url">

    <meta property="og:title" content="$mekan_adi | $sehir Mekan Rehberi">
    <meta property="og:description" content="$meta_description">
    <meta property="og:type" content="place">
    <meta property="og:url" content="$canonical_url">
    <meta name="twitter:card" content="summary">

    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;500;700;900&display=swap" rel="stylesheet">

    <script type="application/ld+json">
$schema_json
    </script>

    <style>
        body {
            font-family: 'Outfit', sans-serif;
            background-color: #050505;
            color: #f8fafc;
        }

        .prose p {
            margin-bottom: 1.25rem;
        }
    </style>
</head>

<body class="pb-12">
    <div class="w-full pt-16 pb-24 px-8 bg-gradient-to-br $renk relative overflow-hidden">
        <div class="absolute inset-0 bg-black/30"></div>

        <div class="max-w-5xl mx-auto relative z-10">
            <div class="flex flex-wrap gap-3 mb-6">
                <a href="/" class="text-white/75 hover:text-white font-bold inline-block transition">← Zarı Yeniden At</a>
                <a href="/$sehir_url" class="text-white/75 hover:text-white font-bold inline-block transition">/$sehir mekanları</a>
            </div>

            <div class="inline-block px-3 py-1 bg-black/40 backdrop-blur-md text-white rounded-full text-xs font-bold uppercase tracking-widest mb-4 border border-white/10">
                📍 $sehir
            </div>

            <h1 class="text-5xl md:text-7xl font-black text-white leading-[1.1] tracking-tighter">$mekan_adi</h1>
        </div>
    </div>

    <main class="max-w-5xl mx-auto px-8 -mt-12 relative z-20">
        <div class="grid grid-cols-1 md:grid-cols-3 gap-8">

            <div class="md:col-span-2 space-y-8">
                <article class="prose prose-invert prose-lg max-w-none text-slate-300 leading-relaxed bg-slate-900/90 backdrop-blur-xl p-8 md:p-10 rounded-3xl border border-slate-800 shadow-2xl">
                    <h2 class="text-2xl font-bold text-white mb-6 border-b border-slate-700 pb-4 flex items-center gap-2">
                        🤖 Editörün Notu
                    </h2>
                    $makale_html

                    <div class="mt-8 pt-6 border-t border-slate-800 text-sm text-slate-500">
                        Bu içerik yapay zeka destekli olarak hazırlanmıştır. Mekan verileri OpenStreetMap kaynaklıdır; çalışma saatleri, fiyatlar ve hizmet detayları yerinde doğrulanmalıdır.
                    </div>
                </article>

                <div class="bg-slate-900/90 rounded-3xl border border-slate-800 overflow-hidden shadow-2xl p-2">
                    <iframe
                        width="100%"
                        height="350"
                        style="border:0; border-radius: 1.5rem;"
                        loading="lazy"
                        allowfullscreen
                        referrerpolicy="no-referrer-when-downgrade"
                        src="https://maps.google.com/maps?q=$enlem,$boylam&hl=tr&z=15&output=embed">
                    </iframe>
                </div>
            </div>

            <aside class="space-y-6">
                <div class="bg-slate-900/90 backdrop-blur-xl p-8 rounded-3xl border border-slate-800 shadow-xl">
                    <h3 class="text-xl font-bold mb-6">Özet Bilgiler</h3>

                    <div class="space-y-4">
                        <div class="flex justify-between gap-4 border-b border-slate-800 pb-3">
                            <span class="text-slate-400">Wi-Fi Bağlantısı</span>
                            <span class="font-bold text-white text-right">$wifi</span>
                        </div>

                        <div class="flex justify-between gap-4 border-b border-slate-800 pb-3">
                            <span class="text-slate-400">Dış Mekan</span>
                            <span class="font-bold text-white text-right">$dis_mekan</span>
                        </div>

                        <div class="flex justify-between gap-4 border-b border-slate-800 pb-3">
                            <span class="text-slate-400">Veri Kaynağı</span>
                            <span class="font-bold text-white text-right">OSM</span>
                        </div>
                    </div>
                </div>

                <a href="https://maps.google.com/maps?dirflg=d&daddr=$enlem,$boylam"
                   target="_blank"
                   rel="noopener noreferrer"
                   class="block w-full text-center bg-white text-black font-black py-6 rounded-3xl shadow-[0_0_30px_rgba(255,255,255,0.1)] hover:scale-[1.03] transition-all">
                    Yol Tarifi Al 🧭
                </a>
            </aside>

        </div>
    </main>
        <footer class="max-w-5xl mx-auto px-8 mt-16 text-xs text-slate-500 leading-relaxed">
        Mekan verileri
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer nofollow" class="underline hover:text-slate-300">
            © OpenStreetMap contributors
        </a>
        tarafından sağlanır ve ODbL lisansı kapsamındadır.
    </footer>
</body>
</html>""")


INDEX_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MekanZar | Şansını Dene</title>
    <meta name="description" content="Türkiye şehirlerinden rastgele cafe ve mekan keşfet. Gerçek OpenStreetMap verileriyle yapay zeka destekli mekan rehberi.">
    <link rel="canonical" href="$site_url/">

    <meta property="og:title" content="MekanZar | Şansını Dene">
    <meta property="og:description" content="Türkiye şehirlerinden rastgele cafe ve mekan keşfet.">
    <meta property="og:type" content="website">
    <meta property="og:url" content="$site_url/">
    <meta name="twitter:card" content="summary">

    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;500;700;900&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js"></script>

    <style>
        body {
            font-family: 'Outfit', sans-serif;
            background-color: #050505;
            color: #f8fafc;
            overflow-x: hidden;
        }

        .spin-3d {
            animation: fastSpin 2s cubic-bezier(0.25, 0.1, 0.25, 1) forwards;
            transform-style: preserve-3d;
        }

        @keyframes fastSpin {
            0% {
                transform: rotateY(0deg) scale(0.8);
                opacity: 1;
            }

            50% {
                transform: rotateY(1800deg) scale(1.1);
                filter: blur(2px);
            }

            100% {
                transform: rotateY(3600deg) scale(1);
                filter: blur(0);
            }
        }

        .glass-panel {
            background: rgba(255, 255, 255, 0.03);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.05);
        }
    </style>
</head>

<body class="min-h-screen flex items-center justify-center relative p-4">

    <main id="step-1" class="glass-panel p-10 rounded-[2.5rem] w-full max-w-lg z-10 text-center">
        <h1 class="text-6xl font-black mb-2 tracking-tighter">
            mekan<span class="text-transparent bg-clip-text bg-gradient-to-r from-indigo-500 to-pink-500">zar</span>.
        </h1>

        <p class="text-slate-400 mb-10">
            Tasarım kirliliği yok. Gerçek OpenStreetMap verileri ve yapay zeka destekli keşif notları.
        </p>

        <div class="mb-8">
            <select id="sehir-secimi" class="w-full bg-white/5 border border-white/10 text-white rounded-2xl py-5 px-6 outline-none focus:border-indigo-500 transition font-medium appearance-none">
                <option value="hepsi">Tüm Şehirler</option>
            </select>
        </div>

        <button onclick="rollTheDice()" class="w-full bg-white text-black font-black text-xl py-6 rounded-2xl hover:scale-[1.02] transition-all shadow-xl">
            🎲 Zarı At
        </button>

        <div class="mt-8 flex flex-wrap justify-center gap-2 text-xs">
            $city_links
        </div>
    </main>

    <section id="step-2" class="hidden z-20 absolute inset-0 flex flex-col items-center justify-center bg-black/95 backdrop-blur-md">
        <div id="spinner" class="w-64 h-80 rounded-[2.5rem] bg-gradient-to-tr from-slate-700 to-slate-900 p-1 flex items-center justify-center">
            <div class="w-full h-full bg-black rounded-[2.4rem] flex items-center justify-center text-7xl">🎲</div>
        </div>
    </section>

    <section id="step-3" class="hidden glass-panel w-full max-w-md z-30 transform scale-95 opacity-0 transition-all duration-700 overflow-hidden rounded-[2.5rem] border border-slate-800">
        <div id="res-color-box" class="relative h-40 w-full bg-gradient-to-br from-indigo-600 to-purple-800 flex items-center justify-center">
            <div class="absolute inset-0 bg-black/20"></div>

            <button onclick="location.reload()" class="absolute top-4 left-4 bg-black/50 backdrop-blur-md text-white px-4 py-2 rounded-full text-xs font-bold border border-white/10 hover:bg-white/20 transition z-10">
                ← Tekrar At
            </button>

            <span class="text-6xl relative z-10">📍</span>
        </div>

        <div class="p-8 bg-slate-950 relative">
            <span id="res-sehir" class="absolute -top-4 right-8 bg-black text-white border border-white/10 px-4 py-1.5 rounded-full text-xs font-bold uppercase tracking-widest shadow-lg">
                Şehir
            </span>

            <h2 id="res-ad" class="text-3xl font-black text-white mb-4 leading-tight mt-2">
                Mekan Adı
            </h2>

            <div class="bg-slate-900/80 p-5 rounded-2xl border border-slate-800 mb-8">
                <p class="text-xs text-slate-500 uppercase tracking-wider mb-2 font-bold flex items-center gap-2">
                    🤖 Vibe
                </p>

                <p id="res-ozet" class="font-medium text-slate-300 leading-relaxed">
                    ...
                </p>
            </div>

            <a id="res-link" href="#" class="block w-full text-center bg-white text-black font-black text-lg py-5 rounded-2xl hover:bg-slate-200 transition-all shadow-xl">
                Rehberi Gör & Git →
            </a>
        </div>
    </section>

    <footer class="absolute bottom-4 left-4 right-4 text-center text-[11px] text-slate-600">
        Veriler
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer nofollow" class="underline hover:text-slate-400">
            © OpenStreetMap contributors
        </a>
        kaynaklıdır.
    </footer>

    <script>
        let mekanlar = [];

        function escapeHtml(value) {
            return String(value || "")
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#039;");
        }

        function showError(message) {
            alert(message);
        }

        fetch("veri.json")
            .then(function(res) {
                if (!res.ok) {
                    throw new Error("Veri yüklenemedi.");
                }

                return res.json();
            })
            .then(function(data) {
                mekanlar = Array.isArray(data) ? data : [];

                if (!mekanlar.length) {
                    showError("Henüz mekan verisi bulunamadı.");
                    return;
                }

                const sehirler = Array.from(new Set(mekanlar.map(function(m) {
                    return m.sehir;
                }))).sort();

                const select = document.getElementById("sehir-secimi");

                sehirler.forEach(function(s) {
                    const option = document.createElement("option");
                    option.value = s;
                    option.textContent = s;
                    select.appendChild(option);
                });
            })
            .catch(function() {
                showError("Mekan verisi şu anda yüklenemiyor.");
            });

        function rollTheDice() {
            if (!mekanlar.length) {
                showError("Mekan verisi hazır değil.");
                return;
            }

            const seciliSehir = document.getElementById("sehir-secimi").value;

            let filtrelenmis = seciliSehir !== "hepsi"
                ? mekanlar.filter(function(m) { return m.sehir === seciliSehir; })
                : mekanlar;

            if (!filtrelenmis.length) {
                showError("Bu seçim için mekan bulunamadı.");
                return;
            }

            const kazanan = filtrelenmis[Math.floor(Math.random() * filtrelenmis.length)];

        document.getElementById("step-1").style.display = "none";
            document.getElementById("step-2").classList.remove("hidden");
            document.getElementById("spinner").classList.add("spin-3d");

            setTimeout(function() {
                document.getElementById("step-2").classList.add("hidden");

                const resDiv = document.getElementById("step-3");
                resDiv.classList.remove("hidden");

                setTimeout(function() {
                    resDiv.classList.remove("scale-95", "opacity-0");
                }, 50);

                const colorBox = document.getElementById("res-color-box");
                colorBox.className = "relative h-40 w-full bg-gradient-to-br " + kazanan.renk + " flex items-center justify-center";

                document.getElementById("res-ad").textContent = kazanan.ad || "Mekan";
                document.getElementById("res-sehir").textContent = kazanan.sehir || "Şehir";
                document.getElementById("res-ozet").textContent = kazanan.vibe || "Keşfedilecek bir durak.";
                document.getElementById("res-link").href = kazanan.url || "#";

                confetti({
                    particleCount: 200,
                    spread: 90,
                    origin: { y: 0.6 },
                    colors: ["#ffffff", "#a855f7", "#3b82f6"]
                });
            }, 2000);
        }
    </script>
</body>
</html>""")


CITY_PAGE_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>$sehir Mekan Rehberi | MekanZar</title>
    <meta name="description" content="$sehir içindeki cafe ve mekanları keşfet. OpenStreetMap verileriyle hazırlanmış yapay zeka destekli mekan rehberi.">
    <link rel="canonical" href="$canonical_url">

    <meta property="og:title" content="$sehir Mekan Rehberi | MekanZar">
    <meta property="og:description" content="$sehir içindeki cafe ve mekanları keşfet.">
    <meta property="og:type" content="website">
    <meta property="og:url" content="$canonical_url">
    <meta name="twitter:card" content="summary">

    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;500;700;900&display=swap" rel="stylesheet">

    <style>
        body {
            font-family: 'Outfit', sans-serif;
            background-color: #050505;
            color: #f8fafc;
        }
    </style>
</head>

<body class="min-h-screen">
    <header class="px-8 py-16 bg-gradient-to-br from-slate-900 to-black border-b border-slate-800">
        <div class="max-w-6xl mx-auto">
            <a href="/" class="text-slate-400 hover:text-white font-bold mb-8 inline-block">← Ana Sayfa</a>
            <h1 class="text-5xl md:text-7xl font-black tracking-tighter">$sehir Mekan Rehberi</h1>
            <p class="text-slate-400 mt-4 max-w-2xl">
                $sehir içindeki OpenStreetMap kaynaklı cafe ve mekan keşifleri.
            </p>
        </div>
    </header>

    <main class="max-w-6xl mx-auto px-8 py-12">
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            $cards_html
        </div>
    </main>

    <footer class="max-w-6xl mx-auto px-8 pb-12 text-xs text-slate-500 leading-relaxed">
        Mekan verileri
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer nofollow" class="underline hover:text-slate-300">
            © OpenStreetMap contributors
        </a>
        tarafından sağlanır ve ODbL lisansı kapsamındadır.
    </footer>
</body>
</html>""")


# ============================================================
# 7. SAYFA RENDER FONKSİYONLARI
# ============================================================

def render_place_page(item: dict) -> str:
    name = item["ad"]
    sehir = item["sehir"]
    filename = item["url"]
    canonical_url = f"{SITE_URL}/{filename}"

    meta_description = (
        f"{sehir} şehrindeki {name} hakkında yapay zeka destekli mekan notu. "
        f"Wi-Fi, dış mekan, harita ve konum bilgileri."
    )

    schema = {
        "@context": "https://schema.org",
        "@type": "CafeOrCoffeeShop",
        "name": name,
        "address": {
            "@type": "PostalAddress",
            "addressLocality": sehir,
            "addressCountry": "TR"
        },
        "geo": {
            "@type": "GeoCoordinates",
            "latitude": item["enlem"],
            "longitude": item["boylam"]
        },
        "url": canonical_url
    }

    schema_json = json.dumps(schema, ensure_ascii=False, indent=2).replace("</", "<\\/")

    return SEO_PAGE_TEMPLATE.substitute(
        mekan_adi=esc(name),
        sehir=esc(sehir),
        sehir_url=esc(city_page_filename(sehir)),
        meta_description=esc(meta_description),
        canonical_url=esc(canonical_url),
        schema_json=schema_json,
        renk=esc(item["renk"]),
        makale_html=item["makale_html"],
        wifi=esc(item["wifi"]),
        dis_mekan=esc(item["dis_mekan"]),
        enlem=esc(item["enlem"]),
        boylam=esc(item["boylam"])
    )


def render_city_page(sehir: str, items: list) -> str:
    cards = []

    for item in sorted(items, key=lambda x: x["ad"].lower()):
        cards.append(f"""
            <a href="{esc(item["url"])}" class="block bg-slate-900/90 border border-slate-800 rounded-3xl overflow-hidden hover:scale-[1.02] hover:border-slate-600 transition">
                <div class="h-28 bg-gradient-to-br {esc(item["renk"])} flex items-center justify-center">
                    <span class="text-4xl">📍</span>
                </div>

                <div class="p-6">
                    <div class="text-xs text-slate-500 font-bold uppercase tracking-widest mb-2">{esc(item["sehir"])}</div>
                    <h2 class="text-xl font-black text-white mb-3">{esc(item["ad"])}</h2>
                    <p class="text-slate-400 text-sm leading-relaxed">{esc(item["vibe"])}</p>
                </div>
            </a>
        """.strip())

    cards_html = "\n".join(cards) if cards else """
        <div class="col-span-full bg-slate-900 border border-slate-800 rounded-3xl p-8 text-slate-400">
            Bu şehir için henüz mekan bulunamadı.
        </div>
    """

    filename = city_page_filename(sehir)
    canonical_url = f"{SITE_URL}/{filename}"

    return CITY_PAGE_TEMPLATE.substitute(
        sehir=esc(sehir),
        canonical_url=esc(canonical_url),
        cards_html=cards_html
    )


def render_index_page(city_names: list) -> str:
    links = []

    for city in sorted(city_names):
        links.append(
            f'<a href="{esc(city_page_filename(city))}" class="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-slate-400 hover:text-white hover:bg-white/10 transition">{esc(city)}</a>'
        )

    city_links = "\n".join(links)

    return INDEX_TEMPLATE.substitute(
        site_url=esc(SITE_URL),
        city_links=city_links
    )


def create_sitemap(urls: list) -> str:
    gunun_tarihi = datetime.now().strftime("%Y-%m-%d")

    items = [
        f"<url><loc>{xml_esc(SITE_URL + '/')}</loc><lastmod>{gunun_tarihi}</lastmod></url>"
    ]

    for url in urls:
        items.append(
            f"<url><loc>{xml_esc(url)}</loc><lastmod>{gunun_tarihi}</lastmod></url>"
        )

    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        f"{''.join(items)}"
        "</urlset>"
    )


def create_robots_txt() -> str:
    return f"""User-agent: *
Allow: /

Sitemap: {SITE_URL}/sitemap.xml
"""
# ============================================================
# 8. ANA AKIŞ
# ============================================================

def run():
    logging.info("MekanRehber otomasyonu başladı.")

    model = setup_gemini_model()
    ai_cache = load_json_file(AI_CACHE_FILE, {})

    canli_veritabani = []
    sitemap_urls = []
    seen_pages = set()
    seen_osm_objects = set()

    for sehir in HEDEF_SEHIRLER:
        logging.info("%s taranıyor...", sehir)

        elements = fetch_city_cafes(sehir)
        logging.info("%s için %s mekan adayı bulundu.", sehir, len(elements))

        time.sleep(OVERPASS_DELAY_SECONDS)

        for element in elements:
            osm_type = element.get("type", "osm")
            osm_id = element.get("id")

            if osm_id is None:
                continue

            unique_osm_key = f"{osm_type}:{osm_id}"

            if unique_osm_key in seen_osm_objects:
                continue

            seen_osm_objects.add(unique_osm_key)

            tags = element.get("tags") or {}
            name = tags.get("name")

            if not name:
                continue

            enlem, boylam = get_lat_lon(element)

            if enlem is None or boylam is None:
                logging.info("Koordinat bulunamadı, atlandı: %s / %s", sehir, name)
                continue

            dosya_adi = place_page_filename(name, sehir, osm_type, osm_id)

            if dosya_adi in seen_pages:
                dosya_adi = f"{slugify(name)}-{slugify(sehir)}-{slugify(osm_type)}-{osm_id}-{random.randint(1000, 9999)}.html"

            seen_pages.add(dosya_adi)

            wifi = normalize_bool_tag(tags.get("internet_access"))
            dis_mekan = normalize_bool_tag(tags.get("outdoor_seating"))
            atanan_renk = renk_sec(name)

            logging.info("İşleniyor: %s | %s", name, sehir)

            ai_content = generate_ai_content(
                model=model,
                sehir=sehir,
                name=name,
                osm_id=osm_id,
                ai_cache=ai_cache
            )

            makale_html = paragraphs_to_html(ai_content.get("makale", ""))
            vibe_metni = str(ai_content.get("vibe", "")).strip() or f"{sehir} rotasında keşfedilebilecek bir durak."

            item = {
                "ad": name,
                "sehir": sehir,
                "url": dosya_adi,
                "vibe": vibe_metni,
                "renk": atanan_renk,
                "enlem": enlem,
                "boylam": boylam,
                "wifi": wifi,
                "dis_mekan": dis_mekan,
                "osm_type": osm_type,
                "osm_id": osm_id,
                "makale_html": makale_html
            }

            sayfa_icerigi = render_place_page(item)

            with (DIST_DIR / dosya_adi).open("w", encoding="utf-8") as f:
                f.write(sayfa_icerigi)

            public_item = {
                "ad": name,
                "sehir": sehir,
                "url": dosya_adi,
                "vibe": vibe_metni,
                "renk": atanan_renk,
                "enlem": enlem,
                "boylam": boylam,
                "wifi": wifi,
                "dis_mekan": dis_mekan,
                "osm_type": osm_type,
                "osm_id": osm_id
            }

            canli_veritabani.append(public_item)
            sitemap_urls.append(f"{SITE_URL}/{dosya_adi}")

    with (DIST_DIR / "veri.json").open("w", encoding="utf-8") as f:
        json.dump(canli_veritabani, f, ensure_ascii=False, indent=2)

    city_names = sorted(set(item["sehir"] for item in canli_veritabani))

    for city in city_names:
        city_items = [item for item in canli_veritabani if item["sehir"] == city]
        city_html = render_city_page(city, city_items)
        city_filename = city_page_filename(city)

        with (DIST_DIR / city_filename).open("w", encoding="utf-8") as f:
            f.write(city_html)

        sitemap_urls.append(f"{SITE_URL}/{city_filename}")

    index_html = render_index_page(city_names)

    with (DIST_DIR / "index.html").open("w", encoding="utf-8") as f:
        f.write(index_html)

    sitemap_xml = create_sitemap(sitemap_urls)

    with (DIST_DIR / "sitemap.xml").open("w", encoding="utf-8") as f:
        f.write(sitemap_xml)

    robots_txt = create_robots_txt()

    with (DIST_DIR / "robots.txt").open("w", encoding="utf-8") as f:
        f.write(robots_txt)

    logging.info("MESAİ BİTTİ.")
    logging.info("Toplam mekan: %s", len(canli_veritabani))
    logging.info("Çıktı klasörü: %s", DIST_DIR.resolve())


if __name__ == "__main__":
    run()
    
