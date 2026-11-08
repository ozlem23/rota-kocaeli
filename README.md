# Rota Planlayıcı — 3 Kişilik Hızlı Geliştirme İskeleti

Zaman kısıtlı hackathon/atölye ortamında **kod paylaşımını ve Git çakışmalarını sıfıra indirmek** için tasarlanmış 3 katmanlı proje yapısıdır.

## Klasör Sahipliği

| Klasör | Sahibi | Görevi |
| :--- | :--- | :--- |
| `contracts/` | Ortak (Salt Okunur) | Pydantic veri modelleri ve sahte (mock) JSON sözleşmeleri |
| `data/` | Kişi 1 (Üretir) / Kişi 2 (Okur) | Doğrulanmış `venues.json`, yaya (`walking_matrix.json`, `walking_paths.json`) ve araç (`driving_matrix.json`, `driving_paths.json`) ağ verileri |
| `person1_data_ai/` | **Kişi 1** | OSM/Wikimedia şehir verisi indirici, LLM ayrıştırıcı/anlatıcı, 20 istek sınaması |
| `person2_engine/` | **Kişi 2** | Yaya & araç optimizasyonu, çok günlük konaklama döngüsü, gün ortası yeniden planlama ve `service.py` |
| `person3_ui/` | **Kişi 3** | Kurumsal Streamlit arayüzü, PyDeck **🚶 Yürüyüş / 🚗 Araba** haritası ve hesap/kayıtlı geziler (`storage.py`) |

## Hızlı Kurulum (Herkes Kendi Bilgisayarında)

```bash
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env
```

## Tüm Parçaları Birlikte Test Etme (Entegrasyon)

```bash
# 1. Kişi 2 birim testleri + Kişi 1/2 20 senaryo + Kişi 3 harita/sözleşme testi (Tek komut):
python test_all.py

# 2. Tam entegre web arayüzünü başlatma:
streamlit run person3_ui/app.py
```

## Her Kişinin Bağımsız Çalıştırma Komutları

### Kişi 3 (Arayüz + Mock Modu — İlk Dakikadan Çalışır)
```bash
streamlit run person3_ui/app.py
```
> Kenar çubuğundan **"Mock (Demo) Modu"** seçiliyken Kişi 1 ve Kişi 2'yi beklemeden `contracts/mock_final_response.json` ile çalışır.

### Kişi 2 (Rota Motoru Birim Testleri)
```bash
pytest person2_engine/test_engine.py -v
```

### Kişi 1 (Veri Çekme ve 20 İstek Doğrulama)
```bash
# Şehir verisi üretmek için (örnek: İzmit veya seçilen şehir):
python -m person1_data_ai.fetch_city_data --help

# 20 istek otomatik doğrulama suite'ini çalıştırmak için:
python -m person1_data_ai.eval_20
```

## Çakışmasız Git Akışı
1. Herkes `main` dalından kendi dalını açar:
   - `git checkout -b feat/kisi1-data-ai`
   - `git checkout -b feat/kisi2-engine`
   - `git checkout -b feat/kisi3-ui`
2. Kimse diğer kişinin klasörüne dokunmaz (`contracts/` Faz 0'dan sonra kilitlidir).
3. Entegrasyonda `main` içine sırayla merge edilir -> çakışma sıfır!
