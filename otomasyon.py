import os
import json
import requests
import re
import google.generativeai as genai
from datetime import datetime
import time

# ==========================================
# 1. AYARLAR VE API BAĞLANTILARI
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

os.makedirs("dist", exist_ok=True)

# Sadece 3 büyükşehri hedefliyoruz
HEDEF_SEHIRLER = ["İzmir", "İstanbul", "Ankara"]

# ==========================================
# 2. ŞABLONLAR (DİNAMİK ŞEHİR ALTYAPILI)
# ==========================================

SEO_SAYFA_SABLONU = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{mekan_adi} İncelemesi | {sehir} Mekan Rehberi</title>
    <meta name="description" content="{sehir} şehrindeki {mekan_adi} hakkında yapay zeka destekli detaylı inceleme. Priz durumu, Wi-Fi kalitesi ve genel atmosferi keşfet.">
    <link rel="canonical" href="https://mekanrehber.com/{dosya_adi}">
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;500;700;900&display=swap" rel="stylesheet">
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "CafeOrCoffeeShop",
      "name": "{mekan_adi}",
      "address": {{
        "@type": "PostalAddress",
        "addressLocality": "{sehir}",
        "addressCountry": "TR"
      }},
      "geo": {{
        "@type": "GeoCoordinates",
        "latitude": {enlem},
        "longitude": {boylam}
      }},
      "url": "https://mekanrehber.com/{dosya_adi}"
    }}
    </script>
    <style>body {{ font-family: 'Outfit', sans-serif; background-color: #0f172a; color: #f8fafc; }}</style>
</head>
<body class="p-8 max-w-4xl mx-auto">
    <a href="/" class="text-indigo-400 hover:text-pink-500 font-bold mb-8 inline-block transition">← Ana Sayfaya Dön ve Zarat</a>
    <div class="inline-block px-3 py-1 bg-slate-800 text-slate-300 rounded-full text-xs font-bold uppercase tracking-widest mb-4 border border-slate-700">📍 {sehir}</div>
    <h1 class="text-5xl font-black mb-4 bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-pink-500">{mekan_adi}</h1>
    <div class="flex gap-4 mb-8">
        <span class="bg-indigo-900 text-indigo-200 px-3 py-1 rounded-full text-sm font-bold">Wi-Fi: {wifi}</span>
        <span class="bg-pink-900 text-pink-200 px-3 py-1 rounded-full text-sm font-bold">Dış Mekan: {dis_mekan}</span>
    </div>
    <div class="prose prose-invert prose-lg max-w-none text-slate-300 leading-relaxed bg-slate-800/50 p-8 rounded-2xl border border-slate-700">
        {makale}
    </div>
    <a href="https://www.google.com/maps/search/?api=1&query={enlem},{boylam}" target="_blank" class="mt-8 block text-center bg-gradient-to-r from-indigo-600 to-pink-600 text-white font-bold py-4 rounded-xl shadow-lg hover:scale-105 transition">Google Haritalar'da Aç 🗺️</a>
</body>
</html>"""

ANA_SAYFA_SABLONU = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Türkiye Mekan Rehberi | Ne Yapsak Derdine Son!</title>
    <meta name="description" content="Türkiye'nin en iyi mekanlarını bul. Zarı at, yapay zeka senin için anında en doğru mekanı seçsin.">
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;500;700;900&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js"></script>
    <style>
        body { font-family: 'Outfit', sans-serif; background-color: #0f172a; color: #f8fafc; overflow-x: hidden; }
        .spin-3d { animation: fastSpin 2.5s cubic-bezier(0.25, 0.1, 0.25, 1) forwards; transform-style: preserve-3d; }
        @keyframes fastSpin { 0% { transform: rotateY(0deg) scale(0.8); opacity: 1; } 50% { transform: rotateY(1800deg) scale(1.1); filter: blur(2px); } 100% { transform: rotateY(3600deg) scale(1); filter: blur(0); } }
        .glass-panel { background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.1); }
        .neon-blob { position: absolute; border-radius: 50%; filter: blur(100px); z-index: -1; }
        .blob-1 { width: 400px; height: 400px; background: #6366f1; top: -100px; left: -100px; opacity: 0.4; }
        .blob-2 { width: 500px; height: 500px; background: #ec4899; bottom: -200px; right: -100px; opacity: 0.3; }
    </style>
</head>
<body class="min-h-screen flex items-center justify-center relative">
    <div class="neon-blob blob-1"></div><div class="neon-blob blob-2"></div>

    <div id="step-1" class="glass-panel p-8 md:p-12 rounded-3xl w-full max-w-xl mx-4 z-10 transition-all duration-500">
        <h1 class="text-4xl md:text-5xl font-black text-center mb-2 tracking-tight">mekan<span class="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-pink-500">zar</span>.</h1>
        <p class="text-center text-slate-400 mb-8 font-light">Kararsızlığa son. Şehrini seç, zarı at.</p>
        
        <div class="mb-8">
            <label class="block text-sm font-semibold text-slate-300 mb-3 uppercase tracking-wider">Hangi Şehirdesin?</label>
            <select id="sehir-secimi" class="w-full bg-slate-800/50 border border-slate-700 text-white rounded-xl py-4 px-4 outline-none focus:border-indigo-500 transition appearance-none">
                <option value="hepsi">Farketmez, Tüm Türkiye</option>
                </select>
        </div>

        <button onclick="rollTheDice()" class="w-full bg-gradient-to-r from-indigo-600 to-pink-600 text-white font-bold text-xl py-6 rounded-xl shadow-lg transition transform hover:-translate-y-1">🎲 Mekan Zarını At</button>
    </div>

    <div id="step-2" class="hidden z-20 absolute inset-0 flex flex-col items-center justify-center bg-slate-900/90 backdrop-blur-sm">
        <h2 class="text-3xl font-bold text-white mb-8 animate-pulse">Sistem Tarıyor...</h2>
        <div id="spinner" class="w-64 h-80 rounded-2xl bg-gradient-to-tr from-indigo-500 to-pink-500 p-1 flex items-center justify-center shadow-2xl shadow-indigo-500/50">
            <div class="w-full h-full bg-slate-900 rounded-xl flex items-center justify-center"><span class="text-7xl">❓</span></div>
        </div>
    </div>

    <div id="step-3" class="hidden glass-panel p-8 rounded-3xl w-full max-w-2xl mx-4 z-30 transform scale-95 opacity-0 transition-all duration-700">
        <button onclick="location.reload()" class="text-slate-400 hover:text-white mb-6 text-sm font-semibold">← Yeniden Zarat</button>
        <span id="res-sehir" class="inline-block px-3 py-1 bg-slate-800 text-slate-300 rounded-full text-xs font-bold uppercase tracking-widest mb-4 border border-slate-700">Şehir</span>
        <h2 id="res-ad" class="text-5xl font-black text-white mb-6">Mekan Adı</h2>
        <div class="bg-slate-800/50 p-4 rounded-xl border border-slate-700 mb-6">
            <p class="text-sm text-slate-400 mb-1">Mekan Özeti</p>
            <p id="res-ozet" class="font-bold text-white">...</p>
        </div>
        <a id="res-link" href="#" class="block w-full text-center bg-white text-slate-900 font-bold text-lg py-4 rounded-xl hover:bg-slate-200 transition">🔍 Yapay Zeka İncelemesini Oku</a>
    </div>

    <script>
        let mekanlar = [];
        
        fetch('veri.json').then(response => response.json()).then(data => { 
            mekanlar = data; 
            
            // Veritabanındaki benzersiz şehirleri bul ve dropdown'a otomatik ekle
            const sehirler = [...new Set(mekanlar.map(m => m.sehir))].sort();
            const select = document.getElementById('sehir-secimi');
            sehirler.forEach(sehir => {
                let opt = document.createElement('option');
                opt.value = sehir;
                opt.innerHTML = sehir;
                select.appendChild(opt);
            });
        });

        function rollTheDice() {
            if(mekanlar.length === 0) return alert("Veriler yükleniyor...");
            
            const seciliSehir = document.getElementById('sehir-secimi').value;
            let filtrelenmisMekanlar = mekanlar;
            
            if(seciliSehir !== 'hepsi') {
                filtrelenmisMekanlar = mekanlar.filter(m => m.sehir === seciliSehir);
            }
            
            if(filtrelenmisMekanlar.length === 0) filtrelenmisMekanlar = mekanlar;

            const kazanan = filtrelenmisMekanlar[Math.floor(Math.random() * filtrelenmisMekanlar.length)];
            
            document.getElementById('step-1').style.display = 'none';
            document.getElementById('step-2').classList.remove('hidden');
            document.getElementById('spinner').classList.add('spin-3d');

            setTimeout(() => {
                document.getElementById('step-2').classList.add('hidden');
                const resDiv = document.getElementById('step-3');
                resDiv.classList.remove('hidden');
                setTimeout(() => resDiv.classList.remove('scale-95', 'opacity-0'), 50);

                document.getElementById('res-ad').innerText = kazanan.ad;
                document.getElementById('res-sehir').innerText = "📍 " + kazanan.sehir;
                document.getElementById('res-ozet').innerText = kazanan.vibe;
                document.getElementById('res-link').href = kazanan.url;

                confetti({ particleCount: 150, spread: 80, origin: { y: 0.6 }, colors: ['#6366f1', '#ec4899', '#ffffff'] });
            }, 2500);
        }
    </script>
</body>
</html>"""

def clean_filename(name):
    name = name.lower().replace(' ', '-').replace('ı','i').replace('ğ','g').replace('ü','u').replace('ş','s').replace('ö','o').replace('ç','c')
    return re.sub(r'[^a-z0-9-]', '', name)

def run():
    print("Sistem Başlatıldı: Türkiye Geneli Veri Avı Başlıyor...")
    
    canli_veritabani = []
    sitemap_urls = []
    gunun_tarihi = datetime.now().strftime("%Y-%m-%d")
    
    # 3. ŞEHİRLER ARASINDA DÖNGÜ (Limitleri aşmamak için)
    for sehir in HEDEF_SEHIRLER:
        print(f"\n---> {sehir} şehri taranıyor...")
        
        # Her şehir için API sorgusu (Sistemi yormamak için limit şimdilik 5)
        url = "http://overpass-api.de/api/interpreter"
        query = f"""[out:json][timeout:25];area["name"="{sehir}"]->.searchArea;node["amenity"="cafe"]["name"](area.searchArea);out tags center limit 5;"""
        
        try:
            response = requests.get(url, params={'data': query})
            data = response.json()
            
            for element in data.get('elements', []):
                tags = element.get('tags', {})
                name = tags.get('name')
                if not name: continue
                
                dosya_adi = clean_filename(name) + f"-{clean_filename(sehir)}.html"
                enlem = element.get("lat", "")
                boylam = element.get("lon", "")
                wifi = tags.get("internet_access", "Bilinmiyor")
                dis_mekan = tags.get("outdoor_seating", "Bilinmiyor")
                
                print(f"İşleniyor: {name} ({sehir})")
                
                # 4. GEMINI İLE ŞEHRE ÖZEL İÇERİK
                prompt = f"{sehir} şehrindeki '{name}' adlı kafe için kısa ve etkileyici bir inceleme yazısı yaz. İçerisinde 'freelancer' veya 'öğrenci' kelimeleri geçsin. Ayrıca bu mekanın genel atmosferini tek bir cümleyle özetle. Çıktı formatı tam olarak şöyle olmalı:\nVIBE: [Tek cümlelik özet]\nMAKALE: [Yazdığın makale]"
                
                try:
                    yanit = model.generate_content(prompt).text
                    if "MAKALE:" in yanit:
                        vibe_metni = yanit.split("MAKALE:")[0].replace("VIBE:", "").strip()
                        makale_metni = yanit.split("MAKALE:")[1].strip().replace('\n', '<br><br>')
                    else:
                        vibe_metni = "Harika bir keşif noktası."
                        makale_metni = yanit.replace('\n', '<br>')
                except Exception as e:
                    vibe_metni = f"{sehir}'de popüler bir mekan."
                    makale_metni = "Yapay zeka analizimiz yakında eklenecektir."

                # Bireysel Sayfayı Oluştur
                sayfa_icerigi = SEO_SAYFA_SABLONU.format(
                    mekan_adi=name, sehir=sehir, dosya_adi=dosya_adi, wifi=wifi, dis_mekan=dis_mekan, 
                    enlem=enlem, boylam=boylam, makale=makale_metni
                )
                with open(f"dist/{dosya_adi}", "w", encoding="utf-8") as f:
                    f.write(sayfa_icerigi)

                # JSON Veritabanına Ekle
                canli_veritabani.append({
                    "ad": name,
                    "sehir": sehir,
                    "url": dosya_adi,
                    "vibe": vibe_metni
                })
                
                sitemap_urls.append(f"<url><loc>https://mekanrehber.com/{dosya_adi}</loc><lastmod>{gunun_tarihi}</lastmod><changefreq>weekly</changefreq></url>")
                
                # Gemini API limitlerine takılmamak için 2 saniye bekle
                time.sleep(2)
                
        except Exception as e:
            print(f"{sehir} çekilirken hata oluştu: {e}")

    # 5. GERÇEK ÇIKTILARI OLUŞTURMA
    with open("dist/veri.json", "w", encoding="utf-8") as f:
        json.dump(canli_veritabani, f, ensure_ascii=False, indent=2)
        
    with open("dist/index.html", "w", encoding="utf-8") as f:
        f.write(ANA_SAYFA_SABLONU)
        
    sitemap_icerigi = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://mekanrehber.com/</loc><lastmod>{gunun_tarihi}</lastmod><changefreq>daily</changefreq></url>
    {''.join(sitemap_urls)}
</urlset>"""
    with open("dist/sitemap.xml", "w", encoding="utf-8") as f:
        f.write(sitemap_icerigi)

    print("İŞLEM TAMAMLANDI! 3 Büyükşehir canlıya alınmaya hazır.")

if __name__ == "__main__":
    run()
        
