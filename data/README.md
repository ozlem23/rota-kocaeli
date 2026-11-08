# Kocaeli (İzmit) Şehir Verisi

Bu klasör çalışma zamanında API limitlerine takılmamak için önceden indirilmiş statik şehir verisini tutar.

- `venues.json`: Gezilecek noktalar, restoranlar, açılış saatleri, kategori bazlı varsayılan kalış süreleri ve Wikipedia/Wikivoyage açıklamaları.
- `walking_matrix.json`: Tüm duraklar arası yaya yürüme süresi (`duration_min`) ve mesafesi (`distance_m`).

> **Sorumlu:** Yalnızca **Kişi 1** (`person1_data_ai/fetch_city_data.py` ile günceller). Kişi 2 salt-okunur kullanır.
> Başlangıçta İzmit Merkez örnek verisi ile hazır doldurulmuştur; Kişi 1 dilerse OSM + OSRM + Wiki verisiyle genişletebilir.

