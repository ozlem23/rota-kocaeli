# 🗺️ Rota Kocaeli — Akıllı Şehir ve Gezi Planlayıcısı

**Rota Kocaeli**, Kocaeli (İzmit) genelinde tarihi mekanlar, müzeler, parklar ve yerel lezzet durakları için **gerçek sokak mesafelerine dayalı, kişiselleştirilebilir günlük gezi rotaları** oluşturan bir web uygulamasıdır.

Serbest metinle yazdığınız bir gezi isteğini ("Cumartesi sabah Gar'dan başlayıp müzeleri gezelim, öğlen köfte yiyelim") saniyeler içinde süreleri, durak sıralaması ve haritasıyla eksiksiz bir seyahat planına dönüştürür.

---

## ✨ Öne Çıkan Özellikler

* **🧭 Gerçekçi Rota Optimizasyonu:** Ziyaret sırası, yürüme/araç süreleri ve mesafeler OpenStreetMap ağ verileri üzerinden deterministik algoritmalarla hesaplanır; tahmini veya uydurma süreler üretilmez.
* **🕒 Açılış Saati ve Gün Denetimi:** Mekanların açık ve kapalı olduğu saatler otomatik kontrol edilir. Örneğin Pazartesi günleri kapalı olan müzeler plana alınmaz ve kullanıcıya açıkça bildirilir.
* **🍽️ Entegre Öğle Yemeği:** Günün akışına ve saatine göre rotaya en uygun İzmit lezzet durakları (tarihi köfteciler, balık restoranları, simit ve tatlı durakları) plana dahil edilir.
* **🏨 Çok Günlük Seyahat Planlama:** 1, 2 veya 3 günlük gezilerde konaklama noktanızı (otel vb.) baz alarak her gün için dengeli başlangıç ve dönüş rotaları kurgular.
* **🏛️ Sanal Müze & Kültür Keşfi:** Kasr-ı Hümayun (Av Köşkü), Kocaeli Arkeoloji Müzesi, SEKA Kağıt Müzesi ve TCG Gayret Gemi Müzesi için 360° sanal turlar, tarihi koleksiyon bilgileri ve tek tıkla rotaya ekleme desteği sunar.
* **🗺️ İnteraktif Harita:** PyDeck altyapısıyla yaya kaldırımlarını ve araç yollarını gösteren harita, durak sıralaması ve gün bazlı renk kodlaması içerir.
* **✏️ Canlı Düzenleme ve İlerleme Takibi:** Durakların kalış sürelerini değiştirebilir, durak çıkarabilir, gezilen yerleri işaretleyebilir ve gezinizi profilinize kaydedebilirsiniz.

---

## 🛠️ Nasıl Çalışır?

Proje **"Hesabı Kod Yapar, Dil Modeli Destekler"** mimari prensibiyle geliştirilmiştir:

1. **İstek Çözümleme:** Kullanıcının yazdığı serbest istek metni (isteğe bağlı Gemini API veya yerel kural tabanlı ayrıştırıcı ile) başlangıç noktası, gün, saat ve ilgi alanlarına ayrıştırılır.
2. **Rota Motoru:** Gerçek mesafe matrisleri üzerinden gezgin satıcı / en kısa yol algoritmaları çalıştırılır; açılış saatleri ve öğle yemeği penceresi matematiksel olarak hesaplanır.
3. **Yedekli Yapı:** Harici bir API anahtarı (`GEMINI_API_KEY`) olmasa bile uygulama kural tabanlı motoruyla %100 işlevsel olarak çalışmaya devam eder.

---

## 🚀 Hızlı Kurulum

### 1. Depoyu Klonlayın
```bash
git clone https://github.com/ozlem23/rota-kocaeli.git
cd rota-kocaeli
```

### 2. Sanal Ortamı Oluşturun ve Paketleri Yükleyin
```bash
python -m venv .venv

# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1

# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Uygulamayı Başlatın
```bash
streamlit run person3_ui/app.py
```
Tarayıcınızda otomatik olarak `http://localhost:8501` adresi açılacaktır.

---

## ⚙️ Yapılandırma (İsteğe Bağlı)

Uygulama herhangi bir API anahtarı girmeden doğrudan çalışır. Gelişmiş dil modeli özelliklerini (doğal dil serbest metin çözümleme ve zenginleştirilmiş anlatım) aktif etmek isterseniz ana dizinde `.env` dosyası oluşturabilirsiniz:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

---

## 🧪 Testleri Çalıştırma

Tüm rota hesaplama motorunu, açılış saati denetimlerini ve arayüz testlerini tek komutla çalıştırabilirsiniz:

```bash
python test_all.py
```

---

## 🧰 Kullanılan Teknolojiler

* **Arayüz:** Streamlit, PyDeck, Custom CSS
* **Veri & Coğrafi Modelleme:** OpenStreetMap, OSRM, Wikimedia Commons
* **Backend & Tip Güvenliği:** Python 3.10+, Pydantic v2, SQLite
* **Yapay Zeka Entegrasyonu:** Google GenAI SDK (Gemini 2.5 Flash / Kural tabanlı hibrit mimari)
