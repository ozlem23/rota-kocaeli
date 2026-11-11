"""
3 Kişilik Entegrasyon Test Koşucusu
Kullanım:
    python test_all.py
Adımlar:
    1. Kişi 2 Motor + Çok Günlü + Gün Ortası + Alternatif Plan Birim Testleri (pytest)
    2. Kişi 1 + Kişi 2 Uçtan Uca 20 Senaryo Doğrulaması (eval_20)
    3. Kişi 3 Sözleşme, Veritabanı (SQLite Hesap/Kayıt), PyDeck Harita ve Streamlit UI Uçtan Uca Testi
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent


def _run_step(title: str, cmd: list[str]) -> None:
    print(f"\n{'=' * 60}\n▶ {title}\n{'=' * 60}")
    result = subprocess.run(cmd, cwd=ROOT_DIR)
    if result.returncode != 0:
        raise SystemExit(f"❌ Başarısız adım: {title}")


def _smoke_test_storage() -> None:
    from person2_engine.service import plan_multi_day_trip
    from person3_ui import storage

    with tempfile.TemporaryDirectory() as td:
        db_file = Path(td) / "test_trips.db"
        ok, _, user = storage.register_user("test@kocaeli.edu.tr", "gizli123", "Test Kullanıcı", db_path=db_file)
        assert ok and user is not None

        ok_l, _, user_l = storage.login_user("test@kocaeli.edu.tr", "gizli123", db_path=db_file)
        assert ok_l and user_l is not None

        plans = plan_multi_day_trip("2 günlük hafta sonu turu", overrides={"num_days": 2, "accommodation_id": "hotel_sekapark"})
        plan_dicts = [p.model_dump() for p in plans]

        ok_s, _, tid = storage.save_trip(user_l, "İzmit Hafta Sonu", plan_dicts, ["seka_kagit_muzesi"], db_path=db_file)
        assert ok_s and tid is not None

        trips = storage.list_saved_trips(user_l, db_path=db_file)
        assert len(trips) == 1
        assert trips[0]["num_days"] == 2
        assert "seka_kagit_muzesi" in trips[0]["completed_stop_ids"]

        ok_d, _ = storage.delete_saved_trip(user_l, tid, db_path=db_file)
        assert ok_d and len(storage.list_saved_trips(user_l, db_path=db_file)) == 0
    print("✅ Hesap açma, giriş, gezi kaydetme, yeniden açma ve silme (storage) testleri geçti.")


def _smoke_test_ui_and_contracts() -> None:
    print(f"\n{'=' * 60}\n▶ 3. Adım: Kişi 3 Sözleşme, Depolama, PyDeck Harita ve Streamlit UI Testi\n{'=' * 60}")
    from streamlit.testing.v1 import AppTest

    from contracts.models import FinalResponse
    from person3_ui.app import _build_multi_day_pydeck_map, _build_pydeck_map

    with open(ROOT_DIR / "contracts" / "mock_final_response.json", encoding="utf-8") as f:
        mock_data = json.load(f)
    FinalResponse.model_validate(mock_data)
    _build_pydeck_map(mock_data, use_street_routing=True, travel_mode="walking")
    _build_pydeck_map(mock_data, use_street_routing=True, travel_mode="driving")
    _build_multi_day_pydeck_map([mock_data, mock_data], use_street_routing=True, travel_mode="walking")
    _build_multi_day_pydeck_map([mock_data, mock_data], use_street_routing=True, travel_mode="driving")

    _smoke_test_storage()

    at = AppTest.from_file(str(ROOT_DIR / "person3_ui" / "app.py"), default_timeout=20)
    at.run()
    assert not at.exception, f"UI başlangıç hatası: {at.exception}"

    # Rota oluştur (varsayılan: Yürüyüş Yolu)
    submit_btn = next(b for b in at.button if "Rota Oluştur" in b.label)
    submit_btn.click().run()
    assert not at.exception, f"Rota Oluştur hatası: {at.exception}"
    assert at.success, "Özet başarı mesajı oluşmadı."
    assert any("Yürüme" in m.label for m in at.metric), "Varsayılan mod Yürüyüş olmalı."

    # Google Maps tarzı Araba Yolu geçişi
    drive_btn = next(b for b in at.button if b.key == "mode_drive_day_1")
    drive_btn.click().run()
    assert not at.exception, f"Araba Yolu geçiş hatası: {at.exception}"
    assert any("Araç" in m.label for m in at.metric), "Araba modunda Araç Süresi metriği gösterilmeli."
    assert any("araç (araba)" in s.value.lower() for s in at.success), "Araba modunda özet metni güncellenmeli."

    # Tekrar Yürüyüş Yolu'na dönüş
    walk_btn = next(b for b in at.button if b.key == "mode_walk_day_1")
    walk_btn.click().run()
    assert not at.exception, f"Yürüyüş Yolu dönüş hatası: {at.exception}"
    assert any("Yürüme" in m.label for m in at.metric), "Yürüyüş moduna dönüşte Yürüme Süresi metriği görünmeli."

    # Düzenleme modunu aç ve yeniden hesapla
    at.toggle(key="edit_mode_1").set_value(True).run()
    assert not at.exception, f"Düzenleme modu hatası: {at.exception}"
    recalc_btn = next(b for b in at.button if "Yeniden Hesapla" in b.label)
    recalc_btn.click().run()
    assert not at.exception, f"Yeniden Hesapla hatası: {at.exception}"

    # Alternatif plan geri bildirimi test et
    fb_input = next(t for t in at.text_input if t.key == "feedback_box")
    fb_input.set_value("daha az müze, daha çok park")
    alt_btn = next(b for b in at.button if b.key == "btn_alt_feedback")
    alt_btn.click().run()
    assert not at.exception, f"Alternatif Plan hatası: {at.exception}"

    # Üst navigasyon barı sayfalarını test et
    for nav_key in ("top_nav_catalog", "top_nav_account", "top_nav_eval", "top_nav_planner"):
        nb = next(b for b in at.button if b.key == nav_key)
        nb.click().run()
        assert not at.exception, f"Sayfa geçiş hatası ({nav_key}): {at.exception}"

    print("✅ Sözleşme, PyDeck OSM yaya haritası, çok günlük rota, alternatif plan ve tüm UI sayfaları geçti.")


def main() -> None:
    py = sys.executable
    _run_step("1. Adım: Kişi 2 Rota Motoru Birim Testleri", [py, "-m", "pytest", "person2_engine/test_engine.py", "-v"])
    _run_step("2. Adım: Kişi 1 + Kişi 2 20 İstek Doğrulaması", [py, "-m", "person1_data_ai.eval_20"])
    _smoke_test_ui_and_contracts()
    print("\n🎉 TÜM ENTEGRASYON TESTLERİ BAŞARIYLA GEÇTİ!")
    print("Canlı arayüzü başlatmak için: streamlit run person3_ui/app.py")


if __name__ == "__main__":
    main()
