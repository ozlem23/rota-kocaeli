"""
3 Kişilik Entegrasyon Test Koşucusu
Kullanım:
    python test_all.py
Adımlar:
    1. Kişi 2 Motor Birim Testleri (pytest)
    2. Kişi 1 + Kişi 2 Uçtan Uca 20 Senaryo Doğrulaması (eval_20)
    3. Kişi 3 Streamlit UI + PyDeck Harita + Yeniden Hesaplama Uçtan Uca Testi (AppTest)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent


def _run_step(title: str, cmd: list[str]) -> None:
    print(f"\n{'=' * 60}\n▶ {title}\n{'=' * 60}")
    result = subprocess.run(cmd, cwd=ROOT_DIR)
    if result.returncode != 0:
        raise SystemExit(f"❌ Başarısız adım: {title}")


def _smoke_test_ui_and_contracts() -> None:
    print(f"\n{'=' * 60}\n▶ 3. Adım: Kişi 3 Sözleşme, Streamlit UI ve Yeniden Hesaplama Testi\n{'=' * 60}")
    from streamlit.testing.v1 import AppTest

    from contracts.models import FinalResponse
    from person3_ui.app import _build_pydeck_map

    with open(ROOT_DIR / "contracts" / "mock_final_response.json", encoding="utf-8") as f:
        mock_data = json.load(f)
    FinalResponse.model_validate(mock_data)
    _build_pydeck_map(mock_data)

    at = AppTest.from_file(str(ROOT_DIR / "person3_ui" / "app.py"), default_timeout=15)
    at.run()
    assert not at.exception, f"UI başlangıç hatası: {at.exception}"

    submit_btn = next(b for b in at.button if "Rota Oluştur" in b.label)
    submit_btn.click().run()
    assert not at.exception, f"Rota Oluştur hatası: {at.exception}"
    assert at.success, "Özet başarı mesajı oluşmadı."

    recalc_btn = next(b for b in at.button if "Yeniden Hesapla" in b.label)
    recalc_btn.click().run()
    assert not at.exception, f"Yeniden Hesapla hatası: {at.exception}"

    print("✅ Mock sözleşme, PyDeck harita, UI Rota Oluştur ve Yeniden Hesaplama testleri geçti.")


def main() -> None:
    py = sys.executable
    _run_step("1. Adım: Kişi 2 Rota Motoru Birim Testleri", [py, "-m", "pytest", "person2_engine/test_engine.py", "-v"])
    _run_step("2. Adım: Kişi 1 + Kişi 2 20 İstek Doğrulaması", [py, "-m", "person1_data_ai.eval_20"])
    _smoke_test_ui_and_contracts()
    print("\n🎉 TÜM ENTEGRASYON TESTLERİ BAŞARIYLA GEÇTİ!")
    print("Canlı arayüzü başlatmak için: streamlit run person3_ui/app.py")


if __name__ == "__main__":
    main()
