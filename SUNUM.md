# Final Projesi Sunum Rehberi: Kocaeli Rota Planlayıcı
**Ajan Tabanlı Yapay Zeka Atölyesi — 6. Gün Sunumu**
*(Slayt 16 Kurgusuna Birebir Uygun Hazırlanmıştır)*

---

## 1. Problem (Kimin İçin, Hangi Şehir?)
* **Kullanıcı:** Kocaeli (İzmit) şehir merkezini yürüyerek gezmek isteyen yerli/yabancı günübirlik ziyaretçiler.
* **Kapsam:** Kocaeli (İzmit Merkez) tarihi aksı (Eski Gar, Saat Kulesi, Kasr-ı Hümayun, Sırrı Paşa Konağı, Arkeoloji Müzesi, SEKA Kağıt Müzesi, camiler ve Sekapark sahil şeridi).
* **Temel Vaat:** En az yürüme mesafesiyle saat saat rota çıkarmak, öğle saatinde en fazla 10 dk yürüme mesafesinde mutfak tercihine uygun yemek önermek, açılışı bilinmeyen yerleri dürüstçe uyarmak ve **asla kapalı veya uydurma mekan sunmamak**.

---

## 2. Canlı Gösterim (Live Demo)

### A. Kusursuz Çalışan İstek (Temsili İstek)
> **İstek:**  
> *"Cumartesi sabah 09.30'da İzmit Eski Tren Garı'dayım, 17.00'de oraya döneceğim. Müzeleri ve tarihi yapıları görmek istiyorum. Öğlen iskender yemek molası olsun."*
* **Gözlemlenecekler:**
  1. En kısa yürüyüş sırası (Eski Gar → Arkeoloji → Seka Kağıt → Saat Kulesi → Kasr-ı Hümayun → Tarihi Bursa İskender → Sırrı Paşa → Fevziye → Eski Gar).
  2. Saat 13:26'da öğle yemeği molası ve alternatif 3 restoran seçimi (`st.radio`).
  3. Süre düzenleme (örneğin Saat Kulesi kalışını 15 dk'dan 30 dk'ya çıkarıp `Yeniden Hesapla` butonuna basılması).
  4. Durak silme (`🗑️ Çıkar`) ve gezilen yeri işaretleme (`✅ Gezdim`).

### B. Sistemin Zorlandığı İstek (Edge Case / Uç Senaryo)
> **İstek:**  
> *"Pazartesi günü 09:30 - 16:30 arası İzmit Eski Gar'dan başlayıp müzeleri ve konakları gezmek istiyorum."*
* **Sistemin Kararı:**
  * Pazartesi günü Kocaeli Arkeoloji Müzesi, SEKA Kağıt Müzesi, Kasr-ı Hümayun ve Gayret Gemi Müzesi kapalıdır.
  * Dil modeli bunları uydurmaz; rota motoru kapalı olduklarını tespit eder, rotadan çıkarır ve **"Pazartesi günü kapalı olduğu için rotaya alınmadı"** uyarısı üretir.
  * Rota yalnızca açık olan tarihi konaklar (Sırrı Paşa), açık anıtlar ve camilerle oluşturulur.

---

## 3. Mimari (Bileşenler ve Kullanılan Servisler)

| Katman | Sorumlu | Teknoloji | Görevi |
| :--- | :--- | :--- | :--- |
| **Veri Pipeline** | Kişi 1 | OpenStreetMap (`routed-foot`), Wikimedia Commons, Wikipedia TR | Gerçek yaya koordinatlı 18 mekan/otel/restoran, sokak-kıvrımlı yaya yolları (`walking_paths.json`) ve doğrulanmış fotoğraflar. |
| **İstek Ayrıştırma** | Kişi 1 | Gemini API (`gemini-3.8-flash` Pydantic `response_format`) | Serbest metni 1-3 günlük plan, başlangıç/konaklama/bitiş, saat ve geri bildirim güncellemelerine (`daha az müze`) çevirme. |
| **Optimizasyon & Motor** | Kişi 2 | Python (`permutations` + 2-opt, coğrafi gün bölümleme) | Çok günlük konaklama döngüsü, açılış saati kontrolü, 10 dk restoran filtresi ve **gün ortasında anlık konum/saatten** yeniden planlama. |
| **Arayüz, Harita & Hesap** | Kişi 3 | Streamlit + PyDeck + SQLite / Opsiyonel Supabase Auth & REST | Üst sayfa barı, görselli durak kartları, sokak-kıvrımlı OSM yaya haritası, kullanıcı hesabı, gezi kaydetme ve gezildi takibi. |

---

## 4. Sınama (20 İstek Testinin Sonucu)

`python -m person1_data_ai.eval_20` ile 20 farklı Türkçe istek otomatik denetlenmiştir:

* **Toplam Skor:** **20 / 20 Başarılı (%100 Başarı Oranı)**
* **Kontrol Kriterleri:**
  1. Başlangıç ve bitiş noktası eşleşmesi: **%100**
  2. Dönüş saatinin bitiş saatini aşmaması: **%100**
  3. Planda sıfır kapalı mekan: **%100**
  4. Planda sıfır uydurma mekan (katalog dışı): **%100**
  5. Öğle yemeği molasının istenen saatte olması: **%100**
  6. Restoranların listede olması ve `≤ 10 dk` yürüme mesafesinde bulunması: **%100**
  7. Metinde anlatılan sayıların hesaplanan sayılarla birebir tutarlılığı: **%100**

---

## 5. Agent Deneyimi (Yapay Zeka Ajanının Rolü ve Yanıldığı Yer)

### A. Ajan'a (AI Coding Assistant) Yaptırılanlar
* Projenin 3 kişilik sözleşme bazlı klasör mimarisinin kurulması (`contracts/`).
* OpenStreetMap ve Wikipedia veri çekme şablonlarının hazırlanması.
* TSP (Gezgin Satıcı) permütasyon optimizasyonu ve zaman çizelgesi simülatörünün kodlanması.
* PyDeck harita katmanları ve Streamlit arayüz bileşenlerinin geliştirilmesi.
* 20 senaryoluk otomatik test motorunun kurgulanması.

### B. Ajan'ın Yanıldığı Somut Yerler (Hata Örnekleri)
1. **Cuma / Cumartesi Regex Çakışması:** Ajan Türkçe gün eşleştirmesi yaparken `"cumartesi"` kelimesinin başında `"cuma"` alt dizgisini yakaladığı için Cumartesi gününü Cuma olarak algıladı ve Pazartesi kapalı olan mekanları Cumartesi'ye denk getirdi. (Kelime sınırı `\b` eklenerek düzeltildi).
2. **Olumsuzluk Algısı Hatası:** Kullanıcı *"yemek olmasın"* yazdığında, ajan `"yemek"` kelimesini görüp öğle molasını zorunlu kıldı. (Olumsuz kalıplar genişletilerek çözüldü).
3. **Erken Öğle Molası ve Kapalı Restoran:** Ziyaretçi az durak gezip saat 10:57'de sahile vardığında, sahil restoranı 11:30'da açıldığı için ajan *"uygun restoran bulunamadı"* uyarısı verdi. Rota motoruna öğle yemeği penceresine (12:00) kadar bekleme kuralı eklenerek sorun giderildi.
4. **Markdown HTML Girinti Hatası:** Mekan kartlarını oluştururken f-string içinde 4 boşlukluk girinti bırakılması sonucu Streamlit CommonMark motoru HTML etiketlerini (`</div>`, `<a>`) kod bloğu zannedip ekrana ham metin olarak bastı. (HTML blokları girintisiz ve temiz hale getirilerek çözüldü).
5. **Çoklu Gün Kısıtı:** İstek şeması başta tek günle sınırlandırıldığı için model iki günlük planlama yapamadı. Şemaya `num_days` ve `plan_days` alanları eklenip duraklar iki güne dengeli dağıtılarak (1. gün müzeler, 2. gün konak ve camiler) sorun çözüldü.

---

## 6. Sınırlar (Sistemin Yapamadıkları)
* **Toplu Taşıma:** Sistem yalnızca yaya rotalarını destekler; tramvay, vapur veya otobüs aktarmalarını hesaplamaz.
* **Açılış Saati Bilinmeyen Mekanlar:** OpenStreetMap üzerinde açılış saati girilmemiş tarihi çeşme, saat kulesi veya anıtlar için saat uydurulmaz; açıkça *"Açılış saati bilinmiyor"* uyarısı verilir.
* **Katalog Sınırı:** İnternetten serbest mekan araması yapılmaz; halüsinasyon riskini sıfırlamak için yalnızca doğrulanmış `venues.json` listesindeki mekanlar ve restoranlar kullanılır.

