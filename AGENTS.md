# AGENTS.md — Rota Planlayıcı (3 Kişilik İzole Geliştirme Kuralları)

## Proje Özeti
**Kocaeli (İzmit)** için yürüyüş odaklı günlük gezi planı ve öğle yemeği önerisi üreten **Streamlit** web uygulaması (BTK Akademi Final Projesi).

## Kesin Teknik Kurallar
1. **Hesabı Kod Yapar, Dil Modeli Yapmaz:**
   - Ziyaret sırası, yürüme süresi, mesafe, varış/ayrılış saatleri ve açılış saati kontrolleri **yalnızca Python kodu (`person2_engine/`)** tarafından hesaplanır.
   - Dil modeli (LLM) yalnızca serbest metni JSON şemasına ayrıştırır, listeden aday mekan ID'si seçer ve kesinleşmiş planı kaynak göstererek anlatır.
2. **Uydurma ve Kapalı Mekan Yasağı:**
   - LLM veya motor `data/venues.json` dışında hiçbir mekan veya restoran üretemez.
   - Açılış saati bilinmeyen mekanlar için saat uydurulmaz; `"Açılış saati bilinmiyor"` uyarısı eklenir.
   - Ziyaret saatinde kapalı olduğu bilinen mekanlar planda bırakılmaz, çıkarılır ve uyarıya eklenir.
3. **Canlı API Kotası Koruması:**
   - Şehir verisi ve yürüme matrisi `data/` içine önceden indirilir; çalışma zamanında toplu OSM/OSRM taraması yapılmaz.
4. **Yeni Bağımlılık Kuralı:**
   - `requirements.txt` dosyasına ekibin onayı olmadan yeni paket eklenmez.

## Kod Paylaşımını Minimize Eden Klasör Sahipliği
Her ajan ve geliştirici **yalnızca kendi sorumlu olduğu klasörde** değişiklik yapar:
- `contracts/` -> İlk 20 dakikada birlikte dondurulur. Sonrasında **SALT OKUNUR**.
- `data/` -> **Yalnızca Kişi 1** günceller (`fetch_city_data.py` çıktısı).
- `person1_data_ai/` -> **Yalnızca Kişi 1** düzenler.
- `person2_engine/` -> **Yalnızca Kişi 2** düzenler.
- `person3_ui/` -> **Yalnızca Kişi 3** düzenler.

## Çalışma Biçimi
- Önce kısa plan sun, onay bekle, tek seferde tek değişiklik yap.
- Küçük aralıklarla anlamlı `git commit` at.
- Gizli anahtarları (`.env`) asla repoya gönderme; sadece `.env.example` güncelle.
