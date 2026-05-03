import os
import json
import requests
import google.generativeai as genai

# API Ayarları
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Yeni Nesil 3D Oyunlaştırılmış HTML ve JS Şablonu
HTML_SABLONU = """<!DOCTYPE html>
<html lang="tr" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mekan Rehberi | Şansını Dene</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;700;900&display=swap" rel="stylesheet">
    <style>
        body {{ font-family: 'Plus Jakarta Sans', sans-serif; background-color: #0f172a; color: white; overflow: hidden; }}
        
        /* 3D Zar Animasyon CSS'i */
        .scene {{ width: 200px; height: 200px; perspective: 600px; margin: 0 auto; display: none; }}
        .cube {{ width: 100%; height: 100%; position: relative; transform-style: preserve-3d; animation: spin 0.8s infinite linear; }}
        .cube__face {{ position: absolute; width: 200px; height: 200px; background: rgba(99, 102, 241, 0.8); border: 2px solid #fff; box-shadow: 0 0 20px rgba(99, 102, 241, 0.5); border-radius: 20px; display: flex; align-items: center; justify-content: center; font-size: 60px; font-weight: 900; }}
        .cube__face--front  {{ transform: rotateY(  0deg) translateZ(100px); }}
        .cube__face--right  {{ transform: rotateY( 90deg) translateZ(100px); }}
        .cube__face--back   {{ transform: rotateY(180deg) translateZ(100px); }}
        .cube__face--left   {{ transform: rotateY(-90deg) translateZ(100px); }}
        .cube__face--top    {{ transform: rotateX( 90deg) translateZ(100px); }}
        .cube__face--bottom {{ transform: rotateX(-90deg) translateZ(100px); }}
        
        @keyframes spin {{ 
            0% {{ transform: translateZ(-100px) rotateX(0deg) rotateY(0deg); }}
            100% {{ transform: translateZ(-100px) rotateX(360deg) rotateY(360deg); }}
        }}

        .glow-button {{ background: linear-gradient(45deg, #4f46e5, #06b6d4); box-shadow: 0 0 30px rgba(79, 70, 229, 0.5); transition: all 0.3s; }}
        .glow-button:hover {{ transform: scale(1.05); box-shadow: 0 0 50px rgba(6, 182, 212, 0.8); }}
    </style>
</head>
<body class="flex items-center justify-center min-h-screen">

    <!-- EKRAN 1: Filtreler ve Zar Atma -->
    <div id="step-1" class="text-center w-full max-w-md p-8 relative z-10 transition-all duration-500">
        <h1 class="text-5xl font-black mb-2 tracking-tighter">mekan<span class="text-indigo-500">rehber</span>.</h1>
        <p class="text-slate-400 mb-10">Bugün ne arıyorsun? Seç ve zarı at.</p>
        
        <div class="space-y-4 mb-10 text-left">
            <div>
                <label class="block text-sm font-bold text-slate-300 mb-2">Bölge Seç</label>
                <select id="bolge" class="w-full bg-slate-800 border border-slate-700 rounded-xl p-4 text-white focus:outline-none focus:border-indigo-500">
                    <option value="all">Farketmez, şaşırt beni</option>
                    <option value="Alsancak">Alsancak</option>
                    <option value="Bornova">Bornova</option>
                    <option value="Karşıyaka">Karşıyaka</option>
                </select>
            </div>
            <div>
                <label class="block text-sm font-bold text-slate-300 mb-2">Modun Ne?</label>
                <select id="mod" class="w-full bg-slate-800 border border-slate-700 rounded-xl p-4 text-white focus:outline-none focus:border-indigo-500">
                    <option value="all">Sadece güzel bir yer</option>
                    <option value="calisma">Bilgisayarla Çalışmalık (Wi-Fi)</option>
                    <option value="acikhava">Açık Hava / Teras</option>
                </select>
            </div>
        </div>
        
        <button onclick="zariAt()" class="glow-button w-full py-5 rounded-2xl text-xl font-black uppercase tracking-widest text-white">
            Şanslı Zarı At 🎲
        </button>
    </div>

    <!-- EKRAN 2: 3D Animasyon -->
    <div id="step-2" class="scene fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2">
        <div class="cube">
            <div class="cube__face cube__face--front">?</div>
            <div class="cube__face cube__face--back">?</div>
            <div class="cube__face cube__face--right">?</div>
            <div class="cube__face cube__face--left">?</div>
            <div class="cube__face cube__face--top">?</div>
            <div class="cube__face cube__face--bottom">?</div>
        </div>
        <p class="text-center mt-64 font-bold text-indigo-400 animate-pulse text-xl">Senin için seçiliyor...</p>
    </div>

    <!-- EKRAN 3: Sonuç Kartı -->
    <div id="step-3" class="hidden w-full max-w-lg p-6 relative z-10">
        <div class="bg-slate-800/80 backdrop-blur-xl border border-slate-700 p-8 rounded-3xl shadow-2xl relative">
            <div class="absolute -top-6 -right-6 text-6xl">🎯</div>
            <h2 id="sonuc-isim" class="text-4xl font-black mb-4 text-white"></h2>
            
            <div class="flex gap-2 mb-6" id="sonuc-etiketler">
                <!-- Etiketler JS ile dolacak -->
            </div>
            
            <div class="prose prose-invert prose-slate mb-8" id="sonuc-makale"></div>
            
            <a id="sonuc-harita" href="#" target="_blank" class="block w-full bg-indigo-600 hover:bg-indigo-500 text-center py-4 rounded-xl font-bold mb-3 transition">Haritada Git</a>
            <button onclick="basaDon()" class="block w-full bg-transparent border border-slate-600 hover:bg-slate-700 text-center py-4 rounded-xl font-bold transition text-slate-300">Başka Bir Yer Bul</button>
        </div>
    </div>

    <!-- SİSTEMİN BEYNİ: Mekan Veritabanı (Python burayı dolduracak) -->
    <script>
        const mekanlar = {mekan_verisi_json};

        function zariAt() {{
            // 1. Filtreleri al
            const secilenBolge = document.getElementById('bolge').value;
            const secilenMod = document.getElementById('mod').value;

            // 2. Mekanları filtrele
            let uygunMekanlar = mekanlar;
            
            if (secilenMod === 'calisma') {{
                uygunMekanlar = uygunMekanlar.filter(m => m.wifi === 'yes' || m.wifi === 'wlan');
            }} else if (secilenMod === 'acikhava') {{
                uygunMekanlar = uygunMekanlar.filter(m => m.dis_mekan === 'yes');
            }}

            if (uygunMekanlar.length === 0) {{
                alert("Bu filtrelere uygun mekan bulamadık, zarı tekrar at!");
                return;
            }}

            // 3. Rastgele mekan seç
            const rastgeleIndex = Math.floor(Math.random() * uygunMekanlar.length);
            const secilenMekan = uygunMekanlar[rastgeleIndex];

            // 4. Ekran geçişleri ve Animasyon
            document.getElementById('step-1').style.display = 'none';
            document.getElementById('step-2').style.display = 'block';

            // 3 saniye zar dönsün, sonra sonucu göster
            setTimeout(() => {{
                document.getElementById('step-2').style.display = 'none';
                gosterSonuc(secilenMekan);
            }}, 3000);
        }}

        function gosterSonuc(mekan) {{
            document.getElementById('sonuc-isim').innerText = mekan.isim;
            document.getElementById('sonuc-makale').innerHTML = mekan.makale;
            document.getElementById('sonuc-harita').href = `https://www.google.com/maps/search/?api=1&query=${{mekan.enlem}},${{mekan.boylam}}`;
            
            let etiketlerHTML = '';
            if(mekan.wifi === 'yes' || mekan.wifi === 'wlan') etiketlerHTML += '<span class="bg-blue-900/50 text-blue-300 px-3 py-1 rounded-full text-xs font-bold border border-blue-700/50">💻 Wi-Fi Var</span>';
            if(mekan.dis_mekan === 'yes') etiketlerHTML += '<span class="bg-green-900/50 text-green-300 px-3 py-1 rounded-full text-xs font-bold border border-green-700/50">🌿 Dış Mekan</span>';
            
            document.getElementById('sonuc-etiketler').innerHTML = etiketlerHTML || '<span class="bg-slate-700 px-3 py-1 rounded-full text-xs font-bold">Keşfetmeye Değer</span>';
            
            document.getElementById('step-3').style.display = 'block';
        }}

        function basaDon() {{
            document.getElementById('step-3').style.display = 'none';
            document.getElementById('step-1').style.display = 'block';
        }}
    </script>
</body>
</html>"""

def run():
    print("Oyunlaştırılmış Sistem Başlatıldı...")
    os.makedirs("dist", exist_ok=True)
    
    url = "http://overpass-api.de/api/interpreter"
    query = """[out:json][timeout:25];area["name"="İzmir"]->.searchArea;node["amenity"="cafe"](area.searchArea);out tags limit 10;"""
    
    response = requests.get(url, params={'data': query})
    data = response.json()
    
    mekan_listesi = []
    
    for element in data.get('elements', []):
        tags = element.get('tags', {})
        name = tags.get('name')
        if not name: continue
        
        print(f"İşleniyor: {name}")
        wifi = tags.get("internet_access", "no")
        dis_mekan = tags.get("outdoor_seating", "no")
        
        prompt = f"İzmir'deki '{name}' adlı mekan için enerjik, modern ve kullanıcıya doğrudan hitap eden ('Burası tam sana göre!' gibi) 100 kelimelik heyecan verici bir sonuç yazısı yaz."
        try:
            makale_yaniti = model.generate_content(prompt)
            makale_metni = makale_yaniti.text.replace('\n', '<br>')
        except:
            makale_metni = "Bu mekan sırrını koruyor, git ve kendin keşfet!"
            
        mekan_listesi.append({
            "isim": name,
            "enlem": element.get("lat"),
            "boylam": element.get("lon"),
            "wifi": wifi.lower(),
            "dis_mekan": dis_mekan.lower(),
            "makale": makale_metni
        })

    # Veriyi JSON formatına çevir ve HTML şablonunun içine göm
    json_verisi = json.dumps(mekan_listesi, ensure_ascii=False)
    final_html = HTML_SABLONU.replace("{mekan_verisi_json}", json_verisi)
    
    # Tek bir index.html oluştur (Tüm site bu dosyadan ibaret)
    with open("dist/index.html", "w", encoding="utf-8") as f:
        f.write(final_html)
        
    print("Oyunlaştırılmış index.html üretildi ve yayına hazır!")

if __name__ == "__main__":
    run()
