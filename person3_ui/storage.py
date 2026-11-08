"""
Kişi 3 — Kullanıcı Hesabı ve Kayıtlı Geziler Kalıcılık Katmanı (Slayt 4 & Slayt 14)
Desteklenen arka uçlar (ek kütüphane gerekmez):
1. Yerel kalıcı SQLite veritabanı (`data/rota_kocaeli.db`) — kurulumsuz çalışır.
2. Opsiyonel Supabase Auth + PostgREST API (`.env` içinde `SUPABASE_URL` ve `SUPABASE_ANON_KEY` varsa).
Not (Slayt 14 Gizlilik): Kullanıcı e-postası ve kimlik bilgileri kesinlikle LLM istemlerine gönderilmez.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT_DIR / "data" / "rota_kocaeli.db"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _supabase_config() -> Optional[Tuple[str, str]]:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if url and key:
        return url, key
    return None


def get_backend_label() -> str:
    if _supabase_config():
        return "Supabase Bulut (Auth + PostgREST)"
    return "Yerel Kalıcı Veritabanı (SQLite)"


def _hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    salt_val = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_val.encode("utf-8"),
        120_000,
    ).hex()
    return digest, salt_val


def _verify_password(password: str, stored_hash: str, salt: str) -> bool:
    candidate, _ = _hash_password(password, salt=salt)
    return hmac.compare_digest(candidate, stored_hash)


@contextmanager
def _get_conn(db_path: Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_trips (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                num_days INTEGER NOT NULL,
                summary TEXT NOT NULL,
                plan_bundle_json TEXT NOT NULL,
                completed_stop_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_session (
                slot INTEGER PRIMARY KEY CHECK (slot = 1),
                user_id TEXT,
                logged_out INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        yield conn
    finally:
        conn.close()


def set_active_session_user(
    user_id: Optional[str],
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    now_iso = _utc_now_iso()
    logged_out = 0 if user_id else 1
    with _get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_session (slot, user_id, logged_out, updated_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(slot) DO UPDATE SET
                user_id = excluded.user_id,
                logged_out = excluded.logged_out,
                updated_at = excluded.updated_at
            """,
            (user_id, logged_out, now_iso),
        )
        conn.commit()


def logout_user(db_path: Path = DEFAULT_DB_PATH) -> None:
    set_active_session_user(None, db_path=db_path)


def get_active_session_user(db_path: Path = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    with _get_conn(db_path) as conn:
        sess = conn.execute(
            "SELECT user_id, logged_out FROM app_session WHERE slot = 1"
        ).fetchone()
        if sess and sess["logged_out"] == 1:
            return None
        target_uid = sess["user_id"] if sess and sess["user_id"] else None
        if target_uid:
            row = conn.execute(
                "SELECT id, email, full_name FROM users WHERE id = ?",
                (target_uid,),
            ).fetchone()
            if row:
                return {
                    "id": row["id"],
                    "email": row["email"],
                    "full_name": row["full_name"],
                    "backend": "sqlite",
                }
        # Eğer henüz app_session kaydı yoksa ve veritabanında kullanıcı varsa son kullanıcıyı otomatik hatırla
        if sess is None:
            last_row = conn.execute(
                "SELECT id, email, full_name FROM users ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if last_row:
                conn.execute(
                    "INSERT OR REPLACE INTO app_session (slot, user_id, logged_out, updated_at) VALUES (1, ?, 0, ?)",
                    (last_row["id"], _utc_now_iso()),
                )
                conn.commit()
                return {
                    "id": last_row["id"],
                    "email": last_row["email"],
                    "full_name": last_row["full_name"],
                    "backend": "sqlite",
                }
    return None


def list_local_users(db_path: Path = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    with _get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.email, u.full_name, u.created_at,
                   COUNT(t.id) AS trip_count
            FROM users u
            LEFT JOIN saved_trips t ON t.user_id = u.id
            GROUP BY u.id
            ORDER BY u.created_at DESC
            """
        ).fetchall()
    return [
        {
            "id": r["id"],
            "email": r["email"],
            "full_name": r["full_name"],
            "created_at": r["created_at"],
            "trip_count": int(r["trip_count"] or 0),
            "backend": "sqlite",
        }
        for r in rows
    ]


def quick_login_by_id(
    user_id: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    with _get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT id, email, full_name FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return False, "Profil bulunamadı.", None
    user_obj = {
        "id": row["id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "backend": "sqlite",
    }
    set_active_session_user(row["id"], db_path=db_path)
    return True, f"Hoş geldiniz, {row['full_name']}!", user_obj


def reset_password(
    identifier: str,
    new_password: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    clean_id = identifier.strip().lower()
    if not clean_id:
        return False, "Lütfen e-posta adresinizi veya adınızı girin.", None
    if len(new_password) < 4:
        return False, "Yeni şifre en az 4 karakter olmalıdır.", None
    with _get_conn(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, email, full_name FROM users
            WHERE lower(email) = ? OR lower(full_name) = ? OR lower(substr(email, 1, instr(email, '@') - 1)) = ?
            LIMIT 1
            """,
            (clean_id, clean_id, clean_id),
        ).fetchone()
        if not row:
            return False, "Bu e-posta veya isimle kayıtlı bir profil bulunamadı.", None
        pw_hash, salt = _hash_password(new_password)
        conn.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
            (pw_hash, salt, row["id"]),
        )
        conn.commit()
    set_active_session_user(row["id"], db_path=db_path)
    return (
        True,
        f"Şifreniz güncellendi ve {row['full_name']} profiline giriş yapıldı.",
        {
            "id": row["id"],
            "email": row["email"],
            "full_name": row["full_name"],
            "backend": "sqlite",
        },
    )


def _build_trip_summary(day_plans: List[Dict[str, Any]], completed_ids: List[str]) -> str:
    total_walk = sum(int(p.get("total_walk_min", 0)) for p in day_plans)
    total_km = round(sum(float(p.get("total_walk_km", 0.0)) for p in day_plans), 2)
    poi_total = sum(
        sum(
            1
            for s in p.get("stops", [])
            if not s.get("is_start") and not s.get("is_end") and not s.get("is_lunch")
        )
        for p in day_plans
    )
    done_cnt = len(set(completed_ids))
    return f"{len(day_plans)} gün • {poi_total} durak ({done_cnt} gezildi) • {total_walk} dk / {total_km} km"


def register_user(
    email: str,
    password: str,
    full_name: str = "",
    db_path: Path = DEFAULT_DB_PATH,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    clean_email = email.strip().lower()
    clean_name = full_name.strip() or clean_email.split("@")[0]

    if not _EMAIL_RE.match(clean_email):
        return False, "Lütfen geçerli bir e-posta adresi girin.", None
    if len(password) < 6:
        return False, "Şifre en az 6 karakter olmalıdır.", None

    sb = _supabase_config()
    if sb:
        sb_url, sb_key = sb
        try:
            resp = requests.post(
                f"{sb_url}/auth/v1/signup",
                headers={"apikey": sb_key, "Content-Type": "application/json"},
                json={"email": clean_email, "password": password, "data": {"full_name": clean_name}},
                timeout=10,
            )
            data = resp.json()
            if resp.status_code in (200, 201) and data.get("user"):
                user_obj = {
                    "id": data["user"]["id"],
                    "email": clean_email,
                    "full_name": clean_name,
                    "access_token": data.get("access_token", ""),
                    "backend": "supabase",
                }
                return True, "Supabase hesabı oluşturuldu.", user_obj
            msg = data.get("msg") or data.get("error_description") or "Kayıt tamamlanamadı."
            return False, f"Supabase kayıt hatası: {msg}", None
        except Exception as e:
            return False, f"Supabase bağlantı hatası: {e}", None

    with _get_conn(db_path) as conn:
        existing = conn.execute(
            "SELECT id, email, full_name, password_hash, salt FROM users WHERE email = ?",
            (clean_email,),
        ).fetchone()
        if existing:
            if _verify_password(password, existing["password_hash"], existing["salt"]):
                set_active_session_user(existing["id"], db_path=db_path)
                return (
                    True,
                    "Mevcut hesabınıza giriş yapıldı.",
                    {
                        "id": existing["id"],
                        "email": existing["email"],
                        "full_name": existing["full_name"],
                        "backend": "sqlite",
                    },
                )
            return (
                False,
                "Bu e-posta adresi ile kayıtlı bir hesap zaten var. Giriş yapabilir veya 'Kayıtlı Profiller' bölümünden tek tıkla profilinizi açabilirsiniz.",
                None,
            )

        uid = str(uuid.uuid4())
        pw_hash, salt = _hash_password(password)
        now_iso = _utc_now_iso()
        conn.execute(
            "INSERT INTO users (id, email, full_name, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uid, clean_email, clean_name, pw_hash, salt, now_iso),
        )
        conn.commit()
    set_active_session_user(uid, db_path=db_path)
    return (
        True,
        "Hesabınız oluşturuldu ve giriş yapıldı.",
        {
            "id": uid,
            "email": clean_email,
            "full_name": clean_name,
            "backend": "sqlite",
        },
    )


def login_user(
    email: str,
    password: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    clean_id = email.strip().lower()
    if not clean_id or not password:
        return False, "E-posta/isim ve şifre boş bırakılamaz.", None

    sb = _supabase_config()
    if sb:
        sb_url, sb_key = sb
        try:
            resp = requests.post(
                f"{sb_url}/auth/v1/token?grant_type=password",
                headers={"apikey": sb_key, "Content-Type": "application/json"},
                json={"email": clean_id, "password": password},
                timeout=10,
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("user"):
                meta = data["user"].get("user_metadata", {}) or {}
                user_obj = {
                    "id": data["user"]["id"],
                    "email": clean_id,
                    "full_name": meta.get("full_name") or clean_id.split("@")[0],
                    "access_token": data.get("access_token", ""),
                    "backend": "supabase",
                }
                return True, "Supabase hesabına giriş yapıldı.", user_obj
            msg = data.get("error_description") or data.get("msg") or "Hatalı e-posta veya şifre."
            return False, f"Giriş başarısız: {msg}", None
        except Exception as e:
            return False, f"Supabase bağlantı hatası: {e}", None

    with _get_conn(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, email, full_name, password_hash, salt
            FROM users
            WHERE lower(email) = ?
               OR lower(full_name) = ?
               OR lower(substr(email, 1, instr(email, '@') - 1)) = ?
            LIMIT 1
            """,
            (clean_id, clean_id, clean_id),
        ).fetchone()
        if not row:
            return (
                False,
                "Bu e-posta veya isimle kayıtlı bir hesap bulunamadı. Üstteki 'Kayıtlı Profiller' kartından tek tıkla girebilir veya 'Yeni Hesap Oluştur' sekmesini kullanabilirsiniz.",
                None,
            )
        if not _verify_password(password, row["password_hash"], row["salt"]):
            return (
                False,
                "Şifre hatalı. Üstteki 'Kayıtlı Profiller' kartından tek tıkla profilinize girebilir veya 'Şifremi Yenile' sekmesinden yeni şifre belirleyebilirsiniz.",
                None,
            )

    set_active_session_user(row["id"], db_path=db_path)
    return (
        True,
        "Giriş başarılı.",
        {
            "id": row["id"],
            "email": row["email"],
            "full_name": row["full_name"],
            "backend": "sqlite",
        },
    )


def save_trip(
    user: Dict[str, Any],
    title: str,
    day_plans: List[Dict[str, Any]],
    completed_ids: Optional[List[str]] = None,
    trip_id: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> Tuple[bool, str, Optional[str]]:
    if not user or not user.get("id"):
        return False, "Planı kaydetmek için önce hesabınıza giriş yapın.", None
    if not day_plans:
        return False, "Kaydedilecek aktif bir rota bulunamadı.", None

    done_list = list(dict.fromkeys(completed_ids or []))
    clean_title = title.strip() or f"Kocaeli Gezi Planı ({len(day_plans)} Gün)"
    summary = _build_trip_summary(day_plans, done_list)
    bundle_str = json.dumps({"days": day_plans}, ensure_ascii=False)
    done_str = json.dumps(done_list, ensure_ascii=False)
    now_iso = _utc_now_iso()
    record_id = trip_id or str(uuid.uuid4())

    sb = _supabase_config()
    if sb and user.get("backend") == "supabase" and user.get("access_token"):
        sb_url, sb_key = sb
        headers = {
            "apikey": sb_key,
            "Authorization": f"Bearer {user['access_token']}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=representation",
        }
        payload = {
            "id": record_id,
            "user_id": user["id"],
            "title": clean_title,
            "num_days": len(day_plans),
            "summary": summary,
            "plan_bundle": {"days": day_plans},
            "completed_stop_ids": done_list,
            "updated_at": now_iso,
        }
        try:
            resp = requests.post(f"{sb_url}/rest/v1/saved_trips", headers=headers, json=payload, timeout=10)
            if resp.status_code in (200, 201):
                return True, f"Plan '{clean_title}' Supabase hesabınıza kaydedildi.", record_id
            return False, f"Supabase kaydetme hatası ({resp.status_code}): {resp.text[:160]}", None
        except Exception as e:
            return False, f"Supabase bağlantı hatası: {e}", None

    with _get_conn(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM saved_trips WHERE id = ? AND user_id = ?",
            (record_id, user["id"]),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE saved_trips
                SET title = ?, num_days = ?, summary = ?, plan_bundle_json = ?,
                    completed_stop_ids_json = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (clean_title, len(day_plans), summary, bundle_str, done_str, now_iso, record_id, user["id"]),
            )
            msg = f"Kayıtlı gezi '{clean_title}' güncellendi."
        else:
            conn.execute(
                """
                INSERT INTO saved_trips
                (id, user_id, title, num_days, summary, plan_bundle_json, completed_stop_ids_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record_id, user["id"], clean_title, len(day_plans), summary, bundle_str, done_str, now_iso, now_iso),
            )
            msg = f"Plan '{clean_title}' hesabınıza kaydedildi."
        conn.commit()
    return True, msg, record_id


def update_trip_progress(
    user: Dict[str, Any],
    trip_id: str,
    completed_ids: List[str],
    day_plans: Optional[List[Dict[str, Any]]] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> Tuple[bool, str]:
    existing = get_saved_trip(user, trip_id, db_path=db_path)
    if not existing:
        return False, "Kayıtlı gezi bulunamadı."
    target_days = day_plans if day_plans is not None else existing["day_plans"]
    ok, msg, _ = save_trip(
        user=user,
        title=existing["title"],
        day_plans=target_days,
        completed_ids=completed_ids,
        trip_id=trip_id,
        db_path=db_path,
    )
    return ok, msg


def list_saved_trips(
    user: Dict[str, Any],
    db_path: Path = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    if not user or not user.get("id"):
        return []

    sb = _supabase_config()
    if sb and user.get("backend") == "supabase" and user.get("access_token"):
        sb_url, sb_key = sb
        headers = {
            "apikey": sb_key,
            "Authorization": f"Bearer {user['access_token']}",
        }
        try:
            resp = requests.get(
                f"{sb_url}/rest/v1/saved_trips?user_id=eq.{user['id']}&order=updated_at.desc",
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                rows = resp.json()
                out = []
                for r in rows:
                    out.append(
                        {
                            "id": r["id"],
                            "title": r["title"],
                            "num_days": r.get("num_days", 1),
                            "summary": r.get("summary", ""),
                            "day_plans": (r.get("plan_bundle") or {}).get("days", []),
                            "completed_stop_ids": r.get("completed_stop_ids") or [],
                            "created_at": r.get("created_at", ""),
                            "updated_at": r.get("updated_at", ""),
                        }
                    )
                return out
        except Exception:
            return []

    with _get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, title, num_days, summary, plan_bundle_json, completed_stop_ids_json, created_at, updated_at
            FROM saved_trips
            WHERE user_id = ?
            ORDER BY updated_at DESC
            """,
            (user["id"],),
        ).fetchall()

    results: List[Dict[str, Any]] = []
    for r in rows:
        bundle = json.loads(r["plan_bundle_json"])
        completed = json.loads(r["completed_stop_ids_json"])
        results.append(
            {
                "id": r["id"],
                "title": r["title"],
                "num_days": r["num_days"],
                "summary": r["summary"],
                "day_plans": bundle.get("days", []),
                "completed_stop_ids": completed,
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
        )
    return results


def get_saved_trip(
    user: Dict[str, Any],
    trip_id: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    trips = list_saved_trips(user, db_path=db_path)
    return next((t for t in trips if t["id"] == trip_id), None)


def delete_saved_trip(
    user: Dict[str, Any],
    trip_id: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> Tuple[bool, str]:
    if not user or not user.get("id"):
        return False, "Yetkisiz işlem."

    sb = _supabase_config()
    if sb and user.get("backend") == "supabase" and user.get("access_token"):
        sb_url, sb_key = sb
        headers = {
            "apikey": sb_key,
            "Authorization": f"Bearer {user['access_token']}",
        }
        try:
            resp = requests.delete(
                f"{sb_url}/rest/v1/saved_trips?id=eq.{trip_id}&user_id=eq.{user['id']}",
                headers=headers,
                timeout=10,
            )
            if resp.status_code in (200, 204):
                return True, "Kayıtlı gezi silindi."
            return False, f"Silinemedi ({resp.status_code})."
        except Exception as e:
            return False, f"Bağlantı hatası: {e}"

    with _get_conn(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM saved_trips WHERE id = ? AND user_id = ?",
            (trip_id, user["id"]),
        )
        conn.commit()
        if cur.rowcount > 0:
            return True, "Kayıtlı gezi silindi."
    return False, "Gezi bulunamadı."
